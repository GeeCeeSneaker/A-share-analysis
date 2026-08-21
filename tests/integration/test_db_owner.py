"""DB Owner process-level exclusivity tests (design ruling P0-1).

Covers the four mandated tests:
1. two writer processes compete: the second one FAILS explicitly;
2. while a writer holds the DB, we never assert that readers "should work";
   (we assert the documented behaviour: ownership is refused)
3. owner dying abnormally releases the lock (recoverable);
4. a stale lock FILE (no OS lock) never blocks startup permanently.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ashare_state.storage.connection import (
    DatabaseOwnedError,
    DuckDBConnectionManager,
    OwnerModeConflictError,
)

HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from ashare_state.storage.connection import DuckDBConnectionManager
    m = DuckDBConnectionManager(Path(sys.argv[1]))
    try:
        with m.owner(sys.argv[2]):
            print("ACQUIRED", flush=True)
            time.sleep(float(sys.argv[3]))
    except Exception:
        print("FAILED", flush=True)
        sys.exit(2)
    print("RELEASED", flush=True)
    """
)


def _spawn_holder(db_path: Path, mode: str, seconds: float) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(db_path), mode, str(seconds)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "atlas.duckdb"


@pytest.mark.integration
class TestSingleWriterRule:
    def test_initializes_and_creates_file(self, db_path: Path):
        manager = DuckDBConnectionManager(db_path)
        with manager.owner("read_write") as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.execute("INSERT INTO t VALUES (42)")
        assert db_path.exists()

    def test_same_process_same_mode_reentrant(self, db_path: Path):
        manager = DuckDBConnectionManager(db_path)
        with manager.owner("read_write") as outer:
            with manager.owner("read_write") as inner:
                inner.execute("CREATE TABLE t (id INTEGER)")
            outer.execute("INSERT INTO t VALUES (1)")

    def test_mode_conflict_within_process_rejected(self, db_path: Path):
        manager = DuckDBConnectionManager(db_path)
        # SIM117: nested ownership is the point of this test - we must hold
        # the read_write owner and then attempt a conflicting one inside it.
        with manager.owner("read_write"):  # noqa: SIM117
            with pytest.raises(OwnerModeConflictError):
                with manager.owner("read_only"):
                    pass

    def test_read_only_requires_existing_file(self, db_path: Path):
        manager = DuckDBConnectionManager(db_path)
        # SIM117: raises must wrap the owner entry (the failure point).
        with pytest.raises(Exception, match="does not exist"):  # noqa: SIM117
            with manager.owner("read_only"):
                pass

    def test_two_writer_processes_second_fails(self, db_path: Path):
        # seed the database first
        manager = DuckDBConnectionManager(db_path)
        with manager.owner("read_write") as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")

        holder = _spawn_holder(db_path, "read_write", 3.0)
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "ACQUIRED"
            # rule test 1: second writer fails explicitly
            with pytest.raises(DatabaseOwnedError), manager.owner("read_write"):
                pass
            # rule test 2: while a WRITER holds it, ownership is refused for
            # readers too - we never promise concurrent read access.
            with pytest.raises(DatabaseOwnedError), manager.owner("read_only"):
                pass
        finally:
            holder.wait(timeout=10)

    def test_ownership_recovers_after_owner_dies(self, db_path: Path):
        """Rule test 3: abnormal owner exit releases the OS lock."""
        manager = DuckDBConnectionManager(db_path)
        with manager.owner("read_write") as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")

        holder = _spawn_holder(db_path, "read_write", 60.0)
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ACQUIRED"
        holder.kill()  # abnormal termination - no cleanup runs
        holder.wait(timeout=10)

        # ownership must be recoverable immediately
        with manager.owner("read_write") as conn:
            assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0

    def test_stale_lock_file_does_not_block(self, db_path: Path):
        """Rule test 4: leftover lock FILE (unlocked) never blocks startup."""
        manager = DuckDBConnectionManager(db_path)
        with manager.owner("read_write") as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
        # simulate a crash that left metadata inside the lock file
        lock_path = db_path.with_suffix(db_path.suffix + ".owner.lock")
        lock_path.write_text("pid=999999 mode=read_write since=2020-01-01", encoding="utf-8")
        with manager.owner("read_write") as conn:
            conn.execute("SELECT 1")

    def test_wait_option_can_wait_for_release(self, db_path: Path):
        manager = DuckDBConnectionManager(db_path)
        with manager.owner("read_write") as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
        holder = _spawn_holder(db_path, "read_write", 1.0)
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "ACQUIRED"
            with manager.owner("read_write", wait=True, timeout=15.0) as conn:
                conn.execute("SELECT 1")
        finally:
            holder.wait(timeout=10)
