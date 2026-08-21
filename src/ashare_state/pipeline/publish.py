"""Publish transaction service and published readers.

Implements the frozen publish contract (V1.3.2 sections 2.10/6.44, design
ruling on atomic republish):

- One DuckDB transaction performs: old PUBLISHED -> SUPERSEDED, insert new
  PUBLISHED, write meta_publish_universe, set meta_pipeline_run=PUBLISHED.
- Any failure rolls the whole transaction back: the previous PUBLISHED
  publish stays visible (failure injection scenario D).
- "At most one PUBLISHED per trade_date" is enforced inside the transaction
  (DuckDB has no partial unique index).
- Readers NEVER glob directories; artifact files resolve exclusively via
  meta_feature_artifact_component of the publish's artifact set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


class PublishError(RuntimeError):
    """Base error for publish contract violations."""


class PublishStateError(PublishError):
    """Preconditions for publishing are not met."""


def publish_snapshot(
    conn: DuckDBPyConnection,
    *,
    trade_date: date,
    data_snapshot_id: str,
    feature_artifact_set_id: str,
    feature_set_version: str,
    universes: list[tuple[str, str]],
    pipeline_run_id: str | None = None,
    quality_grade: str | None = None,
    publish_id: str | None = None,
) -> str:
    """Atomically publish one trade_date. Returns the publish_id.

    Steps inside ONE transaction (all-or-nothing):
      1. existing PUBLISHED for trade_date -> SUPERSEDED (previous_publish_id)
      2. insert new row status=PUBLISHED
      3. insert meta_publish_universe rows
      4. meta_pipeline_run.status -> PUBLISHED
    """
    pid = publish_id or str(uuid.uuid4())
    now = datetime.now(UTC)

    # preconditions (outside txn: fail fast with clear errors)
    snap = conn.execute(
        "SELECT status FROM meta_data_snapshot WHERE data_snapshot_id = ?",
        [data_snapshot_id],
    ).fetchone()
    if snap is None:
        msg = f"data_snapshot {data_snapshot_id} not registered"
        raise PublishStateError(msg)
    if snap[0] != "DATA_VALIDATED":
        msg = f"data_snapshot {data_snapshot_id} status is {snap[0]}, expected DATA_VALIDATED"
        raise PublishStateError(msg)
    art = conn.execute(
        "SELECT status FROM meta_feature_artifact_set WHERE feature_artifact_set_id = ?",
        [feature_artifact_set_id],
    ).fetchone()
    if art is None:
        msg = f"feature_artifact_set {feature_artifact_set_id} not registered"
        raise PublishStateError(msg)
    if art[0] != "FEATURE_VALIDATED":
        msg = (
            f"artifact set {feature_artifact_set_id} status is {art[0]}, expected FEATURE_VALIDATED"
        )
        raise PublishStateError(msg)
    if not universes:
        msg = "at least one (universe_id, universe_version) is required"
        raise PublishStateError(msg)

    conn.execute("BEGIN TRANSACTION")
    try:
        existing = conn.execute(
            "SELECT publish_id FROM meta_publish_snapshot "
            "WHERE trade_date = ? AND status = 'PUBLISHED'",
            [trade_date],
        ).fetchone()
        previous_publish_id = existing[0] if existing else None
        if existing is not None:
            conn.execute(
                "UPDATE meta_publish_snapshot SET status = 'SUPERSEDED' WHERE publish_id = ?",
                [existing[0]],
            )
        conn.execute(
            "INSERT INTO meta_publish_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?)",
            [
                pid,
                trade_date,
                pipeline_run_id,
                data_snapshot_id,
                feature_artifact_set_id,
                feature_set_version,
                None,  # mart_version (M0 skeleton)
                now,
                quality_grade,
                previous_publish_id,
            ],
        )
        for universe_id, universe_version in universes:
            conn.execute(
                "INSERT INTO meta_publish_universe VALUES (?, ?, ?)",
                [pid, universe_id, universe_version],
            )
        if pipeline_run_id is not None:
            conn.execute(
                "UPDATE meta_pipeline_run SET status = 'PUBLISHED', ended_at = ? "
                "WHERE pipeline_run_id = ?",
                [now, pipeline_run_id],
            )
        # in-transaction uniqueness guard: at most one PUBLISHED per trade_date
        count_row = conn.execute(
            "SELECT count(*) FROM meta_publish_snapshot "
            "WHERE trade_date = ? AND status = 'PUBLISHED'",
            [trade_date],
        ).fetchone()
        n = count_row[0] if count_row is not None else 0
        if n != 1:
            msg = f"publish invariant violated: {n} PUBLISHED rows for {trade_date}"
            raise PublishError(msg)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return pid


# ------------------------------------------------------------------- readers


def latest_published(conn: DuckDBPyConnection, trade_date: date) -> dict[str, Any] | None:
    """The current PUBLISHED publish for a trade_date (or None)."""
    row = conn.execute(
        "SELECT publish_id, trade_date, data_snapshot_id, feature_artifact_set_id, "
        "feature_set_version, status, published_at, previous_publish_id, quality_grade "
        "FROM meta_publish_snapshot WHERE trade_date = ? AND status = 'PUBLISHED'",
        [trade_date],
    ).fetchone()
    if row is None:
        return None
    keys = (
        "publish_id",
        "trade_date",
        "data_snapshot_id",
        "feature_artifact_set_id",
        "feature_set_version",
        "status",
        "published_at",
        "previous_publish_id",
        "quality_grade",
    )
    return dict(zip(keys, row, strict=True))


def resolve_publish(conn: DuckDBPyConnection, publish_id: str) -> dict[str, Any]:
    """Exact replay anchor: resolve any publish (incl. SUPERSEDED)."""
    row = conn.execute(
        "SELECT publish_id, trade_date, data_snapshot_id, feature_artifact_set_id, "
        "feature_set_version, status, published_at, previous_publish_id "
        "FROM meta_publish_snapshot WHERE publish_id = ?",
        [publish_id],
    ).fetchone()
    if row is None:
        msg = f"publish {publish_id} not found"
        raise PublishError(msg)
    keys = (
        "publish_id",
        "trade_date",
        "data_snapshot_id",
        "feature_artifact_set_id",
        "feature_set_version",
        "status",
        "published_at",
        "previous_publish_id",
    )
    return dict(zip(keys, row, strict=True))


def artifact_files_for_publish(conn: DuckDBPyConnection, publish_id: str) -> list[dict[str, Any]]:
    """Exact file list via the artifact component manifest - never a glob."""
    pub = resolve_publish(conn, publish_id)
    rows = conn.execute(
        "SELECT layer, feature_family, feature_family_version, file_uri, "
        "content_hash, schema_hash, row_count "
        "FROM meta_feature_artifact_component WHERE feature_artifact_set_id = ? "
        "ORDER BY file_uri",
        [pub["feature_artifact_set_id"]],
    ).fetchall()
    keys = (
        "layer",
        "feature_family",
        "feature_family_version",
        "file_uri",
        "content_hash",
        "schema_hash",
        "row_count",
    )
    return [dict(zip(keys, r, strict=True)) for r in rows]


def publish_universes(conn: DuckDBPyConnection, publish_id: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT universe_id, universe_version FROM meta_publish_universe "
        "WHERE publish_id = ? ORDER BY universe_id",
        [publish_id],
    ).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


# -------------------------------------------------------- startup recovery


def find_orphan_files(conn: DuckDBPyConnection, features_root: Path) -> list[Path]:
    """Scenario A recovery check: physical files not registered anywhere.

    An orphan (file moved but DB registration crashed before commit) is
    invisible to all readers and MAY be cleaned later. This function only
    reports; deletion is a separate, audited operation.
    """
    registered: set[str] = {
        str(row[0])
        for row in conn.execute("SELECT file_uri FROM meta_feature_artifact_component").fetchall()
    }
    registered |= {
        str(row[0])
        for row in conn.execute("SELECT file_uri FROM meta_data_snapshot_component").fetchall()
    }
    orphans: list[Path] = []
    if not features_root.is_dir():
        return orphans
    for path in features_root.rglob("*.parquet"):
        rel = path.relative_to(features_root).as_posix()
        if rel not in registered:
            orphans.append(path)
    return orphans
