"""Failure injection tests (design ruling section 7, scenarios A-D).

A. file moved, DB not registered         -> orphan file invisible, cleanable
B. snapshot registered, not published     -> latest still points to previous
C. artifact validated, publish txn crashed -> artifact invisible to latest
D. publish transaction fails              -> old PUBLISHED preserved
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_state.pipeline import (
    artifact_files_for_publish,
    find_orphan_files,
    latest_published,
    publish_snapshot,
)
from ashare_state.pipeline.mock_e2e import run_mock_e2e
from ashare_state.storage.connection import DuckDBConnectionManager


@pytest.fixture
def base_run(tmp_path: Path):
    db = tmp_path / "atlas.duckdb"
    data_root = tmp_path / "data"
    return run_mock_e2e(db, data_root, start=date(2026, 8, 3), end=date(2026, 8, 14))


class TestScenarioA_OrphanFile:
    def test_unregistered_file_is_orphan_and_invisible(self, base_run):
        """Crash between os.replace() and component registration."""
        orphan_rel = (
            "features/security/layer=base/family=skeleton/version=0.0.1"
            "/year=2026/month=99/part-zombie-9999.parquet"
        )
        orphan_path = base_run.data_root / orphan_rel
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(b"orphan")

        manager = DuckDBConnectionManager(base_run.db_path)
        with manager.owner("read_only") as conn:
            # invisible to the publish contract: not in any component manifest
            files = artifact_files_for_publish(conn, base_run.publish_ids[0])
            assert orphan_rel not in {f["file_uri"] for f in files}
            # but detectable by the startup recovery check (P1-01: data_root)
            orphans = find_orphan_files(conn, base_run.data_root)
        assert orphan_path in orphans


class TestScenarioB_SnapshotWithoutPublish:
    def test_latest_unchanged_when_snapshot_not_published(self, base_run, tmp_path: Path):
        """A DATA_VALIDATED snapshot alone never flips latest."""
        trade_date = date(2026, 8, 17)
        manager = DuckDBConnectionManager(base_run.db_path)
        with manager.owner("read_write") as conn:
            # register a new snapshot without publishing
            conn.execute(
                "INSERT INTO meta_data_snapshot VALUES "
                "(?, ?, ?, ?, ?, ?, ?, 'DATA_VALIDATED', ?, ?)",
                [
                    "snap-new",
                    datetime.now(UTC),
                    "availability-mock-v1",
                    "source-policy-mock-v1",
                    "schema-m0",
                    "0" * 64,
                    datetime.now(UTC),
                    None,
                    "scenario B",
                ],
            )
            latest = latest_published(conn, trade_date)
            assert latest is None  # nothing published for the new date
            previous = latest_published(conn, date(2026, 8, 14))
            assert previous is not None
            assert previous["publish_id"] == base_run.publish_ids[0]


class TestScenarioC_ArtifactWithoutPublish:
    def test_validated_artifact_invisible_to_latest(self, base_run):
        """FEATURE_VALIDATED but publish txn never ran -> readers see nothing."""
        manager = DuckDBConnectionManager(base_run.db_path)
        with manager.owner("read_write") as conn:
            # register a second artifact set on the same snapshot, never publish it
            conn.execute(
                "INSERT INTO meta_feature_artifact_set VALUES "
                "(?, ?, 'skeleton-v0', ?, ?, ?, ?, ?, 'FEATURE_VALIDATED', ?, ?)",
                [
                    "art-unpublished",
                    base_run.data_snapshot_id,
                    "skeleton-commit",
                    "skeleton-env",
                    "skeleton-config",
                    None,
                    "1" * 64,
                    datetime.now(UTC),
                    datetime.now(UTC),
                ],
            )
            latest = latest_published(conn, date(2026, 8, 14))
            assert latest["feature_artifact_set_id"] == base_run.feature_artifact_set_id
            assert latest["feature_artifact_set_id"] != "art-unpublished"


class TestScenarioD_PublishTransactionFailure:
    def test_failed_publish_preserves_old_published(self, base_run):
        manager = DuckDBConnectionManager(base_run.db_path)
        with manager.owner("read_write") as conn:
            # force a failure inside the transaction: duplicate universe row
            # violates the primary key -> whole txn rolls back
            with pytest.raises(Exception):
                publish_snapshot(
                    conn,
                    trade_date=date(2026, 8, 14),
                    data_snapshot_id=base_run.data_snapshot_id,
                    feature_artifact_set_id=base_run.feature_artifact_set_id,
                    feature_set_version="skeleton-v0",
                    universes=[("ALL_A", "v1"), ("ALL_A", "v1")],  # PK violation
                    quality_grade="SHOULD-NOT-APPEAR",
                )
            # old PUBLISHED preserved untouched
            latest = latest_published(conn, date(2026, 8, 14))
            assert latest["publish_id"] == base_run.publish_ids[0]
            assert latest["quality_grade"] != "SHOULD-NOT-APPEAR"
            # no SUPERSEDED rows were left behind by the failed attempt
            rows = conn.execute(
                "SELECT count(*) FROM meta_publish_snapshot WHERE status = 'SUPERSEDED'"
            ).fetchone()[0]
            assert rows == 0

    def test_publish_requires_validated_states(self, base_run):
        """Publishing from a STAGING snapshot is refused before any write."""
        manager = DuckDBConnectionManager(base_run.db_path)
        with manager.owner("read_write") as conn:
            conn.execute(
                "INSERT INTO meta_data_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, 'STAGING', ?, ?)",
                [
                    "snap-staging",
                    datetime.now(UTC),
                    None,
                    None,
                    None,
                    "2" * 64,
                    datetime.now(UTC),
                    None,
                    None,
                ],
            )
            from ashare_state.pipeline import PublishStateError

            with pytest.raises(PublishStateError, match="DATA_VALIDATED"):
                publish_snapshot(
                    conn,
                    trade_date=date(2026, 8, 14),
                    data_snapshot_id="snap-staging",
                    feature_artifact_set_id=base_run.feature_artifact_set_id,
                    feature_set_version="skeleton-v0",
                    universes=[("ALL_A", "v1")],
                )
            latest = latest_published(conn, date(2026, 8, 14))
            assert latest["publish_id"] == base_run.publish_ids[0]
