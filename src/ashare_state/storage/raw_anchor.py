"""Raw evidence trust anchor ledger (CR-2.3, audit 20260901 section 3).

THE PROBLEM THIS MODULE CLOSES: before CR-2.3 the first normalization
run of a request treated the meta bytes it happened to see as the
initial trusted baseline - ``verify_meta_closure()`` proves payload
hashes against the meta's OWN declarations, but nothing outside the
raw filesystem proved the meta itself was still the exact bytes
RawWriter committed. A first-consume tamper that only edits
non-payload-hash fields (normalization_surface / endpoint / request
params / account) could launder itself into the initial truth.

THE ANCHOR: the governed ingestion control flow rereads the persisted
meta bytes the moment RawWriter commits them (meta lands LAST) and
persists the EXACT-BYTE SHA-256 into ``meta_raw_evidence_anchor``
(migration 017) - a DuckDB ledger OUTSIDE the raw filesystem.
Normalization then looks up the EXPECTED evidence hash here BEFORE any
routing/mapping; the current bytes must equal the anchor or the run
fails closed.

Rulings (audit section 3.3):

- the runner never treats its first-seen meta hash as a trust root;
- the expected hash is NEVER a normalization caller parameter;
- ``evidence_conflict`` (migration 016) is demoted to a diagnostic
  attribute - the anchor is the single correctness trust root;
- legacy raw WITHOUT an anchor fails closed (no auto-grandfathering:
  a 015-era laundering history can never be silently blessed by an
  upgrade; re-ingest is the governed repair path);
- recording the same request id with DIFFERENT meta bytes is a hard
  anchor conflict (RawAnchorError) - the anchor ledger itself is
  append-only-truth, one immutable identity per request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

__all__ = [
    "RawAnchorError",
    "RawEvidenceAnchor",
    "lookup_raw_evidence_anchor",
    "record_raw_evidence_anchor",
]


class RawAnchorError(RuntimeError):
    """The raw evidence anchor contract was violated (missing meta /
    unreadable meta / conflicting anchor identity)."""


@dataclass(frozen=True)
class RawEvidenceAnchor:
    """One authoritative ingestion-time anchor of a persisted raw meta."""

    provider: str
    provider_dataset: str
    request_id: str
    evidence_uri: str
    evidence_hash: str
    endpoint: str
    operation_id: str
    normalization_surface: str
    payload_kind: str
    ingest_run_id: str
    created_at: str


_ANCHOR_COLUMNS = (
    "provider",
    "provider_dataset",
    "request_id",
    "evidence_uri",
    "evidence_hash",
    "endpoint",
    "operation_id",
    "normalization_surface",
    "payload_kind",
    "ingest_run_id",
    "created_at",
)


def _meta_path(raw_root: Path, provider: str, provider_dataset: str, request_id: str) -> Path:
    return (
        raw_root
        / f"provider={provider}"
        / f"dataset={provider_dataset}"
        / f"{request_id}.meta.json"
    )


def record_raw_evidence_anchor(
    conn: DuckDBPyConnection,
    raw_root: Path | str,
    *,
    provider: str,
    provider_dataset: str,
    request_id: str,
    ingest_run_id: str | None = None,
) -> RawEvidenceAnchor:
    """Governed ingestion-time anchoring: reread the persisted meta
    EXACT BYTES, hash them, and persist the authoritative anchor row.

    Called by the ingestion control flow right after RawWriter commits
    the meta (the meta lands LAST - see RawWriter). Idempotent for the
    SAME bytes; a DIFFERENT-bytes re-record of the same request is a
    hard anchor conflict (the raw store is immutable - this is an
    integrity breach, never a re-baselining opportunity)."""
    root = Path(raw_root)
    meta_path = _meta_path(root, provider, provider_dataset, request_id)
    if not meta_path.is_file():
        msg = (
            f"cannot anchor request {request_id!r}: no persisted raw meta at "
            f"{meta_path} - anchors are recorded at ingestion time only "
            "(CR-2.3 audit 20260901 section 3.3)"
        )
        raise RawAnchorError(msg)
    meta_bytes = meta_path.read_bytes()
    evidence_hash = hashlib.sha256(meta_bytes).hexdigest()
    try:
        doc: dict[str, Any] = json.loads(meta_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"cannot anchor request {request_id!r}: raw meta unreadable: {exc}"
        raise RawAnchorError(msg) from exc

    existing = lookup_raw_evidence_anchor(
        conn, provider=provider, provider_dataset=provider_dataset, request_id=request_id
    )
    if existing is not None:
        if existing.evidence_hash != evidence_hash:
            msg = (
                f"raw evidence anchor CONFLICT for request {request_id!r}: the "
                f"anchor ledger binds {existing.evidence_hash[:16]}... but the "
                f"current persisted meta bytes hash to {evidence_hash[:16]}... - "
                "the raw store is immutable; investigate (an anchor is never "
                "re-baselined)"
            )
            raise RawAnchorError(msg)
        return existing

    anchor = RawEvidenceAnchor(
        provider=provider,
        provider_dataset=provider_dataset,
        request_id=request_id,
        evidence_uri=(f"provider={provider}/dataset={provider_dataset}/{request_id}.meta.json"),
        evidence_hash=evidence_hash,
        endpoint=str(doc.get("endpoint") or ""),
        operation_id=str(doc.get("operation_id") or ""),
        normalization_surface=str(doc.get("normalization_surface") or ""),
        payload_kind=str(doc.get("payload_kind") or ""),
        ingest_run_id=str(ingest_run_id or doc.get("ingest_run_id") or ""),
        created_at=datetime.now(UTC).isoformat(),
    )
    conn.execute(
        f"INSERT INTO meta_raw_evidence_anchor ({', '.join(_ANCHOR_COLUMNS)}) "
        f"VALUES ({', '.join(['?'] * len(_ANCHOR_COLUMNS))})",
        [
            anchor.provider,
            anchor.provider_dataset,
            anchor.request_id,
            anchor.evidence_uri,
            anchor.evidence_hash,
            anchor.endpoint,
            anchor.operation_id,
            anchor.normalization_surface,
            anchor.payload_kind,
            anchor.ingest_run_id,
            anchor.created_at,
        ],
    )
    return anchor


def lookup_raw_evidence_anchor(
    conn: DuckDBPyConnection,
    *,
    provider: str,
    provider_dataset: str,
    request_id: str,
) -> RawEvidenceAnchor | None:
    """Read-only exact anchor lookup (None = no authoritative anchor:
    legacy raw - CR-2 fails closed on it)."""
    row = conn.execute(
        f"SELECT {', '.join(_ANCHOR_COLUMNS)} FROM meta_raw_evidence_anchor "
        "WHERE provider = ? AND provider_dataset = ? AND request_id = ?",
        [provider, provider_dataset, request_id],
    ).fetchone()
    if row is None:
        return None
    values = tuple(str(v) if v is not None else "" for v in row)
    return RawEvidenceAnchor(*values)
