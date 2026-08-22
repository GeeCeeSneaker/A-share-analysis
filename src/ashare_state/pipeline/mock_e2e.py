"""Mock end-to-end skeleton pipeline (M0 exit criterion A6).

Validates the FULL storage contract with the deterministic FixtureProvider:

    Mock bars -> provider-normalized parquet (atomic commit)
              -> DATA_VALIDATED snapshot (+components, manifest hash)
              -> skeleton feature parquet
              -> FEATURE_VALIDATED artifact set (+components, feature set registry)
              -> atomic PUBLISHED publish (+universes)

This is a CONTRACT test harness, not a business pipeline: the "skeleton
feature" deliberately carries no market semantics so nothing unvalidated
leaks into canonical business logic (design ruling Q1 condition).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from ashare_state.identity import resolve_security_identity
from ashare_state.pipeline.publish import publish_snapshot, record_artifact_validation
from ashare_state.providers.mock import FixtureProvider
from ashare_state.storage.atomic_files import (
    ComponentIdentity,
    compute_manifest_hash,
    schema_hash_of,
    write_file_atomic,
)
from ashare_state.storage.connection import DuckDBConnectionManager
from ashare_state.storage.migrations import apply_migrations

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

SKELETON_FEATURE_SET_VERSION = "skeleton-v0"
SKELETON_FEATURE_ID = "SKELETON_CLOSE"
SKELETON_FEATURE_VERSION = "0.0.1"
SKELETON_PARAM_SET_ID = "DEFAULT"

_BAR_SCHEMA_TEXT = (
    "provider_symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE, "
    "low DOUBLE, close DOUBLE, pre_close DOUBLE, volume_shares BIGINT, "
    "amount_cny DOUBLE"
)
_FEATURE_SCHEMA_TEXT = "security_id VARCHAR, trade_date DATE, skeleton_close DOUBLE"


@dataclass
class MockE2eResult:
    db_path: Path
    data_root: Path
    data_snapshot_id: str = ""
    data_manifest_hash: str = ""
    feature_artifact_set_id: str = ""
    artifact_manifest_hash: str = ""
    publish_ids: list[str] = field(default_factory=list)
    canonical_files: list[str] = field(default_factory=list)
    feature_files: list[str] = field(default_factory=list)


def _register_feature_set(conn: DuckDBPyConnection) -> None:
    """Design ruling P0-3: feature_set_version must resolve BEFORE the first
    artifact set exists.

    R3-P1-03: the registered definition_hash uses the SAME formula as
    storage.versioning.recompute_feature_set_hash so the publish-time
    self-check passes for honest sets.
    """
    import hashlib

    members = [(SKELETON_FEATURE_ID, SKELETON_FEATURE_VERSION, SKELETON_PARAM_SET_ID)]
    definition_hash = hashlib.sha256(
        "|".join(f"{fid}:{fv}:{psid}" for fid, fv, psid in members).encode()
    ).hexdigest()
    existing = conn.execute(
        "SELECT 1 FROM meta_feature_set WHERE feature_set_version = ?",
        [SKELETON_FEATURE_SET_VERSION],
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO meta_feature_set VALUES (?, ?, ?, ?, ?)",
            [
                SKELETON_FEATURE_SET_VERSION,
                definition_hash,
                "ACTIVE",
                datetime.now(UTC),
                "M0 contract-test skeleton - no market semantics",
            ],
        )
        conn.execute(
            "INSERT INTO meta_feature_set_member VALUES (?, ?, ?, ?)",
            [
                SKELETON_FEATURE_SET_VERSION,
                SKELETON_FEATURE_ID,
                SKELETON_FEATURE_VERSION,
                SKELETON_PARAM_SET_ID,
            ],
        )


def _feature_definition_hash() -> str:
    return hashlib.sha256(
        f"{SKELETON_FEATURE_ID}:{SKELETON_FEATURE_VERSION}:{SKELETON_PARAM_SET_ID}".encode()
    ).hexdigest()


def run_mock_e2e(
    db_path: Path,
    data_root: Path,
    *,
    start: date,
    end: date,
    republish: bool = False,
) -> MockE2eResult:
    """Run the skeleton pipeline once (or twice with republish=True)."""
    result = MockE2eResult(db_path=db_path, data_root=data_root)
    manager = DuckDBConnectionManager(db_path)
    # src/ashare_state/pipeline/mock_e2e.py -> repo root
    migrations_dir = Path(__file__).resolve().parents[3] / "migrations"

    with manager.owner("read_write") as conn:
        apply_migrations(conn, migrations_dir)

        provider = FixtureProvider()
        bars = provider.get_daily_bars(start, end)

        # identities are generated FIRST so filenames carry output identity
        # (audit P0-01: two runs must physically coexist, never overwrite)
        result.data_snapshot_id = str(uuid.uuid4())
        result.feature_artifact_set_id = str(uuid.uuid4())
        # R2-P1-08: full 32-hex tags (8-hex tags collide eventually)
        snap_tag = result.data_snapshot_id.replace("-", "")
        artifact_tag = result.feature_artifact_set_id.replace("-", "")

        # -- 1. provider-normalized canonical files (atomic commit) ---------
        canonical_dir = data_root / "canonical" / "daily_bar"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        canonical_components: list[ComponentIdentity] = []
        by_month: dict[str, list] = {}
        for bar in bars:
            by_month.setdefault(bar.trade_date.strftime("%Y-%m"), []).append(bar)

        canonical_rels: list[str] = []
        for month, month_bars in sorted(by_month.items()):
            table = pa.table(
                {
                    "provider_symbol": [b.provider_symbol for b in month_bars],
                    "trade_date": [b.trade_date for b in month_bars],
                    "open": [b.open for b in month_bars],
                    "high": [b.high for b in month_bars],
                    "low": [b.low for b in month_bars],
                    "close": [b.close for b in month_bars],
                    "pre_close": [b.pre_close for b in month_bars],
                    "volume_shares": [b.volume_shares for b in month_bars],
                    "amount_cny": [b.amount_cny for b in month_bars],
                }
            )
            rel = (
                f"canonical/daily_bar/year={month[:4]}/month={month[5:]}/"
                f"part-{snap_tag}-0001.parquet"
            )
            final = data_root / rel
            buf = pa.BufferOutputStream()
            pq.write_table(table, buf, compression="zstd")
            content_hash = write_file_atomic(final, buf.getvalue().to_pybytes())
            result.canonical_files.append(rel)
            canonical_rels.append(rel)
            canonical_components.append(
                ComponentIdentity(
                    dataset="daily_bar",
                    logical_partition_key=f"year={month[:4]}/month={month[5:]}",
                    content_hash=content_hash,
                    schema_hash=schema_hash_of(_BAR_SCHEMA_TEXT),
                    row_count=len(month_bars),
                    provider="mock",
                    source_revision="r1",
                )
            )

        # -- 2. DATA_VALIDATED snapshot ------------------------------------
        result.data_manifest_hash = compute_manifest_hash(canonical_components)
        conn.execute(
            "INSERT INTO meta_data_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, 'DATA_VALIDATED', ?, ?)",
            [
                result.data_snapshot_id,
                datetime.now(UTC),
                "availability-mock-v1",
                "source-policy-mock-v1",
                "schema-m0",
                result.data_manifest_hash,
                datetime.now(UTC),
                None,
                "mock e2e",
            ],
        )
        for rel, comp in zip(canonical_rels, canonical_components, strict=True):
            conn.execute(
                "INSERT INTO meta_data_snapshot_component VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    result.data_snapshot_id,
                    comp.dataset,
                    comp.logical_partition_key,
                    rel,
                    comp.content_hash,
                    comp.schema_hash,
                    comp.row_count,
                    comp.provider,
                    comp.source_revision,
                ],
            )

        # -- 3. skeleton feature output ------------------------------------
        _register_feature_set(conn)
        master = {e.provider_symbol: e for e in provider.get_security_master()}
        feature_rows: dict[str, list] = {}
        for bar in bars:
            entry = master[bar.provider_symbol]
            identity = resolve_security_identity(
                entry.exchange, "STOCK", bar.provider_symbol, entry.list_date
            )
            feature_rows.setdefault(bar.trade_date.strftime("%Y-%m"), []).append(
                (str(identity.security_id), bar.trade_date, bar.close)
            )

        feature_components: list[ComponentIdentity] = []
        for month, rows in sorted(feature_rows.items()):
            partition = (
                f"layer=base/family=skeleton/version=0.0.1/year={month[:4]}/month={month[5:]}"
            )
            rel = f"features/security/{partition}/part-{artifact_tag}-0001.parquet"
            final = data_root / rel
            table = pa.table(
                {
                    "security_id": [r[0] for r in rows],
                    "trade_date": [r[1] for r in rows],
                    "skeleton_close": [r[2] for r in rows],
                }
            )
            buf = pa.BufferOutputStream()
            pq.write_table(table, buf, compression="zstd")
            content_hash = write_file_atomic(final, buf.getvalue().to_pybytes())
            result.feature_files.append(rel)
            feature_components.append(
                ComponentIdentity(
                    dataset="security_feature_skeleton",
                    logical_partition_key=partition,
                    content_hash=content_hash,
                    schema_hash=schema_hash_of(_FEATURE_SCHEMA_TEXT),
                    row_count=len(rows),
                )
            )

        # -- 4. FEATURE_VALIDATED artifact set ------------------------------
        result.artifact_manifest_hash = compute_manifest_hash(feature_components)
        conn.execute(
            "INSERT INTO meta_feature_artifact_set VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, 'FEATURE_VALIDATED', ?, ?)",
            [
                result.feature_artifact_set_id,
                result.data_snapshot_id,
                SKELETON_FEATURE_SET_VERSION,
                "skeleton-commit",
                "skeleton-env",
                "skeleton-config",
                None,
                result.artifact_manifest_hash,
                datetime.now(UTC),
                datetime.now(UTC),
            ],
        )
        for rel, comp in zip(result.feature_files, feature_components, strict=True):
            conn.execute(
                "INSERT INTO meta_feature_artifact_component VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    result.feature_artifact_set_id,
                    "BASE",
                    "skeleton",
                    "0.0.1",
                    comp.logical_partition_key,
                    rel,
                    comp.content_hash,
                    comp.schema_hash,
                    comp.row_count,
                    None,
                ],
            )

        # -- 5. atomic publish ----------------------------------------------
        # universes must exist in dim_universe (audit P0-02 lineage gate)
        for universe_id, universe_version in (("ALL_A", "v1"), ("CORE_TRADABLE", "v1")):
            existing = conn.execute(
                "SELECT 1 FROM dim_universe WHERE universe_id = ? AND universe_version = ?",
                [universe_id, universe_version],
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO dim_universe VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        universe_id,
                        universe_version,
                        f"mock universe {universe_id}",
                        "mock-rule-v1",
                        "mock e2e",
                        datetime.now(UTC),
                    ],
                )
        # R2-P0-06: bind artifact to its producing run (lineage closes)
        pipeline_run_id = str(uuid.uuid4())
        conn.execute(
            "UPDATE meta_feature_artifact_set SET calc_run_id = ? "
            "WHERE feature_artifact_set_id = ?",
            [pipeline_run_id, result.feature_artifact_set_id],
        )
        conn.execute(
            "INSERT INTO meta_pipeline_run (pipeline_run_id, run_type, status, started_at) "
            "VALUES (?, 'EOD', 'FEATURE_VALIDATED', ?)",
            [pipeline_run_id, datetime.now(UTC)],
        )
        # R2-P0-05: validation record is a system invariant for publish
        record_artifact_validation(
            conn,
            feature_artifact_set_id=result.feature_artifact_set_id,
            validation_version="mock-v1",
            identity_fallback_count=0,
            blocking_dq_count=0,
        )
        universes = [("ALL_A", "v1"), ("CORE_TRADABLE", "v1")]
        pid = publish_snapshot(
            conn,
            trade_date=end,
            data_snapshot_id=result.data_snapshot_id,
            feature_artifact_set_id=result.feature_artifact_set_id,
            feature_set_version=SKELETON_FEATURE_SET_VERSION,
            universes=universes,
            pipeline_run_id=pipeline_run_id,
            quality_grade="MOCK",
        )
        result.publish_ids.append(pid)

        # optional second publish for the same trade_date (supersede path);
        # R2-P0-06: republish runs as an explicit RECOVERY run
        if republish:
            recovery_run_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO meta_pipeline_run (pipeline_run_id, run_type, status, started_at) "
                "VALUES (?, 'RECOVERY', 'FEATURE_VALIDATED', ?)",
                [recovery_run_id, datetime.now(UTC)],
            )
            pid2 = publish_snapshot(
                conn,
                trade_date=end,
                data_snapshot_id=result.data_snapshot_id,
                feature_artifact_set_id=result.feature_artifact_set_id,
                feature_set_version=SKELETON_FEATURE_SET_VERSION,
                universes=universes,
                pipeline_run_id=recovery_run_id,
                quality_grade="MOCK-RERUN",
            )
            result.publish_ids.append(pid2)

    return result


def verify_registered_files(result: MockE2eResult, registered: list[str]) -> bool:
    """Every registered logical URI exists on disk under data_root."""
    return all((result.data_root / rel).is_file() for rel in registered)
