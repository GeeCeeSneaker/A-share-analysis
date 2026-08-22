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
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

_READ_CHUNK = 1024 * 1024

# Audit R2-P1-07: immutable commits are serialized PROCESS-WIDE so the
# exists->write->replace window (TOCTOU) cannot interleave between threads.
# Cross-process safety comes from the DuckDB single-owner model: all
# immutable commits happen inside the DB owner process.
_COMMIT_COORDINATOR_LOCK = threading.RLock()


class FileCommitCoordinator:
    """Process-wide serializer for immutable file commits (R2-P1-07).

    Rule: every write_file_atomic() call runs under this coordinator, so
    the exists->write->replace window cannot interleave between threads.
    Cross-process concurrency remains governed by the DuckDB single-owner
    model (immutable commits happen inside the owner process).
    """

    @staticmethod
    @contextmanager
    def lock() -> Iterator[None]:
        with _COMMIT_COORDINATOR_LOCK:
            yield


class AtomicCommitError(RuntimeError):
    """Base error for atomic commit failures."""


class VolumeMismatchError(AtomicCommitError):
    """temp and final paths live on different volumes; os.replace not atomic."""


class HashMismatchError(AtomicCommitError):
    """Content hash verification failed before commit."""


class ImmutableFileExistsError(AtomicCommitError):
    """final_path already exists: committed files must never change bytes.

    Audit P0-01 (2026-08-22): once a file_uri is referenced by a snapshot
    or artifact manifest its bytes are frozen; a rewrite requires a NEW
    identity-carrying filename, never a replace.
    """


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
    allow_existing_identical: bool = False,
) -> str:
    """Write bytes to final_path atomically following the ruled 8-step order.

    Immutable contract (audit P0-01): if final_path already exists the write
    BLOCKS with ImmutableFileExistsError. With allow_existing_identical=True,
    an existing file whose SHA-256 equals the incoming content is an
    idempotent no-op returning that hash; different content always BLOCKs.

    R2-P1-07: the whole exists->write->replace sequence runs under the
    FileCommitCoordinator lock, so concurrent threads cannot interleave.

    1-4: write temp file in staging_dir (default: final_path.parent), flush,
         fsync, close.
    5:   verify SHA-256 (against expected when provided).
    6:   os.replace(temp, final) - requires same volume, enforced.
    Returns the content hash. Steps 7-8 (component registration and publish
    pointer switch) belong to the caller's DuckDB transaction.
    """
    with FileCommitCoordinator.lock():
        return _write_file_atomic_locked(
            final_path,
            data,
            staging_dir=staging_dir,
            expected_sha256=expected_sha256,
            allow_existing_identical=allow_existing_identical,
        )


def _write_file_atomic_locked(
    final_path: Path,
    data: bytes,
    *,
    staging_dir: Path | None,
    expected_sha256: str | None,
    allow_existing_identical: bool,
) -> str:
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # P0-01: fail fast BEFORE writing any temp file.
    incoming_hash = hashlib.sha256(data).hexdigest()
    if final_path.exists():
        if allow_existing_identical and file_sha256(final_path) == incoming_hash:
            if expected_sha256 is not None and incoming_hash != expected_sha256:
                msg = (
                    f"content hash mismatch for {final_path.name}: "
                    f"expected {expected_sha256}, computed {incoming_hash}"
                )
                raise HashMismatchError(msg)
            # idempotent retry: identical bytes already committed under this
            # URI - keep them untouched and report the existing hash.
            return incoming_hash
        msg = (
            f"immutable file {final_path} already exists; committed files must "
            "never change bytes - write to a new identity-carrying filename, or "
            "pass allow_existing_identical=True for same-hash idempotent retries"
        )
        raise ImmutableFileExistsError(msg)

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
