"""Atomic file commit tests (design ruling section 7: fixed 8-step order).

Audit P0-01 (2026-08-22): committed files are IMMUTABLE - same URI can
never change bytes. The old overwrite test validated the wrong contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ashare_state.storage.atomic_files import (
    HashMismatchError,
    ImmutableFileExistsError,
    VolumeMismatchError,
    file_sha256,
    write_file_atomic,
)


class TestWriteFileAtomic:
    def test_commit_creates_file_and_returns_hash(self, tmp_path: Path):
        final = tmp_path / "out" / "part-0001.parquet"
        h = write_file_atomic(final, b"hello world")
        assert final.read_bytes() == b"hello world"
        assert h == file_sha256(final)
        # no temp residue
        assert list(final.parent.glob(".tmp-*")) == []

    def test_expected_hash_verified(self, tmp_path: Path):
        import hashlib

        final = tmp_path / "f.parquet"
        good = hashlib.sha256(b"data").hexdigest()
        assert write_file_atomic(final, b"data", expected_sha256=good) == good
        # mismatch on a NEW path blocks BEFORE commit (P0-01 ordering)
        other = tmp_path / "g.parquet"
        with pytest.raises(HashMismatchError, match="mismatch"):
            write_file_atomic(other, b"data", expected_sha256="0" * 64)
        assert not other.exists()

    def test_staging_dir_on_same_volume_allowed(self, tmp_path: Path):
        staging = tmp_path / "staging"
        final = tmp_path / "final" / "f.parquet"
        write_file_atomic(final, b"x", staging_dir=staging)
        assert final.read_bytes() == b"x"

    def test_published_file_cannot_be_overwritten(self, tmp_path: Path):
        """Audit P0-01: a committed URI never changes bytes."""
        final = tmp_path / "part-snap0001-0001.parquet"
        write_file_atomic(final, b"v1")
        with pytest.raises(ImmutableFileExistsError, match="immutable"):
            write_file_atomic(final, b"v2")
        assert final.read_bytes() == b"v1"  # old bytes intact

    def test_existing_identical_is_idempotent_noop(self, tmp_path: Path):
        final = tmp_path / "f.parquet"
        h1 = write_file_atomic(final, b"same")
        h2 = write_file_atomic(final, b"same", allow_existing_identical=True)
        assert h1 == h2
        assert final.read_bytes() == b"same"

    def test_existing_file_different_hash_blocks_even_identical_mode(self, tmp_path: Path):
        final = tmp_path / "f.parquet"
        write_file_atomic(final, b"original")
        with pytest.raises(ImmutableFileExistsError):
            write_file_atomic(final, b"changed", allow_existing_identical=True)
        assert final.read_bytes() == b"original"

    def test_cross_volume_rejected(self, tmp_path: Path, monkeypatch):
        """Staging on a different drive must be rejected loudly on Windows."""
        final = tmp_path / "f.parquet"

        from ashare_state.storage import atomic_files

        def fake_same_volume(a, b):  # noqa: ARG001
            return False

        monkeypatch.setattr(atomic_files, "_same_volume", fake_same_volume)
        with pytest.raises(VolumeMismatchError):
            write_file_atomic(final, b"x", staging_dir=tmp_path / "staging")
