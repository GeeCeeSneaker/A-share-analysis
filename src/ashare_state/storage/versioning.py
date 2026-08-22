"""Version immutability service rules (audit R2-P1-10 / R2-P1-11).

Frozen rule: a versioned definition (Feature Set / Universe / Source
Policy) follows DRAFT -> ACTIVE -> immutable; any modification after
activation must create a NEW version. These helpers are the ONLY blessed
write paths; direct UPDATE/DELETE on activated versions is forbidden by
convention and guarded by tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


class VersioningError(RuntimeError):
    """Forbidden mutation of an immutable (activated/approved) version."""


def activate_feature_set(conn: DuckDBPyConnection, feature_set_version: str) -> None:
    """DRAFT -> ACTIVE transition; ACTIVE sets are member-immutable."""
    row = conn.execute(
        "SELECT status FROM meta_feature_set WHERE feature_set_version = ?",
        [feature_set_version],
    ).fetchone()
    if row is None:
        msg = f"feature set {feature_set_version!r} not registered"
        raise VersioningError(msg)
    if row[0] == "ACTIVE":
        msg = f"feature set {feature_set_version!r} is already ACTIVE"
        raise VersioningError(msg)
    if row[0] != "DRAFT":
        msg = f"feature set {feature_set_version!r} status is {row[0]}; only DRAFT can be activated"
        raise VersioningError(msg)
    conn.execute(
        "UPDATE meta_feature_set SET status = 'ACTIVE' WHERE feature_set_version = ?",
        [feature_set_version],
    )


def assert_feature_set_members_mutable(conn: DuckDBPyConnection, feature_set_version: str) -> None:
    """Guard for member writes: raise when the set is immutable."""
    row = conn.execute(
        "SELECT status FROM meta_feature_set WHERE feature_set_version = ?",
        [feature_set_version],
    ).fetchone()
    if row is not None and row[0] in ("ACTIVE", "RETIRED"):
        msg = (
            f"feature set {feature_set_version!r} is {row[0]}: members are "
            "immutable; create a new version instead"
        )
        raise VersioningError(msg)


def activate_universe(conn: DuckDBPyConnection, universe_id: str, universe_version: str) -> None:
    """Universe activation (R3-P1-02): idempotent for the SAME rule hash,
    BLOCKED for a different one - never overwritten."""
    import hashlib
    from datetime import UTC, datetime

    row = conn.execute(
        "SELECT rule_json FROM dim_universe WHERE universe_id = ? AND universe_version = ?",
        [universe_id, universe_version],
    ).fetchone()
    if row is None:
        msg = f"universe ({universe_id}, {universe_version}) not registered"
        raise VersioningError(msg)
    rule_hash = hashlib.sha256(str(row[0]).encode()).hexdigest()
    existing = conn.execute(
        "SELECT rule_hash FROM universe_activation WHERE universe_id = ? AND universe_version = ?",
        [universe_id, universe_version],
    ).fetchone()
    if existing is not None:
        if existing[0] == rule_hash:
            return  # same rule: idempotent no-op
        msg = (
            f"universe ({universe_id}, {universe_version}) is ACTIVATED with a "
            f"different rule hash ({str(existing[0])[:12]}... != {rule_hash[:12]}...); "
            "reactivation with changed rules is forbidden - create a new version"
        )
        raise VersioningError(msg)
    conn.execute(
        "INSERT INTO universe_activation VALUES (?, ?, ?, ?)",
        [universe_id, universe_version, rule_hash, datetime.now(UTC)],
    )


def recompute_feature_set_hash(conn: DuckDBPyConnection, feature_set_version: str) -> str | None:
    """R3-P1-03: recompute the members' definition hash from CURRENT rows.

    Mirrors the registration formula (sorted member tuples -> sha256) so a
    publish-time self-check can detect out-of-band member edits. Returns
    None when the set is not registered.
    """
    import hashlib

    rows = conn.execute(
        "SELECT feature_id, feature_version, param_set_id "
        "FROM meta_feature_set_member WHERE feature_set_version = ? "
        "ORDER BY feature_id, feature_version, param_set_id",
        [feature_set_version],
    ).fetchall()
    if not rows:
        return None
    payload = "|".join(f"{r[0]}:{r[1]}:{r[2]}" for r in rows)
    return hashlib.sha256(payload.encode()).hexdigest()


def assert_universe_rule_mutable(
    conn: DuckDBPyConnection, universe_id: str, universe_version: str, rule_json: str
) -> None:
    """Guard for rule_json writes: raise when the activated rule would change."""
    import hashlib

    row = conn.execute(
        "SELECT rule_hash FROM universe_activation WHERE universe_id = ? AND universe_version = ?",
        [universe_id, universe_version],
    ).fetchone()
    if row is None:
        return  # not activated yet: mutable
    new_hash = hashlib.sha256(str(rule_json).encode()).hexdigest()
    if new_hash != row[0]:
        msg = (
            f"universe ({universe_id}, {universe_version}) is ACTIVATED: "
            "rule_json is immutable; create a new version instead"
        )
        raise VersioningError(msg)


# ------------------------------------------------- STAGING service rule (R2-P1-10)


def assert_snapshot_insert_validated(status: str) -> None:
    """ADR-009: snapshot/artifact metadata rows insert ONLY as validated.

    The 003 DDL keeps a legacy DEFAULT 'STAGING'; this service rule makes
    new STAGING inserts impossible through blessed paths.
    """
    if status not in ("DATA_VALIDATED",):
        msg = (
            f"snapshot metadata must insert as DATA_VALIDATED (got {status!r}); "
            "staging lives in the run/filesystem layer only (ADR-009)"
        )
        raise VersioningError(msg)


def assert_artifact_insert_validated(status: str) -> None:
    if status not in ("FEATURE_VALIDATED",):
        msg = (
            f"artifact metadata must insert as FEATURE_VALIDATED (got {status!r}); "
            "staging lives in the run/filesystem layer only (ADR-009)"
        )
        raise VersioningError(msg)


__all__ = [
    "VersioningError",
    "activate_feature_set",
    "activate_universe",
    "assert_artifact_insert_validated",
    "assert_feature_set_members_mutable",
    "assert_snapshot_insert_validated",
    "assert_universe_rule_mutable",
]
