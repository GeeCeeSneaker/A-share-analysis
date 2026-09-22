"""CR-4.2: the snapshot verification entry point (audit 20260902
section 5, P0-B03/P0-B04).

``verify_snapshot`` verifies ONE snapshot ledger row end-to-end:

1. the deterministic manifest URI + manifest bytes == ledger hash;
2. every explicit manifest correctness field == the ledger seal;
3. the snapshot identity is PHYSICALLY recomputed from the manifest
   primitives (canonical run-level seals + snapshot contract + the
   builder code fingerprint) - UUID5 cross-bind, never trusted;
4. the canonical provenance cross-bind: the canonical manifest and the
   selected projection needed by this boundary consume the referenced
   ledger/hash/version seal; the full canonical chain is not recursively
   re-verified on every snapshot read;
5. the artifact exact set == the requested domain set;
6. every per-domain artifact is physically verified (deterministic
   URI, bytes == content_hash, schema == the registry schema and row
   count), its sealed semantic hash is consumed after the manifest/ledger
   bind, and the deterministic projection is replayed row-by-row; aggregate
   seals (artifact_set_hash / snapshot_semantic_hash / row_count_total)
   are recomputed from those physical and sealed values;
7. the verified rows are optionally materialized per domain for callers that
   need the in-memory hand-off; seal-only consumers can disable that
   retention.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.canonical.canonicalizer import (
    _canonical_json,
)
from ashare_state.canonical.verifier import (
    CanonicalConsumptionError,
    load_canonical_projection,
)
from ashare_state.snapshot.builder import (
    SNAPSHOT_LEDGER_COLUMNS,
    snapshot_builder_code_fingerprint,
    snapshot_manifest_uri,
)
from ashare_state.snapshot.models import (
    SnapshotVerifierError,
    VerifiedSnapshot,
    snapshot_base_hash_from_primitives,
    snapshot_id_from_base_hash,
)
from ashare_state.snapshot.schema import (
    SnapshotSchemaError,
    polars_domain_schema,
    project_canonical_snapshot,
)

__all__ = ["verify_snapshot"]


def verify_snapshot(
    conn: Any,
    snapshot_id: str,
    *,
    raw_root: Path,
    normalized_root: Path,
    retain_domain_rows: bool = True,
) -> VerifiedSnapshot:
    """Verify ONE snapshot ledger row end-to-end and materialize the
    per-domain rows from the hash-verified parquet artifacts.

    ``retain_domain_rows=False`` keeps the exact physical/projection
    comparison and all seals, PIT checks, and key checks, but does not retain
    every verified row in the returned hand-off.  ReadModel consumers only
    need the verified manifest/seals and use this mode to avoid a second
    full-dataset Python representation.
    """
    row = conn.execute(
        f"SELECT {', '.join(SNAPSHOT_LEDGER_COLUMNS)} FROM meta_snapshot_build "
        "WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchone()
    if row is None:
        msg = f"snapshot {snapshot_id} does not exist in the snapshot ledger"
        raise SnapshotVerifierError(msg)
    record = dict(zip(SNAPSHOT_LEDGER_COLUMNS, row, strict=True))
    raw_as_of = record["canonical_as_of"]
    if not isinstance(raw_as_of, datetime):
        msg = f"snapshot {snapshot_id} ledger row carries no canonical as_of"
        raise SnapshotVerifierError(msg)
    # normalize the DuckDB TIMESTAMPTZ fetch (session-timezone aware)
    # back to UTC - the deterministic anchor is always the UTC instant
    as_of = raw_as_of.astimezone(UTC) if raw_as_of.tzinfo else raw_as_of.replace(tzinfo=UTC)

    # 1. deterministic manifest URI + bytes == ledger hash
    expected_uri = snapshot_manifest_uri(snapshot_id, as_of)
    if str(record["manifest_uri"]) != expected_uri:
        msg = (
            f"snapshot manifest_uri {str(record['manifest_uri'])!r} is not the "
            f"deterministic anchor {expected_uri!r} (rebind)"
        )
        raise SnapshotVerifierError(msg)
    manifest_path = normalized_root / str(record["manifest_uri"])
    if not manifest_path.is_file():
        msg = f"snapshot manifest missing: {record['manifest_uri']}"
        raise SnapshotVerifierError(msg)
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != str(record["manifest_hash"]):
        msg = "snapshot manifest bytes do not match the ledger hash (rebind)"
        raise SnapshotVerifierError(msg)
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"snapshot manifest unreadable: {exc}"
        raise SnapshotVerifierError(msg) from exc

    # 2. manifest explicit correctness fields == the ledger seal
    problems: list[str] = []
    expected_fields = (
        ("snapshot_id", snapshot_id),
        ("snapshot_contract_version", str(record["snapshot_contract_version"])),
        ("canonical_run_id", str(record["canonical_run_id"])),
        ("canonical_manifest_uri", str(record["canonical_manifest_uri"])),
        ("canonical_manifest_hash", str(record["canonical_manifest_hash"])),
        ("canonical_as_of", as_of.isoformat()),
        ("canonical_requested_domains_hash", str(record["requested_domains_hash"])),
        # (canonical_selected_semantic_hash is NOT a snapshot-ledger
        # column: it is consumed against the VERIFIED canonical ledger
        # truth in the provenance cross-bind below)
        ("snapshot_builder_code_fingerprint", str(record["builder_code_fingerprint"])),
        ("artifact_set_hash", str(record["artifact_set_hash"])),
        ("snapshot_semantic_hash", str(record["snapshot_semantic_hash"])),
        ("status", str(record["status"])),
    )
    for field, expected in expected_fields:
        if str(manifest.get(field)) != expected:
            problems.append(
                f"snapshot manifest field {field} does not match the ledger seal (manifest rebind)"
            )
    try:
        manifest_domains = [str(d) for d in manifest.get("requested_domains") or []]
    except TypeError:
        manifest_domains = []
        problems.append("snapshot manifest requested_domains is unreadable")
    try:
        ledger_domains = [str(d) for d in json.loads(str(record["requested_domains_json"]))]
    except json.JSONDecodeError:
        ledger_domains = []
        problems.append("snapshot ledger requested_domains_json is unreadable")
    if manifest_domains != ledger_domains:
        problems.append("snapshot manifest requested_domains does not match the ledger")
    if int(manifest.get("row_count_total", -1)) != int(record["row_count_total"]):
        problems.append("snapshot manifest row_count_total does not match the ledger")
    if problems:
        msg = f"snapshot {snapshot_id} is DAMAGED: {'; '.join(problems)}"
        raise SnapshotVerifierError(msg)
    if str(record["status"]) != "SUCCESS":
        msg = (
            f"snapshot {snapshot_id} has status {record['status']!r} - only a "
            "SUCCESS snapshot may be consumed"
        )
        raise SnapshotVerifierError(msg)

    # 3. snapshot identity physical recompute (UUID5 cross-bind)
    base_recompute = snapshot_base_hash_from_primitives(
        canonical_run_id=str(manifest["canonical_run_id"]),
        canonical_manifest_hash=str(manifest["canonical_manifest_hash"]),
        canonical_requested_domains_hash=str(manifest["canonical_requested_domains_hash"]),
        canonical_selected_semantic_hash=str(manifest["canonical_selected_semantic_hash"]),
        canonical_as_of=str(manifest["canonical_as_of"]),
        snapshot_contract_version=str(manifest["snapshot_contract_version"]),
        snapshot_builder_code_fingerprint=str(manifest["snapshot_builder_code_fingerprint"]),
    )
    if str(manifest.get("snapshot_base_hash")) != base_recompute:
        msg = "snapshot_base_hash does not match the manifest primitives (rebind)"
        raise SnapshotVerifierError(msg)
    if snapshot_id_from_base_hash(base_recompute) != snapshot_id:
        msg = "snapshot_id does not match UUID5 of the recomputed base hash (identity rebind)"
        raise SnapshotVerifierError(msg)
    if str(manifest["snapshot_builder_code_fingerprint"]) != snapshot_builder_code_fingerprint():
        msg = (
            "snapshot was built by a DIFFERENT snapshot builder code version - "
            "the current builder cannot verify its construction rules"
        )
        raise SnapshotVerifierError(msg)

    # 4. canonical provenance cross-bind: consume the canonical manifest
    # seal and the selected projection needed by this boundary. The
    # canonical owner already performed deep artifact/finding/input
    # verification; this consumer does not recursively re-run that chain.
    try:
        canonical_record, _canonical_manifest, canonical_as_of, canonical_rows = (
            load_canonical_projection(
                conn,
                str(manifest["canonical_run_id"]),
                normalized_root=normalized_root,
            )
        )
    except CanonicalConsumptionError as exc:
        msg = f"snapshot canonical provenance is DAMAGED: {exc}"
        raise SnapshotVerifierError(msg) from exc
    cross_problems: list[str] = []
    if str(manifest["canonical_manifest_hash"]) != str(canonical_record["manifest_hash"]):
        cross_problems.append("canonical manifest hash drifted after the snapshot build")
    if str(manifest["canonical_requested_domains_hash"]) != str(
        canonical_record["requested_domains_hash"]
    ):
        cross_problems.append("canonical requested domains hash drifted after the build")
    if str(manifest["canonical_selected_semantic_hash"]) != str(
        canonical_record["selected_semantic_hash"]
    ):
        cross_problems.append("canonical selected semantic hash drifted after the build")
    if str(manifest["canonical_as_of"]) != canonical_as_of.isoformat():
        cross_problems.append("canonical as_of drifted after the snapshot build")
    try:
        canonical_domains = tuple(
            str(domain) for domain in json.loads(str(canonical_record["requested_domains_json"]))
        )
    except (TypeError, json.JSONDecodeError):
        canonical_domains = ()
        cross_problems.append("canonical requested domains are unreadable")
    if tuple(manifest_domains) != canonical_domains:
        cross_problems.append("snapshot requested domains diverge from the canonical run")
    if cross_problems:
        msg = f"snapshot {snapshot_id} canonical provenance is DAMAGED: {'; '.join(cross_problems)}"
        raise SnapshotVerifierError(msg)
    try:
        expected_rows_by_domain = project_canonical_snapshot(
            canonical_rows,
            requested_domains=canonical_domains,
            canonical_run_id=str(canonical_record["canonical_run_id"]),
            as_of=canonical_as_of,
            snapshot_id=snapshot_id,
        )
    except SnapshotSchemaError as exc:
        raise SnapshotVerifierError(
            f"snapshot {snapshot_id} canonical projection is DAMAGED: {exc}"
        ) from exc
    # ``project_canonical_snapshot`` creates fresh schema-projected rows.  The
    # source rows are no longer needed after that bridge has completed.  On a
    # large daily-bar snapshot retaining both representations makes the
    # subsequent physical verification unnecessarily peak-heavy.
    del canonical_rows

    # 5. artifact exact set == the requested domain set
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        msg = f"snapshot {snapshot_id} manifest carries no artifact map"
        raise SnapshotVerifierError(msg)
    if set(artifacts) != set(manifest_domains):
        msg = (
            f"snapshot artifact set {sorted(artifacts)} is not exactly the "
            f"requested domain set {sorted(manifest_domains)}"
        )
        raise SnapshotVerifierError(msg)

    # 6. per-domain physical verify + aggregate seal recompute
    domain_rows: dict[str, tuple[dict[str, Any], ...]] = {}
    recomputed_seals: dict[str, dict[str, Any]] = {}
    row_count_total = 0
    for domain in manifest_domains:
        entry = artifacts[domain]
        expected_artifact_uri = (
            f"{snapshot_manifest_uri(snapshot_id, as_of).rsplit('/', 1)[0]}/{domain}.parquet"
        )
        if str(entry.get("uri")) != expected_artifact_uri:
            msg = (
                f"snapshot {domain} artifact uri is not the deterministic "
                f"recompute ({entry.get('uri')!r} != {expected_artifact_uri!r})"
            )
            raise SnapshotVerifierError(msg)
        path = normalized_root / str(entry.get("uri"))
        if not path.is_file():
            msg = f"snapshot {domain} artifact missing: {entry.get('uri')}"
            raise SnapshotVerifierError(msg)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != str(entry.get("content_hash")):
            msg = f"snapshot {domain} artifact bytes tampered"
            raise SnapshotVerifierError(msg)
        # Parse exactly the bytes whose hash was verified above; do not
        # reread a mutable path after verification.
        frame = pl.read_parquet(io.BytesIO(data))
        actual_schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
        if actual_schema_hash != str(entry.get("schema_hash")):
            msg = (
                f"snapshot {domain} artifact schema hash does not match the physical "
                "schema (schema rebind)"
            )
            raise SnapshotVerifierError(msg)
        if str(frame.schema) != str(polars_domain_schema(domain)):
            msg = f"snapshot {domain} artifact schema is not the registry schema (schema rebind)"
            raise SnapshotVerifierError(msg)
        if frame.height != int(entry.get("row_count", -1)):
            msg = f"snapshot {domain} artifact row count mismatch"
            raise SnapshotVerifierError(msg)
        # The snapshot builder owns the semantic value seal.  Downstream
        # verification consumes that seal and checks the physical bytes,
        # schema, row count, deterministic projection and PIT/key rules;
        # it does not serialize the full dataset again just to re-hash it.
        semantic = str(entry.get("semantic_hash") or "")
        if len(semantic) != 64 or any(char not in "0123456789abcdef" for char in semantic):
            raise SnapshotVerifierError(f"snapshot {domain} semantic seal is malformed")
        expected_rows = expected_rows_by_domain[domain]
        # Both the builder and the projection registry promise the same
        # stable canonical-key order.  Compare one row at a time instead of
        # allocating two full lists of canonical JSON strings (which is a
        # material, avoidable peak for multi-million-row daily-bar snapshots).
        rows: list[dict[str, Any]] | None = [] if retain_domain_rows else None
        for ordinal, (actual, expected_row) in enumerate(
            zip(frame.iter_rows(named=True), expected_rows, strict=True)
        ):
            if _canonical_json(actual) != _canonical_json(expected_row):
                msg = (
                    f"snapshot {domain} artifact row {ordinal} diverges from the "
                    "deterministic canonical projection"
                )
                raise SnapshotVerifierError(msg)
            if rows is not None:
                rows.append(actual)
            # PIT + key sanity re-check on the materialized rows
            r = actual
            available = r.get("available_at")
            if not isinstance(available, datetime) or available > as_of:
                msg = (
                    f"snapshot {domain} row {r.get('canonical_key')!r} violates "
                    "the PIT contract (available_at > as_of)"
                )
                raise SnapshotVerifierError(msg)
            if r.get("snapshot_id") != snapshot_id:
                msg = f"snapshot {domain} row carries a foreign snapshot_id projection"
                raise SnapshotVerifierError(msg)
            if r.get("canonical_run_id") != str(manifest["canonical_run_id"]):
                msg = f"snapshot {domain} row carries a foreign canonical_run_id projection"
                raise SnapshotVerifierError(msg)
        domain_rows[domain] = tuple(rows) if rows is not None else ()
        del expected_rows_by_domain[domain]
        recomputed_seals[domain] = {
            "uri": str(entry.get("uri")),
            "content_hash": hashlib.sha256(data).hexdigest(),
            "schema_hash": actual_schema_hash,
            "row_count": frame.height,
            "semantic_hash": semantic,
        }
        row_count_total += frame.height

    artifact_set_recompute = hashlib.sha256(
        _canonical_json(recomputed_seals).encode("utf-8")
    ).hexdigest()
    if artifact_set_recompute != str(record["artifact_set_hash"]):
        msg = "snapshot artifact_set_hash does not match the physical artifacts (rebind)"
        raise SnapshotVerifierError(msg)
    semantic_recompute = hashlib.sha256(
        _canonical_json({d: s["semantic_hash"] for d, s in recomputed_seals.items()}).encode(
            "utf-8"
        )
    ).hexdigest()
    if semantic_recompute != str(record["snapshot_semantic_hash"]):
        msg = "snapshot_semantic_hash does not match the physical artifacts (rebind)"
        raise SnapshotVerifierError(msg)
    if row_count_total != int(record["row_count_total"]):
        msg = "snapshot row_count_total does not match the physical artifacts"
        raise SnapshotVerifierError(msg)

    return VerifiedSnapshot(
        snapshot_id=snapshot_id,
        canonical_run_id=str(manifest["canonical_run_id"]),
        as_of=as_of,
        requested_domains=tuple(manifest_domains),
        ledger_record=record,
        manifest=manifest,
        domain_rows=domain_rows,
    )
