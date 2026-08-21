"""Mock end-to-end contract tests (M0 exit criterion A6).

Validates the full storage contract through the deterministic FixtureProvider:
snapshot -> artifact -> publish -> readers, including same-trade_date
republish supersede semantics and exact replay of superseded publishes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ashare_state.pipeline import (
    artifact_files_for_publish,
    latest_published,
    publish_universes,
    resolve_publish,
)
from ashare_state.pipeline.mock_e2e import run_mock_e2e
from ashare_state.storage.connection import DuckDBConnectionManager


@pytest.fixture
def e2e(tmp_path: Path):
    db = tmp_path / "atlas.duckdb"
    data_root = tmp_path / "data"
    return run_mock_e2e(
        db,
        data_root,
        start=date(2026, 8, 3),
        end=date(2026, 8, 14),
        republish=True,
    )


@pytest.mark.integration
class TestMockPipelineContract:
    def test_publish_visible_as_latest(self, e2e):
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            latest = latest_published(conn, date(2026, 8, 14))
            assert latest is not None
            # second publish superseded the first
            assert latest["publish_id"] == e2e.publish_ids[-1]

    def test_superseded_publish_exact_replay(self, e2e):
        """Design ruling: old PUBLISHED -> SUPERSEDED but still exactly replayable."""
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            old_pid = e2e.publish_ids[0]
            old = resolve_publish(conn, old_pid)
            assert old["status"] == "SUPERSEDED"
            new = resolve_publish(conn, e2e.publish_ids[1])
            assert new["status"] == "PUBLISHED"
            assert new["previous_publish_id"] == old_pid

    def test_universes_recovered_from_publish(self, e2e):
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            universes = publish_universes(conn, e2e.publish_ids[-1])
        assert set(universes) == {("ALL_A", "v1"), ("CORE_TRADABLE", "v1")}

    def test_artifact_files_resolved_via_manifest_not_glob(self, e2e):
        """Files resolve exclusively via meta_feature_artifact_component."""
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            files = artifact_files_for_publish(conn, e2e.publish_ids[-1])
        assert files, "no artifact components registered"
        for f in files:
            physical = e2e.data_root / f["file_uri"]
            assert physical.is_file(), f["file_uri"]

    def test_files_on_disk_match_content_hashes(self, e2e):
        import hashlib

        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            files = artifact_files_for_publish(conn, e2e.publish_ids[-1])
        for f in files:
            digest = hashlib.sha256((e2e.data_root / f["file_uri"]).read_bytes()).hexdigest()
            assert digest == f["content_hash"]

    def test_pipeline_run_marked_published(self, e2e):
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            status = conn.execute(
                "SELECT status FROM meta_pipeline_run ORDER BY started_at DESC LIMIT 1"
            ).fetchone()[0]
        assert status == "PUBLISHED"

    def test_snapshot_and_artifact_states(self, e2e):
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            snap = conn.execute(
                "SELECT status, data_manifest_hash FROM meta_data_snapshot "
                "WHERE data_snapshot_id = ?",
                [e2e.data_snapshot_id],
            ).fetchone()
            art = conn.execute(
                "SELECT status FROM meta_feature_artifact_set WHERE feature_artifact_set_id = ?",
                [e2e.feature_artifact_set_id],
            ).fetchone()
        assert snap[0] == "DATA_VALIDATED"
        assert snap[1] == e2e.data_manifest_hash
        assert art[0] == "FEATURE_VALIDATED"

    def test_feature_set_registry_resolvable(self, e2e):
        """Design ruling P0-3: feature_set_version resolves to members."""
        manager = DuckDBConnectionManager(e2e.db_path)
        with manager.owner("read_only") as conn:
            rows = conn.execute(
                "SELECT m.feature_id, m.feature_version, m.param_set_id "
                "FROM meta_feature_set s JOIN meta_feature_set_member m "
                "ON s.feature_set_version = m.feature_set_version "
                "WHERE s.feature_set_version = 'skeleton-v0'"
            ).fetchall()
        assert rows == [("SKELETON_CLOSE", "0.0.1", "DEFAULT")]

    def test_two_clean_rebuilds_produce_identical_hashes(self, tmp_path: Path):
        """Same fixture input -> identical manifest hashes across rebuilds."""
        run_a = run_mock_e2e(
            tmp_path / "a" / "atlas.duckdb",
            tmp_path / "a" / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        run_b = run_mock_e2e(
            tmp_path / "b" / "atlas.duckdb",
            tmp_path / "b" / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        assert run_a.data_manifest_hash == run_b.data_manifest_hash
        assert run_a.artifact_manifest_hash == run_b.artifact_manifest_hash
