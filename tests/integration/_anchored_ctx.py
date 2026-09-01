"""Shared CR-2.4 test helper: an in-memory migrated DB connection for
``ProbeContext`` construction.

CR-2.4 (audit 20260901 section 3): the provider-evidence write path is
the ANCHORED boundary - ``ProbeContext`` REQUIRES a DuckDB connection
carrying ``meta_raw_evidence_anchor`` (migration 017). Every test that
builds a ProbeContext uses this helper so its evidence writes enroll
anchors exactly like production.

Tests-only module (top-level same-directory import, CI-safe).
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def anchored_conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the full migration chain applied."""
    from ashare_state.storage import apply_migrations

    conn = duckdb.connect(":memory:")
    apply_migrations(conn, Path(__file__).resolve().parents[2] / "migrations")
    return conn
