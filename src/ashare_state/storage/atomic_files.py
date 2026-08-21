"""Atomic file commit and manifest identity hashing.

Two design rulings live here:

P0-5  Manifest identity hash is computed ONLY from logical fields
      (dataset, logical_partition_key, content_hash, schema_hash, row_count,
      provider, source_revision). Machine absolute paths, staging paths,
      random run_ids, created_at/ingested_at never enter the hash.
      file_uri is a locator, not an identity input.

Section 7 (Windows atomic commit, fixed order):
      1. write temp -> 2. flush -> 3. fsync(temp) -> 4. close ->
      5. SHA-256 verify -> 6. os.replace(temp, final) [same volume] ->
      7. register component -> 8. switch publish pointer in one DuckDB txn.

We do NOT claim directory-level durability on Windows. Recovery guarantees
come from immutable files + content hash + pointer-switches-last + startup
recovery checks, not from filesystem semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_READ_CHUNK = 1024 * 1024


class AtomicCommitError(RuntimeError):
    """Base error for atomic commit failures."""


class VolumeMismatchError(AtomicCommitError):
    """temp and final paths live on different volumes; os.replace not atomic."""


class HashMismatchError(AtomicCommitError):
    """Content hash verification failed before commit."""


def file_sha256(path: Path) -> str:
    """Stream a file and return its hex SHA-256."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def schema_hash_of(schema_text: str) -> str:
    """Hash a canonical schema description (e.g. sorted 'name type' lines)."""
    return hashlib.sha256(schema_text.encode("utf-8")).hexdigest()


def _same_volume(a: Path, b: Path) -> bool:
    """True when both paths resolve to the same drive/root."""
    a_drive = os.path.splitdrive(str(Path(a).resolve()))[0]
    b_drive = os.path.splitdrive(str(Path(b).resolve()))[0]
    return a_drive == b_drive


def write_file_atomic(
    final_path: Path,
    data: bytes,
    *,
    staging_dir: Path | None = None,
    expected_sha256: str | None = None,
) -> str:
    """Write bytes to final_path atomically following the ruled 8-step order.

    1-4: write temp file in staging_dir (default: final_path.parent), flush,
         fsync, close.
    5:   verify SHA-256 (against expected when provided).
    6:   os.replace(temp, final) - requires same volume, enforced.
    Returns the content hash. Steps 7-8 (component registration and publish
    pointer switch) belong to the caller's DuckDB transaction.
    """
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if staging_dir is None:
        staging_dir = final_path.parent
    else:
        staging_dir = Path(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        if not _same_volume(staging_dir, final_path.parent):
            msg = (
                f"staging dir {staging_dir} and final dir {final_path.parent} are on "
                "different volumes; os.replace would not be atomic"
            )
            raise VolumeMismatchError(msg)

    temp_path = staging_dir / f".tmp-{final_path.name}"
    digest = hashlib.sha256()
    with temp_path.open("wb") as fh:
        fh.write(data)
        digest.update(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        content_hash = digest.hexdigest()
        if expected_sha256 is not None and content_hash != expected_sha256:
            msg = (
                f"content hash mismatch for {final_path.name}: "
                f"expected {expected_sha256}, computed {content_hash}"
            )
            raise HashMismatchError(msg)
        # PTH105: os.replace is deliberate - Path.replace shadows the exact
        # cross-platform atomic-rename semantics we depend on (ruling step 6).
        os.replace(temp_path, final_path)  # noqa: PTH105
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return content_hash


@dataclass(frozen=True)
class ComponentIdentity:
    """Logical identity of one immutable file component.

    Deliberately excludes: file_uri, machine paths, run ids, timestamps.
    """

    dataset: str
    logical_partition_key: str
    content_hash: str
    schema_hash: str
    row_count: int
    provider: str | None = None
    source_revision: str | None = None

    def identity_tuple(self) -> tuple[str, str, str, str, int, str, str]:
        return (
            self.dataset,
            self.logical_partition_key,
            self.content_hash,
            self.schema_hash,
            self.row_count,
            self.provider or "",
            self.source_revision or "",
        )


def compute_manifest_hash(components: Sequence[ComponentIdentity]) -> str:
    """Deterministic manifest identity hash.

    Components are sorted by their logical identity tuple, then serialized as
    a canonical JSON array. The result is stable across directories, machines,
    operating systems and run ids (design ruling P0-5).
    """
    payload = [asdict(c) for c in sorted(components, key=lambda c: c.identity_tuple())]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
