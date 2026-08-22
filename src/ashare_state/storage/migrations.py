"""DuckDB migration runner (design ruling 8, V1.3.2 section 6.45).

Guarantees:

1. Sequential application of numbered SQL files (001_..., 002_...).
2. Idempotent: already-applied migrations are skipped.
3. Tamper-proof: every applied migration records a SHA-256 content hash in
   meta_schema_version; if an applied file's hash changes, startup BLOCKS.
4. Transactional: each migration runs inside one transaction; failure rolls
   the whole migration back (DDL included - DuckDB supports transactional DDL).
5. The ledger table itself (meta_schema_version) is bootstrapped by the runner
   and is therefore not a numbered migration.

Statement splitting: migration files are split on ';' at top level. Line
comments ('--') are stripped before splitting. String literals containing ';'
are NOT supported by design - keep migration SQL simple (DDL only).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS meta_schema_version (
    migration_id   VARCHAR PRIMARY KEY,
    filename       VARCHAR NOT NULL,
    content_hash   VARCHAR NOT NULL,
    applied_at     TIMESTAMPTZ NOT NULL
)
"""

_MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """Base error for migration failures."""


class MigrationTamperedError(MigrationError):
    """An already-applied migration file was modified after application."""


class MigrationNameError(MigrationError):
    """A file in the migrations directory has an invalid name."""


class MigrationNamingError(MigrationError):
    """A *.sql file in the migrations directory violates the naming rule.

    Audit P1-05: non-conforming .sql files must BLOCK startup, never be
    silently ignored (a stray '  9_x.sql' would look like a no-op).
    """


class MigrationLedgerGapError(MigrationError):
    """Applied ledger ids are not a complete prefix of the repo sequence.

    Audit P1-05: detects deleted or renamed already-applied migrations.
    """


class MigrationSequenceGapError(MigrationError):
    """The REPO migration sequence itself has a gap (audit R2-P1-09).

    Repo files must be exactly 001..N consecutive; a gap like 001,003,004
    means a migration was never committed and blocks startup.
    """


@dataclass(frozen=True)
class MigrationRecord:
    migration_id: str
    filename: str
    content_hash: str


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_statements(sql_text: str) -> list[str]:
    """Split a migration file into individual statements.

    Strips '--' line comments, then splits on ';'. Empty statements are
    dropped. Block comments are not supported (not used in our DDL).
    """
    lines = []
    for line in sql_text.splitlines():
        # only strip comments that start the effective line (after whitespace)
        stripped = line.lstrip()
        if stripped.startswith("--"):
            continue
        # trailing inline comments are tolerated only when preceded by whitespace
        idx = line.find(" -- ")
        lines.append(line if idx == -1 else line[:idx])
    text = "\n".join(lines)
    return [s.strip() for s in text.split(";") if s.strip()]


def discover_migrations(migrations_dir: Path) -> list[Path]:
    """Return numbered migration files sorted by migration id.

    Audit P1-05: any .sql file violating the naming rule BLOCKs (instead of
    being silently ignored). Non-.sql files (README etc.) remain ignored.
    """
    if not migrations_dir.is_dir():
        msg = f"migrations directory not found: {migrations_dir}"
        raise MigrationError(msg)
    found: list[tuple[str, Path]] = []
    for path in migrations_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() != ".sql":
            continue  # README etc. are not migrations
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            msg = (
                f"migration file {path.name} violates the NNN_name.sql naming "
                "rule; startup BLOCKED (audit P1-05: never silently ignore)"
            )
            raise MigrationNamingError(msg)
        found.append((match.group(1), path))
    found.sort(key=lambda pair: pair[0])
    # duplicate ids are impossible with the 3-digit naming scheme, but assert anyway
    ids = [mid for mid, _ in found]
    if len(ids) != len(set(ids)):
        msg = "duplicate migration ids"
        raise MigrationNameError(msg)
    # audit R2-P1-09: repo ids must be exactly 001..N consecutive
    for expected, actual in enumerate(ids, start=1):
        if int(actual) != expected:
            msg = (
                f"migration sequence gap: expected {expected:03d} but found "
                f"{actual}; repository migrations must be consecutive 001..N"
            )
            raise MigrationSequenceGapError(msg)
    return [path for _, path in found]


def applied_migrations(conn: DuckDBPyConnection) -> dict[str, MigrationRecord]:
    """Read the ledger (bootstrapping it if necessary)."""
    conn.execute(_LEDGER_DDL)
    rows = conn.execute(
        "SELECT migration_id, filename, content_hash FROM meta_schema_version"
    ).fetchall()
    return {row[0]: MigrationRecord(str(row[0]), str(row[1]), str(row[2])) for row in rows}


def apply_migrations(
    conn: DuckDBPyConnection,
    migrations_dir: Path,
) -> list[MigrationRecord]:
    """Apply all pending migrations; verify checksums of applied ones.

    Returns the ledger state after the run. Raises MigrationTamperedError when
    an applied file's current hash differs from the recorded hash.
    """
    ledger = applied_migrations(conn)
    files = discover_migrations(migrations_dir)

    # P1-05: the applied ledger must be a COMPLETE PREFIX of the repo
    # sequence - detects deletions and renames of already-applied files.
    repo_ids = []
    for path in files:
        match = _MIGRATION_NAME.match(path.name)
        assert match is not None
        repo_ids.append(match.group(1))
    applied_ids = sorted(ledger.keys())
    prefix_len = len(applied_ids)
    if repo_ids[:prefix_len] != applied_ids:
        missing = [mid for mid in applied_ids if mid not in repo_ids]
        renamed = [
            (mid, ledger[mid].filename)
            for mid in applied_ids
            if mid in repo_ids
            and any(
                _MIGRATION_NAME.match(p.name)
                and _MIGRATION_NAME.match(p.name).group(1) == mid  # type: ignore[union-attr]
                and p.name != ledger[mid].filename
                for p in files
            )
        ]
        msg = (
            f"applied migration ledger is not a complete prefix of the repo "
            f"sequence (ledger={applied_ids}, repo={repo_ids}); "
            f"missing/deleted={missing}, renamed={renamed}; startup BLOCKED "
            "(audit P1-05)"
        )
        raise MigrationLedgerGapError(msg)

    # verify integrity of already-applied migrations first: BLOCK before any change
    for path in files:
        match = _MIGRATION_NAME.match(path.name)
        assert match is not None
        migration_id = match.group(1)
        current_hash = _file_sha256(path)
        record = ledger.get(migration_id)
        if record is not None:
            if record.content_hash != current_hash:
                msg = (
                    f"migration {path.name} was modified after being applied "
                    f"(recorded hash {record.content_hash}, current hash {current_hash}); "
                    "startup BLOCKED - restore the original file or add a new migration"
                )
                raise MigrationTamperedError(msg)
            if record.filename != path.name:
                msg = (
                    f"migration {migration_id} was renamed after being applied "
                    f"(ledger filename {record.filename}, repo filename {path.name}); "
                    "startup BLOCKED - restore the original filename"
                )
                raise MigrationLedgerGapError(msg)

    newly_applied: list[MigrationRecord] = []
    for path in files:
        match = _MIGRATION_NAME.match(path.name)
        assert match is not None
        migration_id = match.group(1)
        if migration_id in ledger:
            continue
        current_hash = _file_sha256(path)
        statements = split_statements(path.read_text(encoding="utf-8"))
        conn.execute("BEGIN TRANSACTION")
        try:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO meta_schema_version VALUES (?, ?, ?, now())",
                [migration_id, path.name, current_hash],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            msg = f"migration {path.name} failed and was rolled back"
            raise MigrationError(msg) from None
        record = MigrationRecord(migration_id, path.name, current_hash)
        newly_applied.append(record)
        ledger[migration_id] = record

    return newly_applied
