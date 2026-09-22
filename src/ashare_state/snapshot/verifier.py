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
import heapq
import json
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from ashare_state.canonical.canonicalizer import (
    _canonical_json,
)
from ashare_state.canonical.verifier import (
    CanonicalConsumptionError,
    CanonicalProjectionSource,
    load_canonical_projection,
    open_canonical_projection_source,
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
    project_selected_row,
)

__all__ = ["verify_snapshot"]


_CANONICAL_PROJECTION_BATCH_SIZE = 32_768
_CANONICAL_SORT_CHUNK_ROWS = 32_768
_CANONICAL_MAX_OPEN_CHUNKS = 64
_MISSING = object()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_parquet_rows(path: Path, *, batch_size: int) -> Iterator[dict[str, Any]]:
    """Yield physical Parquet rows in bounded Arrow batches."""
    try:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=batch_size):
            for row in batch.to_pylist():
                if not isinstance(row, dict):  # pragma: no cover - pyarrow contract
                    raise SnapshotVerifierError("snapshot artifact yielded a non-mapping row")
                yield row
    except SnapshotVerifierError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed at the artifact boundary
        raise SnapshotVerifierError(f"snapshot artifact cannot be streamed: {path}") from exc


class _BoundedProjectedRows:
    """External-sort canonical projection rows for seal-only verification."""

    def __init__(
        self,
        source: CanonicalProjectionSource,
        *,
        requested_domains: tuple[str, ...],
        canonical_run_id: str,
        as_of: datetime,
        snapshot_id: str,
    ) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="snapshot-project-")
        self._root = Path(self._temporary_directory.name)
        self._created: list[Path] = []
        self._chunks: dict[str, list[Path]] = {domain: [] for domain in requested_domains}
        self._chunk_index = 0
        try:
            self._build(
                source,
                requested_domains=requested_domains,
                canonical_run_id=canonical_run_id,
                as_of=as_of,
                snapshot_id=snapshot_id,
            )
        except Exception:
            self.close()
            raise

    def _flush(self, domain: str, lines: list[str]) -> None:
        if not lines:
            return
        path = self._root / f"{domain}-{self._chunk_index:08d}.jsonl"
        self._chunk_index += 1
        with path.open("w", encoding="utf-8", newline="") as output:
            output.writelines(sorted(lines))
        self._created.append(path)
        self._chunks[domain].append(path)
        lines.clear()

    def _build(
        self,
        source: CanonicalProjectionSource,
        *,
        requested_domains: tuple[str, ...],
        canonical_run_id: str,
        as_of: datetime,
        snapshot_id: str,
    ) -> None:
        buffers: dict[str, list[str]] = {domain: [] for domain in requested_domains}
        for selected_row in source.iter_rows(batch_size=_CANONICAL_PROJECTION_BATCH_SIZE):
            domain = selected_row.get("canonical_domain")
            if not isinstance(domain, str) or domain not in buffers:
                raise SnapshotVerifierError(
                    f"canonical run emitted domain {domain!r} outside the requested domain set"
                )
            try:
                projected = project_selected_row(
                    domain,
                    selected_row,
                    canonical_run_id=canonical_run_id,
                    snapshot_id=snapshot_id,
                    as_of=as_of,
                )
            except SnapshotSchemaError as exc:
                raise SnapshotVerifierError(
                    f"snapshot {snapshot_id} canonical projection is DAMAGED: {exc}"
                ) from exc
            buffers[domain].append(
                f"{projected['canonical_key']}\t{_canonical_json(projected)}\n"
            )
            if len(buffers[domain]) >= _CANONICAL_SORT_CHUNK_ROWS:
                self._flush(domain, buffers[domain])
        for domain in requested_domains:
            self._flush(domain, buffers[domain])

    @staticmethod
    def _merge_group(group: list[Path], destination: Path) -> None:
        from contextlib import ExitStack

        with ExitStack() as stack:
            streams = [
                stack.enter_context(path.open("r", encoding="utf-8", newline=""))
                for path in group
            ]
            with destination.open("w", encoding="utf-8", newline="") as output:
                for line in heapq.merge(*(iter(stream) for stream in streams)):
                    output.write(line)

    def _reduced_chunks(self, domain: str) -> list[Path]:
        current = list(self._chunks[domain])
        merge_round = 0
        while len(current) > _CANONICAL_MAX_OPEN_CHUNKS:
            merged: list[Path] = []
            for offset in range(0, len(current), _CANONICAL_MAX_OPEN_CHUNKS):
                group = current[offset : offset + _CANONICAL_MAX_OPEN_CHUNKS]
                destination = self._root / f"{domain}-merge-{merge_round:04d}-{offset:08d}.jsonl"
                self._merge_group(group, destination)
                self._created.append(destination)
                merged.append(destination)
                for path in group:
                    path.unlink(missing_ok=True)
            current = merged
            merge_round += 1
        self._chunks[domain] = current
        return current

    def iter_domain(self, domain: str) -> Iterator[str]:
        from contextlib import ExitStack

        paths = self._reduced_chunks(domain)
        with ExitStack() as stack:
            streams = [
                stack.enter_context(path.open("r", encoding="utf-8", newline=""))
                for path in paths
            ]
            previous_key: str | None = None
            for line in heapq.merge(*(iter(stream) for stream in streams)):
                line = line[:-1] if line.endswith("\n") else line
                try:
                    key, row_json = line.split("\t", 1)
                except ValueError as exc:  # pragma: no cover - internal format guard
                    raise SnapshotVerifierError(
                        f"bounded canonical projection chunk for {domain} is malformed"
                    ) from exc
                if key == previous_key:
                    raise SnapshotVerifierError(
                        f"domain {domain} carries duplicate canonical keys"
                    )
                previous_key = key
                yield row_json

    def close(self) -> None:
        for path in self._created:
            path.unlink(missing_ok=True)
        self._temporary_directory.cleanup()


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
    bounded_projected_rows: _BoundedProjectedRows | None = None
    canonical_source: CanonicalProjectionSource | None = None
    try:
        if retain_domain_rows:
            canonical_record, _canonical_manifest, canonical_as_of, canonical_rows = (
                load_canonical_projection(
                    conn,
                    str(manifest["canonical_run_id"]),
                    normalized_root=normalized_root,
                )
            )
        else:
            canonical_source = open_canonical_projection_source(
                conn,
                str(manifest["canonical_run_id"]),
                normalized_root=normalized_root,
            )
            canonical_record = canonical_source.record
            _canonical_manifest = canonical_source.manifest
            canonical_as_of = canonical_source.as_of
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
    expected_rows_by_domain: dict[str, tuple[dict[str, Any], ...]] | None = None
    if retain_domain_rows:
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
        # ``project_canonical_snapshot`` creates fresh schema-projected rows.
        # The source rows are no longer needed after that bridge has completed.
        del canonical_rows
    else:
        assert canonical_source is not None
        bounded_projected_rows = _BoundedProjectedRows(
            canonical_source,
            requested_domains=canonical_domains,
            canonical_run_id=str(canonical_record["canonical_run_id"]),
            as_of=canonical_as_of,
            snapshot_id=snapshot_id,
        )

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
    try:
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
            content_hash = _sha256_file(path)
            if content_hash != str(entry.get("content_hash")):
                msg = f"snapshot {domain} artifact bytes tampered"
                raise SnapshotVerifierError(msg)
            try:
                physical_schema = pl.read_parquet_schema(path)
                physical_parquet = pq.ParquetFile(path)
                metadata = physical_parquet.metadata
                physical_row_count = -1 if metadata is None else int(metadata.num_rows)
            except Exception as exc:  # noqa: BLE001 - fail closed at the artifact boundary
                raise SnapshotVerifierError(
                    f"snapshot {domain} artifact schema or metadata is unreadable"
                ) from exc
            actual_schema_hash = hashlib.sha256(str(physical_schema).encode("utf-8")).hexdigest()
            if actual_schema_hash != str(entry.get("schema_hash")):
                msg = (
                    f"snapshot {domain} artifact schema hash does not match the physical "
                    "schema (schema rebind)"
                )
                raise SnapshotVerifierError(msg)
            if str(physical_schema) != str(polars_domain_schema(domain)):
                msg = (
                    f"snapshot {domain} artifact schema is not the registry schema "
                    "(schema rebind)"
                )
                raise SnapshotVerifierError(msg)
            if physical_row_count != int(entry.get("row_count", -1)):
                msg = f"snapshot {domain} artifact row count mismatch"
                raise SnapshotVerifierError(msg)
            # The snapshot builder owns the semantic value seal.  Downstream
            # verification consumes that seal and checks the physical bytes,
            # schema, row count, deterministic projection and PIT/key rules;
            # it does not serialize the full dataset again just to re-hash it.
            semantic = str(entry.get("semantic_hash") or "")
            if len(semantic) != 64 or any(char not in "0123456789abcdef" for char in semantic):
                raise SnapshotVerifierError(f"snapshot {domain} semantic seal is malformed")
            if bounded_projected_rows is not None:
                expected_json_rows: Iterator[str] = bounded_projected_rows.iter_domain(domain)
            else:
                assert expected_rows_by_domain is not None
                expected_json_rows = (
                    _canonical_json(expected_row)
                    for expected_row in expected_rows_by_domain[domain]
                )
            # Both the builder and the projection registry promise the same
            # stable canonical-key order.  Compare one row at a time instead
            # of allocating full physical or projected row lists.
            rows: list[dict[str, Any]] | None = [] if retain_domain_rows else None
            for ordinal, (actual, expected_json) in enumerate(
                zip_longest(
                    _iter_parquet_rows(path, batch_size=_CANONICAL_PROJECTION_BATCH_SIZE),
                    expected_json_rows,
                    fillvalue=_MISSING,
                )
            ):
                if actual is _MISSING or expected_json is _MISSING:
                    raise SnapshotVerifierError(
                        f"snapshot {domain} physical/projection row count diverges at row {ordinal}"
                    )
                assert isinstance(actual, dict)
                assert isinstance(expected_json, str)
                if _canonical_json(actual) != expected_json:
                    msg = (
                        f"snapshot {domain} artifact row {ordinal} diverges from the "
                        "deterministic canonical projection"
                    )
                    raise SnapshotVerifierError(msg)
                if rows is not None:
                    rows.append(actual)
                # PIT + key sanity re-check on the materialized rows
                available = actual.get("available_at")
                if not isinstance(available, datetime) or available > as_of:
                    msg = (
                        f"snapshot {domain} row {actual.get('canonical_key')!r} violates "
                        "the PIT contract (available_at > as_of)"
                    )
                    raise SnapshotVerifierError(msg)
                if actual.get("snapshot_id") != snapshot_id:
                    msg = f"snapshot {domain} row carries a foreign snapshot_id projection"
                    raise SnapshotVerifierError(msg)
                if actual.get("canonical_run_id") != str(manifest["canonical_run_id"]):
                    msg = f"snapshot {domain} row carries a foreign canonical_run_id projection"
                    raise SnapshotVerifierError(msg)
            domain_rows[domain] = tuple(rows) if rows is not None else ()
            if expected_rows_by_domain is not None:
                del expected_rows_by_domain[domain]
            recomputed_seals[domain] = {
                "uri": str(entry.get("uri")),
                "content_hash": content_hash,
                "schema_hash": actual_schema_hash,
                "row_count": physical_row_count,
                "semantic_hash": semantic,
            }
            row_count_total += physical_row_count
    finally:
        if bounded_projected_rows is not None:
            bounded_projected_rows.close()

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

