"""Immutability + exact-replay contract tests (audit P0-01, section 27).

Two runs with different identities must PHYSICALLY COEXIST: same logical
partition, different identity-carrying filenames, and an old publish's
content hashes must still match the bytes on disk after a newer run.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from ashare_state.pipeline import artifact_files_for_publish
from ashare_state.pipeline.mock_e2e import run_mock_e2e
from ashare_state.storage.connection import DuckDBConnectionManager


@pytest.mark.integration
class TestImmutabilityCoexist:
    def test_two_snapshots_same_partition_coexist(self, tmp_path: Path):
        """Two runs -> same month partition, both file sets alive."""
        run_a = run_mock_e2e(
            tmp_path / "atlas.duckdb",
            tmp_path / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        run_b = run_mock_e2e(
            tmp_path / "atlas.duckdb",
            tmp_path / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        # every registered file from BOTH runs exists on disk
        for rel in run_a.canonical_files + run_b.canonical_files:
            assert (tmp_path / "data" / rel).is_file(), rel
        # different identities -> different filenames (no overwrite path)
        assert set(run_a.canonical_files).isdisjoint(run_b.canonical_files)
        assert set(run_a.feature_files).isdisjoint(run_b.feature_files)
        # distinct snapshot ids
        assert run_a.data_snapshot_id != run_b.data_snapshot_id
        assert run_a.feature_artifact_set_id != run_b.feature_artifact_set_id

    def test_old_publish_hash_still_matches_after_new_run(self, tmp_path: Path):
        """Exact replay: after a second run, the FIRST publish's registered
        content hashes still match the physical bytes."""
        run_a = run_mock_e2e(
            tmp_path / "atlas.duckdb",
            tmp_path / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        run_b = run_mock_e2e(
            tmp_path / "atlas.duckdb",
            tmp_path / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
            republish=True,
        )
        _ = run_b  # second run exists to disturb the filesystem; unused otherwise
        manager = DuckDBConnectionManager(tmp_path / "atlas.duckdb")
        with manager.owner("read_only") as conn:
            old_files = artifact_files_for_publish(conn, run_a.publish_ids[0])
        assert old_files, "old publish must resolve its artifact files"
        for f in old_files:
            digest = hashlib.sha256((tmp_path / "data" / f["file_uri"]).read_bytes()).hexdigest()
            assert digest == f["content_hash"], f["file_uri"]

    def test_registered_files_are_not_orphans(self, tmp_path: Path):
        """Audit P1-01: registered files must never be flagged as orphans."""
        from ashare_state.pipeline import find_orphan_files

        run = run_mock_e2e(
            tmp_path / "atlas.duckdb",
            tmp_path / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        manager = DuckDBConnectionManager(tmp_path / "atlas.duckdb")
        with manager.owner("read_only") as conn:
            orphans = find_orphan_files(conn, tmp_path / "data")
        # data_root scan finds ALL registered files -> zero orphans here
        assert orphans == []

    def test_true_orphan_detected_via_data_root(self, tmp_path: Path):
        from ashare_state.pipeline import find_orphan_files

        run = run_mock_e2e(
            tmp_path / "atlas.duckdb",
            tmp_path / "data",
            start=date(2026, 8, 3),
            end=date(2026, 8, 14),
        )
        orphan = (
            tmp_path
            / "data"
            / "canonical"
            / "daily_bar"
            / "year=2026"
            / "month=08"
            / "part-zombie-0001.parquet"
        )
        orphan.write_bytes(b"zombie")
        manager = DuckDBConnectionManager(tmp_path / "atlas.duckdb")
        with manager.owner("read_only") as conn:
            orphans = find_orphan_files(conn, tmp_path / "data")
        assert orphan in orphans
        # and no registered file is flagged
        registered = set(run.canonical_files + run.feature_files)
        flagged = {p.relative_to(tmp_path / "data").as_posix() for p in orphans}
        assert flagged.isdisjoint(registered)
