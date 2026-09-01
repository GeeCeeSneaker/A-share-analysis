"""Provider-Normalization execution runner (CR-2 / CR-2.1, audit 20260831).

The ONE formal normalization boundary::

    persisted Raw evidence (.meta.json + payload bytes)
      -> closure verification (verified reader, no re-call of the SDK)
      -> system-derived surface routing (typed registry key, the
         persisted normalization_surface of the envelope - legacy raw
         evidence on an AMBIGUOUS endpoint fails closed, never guessed)
      -> provider-faithful row / whole-payload mapping
      -> immutable normalized parquet artifacts + deterministic
         manifest (correctness bytes carry NO wall-clock)
      -> first-class quarantine records (append-only, exact-set sealed)
      -> meta_provider_normalization_run ledger row - committed in ONE
         DuckDB transaction together with the full quarantine set

Machine-enforced invariants (audit sections 2-5):

- P0-01 the runner NEVER calls the provider/SDK - its only input is
  the persisted raw evidence, read through the verified RawWriter
  reader (``read(verify=True)``);
- CR-2.1 P0-01 surface identity is the PERSISTED envelope field, not a
  request parameter: stock daily_bar and index daily_bar share the
  same (provider_dataset, endpoint) and route to different mappers
  ONLY through the system-derived ``normalization_surface``;
- CR-2.1 P0-03 ONE exact replay policy for SUCCESS / PARTIAL / BLOCKED:
  the same exact input identity re-verifies the existing run closure
  (manifest bytes, outputs, quarantine exact set) BEFORE an
  idempotent return; a damaged/tampered existing run fails closed
  (repair required) instead of returning a false healthy replay;
- CR-2.1 P0-03 the run identity includes the SYSTEM-DERIVED mapper
  code fingerprint - a mapper implementation change yields a NEW run
  identity (history preserved, never overwritten);
- CR-2.1 P0-04 commit closure: outputs land first, the manifest anchor
  lands LAST (file side); the run ledger + the full quarantine set +
  the count assertion commit in ONE DuckDB transaction - a DB failure
  rolls the ledger back while the deterministic file-side anchor lets
  the exact retry recover (identical bytes are a no-op);
- CR-2.1 P0-04 the quarantine evidence is sealed as an exact set
  (``quarantine_set_hash`` over the sorted semantic records) bound to
  both the run manifest and the ledger row - UPDATE/DELETE/missing
  quarantine rows break replay verification;
- P0-04 row-scope accounting ``input == normalized + quarantined`` is
  checked by the runtime itself - a silent drop fails the run;
- P0-06 every quarantine carries the deterministic raw locator
  (request id / table / row ordinal);
- P0-08 error classes separate provider failures, mapping failures
  and surface ambiguity;
- P0-10 the run status machine is SUCCESS / PARTIAL / BLOCKED with
  PARTIAL permitted only where the static registry allows it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.normalization import registry as _registry
from ashare_state.normalization.registry import (
    DatasetNormalizationSpec,
    NormalizationErrorClass,
    NormalizationRunStatus,
    QuarantineScope,
    SurfaceSupport,
    lookup_spec,
    mapper_identity_for,
    specs_for,
)
from ashare_state.providers.errors import MappingValidationError
from ashare_state.storage.paths import physical_from_logical_uri, validate_logical_uri
from ashare_state.storage.raw_anchor import lookup_raw_evidence_anchor
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

#: uuid namespaces for deterministic identities (same inputs -> same id)
_RUN_NAMESPACE = uuid.UUID("6f1c2b9a-4d3e-5f8a-9b7c-1e2d3c4b5a60")
_QTZ_NAMESPACE = uuid.UUID("8d2e3f0b-5c4a-6e9d-af8d-2f3e4d5c6b71")

_SECRET_MARKERS = ("password", "token", "secret", "credential")

#: semantic fields of a quarantine record entering the exact-set seal
_QTZ_SEMANTIC_FIELDS = (
    "provider",
    "provider_dataset",
    "raw_request_id",
    "raw_evidence_uri",
    "raw_evidence_hash",
    "raw_table_name",
    "raw_row_ordinal",
    "source_key",
    "quarantine_scope",
    "error_class",
    "error_message",
    "error_context_json",
    "mapper_identity",
)

#: ledger columns (migration 014 + 015 + 016 + 017) in canonical order
_LEDGER_COLUMNS = (
    "normalization_run_id",
    "provider",
    "provider_dataset",
    "endpoint",
    "raw_request_id",
    "raw_evidence_uri",
    "raw_evidence_hash",
    "raw_payload_kind",
    "normalization_contract_version",
    "mapper_identity",
    "normalized_manifest_uri",
    "normalized_manifest_hash",
    "input_count",
    "normalized_count",
    "quarantined_count",
    "status",
    "error_class",
    "error_message",
    "idempotency_key",
    "idempotent_replay",
    "started_at",
    "completed_at",
    "normalization_surface",
    "mapper_code_hash",
    "quarantine_set_hash",
    "evidence_conflict",
    "normalized_output_set_hash",
    "normalized_semantic_hash",
)

_QTZ_COLUMNS = (
    "quarantine_id",
    "normalization_run_id",
    "provider",
    "provider_dataset",
    "raw_request_id",
    "raw_evidence_uri",
    "raw_evidence_hash",
    "raw_table_name",
    "raw_row_ordinal",
    "source_key",
    "quarantine_scope",
    "error_class",
    "error_message",
    "error_context_json",
    "mapper_identity",
    "normalization_contract_version",
    "created_at",
)


class NormalizationRunnerError(RuntimeError):
    """The normalization boundary contract was violated (caller misuse,
    a damaged existing run requiring repair, or unrecoverable input
    state - e.g. the raw meta does not exist at all, so no
    evidence-bound run can even be recorded)."""


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
    normalization_surface: str | None = None
    quarantine_set_hash: str | None = None


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


def _quarantine_set_hash(records: list[dict[str, Any]]) -> str:
    """CR-2.1 P0-04: the exact-set seal of a run's quarantine evidence
    - canonical JSON over the SEMANTIC fields (no wall-clock, no random
    ids), ordered by the canonical semantic form of each record so the
    seal recomputes identically from persisted DB rows."""
    ordered = sorted(records, key=_quarantine_semantic_key)
    semantic = [{field: record.get(field) for field in _QTZ_SEMANTIC_FIELDS} for record in ordered]
    canonical = json.dumps(
        semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _quarantine_semantic_key(record: dict[str, Any]) -> str:
    return json.dumps(
        {field: record.get(field) for field in _QTZ_SEMANTIC_FIELDS},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _output_set_hash(records: list[dict[str, Any]]) -> str:
    """CR-2.3 P0-03 (audit 20260901 section 4.3): the exact-set seal of
    a run's materialized outputs - canonical JSON over the sorted
    (output_name, canonical logical uri, content_hash, schema_hash,
    row_count) tuples. Three-way bound: ledger == manifest ==
    replay-time physical recompute; removing a required output and
    rebinding both hashes breaks the exact-set comparison."""
    ordered = sorted(records, key=lambda r: str(r.get("output_name") or ""))
    canonical = json.dumps(
        [
            {
                "output_name": str(r.get("output_name") or ""),
                "uri": str(r.get("uri") or ""),
                "content_hash": str(r.get("content_hash") or ""),
                "schema_hash": str(r.get("schema_hash") or ""),
                "row_count": int(r.get("row_count") or 0),
            }
            for r in ordered
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
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


@dataclass(frozen=True)
class NormalizationRunSeal:
    """CR-2.2 P0-03 (audit 20260901 section 4.5) + CR-2.3 P0-03 (audit
    section 4.3): the typed full-seal binding of one normalization run.
    A replay is healthy only when the ledger row, the manifest bytes,
    the replay-time PHYSICAL recompute (output exact set + semantic
    values) AND the CURRENT system-derived provenance (contract + FULL
    mapper code fingerprint) all agree with this seal - a rebind-style
    tamper (edit manifest, rehash the file, update the ledger hash)
    still breaks it because every semantic field is compared, not just
    the outer file hash."""

    normalization_run_id: str
    provider: str
    normalization_surface: str
    provider_dataset: str
    endpoint: str
    raw_request_id: str
    raw_evidence_uri: str
    raw_evidence_hash: str
    raw_payload_kind: str
    normalization_contract_version: str
    mapper_identity: str
    mapper_code_hash: str
    status: str
    input_count: int
    normalized_count: int
    quarantined_count: int
    quarantine_set_hash: str | None
    normalized_output_set_hash: str | None
    normalized_semantic_hash: str | None

    @classmethod
    def from_ledger(cls, row: dict[str, Any]) -> NormalizationRunSeal:
        return cls(
            normalization_run_id=str(row["normalization_run_id"]),
            provider=str(row["provider"]),
            normalization_surface=str(row["normalization_surface"] or ""),
            provider_dataset=str(row["provider_dataset"]),
            endpoint=str(row["endpoint"]),
            raw_request_id=str(row["raw_request_id"]),
            raw_evidence_uri=str(row["raw_evidence_uri"]),
            raw_evidence_hash=str(row["raw_evidence_hash"]),
            raw_payload_kind=str(row["raw_payload_kind"] or ""),
            normalization_contract_version=str(row["normalization_contract_version"]),
            mapper_identity=str(row["mapper_identity"]),
            mapper_code_hash=str(row["mapper_code_hash"] or ""),
            status=str(row["status"]),
            input_count=int(row["input_count"]),
            normalized_count=int(row["normalized_count"]),
            quarantined_count=int(row["quarantined_count"]),
            quarantine_set_hash=(
                str(row["quarantine_set_hash"]) if row["quarantine_set_hash"] is not None else None
            ),
            normalized_output_set_hash=(
                str(row["normalized_output_set_hash"])
                if row.get("normalized_output_set_hash") is not None
                else None
            ),
            normalized_semantic_hash=(
                str(row["normalized_semantic_hash"])
                if row.get("normalized_semantic_hash") is not None
                else None
            ),
        )

    def current_provenance_problems(self) -> list[str]:
        """The seal must still match the CURRENT system-derived contract
        + FULL mapper fingerprint (defense in depth on top of the exact
        idempotency key: a ledger tamper of mapper_code_hash or an
        untracked contract drift is caught explicitly)."""
        problems: list[str] = []
        if self.normalization_contract_version != _registry.NORMALIZATION_CONTRACT_VERSION:
            problems.append(
                "ledger normalization_contract_version "
                f"{self.normalization_contract_version!r} does not match the current "
                f"contract {_registry.NORMALIZATION_CONTRACT_VERSION!r}"
            )
        if self.mapper_code_hash != _registry.MAPPER_CODE_FINGERPRINT:
            problems.append(
                "ledger mapper_code_hash does not match the CURRENT system-derived "
                "mapper code fingerprint (full SHA-256)"
            )
        return problems

    def manifest_binding_problems(self, manifest: dict[str, Any]) -> list[str]:
        """Every semantic field of the manifest must equal the ledger
        seal (audit 20260901 section 4.2 + CR-2.3 section 4.3 list) - a
        rebind that edits any of these fields and rehashes the file
        still fails here."""
        problems: list[str] = []
        expected = {
            "normalization_run_id": self.normalization_run_id,
            "provider": self.provider,
            "normalization_surface": self.normalization_surface,
            "provider_dataset": self.provider_dataset,
            "endpoint": self.endpoint,
            "raw_request_id": self.raw_request_id,
            "raw_evidence_uri": self.raw_evidence_uri,
            "raw_evidence_hash": self.raw_evidence_hash,
            "raw_payload_kind": self.raw_payload_kind,
            "normalization_contract_version": self.normalization_contract_version,
            "mapper_identity": self.mapper_identity,
            "mapper_code_hash": self.mapper_code_hash,
            "status": self.status,
            "input_count": str(self.input_count),
            "normalized_count": str(self.normalized_count),
            "quarantined_count": str(self.quarantined_count),
        }
        for field, sealed in expected.items():
            if str(manifest.get(field)) != sealed:
                problems.append(
                    f"manifest field {field} does not match the ledger seal "
                    f"(expected {sealed!r}, manifest carries {manifest.get(field)!r})"
                )
        # three-way quarantine seal: manifest == ledger (the DB-side
        # recompute lives in _verify_quarantine_set)
        if self.quarantine_set_hash is None or str(manifest.get("quarantine_set_hash")) != str(
            self.quarantine_set_hash
        ):
            problems.append(
                "manifest quarantine_set_hash does not match the ledger seal "
                "(three-way quarantine binding broken)"
            )
        # CR-2.3 P0-03: three-way output-set + semantic seals (manifest
        # == ledger; the PHYSICAL recompute lives in
        # _verify_manifest_outputs)
        for field, sealed_value in (
            ("output_set_hash", self.normalized_output_set_hash),
            ("semantic_hash", self.normalized_semantic_hash),
        ):
            if sealed_value is None or str(manifest.get(field)) != sealed_value:
                problems.append(
                    f"manifest {field} does not match the ledger seal "
                    "(three-way output/semantic binding broken)"
                )
        return problems


class NormalizationRunner:
    """CR-2 P0-01 / CR-2.1: the formal normalization runtime. Inputs
    are the persisted raw evidence + the immutable static registry
    ONLY - there is no provider/SDK access anywhere in this class, and
    no caller-supplied spec/mapper/registry anywhere in the API."""

    def __init__(
        self,
        conn: DuckDBPyConnection,
        *,
        raw_root: Path | str,
        normalized_root: Path | str,
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
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

        # ---------------- CR-2.3 P0-02: RAW EVIDENCE TRUST ANCHOR
        # (audit 20260901 section 3.3): the authoritative expected hash
        # of this request's meta is the INGESTION-TIME anchor persisted
        # OUTSIDE the raw filesystem (meta_raw_evidence_anchor, recorded
        # by the governed ingestion flow the moment RawWriter committed
        # the meta). The runner NEVER treats its first-seen meta hash as
        # a trust root:
        #   - no anchor (legacy pre-017 raw) -> fail closed; the
        #     governed repair is re-ingestion, never auto-grandfathering
        #     (a 015-era laundering history cannot be blessed silently);
        #   - current bytes != anchor hash -> INCIDENT HARD BLOCK before
        #     ANY routing/mapping (diagnostic evidence_conflict=TRUE -
        #     the trust root stays the anchor, so repeated tampered runs
        #     stay blocked forever and repairing the exact original
        #     bytes replays the original run).
        anchor = lookup_raw_evidence_anchor(
            self.conn, provider=provider, provider_dataset=provider_dataset, request_id=request_id
        )
        if anchor is None:
            anchor_missing_key = self._blocked_key(
                raw_evidence_hash, None, provider_dataset, None, None
            )
            replay = self._maybe_replay(anchor_missing_key)
            if replay is not None:
                return replay
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=None,
                endpoint=None,
                surface=None,
                error_class=NormalizationErrorClass.RAW_ANCHOR_MISSING,
                error_message=(
                    "no authoritative raw evidence anchor for request "
                    f"{request_id!r} - legacy raw without an ingestion-time "
                    "anchor fails closed (CR-2.3 audit 20260901 section 3.3); "
                    "the governed repair path is re-ingestion, never "
                    "auto-grandfathering"
                ),
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
            )
        if anchor.evidence_hash != raw_evidence_hash:
            anchor_mismatch_key = self._blocked_key(
                raw_evidence_hash, None, provider_dataset, None, None
            )
            replay = self._maybe_replay(anchor_mismatch_key)
            if replay is not None:
                return replay
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=None,
                endpoint=None,
                surface=None,
                error_class=NormalizationErrorClass.RAW_ANCHOR_MISMATCH,
                error_message=(
                    "raw evidence ANCHOR MISMATCH: the ingestion-time anchor binds "
                    f"{anchor.evidence_hash[:16]}... but the current persisted meta "
                    f"bytes hash to {raw_evidence_hash[:16]}... - tampering detected "
                    "BEFORE routing/mapping; the raw store is immutable, repair the "
                    "exact original bytes or re-ingest"
                ),
                started=started,
                input_count=0,
                normalized_count=0,
                quarantined_count=0,
                manifest_uri=None,
                manifest_hash=None,
                quarantines=[],
                evidence_conflict=True,
            )

        try:
            meta_doc = json.loads(raw_evidence_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            replay = self._maybe_replay(
                self._blocked_key(raw_evidence_hash, None, provider_dataset, None, None)
            )
            if replay is not None:
                return replay
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=None,
                endpoint=None,
                surface=None,
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
        # CR-2.1 P0-01: the business surface is the SYSTEM-DERIVED value
        # the provider facade persisted on the envelope - never a caller
        # argument, never a request-parameter guess.
        surface = str(meta_doc.get("normalization_surface") or "")

        # -------------------------------------------- closure verification
        problems = verify_meta_closure(dataset_dir, meta_doc)
        if problems:
            replay = self._maybe_replay(
                self._blocked_key(raw_evidence_hash, surface, provider_dataset, endpoint, None)
            )
            if replay is not None:
                return replay
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                surface=surface or None,
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
            replay = self._maybe_replay(
                self._blocked_key(raw_evidence_hash, surface, provider_dataset, endpoint, None)
            )
            if replay is not None:
                return replay
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
                surface=surface or None,
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
        spec, blocked_error = self._route(provider, provider_dataset, endpoint, surface)
        if blocked_error is not None:
            blocked_class, detail = blocked_error
            replay = self._maybe_replay(
                self._blocked_key(raw_evidence_hash, surface, provider_dataset, endpoint, spec)
            )
            if replay is not None:
                return replay
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                surface=surface or None,
                error_class=blocked_class,
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

        # routing returned a SUPPORTED spec (blocked_error is None only
        # for supported surfaces) - narrow for the rest of the flow
        assert spec is not None
        mapper_identity = mapper_identity_for(spec)
        idempotency_key = self._supported_key(raw_evidence_hash, mapper_identity)

        # ---------------------------------------- idempotent replay return
        # CR-2.2 P0-02B: EXACT replay lookup over the FULL history - the
        # deterministic run id (uuid5 over the exact idempotency key)
        # either exists in the ledger or it does not; no latest-run
        # comparison can shadow a historical exact match (A -> B -> A
        # rollback replays run A, never a duplicate of B, never a
        # duplicate-PK error).
        replay = self._maybe_replay(idempotency_key)
        if replay is not None:
            return replay

        # ------------------------------------- verified payload read (P0-01)
        try:
            payload = self._reader.read(
                provider=provider, dataset=provider_dataset, request_id=request_id, verify=True
            )
        except RawWriterError as exc:
            replay = self._maybe_replay(
                self._blocked_key(raw_evidence_hash, surface, provider_dataset, endpoint, spec)
            )
            if replay is not None:
                return replay
            return self._blocked_run(
                provider=provider,
                provider_dataset=provider_dataset,
                request_id=request_id,
                raw_evidence_uri=raw_evidence_uri,
                raw_evidence_hash=raw_evidence_hash,
                raw_payload_kind=payload_kind,
                endpoint=endpoint,
                surface=surface or None,
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
                replay = self._maybe_replay(idempotency_key)
                if replay is not None:
                    return replay
                return self._blocked_run(
                    provider=provider,
                    provider_dataset=provider_dataset,
                    request_id=request_id,
                    raw_evidence_uri=raw_evidence_uri,
                    raw_evidence_hash=raw_evidence_hash,
                    raw_payload_kind=payload_kind,
                    endpoint=endpoint,
                    surface=surface or None,
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
                    idempotency_key=idempotency_key,
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
                            context=self._row_error_context(exc, row),
                            mapper_identity=mapper_identity,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
                    quarantines.append(
                        self._quarantine_record(
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
                            context=self._row_error_context(exc, row),
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
                replay = self._maybe_replay(idempotency_key)
                if replay is not None:
                    return replay
                return self._blocked_run(
                    provider=provider,
                    provider_dataset=provider_dataset,
                    request_id=request_id,
                    raw_evidence_uri=raw_evidence_uri,
                    raw_evidence_hash=raw_evidence_hash,
                    raw_payload_kind=payload_kind,
                    endpoint=endpoint,
                    surface=surface or None,
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
        # internal-error rows are quarantined like any other bad row
        # (P0-08 separation lives in the ERROR CLASS of the record) -
        # the status machine itself follows the retention rules only.
        if quarantines and spec.quarantine_scope is QuarantineScope.WHOLE_PAYLOAD:
            status = NormalizationRunStatus.BLOCKED
            error_class: str | None = NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            error_message = "whole payload quarantined - zero normalized output"
        elif quarantines and not spec.allow_partial:
            status = NormalizationRunStatus.BLOCKED
            error_class = NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            error_message = (
                f"{len(quarantines)} row(s) quarantined and PARTIAL is not "
                f"allowed for {provider_dataset}/{endpoint}"
            )
        elif quarantines and mapped_rows == 0:
            # nothing survived: PARTIAL means good rows RETAINED - with
            # zero retained rows the run is BLOCKED, never a healthy
            # "partial" truth
            status = NormalizationRunStatus.BLOCKED
            error_class = (
                NormalizationErrorClass.NORMALIZATION_INTERNAL_ERROR
                if internal_errors
                else NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            )
            error_message = (
                f"{len(quarantines)} row(s) quarantined and ZERO rows normalized - "
                "nothing was retained"
            )
        elif quarantines:
            status = NormalizationRunStatus.PARTIAL
            error_class = (
                NormalizationErrorClass.NORMALIZATION_INTERNAL_ERROR
                if internal_errors
                else NormalizationErrorClass.MAPPING_VALIDATION_FAILED
            )
            error_message = f"{len(quarantines)} row(s) quarantined; good rows retained" + (
                f" ({internal_errors} mapper internal error(s))" if internal_errors else ""
            )
        else:
            status = NormalizationRunStatus.SUCCESS
            error_class = None
            error_message = None

        # ------------------------- deterministic run + artifact identity
        # CR-2.1 P0-03: the run id is derived from the exact input
        # identity (raw evidence hash + contract + SYSTEM-DERIVED mapper
        # identity incl. the code fingerprint) - a mapper implementation
        # change therefore yields a NEW run and NEW artifact paths
        # (history preserved, never overwritten).
        run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
        base_uri = (
            f"provider={provider}/dataset={provider_dataset}/"
            f"raw_request={request_id}/"
            f"contract={_registry.NORMALIZATION_CONTRACT_VERSION}/run={run_id}"
        )
        qtz_set_hash = _quarantine_set_hash(self._bind_quarantine_ids(run_id, quarantines))

        manifest_uri: str | None = None
        manifest_hash: str | None = None
        output_set_hash: str | None = None
        semantic_hash: str | None = None
        # ROW-scope runs materialize their output tables (possibly
        # EMPTY ones when every row quarantined - the empty parquet IS
        # the "nothing normalized, no sentinel row" evidence); a
        # WHOLE_PAYLOAD quarantine produces zero output by contract.
        should_write_artifacts = (
            spec.quarantine_scope is QuarantineScope.ROW or mapped_rows > 0 or input_count == 0
        )
        if should_write_artifacts:
            import io

            import polars as pl

            # CR-2.3 P0-03 (audit 20260901 section 4.3): the
            # materialized output set is EXACTLY spec.output_names -
            # every declared output is materialized (an empty parquet
            # for an empty table), never a subset. The exact set is
            # sealed (output_set_hash) into BOTH the manifest and the
            # ledger, and replay re-verifies it against the CURRENT
            # registry spec - removing a required output (or adding an
            # undeclared one) and rebinding both hashes breaks the seal.
            output_records: list[dict[str, Any]] = []
            for output_name in spec.output_names:
                out_rows = normalized.get(output_name, [])
                frame_out = pl.DataFrame(out_rows)
                # deterministic ordering: sort by ALL columns (schema order)
                if frame_out.height > 0:
                    frame_out = frame_out.sort(frame_out.columns)
                artifact_uri = f"{base_uri}/{output_name}.parquet"
                artifact_path = physical_from_logical_uri(self.normalized_root, artifact_uri)
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
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
            output_set_hash = _output_set_hash(output_records)
            # CR-2.3 P0-03: the semantic identity of the normalized
            # VALUES is sealed into BOTH the ledger and the manifest;
            # replay recomputes it from the physical parquet records -
            # swapping the parquet for same-schema/same-row-count
            # different values and rebinding content/manifest hashes
            # still breaks it.
            semantic_hash = _canonical_semantic_hash(
                {name: normalized.get(name, []) for name in spec.output_names}
            )
            # CR-2.1 P0-04: correctness bytes carry NO wall-clock and NO
            # caller-declared provenance - an exact retry regenerates
            # byte-identical manifest bytes (the immutable write is a
            # no-op), so a transient DB failure can never strand the
            # run behind a conflicting manifest.
            manifest = {
                "normalization_run_id": run_id,
                "provider": provider,
                "normalization_surface": surface,
                "provider_dataset": provider_dataset,
                "endpoint": endpoint,
                "raw_request_id": request_id,
                "raw_evidence_uri": raw_evidence_uri,
                "raw_evidence_hash": raw_evidence_hash,
                "raw_payload_kind": payload_kind,
                "raw_table_name": raw_table_name,
                "normalization_contract_version": _registry.NORMALIZATION_CONTRACT_VERSION,
                "mapper_identity": mapper_identity,
                "mapper_code_hash": _registry.MAPPER_CODE_FINGERPRINT,
                "outputs": output_records,
                "output_set_hash": output_set_hash,
                "semantic_hash": semantic_hash,
                "quarantine_set_hash": qtz_set_hash,
                "input_count": input_count,
                "normalized_count": mapped_rows,
                "quarantined_count": len(quarantines),
                "status": status.value,
            }
            manifest_uri = f"{base_uri}/manifest.json"
            manifest_path = physical_from_logical_uri(self.normalized_root, manifest_uri)
            manifest_bytes = json.dumps(
                manifest, sort_keys=True, indent=1, ensure_ascii=False
            ).encode("utf-8")
            # the manifest is the FILE-SIDE anchor: it lands LAST, only
            # after every output artifact is in place
            self._write_immutable(manifest_path, manifest_bytes, run_id)
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()

        # --------------------------- ledger + quarantine atomic commit
        completed = datetime.now(UTC)
        self._commit_ledger(
            run_id=run_id,
            provider=provider,
            provider_dataset=provider_dataset,
            endpoint=endpoint,
            request_id=request_id,
            raw_evidence_uri=raw_evidence_uri,
            raw_evidence_hash=raw_evidence_hash,
            raw_payload_kind=payload_kind,
            mapper_identity=mapper_identity,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            input_count=input_count,
            normalized_count=mapped_rows,
            quarantined_count=len(quarantines),
            status=status.value,
            error_class=error_class,
            error_message=error_message,
            idempotency_key=idempotency_key,
            started=started,
            completed=completed,
            surface=surface or None,
            quarantines=quarantines,
            qtz_set_hash=qtz_set_hash,
            output_set_hash=output_set_hash,
            semantic_hash=semantic_hash,
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
            normalization_surface=surface or None,
            quarantine_set_hash=qtz_set_hash,
        )

    # ------------------------------------------------------------ routing
    def _route(
        self, provider: str, provider_dataset: str, endpoint: str, surface: str
    ) -> tuple[DatasetNormalizationSpec | None, tuple[NormalizationErrorClass, str] | None]:
        """Typed surface routing (CR-2.1 P0-01).

        Returns (spec, blocked) - exactly one is None. When the meta
        carries the persisted ``normalization_surface`` the lookup is
        the exact typed key. Legacy evidence WITHOUT the surface field
        routes through the (dataset, endpoint) pair ONLY when it is
        unambiguous; an ambiguous pair (stock vs index daily bar on
        MarketData.query_kline) fails closed with
        PAYLOAD_SURFACE_AMBIGUOUS - never a symbol-prefix or
        request-parameter guess."""
        if surface:
            spec = lookup_spec(provider, surface, provider_dataset, endpoint)
            if spec is None:
                return None, (
                    NormalizationErrorClass.PAYLOAD_SHAPE_UNSUPPORTED,
                    (
                        f"no registry entry for surface {surface}/{provider_dataset}/{endpoint} "
                        "- unknown surfaces fail closed (never take-first-table or "
                        "fuzzy routing)"
                    ),
                )
            return self._check_support(spec, provider_dataset, endpoint)
        entries = specs_for(provider, provider_dataset, endpoint)
        if not entries:
            return None, (
                NormalizationErrorClass.PAYLOAD_SHAPE_UNSUPPORTED,
                (
                    f"no registry entry for surface {provider_dataset}/{endpoint} - "
                    "unknown surfaces fail closed (never take-first-table or "
                    "fuzzy routing)"
                ),
            )
        if len(entries) > 1:
            surfaces = sorted({entry.normalization_surface for entry in entries})
            return None, (
                NormalizationErrorClass.PAYLOAD_SURFACE_AMBIGUOUS,
                (
                    f"legacy raw evidence for {provider_dataset}/{endpoint} carries no "
                    f"normalization_surface and the pair is ambiguous (business "
                    f"surfaces: {surfaces}) - re-ingest through the provider facade "
                    "so the system-derived surface identity is persisted; guessing "
                    "from symbol prefixes or request params is forbidden "
                    "(CR-2.1 P0-01)"
                ),
            )
        return self._check_support(entries[0], provider_dataset, endpoint)

    @staticmethod
    def _check_support(
        spec: DatasetNormalizationSpec, provider_dataset: str, endpoint: str
    ) -> tuple[DatasetNormalizationSpec | None, tuple[NormalizationErrorClass, str] | None]:
        if spec.support is SurfaceSupport.SUPPORTED_NORMALIZATION:
            return spec, None
        if spec.support is SurfaceSupport.BLOCKED_PENDING_MAPPER:
            return spec, (
                NormalizationErrorClass.PAYLOAD_SHAPE_UNSUPPORTED,
                (
                    f"surface {spec.normalization_surface}/{provider_dataset}/{endpoint} is "
                    f"BLOCKED_PENDING_MAPPER (mapper {spec.mapper_version!r}) - no verified "
                    "mapper exists yet; normalization fails closed, it never silently skips"
                ),
            )
        return spec, (
            NormalizationErrorClass.PAYLOAD_SHAPE_UNSUPPORTED,
            (
                f"surface {spec.normalization_surface}/{provider_dataset}/{endpoint} is "
                f"classified {spec.support.value} - not a normalization input"
            ),
        )

    # ----------------------------------------------------------- identity
    @staticmethod
    def _supported_key(raw_evidence_hash: str, mapper_identity: str) -> str:
        """CR-2.2 P0-03 (audit 20260901 section 4.1): the idempotency key
        mixes in the FULL system-derived MAPPER_CODE_FINGERPRINT - the
        display string in ``mapper_identity`` carries only the first 16
        hex chars, but the correctness hash input is never truncated: a
        fingerprint differing only beyond char 16 yields a NEW run
        identity (same rule for ``_blocked_key``)."""
        return hashlib.sha256(
            "|".join(
                (
                    raw_evidence_hash,
                    _registry.NORMALIZATION_CONTRACT_VERSION,
                    mapper_identity,
                    _registry.MAPPER_CODE_FINGERPRINT,
                )
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _blocked_key(
        raw_evidence_hash: str,
        surface: str | None,
        provider_dataset: str,
        endpoint: str | None,
        spec: DatasetNormalizationSpec | None,
    ) -> str:
        identity = (
            mapper_identity_for(spec)
            if spec is not None
            else f"{surface or '-'}/{provider_dataset}/{endpoint or 'none'}@blocked"
        )
        return hashlib.sha256(
            "|".join(
                (
                    raw_evidence_hash,
                    _registry.NORMALIZATION_CONTRACT_VERSION,
                    identity,
                    _registry.MAPPER_CODE_FINGERPRINT,
                )
            ).encode("utf-8")
        ).hexdigest()

    # -------------------------------------------------------------- replay
    def _maybe_replay(self, idempotency_key: str) -> NormalizationRunResult | None:
        """CR-2.2 P0-02B: the ONE replay policy - SUCCESS, PARTIAL and
        BLOCKED alike, looked up EXACTLY over the full history. The
        deterministic run id (uuid5 over the exact idempotency key) is
        queried directly: a historical run with the same exact identity
        is re-verified (closure intact) and returned as an idempotent
        replay; a damaged prior run fails closed. Nothing here depends
        on which run happens to be 'latest'."""
        run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
        exists = self.conn.execute(
            "SELECT 1 FROM meta_provider_normalization_run WHERE normalization_run_id = ?",
            [run_id],
        ).fetchone()
        if exists is None:
            return None
        return self._require_verified_replay(run_id, idempotency_key)

    def _require_verified_replay(self, run_id: str, idempotency_key: str) -> NormalizationRunResult:
        row = self._ledger_row(run_id)
        if row is None:
            msg = (
                f"prior run {run_id} referenced by idempotency key "
                f"{idempotency_key[:16]}... is missing from the ledger - "
                "inconsistent state, repair required"
            )
            raise NormalizationRunnerError(msg)
        if str(row["idempotency_key"]) != idempotency_key:
            msg = f"prior run {run_id} identity mismatch - repair required"
            raise NormalizationRunnerError(msg)
        problems = self._verify_run_closure(row)
        if problems:
            msg = (
                f"existing run {run_id} is DAMAGED - idempotent replay refused, "
                f"repair required: {'; '.join(problems)}"
            )
            raise NormalizationRunnerError(msg)
        return NormalizationRunResult(
            normalization_run_id=str(row["normalization_run_id"]),
            provider=str(row["provider"]),
            provider_dataset=str(row["provider_dataset"]),
            raw_request_id=str(row["raw_request_id"]),
            status=str(row["status"]),
            error_class=str(row["error_class"]) if row["error_class"] is not None else None,
            error_message=str(row["error_message"]) if row["error_message"] is not None else None,
            input_count=int(row["input_count"]),
            normalized_count=int(row["normalized_count"]),
            quarantined_count=int(row["quarantined_count"]),
            manifest_uri=str(row["normalized_manifest_uri"])
            if row["normalized_manifest_uri"] is not None
            else None,
            manifest_hash=str(row["normalized_manifest_hash"])
            if row["normalized_manifest_hash"] is not None
            else None,
            idempotent_replay=True,
            normalization_surface=str(row["normalization_surface"])
            if row["normalization_surface"] is not None
            else None,
            quarantine_set_hash=str(row["quarantine_set_hash"])
            if row["quarantine_set_hash"] is not None
            else None,
        )

    def _ledger_row(self, run_id: str) -> dict[str, Any] | None:
        result = self.conn.execute(
            f"SELECT {', '.join(_LEDGER_COLUMNS)} "
            "FROM meta_provider_normalization_run "
            "WHERE normalization_run_id = ?",
            [run_id],
        ).fetchone()
        if result is None:
            return None
        return dict(zip(_LEDGER_COLUMNS, result, strict=True))

    def _verify_run_closure(self, row: dict[str, Any]) -> list[str]:
        """CR-2.1 P0-03/P0-04 + CR-2.2 P0-03: re-verify an existing run
        BEFORE an idempotent reuse - the typed seal (ledger == manifest
        == current provenance), the manifest/output bytes and the
        quarantine exact set must all be intact.

        Typed manifest policy (audit 20260901 section 4.3): a
        SUCCESS/PARTIAL run MUST carry its manifest (a ledger status
        flip cannot manufacture a manifest-free healthy replay); a
        BLOCKED run carries a manifest only when it materialized
        empty-output evidence (row scope) - when present it is verified
        with the same full seal."""
        problems: list[str] = []
        status = str(row["status"])
        # quarantine exact-set verification (every status)
        problems.extend(self._verify_quarantine_set(row))
        if (
            status
            in (
                NormalizationRunStatus.SUCCESS.value,
                NormalizationRunStatus.PARTIAL.value,
            )
            and row["normalized_manifest_uri"] is None
        ):
            problems.append(
                f"run {row['normalization_run_id']} is {status} but carries no "
                "normalized manifest - SUCCESS/PARTIAL without a manifest "
                "binding is not replayable as healthy"
            )
        if row["normalized_manifest_uri"] is not None:
            problems.extend(self._verify_manifest_outputs(row))
        return problems

    def _verify_quarantine_set(self, row: dict[str, Any]) -> list[str]:
        run_id = str(row["normalization_run_id"])
        expected_count = int(row["quarantined_count"])
        sealed_hash = row["quarantine_set_hash"]
        problems: list[str] = []
        if sealed_hash is None:
            # CR-2 legacy row without the exact-set seal: never replay-
            # verified as healthy
            return [
                f"run {run_id} carries no quarantine_set_hash seal "
                "(CR-2 legacy row) - re-run under the current contract"
            ]
        rows = self.conn.execute(
            f"SELECT {', '.join(_QTZ_SEMANTIC_FIELDS)} "
            "FROM meta_provider_quarantine "
            "WHERE normalization_run_id = ? ORDER BY quarantine_id",
            [run_id],
        ).fetchall()
        if len(rows) != expected_count:
            problems.append(
                f"quarantine count mismatch: ledger declares {expected_count} "
                f"but {len(rows)} rows persist"
            )
        records = [dict(zip(_QTZ_SEMANTIC_FIELDS, record, strict=True)) for record in rows]
        if _quarantine_set_hash(records) != str(sealed_hash):
            problems.append(
                "quarantine exact-set seal mismatch: persisted rows no longer "
                "match the sealed quarantine_set_hash (tamper or missing rows)"
            )
        return problems

    def _verify_manifest_outputs(self, row: dict[str, Any]) -> list[str]:
        run_id = str(row["normalization_run_id"])
        manifest_uri = row["normalized_manifest_uri"]
        manifest_hash = row["normalized_manifest_hash"]
        problems: list[str] = []
        if manifest_uri is None or manifest_hash is None:
            return [
                f"run {run_id} carries a manifest reference but no manifest hash - repair required"
            ]
        manifest_path = physical_from_logical_uri(self.normalized_root, str(manifest_uri))
        if not manifest_path.is_file():
            return [f"normalized manifest missing: {manifest_uri}"]
        actual_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if actual_manifest_hash != str(manifest_hash):
            return [f"normalized manifest bytes do not match the ledger hash: {manifest_uri}"]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [f"normalized manifest unreadable: {manifest_uri}"]
        # CR-2.2 P0-03: typed full-seal comparison - ledger == manifest
        # == CURRENT provenance (contract + FULL mapper fingerprint)
        seal = NormalizationRunSeal.from_ledger(row)
        problems.extend(seal.current_provenance_problems())
        problems.extend(seal.manifest_binding_problems(manifest))
        import polars as pl

        # --------------------------- CR-2.3 P0-03: EXPECTED OUTPUT EXACT
        # SET == CURRENT typed registry spec.output_names - no missing
        # required output, no undeclared extra, no duplicates.
        registry_spec = lookup_spec(
            seal.provider,
            seal.normalization_surface,
            seal.provider_dataset,
            seal.endpoint,
        )
        if registry_spec is None:
            problems.append(
                "no CURRENT registry spec for "
                f"{seal.normalization_surface}/{seal.provider_dataset}/{seal.endpoint} - "
                "the run's surface is no longer a known normalization surface "
                "(registry drift); replay fails closed"
            )
            return problems
        manifest_outputs = list(manifest.get("outputs", []))
        manifest_names = [str(o.get("output_name") or "") for o in manifest_outputs]
        if len(manifest_names) != len(set(manifest_names)):
            problems.append("manifest carries DUPLICATE output_name entries")
        expected_names = set(registry_spec.output_names)
        actual_names = set(manifest_names)
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        if missing:
            problems.append(
                f"manifest output set MISSING required output(s): {missing} "
                "(exact-set seal: every declared output must be present)"
            )
        if extra:
            problems.append(
                f"manifest output set carries UNDECLARED output(s): {extra} "
                "(exact-set seal: no output outside spec.output_names)"
            )
        # --------------------------- CR-2.3 P0-03: deterministic URI
        # binding - every manifest output uri must equal the expected
        # base path + output_name, recomputed from the LEDGER identity
        # (a rebind onto another valid logical path fails here).
        expected_base = (
            f"provider={seal.provider}/dataset={seal.provider_dataset}/"
            f"raw_request={seal.raw_request_id}/"
            f"contract={seal.normalization_contract_version}/run={run_id}"
        )
        for output in manifest_outputs:
            output_uri = str(output.get("uri", ""))
            expected_uri = f"{expected_base}/{output.get('output_name')}.parquet"
            if output_uri != expected_uri:
                problems.append(
                    f"output uri {output_uri!r} is not the deterministic expected "
                    f"path {expected_uri!r} (URI rebind detected)"
                )
        # --------------------------- CR-2.3 P0-03: three-way OUTPUT SET
        # seal - recompute from the PHYSICAL files and compare with the
        # manifest and the ledger.
        physical_records: list[dict[str, Any]] = []
        rows_by_output: dict[str, list[dict[str, Any]]] = {}
        for output in manifest_outputs:
            output_uri = str(output.get("uri", ""))
            output_name = str(output.get("output_name") or "")
            output_path = physical_from_logical_uri(self.normalized_root, output_uri)
            if not output_path.is_file():
                problems.append(f"normalized output missing: {output_uri}")
                continue
            output_bytes = output_path.read_bytes()
            if hashlib.sha256(output_bytes).hexdigest() != str(output.get("content_hash")):
                problems.append(f"normalized output bytes tampered: {output_uri}")
                continue
            frame = pl.read_parquet(output_path)
            if frame.height != int(output.get("row_count", -1)):
                problems.append(f"normalized output row count mismatch: {output_uri}")
            # CR-2.2 P0-03 (audit section 4.4): schema_hash is RECOMPUTED
            # from the physical parquet - a rebind that swaps the parquet
            # and updates content_hash still breaks on the schema seal
            actual_schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
            if actual_schema_hash != str(output.get("schema_hash")):
                problems.append(f"normalized output schema mismatch: {output_uri}")
            physical_records.append(
                {
                    "output_name": output_name,
                    "uri": output_uri,
                    "content_hash": hashlib.sha256(output_bytes).hexdigest(),
                    "schema_hash": actual_schema_hash,
                    "row_count": frame.height,
                }
            )
            rows_by_output[output_name] = frame.to_dicts()
        if seal.normalized_output_set_hash is not None:
            if _output_set_hash(physical_records) != str(seal.normalized_output_set_hash):
                problems.append(
                    "output exact-set seal mismatch: the physical output recompute "
                    "does not match the ledger normalized_output_set_hash"
                )
        else:
            problems.append(
                "run carries no normalized_output_set_hash seal (pre-CR-2.3 row) - "
                "re-run under the current contract"
            )
        # --------------------------- CR-2.3 P0-03: three-way SEMANTIC
        # seal - recompute the normalized VALUES identity from the
        # physical parquet records.
        if seal.normalized_semantic_hash is not None:
            recomputed_semantic = _canonical_semantic_hash(
                {name: rows_by_output.get(name, []) for name in registry_spec.output_names}
            )
            if recomputed_semantic != str(seal.normalized_semantic_hash):
                problems.append(
                    "semantic seal mismatch: the physical parquet VALUES recompute "
                    "does not match the ledger normalized_semantic_hash"
                )
        else:
            problems.append(
                "run carries no normalized_semantic_hash seal (pre-CR-2.3 row) - "
                "re-run under the current contract"
            )
        return problems

    # ------------------------------------------------------------- commit
    def _commit_ledger(
        self,
        *,
        run_id: str,
        provider: str,
        provider_dataset: str,
        endpoint: str,
        request_id: str,
        raw_evidence_uri: str,
        raw_evidence_hash: str,
        raw_payload_kind: str,
        mapper_identity: str,
        manifest_uri: str | None,
        manifest_hash: str | None,
        input_count: int,
        normalized_count: int,
        quarantined_count: int,
        status: str,
        error_class: str | None,
        error_message: str | None,
        idempotency_key: str,
        started: datetime,
        completed: datetime,
        surface: str | None,
        quarantines: list[dict[str, Any]],
        qtz_set_hash: str,
        evidence_conflict: bool = False,
        output_set_hash: str | None = None,
        semantic_hash: str | None = None,
    ) -> None:
        """CR-2.1 P0-04: the run ledger + the FULL quarantine set commit
        in ONE DuckDB transaction with a post-insert count assertion -
        a failure anywhere rolls the whole ledger back (the file-side
        deterministic anchor lets the exact retry recover).

        CR-2.2 P0-02A: ``evidence_conflict`` marks the INCIDENT HARD
        BLOCK runs (diagnostic/audit only since CR-2.3 - the trust
        root is the raw evidence anchor ledger).

        CR-2.3 P0-03: ``output_set_hash`` / ``semantic_hash`` are the
        ledger-side seals of the exact output set and the normalized
        values (three-way bound with the manifest and the replay-time
        physical recompute)."""
        self.conn.execute("BEGIN TRANSACTION")
        try:
            dup = self.conn.execute(
                "SELECT 1 FROM meta_provider_normalization_run WHERE normalization_run_id = ?",
                [run_id],
            ).fetchone()
            if dup is not None:
                msg = (
                    f"normalization run {run_id} already exists in the ledger - "
                    "conflicting duplicate execution (repair required)"
                )
                raise NormalizationRunnerError(msg)
            self.conn.execute(
                f"INSERT INTO meta_provider_normalization_run "
                f"({', '.join(_LEDGER_COLUMNS)}) VALUES "
                f"({', '.join(['?'] * len(_LEDGER_COLUMNS))})",
                [
                    run_id,
                    provider,
                    provider_dataset,
                    endpoint,
                    request_id,
                    raw_evidence_uri,
                    raw_evidence_hash,
                    raw_payload_kind,
                    _registry.NORMALIZATION_CONTRACT_VERSION,
                    mapper_identity,
                    manifest_uri,
                    manifest_hash,
                    input_count,
                    normalized_count,
                    quarantined_count,
                    status,
                    error_class,
                    error_message,
                    idempotency_key,
                    False,
                    started,
                    completed,
                    surface,
                    _registry.MAPPER_CODE_FINGERPRINT,
                    qtz_set_hash,
                    evidence_conflict,
                    output_set_hash,
                    semantic_hash,
                ],
            )
            for record in quarantines:
                self.conn.execute(
                    f"INSERT INTO meta_provider_quarantine "
                    f"({', '.join(_QTZ_COLUMNS)}) VALUES "
                    f"({', '.join(['?'] * len(_QTZ_COLUMNS))})",
                    [
                        record["_qtz_id"],
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
                        _registry.NORMALIZATION_CONTRACT_VERSION,
                        record["created_at"],
                    ],
                )
            persisted = self.conn.execute(
                "SELECT count(*) FROM meta_provider_quarantine WHERE normalization_run_id = ?",
                [run_id],
            ).fetchone()
            persisted_count = int(persisted[0]) if persisted is not None else -1
            if persisted_count != len(quarantines):
                msg = (
                    f"quarantine set persistence mismatch for run {run_id}: "
                    f"expected {len(quarantines)} rows, persisted {persisted_count}"
                )
                raise NormalizationRunnerError(msg)
            self.conn.execute("COMMIT")
        except Exception as exc:
            with contextlib.suppress(Exception):
                self.conn.execute("ROLLBACK")
            if isinstance(exc, NormalizationRunnerError):
                raise
            msg = f"normalization ledger commit failed for run {run_id}: {exc}"
            raise NormalizationRunnerError(msg) from exc

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _row_error_context(exc: Exception, row: dict[str, Any]) -> dict[str, Any]:
        """Evidence context of a row-level failure: the error's own
        context (when present) plus the OFFENDING ROW itself, scrubbed
        of secret-bearing keys (CR2-P0-05: quarantine must never leak
        credentials, but must carry enough evidence to diagnose)."""
        context: dict[str, Any] = {}
        exc_context = getattr(exc, "context", None)
        if isinstance(exc_context, dict):
            context.update(exc_context)
        context["row"] = _scrub_context(dict(row))
        return context

    @staticmethod
    def _bind_quarantine_ids(run_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deterministic quarantine ids: the same exact run replays to
        the same ids (never a second row set)."""
        for position, record in enumerate(records):
            record["_qtz_id"] = f"qtz-{uuid.uuid5(_QTZ_NAMESPACE, f'{run_id}:{position}')}"
        return records

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
        surface: str | None,
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
        evidence_conflict: bool = False,
    ) -> NormalizationRunResult:
        """Record an honest BLOCKED run (and its quarantine evidence,
        when any) - blocked runs are still first-class ledger rows,
        committed atomically with their quarantine set. CR-2.2: an
        ``evidence_conflict`` run is an INCIDENT HARD BLOCK marker -
        recorded for audit, excluded from the raw-evidence baseline."""
        if idempotency_key is None:
            idempotency_key = self._blocked_key(
                raw_evidence_hash, surface, provider_dataset, endpoint, spec
            )
        run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
        mapper_identity = (
            mapper_identity_for(spec)
            if spec is not None
            else f"{surface or '-'}/{provider_dataset}/{endpoint or 'none'}@blocked"
        )
        completed = datetime.now(UTC)
        qtz_set_hash = _quarantine_set_hash(self._bind_quarantine_ids(run_id, quarantines))
        self._commit_ledger(
            run_id=run_id,
            provider=provider,
            provider_dataset=provider_dataset,
            endpoint=endpoint or "",
            request_id=request_id,
            raw_evidence_uri=raw_evidence_uri,
            raw_evidence_hash=raw_evidence_hash,
            raw_payload_kind=raw_payload_kind or "",
            mapper_identity=mapper_identity,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            input_count=input_count,
            normalized_count=normalized_count,
            quarantined_count=len(quarantines),
            status=NormalizationRunStatus.BLOCKED.value,
            error_class=error_class.value,
            error_message=error_message,
            idempotency_key=idempotency_key,
            started=started,
            completed=completed,
            surface=surface,
            quarantines=quarantines,
            qtz_set_hash=qtz_set_hash,
            evidence_conflict=evidence_conflict,
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
            quarantined_count=len(quarantines),
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            idempotent_replay=False,
            normalization_surface=surface,
            quarantine_set_hash=qtz_set_hash,
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


def verify_normalized_run(
    conn: DuckDBPyConnection,
    run_id: str,
    *,
    raw_root: Path | str,
    normalized_root: Path | str,
) -> list[str]:
    """CR-3 (audit 20260901 CR3-P0-01): read-only closure verification of
    one CR-2 normalization run - the ONLY sanctioned way for downstream
    consumers to establish that a Provider-Normalized artifact is still
    the exact verified truth (manifest bytes, output content/schema/
    row-count, quarantine exact set, typed seal vs current provenance).

    Returns the (possibly empty) problem list. An empty list means the
    run is verified intact; consumers must treat any problem as
    fail-closed. This verifier writes NOTHING and re-maps NOTHING.
    """
    runner = NormalizationRunner(conn, raw_root=raw_root, normalized_root=normalized_root)
    row = runner._ledger_row(run_id)  # noqa: SLF001 - same-module read-only reuse
    if row is None:
        return [f"normalization run {run_id!r} not found in the ledger"]
    return runner._verify_run_closure(row)  # noqa: SLF001 - read-only closure reuse
