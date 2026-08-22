"""Immutable-commit concurrency tests (audit R2-P1-07 + R2-P1-08)."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ashare_state.storage.atomic_files import (
    FileCommitCoordinator,
    ImmutableFileExistsError,
    write_file_atomic,
)


@pytest.mark.integration
class TestConcurrentImmutableCommit:
    def test_concurrent_same_target_cannot_replace(self, tmp_path: Path):
        """Two threads race on the same final path: exactly one commits;
        the loser gets ImmutableFileExistsError (never a silent overwrite)."""
        final = tmp_path / "part-0001.parquet"
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(payload: bytes) -> None:
            barrier.wait()  # maximize the race window
            try:
                write_file_atomic(final, payload)
                with lock:
                    outcomes.append("committed")
            except ImmutableFileExistsError:
                with lock:
                    outcomes.append("blocked")

        threads = [
            threading.Thread(target=worker, args=(b"payload-A",)),
            threading.Thread(target=worker, args=(b"payload-B",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(outcomes) == ["blocked", "committed"]
        # the committed bytes are one of the two payloads, whole and intact
        content = final.read_bytes()
        assert content in (b"payload-A", b"payload-B")

    def test_coordinator_lock_is_reentrant(self):
        with FileCommitCoordinator.lock(), FileCommitCoordinator.lock():
            pass  # nested acquisition must not deadlock

    def test_full_uuid_paths_do_not_collide(self, tmp_path: Path):
        """R2-P1-08: identity tags use the FULL uuid (32 hex), so repeated
        runs produce distinct paths instead of 8-hex collisions."""
        import uuid

        tags = {str(uuid.uuid4()).replace("-", "") for _ in range(200)}
        assert len(tags) == 200  # full hex space, no practical collisions
        # and the mock pipeline uses full tags in physical filenames
        from datetime import date

        from ashare_state.pipeline.mock_e2e import run_mock_e2e

        run_a = run_mock_e2e(
            tmp_path / "a.duckdb", tmp_path / "a", start=date(2026, 8, 3), end=date(2026, 8, 14)
        )
        run_b = run_mock_e2e(
            tmp_path / "b.duckdb", tmp_path / "b", start=date(2026, 8, 3), end=date(2026, 8, 14)
        )
        files_a = {p.name for p in (tmp_path / "a").rglob("*.parquet")}
        files_b = {p.name for p in (tmp_path / "b").rglob("*.parquet")}
        # same logical layout, but snapshot/artifact-tagged names differ
        assert files_a and files_b
        overlap = files_a & files_b
        assert not overlap or all(
            "snap" not in name and "artifact" not in name for name in overlap
        ), f"identity-carrying filenames collided: {overlap}"
        _ = run_a, run_b
