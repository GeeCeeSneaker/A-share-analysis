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


def record_artifact_validation(
    conn: DuckDBPyConnection,
    *,
    feature_artifact_set_id: str,
    validation_version: str,
    identity_fallback_count: int,
    blocking_dq_count: int,
    validator_code_commit: str | None = None,
    validation_hash: str | None = None,
    details_json: str | None = None,
) -> str:
    """APPEND a validation record to the ledger (R3-P1-01).

    Every call inserts a NEW artifact_validation_id - validations are
    immutable history. The publish gate binds the LATEST record for the
    artifact set, and old publishes keep answering "which validation
    approved me" via meta_publish_snapshot.artifact_validation_id.
    Returns the new artifact_validation_id.
    """
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    validation_id = f"val-{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO meta_artifact_validation VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            validation_id,
            feature_artifact_set_id,
            validation_version,
            validator_code_commit,
            int(identity_fallback_count),
            int(blocking_dq_count),
            _datetime.now(_UTC),
            details_json or validation_hash,
        ],
    )
    return validation_id


def publish_snapshot(
    conn: DuckDBPyConnection,
    *,
    trade_date: date,
    data_snapshot_id: str,
    feature_artifact_set_id: str,
    feature_set_version: str,
    universes: list[tuple[str, str]],
    pipeline_run_id: str,
    quality_grade: str | None = None,
    publish_id: str | None = None,
) -> str:
    """Atomically publish one trade_date. Returns the publish_id.

    Steps inside ONE transaction (all-or-nothing):
      1. existing PUBLISHED for trade_date -> SUPERSEDED (previous_publish_id)
      2. insert new row status=PUBLISHED (bound to the artifact_validation_id)
      3. insert meta_publish_universe rows
      4. meta_pipeline_run.status -> PUBLISHED

    Full lineage gate (R1 P0-02 + R2 P0-05/P0-06 + R3 P0-18/P1-01/P1-03):
      - snapshot exists, status DATA_VALIDATED
      - artifact exists, status FEATURE_VALIDATED
      - artifact.data_snapshot_id == data_snapshot_id (no cross-snapshot mix)
      - artifact.feature_set_version == feature_set_version
      - meta_feature_set exists, is ACTIVE, and its members STILL hash to
        the registered definition_hash (P1-03 self-check)
      - pipeline_run REQUIRED - NO exceptions (R3-P0-18: the manual escape
        hatch is removed; recovery/republish must create a RECOVERY run)
      - pipeline_run exists, status FEATURE_VALIDATED
      - artifact.calc_run_id == pipeline_run_id (RECOVERY runs exempt)
      - run/artifact (code_commit, environment_lock_hash, config_hash) match
      - run/snapshot (source_policy_version, availability_policy_version) match
      - every (universe_id, universe_version) exists in dim_universe
      - the LATEST append-only meta_artifact_validation record for the set
        has identity_fallback_count == 0 and blocking_dq_count == 0
    """
    pid = publish_id or str(uuid.uuid4())
    now = datetime.now(UTC)

    if pipeline_run_id is None:
        # R3-P0-18: no run-less publishes, ever - recovery uses RECOVERY runs
        msg = (
            "publish requires pipeline_run_id (R3-P0-18: no manual escape "
            "hatch; recovery/republish must create a RECOVERY-type run)"
        )
        raise PublishStateError(msg)

    # preconditions (outside txn: fail fast with clear errors)
    snap = conn.execute(
        "SELECT status, source_policy_version, availability_policy_version "
        "FROM meta_data_snapshot WHERE data_snapshot_id = ?",
        [data_snapshot_id],
    ).fetchone()
    if snap is None:
        msg = f"data_snapshot {data_snapshot_id} not registered"
        raise PublishStateError(msg)
    if snap[0] != "DATA_VALIDATED":
        msg = f"data_snapshot {data_snapshot_id} status is {snap[0]}, expected DATA_VALIDATED"
        raise PublishStateError(msg)
    art = conn.execute(
        "SELECT status, data_snapshot_id, feature_set_version, calc_run_id, "
        "code_commit, environment_lock_hash, config_hash "
        "FROM meta_feature_artifact_set WHERE feature_artifact_set_id = ?",
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
    if art[1] != data_snapshot_id:
        msg = (
            "SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: artifact "
            f"{feature_artifact_set_id} was computed from snapshot {art[1]}, "
            f"but this publish references snapshot {data_snapshot_id}"
        )
        raise PublishStateError(msg)
    if art[2] != feature_set_version:
        msg = (
            "SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: artifact "
            f"{feature_artifact_set_id} belongs to feature set {art[2]}, "
            f"but this publish references {feature_set_version}"
        )
        raise PublishStateError(msg)
    fset = conn.execute(
        "SELECT status, definition_hash FROM meta_feature_set WHERE feature_set_version = ?",
        [feature_set_version],
    ).fetchone()
    if fset is None:
        msg = (
            f"SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: feature set "
            f"{feature_set_version} not registered"
        )
        raise PublishStateError(msg)
    if fset[0] != "ACTIVE":
        msg = (
            f"SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: feature set "
            f"{feature_set_version} status is {fset[0]}, expected ACTIVE"
        )
        raise PublishStateError(msg)
    # R3-P1-03: self-check - members must STILL hash to the registered
    # definition_hash (out-of-band member edits block the publish even
    # though they bypassed the service helpers)
    from ashare_state.storage.versioning import recompute_feature_set_hash

    current_hash = recompute_feature_set_hash(conn, feature_set_version)
    if current_hash is not None and current_hash != fset[1]:
        msg = (
            f"FEATURE_SET_IMMUTABLE violated: {feature_set_version} members hash to "
            f"{current_hash[:12]}... but the registered definition_hash is "
            f"{str(fset[1])[:12]}... - members changed after activation; create a "
            "new version instead"
        )
        raise PublishStateError(msg)
    if pipeline_run_id is not None:
        run = conn.execute(
            "SELECT status, code_commit, environment_lock_hash, config_hash, "
            "source_policy_version, availability_policy_version, run_type "
            "FROM meta_pipeline_run WHERE pipeline_run_id = ?",
            [pipeline_run_id],
        ).fetchone()
        if run is None:
            msg = (
                f"SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: pipeline run "
                f"{pipeline_run_id} not registered"
            )
            raise PublishStateError(msg)
        if run[0] != "FEATURE_VALIDATED":
            msg = (
                f"SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: pipeline run "
                f"{pipeline_run_id} status is {run[0]}, expected FEATURE_VALIDATED"
            )
            raise PublishStateError(msg)
        is_recovery = str(run[6]) == "RECOVERY"
        # R2-P0-06: artifact <-> run binding. A RECOVERY run may re-publish
        # an artifact produced by another run (that is its purpose); normal
        # runs must be the artifact's producing run.
        if not is_recovery and art[3] is not None and art[3] != pipeline_run_id:
            msg = (
                "RUN_ARTIFACT_LINEAGE_VALID violated: artifact "
                f"{feature_artifact_set_id} was computed by run {art[3]}, "
                f"but this publish references run {pipeline_run_id}"
            )
            raise PublishStateError(msg)
        for label, run_value, art_value in (
            ("code_commit", run[1], art[4]),
            ("environment_lock_hash", run[2], art[5]),
            ("config_hash", run[3], art[6]),
        ):
            if run_value is not None and art_value is not None and run_value != art_value:
                msg = (
                    f"RUN_ARTIFACT_LINEAGE_VALID violated: {label} mismatch "
                    f"(run={run_value!r}, artifact={art_value!r})"
                )
                raise PublishStateError(msg)
        # R2-P0-06: run <-> snapshot policy binding (006 columns)
        for label, run_value, snap_value in (
            ("source_policy_version", run[4], snap[1]),
            ("availability_policy_version", run[5], snap[2]),
        ):
            if run_value is not None and snap_value is not None and run_value != snap_value:
                msg = (
                    f"RUN_SNAPSHOT_POLICY_LINEAGE_VALID violated: {label} mismatch "
                    f"(run={run_value!r}, snapshot={snap_value!r})"
                )
                raise PublishStateError(msg)
    if not universes:
        msg = "at least one (universe_id, universe_version) is required"
        raise PublishStateError(msg)
    for universe_id, universe_version in universes:
        u = conn.execute(
            "SELECT 1 FROM dim_universe WHERE universe_id = ? AND universe_version = ?",
            [universe_id, universe_version],
        ).fetchone()
        if u is None:
            msg = (
                "SNAPSHOT_ARTIFACT_LINEAGE_VALID violated: universe "
                f"({universe_id}, {universe_version}) not registered in dim_universe"
            )
            raise PublishStateError(msg)
    # R2-P0-05 + R3-P1-01: the LATEST append-only validation record is the
    # system invariant; the publish binds its artifact_validation_id
    validation = conn.execute(
        "SELECT artifact_validation_id, identity_fallback_count, blocking_dq_count "
        "FROM meta_artifact_validation WHERE feature_artifact_set_id = ? "
        "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1",
        [feature_artifact_set_id],
    ).fetchone()
    if validation is None:
        msg = (
            "ARTIFACT_VALIDATION_REQUIRED violated: no meta_artifact_validation "
            f"record for {feature_artifact_set_id}; publish is blocked until the "
            "artifact validator records identity_fallback_count and blocking_dq_count"
        )
        raise PublishStateError(msg)
    if validation[1] != 0 or validation[2] != 0:
        msg = (
            "ARTIFACT_VALIDATION_GATE violated: "
            f"identity_fallback_count={validation[1]}, blocking_dq_count={validation[2]}; "
            "fallback identities and blocking DQ findings may never be PUBLISHED"
        )
        raise PublishStateError(msg)
    artifact_validation_id = validation[0]

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
            "INSERT INTO meta_publish_snapshot VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?)",
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
                artifact_validation_id,  # R3-P1-01: bound validation
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


def find_orphan_files(conn: DuckDBPyConnection, data_root: Path) -> list[Path]:
    """Scenario A recovery check: physical files not registered anywhere.

    Audit P1-01: scans data_root (canonical + features) and compares against
    REGISTERED file_uris which are data_root-relative - roots must match.

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
    if not data_root.is_dir():
        return orphans
    for path in data_root.rglob("*.parquet"):
        rel = path.relative_to(data_root).as_posix()
        if rel not in registered:
            orphans.append(path)
    return orphans
