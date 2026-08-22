"""Version immutability + STAGING service rules tests (R2-P1-10 / R2-P1-11)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from ashare_state.storage import apply_migrations
from ashare_state.storage.versioning import (
    VersioningError,
    activate_feature_set,
    activate_universe,
    assert_artifact_insert_validated,
    assert_feature_set_members_mutable,
    assert_snapshot_insert_validated,
    assert_universe_rule_mutable,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.mark.integration
class TestFeatureSetImmutability:
    def _register(self, conn, version: str = "fs-v1") -> None:
        conn.execute(
            "INSERT INTO meta_feature_set VALUES (?, ?, ?, ?, ?)",
            [version, "h" * 64, "DRAFT", datetime.now(UTC), "test"],
        )
        conn.execute(
            "INSERT INTO meta_feature_set_member VALUES (?, ?, ?, ?)",
            [version, "F1", "1.0.0", "DEFAULT"],
        )

    def test_draft_members_mutable(self, conn):
        self._register(conn)
        assert_feature_set_members_mutable(conn, "fs-v1")  # no raise

    def test_active_members_immutable(self, conn):
        self._register(conn)
        activate_feature_set(conn, "fs-v1")
        with pytest.raises(VersioningError, match="immutable"):
            assert_feature_set_members_mutable(conn, "fs-v1")

    def test_double_activation_rejected(self, conn):
        self._register(conn)
        activate_feature_set(conn, "fs-v1")
        with pytest.raises(VersioningError, match="already ACTIVE"):
            activate_feature_set(conn, "fs-v1")

    def test_activation_requires_registration(self, conn):
        with pytest.raises(VersioningError, match="not registered"):
            activate_feature_set(conn, "nope")


@pytest.mark.integration
class TestUniverseImmutability:
    def _register(self, conn) -> None:
        conn.execute(
            "INSERT INTO dim_universe VALUES (?, ?, ?, ?, ?, ?)",
            ["ALL_A", "v1", "all a-shares", "rule-v1", "test", datetime.now(UTC)],
        )

    def test_rule_immutable_after_activation(self, conn):
        self._register(conn)
        activate_universe(conn, "ALL_A", "v1")
        assert_universe_rule_mutable(conn, "ALL_A", "v1", "rule-v1")  # same rule ok
        with pytest.raises(VersioningError, match="immutable"):
            assert_universe_rule_mutable(conn, "ALL_A", "v1", "rule-v2")

    def test_unactivated_rule_mutable(self, conn):
        self._register(conn)
        assert_universe_rule_mutable(conn, "ALL_A", "v1", "rule-v2")  # no raise


@pytest.mark.integration
class TestStagingServiceRule:
    def test_snapshot_staging_insert_forbidden(self):
        with pytest.raises(VersioningError, match="DATA_VALIDATED"):
            assert_snapshot_insert_validated("STAGING")

    def test_snapshot_validated_ok(self):
        assert_snapshot_insert_validated("DATA_VALIDATED")

    def test_artifact_staging_insert_forbidden(self):
        with pytest.raises(VersioningError, match="FEATURE_VALIDATED"):
            assert_artifact_insert_validated("STAGING")

    def test_artifact_validated_ok(self):
        assert_artifact_insert_validated("FEATURE_VALIDATED")
