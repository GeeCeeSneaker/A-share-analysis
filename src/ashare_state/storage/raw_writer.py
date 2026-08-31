"""RawWriter: immutable provider evidence runtime (CR-1b/CR-1.1/CR-1.2).

Contract (audit R4-A2.3 sections 4-5 + R4-A2.4 section 3):
- SUCCESS exchange  -> raw artifact (Parquet for tabular payloads) +
                       .meta.json (envelope), immutable
- FAILURE exchange  -> failure evidence (envelope-only .meta.json), the
                       request audit record is NEVER dropped
- ``write(exchange)`` consumes the ProviderExchange DIRECTLY (audit
  section 3.2-C): request_id consistency is asserted
  (``exchange.request_id == exchange.envelope.request_id``) and
  provider/dataset come from the ENVELOPE first - an external value that
  conflicts with the envelope BLOCKS instead of silently overriding.
- Idempotent: same request + same content hash -> no-op
- Conflict: same request + different bytes -> BLOCK
- Lossless: structured tabular payloads go to Parquet; never repr()
- Secret-scrubbed: params are scrubbed before persisting
- Cross-platform logical URI: relative, forward slashes, no drive letters

CR-1.2 closure (audit R4-A2.4 section 3.1-3.2):
- the EVIDENCE a SpikeCase binds to is the .meta.json of the exchange
  (``evidence_uri``/``evidence_hash``): the meta declares every payload
  artifact's hash, so payload+meta close BIDIRECTIONALLY - deleting or
  tampering EITHER side breaks the evidence closure
- ``RawWriteResult`` splits into ``payload_artifacts`` (uri/content_hash/
  schema_hash/row_count each) + ``meta_artifact`` (uri/content_hash)
- meta persists the FULL scrubbed ``request_params`` + their hash (the
  request is reconstructable; equal-size requests over different symbols
  hash differently), ``ingested_at`` and the ``ingest_run_id`` binding
- multi-file commits are staged: all payload bytes land in a staging dir
  first, then each file is atomically moved into place, and the meta is
  written LAST - an interrupted commit can never produce a meta-anchored
  partial evidence set
- table-name collisions after sanitization BLOCK (never overwrite)
- ``read(verify=True)`` re-verifies every declared payload hash

Payload shapes (audit section 5.2 - MANDATORY support):
    list[dict]                     -> single table
    pandas.DataFrame               -> single table
    pyarrow.Table                  -> single table
    dict[str, list[dict]]          -> one Parquet per logical table
    dict[str, pandas.DataFrame]    -> one Parquet per logical table

dict-of-tables uses scheme A (audit section 5.2): every logical table
gets its own Parquet file; the meta records the table list with each
table's hash/schema/row-count. "Take the first dict value" is FORBIDDEN
- mixed/unsupported shapes raise instead of silently picking a table.

Layout:
    raw/provider=<P>/dataset=<D>/<request_id>.parquet          (single table)
    raw/provider=<P>/dataset=<D>/<request_id>.meta.json
    raw/provider=<P>/dataset=<D>/<request_id>/<table>.parquet  (multi table)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ashare_state.storage.atomic_files import ImmutableFileExistsError, write_file_atomic

#: payload_kind values recorded in the meta document
KIND_ROWS = "rows"
KIND_EMPTY = "empty"
KIND_DATAFRAME = "dataframe"
KIND_ARROW_TABLE = "arrow_table"
KIND_MULTI_ROWS = "multi_table_rows"
KIND_MULTI_FRAMES = "multi_table_frames"

_TABLE_NAME_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


class RawWriterError(RuntimeError):
    """RawWriter contract violation (unsupported shape / id conflict)."""


@dataclass(frozen=True)
class ArtifactRef:
    """CR-1.2 (audit R4-A2.4 section 3.1): one artifact of an exchange,
    separately addressed + hashed (payload artifacts AND the meta)."""

    uri: str
    content_hash: str
    schema_hash: str = ""
    row_count: int = 0


@dataclass(frozen=True)
class TableRecord:
    """One logical table inside a raw artifact (audit section 5.2-A)."""

    name: str | None  # None for single-table payloads
    file: str  # file name relative to the dataset dir
    content_hash: str  # sha256 of the table bytes
    schema_hash: str  # sha256 of the arrow schema
    row_count: int


@dataclass(frozen=True)
class RawWriteResult:
    request_id: str
    logical_uri: str | None  # payload artifact (dir form for multi-table); None for failures
    meta_uri: str
    content_hash: str  # combined hash over all table bytes
    idempotent: bool = False
    payload_kind: str = ""
    row_count: int = 0
    tables: tuple[TableRecord, ...] = field(default_factory=tuple)
    #: the evidence artifact a SpikeCase binds to. CR-1.2: this is ALWAYS
    #: the exchange's .meta.json (whose bytes declare every payload hash),
    #: so payload+meta close bidirectionally under evidence closure.
    evidence_uri: str = ""
    evidence_hash: str = ""
    #: CR-1.2 section 3.1: explicit artifact split
    payload_artifacts: tuple[ArtifactRef, ...] = field(default_factory=tuple)
    meta_artifact: ArtifactRef | None = None


def _scrub(params: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if any(s in str(k).lower() for s in ("password", "token", "secret", "credential")):
            out[str(k)] = "***MASKED***"
        else:
            out[str(k)] = v
    return out


def _is_dataframe_like(obj: Any) -> bool:
    """polars.DataFrame (project stack) or pandas.DataFrame (duck-typed) -
    both are supported tabular payload shapes."""
    return _to_arrow_table(obj) is not None


def _to_arrow_table(obj: Any) -> Any | None:
    """Convert a DataFrame-like object to a pyarrow Table, or None."""
    if isinstance(obj, _pa_table_type()):
        return obj
    if not hasattr(obj, "columns") or not hasattr(obj, "rows"):
        # polars.DataFrame has .columns/.rows; pandas has .columns/.to_records
        # anything else is not a supported DataFrame-like payload
        to_records = getattr(obj, "to_records", None)
        if not (callable(to_records) and hasattr(obj, "index")):
            return None
    to_arrow = getattr(obj, "to_arrow", None)  # polars.DataFrame
    if callable(to_arrow):
        try:
            return to_arrow()
        except TypeError:
            return None
    to_records = getattr(obj, "to_records", None)  # pandas.DataFrame
    if callable(to_records) and hasattr(obj, "columns"):
        import pyarrow as pa

        return pa.Table.from_pandas(obj, preserve_index=False)
    return None


def _pa_table_type() -> type:
    import pyarrow as pa

    return pa.Table


def _rows_to_table(rows: list[dict[str, Any]]) -> Any:
    import pyarrow as pa

    # union of keys across rows, stable order
    columns: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                if key not in columns:
                    columns.append(key)
    data = {
        col: [row.get(col) if isinstance(row, dict) else None for row in rows] for col in columns
    }
    return pa.table(data)


def _empty_table() -> Any:
    import pyarrow as pa

    return pa.table({"_empty": pa.array([], type=pa.int8())})


def _table_bytes(table: Any) -> bytes:
    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def _schema_hash(table: Any) -> str:
    return hashlib.sha256(str(table.schema).encode("utf-8")).hexdigest()


def _safe_table_name(name: str) -> str:
    return _TABLE_NAME_SAFE.sub("_", name) or "table"


def normalize_payload(payload: Any) -> tuple[str, list[tuple[str | None, Any]]]:
    """Classify + normalize a payload into (payload_kind, tables).

    tables is a list of (table_name, arrow_table); table_name is None for
    single-table payloads. Raises RawWriterError for unsupported/mixed
    shapes - never silently picks a dict value (audit section 5.2).
    """
    if payload is None:
        return KIND_EMPTY, [(None, _empty_table())]
    if isinstance(payload, _pa_table_type()):
        return KIND_ARROW_TABLE, [(None, payload)]
    arrow = _to_arrow_table(payload)
    if arrow is not None:
        return KIND_DATAFRAME, [(None, arrow)]
    if isinstance(payload, list):
        if not payload:
            return KIND_EMPTY, [(None, _empty_table())]
        if all(isinstance(r, dict) for r in payload):
            return KIND_ROWS, [(None, _rows_to_table(payload))]
        if any(isinstance(r, dict) for r in payload):
            # mixed dict/scalar rows are a malformed payload - fail loud
            raise RawWriterError(
                "unsupported payload shape: mixed dict/scalar rows "
                f"(element types: {sorted({type(r).__name__ for r in payload})}) - "
                "convert to list[dict] / DataFrame / dict-of-tables explicitly"
            )
        # scalar list (e.g. trade calendar days) -> single 'value' column
        return KIND_ROWS, [(None, _rows_to_table([{"value": r} for r in payload]))]
    if isinstance(payload, dict):
        if not payload:
            return KIND_EMPTY, [(None, _empty_table())]
        values = list(payload.values())
        if all(_is_dataframe_like(v) for v in values):
            converted = [(str(k), _to_arrow_table(v)) for k, v in payload.items()]
            return KIND_MULTI_FRAMES, [(k, t) for k, t in converted if t is not None]
        if all(isinstance(v, list) and all(isinstance(r, dict) for r in v) for v in values):
            return KIND_MULTI_ROWS, [(str(k), _rows_to_table(v)) for k, v in payload.items()]
        raise RawWriterError(
            "unsupported payload shape: dict values must ALL be DataFrames or "
            f"ALL be list[dict] (got value types: {sorted({type(v).__name__ for v in values})}); "
            "silently taking one dict value is forbidden (audit R4-A2.3 section 5.2)"
        )
    raise RawWriterError(
        f"unsupported payload shape {type(payload).__name__}: convert to "
        "list[dict] / DataFrame / pyarrow.Table / dict-of-tables explicitly"
    )


class RawWriter:
    """Persists ProviderExchange results as immutable raw evidence."""

    def __init__(self, raw_root: Path | str, *, ingest_run_id: str = "") -> None:
        self.root = Path(raw_root)
        # CR-1.2 section 3.4: run binding recorded on every meta (empty for
        # non-run usage like unit tests / direct reader access)
        self.ingest_run_id = str(ingest_run_id)

    def _dir_for(self, provider: str, dataset: str) -> Path:
        return self.root / f"provider={provider}" / f"dataset={dataset}"

    # ------------------------------------------------------- unified entry
    def write(
        self,
        exchange: Any,
        *,
        provider: str | None = None,
        dataset: str | None = None,
    ) -> RawWriteResult:
        """CR-1.1 (audit section 3.2-C): persist ONE ProviderExchange.

        - asserts exchange.request_id == exchange.envelope.request_id
        - provider/dataset default to the ENVELOPE's own values; explicit
          arguments that CONFLICT with the envelope raise (no silent
          override)
        - ERROR envelope -> failure evidence (envelope-only meta)
        """
        envelope = getattr(exchange, "envelope", None)
        if envelope is None:
            raise RawWriterError("write() expects a ProviderExchange (missing .envelope)")
        env_request_id = str(getattr(envelope, "request_id", ""))
        if str(getattr(exchange, "request_id", "")) != env_request_id or not env_request_id:
            raise RawWriterError(
                "exchange request_id inconsistency: "
                f"exchange={getattr(exchange, 'request_id', '')!r} "
                f"envelope={env_request_id!r} (audit section 3.2-C)"
            )
        env_provider = str(getattr(envelope, "provider", "") or "amazingdata")
        env_dataset = str(getattr(envelope, "provider_dataset", "") or "")
        if provider is not None and provider != env_provider:
            raise RawWriterError(
                f"provider conflict for request {env_request_id}: envelope says "
                f"{env_provider!r}, caller passed {provider!r} - the envelope is "
                "the source of record (audit section 3.2-C)"
            )
        if dataset is not None and env_dataset and dataset != env_dataset:
            raise RawWriterError(
                f"dataset conflict for request {env_request_id}: envelope says "
                f"{env_dataset!r}, caller passed {dataset!r} - the envelope is "
                "the source of record (audit section 3.2-C)"
            )
        provider_ = env_provider
        dataset_ = env_dataset or (dataset or "unknown")
        if getattr(envelope, "status", "OK") == "ERROR":
            return self._write_failure(provider_, dataset_, exchange)
        return self._write_success(provider_, dataset_, exchange)

    # keep legacy explicit names as thin aliases (backwards compatible)
    def write_success(
        self,
        *,
        provider: str,
        dataset: str,
        request_id: str,
        payload: Any,
        envelope: Any,
    ) -> RawWriteResult:
        """Legacy success entry (kept for compatibility): build the exchange
        inline. New code MUST use write(exchange)."""
        from ashare_state.providers.exchange import ProviderExchange

        envelope = _with_request_id(envelope, request_id, provider=provider, dataset=dataset)
        exchange = ProviderExchange(envelope=envelope, payload=payload)
        return self._write_success(provider, dataset, exchange)

    def write_failure(
        self,
        *,
        provider: str,
        dataset: str,
        request_id: str,
        envelope: Any,
    ) -> RawWriteResult:
        """Legacy failure entry (kept for compatibility)."""
        envelope = _with_request_id(
            envelope, request_id, provider=provider, dataset=dataset, status="ERROR"
        )
        exchange = None  # failure never carries a payload
        from ashare_state.providers.exchange import ProviderExchange

        exchange = ProviderExchange(envelope=envelope, payload=None)
        return self._write_failure(provider, dataset, exchange)

    # ------------------------------------------------------------- success
    def _write_success(self, provider: str, dataset: str, exchange: Any) -> RawWriteResult:
        envelope = exchange.envelope
        request_id = str(envelope.request_id)
        payload_kind, tables = normalize_payload(exchange.payload)

        dataset_dir = self._dir_for(provider, dataset)
        dataset_dir.mkdir(parents=True, exist_ok=True)

        multi = len(tables) > 1 or (len(tables) == 1 and tables[0][0] is not None)
        records: list[TableRecord] = []
        table_files: list[tuple[str | None, Path, bytes]] = []
        if multi:
            table_dir = dataset_dir / request_id
            # P1-02 (audit R4-A2.4 section 9.2): table-name collision after
            # sanitization BLOCKS - two logical tables must never collapse
            # onto the same output file
            file_names = [f"{_safe_table_name(name or 'table')}.parquet" for name, _ in tables]
            if len(set(file_names)) != len(file_names):
                msg = (
                    f"table name collision for request {request_id}: sanitized file "
                    f"names are not unique ({file_names}) - rename the logical tables"
                )
                raise RawWriterError(msg)
            for (name, table), fname in zip(tables, file_names, strict=True):
                payload_bytes = _table_bytes(table)
                records.append(
                    TableRecord(
                        name=name,
                        file=f"{request_id}/{fname}",
                        content_hash=hashlib.sha256(payload_bytes).hexdigest(),
                        schema_hash=_schema_hash(table),
                        row_count=table.num_rows,
                    )
                )
                table_files.append((name, table_dir / fname, payload_bytes))
        else:
            _, table = tables[0]
            payload_bytes = _table_bytes(table)
            records.append(
                TableRecord(
                    name=None,
                    file=f"{request_id}.parquet",
                    content_hash=hashlib.sha256(payload_bytes).hexdigest(),
                    schema_hash=_schema_hash(table),
                    row_count=table.num_rows,
                )
            )
            table_files.append((None, dataset_dir / f"{request_id}.parquet", payload_bytes))

        content_hash = _combined_hash(records)
        meta_path = dataset_dir / f"{request_id}.meta.json"
        row_count = sum(r.row_count for r in records)
        meta_bytes = self._meta_bytes(
            envelope,
            content_hash=content_hash,
            row_count=row_count,
            payload_kind=payload_kind,
            tables=records,
        )

        idem = self._check_idempotent(request_id, records, meta_path, meta_bytes, table_files)
        if not idem:
            self._commit_files(request_id, dataset_dir, meta_path, meta_bytes, table_files)
        # CR-1.2.1 (audit 20260825 section 7.2): an interrupted commit may
        # leave ORPHAN payloads (bytes on disk, no meta anchor). A retry
        # with the SAME bytes RECOVERS the commit (meta lands, idempotent);
        # a retry with DIFFERENT bytes QUARANTINES the orphan (moved under
        # .quarantine/, never mistaken for valid evidence).

        # CR-1.2.3 / R4-A2.7 P0-02 (audit 20260825 #3 section 3): the
        # returned evidence identity MUST describe the PERSISTED bytes, not
        # an unpersisted candidate serialization. On an idempotent retry
        # the disk keeps the FIRST commit's meta (with its ingested_at);
        # hashing the in-memory meta_bytes here would bind callers to a
        # hash that evidence closure can never reproduce. Read the actual
        # file back and hash THOSE bytes.
        persisted_meta_bytes = meta_path.read_bytes()
        if not idem and persisted_meta_bytes != meta_bytes:
            # fresh commit: the bytes on disk must be exactly what we
            # intended to write (write_file_atomic guarantees it; assert)
            msg = (
                f"raw meta write verification failed for request {request_id}: "
                "persisted bytes differ from the intended serialization"
            )
            raise RawWriterError(msg)

        if multi:
            logical_uri = self._logical_uri(provider, dataset, f"{request_id}/")
        else:
            logical_uri = self._logical_uri(provider, dataset, f"{request_id}.parquet")
        # CR-1.2 (audit R4-A2.4 section 3.1): the case evidence is the META
        # - it declares every payload hash, so payload+meta close
        # bidirectionally. Single-table payloads no longer bind the bare
        # parquet (meta deletion/tampering must break the closure).
        evidence_uri = self._logical_uri(provider, dataset, meta_path.name)
        meta_hash = hashlib.sha256(persisted_meta_bytes).hexdigest()
        payload_artifacts = tuple(
            ArtifactRef(
                uri=self._logical_uri(provider, dataset, r.file),
                content_hash=r.content_hash,
                schema_hash=r.schema_hash,
                row_count=r.row_count,
            )
            for r in records
        )
        meta_artifact = ArtifactRef(uri=evidence_uri, content_hash=meta_hash)
        return RawWriteResult(
            request_id=request_id,
            logical_uri=logical_uri,
            meta_uri=self._logical_uri(provider, dataset, meta_path.name),
            content_hash=content_hash,
            idempotent=idem,
            payload_kind=payload_kind,
            row_count=row_count,
            tables=tuple(records),
            evidence_uri=evidence_uri,
            evidence_hash=meta_hash,
            payload_artifacts=payload_artifacts,
            meta_artifact=meta_artifact,
        )

    def _commit_files(
        self,
        request_id: str,
        dataset_dir: Path,
        meta_path: Path,
        meta_bytes: bytes,
        table_files: list[tuple[str | None, Path, bytes]],
    ) -> None:
        """P1-01 (audit R4-A2.4 section 9.1): multi-file atomicity - stage
        ALL payload bytes first, then move each into place, meta LAST. An
        interrupted commit can never leave a meta-anchored partial set (the
        meta is the closure anchor; no meta -> evidence closure BLOCKS)."""
        staging = dataset_dir / f".staging-{request_id[:12]}-{uuid.uuid4().hex[:6]}"
        staged: list[tuple[Path, Path]] = []
        try:
            for _, final_path, payload_bytes in table_files:
                staged_tmp = staging / final_path.name
                write_file_atomic(staged_tmp, payload_bytes, staging_dir=staging)
                staged.append((final_path, staged_tmp))
            # every payload byte is safely on disk in staging -> move each
            # into its final position (os.replace is atomic per file).
            # CR-1.2.1 recovery: a final path that ALREADY exists with the
            # SAME bytes (orphan from an interrupted commit) is skipped -
            # the retry completes the commit by landing the missing meta.
            for final_path, staged_tmp in staged:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                if final_path.exists():
                    if final_path.read_bytes() == staged_tmp.read_bytes():
                        staged_tmp.unlink(missing_ok=True)
                        continue
                    msg = (
                        f"raw artifact conflict for request {request_id}: "
                        f"{final_path} already exists with different bytes"
                    )
                    raise RawWriterError(msg)
                os.replace(staged_tmp, final_path)  # noqa: PTH105 - os.replace is the atomic primitive
            # the meta (closure anchor) lands only after ALL payloads
            write_file_atomic(meta_path, meta_bytes)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # ------------------------------------------------------------- failure
    def _write_failure(self, provider: str, dataset: str, exchange: Any) -> RawWriteResult:
        """Persist a FAILURE exchange: envelope-only evidence (the request
        audit record is retained even with no payload)."""
        envelope = exchange.envelope
        request_id = str(envelope.request_id)
        dataset_dir = self._dir_for(provider, dataset)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        meta_path = dataset_dir / f"{request_id}.meta.json"
        meta_bytes = self._meta_bytes(
            envelope, content_hash="", row_count=0, payload_kind="failure", tables=()
        )
        if meta_path.exists():
            # failure evidence is append-only too: same request id twice
            # with failure is suspicious - block unless byte-identical
            # (ignoring the ingested_at wall-clock, CR-1.2)
            if _same_meta_ignoring_time(meta_path.read_bytes(), meta_bytes):
                meta_hash = hashlib.sha256(meta_path.read_bytes()).hexdigest()
                return RawWriteResult(
                    request_id=request_id,
                    logical_uri=None,
                    meta_uri=self._logical_uri(provider, dataset, meta_path.name),
                    content_hash=meta_hash,
                    idempotent=True,
                    payload_kind="failure",
                    evidence_uri=self._logical_uri(provider, dataset, meta_path.name),
                    evidence_hash=meta_hash,
                    meta_artifact=ArtifactRef(
                        uri=self._logical_uri(provider, dataset, meta_path.name),
                        content_hash=meta_hash,
                    ),
                )
            msg = (
                f"raw failure-evidence conflict for request {request_id}: "
                "different envelope bytes for the same request"
            )
            raise RawWriterError(msg)
        write_file_atomic(meta_path, meta_bytes)
        meta_hash = hashlib.sha256(meta_bytes).hexdigest()
        meta_ref = ArtifactRef(
            uri=self._logical_uri(provider, dataset, meta_path.name), content_hash=meta_hash
        )
        return RawWriteResult(
            request_id=request_id,
            logical_uri=None,
            meta_uri=self._logical_uri(provider, dataset, meta_path.name),
            content_hash=meta_hash,
            payload_kind="failure",
            evidence_uri=self._logical_uri(provider, dataset, meta_path.name),
            evidence_hash=meta_hash,
            meta_artifact=meta_ref,
        )

    # ---------------------------------------------------------------- read
    def read(self, *, provider: str, dataset: str, request_id: str, verify: bool = True) -> Any:
        """Read back a persisted payload: DataFrame for single-table kinds,
        dict[str, DataFrame] for multi-table kinds (lossless round-trip
        support for audit section 5.3 tests). Uses polars - the project
        data stack (pandas is NOT a project dependency).

        P1-03 (audit R4-A2.4 section 9.3): ``verify=True`` re-checks every
        declared payload hash BEFORE returning data."""
        import polars as pl

        dataset_dir = self._dir_for(provider, dataset)
        meta_path = dataset_dir / f"{request_id}.meta.json"
        if not meta_path.is_file():
            raise RawWriterError(f"no raw meta for request {request_id} under {dataset_dir}")
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        if verify:
            problems = verify_meta_closure(dataset_dir, doc)
            if problems:
                msg = (
                    f"raw integrity verification failed for request {request_id}: "
                    f"{'; '.join(problems)}"
                )
                raise RawWriterError(msg)
        kind = str(doc.get("payload_kind", ""))
        if kind in (KIND_MULTI_ROWS, KIND_MULTI_FRAMES):
            frames: dict[str, Any] = {}
            for table in doc.get("tables", []):
                path = dataset_dir / str(table.get("file", ""))
                frames[str(table.get("name", ""))] = pl.read_parquet(path)
            return frames
        if kind == KIND_EMPTY:
            return pl.DataFrame()
        # single table
        return pl.read_parquet(dataset_dir / f"{request_id}.parquet")

    # ------------------------------------------------------------- helpers
    def _check_idempotent(
        self,
        request_id: str,
        records: list[TableRecord],
        meta_path: Path,
        meta_bytes: bytes,
        table_files: list[tuple[str | None, Path, bytes]],
    ) -> bool:
        """Same request id: idempotent no-op iff every existing byte matches
        the new bytes; any difference BLOCKS (immutable raw store). The
        wall-clock ``ingested_at`` is excluded from the comparison.

        CR-1.2.1 orphan recovery (audit 20260825 section 7.2):
        - meta MISSING + payloads present (interrupted commit): same bytes
          -> RECOVER (the caller writes the meta, idempotent=True);
          different bytes -> QUARANTINE the orphan files and BLOCK.
        - meta present + payload missing: tamper/partial -> BLOCK."""
        meta_exists = meta_path.is_file()
        payload_exists = any(p.exists() for _, p, _ in table_files)
        if not meta_exists and not payload_exists:
            return False
        if not meta_exists and payload_exists:
            # orphan payload set without its meta anchor. A PARTIAL set
            # (some members missing) can still recover: every PRESENT
            # member must byte-match the retry's declaration (the missing
            # members are simply written by _commit_files).
            present_same = all(p.read_bytes() == b for _, p, b in table_files if p.is_file())
            unexpected = self._unexpected_orphan_files(request_id, table_files)
            if present_same and not unexpected:
                # same-request retry after an interrupted commit: land the
                # meta now (recovery); _commit_files will write ONLY the
                # missing pieces (payload moves are no-ops for existing
                # bytes via the staging path's exists-check)
                self._commit_files(request_id, meta_path.parent, meta_path, meta_bytes, table_files)
                return True
            if unexpected:
                # R4-A2.6 section 8: the orphan set contains bytes the retry
                # does NOT declare - adopting them would fabricate evidence;
                # quarantine the whole set
                self._quarantine_orphans(request_id, table_files)
                self._quarantine_unexpected(request_id, unexpected)
                self._cleanup_empty_request_dirs(request_id, table_files)
                msg = (
                    f"raw orphan-payload conflict for request {request_id}: the "
                    "orphan set contains files the retry does not declare "
                    f"({sorted(p.name for p in unexpected)}) - the whole set was "
                    "moved to .quarantine/ (audit R4-A2.6 section 8)"
                )
                raise RawWriterError(msg)
            self._quarantine_orphans(request_id, table_files)
            self._cleanup_empty_request_dirs(request_id, table_files)
            msg = (
                f"raw orphan-payload conflict for request {request_id}: an "
                "interrupted commit left payload bytes without a meta anchor, "
                "and the retry carries DIFFERENT bytes - the orphan set was "
                "moved to .quarantine/ (audit 20260825 section 7.2-D)"
            )
            raise RawWriterError(msg)
        same_meta = meta_path.is_file() and _same_meta_ignoring_time(
            meta_path.read_bytes(), meta_bytes
        )
        same_tables = all(p.is_file() and p.read_bytes() == b for _, p, b in table_files)
        if same_meta and same_tables:
            return True
        msg = (
            f"raw artifact conflict for request {request_id}: same request id "
            "with different content - immutable raw store"
        )
        raise RawWriterError(msg)

    @staticmethod
    def _unexpected_orphan_files(
        request_id: str, table_files: list[tuple[str | None, Path, bytes]]
    ) -> list[Path]:
        """R4-A2.6 section 8: files inside the orphan request dir that the
        retry's declaration does NOT cover (an interrupted multi-table
        commit can never legitimately leave such files)."""
        declared = {p.name for _, p, _ in table_files}
        expected_dirs = {p.parent for _, p, _ in table_files}
        unexpected: list[Path] = []
        for parent in expected_dirs:
            if parent.name == request_id and parent.is_dir():
                for member in parent.glob("*.parquet"):
                    if member.name not in declared:
                        unexpected.append(member)
        return unexpected

    @staticmethod
    def _quarantine_unexpected(request_id: str, files: list[Path]) -> None:
        """Move undeclared orphan members under the dataset's .quarantine/
        (inspectable, never active evidence)."""
        for path in files:
            quarantine_dir = path.parent.parent / ".quarantine"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            target = quarantine_dir / f"{request_id}-{path.name}"
            counter = 0
            while target.exists():
                counter += 1
                target = quarantine_dir / f"{request_id}-{counter}-{path.name}"
            path.replace(target)  # atomic move within the dataset dir

    @staticmethod
    def _quarantine_orphans(
        request_id: str, table_files: list[tuple[str | None, Path, bytes]]
    ) -> None:
        """Move conflicting orphan payloads under the dataset's .quarantine/
        so they can never be mistaken for valid evidence (they stay
        inspectable for incident forensics; the write itself BLOCKS with
        RawWriterError)."""
        for _, path, _bytes in table_files:
            if not path.is_file():
                continue
            # single-table payloads sit in the dataset dir; multi-table
            # payloads sit in <dataset_dir>/<request_id>/
            dataset_dir = path.parent.parent if path.parent.name == request_id else path.parent
            quarantine_dir = dataset_dir / ".quarantine"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            target = quarantine_dir / f"{request_id}-{path.name}"
            counter = 0
            while target.exists():  # keep earlier quarantine evidence
                counter += 1
                target = quarantine_dir / f"{request_id}-{counter}-{path.name}"
            path.replace(target)  # atomic move within the dataset dir

    @staticmethod
    def _cleanup_empty_request_dirs(
        request_id: str, table_files: list[tuple[str | None, Path, bytes]]
    ) -> None:
        """Drop request dirs left empty by quarantine (never leave a
        misleading empty skeleton behind)."""
        from shutil import rmtree

        dataset_dirs = {
            p.parent.parent if p.parent.name == request_id else p.parent for _, p, _ in table_files
        }
        for dataset_dir in dataset_dirs:
            request_dir = dataset_dir / request_id
            if request_dir.is_dir() and not any(request_dir.iterdir()):
                rmtree(request_dir, ignore_errors=True)

    def _meta_bytes(
        self,
        envelope: Any,
        *,
        content_hash: str,
        row_count: int,
        payload_kind: str,
        tables: tuple[TableRecord, ...] | list[TableRecord],
    ) -> bytes:
        doc = {
            "request_id": getattr(envelope, "request_id", ""),
            "provider": getattr(envelope, "provider", "amazingdata"),
            "provider_dataset": getattr(envelope, "provider_dataset", ""),
            "endpoint": getattr(envelope, "endpoint", ""),
            # CR-2.1 (audit 20260831 §2): the SYSTEM-DERIVED business
            # surface identity of the exchange - persisted by the
            # provider facade, consumed by the normalization typed
            # routing. Legacy evidence without the field fails closed
            # on ambiguous (dataset, endpoint) pairs.
            "normalization_surface": getattr(envelope, "normalization_surface", "") or "",
            "request_params_hash": getattr(envelope, "request_params_hash", ""),
            "requested_at": getattr(envelope, "requested_at", ""),
            "received_at": getattr(envelope, "received_at", ""),
            "sdk_version": getattr(envelope, "sdk_version", None),
            "runtime_version": getattr(envelope, "runtime_version", None),
            "account_profile_id": getattr(envelope, "account_profile_id", "UNKNOWN"),
            "status": getattr(envelope, "status", "OK"),
            "error_class": getattr(envelope, "error_class", None),
            "duration_ms": getattr(envelope, "duration_ms", 0.0),
            "attempt_count": getattr(envelope, "attempt_count", 1),
            "capability_status": getattr(envelope, "capability_status", None),
            "row_count": row_count,
            "content_hash": content_hash,
            "payload_kind": payload_kind,
            "request_params": _scrub(getattr(envelope, "request_params", None)),
            "ingested_at": datetime.now(UTC).isoformat(),
            "ingest_run_id": self.ingest_run_id,
            "tables": [
                {
                    "name": t.name,
                    "file": t.file,
                    "content_hash": t.content_hash,
                    "schema_hash": t.schema_hash,
                    "row_count": t.row_count,
                }
                for t in tables
            ],
        }
        return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")

    def _logical_uri(self, provider: str, dataset: str, filename: str) -> str:
        # cross-platform logical URI: relative, forward slashes (audit 46)
        return f"provider={provider}/dataset={dataset}/{filename}"


def _same_meta_ignoring_time(existing: bytes, incoming: bytes) -> bool:
    """Byte-compare two meta docs ignoring the wall-clock ``ingested_at``."""
    try:
        a = json.loads(existing)
        b = json.loads(incoming)
    except json.JSONDecodeError:  # pragma: no cover - corrupted meta
        return False
    a.pop("ingested_at", None)
    b.pop("ingested_at", None)
    return a == b


def list_orphan_payloads(raw_root: Path | str) -> list[str]:
    """CR-1.2.1 (audit 20260825 section 7.2-C): detect ORPHAN payloads -
    parquet bytes on disk whose exchange meta anchor is missing (an
    interrupted multi-file commit, or tampering). Returns logical refs
    (provider=.../dataset=.../<file>) for incident forensics; a healthy
    raw store yields an empty list.

    Orphan shapes:
      - <request_id>.parquet with no <request_id>.meta.json
      - <request_id>/<table>.parquet with no <request_id>.meta.json
    """
    root = Path(raw_root)
    orphans: list[str] = []
    if not root.is_dir():
        return orphans
    for dataset_dir in sorted(root.glob("provider=*/dataset=*")):
        for path in sorted(dataset_dir.rglob("*.parquet")):
            rel = path.relative_to(root).as_posix()
            if ".staging" in path.parts or ".quarantine" in path.parts:
                continue
            # meta for a nested table lives at ../<request_id>.meta.json
            request_id = path.stem if path.parent == dataset_dir else path.parent.name
            meta = dataset_dir / f"{request_id}.meta.json"
            if not meta.is_file():
                orphans.append(rel)
    return orphans


def verify_meta_closure(raw_root: Path | str, meta_doc: dict[str, Any]) -> list[str]:
    """CR-1.2 (audit R4-A2.4 section 3.1): verify the payload+meta closure
    of ONE exchange meta document against the bytes on disk.

    Checks (each failure is a returned problem):
      - every declared table file exists and its sha256 equals the declared
        content_hash (payload tamper / partial set detection)
      - the combined content_hash over the declared tables recomputes
    Returns an empty list when the closure holds."""
    root = Path(raw_root)
    problems: list[str] = []
    tables = meta_doc.get("tables") or []
    for table in tables:
        rel = str(table.get("file", ""))
        path = root / rel
        if not path.is_file():
            problems.append(f"payload artifact missing: {rel}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(table.get("content_hash", "")):
            problems.append(f"payload hash mismatch: {rel}")
    if tables and not problems:
        records = [
            TableRecord(
                name=t.get("name"),
                file=str(t.get("file", "")),
                content_hash=str(t.get("content_hash", "")),
                schema_hash=str(t.get("schema_hash", "")),
                row_count=int(t.get("row_count", 0) or 0),
            )
            for t in tables
        ]
        if _combined_hash(records) != str(meta_doc.get("content_hash", "")):
            problems.append("combined content_hash does not recompute from tables")
    return problems


def _with_request_id(
    envelope: Any, request_id: str, *, provider: str, dataset: str, status: str = "OK"
) -> Any:
    """Legacy-entry helper: rebuild the envelope with explicit request_id /
    provider / dataset (used only by the compatibility wrappers)."""
    from dataclasses import replace

    return replace(
        envelope,
        request_id=request_id,
        provider=provider,
        provider_dataset=dataset,
        status=status,
    )


def _combined_hash(records: list[TableRecord]) -> str:
    """Single-table payloads keep the classic content-hash semantics (the
    sha256 of the payload artifact bytes); multi-table payloads hash the
    sorted (file, table-hash) pairs of every table."""
    if len(records) == 1 and records[0].name is None:
        return records[0].content_hash
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda r: r.file):
        digest.update(record.file.encode("utf-8"))
        digest.update(b":")
        digest.update(record.content_hash.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


__all__ = [
    "ArtifactRef",
    "ImmutableFileExistsError",
    "RawWriteResult",
    "RawWriter",
    "RawWriterError",
    "TableRecord",
    "list_orphan_payloads",
    "verify_meta_closure",
]
