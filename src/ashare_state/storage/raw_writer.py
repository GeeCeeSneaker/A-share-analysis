"""RawWriter: immutable provider evidence runtime (CR-1b, audit section 45-46).

Contract:
- SUCCESS exchange  -> raw artifact (Parquet for tabular payloads) +
                       .meta.json (envelope), immutable
- FAILURE exchange  -> failure evidence (envelope-only .meta.json), the
                       request audit record is NEVER dropped
- Idempotent: same request + same content hash -> no-op
- Conflict: same request + different bytes -> BLOCK
- Lossless: structured tabular payloads go to Parquet; never repr()
- Secret-scrubbed: params are scrubbed before persisting
- Cross-platform logical URI: relative, forward slashes, no drive letters

Layout:
    raw/provider=amazingdata/dataset=<D>/<request_id>.parquet
    raw/provider=amazingdata/dataset=<D>/<request_id>.meta.json
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_state.storage.atomic_files import ImmutableFileExistsError, write_file_atomic


class RawWriterError(RuntimeError):
    """RawWriter contract violation."""


@dataclass(frozen=True)
class RawWriteResult:
    request_id: str
    logical_uri: str | None  # None for failure evidence (no payload file)
    meta_uri: str
    content_hash: str
    idempotent: bool = False


def _scrub(params: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (params or {}).items():
        if any(s in str(k).lower() for s in ("password", "token", "secret", "credential")):
            out[str(k)] = "***MASKED***"
        else:
            out[str(k)] = v
    return out


class RawWriter:
    """Persists ProviderExchange results as immutable raw evidence."""

    def __init__(self, raw_root: Path | str) -> None:
        self.root = Path(raw_root)

    def _dir_for(self, provider: str, dataset: str) -> Path:
        return self.root / f"provider={provider}" / f"dataset={dataset}"

    # ------------------------------------------------------------- success
    def write_success(
        self,
        *,
        provider: str,
        dataset: str,
        request_id: str,
        payload: Any,
        envelope: Any,
    ) -> RawWriteResult:
        """Persist a SUCCESS exchange: payload + envelope metadata."""
        dataset_dir = self._dir_for(provider, dataset)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        payload_path = dataset_dir / f"{request_id}.parquet"
        meta_path = dataset_dir / f"{request_id}.meta.json"

        # lossless tabular serialization (audit section 46: never repr())
        rows = _rows_of(payload)
        payload_bytes = _to_parquet_bytes(rows)
        content_hash = hashlib.sha256(payload_bytes).hexdigest()
        meta_bytes = self._meta_bytes(envelope, content_hash, len(rows))

        idem = False
        if payload_path.exists() or meta_path.exists():
            existing_hash = _existing_hash(payload_path)
            if existing_hash == content_hash and meta_path.exists():
                idem = True  # same content: idempotent no-op
            else:
                msg = (
                    f"raw artifact conflict for request {request_id}: same "
                    "request id with different content - immutable raw store"
                )
                raise RawWriterError(msg)
        if not idem:
            write_file_atomic(payload_path, payload_bytes)
            write_file_atomic(meta_path, meta_bytes)
        return RawWriteResult(
            request_id=request_id,
            logical_uri=self._logical_uri(provider, dataset, payload_path.name),
            meta_uri=self._logical_uri(provider, dataset, meta_path.name),
            content_hash=content_hash,
            idempotent=idem,
        )

    # ------------------------------------------------------------- failure
    def write_failure(
        self,
        *,
        provider: str,
        dataset: str,
        request_id: str,
        envelope: Any,
    ) -> RawWriteResult:
        """Persist a FAILURE exchange: envelope-only evidence (the request
        audit record is retained even with no payload)."""
        dataset_dir = self._dir_for(provider, dataset)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        meta_path = dataset_dir / f"{request_id}.meta.json"
        if meta_path.exists():
            # failure evidence is append-only too: same request id twice
            # with failure is suspicious - block unless byte-identical
            meta_bytes = self._meta_bytes(envelope, "", 0)
            if meta_path.read_bytes() == meta_bytes:
                return RawWriteResult(
                    request_id=request_id,
                    logical_uri=None,
                    meta_uri=self._logical_uri(provider, dataset, meta_path.name),
                    content_hash=hashlib.sha256(meta_bytes).hexdigest(),
                    idempotent=True,
                )
            msg = (
                f"raw failure-evidence conflict for request {request_id}: "
                "different envelope bytes for the same request"
            )
            raise RawWriterError(msg)
        meta_bytes = self._meta_bytes(envelope, "", 0)
        write_file_atomic(meta_path, meta_bytes)
        return RawWriteResult(
            request_id=request_id,
            logical_uri=None,
            meta_uri=self._logical_uri(provider, dataset, meta_path.name),
            content_hash=hashlib.sha256(meta_bytes).hexdigest(),
        )

    # ------------------------------------------------------------- helpers
    def _meta_bytes(self, envelope: Any, content_hash: str, row_count: int) -> bytes:
        doc = {
            "request_id": getattr(envelope, "request_id", ""),
            "provider": getattr(envelope, "provider", "amazingdata"),
            "provider_dataset": getattr(envelope, "provider_dataset", ""),
            "endpoint": getattr(envelope, "endpoint", ""),
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
        }
        return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")

    def _logical_uri(self, provider: str, dataset: str, filename: str) -> str:
        # cross-platform logical URI: relative, forward slashes (audit 46)
        return f"provider={provider}/dataset={dataset}/{filename}"


def _rows_of(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        for value in payload.values():
            if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
                return list(value)
        return []
    if isinstance(payload, list):
        return list(payload)
    return [payload]


def _to_parquet_bytes(rows: list[dict[str, Any]]) -> bytes:
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    if not rows:
        # empty-but-typed artifact
        table = pa.table({"_empty": pa.array([], type=pa.int8())})
    else:
        # union of keys across rows, stable order
        columns: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                for key in row:
                    if key not in columns:
                        columns.append(key)
        data = {
            col: [row.get(col) if isinstance(row, dict) else None for row in rows]
            for col in columns
        }
        table = pa.table(data)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def _existing_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "ImmutableFileExistsError",
    "RawWriteResult",
    "RawWriter",
    "RawWriterError",
]
