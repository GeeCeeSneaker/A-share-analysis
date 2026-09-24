"""CR-4.1: canonical owner verification and downstream seal hand-offs
(audit 20260902 sections 3-4, CR-4 work requirement P0-A01/P0-A02).

SnapshotBuilder calls ``verify_canonical_run_for_consumption`` at the
canonical owner boundary. Downstream durable boundaries consume the
small ``read_canonical_run_manifest`` / ``load_canonical_projection``
seal hand-offs and enforce their own artifact/schema/PIT invariants;
they do not recursively re-run the full CR-3 chain on every read.
The full verifier remains the explicit deep-audit/owner entry point.

Deliberate distinction from the CR-3 continuity guard: consumption
does NOT require the sealed CR-2 inputs to still be part of the
CURRENT snapshot discovery (a later legitimate superset input world
must not retroactively break consumption of an already-minted
SUCCESS run) - but every consumed input must still exist in the
authoritative CR-2 ledger with an identical identity and healthy
physical / anchored evidence.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from ashare_state.canonical.canonicalizer import (
    _LEDGER_COLUMNS,
    CanonicalRunner,
    CanonicalRunSeal,
    _ledger_as_of,
)
from ashare_state.canonical.daily_bar import (
    deep_verify_daily_bar_partitions,
    iter_daily_bar_partition_rows,
)
from ashare_state.storage.paths import physical_from_logical_uri

__all__ = [
    "CanonicalConsumptionError",
    "CanonicalProjectionSource",
    "VerifiedCanonicalRun",
    "load_canonical_projection",
    "open_canonical_projection_source",
    "read_canonical_run_manifest",
    "verify_canonical_run_for_consumption",
]


class CanonicalConsumptionError(Exception):
    """A canonical run cannot be consumed: unknown id, damaged seal /
    artifacts / findings truth, non-SUCCESS status, or degraded
    upstream CR-2 evidence. Fail closed - no partial truth escapes."""


@dataclass(frozen=True)
class CanonicalProjectionSource:
    """A hash-verified selected artifact that can be consumed in batches.

    The legacy ``load_canonical_projection`` hand-off intentionally returns
    all selected rows for builders that need an in-memory tuple.  ReadModel
    and Snapshot seal-only consumers must not pay that memory cost, so this
    hand-off exposes the same verified artifact through a bounded iterator.
    """

    record: dict[str, Any]
    manifest: dict[str, Any]
    as_of: datetime
    path: Path
    row_count: int
    daily_bar_partitions: tuple[dict[str, Any], ...] = ()
    normalized_root: Path | None = None

    def iter_rows(self, *, batch_size: int = 32_768) -> Iterator[dict[str, Any]]:
        """Yield selected rows from Parquet without materializing the file."""
        if batch_size <= 0:
            raise CanonicalConsumptionError("canonical projection batch_size must be positive")
        try:
            parquet = pq.ParquetFile(self.path)
            for batch in parquet.iter_batches(batch_size=batch_size):
                for row in batch.to_pylist():
                    if not isinstance(row, dict):  # pragma: no cover - pyarrow contract
                        raise CanonicalConsumptionError(
                            "canonical selected artifact yielded a non-mapping row"
                        )
                    for field in self.manifest.get("selected_schema_fields", []):
                        row.setdefault(str(field), None)
                    yield row
            if self.daily_bar_partitions:
                if self.normalized_root is None:  # pragma: no cover - construction invariant
                    raise CanonicalConsumptionError("daily-bar projection source has no root")
                for entry in self.daily_bar_partitions:
                    for row in iter_daily_bar_partition_rows(
                        self.normalized_root, entry, batch_size=batch_size
                    ):
                        for field in self.manifest.get("selected_schema_fields", []):
                            row.setdefault(str(field), None)
                        yield row
        except CanonicalConsumptionError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed at the artifact boundary
            raise CanonicalConsumptionError(
                "canonical selected artifact cannot be streamed"
            ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class VerifiedCanonicalRun:
    """The verified canonical truth a downstream builder may consume:
    the ledger record, the verified manifest, the exact requested
    domain set and the materialized selected rows (read from the
    hash-verified selected.parquet inside the verification)."""

    canonical_run_id: str
    as_of: datetime
    requested_domains: tuple[str, ...]
    status: str
    ledger_record: dict[str, Any]
    manifest: dict[str, Any]
    selected_rows: tuple[dict[str, Any], ...]


def read_canonical_run_manifest(
    conn: Any,
    canonical_run_id: str,
    *,
    normalized_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], datetime]:
    """Read the durable canonical manifest seal for a downstream boundary.

    This is intentionally lighter than ``verify_canonical_run_for_consumption``:
    it verifies the current ledger row, deterministic manifest URI, manifest
    bytes hash, and the manifest's identity fields, but it does not re-run
    canonical artifact/finding/input closure.  The owner boundary performs
    that deep verification once; downstream consumers compare this referenced
    identity and verify only their own inputs.
    """
    row = conn.execute(
        f"SELECT {', '.join(_LEDGER_COLUMNS)} FROM meta_canonicalization_run "
        "WHERE canonical_run_id = ?",
        [canonical_run_id],
    ).fetchone()
    if row is None:
        raise CanonicalConsumptionError(
            f"canonical run {canonical_run_id} does not exist in the canonical ledger"
        )
    record = dict(zip(_LEDGER_COLUMNS, row, strict=True))
    if str(record["status"]) != "SUCCESS":
        raise CanonicalConsumptionError(
            f"canonical run {canonical_run_id} has status {record['status']!r}; "
            "only SUCCESS runs may be referenced"
        )
    as_of = _ledger_as_of(record)
    expected_uri = (
        f"canonical/contract={record['canonical_contract_version']}/"
        f"as_of={as_of.strftime('%Y%m%dT%H%M%SZ')}/"
        f"run={canonical_run_id}/manifest.json"
    )
    if str(record["manifest_uri"]) != expected_uri:
        raise CanonicalConsumptionError(
            f"canonical manifest URI is not deterministic: {record['manifest_uri']!r}"
        )
    try:
        manifest_path = physical_from_logical_uri(Path(normalized_root), expected_uri)
    except Exception as exc:  # noqa: BLE001 - fail closed at the path boundary
        raise CanonicalConsumptionError(
            f"canonical manifest URI is outside the normalized root: {expected_uri!r}"
        ) from exc
    if not manifest_path.is_file():
        raise CanonicalConsumptionError(f"canonical manifest missing: {expected_uri}")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != str(record["manifest_hash"]):
        raise CanonicalConsumptionError("canonical manifest bytes do not match the ledger hash")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalConsumptionError(f"canonical manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise CanonicalConsumptionError("canonical manifest root is not an object")
    for field in (
        "canonical_run_id",
        "canonical_contract_version",
        "requested_domains_hash",
        "selected_semantic_hash",
        "status",
    ):
        if str(manifest.get(field)) != str(record[field]):
            raise CanonicalConsumptionError(
                f"canonical manifest field {field} does not match the ledger seal"
            )
    if str(manifest.get("as_of")) != as_of.isoformat():
        raise CanonicalConsumptionError("canonical manifest as_of does not match the ledger")
    try:
        requested_domains = json.loads(str(record["requested_domains_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise CanonicalConsumptionError(
            "canonical ledger requested_domains_json is unreadable"
        ) from exc
    if not isinstance(requested_domains, list) or not all(
        isinstance(domain, str) for domain in requested_domains
    ):
        raise CanonicalConsumptionError(
            "canonical ledger requested_domains_json is not a list of strings"
        )
    if manifest.get("requested_domains") != requested_domains:
        raise CanonicalConsumptionError(
            "canonical manifest requested_domains does not match the ledger"
        )
    return record, manifest, as_of


def open_canonical_projection_source(
    conn: Any,
    canonical_run_id: str,
    *,
    normalized_root: Path,
) -> CanonicalProjectionSource:
    """Verify the selected artifact seal and return a bounded row source.

    This is deliberately a separate hand-off from ``load_canonical_projection``:
    callers that need the historical tuple keep the old API, while seal-only
    consumers can stream the exact same artifact without a full ``read_bytes``
    or ``to_dicts`` allocation.
    """
    record, manifest, as_of = read_canonical_run_manifest(
        conn, canonical_run_id, normalized_root=normalized_root
    )
    artifacts = manifest.get("artifacts")
    selected = artifacts.get("selected") if isinstance(artifacts, dict) else None
    if not isinstance(selected, dict):
        raise CanonicalConsumptionError("canonical manifest has no selected artifact seal")
    expected_uri = (
        f"canonical/contract={record['canonical_contract_version']}/"
        f"as_of={as_of.strftime('%Y%m%dT%H%M%SZ')}/"
        f"run={canonical_run_id}/selected.parquet"
    )
    if str(selected.get("uri")) != expected_uri:
        raise CanonicalConsumptionError("canonical selected artifact URI is not deterministic")
    try:
        path = physical_from_logical_uri(Path(normalized_root), expected_uri)
    except Exception as exc:  # noqa: BLE001 - fail closed at the path boundary
        raise CanonicalConsumptionError("canonical selected artifact URI is invalid") from exc
    if not path.is_file():
        raise CanonicalConsumptionError(f"canonical selected artifact missing: {expected_uri}")
    if _sha256_file(path) != str(selected.get("content_hash")):
        raise CanonicalConsumptionError("canonical selected artifact bytes are tampered")
    try:
        schema = pl.read_parquet_schema(path)
        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
        row_count = -1 if metadata is None else int(metadata.num_rows)
    except Exception as exc:  # noqa: BLE001 - fail closed at the artifact boundary
        raise CanonicalConsumptionError(
            "canonical selected artifact schema or metadata is unreadable"
        ) from exc
    schema_hash = hashlib.sha256(str(schema).encode("utf-8")).hexdigest()
    if schema_hash != str(selected.get("schema_hash")):
        raise CanonicalConsumptionError("canonical selected artifact schema is tampered")
    if row_count != int(selected.get("row_count", -1)):
        raise CanonicalConsumptionError("canonical selected artifact row count is tampered")
    partition_entries = manifest.get("daily_bar_partitions", [])
    if not isinstance(partition_entries, list):
        raise CanonicalConsumptionError("canonical daily_bar_partitions seal is not a list")
    total_count = row_count
    if partition_entries:
        partition_count = sum(int(entry.get("row_count", -1)) for entry in partition_entries)
        for entry in partition_entries:
            if not isinstance(entry, dict):
                raise CanonicalConsumptionError("canonical daily-bar partition entry is invalid")
            # Check manifest and artifact identities before yielding rows. The
            # bytes are deeply hashed by the explicit Canonical verifier.
            manifest_uri = str(entry.get("partition_manifest_uri", ""))
            partition_path = physical_from_logical_uri(Path(normalized_root), manifest_uri)
            if not partition_path.is_file():
                raise CanonicalConsumptionError("canonical daily-bar partition manifest is missing")
            if _sha256_file(partition_path) != str(entry.get("partition_manifest_hash")):
                raise CanonicalConsumptionError(
                    "canonical daily-bar partition manifest is tampered"
                )
        total_count += partition_count
    if total_count != int(record["selected_count"]):
        raise CanonicalConsumptionError(
            "canonical selected artifact plus daily partitions differ from selected_count"
        )
    return CanonicalProjectionSource(
        record=record,
        manifest=manifest,
        as_of=as_of,
        path=path,
        row_count=total_count,
        daily_bar_partitions=tuple(partition_entries),
        normalized_root=Path(normalized_root),
    )


def load_canonical_projection(
    conn: Any,
    canonical_run_id: str,
    *,
    normalized_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], datetime, tuple[dict[str, Any], ...]]:
    """Load the selected projection after consuming the canonical manifest seal.

    Only the selected artifact needed by snapshot construction is opened.  Its
    URI, byte hash, schema hash, and row count are checked against the already
    sealed manifest; canonical findings, decisions, and upstream inputs are
    not recursively reverified here.
    """
    record, manifest, as_of = read_canonical_run_manifest(
        conn, canonical_run_id, normalized_root=normalized_root
    )
    artifacts = manifest.get("artifacts")
    selected = artifacts.get("selected") if isinstance(artifacts, dict) else None
    if not isinstance(selected, dict):
        raise CanonicalConsumptionError("canonical manifest has no selected artifact seal")
    expected_uri = (
        f"canonical/contract={record['canonical_contract_version']}/"
        f"as_of={as_of.strftime('%Y%m%dT%H%M%SZ')}/"
        f"run={canonical_run_id}/selected.parquet"
    )
    if str(selected.get("uri")) != expected_uri:
        raise CanonicalConsumptionError("canonical selected artifact URI is not deterministic")
    try:
        path = physical_from_logical_uri(Path(normalized_root), expected_uri)
    except Exception as exc:  # noqa: BLE001 - fail closed at the path boundary
        raise CanonicalConsumptionError("canonical selected artifact URI is invalid") from exc
    if not path.is_file():
        raise CanonicalConsumptionError(f"canonical selected artifact missing: {expected_uri}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != str(selected.get("content_hash")):
        raise CanonicalConsumptionError("canonical selected artifact bytes are tampered")
    frame = pl.read_parquet(io.BytesIO(data))
    schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
    if schema_hash != str(selected.get("schema_hash")):
        raise CanonicalConsumptionError("canonical selected artifact schema is tampered")
    if frame.height != int(selected.get("row_count", -1)):
        raise CanonicalConsumptionError("canonical selected artifact row count is tampered")
    selected_rows = frame.to_dicts()
    partition_entries = manifest.get("daily_bar_partitions")
    if partition_entries is not None:
        if not isinstance(partition_entries, list):
            raise CanonicalConsumptionError("canonical daily_bar_partitions seal is not a list")
        selected_rows.extend(deep_verify_daily_bar_partitions(normalized_root, partition_entries))
        selected_fields = manifest.get("selected_schema_fields", [])
        if not isinstance(selected_fields, list) or any(
            not isinstance(field, str) for field in selected_fields
        ):
            raise CanonicalConsumptionError("canonical selected_schema_fields seal is invalid")
        for row in selected_rows:
            for field in selected_fields:
                row.setdefault(field, None)
    return record, manifest, as_of, tuple(selected_rows)


def verify_canonical_run_for_consumption(
    conn: Any,
    canonical_run_id: str,
    *,
    raw_root: Path,
    normalized_root: Path,
) -> VerifiedCanonicalRun:
    """Verify ONE historical canonical run end-to-end for downstream
    consumption (CR-4 work requirement P0-A01):

    1. the ledger row exists;
    2. the typed identity seal verifies (deterministic manifest URI +
       bytes hash + manifest == ledger correctness fields + the FULL
       derived run identity physical recompute incl. the run-id UUID5
       cross-bind);
    3. the shared canonical artifact closure verifier passes
       (selected / decisions / findings exact set + deterministic URIs
       + physical hashes + semantic seals);
    4. the findings truth (DB == parquet == seal) holds and the
       status is RECOMPUTED from that truth;
    5. the verified status is SUCCESS (a BLOCKED run is explicitly
       rejected - its findings are a failure record, not truth);
    6. every sealed CR-2 input still exists in the authoritative CR-2
       ledger with an identical identity and healthy physical /
       anchored evidence (sealed-input physical verification
       symmetric with the first consume).

    Any problem -> CanonicalConsumptionError (fail closed; nothing is
    returned partially). Success -> the selected rows are materialized
    from the hash-verified selected.parquet."""
    runner = CanonicalRunner(conn, raw_root=raw_root, normalized_root=normalized_root)
    row = conn.execute(
        f"SELECT {', '.join(_LEDGER_COLUMNS)} FROM meta_canonicalization_run "
        "WHERE canonical_run_id = ?",
        [canonical_run_id],
    ).fetchone()
    if row is None:
        msg = (
            f"canonical run {canonical_run_id} does not exist in the canonical "
            "ledger - nothing to consume"
        )
        raise CanonicalConsumptionError(msg)
    record = dict(zip(_LEDGER_COLUMNS, row, strict=True))
    seal = CanonicalRunSeal.from_ledger(record)

    # 2. typed identity seal (deterministic URI + bytes hash + manifest ==
    # ledger + full derived identity physical recompute incl. run-id bind)
    manifest, identity_problems = runner._verify_historical_identity_seal(seal, record)  # noqa: SLF001 - the ONE shared implementation
    if identity_problems or manifest is None:
        detail = "; ".join(identity_problems) if identity_problems else "no verifiable seal"
        msg = f"canonical run {canonical_run_id} is DAMAGED and cannot be consumed: {detail}"
        raise CanonicalConsumptionError(msg)

    # 3. shared canonical artifact closure verifier
    artifact_problems, artifact_rows = runner._verify_canonical_artifacts_with_rows(  # noqa: SLF001
        record, manifest
    )
    if artifact_problems:
        msg = (
            f"canonical run {canonical_run_id} artifacts are DAMAGED and "
            f"cannot be consumed: {'; '.join(artifact_problems)}"
        )
        raise CanonicalConsumptionError(msg)

    # 4. findings truth (DB == parquet == seal) + status recompute
    verified_status, finding_problems = runner._verify_findings_truth(record, manifest)  # noqa: SLF001 - the ONE shared implementation
    if finding_problems:
        msg = (
            f"canonical run {canonical_run_id} findings truth is DAMAGED and "
            f"cannot be consumed: {'; '.join(finding_problems)}"
        )
        raise CanonicalConsumptionError(msg)

    # 5. only a verified SUCCESS may be consumed
    if verified_status != "SUCCESS":
        msg = (
            f"canonical run {canonical_run_id} is {verified_status} - only a "
            "verified SUCCESS run may be consumed for snapshot construction"
        )
        raise CanonicalConsumptionError(msg)

    # 6. every sealed CR-2 input: authoritative ledger identity + physical /
    # anchored health (no current-discovery-presence requirement)
    as_of_dt = _ledger_as_of(record)
    for entry in manifest.get("input_normalized_runs", []):
        run_id = str(entry.get("run_id"))
        authority_problems = runner._sealed_input_authority_problems(entry, run_id)  # noqa: SLF001 - the ONE shared implementation
        if authority_problems:
            msg = (
                f"canonical run {canonical_run_id} cannot be consumed - "
                f"sealed CR-2 input is degraded: {'; '.join(authority_problems)}"
            )
            raise CanonicalConsumptionError(msg)
        physical_problems = runner._verify_sealed_input(entry, as_of_dt)  # noqa: SLF001 - the ONE shared implementation
        if physical_problems:
            msg = (
                f"canonical run {canonical_run_id} cannot be consumed - "
                f"sealed CR-2 input is no longer intact: "
                f"{'; '.join(physical_problems)}"
            )
            raise CanonicalConsumptionError(msg)

    # Reuse the rows materialized from the exact bytes inside the shared
    # artifact verifier; never reread a mutable path after verification.
    rows = artifact_rows["selected"]
    try:
        requested_domains = tuple(
            str(d) for d in json_loads_domains(str(record["requested_domains_json"]))
        )
    except ValueError as exc:
        msg = f"canonical run {canonical_run_id} carries unreadable requested domains: {exc}"
        raise CanonicalConsumptionError(msg) from exc
    return VerifiedCanonicalRun(
        canonical_run_id=canonical_run_id,
        as_of=as_of_dt,
        requested_domains=requested_domains,
        status=verified_status,
        ledger_record=record,
        manifest=manifest,
        selected_rows=tuple(rows),
    )


def json_loads_domains(raw: str) -> list[str]:
    import json

    try:
        domains = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(domains, list) or not all(isinstance(d, str) for d in domains):
        raise ValueError("requested_domains_json is not a list of strings")
    return domains
