"""CR-4.3 DuckDB ReadModel integration tests (work requirement audit
20260902 section 6, CR-4.4 verified-open closure).

Reuses the CR-4.2 test harness (seeding helpers + snapshot build) from
``test_snapshot``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest
from test_snapshot import (
    ALL_DOMAINS,
    AS_OF_LATE,
    _canonical,
    _canonical_success,
    _seed_bars,
    _snapshot_manifest,
)

from ashare_state.canonical.canonicalizer import _rows_semantic_hash
from ashare_state.readmodel import (
    READMODEL_CONTRACT_VERSION,
    DuckDBReadModel,
    ReadModelError,
    readmodel_builder_code_fingerprint,
    readmodel_db_uri,
)
from ashare_state.readmodel.duckdb_model import _normalize_seal_row
from ashare_state.readmodel.schema import duckdb_domain_columns, duckdb_domain_table_name
from ashare_state.snapshot import SnapshotBuilder, SnapshotVerifierError


def _builder(conn, env_root):
    return SnapshotBuilder(conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"])


def _model(conn, env_root):
    return DuckDBReadModel(conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"])


def _built_snapshot(conn, env_root, domains=("daily_bar",)):
    result = _canonical_success(conn, env_root, domains=domains)
    return _builder(conn, env_root).build(result.canonical_run_id)


@pytest.mark.integration
class TestDuckDBReadModel:
    """Mandatory tests 31-42."""

    def test_rebuild_success(self, conn, env_root):
        """Mandatory 31: a verified snapshot rebuilds into a complete
        DuckDB read model with the declared table set + one snapshot
        meta row."""
        built = _built_snapshot(conn, env_root)
        rebuilt = _model(conn, env_root).rebuild(built.snapshot_id)
        assert rebuilt.snapshot_id == built.snapshot_id
        assert rebuilt.readmodel_contract_version == READMODEL_CONTRACT_VERSION
        db_path = env_root["normalized"] / readmodel_db_uri(built.snapshot_id)
        assert db_path.is_file()
        db = _model(conn, env_root).open_read_only(built.snapshot_id)
        try:
            tables = {
                r[0]
                for r in db.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            }
            assert tables == {"rm_daily_bar", "rm_domain_meta", "rm_snapshot_meta"}
            count = db.execute("SELECT COUNT(*) FROM rm_daily_bar").fetchone()[0]
            assert int(count) == 2
            meta = db.execute("SELECT COUNT(*) FROM rm_snapshot_meta").fetchone()[0]
            assert int(meta) == 1
        finally:
            db.close()

    def test_logical_seal_row_counts_and_semantics(self, conn, env_root):
        """Mandatory 32 + 33: the built tables carry EXACTLY the
        snapshot row counts and the logical semantic hashes recomputed
        from the table contents equal the snapshot domain seals."""
        built = _built_snapshot(conn, env_root, domains=ALL_DOMAINS)
        rebuilt = _model(conn, env_root).rebuild(built.snapshot_id)
        assert rebuilt.row_count_total == 7
        manifest = _snapshot_manifest(env_root, built)
        db = _model(conn, env_root).open_read_only(built.snapshot_id)
        try:
            for domain in ALL_DOMAINS:
                table = duckdb_domain_table_name(domain)
                entry = manifest["artifacts"][domain]
                count = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                assert count == int(entry["row_count"])
                rows = db.execute(f"SELECT * FROM {table}").fetchall()
                col_names = list(duckdb_domain_columns(domain))
                dicts = [_normalize_seal_row(dict(zip(col_names, r, strict=True))) for r in rows]
                assert _rows_semantic_hash(dicts) == str(entry["semantic_hash"])
        finally:
            db.close()

    def test_no_stale_table_between_snapshots(self, conn, env_root):
        """Mandatory 34: rebuilding snapshot B (only daily_bar) must
        not leave snapshot A's trade_calendar table in B's database."""
        first_run = _canonical_success(conn, env_root, domains=("daily_bar", "trade_calendar"))
        first = _builder(conn, env_root).build(first_run.canonical_run_id)
        _model(conn, env_root).rebuild(first.snapshot_id)
        # a new canonical world with ONLY daily_bar
        second_run = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second_run.status == "SUCCESS"
        assert second_run.canonical_run_id != first_run.canonical_run_id
        second = _builder(conn, env_root).build(second_run.canonical_run_id)
        assert second.snapshot_id != first.snapshot_id
        _model(conn, env_root).rebuild(second.snapshot_id)
        db = _model(conn, env_root).open_read_only(second.snapshot_id)
        try:
            tables = {
                r[0]
                for r in db.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            }
            assert "rm_trade_calendar" not in tables
            assert tables == {"rm_daily_bar", "rm_domain_meta", "rm_snapshot_meta"}
        finally:
            db.close()

    def test_schema_exactness_with_explicit_timezone(self, conn, env_root):
        """Mandatory 35/36: the physical column types equal the
        declared readmodel schema; time columns are TIMESTAMP WITH
        TIME ZONE and the UTC instants round-trip exactly."""
        built = _built_snapshot(conn, env_root)
        _model(conn, env_root).rebuild(built.snapshot_id)
        manifest = _snapshot_manifest(env_root, built)
        db = _model(conn, env_root).open_read_only(built.snapshot_id)
        try:
            declared = duckdb_domain_columns("daily_bar")
            actual = {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'main' AND table_name = 'rm_daily_bar' "
                    "ORDER BY ordinal_position"
                ).fetchall()
            }
            assert actual == declared
            assert actual["available_at"] == "TIMESTAMP WITH TIME ZONE"
            assert actual["ingested_at"] == "TIMESTAMP WITH TIME ZONE"
            assert actual["trade_date"] == "DATE"
            # exact UTC instant round-trip against the snapshot parquet
            import polars as pl

            snap_rows = pl.read_parquet(
                env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])
            ).to_dicts()
            db_rows = db.execute("SELECT * FROM rm_daily_bar").fetchall()
            col_names = list(duckdb_domain_columns("daily_bar"))
            db_dicts = [dict(zip(col_names, r, strict=True)) for r in db_rows]
            by_key = {r["canonical_key"]: r for r in db_dicts}
            for snap in snap_rows:
                dbrow = by_key[snap["canonical_key"]]
                assert dbrow["available_at"] == snap["available_at"]
                assert dbrow["ingested_at"] == snap["ingested_at"]
                assert dbrow["trade_date"] == snap["trade_date"]
                assert dbrow["open"] == snap["open"]
        finally:
            db.close()

    def test_key_uniqueness(self, conn, env_root):
        """Mandatory 37: canonical_key is unique in every rm_ table."""
        built = _built_snapshot(conn, env_root, domains=ALL_DOMAINS)
        _model(conn, env_root).rebuild(built.snapshot_id)
        db = _model(conn, env_root).open_read_only(built.snapshot_id)
        try:
            for domain in ALL_DOMAINS:
                table = duckdb_domain_table_name(domain)
                count = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                distinct = int(
                    db.execute(f"SELECT COUNT(DISTINCT canonical_key) FROM {table}").fetchone()[0]
                )
                assert distinct == count
        finally:
            db.close()

    def test_meta_tables_content(self, conn, env_root):
        """Mandatory 38: rm_snapshot_meta / rm_domain_meta carry the
        verified snapshot provenance exactly."""
        built = _built_snapshot(conn, env_root, domains=("daily_bar",))
        _model(conn, env_root).rebuild(built.snapshot_id)
        manifest = _snapshot_manifest(env_root, built)
        db = _model(conn, env_root).open_read_only(built.snapshot_id)
        try:
            meta = db.execute(
                "SELECT snapshot_id, snapshot_contract_version, canonical_run_id, "
                "canonical_as_of, requested_domains, readmodel_contract_version, "
                "snapshot_builder_code_fingerprint, readmodel_builder_code_fingerprint "
                "FROM rm_snapshot_meta"
            ).fetchone()
            assert meta[0] == built.snapshot_id
            assert str(meta[1]) == str(manifest["snapshot_contract_version"])
            assert str(meta[2]) == built.canonical_run_id
            assert meta[3].astimezone(UTC) == AS_OF_LATE
            import json

            assert list(json.loads(str(meta[4]))) == ["daily_bar"]
            assert str(meta[5]) == READMODEL_CONTRACT_VERSION
            assert str(meta[6]) == str(manifest["snapshot_builder_code_fingerprint"])
            assert str(meta[7]) == readmodel_builder_code_fingerprint()
            dmeta = db.execute(
                "SELECT domain, artifact_uri, row_count, semantic_hash FROM rm_domain_meta"
            ).fetchone()
            entry = manifest["artifacts"]["daily_bar"]
            assert str(dmeta[0]) == "daily_bar"
            assert str(dmeta[1]) == str(entry["uri"])
            assert int(dmeta[2]) == int(entry["row_count"])
            assert str(dmeta[3]) == str(entry["semantic_hash"])
        finally:
            db.close()

    def test_rebuild_unknown_snapshot_fails_clean(self, conn, env_root):
        """Mandatory 39: rebuilding an unknown snapshot id fails and
        leaves no temp residue."""
        _canonical_success(conn, env_root, domains=("daily_bar",))
        model = _model(conn, env_root)
        import uuid

        with pytest.raises(SnapshotVerifierError, match="does not exist"):
            model.rebuild(str(uuid.uuid4()))
        leftovers = list((env_root["normalized"] / "readmodel").rglob(".readmodel.building.duckdb"))
        assert leftovers == []

    def test_exact_second_rebuild_idempotent(self, conn, env_root):
        """Mandatory 40: an exact second rebuild of the same snapshot
        succeeds and yields the same logical truth (the target is
        atomically replaced, never corrupted)."""
        built = _built_snapshot(conn, env_root)
        model = _model(conn, env_root)
        first = model.rebuild(built.snapshot_id)
        second = model.rebuild(built.snapshot_id)
        assert second.snapshot_id == first.snapshot_id
        assert second.table_set == first.table_set
        db = model.open_read_only(built.snapshot_id)
        try:
            count = int(db.execute("SELECT COUNT(*) FROM rm_daily_bar").fetchone()[0])
            assert count == 2
            meta = int(db.execute("SELECT COUNT(*) FROM rm_snapshot_meta").fetchone()[0])
            assert meta == 1
        finally:
            db.close()
        leftovers = list((env_root["normalized"] / "readmodel").rglob(".readmodel.building.duckdb"))
        assert leftovers == []

    def test_rebuild_atomic_failure_leaves_target_intact(self, conn, env_root, monkeypatch):
        """Mandatory 41: a failure DURING the rebuild leaves the
        previous target untouched and removes the temp file - no
        partial / corrupt model is ever visible."""
        built = _built_snapshot(conn, env_root)
        model = _model(conn, env_root)
        model.rebuild(built.snapshot_id)
        target = env_root["normalized"] / readmodel_db_uri(built.snapshot_id)
        before = target.read_bytes()

        def _boom(self, db, verified):
            raise AssertionError("injected logical-seal failure")

        monkeypatch.setattr(DuckDBReadModel, "_validate_logical_seal", _boom)
        with pytest.raises(AssertionError, match="injected"):
            model.rebuild(built.snapshot_id)
        monkeypatch.undo()
        # the previous target is byte-intact and no temp residue exists
        assert target.read_bytes() == before
        leftovers = list((env_root["normalized"] / "readmodel").rglob(".readmodel.building.duckdb"))
        assert leftovers == []
        # and the model still opens and answers correctly
        db = model.open_read_only(built.snapshot_id)
        try:
            count = int(db.execute("SELECT COUNT(*) FROM rm_daily_bar").fetchone()[0])
            assert count == 2
        finally:
            db.close()

    def test_open_read_only_unknown_snapshot(self, conn, env_root):
        """Mandatory 42: opening an unbuilt snapshot fails closed."""
        _canonical_success(conn, env_root, domains=("daily_bar",))
        import uuid

        with pytest.raises(ReadModelError, match="has not been built"):
            _model(conn, env_root).open_read_only(str(uuid.uuid4()))

    def test_verified_open_rejects_canonical_as_of_drift(self, conn, env_root):
        """A foreign canonical_as_of in an otherwise readable DB is refused."""
        built = _built_snapshot(conn, env_root)
        model = _model(conn, env_root)
        model.rebuild(built.snapshot_id)
        target = env_root["normalized"] / readmodel_db_uri(built.snapshot_id)
        db = duckdb.connect(str(target))
        try:
            db.execute(
                "UPDATE rm_snapshot_meta SET canonical_as_of = TIMESTAMPTZ '2020-01-01 00:00:00+00'"
            )
        finally:
            db.close()
        with pytest.raises(ReadModelError, match="canonical_as_of"):
            model.open_read_only(built.snapshot_id)

    def test_verified_open_rejects_foreign_domain_meta(self, conn, env_root):
        """Every domain metadata row must bind to this snapshot id."""
        built = _built_snapshot(conn, env_root)
        model = _model(conn, env_root)
        model.rebuild(built.snapshot_id)
        target = env_root["normalized"] / readmodel_db_uri(built.snapshot_id)
        db = duckdb.connect(str(target))
        try:
            db.execute("UPDATE rm_domain_meta SET snapshot_id = 'foreign-snapshot'")
        finally:
            db.close()
        with pytest.raises(ReadModelError, match="foreign snapshot_id"):
            model.open_read_only(built.snapshot_id)

    def test_verified_open_rejects_logical_row_tamper(self, conn, env_root):
        """A changed table value is rejected before a read-only handle escapes."""
        built = _built_snapshot(conn, env_root)
        model = _model(conn, env_root)
        model.rebuild(built.snapshot_id)
        target = env_root["normalized"] / readmodel_db_uri(built.snapshot_id)
        db = duckdb.connect(str(target))
        try:
            db.execute("UPDATE rm_daily_bar SET close = 999.0")
        finally:
            db.close()
        with pytest.raises(ReadModelError, match="logical semantic hash"):
            model.open_read_only(built.snapshot_id)

    def test_verified_open_rejects_foreign_snapshot_file(self, conn, env_root):
        """A database copied from another snapshot cannot be opened under A."""
        first_run = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _builder(conn, env_root).build(first_run.canonical_run_id)
        _seed_bars(
            conn,
            env_root,
            "req-new-bars",
            received_at=datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC),
        )
        second_run = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second_run.status == "SUCCESS"
        second = _builder(conn, env_root).build(second_run.canonical_run_id)
        model = _model(conn, env_root)
        model.rebuild(first.snapshot_id)
        model.rebuild(second.snapshot_id)
        target_a = env_root["normalized"] / readmodel_db_uri(first.snapshot_id)
        target_b = env_root["normalized"] / readmodel_db_uri(second.snapshot_id)
        target_a.write_bytes(target_b.read_bytes())
        with pytest.raises(ReadModelError, match="snapshot_id|semantic"):
            model.open_read_only(first.snapshot_id)

    def test_verify_readmodel_green(self, conn, env_root):
        built = _built_snapshot(conn, env_root)
        model = _model(conn, env_root)
        model.rebuild(built.snapshot_id)
        assert model.verify_readmodel(built.snapshot_id).snapshot_id == built.snapshot_id

    def test_superset_snapshot_both_models_coexist(self, conn, env_root):
        """Additional: two snapshots' read models coexist
        side-by-side (deterministic per-snapshot paths). The second
        canonical world adds an EQUIVALENT duplicate input run (same
        keys, same values) - selected stays 2 rows (deterministic
        winner per key), but the input seal differs -> a distinct
        snapshot with its own model."""
        first_run = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _builder(conn, env_root).build(first_run.canonical_run_id)
        _seed_bars(
            conn, env_root, "req-new-bars", received_at=datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
        )
        second_run = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second_run.status == "SUCCESS"
        assert second_run.canonical_run_id != first_run.canonical_run_id
        second = _builder(conn, env_root).build(second_run.canonical_run_id)
        assert second.snapshot_id != first.snapshot_id
        model = _model(conn, env_root)
        model.rebuild(first.snapshot_id)
        model.rebuild(second.snapshot_id)
        db1 = model.open_read_only(first.snapshot_id)
        db2 = model.open_read_only(second.snapshot_id)
        try:
            assert int(db1.execute("SELECT COUNT(*) FROM rm_daily_bar").fetchone()[0]) == 2
            assert int(db2.execute("SELECT COUNT(*) FROM rm_daily_bar").fetchone()[0]) == 2
            id1 = db1.execute("SELECT source_raw_request_id FROM rm_daily_bar LIMIT 1").fetchone()
            id2 = db2.execute("SELECT source_raw_request_id FROM rm_daily_bar LIMIT 1").fetchone()
            # world 1 has exactly one candidate run -> its winner is
            # necessarily req-bars. World 2 has two EQUIVALENT runs; the
            # deterministic winner is chosen by (priority, run_manifest_hash,
            # ordinal) and the two raw-evidence hashes are wall-clock
            # dependent, so the winner may legitimately differ between
            # independently ingested environments - assert it is one of the
            # two and stable WITHIN the world (rebuild idempotency).
            assert str(id1[0]) == "req-bars"
            assert str(id2[0]) in {"req-bars", "req-new-bars"}
        finally:
            db1.close()
            db2.close()
