"""Migration runner integration tests (design ruling 8).

Covers M0 exit criteria:
- from-zero initialization applies all migrations
- re-run is idempotent (skips applied)
- modifying an applied migration BLOCKs startup
- a failing migration rolls back completely (transactional DDL)
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ashare_state.storage import (
    MigrationError,
    MigrationLedgerGapError,
    MigrationNamingError,
    MigrationTamperedError,
    applied_migrations,
    apply_migrations,
)
from ashare_state.storage.migrations import discover_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

EXPECTED_TABLES = {
    # 001
    "dim_security",
    "bridge_security_provider_symbol",
    "dim_trade_calendar",
    "dim_trading_rule",
    # 002
    "meta_data_source",
    "meta_provider_capability",
    "meta_provider_field_map",
    "meta_source_policy",
    "meta_tolerance_rule",
    "meta_ingest_run",
    # 003
    "dim_universe",
    "meta_pipeline_run",
    "meta_data_snapshot",
    "meta_data_snapshot_component",
    "meta_feature_artifact_set",
    "meta_feature_artifact_component",
    "meta_publish_snapshot",
    "meta_publish_universe",
    # 004
    "meta_feature_set",
    "meta_feature_set_member",
    # 005 canonical fact domains (task book section 8)
    "fact_daily_bar",
    "fact_security_status_daily",
    "fact_limit_price",
    "fact_adj_factor",
    "fact_corporate_action",
    # 011 (R4-B2 publish validation exactness)
    "meta_artifact_dq_finding",
    # 012 (R4-B2.1 validation closure)
    "meta_artifact_check_execution",
    # 013 (R4-B2.3 authoritative-input seal) adds columns only
    # 014 (CR-2 provider normalization + quarantine)
    "meta_provider_normalization_run",
    "meta_provider_quarantine",
    # 017 (CR-2.3 raw evidence trust anchor)
    "meta_raw_evidence_anchor",
    # 018 (CR-3 canonicalization)
    "meta_canonicalization_run",
    "meta_canonical_reconciliation_finding",
    # runner bootstrap
    "meta_schema_version",
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "atlas.duckdb"


@pytest.mark.integration
class TestFromZeroInit:
    def test_all_tables_created(self, db_path: Path):
        conn = duckdb.connect(str(db_path))
        try:
            applied = apply_migrations(conn, MIGRATIONS_DIR)
            assert len(applied) == 20
            tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
            assert tables >= EXPECTED_TABLES
        finally:
            conn.close()

    def test_idempotent_rerun(self, db_path: Path):
        conn = duckdb.connect(str(db_path))
        try:
            first = apply_migrations(conn, MIGRATIONS_DIR)
            second = apply_migrations(conn, MIGRATIONS_DIR)
            assert len(first) == 20
            assert second == []  # nothing new applied
            ledger = applied_migrations(conn)
            assert len(ledger) == 20
        finally:
            conn.close()


@pytest.mark.integration
class TestTamperDetection:
    def test_modified_applied_migration_blocks(self, db_path: Path, tmp_path: Path):
        # copy migrations to a temp dir so we can tamper safely
        tampered_dir = tmp_path / "migrations"
        tampered_dir.mkdir()
        for f in MIGRATIONS_DIR.glob("*.sql"):
            (tampered_dir / f.name).write_bytes(f.read_bytes())

        conn = duckdb.connect(str(db_path))
        try:
            apply_migrations(conn, tampered_dir)
            # tamper with an applied migration
            target = tampered_dir / "001_identity_calendar.sql"
            target.write_text(target.read_text(encoding="utf-8") + "\n-- tampered\n")
            with pytest.raises(MigrationTamperedError, match="BLOCKED"):
                apply_migrations(conn, tampered_dir)
        finally:
            conn.close()

    def test_tamper_check_runs_before_any_new_migration(self, db_path: Path, tmp_path: Path):
        """BLOCK must happen even when a new pending migration exists."""
        tampered_dir = tmp_path / "migrations"
        tampered_dir.mkdir()
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for f in files:
            (tampered_dir / f.name).write_bytes(f.read_bytes())

        conn = duckdb.connect(str(db_path))
        try:
            apply_migrations(conn, tampered_dir)
            # tamper 002 and add a new 021 (015..020 exist in the real repo set)
            target = tampered_dir / "002_provider_governance.sql"
            target.write_text(target.read_text(encoding="utf-8") + "\n-- tampered\n")
            (tampered_dir / "021_new_thing.sql").write_text(
                "CREATE TABLE tamper_probe (id INTEGER);"
            )
            with pytest.raises(MigrationTamperedError):
                apply_migrations(conn, tampered_dir)
            # the new migration must NOT have been applied
            tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
            assert "tamper_probe" not in tables
        finally:
            conn.close()


@pytest.mark.integration
class TestTransactionalRollback:
    def test_failing_migration_rolls_back_completely(self, db_path: Path, tmp_path: Path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        # first migration fine, second one breaks halfway
        (migrations_dir / "001_ok.sql").write_text("CREATE TABLE ok_table (id INTEGER);")
        (migrations_dir / "002_bad.sql").write_text(
            "CREATE TABLE partial_table (id INTEGER);\n"
            "CREATE TABLE will_fail (id INTEGER);\n"
            "CREATE TABLE will_fail (id INTEGER);\n"  # duplicate -> error
        )
        conn = duckdb.connect(str(db_path))
        try:
            with pytest.raises(MigrationError, match="rolled back"):
                apply_migrations(conn, migrations_dir)
            tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
            assert "ok_table" in tables
            assert "partial_table" not in tables  # rolled back
            ledger = applied_migrations(conn)
            assert "001" in ledger and "002" not in ledger
            # fixing the bad file allows progress
            (migrations_dir / "002_bad.sql").write_text("CREATE TABLE fixed_table (id INTEGER);")
            applied = apply_migrations(conn, migrations_dir)
            assert [r.migration_id for r in applied] == ["002"]
            tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
            assert "fixed_table" in tables
        finally:
            conn.close()


@pytest.mark.integration
class TestLedgerIntegrity:
    """Audit P1-05: deleted / renamed / mis-named migrations must BLOCK."""

    def _copy_migrations(self, tmp_path: Path) -> Path:
        target = tmp_path / "migrations"
        target.mkdir(exist_ok=True)
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            (target / f.name).write_bytes(f.read_bytes())
        return target

    def test_deleted_applied_migration_blocks(self, db_path: Path, tmp_path: Path):
        migrations_dir = self._copy_migrations(tmp_path)
        conn = duckdb.connect(str(db_path))
        try:
            apply_migrations(conn, migrations_dir)
            # delete an already-applied migration file: repo sequence gap
            # (R2-P1-09) fires first and equally BLOCKs startup
            (migrations_dir / "002_provider_governance.sql").unlink()
            from ashare_state.storage.migrations import MigrationSequenceGapError

            with pytest.raises((MigrationLedgerGapError, MigrationSequenceGapError)):
                apply_migrations(conn, migrations_dir)
        finally:
            conn.close()

    def test_repo_sequence_gap_blocks(self, tmp_path: Path):
        """Audit R2-P1-09: a gap in the repo sequence (001, 003, ...) blocks
        even on a FRESH database - a migration was never committed."""
        from ashare_state.storage.migrations import MigrationSequenceGapError

        migrations_dir = self._copy_migrations(tmp_path)
        (migrations_dir / "002_provider_governance.sql").unlink()
        conn = duckdb.connect(":memory:")
        try:
            with pytest.raises(MigrationSequenceGapError, match="consecutive"):
                apply_migrations(conn, migrations_dir)
        finally:
            conn.close()

    def test_renamed_applied_migration_blocks(self, db_path: Path, tmp_path: Path):
        migrations_dir = self._copy_migrations(tmp_path)
        conn = duckdb.connect(str(db_path))
        try:
            apply_migrations(conn, migrations_dir)
            # rename an already-applied migration file (same id, new name)
            old = migrations_dir / "003_run_snapshot_publish.sql"
            old.rename(migrations_dir / "003_renamed_oops.sql")
            with pytest.raises((MigrationLedgerGapError, MigrationTamperedError)):
                apply_migrations(conn, migrations_dir)
        finally:
            conn.close()

    def test_invalid_sql_filename_blocks(self, db_path: Path, tmp_path: Path):
        migrations_dir = self._copy_migrations(tmp_path)
        (migrations_dir / "bad_name.sql").write_text("CREATE TABLE nope (id INTEGER);")
        conn = duckdb.connect(str(db_path))
        try:
            with pytest.raises(MigrationNamingError, match="P1-05"):
                apply_migrations(conn, migrations_dir)
        finally:
            conn.close()

    def test_upgrade_from_prior_chain_applies_only_new_tail(self, db_path: Path, tmp_path: Path):
        """CR-2.1 audit §7 item 17: a database initialized on the
        PRIOR migration chain (001..014) upgrades cleanly when 015
        ships - only the new tail applies, prior files untouched."""
        upgrade_dir = tmp_path / "migrations"
        upgrade_dir.mkdir()
        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if int(f.name[:3]) <= 19:
                (upgrade_dir / f.name).write_bytes(f.read_bytes())
        conn = duckdb.connect(str(db_path))
        try:
            first = apply_migrations(conn, upgrade_dir)
            assert [r.migration_id for r in first] == [f"{i:03d}" for i in range(1, 20)]
            # ship 020 into the same directory set
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if int(f.name[:3]) == 20:
                    (upgrade_dir / f.name).write_bytes(f.read_bytes())
            second = apply_migrations(conn, upgrade_dir)
            assert [r.migration_id for r in second] == ["020"]
            ledger = applied_migrations(conn)
            assert len(ledger) == 20
            # the CR-2.1 seal columns exist on the upgraded database
            columns = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'meta_provider_normalization_run'"
                ).fetchall()
            }
            assert {
                "normalization_surface",
                "mapper_code_hash",
                "quarantine_set_hash",
                "evidence_conflict",
                "normalized_output_set_hash",
                "normalized_semantic_hash",
            } <= columns
            # the CR-3.1 replay-seal columns exist on the upgraded database
            canonical_columns = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'meta_canonicalization_run'"
                ).fetchall()
            }
            assert {
                "requested_domains_json",
                "requested_domains_hash",
                "selected_semantic_hash",
                "decision_set_hash",
                "base_identity_hash",
                "verification_state_hash",
                "input_seal_hash",
                "identity_master_input_set_hash",
            } <= canonical_columns
            # the CR-2.3 anchor ledger exists on the upgraded database
            anchor_cols = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'meta_raw_evidence_anchor'"
                ).fetchall()
            }
            assert {
                "provider",
                "provider_dataset",
                "request_id",
                "evidence_uri",
                "evidence_hash",
                "endpoint",
                "operation_id",
                "normalization_surface",
                "payload_kind",
                "ingest_run_id",
                "created_at",
            } <= anchor_cols
        finally:
            conn.close()

    def test_non_sql_files_still_ignored(self, tmp_path: Path):
        """README.md etc. must NOT trigger the naming gate."""
        migrations_dir = self._copy_migrations(tmp_path)
        (migrations_dir / "README.md").write_text("notes")
        files = discover_migrations(migrations_dir)
        assert all(f.suffix == ".sql" for f in files)
