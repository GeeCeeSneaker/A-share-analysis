"""Provider-Normalization execution runner (CR-2, audit 20260831).

The ONE formal normalization boundary::

    persisted Raw evidence (.meta.json + payload bytes)
      -> closure verification (verified reader, no re-call of the SDK)
      -> static registry lookup (exact dataset+endpoint routing)
      -> provider-faithful row / whole-payload mapping
      -> immutable normalized parquet artifacts + manifest
      -> first-class quarantine records (append-only)
      -> meta_provider_normalization_run ledger row

Machine-enforced invariants (audit sections 5-6):

- P0-01 the runner NEVER calls the provider/SDK - its only input is
  the persisted raw evidence, read through the verified RawWriter
  reader (``read(verify=True)``);
- P0-03 normalized output is a FIRST-CLASS immutable persisted
  artifact (parquet per output table + manifest), never memory-only;
- P0-04 row-scope accounting ``input == normalized + quarantined`` is
  checked by the runtime itself - a silent drop fails the run;
- P0-05 quarantine records are first-class persisted evidence with
  scrubbed structured error context;
- P0-06 every quarantine carries the deterministic raw locator
  (request id / table / row ordinal);
- P0-07 the run id and artifact URIs are derived deterministically
  from (raw evidence hash + contract version + mapper identity): a
  replay of the same inputs is an idempotent no-op returning the
  existing run; conflicting raw evidence bytes for the same request
  BLOCK;
- P0-08 error classes separate provider failures from mapping
  failures;
- P0-10 the run status machine is SUCCESS / PARTIAL / BLOCKED with
  PARTIAL permitted only where the static registry allows it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.normalization.registry import (
    NORMALIZATION_CONTRACT_VERSION,
    DatasetNormalizationSpec,
    NormalizationErrorClass,
    NormalizationRunStatus,
    QuarantineScope,
    SurfaceSupport,
    lookup_spec,
    mapper_identity_for,
)
from ashare_state.providers.errors import MappingValidationError
from ashare_state.storage.paths import physical_from_logical_uri, validate_logical_uri
from ashare_state.storage.raw_writer import (
    KIND_EMPTY,
    KIND_MULTI_FRAMES,
    KIND_MULTI_ROWS,
    RawWriter,
    RawWriterError,
    verify_meta_closure,
)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

__all__ = [
    "NormalizationRunner",
    "NormalizationRunnerError",
    "NormalizationRunResult",
]

#: uuid namespace for deterministic run ids (same inputs -> same id)
_RUN_NAMESPACE = uuid.UUID("6f1c2b9a-4d3e-5f8a-9b7c-1e2d3c4b5a60")

_SECRET_MARKERS = ("password", "token", "secret", "credential")


class NormalizationRunnerError(RuntimeError):
    """The normalization boundary contract was violated (caller misuse
    or unrecoverable input state - e.g. the raw meta does not exist at
    all, so no evidence-bound run can even be recorded)."""


@dataclass(frozen=True)
class NormalizationRunResult:
    normalization_run_id: str
    provider: str
    provider_dataset: str
    raw_request_id: str
    status: str
    error_class: str | None
    error_message: str | None
    input_count: int
    normalized_count: int
    quarantined_count: int
    manifest_uri: str | None
    manifest_hash: str | None
    idempotent_replay: bool


def _scrub_context(value: Any) -> Any:
    """Recursively drop secret-bearing keys from a quarantine error
    context (CR2-P0-05: quarantine must never leak credentials)."""
    if isinstance(value, dict):
        return {
            str(k): (
                "[REDACTED]"
                if any(m in str(k).lower() for m in _SECRET_MARKERS)
                else _scrub_context(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_context(v) for v in value]
    return value


def _dto_row(dto: Any) -> dict[str, Any]:
    """Serialize one DTO into a parquet-ready row dict (dates -> ISO
    strings; nested dict fields stay JSON-able)."""
    if is_dataclass(dto) and not isinstance(dto, type):
        doc = asdict(dto)
    else:
        doc = dict(dto)
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if isinstance(value, date):
            out[str(key)] = value.isoformat()
        elif isinstance(value, dict):
            out[str(key)] = json.dumps(value, sort_keys=True, ensure_ascii=False)
        else:
            out[str(key)] = value
    return out


def _canonical_semantic_hash(rows_by_output: dict[str, list[dict[str, Any]]]) -> str:
    """Deterministic semantic identity of the normalized records
    (sorted canonical JSON over ALL output tables) - the replay
    comparison ignores wall-clock and parquet-level metadata."""
    payload = {
        output: sorted(
            (json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) for row in rows),
        )
        for output, rows in rows_by_output.items()
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_component(value: str, label: str) -> None:
    """A path component of the normalized artifact URI must be a safe
    single segment - '/', '\\', '..', ':' or empty values can only come
    from a caller trying to escape the confinement root."""
    text = str(value)
    if (
        not text
        or "/" in text
        or "\\" in text
        or ".." in text
        or ":" in text
        or text != text.strip()
    ):
        msg = (
            f"unsafe {label} component {value!r}: normalized artifact paths "
            "are confined logical URIs (CR-2 P0-03 / frozen P0-4)"
        )
        raise NormalizationRunnerError(msg)


class NormalizationRunner:
    """CR-2 P0-01: the formal normalization runtime. Inputs are the
    persisted raw evidence + the static registry ONLY - there is no
    provider/SDK access anywhere in this class."""

    def __init__(
        self,
        conn: DuckDBPyConnection,
        *,
        raw_root: Path | str,
        normalized_root: Path | str,
        code_commit: str = "",
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
        self.code_commit = code_commit
        # the verified reader is the EXISTING RawWriter read path
        self._reader = RawWriter(self.raw_root)

    # ---------------------------------------------------------------- api
    def run(
        self,
        *,
        provider: str = "amazingdata",
        provider_dataset: str,
        request_id: str,
    ) -> NormalizationRunResult:
        started = datetime.now(UTC)
        _validate_component(provider, "provider")
        _validate_component(provider_dataset, "provider_dataset")
        _validate_component(request_id, "request_id")
        dataset_dir = self.raw_root / f"provider={provider}" / f"dataset={provider_dataset}"
        meta_path = dataset_dir / f"{request_id}.meta.json"
        if not meta_path.is_file():
            # no evidence at all: nothing to bind a run to - caller misuse
            msg = (
                f"no raw meta for request {request_id!r} under {dataset_dir} - "
                "normalization consumes PERSISTED raw evidence only (CR-2 P0-01)"
            )
            raise NormalizationRunnerError(msg)
        raw_evidence_bytes = meta_path.read_bytes()
        raw_evidence_hash = hashlib.sha256(raw_evidence_bytes).hexdigest()
        raw_evidence_uri = f"provider={provider}/dataset={provider_dataset}/{request_id}.meta.json"
        validate_logical_uri(raw_evidence_uri)  # defense in depth

        try:
            meta_doc = json.loads(raw_evidence_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=None,
                endpoint=None,
                error_class=NormalizationErrorClass.RAW_EVIDENCE_INVALID,
                error_message=f"raw meta unreadable: {exc}",
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
            )

        endpoint = str(meta_doc.get("endpoint") or "")
        payload_kind = str(meta_doc.get("payload_kind") or "")

        # ---------------------------------------------------- idempotency
        prior = self.conn.execute(
            "SELECT normalization_run_id, raw_evidence_hash, idempotency_key "
            "FROM meta_provider_normalization_run "
            "WHERE provider = ? AND provider_dataset = ? AND raw_request_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            [provider, provider_dataset, request_id],
        ).fetchone()
        if prior is not None and str(prior[1]) != raw_evidence_hash:
            # same request id, DIFFERENT raw evidence bytes: the immutable
            # raw store itself should have prevented this - fail closed
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                error_class=NormalizationErrorClass.RAW_EVIDENCE_INVALID,
                error_message=(
                    "conflicting raw evidence bytes for the same request id "
                    f"(existing run {str(prior[0])} bound hash {str(prior[1])[:16]}... "
                    f"!= current {raw_evidence_hash[:16]}...) - the raw store is "
                    "immutable; investigate before normalizing"
                ),
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
            )

        # -------------------------------------------- closure verification
        problems = verify_meta_closure(dataset_dir, meta_doc)
        if problems:
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                error_class=NormalizationErrorClass.RAW_EVIDENCE_INVALID,
                error_message=f"raw evidence closure failed: {'; '.join(problems)}",
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
            )

        # ------------------------------------ source exchange failed check
        if str(meta_doc.get("status") or "OK") == "ERROR":
            # a FAILED provider exchange is NOT a mapping failure: record
            # SOURCE_EXCHANGE_FAILED and keep the raw failure evidence -
            # it never enters the normalized main output
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                error_class=NormalizationErrorClass.SOURCE_EXCHANGE_FAILED,
                error_message=(
                    f"source exchange failed ({meta_doc.get('error_class')}) - "
                    "the raw failure evidence is preserved; a failed exchange "
                    "is not normalizable data"
                ),
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
            )

        # ------------------------------------------------ registry routing
        spec = lookup_spec(provider_dataset, endpoint)
        if spec is None or spec.support is not SurfaceSupport.SUPPORTED_NORMALIZATION:
            if spec is not None and spec.support is SurfaceSupport.BLOCKED_PENDING_MAPPER:
                detail = (
                    f"surface {provider_dataset}/{endpoint} is BLOCKED_PENDING_MAPPER "
                    f"(mapper {spec.mapper_version!r}) - no verified mapper exists yet; "
                    "normalization fails closed, it never silently skips"
                )
            elif spec is not None:
                detail = (
                    f"surface {provider_dataset}/{endpoint} is classified "
                    f"{spec.support.value} - not a normalization input"
                )
            else:
                detail = (
                    f"no registry entry for surface {provider_dataset}/{endpoint} - "
                    "unknown surfaces fail closed (never take-first-table or "
                    "fuzzy routing)"
                )
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                error_class=NormalizationErrorClass.PAYLOAD_SHAPE_UNSUPPORTED,
                error_message=detail,
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
            )

        mapper_identity = mapper_identity_for(spec)
        idempotency_key = hashlib.sha256(
            "|".join(
                (
                    raw_evidence_hash,
                    NORMALIZATION_CONTRACT_VERSION,
                    mapper_identity,
                )
            ).encode("utf-8")
        ).hexdigest()

        # ---------------------------------------- idempotent replay return
        if prior is not None and str(prior[2]) == idempotency_key:
            existing = self.conn.execute(
                "SELECT normalization_run_id, status, error_class, error_message, "
                "input_count, normalized_count, quarantined_count, "
                "normalized_manifest_uri, normalized_manifest_hash "
                "FROM meta_provider_normalization_run "
                "WHERE normalization_run_id = ?",
                [str(prior[0])],
            ).fetchone()
            if existing is not None:
                return NormalizationRunResult(
                    normalization_run_id=str(existing[0]),
                    provider=provider,
                    provider_dataset=provider_dataset,
                    raw_request_id=request_id,
                    status=str(existing[1]),
                    error_class=str(existing[2]) if existing[2] is not None else None,
                    error_message=str(existing[3]) if existing[3] is not None else None,
                    input_count=int(existing[4]),
                    normalized_count=int(existing[5]),
                    quarantined_count=int(existing[6]),
                    manifest_uri=str(existing[7]) if existing[7] is not None else None,
                    manifest_hash=str(existing[8]) if existing[8] is not None else None,
                    idempotent_replay=True,
                )

        # ------------------------------------- verified payload read (P0-01)
        try:
            payload = self._reader.read(
                provider=provider, dataset=provider_dataset, request_id=request_id, verify=True
            )
        except RawWriterError as exc:
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                error_class=NormalizationErrorClass.RAW_EVIDENCE_INVALID,
                error_message=f"verified raw read failed: {exc}",
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
                spec=spec,
            )

        # ------------------------------------------ frame / table routing
        raw_table_name: str | None = None
        if isinstance(payload, dict):
            # multi-table payload: exact table routing only (P0-06)
            if spec.source_table is None or spec.source_table not in payload:
                names = sorted(payload.keys())
                detail = (
                    f"multi-table raw payload for {provider_dataset}/{endpoint} but "
                    f"the spec routes no exact source table (payload tables: {names}) "
                    "- taking the first table is forbidden (CR-2 P0-06)"
                )
                return self._blocked_run(
                    provider=provider,
                    provider_dataset=provider_dataset,
                    request_id=request_id,
                    raw_evidence_uri=raw_evidence_uri,
                    raw_evidence_hash=raw_evidence_hash,
                    raw_payload_kind=payload_kind,
                    endpoint=endpoint,
                    error_class=NormalizationErrorClass.PAYLOAD_SHAPE_UNSUPPORTED,
                    error_message=detail,
                    started=started,
                    input_count=0,
                    normalized_count=0,
                    quarantined_count=0,
                    manifest_uri=None,
                    manifest_hash=None,
                    quarantines=[],
                    spec=spec,
                )
            raw_table_name = spec.source_table
            frame = payload[spec.source_table]
        else:
            frame = payload

        rows: list[dict[str, Any]] = (
            frame.iter_rows(named=True) if hasattr(frame, "iter_rows") else []
        )
        row_list = list(rows)
        input_count = len(row_list)

        # ------------------------------------------------------ mapping
        normalized: dict[str, list[dict[str, Any]]] = {name: [] for name in spec.output_names}
        quarantines: list[dict[str, Any]] = []
        internal_errors = 0
        mapped_rows = 0

        if spec.quarantine_scope is QuarantineScope.WHOLE_PAYLOAD:
            values = [row.get("value") for row in row_list]
            assert spec.map_payload is not None
            try:
                dto = spec.map_payload(values, dict(meta_doc.get("request_params") or {}))
                normalized["main"] = [_dto_row(dto)]
                mapped_rows = input_count
            except MappingValidationError as exc:
                quarantines.append(
                    self._quarantine_record(
                        run_id_placeholder=None,
                        provider=provider,
                        provider_dataset=provider_dataset,
                        request_id=request_id,
                        raw_evidence_uri=raw_evidence_uri,
                        raw_evidence_hash=raw_evidence_hash,
                        raw_table_name=raw_table_name,
                        raw_row_ordinal=None,
                        source_key=None,
                        scope=QuarantineScope.WHOLE_PAYLOAD,
                        error_class=NormalizationErrorClass.MAPPING_VALIDATION_FAILED,
                        message=str(exc),
                        context=getattr(exc, "context", None),
                        mapper_identity=mapper_identity,
                    )
                )
        else:
            assert spec.map_row is not None
            for ordinal, row in enumerate(row_list):
                try:
                    outputs = spec.map_row(dict(row))
                    for output_name, dto in outputs.items():
                        normalized.setdefault(output_name, []).append(_dto_row(dto))
                    mapped_rows += 1
                except MappingValidationError as exc:
                    quarantines.append(
                        self._quarantine_record(
                            run_id_placeholder=None,
                            provider=provider,
                            provider_dataset=provider_dataset,
                            request_id=request_id,
                            raw_evidence_uri=raw_evidence_uri,
                            raw_evidence_hash=raw_evidence_hash,
                            raw_table_name=raw_table_name,
                            raw_row_ordinal=ordinal,
                            source_key=self._source_key_of(row),
                            scope=QuarantineScope.ROW,
                            error_class=NormalizationErrorClass.MAPPING_VALIDATION_FAILED,
                            message=str(exc),
                            context=getattr(exc, "context", None),
                            mapper_identity=mapper_identity,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
                    quarantines.append(
                        self._quarantine_record(
                            run_id_placeholder=None,
                            provider=provider,
                            provider_dataset=provider_dataset,
                            request_id=request_id,
                            raw_evidence_uri=raw_evidence_uri,
                            raw_evidence_hash=raw_evidence_hash,
                            raw_table_name=raw_table_name,
                            raw_row_ordinal=ordinal,
                            source_key=self._source_key_of(row),
                            scope=QuarantineScope.ROW,
                            error_class=NormalizationErrorClass.NORMALIZATION_INTERNAL_ERROR,
                            message=f"{type(exc).__name__}: {exc}"[:500],
                            context=None,
                            mapper_identity=mapper_identity,
                        )
                    )
                    internal_errors += 1

        # ------------------------------- accounting invariant (P0-04)
        if spec.quarantine_scope is QuarantineScope.ROW:
            accounted = mapped_rows + len(quarantines)
            if accounted != input_count:
                # a runner/mapper bug: rows vanished without quarantine -
                # this is a contract violation, fail the run BLOCKED
                return self._blocked_run(
                    provider=provider,
                    provider_dataset=provider_dataset,
                    request_id=request_id,
                    raw_evidence_uri=raw_evidence_uri,
                    raw_evidence_hash=raw_evidence_hash,
                    raw_payload_kind=payload_kind,
                    endpoint=endpoint,
                    error_class=NormalizationErrorClass.NORMALIZATION_INTERNAL_ERROR,
                    error_message=(
                        f"no-silent-drop accounting violated: input {input_count} != "
                        f"mapped {mapped_rows} + quarantined {len(quarantines)} "
                        "(rows vanished without quarantine evidence)"
                    ),
                    started=started,
                    input_count=input_count,
                    normalized_count=mapped_rows,
                    quarantined_count=len(quarantines),
                    manifest_uri=None,
                    manifest_hash=None,
                    quarantines=quarantines,
                    spec=spec,
                    idempotency_key=idempotency_key,
                )

        # ------------------------------------------------------- status
        if internal_errors:
            status = NormalizationRunStatus.BLOCKED
            error_class: str | None = NormalizationErrorClass.NORMALIZATION_INTERNAL_ERROR
            error_message = f"{internal_errors} mapper internal error(s) quarantined"
        elif quarantines and spec.quarantine_scope is QuarantineScope.WHOLE_PAYLOAD:
            status = NormalizationRunStatus.BLOCKED
            error_class = NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            error_message = "whole payload quarantined - zero normalized output"
        elif quarantines and not spec.allow_partial:
            status = NormalizationRunStatus.BLOCKED
            error_class = NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            error_message = (
                f"{len(quarantines)} row(s) quarantined and PARTIAL is not "
                f"allowed for {provider_dataset}/{endpoint}"
            )
        elif quarantines:
            status = NormalizationRunStatus.PARTIAL
            error_class = NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            error_message = f"{len(quarantines)} row(s) quarantined; good rows retained"
        else:
            status = NormalizationRunStatus.SUCCESS
            error_class = None
            error_message = None

        # -------------------------------------- persist artifacts (P0-03)
        manifest_uri: str | None = None
        manifest_hash: str | None = None
        if status is not NormalizationRunStatus.BLOCKED and (mapped_rows > 0 or input_count == 0):
            run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
            base_uri = (
                f"provider={provider}/dataset={provider_dataset}/"
                f"raw_request={request_id}/contract={NORMALIZATION_CONTRACT_VERSION}"
            )
            import polars as pl

            output_records: list[dict[str, Any]] = []
            for output_name, out_rows in normalized.items():
                if not out_rows and input_count > 0:
                    continue
                frame_out = pl.DataFrame(out_rows)
                # deterministic ordering: sort by ALL columns (schema order)
                if frame_out.height > 0:
                    frame_out = frame_out.sort(frame_out.columns)
                artifact_uri = f"{base_uri}/{output_name}.parquet"
                artifact_path = physical_from_logical_uri(self.normalized_root, artifact_uri)
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                import io

                buf = io.BytesIO()
                frame_out.write_parquet(buf)
                payload_bytes = buf.getvalue()
                self._write_immutable(artifact_path, payload_bytes, run_id)
                output_records.append(
                    {
                        "output_name": output_name,
                        "uri": artifact_uri,
                        "content_hash": hashlib.sha256(payload_bytes).hexdigest(),
                        "schema_hash": hashlib.sha256(
                            str(frame_out.schema).encode("utf-8")
                        ).hexdigest(),
                        "row_count": frame_out.height,
                    }
                )
            semantic_hash = _canonical_semantic_hash(
                {name: rows for name, rows in normalized.items() if rows or input_count == 0}
            )
            manifest = {
                "normalization_run_id": run_id,
                "provider": provider,
                "provider_dataset": provider_dataset,
                "endpoint": endpoint,
                "raw_request_id": request_id,
                "raw_evidence_uri": raw_evidence_uri,
                "raw_evidence_hash": raw_evidence_hash,
                "raw_table_name": raw_table_name,
                "normalization_contract_version": NORMALIZATION_CONTRACT_VERSION,
                "mapper_identity": mapper_identity,
                "code_commit": self.code_commit,
                "outputs": output_records,
                "semantic_hash": semantic_hash,
                "input_count": input_count,
                "normalized_count": mapped_rows,
                "quarantined_count": len(quarantines),
                "status": status.value,
                "completed_at": datetime.now(UTC).isoformat(),
            }
            manifest_uri = f"{base_uri}/manifest.json"
            manifest_path = physical_from_logical_uri(self.normalized_root, manifest_uri)
            manifest_bytes = json.dumps(
                manifest, sort_keys=True, indent=1, ensure_ascii=False
            ).encode("utf-8")
            self._write_immutable(manifest_path, manifest_bytes, run_id)
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        else:
            run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))

        # ------------------------------------------- ledger + quarantine
        completed = datetime.now(UTC)
        self.conn.execute(
            "INSERT INTO meta_provider_normalization_run VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                provider,
                provider_dataset,
                endpoint,
                request_id,
                raw_evidence_uri,
                raw_evidence_hash,
                payload_kind,
                NORMALIZATION_CONTRACT_VERSION,
                mapper_identity,
                manifest_uri,
                manifest_hash,
                input_count,
                mapped_rows,
                len(quarantines),
                status.value,
                error_class,
                error_message,
                idempotency_key,
                False,
                started,
                completed,
            ],
        )
        for record in quarantines:
            self.conn.execute(
                "INSERT INTO meta_provider_quarantine VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    f"qtz-{uuid.uuid4()}",
                    run_id,
                    record["provider"],
                    record["provider_dataset"],
                    record["raw_request_id"],
                    record["raw_evidence_uri"],
                    record["raw_evidence_hash"],
                    record["raw_table_name"],
                    record["raw_row_ordinal"],
                    record["source_key"],
                    record["quarantine_scope"],
                    record["error_class"],
                    record["error_message"],
                    record["error_context_json"],
                    record["mapper_identity"],
                    NORMALIZATION_CONTRACT_VERSION,
                    record["created_at"],
                ],
            )
        return NormalizationRunResult(
            normalization_run_id=run_id,
            provider=provider,
            provider_dataset=provider_dataset,
            raw_request_id=request_id,
            status=status.value,
            error_class=error_class,
            error_message=error_message,
            input_count=input_count,
            normalized_count=mapped_rows,
            quarantined_count=len(quarantines),
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            idempotent_replay=False,
        )

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _source_key_of(row: dict[str, Any]) -> str | None:
        """Best-effort natural key for the quarantine record (never a
        REPLACEMENT for the raw row locator)."""
        for candidate in ("SECURITY_CODE", "INDEX_CODE", "code"):
            value = row.get(candidate)
            if value is not None:
                return str(value)
        return None

    @staticmethod
    def _quarantine_record(
        *,
        run_id_placeholder: None,
        provider: str,
        provider_dataset: str,
        request_id: str,
        raw_evidence_uri: str,
        raw_evidence_hash: str,
        raw_table_name: str | None,
        raw_row_ordinal: int | None,
        source_key: str | None,
        scope: QuarantineScope,
        error_class: NormalizationErrorClass,
        message: str,
        context: Any,
        mapper_identity: str,
    ) -> dict[str, Any]:
        del run_id_placeholder  # bound later, when the run id exists
        context_json: str | None = None
        if context is not None:
            scrubbed = _scrub_context(context)
            context_json = json.dumps(scrubbed, sort_keys=True, ensure_ascii=False, default=str)
        return {
            "provider": provider,
            "provider_dataset": provider_dataset,
            "raw_request_id": request_id,
            "raw_evidence_uri": raw_evidence_uri,
            "raw_evidence_hash": raw_evidence_hash,
            "raw_table_name": raw_table_name,
            "raw_row_ordinal": raw_row_ordinal,
            "source_key": source_key,
            "quarantine_scope": scope.value,
            "error_class": error_class.value,
            "error_message": str(message)[:500],
            "error_context_json": context_json,
            "mapper_identity": mapper_identity,
            "created_at": datetime.now(UTC),
        }

    def _blocked_run(
        self,
        *,
        provider: str,
        provider_dataset: str,
        request_id: str,
        raw_evidence_uri: str,
        raw_evidence_hash: str,
        raw_payload_kind: str | None,
        endpoint: str | None,
        error_class: NormalizationErrorClass,
        error_message: str,
        started: datetime,
        input_count: int,
        normalized_count: int,
        quarantined_count: int,
        manifest_uri: str | None,
        manifest_hash: str | None,
        quarantines: list[dict[str, Any]],
        spec: DatasetNormalizationSpec | None = None,
        idempotency_key: str | None = None,
    ) -> NormalizationRunResult:
        """Record an honest BLOCKED run (and its quarantine evidence,
        when any) - blocked runs are still first-class ledger rows."""
        if idempotency_key is None:
            mapper_identity = (
                mapper_identity_for(spec) if spec is not None else f"{provider_dataset}/none"
            )
            idempotency_key = hashlib.sha256(
                "|".join(
                    (raw_evidence_hash, NORMALIZATION_CONTRACT_VERSION, mapper_identity)
                ).encode("utf-8")
            ).hexdigest()
        run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
        mapper_identity = (
            mapper_identity_for(spec)
            if spec is not None
            else f"{provider_dataset}/{endpoint or 'none'}@blocked"
        )
        completed = datetime.now(UTC)
        self.conn.execute(
            "INSERT INTO meta_provider_normalization_run VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                provider,
                provider_dataset,
                endpoint,
                request_id,
                raw_evidence_uri,
                raw_evidence_hash,
                raw_payload_kind,
                NORMALIZATION_CONTRACT_VERSION,
                mapper_identity,
                manifest_uri,
                manifest_hash,
                input_count,
                normalized_count,
                quarantined_count,
                NormalizationRunStatus.BLOCKED.value,
                error_class.value,
                error_message,
                idempotency_key,
                False,
                started,
                completed,
            ],
        )
        for record in quarantines:
            self.conn.execute(
                "INSERT INTO meta_provider_quarantine VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    f"qtz-{uuid.uuid4()}",
                    run_id,
                    record["provider"],
                    record["provider_dataset"],
                    record["raw_request_id"],
                    record["raw_evidence_uri"],
                    record["raw_evidence_hash"],
                    record["raw_table_name"],
                    record["raw_row_ordinal"],
                    record["source_key"],
                    record["quarantine_scope"],
                    record["error_class"],
                    record["error_message"],
                    record["error_context_json"],
                    record["mapper_identity"],
                    NORMALIZATION_CONTRACT_VERSION,
                    record["created_at"],
                ],
            )
        return NormalizationRunResult(
            normalization_run_id=run_id,
            provider=provider,
            provider_dataset=provider_dataset,
            raw_request_id=request_id,
            status=NormalizationRunStatus.BLOCKED.value,
            error_class=error_class.value,
            error_message=error_message,
            input_count=input_count,
            normalized_count=normalized_count,
            quarantined_count=quarantined_count,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            idempotent_replay=False,
        )

    @staticmethod
    def _write_immutable(path: Path, data: bytes, run_id: str) -> None:
        """Immutable artifact write: identical existing bytes are a
        no-op (idempotent replay); different bytes are a conflict."""
        from ashare_state.storage.atomic_files import write_file_atomic

        if path.exists():
            if path.read_bytes() == data:
                return
            msg = (
                f"normalized artifact conflict at {path}: the file exists with "
                f"different bytes (run {run_id}) - normalized artifacts are "
                "immutable (CR-2 P0-03)"
            )
            raise NormalizationRunnerError(msg)
        write_file_atomic(path, data)


_ = (KIND_EMPTY, KIND_MULTI_ROWS, KIND_MULTI_FRAMES)  # documented kinds
