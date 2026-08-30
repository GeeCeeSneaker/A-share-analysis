"""Publish validation + lineage contract tests (R2 audit section 33, Publish group)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ashare_state.pipeline import (
    PublishStateError,
    publish_snapshot,
    record_artifact_dq_finding,
    validate_artifact_for_publish,
)
from ashare_state.pipeline.mock_e2e import (
    SKELETON_FEATURE_SET_VERSION,
    run_mock_e2e,
)
from ashare_state.storage.connection import DuckDBConnectionManager


@pytest.fixture
def base(tmp_path: Path):
    db = tmp_path / "atlas.duckdb"
    return run_mock_e2e(db, tmp_path / "data", start=date(2026, 8, 3), end=date(2026, 8, 14))


def _kwargs(conn, base) -> dict:
    """Publish kwargs carrying a RECOVERY run (R3-P0-18)."""
    import uuid as uuid_mod
    from datetime import UTC, datetime

    recovery_run = str(uuid_mod.uuid4())
    conn.execute(
        "INSERT INTO meta_pipeline_run "
        "(pipeline_run_id, run_type, status, started_at, code_commit, "
        "environment_lock_hash, config_hash, source_policy_version, "
        "availability_policy_version) "
        "VALUES (?, 'RECOVERY', 'FEATURE_VALIDATED', ?, ?, ?, ?, ?, ?)",
        [
            recovery_run,
            datetime.now(UTC),
            "skeleton-commit",
            "skeleton-env",
            "skeleton-config",
            "source-policy-mock-v1",
            "availability-mock-v1",
        ],
    )
    return {
        "trade_date": date(2026, 8, 18),
        "data_snapshot_id": base.data_snapshot_id,
        "feature_artifact_set_id": base.feature_artifact_set_id,
        "feature_set_version": SKELETON_FEATURE_SET_VERSION,
        "universes": [("ALL_A", "v1")],
        "pipeline_run_id": recovery_run,
        "data_root": base.data_root,
    }


@pytest.mark.integration
class TestArtifactValidationGate:
    def test_publish_requires_validation_record(self, base, tmp_path: Path):
        """R2-P0-05: no meta_artifact_validation row -> BLOCK."""
        db = tmp_path / "fresh.duckdb"
        fresh = run_mock_e2e(db, tmp_path / "fdata", start=date(2026, 8, 3), end=date(2026, 8, 14))
        manager = DuckDBConnectionManager(db)
        with manager.owner("read_write") as conn:
            conn.execute(
                "DELETE FROM meta_artifact_validation WHERE feature_artifact_set_id = ?",
                [fresh.feature_artifact_set_id],
            )
            with pytest.raises(PublishStateError, match="ARTIFACT_VALIDATION_REQUIRED"):
                publish_snapshot(conn, **_kwargs(conn, fresh))

    def test_publish_blocks_fallback_count(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            record_artifact_dq_finding(
                conn,
                feature_artifact_set_id=base.feature_artifact_set_id,
                finding_class="IDENTITY_FALLBACK",
            )
            validate_artifact_for_publish(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=base.feature_artifact_set_id,
                validator_code_commit="test-commit",
            )
            with pytest.raises(PublishStateError, match="IDENTITY_FALLBACK_ZERO"):
                publish_snapshot(conn, **_kwargs(conn, base))

    def test_publish_blocks_blocking_dq(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            record_artifact_dq_finding(
                conn,
                feature_artifact_set_id=base.feature_artifact_set_id,
                finding_class="BLOCKING_DQ",
            )
            record_artifact_dq_finding(
                conn,
                feature_artifact_set_id=base.feature_artifact_set_id,
                finding_class="BLOCKING_DQ",
            )
            record_artifact_dq_finding(
                conn,
                feature_artifact_set_id=base.feature_artifact_set_id,
                finding_class="BLOCKING_DQ",
            )
            validate_artifact_for_publish(
                conn,
                data_root=base.data_root,
                feature_artifact_set_id=base.feature_artifact_set_id,
                validator_code_commit="test-commit",
            )
            with pytest.raises(PublishStateError, match="BLOCKING_DQ_ZERO"):
                publish_snapshot(conn, **_kwargs(conn, base))


@pytest.mark.integration
class TestProductionRunRequired:
    def test_production_publish_requires_pipeline_run(self, base):
        """R3-P0-18: no run-less publish exists AT ALL."""
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = None
            with pytest.raises(PublishStateError, match="requires pipeline_run_id"):
                publish_snapshot(conn, **kwargs)

    def test_recovery_run_can_republish(self, base):
        """R3-P0-18 replacement semantics: recovery goes through a RECOVERY
        run - the old manual escape hatch is gone."""
        import uuid as uuid_mod
        from datetime import UTC, datetime

        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            recovery_run = str(uuid_mod.uuid4())
            conn.execute(
                "INSERT INTO meta_pipeline_run "
                "(pipeline_run_id, run_type, status, started_at, code_commit, "
                "environment_lock_hash, config_hash, source_policy_version, "
                "availability_policy_version) "
                "VALUES (?, 'RECOVERY', 'FEATURE_VALIDATED', ?, ?, ?, ?, ?, ?)",
                [
                    recovery_run,
                    datetime.now(UTC),
                    "skeleton-commit",
                    "skeleton-env",
                    "skeleton-config",
                    "source-policy-mock-v1",
                    "availability-mock-v1",
                ],
            )
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = recovery_run
            pid = publish_snapshot(conn, **kwargs)
            assert pid
            assert pid


@pytest.mark.integration
class TestFullLineage:
    def _new_run(self, conn, run_type: str = "EOD") -> str:
        """A run matching the mock artifact's lineage triple (only the
        specific field under test is then mutated)."""
        run_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO meta_pipeline_run "
            "(pipeline_run_id, run_type, status, started_at, code_commit, "
            "environment_lock_hash, config_hash, source_policy_version, "
            "availability_policy_version) "
            "VALUES (?, ?, 'FEATURE_VALIDATED', ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                run_type,
                datetime.now(UTC),
                "skeleton-commit",
                "skeleton-env",
                "skeleton-config",
                "source-policy-mock-v1",
                "availability-mock-v1",
            ],
        )
        return run_id

    def test_rejects_artifact_calc_run_mismatch(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            other_run = self._new_run(conn)
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = other_run
            with pytest.raises(PublishStateError, match="was computed by run"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_source_policy_mismatch(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            run_id = self._new_run(conn)  # run policy = source-policy-mock-v1
            conn.execute(
                "UPDATE meta_feature_artifact_set SET calc_run_id = ? "
                "WHERE feature_artifact_set_id = ?",
                [run_id, base.feature_artifact_set_id],
            )
            # snapshot policy diverges from the run's
            conn.execute(
                "UPDATE meta_data_snapshot SET source_policy_version = 'sp-v9' "
                "WHERE data_snapshot_id = ?",
                [base.data_snapshot_id],
            )
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = run_id
            with pytest.raises(PublishStateError, match="source_policy_version mismatch"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_availability_policy_mismatch(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            run_id = self._new_run(conn)  # run policy = availability-mock-v1
            conn.execute(
                "UPDATE meta_feature_artifact_set SET calc_run_id = ? "
                "WHERE feature_artifact_set_id = ?",
                [run_id, base.feature_artifact_set_id],
            )
            conn.execute(
                "UPDATE meta_data_snapshot SET availability_policy_version = 'ap-v9' "
                "WHERE data_snapshot_id = ?",
                [base.data_snapshot_id],
            )
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = run_id
            with pytest.raises(PublishStateError, match="availability_policy_version mismatch"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_code_commit_mismatch(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            run_id = self._new_run(conn)
            conn.execute(
                "UPDATE meta_feature_artifact_set SET calc_run_id = ?, code_commit = 'OTHER' "
                "WHERE feature_artifact_set_id = ?",
                [run_id, base.feature_artifact_set_id],
            )
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = run_id
            with pytest.raises(PublishStateError, match="code_commit mismatch"):
                publish_snapshot(conn, **kwargs)

    def test_rejects_config_hash_mismatch(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            run_id = self._new_run(conn)
            conn.execute(
                "UPDATE meta_feature_artifact_set SET calc_run_id = ?, config_hash = 'OTHER' "
                "WHERE feature_artifact_set_id = ?",
                [run_id, base.feature_artifact_set_id],
            )
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = run_id
            with pytest.raises(PublishStateError, match="config_hash mismatch"):
                publish_snapshot(conn, **kwargs)

    def test_recovery_run_may_republish_foreign_artifact(self, base):
        with DuckDBConnectionManager(base.db_path).owner("read_write") as conn:
            recovery = self._new_run(conn, run_type="RECOVERY")
            kwargs = _kwargs(conn, base)
            kwargs["pipeline_run_id"] = recovery
            pid = publish_snapshot(conn, **kwargs)
            assert pid
