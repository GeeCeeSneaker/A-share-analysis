"""CR-4.2: the SnapshotBuilder (audit 20260902 sections 3/5).

Builds the domain-partitioned point-in-time snapshot from ONE verified
canonical SUCCESS run:

- the ONLY canonical input is the CR-4.1 public consumption verifier
  (no canonicalizer internals, no Raw, no CR-2 re-implementation);
- deterministic snapshot identity (UUID5 over the canonical run-level
  seals + the snapshot contract + a contract-specific identity component:
  a source-code fingerprint for legacy snapshots and an output-semantics
  fingerprint for logical daily snapshots);
- strict schema-registry projection (key round-trip + PIT contract +
  typed columns; fail closed on ANY violation);
- immutable per-domain parquet artifacts (selected/typed/sorted) +
  the manifest written LAST;
- one ledger transaction (migration 022) with a duplicate check.

No wall-clock enters any artifact (started_at/completed_at are
ledger-side transaction audit metadata only), so an exact retry after
a crash between file writes and the ledger commit is recoverable:
identical existing bytes are no-ops, missing bytes are written,
conflicting bytes fail closed, and the ledger is committed only after
the complete deterministic file plan is compatible.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.canonical.canonicalizer import _canonical_json, _rows_semantic_hash
from ashare_state.canonical.daily_bar import DAILY_BAR_LAYOUT_REVISION
from ashare_state.canonical.verifier import (
    read_canonical_run_manifest,
    verify_canonical_run_for_consumption,
)
from ashare_state.snapshot.models import (
    SnapshotBuilderError,
    SnapshotBuildResult,
    SnapshotVerifierError,
    snapshot_base_hash_from_primitives,
    snapshot_id_from_base_hash,
)
from ashare_state.snapshot.schema import (
    SNAPSHOT_CONTRACT_VERSION,
    SnapshotSchemaError,
    polars_domain_schema,
    project_canonical_snapshot,
)

__all__ = [
    "LOGICAL_DAILY_SNAPSHOT_SEMANTICS_VERSION",
    "SNAPSHOT_LEDGER_COLUMNS",
    "SnapshotBuilder",
    "logical_daily_snapshot_semantics_fingerprint",
    "snapshot_builder_code_fingerprint",
    "snapshot_base_dir",
    "snapshot_manifest_uri",
]


#: migration 022 ledger columns (meta_snapshot_build).
SNAPSHOT_LEDGER_COLUMNS = (
    "snapshot_id",
    "canonical_run_id",
    "canonical_manifest_uri",
    "canonical_manifest_hash",
    "canonical_as_of",
    "requested_domains_json",
    "requested_domains_hash",
    "snapshot_contract_version",
    "builder_code_fingerprint",
    "manifest_uri",
    "manifest_hash",
    "artifact_set_hash",
    "snapshot_semantic_hash",
    "row_count_total",
    "status",
    "error_message",
    "started_at",
    "completed_at",
)

LOGICAL_DAILY_SNAPSHOT_CONTRACT = "snapshot-daily-v1"
LOGICAL_DAILY_SNAPSHOT_SEMANTICS_VERSION = "snapshot-daily-semantics-v1"


def logical_daily_snapshot_semantics_fingerprint() -> str:
    """Return the stable output-semantics identity for logical daily Snapshots.

    The legacy ledger/manifest field ``builder_code_fingerprint`` stores this
    digest for ``snapshot-daily-v1`` only. It is intentionally independent of
    Python source, verifier implementation, batching, logging, and memory
    management. Increment the explicit semantics version only when the
    logical Snapshot output contract changes.
    """
    semantics = {
        "snapshot_contract_version": LOGICAL_DAILY_SNAPSHOT_CONTRACT,
        "semantics_version": LOGICAL_DAILY_SNAPSHOT_SEMANTICS_VERSION,
    }
    return hashlib.sha256(_canonical_json(semantics).encode("utf-8")).hexdigest()


def snapshot_builder_code_fingerprint() -> str:
    """SHA-256 over the governed snapshot module sources (line-ending
    normalized) - SYSTEM-DERIVED, entering the snapshot identity (a
    snapshot-layer code change yields a NEW snapshot, history
    preserved). The canonical consumption verifier participates: its
    rules are part of the governed construction path."""
    import ashare_state.canonical.verifier as _canonical_verifier
    import ashare_state.snapshot.builder as _builder
    import ashare_state.snapshot.schema as _schema

    digest = hashlib.sha256()
    for module in (_schema, _canonical_verifier, _builder):
        module_file = getattr(module, "__file__", None)
        if module_file is None:  # pragma: no cover
            raise SnapshotBuilderError(f"module {module!r} has no source file")
        source = Path(module_file).read_bytes().decode("utf-8")
        digest.update(source.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def snapshot_base_dir(snapshot_id: str, as_of: datetime) -> str:
    """The deterministic artifact directory for ONE snapshot."""
    return (
        f"snapshot/contract={SNAPSHOT_CONTRACT_VERSION}/"
        f"as_of={as_of.strftime('%Y%m%dT%H%M%SZ')}/"
        f"snapshot={snapshot_id}"
    )


def snapshot_manifest_uri(snapshot_id: str, as_of: datetime) -> str:
    return f"{snapshot_base_dir(snapshot_id, as_of)}/manifest.json"


def logical_daily_snapshot_manifest_uri(
    snapshot_id: str,
    market_as_of: datetime,
    source_vintage_as_of: datetime,
) -> str:
    return (
        f"snapshot/contract={LOGICAL_DAILY_SNAPSHOT_CONTRACT}/"
        f"market_as_of={market_as_of.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}/"
        f"source_vintage_as_of={source_vintage_as_of.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}/"
        f"snapshot={snapshot_id}/manifest.json"
    )


def _assert_immutable_compatible(path: Path, data: bytes) -> None:
    """Check an immutable path before any file in the build is written."""
    if not path.exists():
        return
    if path.is_file() and path.read_bytes() == data:
        return
    raise SnapshotBuilderError(f"immutable artifact conflict: {path} exists with different bytes")


def _write_immutable(path: Path, data: bytes) -> None:
    """Write deterministic bytes exactly once; identical retries are no-ops."""
    _assert_immutable_compatible(path, data)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class SnapshotBuilder:
    """Builds point-in-time snapshots from verified canonical runs."""

    def __init__(self, conn: Any, *, raw_root: Path, normalized_root: Path) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)

    # ------------------------------------------------------------- build
    def build(self, canonical_run_id: str) -> SnapshotBuildResult:
        started = datetime.now(UTC)
        # Read the durable source seal first so an idempotent retry can
        # identify an existing snapshot without re-running the full
        # canonical closure.  A new snapshot still crosses the owner
        # boundary below and receives the complete canonical verification.
        source_record, _source_manifest, source_as_of = read_canonical_run_manifest(
            self.conn,
            canonical_run_id,
            normalized_root=self.normalized_root,
        )
        requested_domains = tuple(
            str(domain) for domain in json.loads(str(source_record["requested_domains_json"]))
        )
        if "daily_bar" in requested_domains:
            if "daily_bar_partitions" not in _source_manifest:
                raise SnapshotBuilderError(
                    "legacy Canonical daily_bar run has no monthly partition seal; "
                    "the old fact-copy Snapshot path is disabled for daily_bar"
                )
            return self._build_logical_daily_snapshot(
                canonical_run_id,
                source_record=source_record,
                source_manifest=_source_manifest,
                source_as_of=source_as_of,
                requested_domains=requested_domains,
                started=started,
            )
        fingerprint = snapshot_builder_code_fingerprint()
        base_hash = snapshot_base_hash_from_primitives(
            canonical_run_id=canonical_run_id,
            canonical_manifest_hash=str(source_record["manifest_hash"]),
            canonical_requested_domains_hash=str(source_record["requested_domains_hash"]),
            canonical_selected_semantic_hash=str(source_record["selected_semantic_hash"]),
            canonical_as_of=source_as_of.isoformat(),
            snapshot_contract_version=SNAPSHOT_CONTRACT_VERSION,
            snapshot_builder_code_fingerprint=fingerprint,
        )
        snapshot_id = snapshot_id_from_base_hash(base_hash)

        # idempotent replay: the snapshot boundary verifies its own seal.
        existing = self.conn.execute(
            "SELECT 1 FROM meta_snapshot_build WHERE snapshot_id = ?",
            [snapshot_id],
        ).fetchone()
        if existing is not None:
            from ashare_state.snapshot.verifier import verify_snapshot

            current = verify_snapshot(
                self.conn,
                snapshot_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
            return SnapshotBuildResult(
                snapshot_id=current.snapshot_id,
                canonical_run_id=current.canonical_run_id,
                manifest_uri=current.ledger_record["manifest_uri"],
                manifest_hash=current.ledger_record["manifest_hash"],
                artifact_set_hash=current.ledger_record["artifact_set_hash"],
                snapshot_semantic_hash=current.ledger_record["snapshot_semantic_hash"],
                row_count_total=int(current.ledger_record["row_count_total"]),
                status=current.ledger_record["status"],
                idempotent_replay=True,
            )

        # New snapshot: the owner boundary performs the complete canonical
        # verification exactly once before any snapshot bytes are written.
        verified = verify_canonical_run_for_consumption(
            self.conn,
            canonical_run_id,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        record = verified.ledger_record
        if str(record["manifest_hash"]) != str(source_record["manifest_hash"]):
            raise SnapshotBuilderError(
                "canonical manifest changed between seal lookup and full verification"
            )

        base_dir = snapshot_base_dir(snapshot_id, verified.as_of)

        # ---- one shared deterministic projection for build + verify
        try:
            projected_by_domain = project_canonical_snapshot(
                verified.selected_rows,
                requested_domains=verified.requested_domains,
                canonical_run_id=verified.canonical_run_id,
                as_of=verified.as_of,
                snapshot_id=snapshot_id,
            )
        except SnapshotSchemaError as exc:
            raise SnapshotBuilderError(
                f"canonical run {canonical_run_id} cannot be projected into a snapshot: {exc}"
            ) from exc

        # ---- deterministic per-domain parquet artifacts + seals
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_payloads: dict[str, bytes] = {}
        row_count_total = 0
        for domain in verified.requested_domains:
            rows = projected_by_domain[domain]
            frame = pl.DataFrame(rows, schema=polars_domain_schema(domain))
            buffer = io.BytesIO()
            frame.write_parquet(buffer)
            data = buffer.getvalue()
            uri = f"{base_dir}/{domain}.parquet"
            artifact_payloads[domain] = data
            schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
            artifacts[domain] = {
                "uri": uri,
                "content_hash": hashlib.sha256(data).hexdigest(),
                "schema_hash": schema_hash,
                "row_count": len(rows),
                "semantic_hash": _rows_semantic_hash(list(rows)),
            }
            row_count_total += len(rows)

        artifact_set_hash = hashlib.sha256(_canonical_json(artifacts).encode("utf-8")).hexdigest()
        snapshot_semantic_hash = hashlib.sha256(
            _canonical_json({d: a["semantic_hash"] for d, a in artifacts.items()}).encode("utf-8")
        ).hexdigest()

        # ---- the manifest is written LAST
        manifest = {
            "snapshot_id": snapshot_id,
            "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
            "snapshot_base_hash": base_hash,
            "snapshot_builder_code_fingerprint": fingerprint,
            "canonical_run_id": canonical_run_id,
            "canonical_manifest_uri": str(record["manifest_uri"]),
            "canonical_manifest_hash": str(record["manifest_hash"]),
            "canonical_as_of": verified.as_of.isoformat(),
            "canonical_requested_domains_hash": str(record["requested_domains_hash"]),
            "canonical_selected_semantic_hash": str(record["selected_semantic_hash"]),
            "requested_domains": list(verified.requested_domains),
            "artifacts": artifacts,
            "artifact_set_hash": artifact_set_hash,
            "snapshot_semantic_hash": snapshot_semantic_hash,
            "row_count_total": row_count_total,
            "status": "SUCCESS",
        }
        manifest_uri = f"{base_dir}/manifest.json"
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False).encode(
            "utf-8"
        )
        # Preflight every deterministic path before writing any one of them:
        # a partial residue is recoverable only when every existing byte is
        # identical to the current deterministic build.
        write_plan = [
            (
                self.normalized_root / str(artifacts[domain]["uri"]),
                artifact_payloads[domain],
            )
            for domain in verified.requested_domains
        ]
        write_plan.append((self.normalized_root / manifest_uri, manifest_bytes))
        for path, data in write_plan:
            _assert_immutable_compatible(path, data)
        # Manifest remains the final publication marker.
        for path, data in write_plan[:-1]:
            _write_immutable(path, data)
        _write_immutable(write_plan[-1][0], write_plan[-1][1])
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()

        # ---- one ledger transaction (duplicate check included)
        completed = datetime.now(UTC)
        self._commit_ledger(
            snapshot_id=snapshot_id,
            canonical_run_id=canonical_run_id,
            canonical_manifest_uri=str(record["manifest_uri"]),
            canonical_manifest_hash=str(record["manifest_hash"]),
            canonical_as_of=verified.as_of,
            requested_domains_json=_canonical_json(list(verified.requested_domains)),
            requested_domains_hash=str(record["requested_domains_hash"]),
            fingerprint=fingerprint,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            snapshot_semantic_hash=snapshot_semantic_hash,
            row_count_total=row_count_total,
            started=started,
            completed=completed,
        )
        return SnapshotBuildResult(
            snapshot_id=snapshot_id,
            canonical_run_id=canonical_run_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            snapshot_semantic_hash=snapshot_semantic_hash,
            row_count_total=row_count_total,
            status="SUCCESS",
            idempotent_replay=False,
        )

    # ------------------------------------------------------------ ledger
    def _build_logical_daily_snapshot(
        self,
        canonical_run_id: str,
        *,
        source_record: dict[str, Any],
        source_manifest: dict[str, Any],
        source_as_of: datetime,
        requested_domains: tuple[str, ...],
        started: datetime,
    ) -> SnapshotBuildResult:
        """Publish a logical Snapshot that references, but never copies,
        Canonical daily-bar partitions. Other requested domains retain their
        existing small typed snapshot artifacts in this bounded slice.
        """
        partition_entries = source_manifest.get("daily_bar_partitions")
        if not isinstance(partition_entries, list):
            raise SnapshotBuilderError("canonical daily_bar_partitions must be a list")
        if any(not isinstance(entry, dict) for entry in partition_entries):
            raise SnapshotBuilderError("canonical daily-bar partition descriptor is invalid")
        partition_ids = [str(entry.get("logical_partition_id", "")) for entry in partition_entries]
        if len(set(partition_ids)) != len(partition_ids) or any(not item for item in partition_ids):
            raise SnapshotBuilderError("canonical daily-bar partition ids are empty or duplicated")
        source_times = [
            datetime.fromisoformat(str(entry["source_vintage_as_of"]).replace("Z", "+00:00"))
            for entry in partition_entries
            if entry.get("source_vintage_as_of")
        ]
        source_vintage_as_of = max(source_times, default=source_as_of).astimezone(UTC)
        fingerprint = logical_daily_snapshot_semantics_fingerprint()
        base_hash = snapshot_base_hash_from_primitives(
            canonical_run_id=canonical_run_id,
            canonical_manifest_hash=str(source_record["manifest_hash"]),
            canonical_requested_domains_hash=str(source_record["requested_domains_hash"]),
            canonical_selected_semantic_hash=str(source_record["selected_semantic_hash"]),
            canonical_as_of=source_as_of.isoformat(),
            snapshot_contract_version=LOGICAL_DAILY_SNAPSHOT_CONTRACT,
            snapshot_builder_code_fingerprint=fingerprint,
        )
        snapshot_id = snapshot_id_from_base_hash(base_hash)
        existing = self.conn.execute(
            "SELECT 1 FROM meta_snapshot_build WHERE snapshot_id = ?", [snapshot_id]
        ).fetchone()
        if existing is not None:
            from ashare_state.snapshot.verifier import consume_snapshot_seal

            current = consume_snapshot_seal(
                self.conn, snapshot_id, normalized_root=self.normalized_root
            )
            return SnapshotBuildResult(
                snapshot_id=current.snapshot_id,
                canonical_run_id=current.canonical_run_id,
                manifest_uri=str(current.ledger_record["manifest_uri"]),
                manifest_hash=str(current.ledger_record["manifest_hash"]),
                artifact_set_hash=str(current.ledger_record["artifact_set_hash"]),
                snapshot_semantic_hash=str(current.ledger_record["snapshot_semantic_hash"]),
                row_count_total=int(current.ledger_record["row_count_total"]),
                status=str(current.ledger_record["status"]),
                idempotent_replay=True,
            )

        canonical_record, canonical_manifest, verified_as_of = read_canonical_run_manifest(
            self.conn,
            canonical_run_id,
            normalized_root=self.normalized_root,
        )
        if str(canonical_record["manifest_hash"]) != str(source_record["manifest_hash"]):
            raise SnapshotBuilderError("canonical manifest changed during Snapshot construction")
        if verified_as_of != source_as_of:
            raise SnapshotBuilderError(
                "canonical market_as_of changed during Snapshot construction"
            )
        if tuple(canonical_manifest.get("requested_domains", ())) != requested_domains:
            raise SnapshotBuilderError(
                "canonical requested domains changed during Snapshot construction"
            )
        if canonical_manifest.get("daily_bar_partitions") != partition_entries:
            raise SnapshotBuilderError(
                "canonical daily-bar partition seal changed during construction"
            )
        if str(canonical_record["status"]) != "SUCCESS":
            raise SnapshotBuilderError("only a SUCCESS Canonical run may back a logical Snapshot")

        from ashare_state.snapshot.daily import validate_canonical_daily_partition_set

        try:
            validate_canonical_daily_partition_set(
                self.normalized_root,
                partition_entries,
                market_as_of=source_as_of,
                source_vintage_as_of=source_vintage_as_of,
            )
        except SnapshotVerifierError as exc:
            raise SnapshotBuilderError(
                f"Canonical daily partition set is not consumable: {exc}"
            ) from exc

        selected = canonical_manifest.get("artifacts", {}).get("selected")
        if not isinstance(selected, dict):
            raise SnapshotBuilderError("Canonical run has no selected artifact seal")
        expected_selected_uri = (
            f"canonical/contract={canonical_record['canonical_contract_version']}/"
            f"as_of={source_as_of.strftime('%Y%m%dT%H%M%SZ')}/"
            f"run={canonical_run_id}/selected.parquet"
        )
        if str(selected.get("uri")) != expected_selected_uri:
            raise SnapshotBuilderError("Canonical selected artifact URI is not deterministic")
        selected_path = self.normalized_root / expected_selected_uri
        if not selected_path.is_file():
            raise SnapshotBuilderError("Canonical non-daily selected artifact is missing")
        selected_bytes = selected_path.read_bytes()
        if hashlib.sha256(selected_bytes).hexdigest() != str(selected.get("content_hash")):
            raise SnapshotBuilderError("Canonical non-daily selected artifact hash differs")
        selected_frame = pl.read_parquet(io.BytesIO(selected_bytes))
        if hashlib.sha256(str(selected_frame.schema).encode("utf-8")).hexdigest() != str(
            selected.get("schema_hash")
        ) or selected_frame.height != int(selected.get("row_count", -1)):
            raise SnapshotBuilderError("Canonical non-daily selected artifact schema/count differs")
        non_daily_rows = selected_frame.to_dicts()
        if any(str(row.get("canonical_domain")) == "daily_bar" for row in non_daily_rows):
            raise SnapshotBuilderError(
                "Canonical selected artifact still duplicates daily_bar rows"
            )
        if len(non_daily_rows) + sum(int(entry["row_count"]) for entry in partition_entries) != int(
            canonical_record["selected_count"]
        ):
            raise SnapshotBuilderError("Canonical selected + partition counts do not reconcile")

        artifact_dir = logical_daily_snapshot_manifest_uri(
            snapshot_id, source_as_of, source_vintage_as_of
        ).rsplit("/", 1)[0]
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_payloads: dict[str, bytes] = {}
        row_count_total = 0

        logical_rows_hash = hashlib.sha256(
            _canonical_json(
                [
                    {
                        "logical_partition_id": entry["logical_partition_id"],
                        "data_revision": entry["data_revision"],
                        "logical_content_hash": entry["logical_content_hash"],
                        "row_count": int(entry["row_count"]),
                    }
                    for entry in partition_entries
                ]
            ).encode("utf-8")
        ).hexdigest()
        daily_artifact_set_hash = hashlib.sha256(
            _canonical_json(
                [
                    {
                        "logical_partition_id": entry["logical_partition_id"],
                        "layout_revision": entry["layout_revision"],
                        "artifact_set_hash": entry["artifact_set_hash"],
                        "partition_manifest_uri": entry["partition_manifest_uri"],
                        "partition_manifest_hash": entry["partition_manifest_hash"],
                    }
                    for entry in partition_entries
                ]
            ).encode("utf-8")
        ).hexdigest()
        artifacts["daily_bar"] = {
            "kind": "canonical_partition_set",
            "layout_revision": DAILY_BAR_LAYOUT_REVISION,
            "partitions": partition_entries,
            "row_count": sum(int(entry["row_count"]) for entry in partition_entries),
            "semantic_hash": logical_rows_hash,
            "artifact_set_hash": daily_artifact_set_hash,
        }
        row_count_total += int(artifacts["daily_bar"]["row_count"])

        non_daily_domains = tuple(domain for domain in requested_domains if domain != "daily_bar")
        if non_daily_domains:
            try:
                projected = project_canonical_snapshot(
                    non_daily_rows,
                    requested_domains=non_daily_domains,
                    canonical_run_id=canonical_run_id,
                    as_of=verified_as_of,
                    snapshot_id=snapshot_id,
                )
            except SnapshotSchemaError as exc:
                raise SnapshotBuilderError(
                    f"canonical run {canonical_run_id} cannot be projected into a snapshot: {exc}"
                ) from exc
            for domain in non_daily_domains:
                rows = projected[domain]
                frame = pl.DataFrame(rows, schema=polars_domain_schema(domain))
                buffer = io.BytesIO()
                frame.write_parquet(buffer)
                payload = buffer.getvalue()
                uri = f"{artifact_dir}/{domain}.parquet"
                artifact_payloads[domain] = payload
                artifacts[domain] = {
                    "kind": "snapshot_parquet",
                    "uri": uri,
                    "content_hash": hashlib.sha256(payload).hexdigest(),
                    "schema_hash": hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest(),
                    "row_count": len(rows),
                    "semantic_hash": _rows_semantic_hash(list(rows)),
                }
                row_count_total += len(rows)

        artifact_set_hash = hashlib.sha256(_canonical_json(artifacts).encode("utf-8")).hexdigest()
        snapshot_semantic_hash = hashlib.sha256(
            _canonical_json(
                {domain: entry["semantic_hash"] for domain, entry in artifacts.items()}
            ).encode("utf-8")
        ).hexdigest()
        manifest_uri = logical_daily_snapshot_manifest_uri(
            snapshot_id, source_as_of, source_vintage_as_of
        )
        manifest = {
            "snapshot_id": snapshot_id,
            "snapshot_contract_version": LOGICAL_DAILY_SNAPSHOT_CONTRACT,
            "snapshot_base_hash": base_hash,
            "snapshot_builder_code_fingerprint": fingerprint,
            "canonical_run_id": canonical_run_id,
            "canonical_manifest_uri": str(canonical_record["manifest_uri"]),
            "canonical_manifest_hash": str(canonical_record["manifest_hash"]),
            "market_as_of": source_as_of.isoformat(),
            "source_vintage_as_of": source_vintage_as_of.isoformat(),
            "canonical_requested_domains_hash": str(canonical_record["requested_domains_hash"]),
            "canonical_selected_semantic_hash": str(canonical_record["selected_semantic_hash"]),
            "requested_domains": list(requested_domains),
            "artifacts": artifacts,
            "artifact_set_hash": artifact_set_hash,
            "snapshot_semantic_hash": snapshot_semantic_hash,
            "row_count_total": row_count_total,
            "status": "SUCCESS",
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False).encode(
            "utf-8"
        )
        write_plan = [
            (self.normalized_root / str(artifacts[domain]["uri"]), payload)
            for domain, payload in artifact_payloads.items()
        ]
        write_plan.append((self.normalized_root / manifest_uri, manifest_bytes))
        for path, payload in write_plan:
            _assert_immutable_compatible(path, payload)
        for path, payload in write_plan[:-1]:
            _write_immutable(path, payload)
        _write_immutable(write_plan[-1][0], write_plan[-1][1])
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        completed = datetime.now(UTC)
        self._commit_ledger(
            snapshot_id=snapshot_id,
            canonical_run_id=canonical_run_id,
            canonical_manifest_uri=str(canonical_record["manifest_uri"]),
            canonical_manifest_hash=str(canonical_record["manifest_hash"]),
            canonical_as_of=source_as_of,
            requested_domains_json=_canonical_json(list(requested_domains)),
            requested_domains_hash=str(canonical_record["requested_domains_hash"]),
            fingerprint=fingerprint,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            snapshot_semantic_hash=snapshot_semantic_hash,
            row_count_total=row_count_total,
            started=started,
            completed=completed,
            contract_version=LOGICAL_DAILY_SNAPSHOT_CONTRACT,
        )
        return SnapshotBuildResult(
            snapshot_id=snapshot_id,
            canonical_run_id=canonical_run_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            snapshot_semantic_hash=snapshot_semantic_hash,
            row_count_total=row_count_total,
            status="SUCCESS",
            idempotent_replay=False,
        )

    def _commit_ledger(
        self,
        *,
        snapshot_id: str,
        canonical_run_id: str,
        canonical_manifest_uri: str,
        canonical_manifest_hash: str,
        canonical_as_of: datetime,
        requested_domains_json: str,
        requested_domains_hash: str,
        fingerprint: str,
        manifest_uri: str,
        manifest_hash: str,
        artifact_set_hash: str,
        snapshot_semantic_hash: str,
        row_count_total: int,
        started: datetime,
        completed: datetime,
        contract_version: str = SNAPSHOT_CONTRACT_VERSION,
    ) -> None:
        """One transaction: duplicate check + INSERT. A failure rolls
        back; the deterministic file-side anchor lets the exact retry
        replay idempotently."""
        self.conn.execute("BEGIN TRANSACTION")
        try:
            dup = self.conn.execute(
                "SELECT 1 FROM meta_snapshot_build WHERE snapshot_id = ?",
                [snapshot_id],
            ).fetchone()
            if dup is not None:
                msg = (
                    f"snapshot {snapshot_id} already exists in the ledger - "
                    "conflicting duplicate execution (repair required)"
                )
                raise SnapshotBuilderError(msg)
            self.conn.execute(
                f"INSERT INTO meta_snapshot_build ({', '.join(SNAPSHOT_LEDGER_COLUMNS)}) "
                f"VALUES ({', '.join(['?'] * len(SNAPSHOT_LEDGER_COLUMNS))})",
                [
                    snapshot_id,
                    canonical_run_id,
                    canonical_manifest_uri,
                    canonical_manifest_hash,
                    canonical_as_of,
                    requested_domains_json,
                    requested_domains_hash,
                    contract_version,
                    fingerprint,
                    manifest_uri,
                    manifest_hash,
                    artifact_set_hash,
                    snapshot_semantic_hash,
                    row_count_total,
                    "SUCCESS",
                    None,
                    started,
                    completed,
                ],
            )
            self.conn.execute("COMMIT")
        except Exception:
            import contextlib

            with contextlib.suppress(Exception):
                self.conn.execute("ROLLBACK")
            raise
