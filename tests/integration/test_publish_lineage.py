"""Publish lineage gate tests (audit P0-02 + P0-06, section 27).

Every lineage invariant must BLOCK a bad publish before any write happens.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_state.pipeline import PublishStateError, publish_snapshot
from ashare_state.pipeline.mock_e2e import (
    SKELETON_FEATURE_SET_VERSION,
    run_mock_e2e,
)
from ashare_state.storage.connection import DuckDBConnectionManager


@pytest.fixture
def base(tmp_path: Path):
    db = tmp_path / "atlas.duckdb"
    data_root = tmp_path / "data"
    return run_mock_e2e(db, data_root, start=date(2026, 8, 3), end=date(2026, 8, 14))


def _valid_kwargs(base) -> dict:
    return {
        "trade_date": date(2026, 8, 18),  # a new trade date (no existing publish)
        "data_snapshot_id": base.data_snapshot_id,
        "feature_artifact_set_id": base.feature_artifact_set_id,
        "feature_set_version": SKELETON_FEATURE_SET_VERSION,
        "universes": [("ALL_A", "v1")],
    }


@pytest.mark.integration
class TestPublishLineageGate:
    def test_valid_publish_still_works(self, base):
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            pid = publish_snapshot(conn, **_valid_kwargs(base))
        assert pid

    def test_rejects_artifact_snapshot_mismatch(self, base, tmp_path: Path):
        """Artifact computed from snapshot B cannot publish under snapshot A."""
        other = run_mock_e2e(
            tmp_path / "other.duckdb",
            tmp_path / "otherdata",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            # register other's snapshot under base's db for the mismatch probe
            conn.execute(
                "INSERT INTO meta_data_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, 'DATA_VALIDATED', ?, ?)",
                [
                    other.data_snapshot_id,
                    datetime.now(UTC),
                    "availability-mock-v1",
                    "source-policy-mock-v1",
                    "schema-m0",
                    "0" * 64,
                    datetime.now(UTC),
                    None,
                    None,
                ],
            )
            kwargs = _valid_kwargs(base)
            kwargs["data_snapshot_id"] = other.data_snapshot_id
            with pytest.raises(PublishStateError, match="artifact .* was computed from"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_feature_set_mismatch(self, base):
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            kwargs = _valid_kwargs(base)
            kwargs["feature_set_version"] = "other-set-v9"
            with pytest.raises(PublishStateError, match="belongs to feature set"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_unknown_feature_set(self, base):
        """Artifact references the set, so unknown set = artifact mismatch,
        but a DIRECT unknown-set probe is covered by the artifact check."""
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            kwargs = _valid_kwargs(base)
            kwargs["feature_set_version"] = "never-registered-v0"
            with pytest.raises(PublishStateError):
                publish_snapshot(conn, **kwargs)

    def test_rejects_inactive_feature_set(self, base):
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            conn.execute(
                "UPDATE meta_feature_set SET status = 'RETIRED' WHERE feature_set_version = ?",
                [SKELETON_FEATURE_SET_VERSION],
            )
            with pytest.raises(PublishStateError, match="expected ACTIVE"):
                publish_snapshot(conn, **_valid_kwargs(base))

    def test_rejects_unknown_pipeline_run(self, base):
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            kwargs = _valid_kwargs(base)
            kwargs["pipeline_run_id"] = "run-that-never-existed"
            with pytest.raises(PublishStateError, match="pipeline run .* not registered"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_pipeline_not_feature_validated(self, base):
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            conn.execute(
                "INSERT INTO meta_pipeline_run (pipeline_run_id, run_type, status, started_at) "
                "VALUES (?, 'EOD', 'RUNNING', ?)",
                ["run-still-running", datetime.now(UTC)],
            )
            kwargs = _valid_kwargs(base)
            kwargs["pipeline_run_id"] = "run-still-running"
            with pytest.raises(PublishStateError, match="expected FEATURE_VALIDATED"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_unknown_universe(self, base):
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            kwargs = _valid_kwargs(base)
            kwargs["universes"] = [("NOT_REGISTERED", "v1")]
            with pytest.raises(PublishStateError, match="not registered in dim_universe"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_identity_fallback(self, base):
        """Audit P0-06: IDENTITY_FALLBACK security ids must BLOCK publish."""
        manager = DuckDBConnectionManager(base.db_path)
        with manager.owner("read_write") as conn:
            kwargs = _valid_kwargs(base)
            kwargs["fallback_security_ids"] = {"fallback-uuid-1", "fallback-uuid-2"}
            with pytest.raises(PublishStateError, match="NO_IDENTITY_FALLBACK"):
                publish_snapshot(conn, **kwargs)
