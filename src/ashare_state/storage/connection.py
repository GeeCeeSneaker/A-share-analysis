"""DuckDB connection management: process-level exclusive DB ownership.

Design ruling P0-1 (2026-08-21): Phase 0 adopts *file-level process
ownership* for atlas.duckdb:

    At any moment the database is owned by exactly ONE process (either in
    read_write or read_only mode). Cross-process read+write concurrency is
    NOT promised. A second owner gets a clear, typed error.

Mechanics:
- An external exclusive gate (a lock file next to the database, locked via
  msvcrt on Windows / fcntl on POSIX) serializes ownership ACROSS processes.
- OS file locks are released automatically when the owning process dies, so
  an owner crash never leaves the database permanently locked (ruling test 3/4).
- Within the owning process, multiple owner() contexts may coexist in the
  SAME mode (DuckDB allows multiple same-config connections per process).
  Mixing modes in one process is rejected with a clear error.
- Phase 1 zero-downtime read requirements will be a separate ADR; do not
  engineer them now.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

import duckdb

if TYPE_CHECKING:
    from collections.abc import Iterator

OwnerMode = Literal["read_write", "read_only"]


class DatabaseOwnershipError(RuntimeError):
    """Base error for DB ownership violations."""


class DatabaseOwnedError(DatabaseOwnershipError):
    """Another process currently owns the database."""

    def __init__(self, db_path: Path, owner_info: str) -> None:
        super().__init__(
            f"database {db_path} is owned by another process ({owner_info}); "
            "Phase 0 grants exclusive file-level ownership - retry later or "
            "coordinate the pipeline/query schedule"
        )
        self.owner_info = owner_info


class OwnerModeConflictError(DatabaseOwnershipError):
    """This process holds the DB in a different mode already."""


def _try_lock(fh: TextIO) -> bool:
    """Attempt a non-blocking exclusive byte-range lock; True on success."""
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        return True
    except OSError:
        return False


def _unlock(fh: TextIO) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        with contextlib.suppress(OSError):
            # the lock dies with the file handle anyway; ignore release errors
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


class DuckDBConnectionManager:
    """File-level exclusive ownership gate + DuckDB connection factory."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._lock_path = self._db_path.with_suffix(self._db_path.suffix + ".owner.lock")
        self._gate_lock = threading.RLock()
        self._gate_fh: TextIO | None = None
        self._gate_mode: OwnerMode | None = None
        self._gate_refcount = 0

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ------------------------------------------------------------------ gate

    def _read_owner_info(self) -> str:
        """Best-effort read of the current owner metadata (diagnostics only)."""
        try:
            return self._lock_path.read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            return "unknown"

    def _write_owner_info(self, mode: OwnerMode) -> None:
        assert self._gate_fh is not None
        info = f"pid={os.getpid()} mode={mode} since={datetime.now(UTC).isoformat()}"
        self._gate_fh.seek(0)
        self._gate_fh.truncate()
        self._gate_fh.write(info)
        self._gate_fh.flush()

    def _acquire_gate(self, mode: OwnerMode, *, wait: bool, timeout: float) -> None:
        with self._gate_lock:
            if self._gate_mode is not None:
                if self._gate_mode != mode:
                    msg = (
                        f"this process owns the database in {self._gate_mode} mode; "
                        f"cannot open a {mode} owner in the same process"
                    )
                    raise OwnerModeConflictError(msg)
                self._gate_refcount += 1
                return

            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            deadline = time.monotonic() + max(timeout, 0.0)
            while True:
                # SIM115/PTH123: the lock file handle is held deliberately
                # for the lifetime of ownership - it IS the cross-process
                # gate; builtin open() keeps append-mode semantics explicit.
                fh = open(self._lock_path, "a+", encoding="utf-8")  # noqa: SIM115, PTH123
                if _try_lock(fh):
                    self._gate_fh = fh
                    self._gate_mode = mode
                    self._gate_refcount = 1
                    self._write_owner_info(mode)
                    return
                fh.close()
                if not wait or time.monotonic() >= deadline:
                    raise DatabaseOwnedError(self._db_path, self._read_owner_info())
                time.sleep(0.1)

    def _release_gate(self) -> None:
        with self._gate_lock:
            self._gate_refcount -= 1
            if self._gate_refcount > 0:
                return
            fh, self._gate_fh = self._gate_fh, None
            self._gate_mode = None
            if fh is not None:
                _unlock(fh)
                fh.close()
                # keep the lock FILE on disk: deleting it races with other
                # processes opening it; an unlocked file is harmless.

    # -------------------------------------------------------------- owner()

    @contextmanager
    def owner(
        self,
        mode: OwnerMode,
        *,
        wait: bool = False,
        timeout: float = 30.0,
    ) -> Iterator[duckdb.DuckDBPyConnection]:
        """Acquire process-level ownership and yield a DuckDB connection.

        wait=False (default): fail immediately with DatabaseOwnedError when
        another process holds the database (ruling test: second writer fails
        loudly).
        """
        self._acquire_gate(mode, wait=wait, timeout=timeout)
        conn: duckdb.DuckDBPyConnection | None = None
        try:
            if mode == "read_only" and not self._db_path.exists():
                msg = f"database file {self._db_path} does not exist"
                raise DatabaseOwnershipError(msg)
            conn = duckdb.connect(str(self._db_path), read_only=(mode == "read_only"))
            yield conn
        finally:
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()
            self._release_gate()


def hold_db_cli() -> None:
    """Helper entry for cross-process tests: hold the DB for N seconds.

    Usage: python -m ashare_state.storage.connection <db_path> <mode> <seconds>
    Prints ACQUIRED once ownership is gained (or FAILED), then RELEASED.
    """
    db_path, mode, seconds = sys.argv[1], sys.argv[2], float(sys.argv[3])
    manager = DuckDBConnectionManager(Path(db_path))
    try:
        with manager.owner(mode):  # type: ignore[arg-type]
            print("ACQUIRED", flush=True)
            time.sleep(seconds)
    except DatabaseOwnershipError:
        print("FAILED", flush=True)
        sys.exit(2)
    print("RELEASED", flush=True)
