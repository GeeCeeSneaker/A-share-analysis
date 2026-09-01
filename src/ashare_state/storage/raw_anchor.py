"""Raw evidence trust anchor ledger + the anchored ingestion boundary
(CR-2.3 audit 20260901 section 3 + CR-2.4 audit 20260901 section 3).

THE PROBLEM CR-2.3 CLOSED: the first normalization run of a request
treated the meta bytes it happened to see as the initial trusted
baseline - ``verify_meta_closure()`` proves payload hashes against the
meta's OWN declarations, but nothing outside the raw filesystem proved
the meta itself was still the exact bytes RawWriter committed. A
first-consume tamper that only edits non-payload-hash fields
(normalization_surface / endpoint / request params / account) could
launder itself into the initial truth.

THE ANCHOR: the governed ingestion control flow persists the
EXACT-BYTE SHA-256 of the committed meta into
``meta_raw_evidence_anchor`` (migration 017) - a DuckDB ledger OUTSIDE
the raw filesystem. Normalization looks up the EXPECTED evidence hash
here BEFORE any routing/mapping; the current bytes must equal the
anchor or the run fails closed.

THE PROBLEM CR-2.4 CLOSED (audit 20260901 section 2): CR-2.3 shipped
the anchor LEDGER and the runner-side verification, but the enrollment
primitive was a freely callable function hashing whatever meta bytes
it found at call time:

- the real production evidence path (``ProbeContext.evidence_from_
  exchange``) never recorded an anchor - tests passed only because a
  test helper emulated the governed flow by hand;
- the recorder hashed "the meta bytes it happens to see" instead of
  binding the identity RawWriter just committed, leaving a
  write -> enroll TOCTOU window where late-tampered bytes (H2) could
  be blessed as the first truth;
- nothing stopped an ordinary production path from writing raw
  evidence and simply never enrolling an anchor.

CR-2.4 replaces that with the ONE production-owned persistence
boundary::

    AnchoredRawEvidenceWriter.write_exchange(exchange)
        RawWriter.write(exchange)          # file-side commit (meta LAST)
        reread the persisted meta bytes    # VERIFY-ONLY
        require sha256(reread) == RawWriteResult.evidence_hash
        require meta uri == the commit's own uri
        require meta identity fields == the exchange envelope's
                provider-owned identity (request/provider/dataset/
                endpoint/normalization_surface/operation_id)
        enroll the immutable anchor keyed to the COMMIT identity
        return RawWriteResult              # ingest is only NOW complete

Rulings (CR-2.4 audit sections 3.1-3.4):

- the anchor expected hash is ALWAYS the RawWriter COMMIT identity
  (``RawWriteResult.evidence_hash`` - itself hashed from the persisted
  bytes); the reread inside the boundary is verify-only and can never
  define a first truth of its own;
- a write -> enroll TOCTOU tamper (bytes swapped after commit) makes
  the whole ingest FAIL LOUDLY - H2 is never enrolled;
- an anchor-enrollment DB failure fails the ingest (the evidence is
  NOT "ready"); the raw bytes survive without an anchor, so
  normalization keeps failing closed until the exact retry completes
  the enrollment (RawWriter is idempotent on the same bytes -> the
  same commit identity -> one immutable anchor);
- an anchor is never re-baselined: same hash = idempotent, different
  hash = hard conflict;
- the enrollment primitive is PRIVATE. The public production surface
  is the anchored writer (+ the read-only lookup). Tests needing
  legacy/unanchored fixtures use the private primitive directly
  (tests-only, same ruling as the B2 scanner static registry).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.storage.raw_writer import RawWriter, RawWriteResult

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

__all__ = [
    "AnchoredRawEvidenceWriter",
    "RawAnchorError",
    "RawEvidenceAnchor",
    "lookup_raw_evidence_anchor",
    "persist_exchange_with_anchor",
]


class RawAnchorError(RuntimeError):
    """The raw evidence anchor contract was violated (missing meta /
    unreadable meta / TOCTOU bytes drift / identity cross-binding
    mismatch / conflicting anchor identity)."""


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

#: envelope identity fields cross-bound against the persisted meta on
#: every anchored write (CR-2.4 audit section 3.1: "require meta
#: request/provider/dataset/operation_id/surface == exchange envelope")
_ENVELOPE_IDENTITY_FIELDS = (
    "request_id",
    "provider",
    "provider_dataset",
    "endpoint",
    "normalization_surface",
    "operation_id",
)


def _meta_path(raw_root: Path, provider: str, provider_dataset: str, request_id: str) -> Path:
    return (
        raw_root
        / f"provider={provider}"
        / f"dataset={provider_dataset}"
        / f"{request_id}.meta.json"
    )


def _enroll_anchor(
    conn: DuckDBPyConnection,
    raw_root: Path | str,
    *,
    provider: str,
    provider_dataset: str,
    request_id: str,
    evidence_hash: str,
    ingest_run_id: str = "",
) -> RawEvidenceAnchor:
    """PRIVATE enrollment primitive (CR-2.4 audit section 3.4).

    Enrolls the anchor for an ALREADY-COMMITTED raw meta. The expected
    hash is a CALLER-DECLARED commit identity (RawWriteResult.
    evidence_hash on the production path); this function only VERIFIES
    it against the persisted bytes - it never hashes the current bytes
    into a first truth of its own. Production callers reach it
    exclusively through :class:`AnchoredRawEvidenceWriter`; tests use
    it directly ONLY to fabricate governed-reingest fixtures.
    """
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
    # verify-only: the declared commit identity must equal the on-disk truth
    if hashlib.sha256(meta_bytes).hexdigest() != str(evidence_hash):
        msg = (
            f"cannot anchor request {request_id!r}: the declared commit "
            f"evidence hash {str(evidence_hash)[:16]}... does not match the "
            f"persisted meta bytes (sha256 {hashlib.sha256(meta_bytes).hexdigest()[:16]}...) "
            "- enrollment never redefines the first truth"
        )
        raise RawAnchorError(msg)
    try:
        doc: dict[str, Any] = json.loads(meta_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"cannot anchor request {request_id!r}: raw meta unreadable: {exc}"
        raise RawAnchorError(msg) from exc

    existing = lookup_raw_evidence_anchor(
        conn, provider=provider, provider_dataset=provider_dataset, request_id=request_id
    )
    if existing is not None:
        if existing.evidence_hash != str(evidence_hash):
            msg = (
                f"raw evidence anchor CONFLICT for request {request_id!r}: the "
                f"anchor ledger binds {existing.evidence_hash[:16]}... but the "
                f"current persisted meta bytes hash to {str(evidence_hash)[:16]}... - "
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
        evidence_hash=str(evidence_hash),
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


class AnchoredRawEvidenceWriter:
    """CR-2.4: the ONE production-owned raw evidence persistence
    boundary. ``RawWriter`` file commits and anchor enrollment are
    INDIVISIBLE here - ordinary production code has no path that
    writes provider evidence without enrolling an anchor, and the
    enrolled hash is always the identity of the commit that just
    happened (never a late re-hash of whatever bytes happen to be on
    disk)."""

    def __init__(
        self,
        conn: DuckDBPyConnection,
        raw_root: Path | str,
        *,
        ingest_run_id: str = "",
    ) -> None:
        self._conn = conn
        self._root = Path(raw_root)
        self._writer = RawWriter(raw_root, ingest_run_id=ingest_run_id)

    @property
    def ingest_run_id(self) -> str:
        return self._writer.ingest_run_id

    # ------------------------------------------------------------------ api
    def write_exchange(self, exchange: Any) -> RawWriteResult:
        """Persist ONE ProviderExchange AND enroll its trust anchor.

        Steps (CR-2.4 audit section 3.1):

        1. ``RawWriter.write(exchange)`` - the file-side commit (payloads
           first, meta LAST; the returned ``evidence_hash`` is hashed
           from the persisted meta bytes);
        2. reread the persisted meta bytes - VERIFY-ONLY: they must hash
           to exactly the commit identity (a write->enroll TOCTOU swap
           fails the whole ingest; the swapped bytes are never enrolled);
        3. cross-bind the persisted meta's identity fields against the
           exchange envelope's provider-owned identity;
        4. enroll the immutable anchor keyed to the commit identity
           (idempotent on the same hash; hard conflict otherwise).

        Any failure raises - the ingest is NOT complete and the evidence
        is NOT ready. The raw bytes (if committed) survive without an
        anchor, so normalization keeps failing closed until an exact
        retry completes the enrollment (RawWriter is idempotent on the
        same bytes -> the same commit identity -> one immutable anchor).
        """
        envelope = getattr(exchange, "envelope", None)
        if envelope is None:
            msg = "write_exchange() expects a ProviderExchange (missing .envelope)"
            raise RawAnchorError(msg)
        result = self._writer.write(exchange)

        provider = str(getattr(envelope, "provider", "") or "amazingdata")
        dataset = str(getattr(envelope, "provider_dataset", "") or "")
        meta_path = _meta_path(self._root, provider, dataset, result.request_id)
        if not meta_path.is_file():
            msg = (
                f"anchored write verification failed for request {result.request_id!r}: "
                f"no persisted raw meta at {meta_path} after the RawWriter commit"
            )
            raise RawAnchorError(msg)
        meta_bytes = meta_path.read_bytes()
        reread_hash = hashlib.sha256(meta_bytes).hexdigest()
        if reread_hash != result.evidence_hash:
            msg = (
                f"anchored write TOCTOU verification failed for request "
                f"{result.request_id!r}: the persisted meta bytes hash to "
                f"{reread_hash[:16]}... but the RawWriter commit identity is "
                f"{result.evidence_hash[:16]}... - the meta changed between "
                "commit and anchor enrollment and is NOT enrolled as truth "
                "(CR-2.4 audit 20260901 section 2.2)"
            )
            raise RawAnchorError(msg)

        try:
            doc: dict[str, Any] = json.loads(meta_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = (
                f"anchored write verification failed for request "
                f"{result.request_id!r}: raw meta unreadable: {exc}"
            )
            raise RawAnchorError(msg) from exc

        # identity cross-binding: the persisted meta must carry the
        # ENVELOPE's own provider-owned identity
        expected_identity = {
            "request_id": result.request_id,
            "provider": provider,
            "provider_dataset": dataset,
            "endpoint": str(getattr(envelope, "endpoint", "") or ""),
            "normalization_surface": str(getattr(envelope, "normalization_surface", "") or ""),
            "operation_id": str(getattr(envelope, "operation_id", "") or ""),
        }
        for field, expected in expected_identity.items():
            if str(doc.get(field, "")) != expected:
                msg = (
                    f"anchored write identity cross-binding failed for request "
                    f"{result.request_id!r}: meta field {field} carries "
                    f"{str(doc.get(field, ''))!r} but the exchange envelope "
                    f"declares {expected!r} - the persisted meta does not "
                    "describe this exchange (CR-2.4 audit 20260901 section 3.1)"
                )
                raise RawAnchorError(msg)
        # uri cross-binding: the commit's own evidence/meta uri must be
        # the canonical request-addressed meta uri
        expected_uri = f"provider={provider}/dataset={dataset}/{result.request_id}.meta.json"
        if result.evidence_uri != expected_uri or result.meta_uri != expected_uri:
            msg = (
                f"anchored write uri cross-binding failed for request "
                f"{result.request_id!r}: the commit reports "
                f"evidence_uri={result.evidence_uri!r} / meta_uri={result.meta_uri!r} "
                f"but the canonical meta uri is {expected_uri!r}"
            )
            raise RawAnchorError(msg)

        _enroll_anchor(
            self._conn,
            self._root,
            provider=provider,
            provider_dataset=dataset,
            request_id=result.request_id,
            evidence_hash=result.evidence_hash,
            ingest_run_id=self._writer.ingest_run_id,
        )
        return result


def persist_exchange_with_anchor(
    conn: DuckDBPyConnection,
    raw_root: Path | str,
    exchange: Any,
    *,
    ingest_run_id: str = "",
) -> RawWriteResult:
    """Convenience one-shot form of the anchored boundary (same
    semantics as :meth:`AnchoredRawEvidenceWriter.write_exchange`)."""
    return AnchoredRawEvidenceWriter(conn, raw_root, ingest_run_id=ingest_run_id).write_exchange(
        exchange
    )
