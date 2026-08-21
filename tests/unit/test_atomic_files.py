"""Atomic file commit tests (design ruling section 7: fixed 8-step order)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ashare_state.storage.atomic_files import (
    HashMismatchError,
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
        with pytest.raises(HashMismatchError, match="mismatch"):
            write_file_atomic(final, b"data", expected_sha256="0" * 64)
        # after failure the target keeps its previous content
        assert final.read_bytes() == b"data"

    def test_staging_dir_on_same_volume_allowed(self, tmp_path: Path):
        staging = tmp_path / "staging"
        final = tmp_path / "final" / "f.parquet"
        write_file_atomic(final, b"x", staging_dir=staging)
        assert final.read_bytes() == b"x"

    def test_overwrite_is_atomic_replace(self, tmp_path: Path):
        final = tmp_path / "f.parquet"
        write_file_atomic(final, b"v1")
        write_file_atomic(final, b"v2")
        assert final.read_bytes() == b"v2"
        assert not (tmp_path / ".tmp-f.parquet").exists()

    def test_cross_volume_rejected(self, tmp_path: Path, monkeypatch):
        """Staging on a different drive must be rejected loudly on Windows."""
        final = tmp_path / "f.parquet"

        from ashare_state.storage import atomic_files

        def fake_same_volume(a, b):  # noqa: ARG001
            return False

        monkeypatch.setattr(atomic_files, "_same_volume", fake_same_volume)
        with pytest.raises(VolumeMismatchError):
            write_file_atomic(final, b"x", staging_dir=tmp_path / "staging")
