"""Governed artifact DQ scan execution boundary (R4-B2.2, audit 20260831).

The R4-B2.1 completion-proof API was still a caller assertion:
``record_artifact_check_execution`` persisted execution METADATA
without executing any scan - the same structural bypass shape closed
for capability approval (B1) and validation rows (B2):

    B1:      caller self-declare APPROVED
    B2:      caller self-declare 0 counts
    B2.1:    caller self-declare "scan executed"

R4-B2.2 removes the production caller-facing completion writer. The
ONE governed boundary is ``run_required_artifact_dq_scan``:

    BEGIN governed scan operation
      resolve CURRENT components from the registry (internally)
      compute the exact component manifest hash (internally)
      for every check in the STATIC production registry:
        execute the production-owned evaluator over authoritative input
        persist every finding it detects (deduplicated, append-only)
        (an evaluator that cannot run leaves NO completion proof)
      INSERT the execution-completion proof LAST
    COMMIT

Caller inputs are (conn, data_root, feature_artifact_set_id) ONLY -
no scanned-identity, no contract version, no producer, no result, no
count, no completion timestamp. Everything identity-shaped is resolved
by the scanner itself from the CURRENT registry; the scan contract /
checker / producer identities are SYSTEM-DERIVED from the static
registry.

Authoritative inputs (audit section 4.5 - what each check READS):

- IDENTITY_FALLBACK: the artifact set's feature component parquet
  ``security_id`` column (distinct) CROSS-JOINED against
  ``dim_security.identity_key_version``. A security whose registered
  identity key version is the fallback variant, or that is NOT
  registered at all (unprovable -> fail closed), is a finding.
- BLOCKING_DQ: the snapshot's canonical fact tables
  (``fact_daily_bar`` / ``fact_security_status_daily`` /
  ``fact_limit_price`` / ``fact_adj_factor`` / ``fact_corporate_action``)
  ``quality_flags`` column for the artifact's bound data snapshot. Any
  row carrying a blocking DQ flag is a finding.

The validator (``artifact_validation.validate_artifact_for_publish``)
consumes ONLY completion proofs produced by this boundary and fails
closed unless the proof's scan contract / checker identity matches the
CURRENT registry and its scanned component manifest equals the CURRENT
manifest.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.storage.paths import physical_from_logical_uri

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

__all__ = [
    "BLOCKING_DQ_FLAG_NAMES",
    "DQ_SCAN_CONTRACT_VERSION",
    "ArtifactDQCheckId",
    "ArtifactDQCheckerSpec",
    "ArtifactDQScanError",
    "ARTIFACT_DQ_CHECKERS",
    "run_required_artifact_dq_scan",
]


class ArtifactDQScanError(RuntimeError):
    """The governed DQ scan boundary contract was violated."""


#: R4-B2.2 (audit 20260831 section 4.3): the scan contract identity.
#: The completion proof records the contract the scan ran under; the
#: validator accepts a proof only when it equals the CURRENT version -
#: old / unknown / mismatched contracts require a rescan.
DQ_SCAN_CONTRACT_VERSION = "dq-scan-b2.2-v1"


class ArtifactDQCheckId(StrEnum):
    """The governed DQ required-check ids (scanner-side identity).

    Values match the validation-side required-check ids
    (``IDENTITY_FALLBACK_ZERO`` / ``BLOCKING_DQ_ZERO``) - the
    completion proof's ``check_id`` column identifies the REQUIRED
    CHECK whose scan completed (migration 012 semantics)."""

    IDENTITY_FALLBACK = "IDENTITY_FALLBACK_ZERO"
    BLOCKING_DQ = "BLOCKING_DQ_ZERO"


#: quality flags counted as BLOCKING DQ by the governed scanner
#: (IDENTITY_FALLBACK is its own check/finding class). V1.3.2 quality
#: flag set minus the identity-fallback flag.
BLOCKING_DQ_FLAG_NAMES: tuple[str, ...] = (
    "STALE_WINDOW",
    "BENCHMARK_UNAVAILABLE",
    "INVALID_LIMIT_RANGE",
    "NO_LIMIT_RULE",
    "LOW_SAMPLE",
)

#: the snapshot-bound canonical fact tables the BLOCKING_DQ evaluator
#: scans (authoritative input).
_BLOCKING_DQ_FACT_TABLES: tuple[str, ...] = (
    "fact_daily_bar",
    "fact_security_status_daily",
    "fact_limit_price",
    "fact_adj_factor",
    "fact_corporate_action",
)

#: identity key version that marks a FALLBACK identity (001 schema)
_FALLBACK_IDENTITY_KEY_VERSION = "SECURITY_IDENTITY_V1_FALLBACK"


@dataclass(frozen=True)
class ArtifactDQCheckerSpec:
    """The STATIC production checker registration for one DQ required
    check. The evaluator is a production-owned function - the registry
    is module-level and NOT caller-injectable (audit section 5)."""

    check_id: ArtifactDQCheckId
    finding_class: str
    checker_version: str
    evaluator: Callable[[DuckDBPyConnection, Path, str, str], list[str]]

    @property
    def producer(self) -> str:
        """SYSTEM-DERIVED producer identity recorded in the completion
        proof (checker identity, not a caller declaration)."""
        return f"artifact-dq-scanner/{self.check_id.value}@{self.checker_version}"


def _resolve_components(
    conn: DuckDBPyConnection, feature_artifact_set_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT layer, feature_family, feature_family_version, partition_key, "
        "file_uri, content_hash, schema_hash, row_count "
        "FROM meta_feature_artifact_component WHERE feature_artifact_set_id = ? "
        "ORDER BY file_uri",
        [feature_artifact_set_id],
    ).fetchall()
    keys = (
        "layer",
        "feature_family",
        "feature_family_version",
        "partition_key",
        "file_uri",
        "content_hash",
        "schema_hash",
        "row_count",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _evaluator_identity_fallback(
    conn: DuckDBPyConnection,
    data_root: Path,
    feature_artifact_set_id: str,
    data_snapshot_id: str,
) -> list[str]:
    """IDENTITY_FALLBACK evaluator - authoritative input: the artifact
    set's feature component parquet ``security_id`` column (distinct)
    cross-joined against ``dim_security.identity_key_version``.

    Findings: a security registered with the FALLBACK identity key
    version, or a security NOT registered at all (unprovable - fail
    closed)."""
    import pyarrow.parquet as pq

    components = _resolve_components(conn, feature_artifact_set_id)
    security_ids: set[str] = set()
    for comp in components:
        path = physical_from_logical_uri(data_root, str(comp["file_uri"]))
        table = pq.read_table(path, columns=["security_id"])
        security_ids.update(str(v) for v in table.column("security_id").to_pylist())
    if not security_ids:
        return []
    findings: list[str] = []
    ids = sorted(security_ids)
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT security_id, identity_key_version FROM dim_security "
            f"WHERE security_id IN ({placeholders})",
            chunk,
        ).fetchall()
        registered = {str(row[0]): str(row[1]) for row in rows}
        for sid in chunk:
            version = registered.get(sid)
            if version is None:
                findings.append(
                    f"security_id {sid} not registered in dim_security - "
                    "cannot prove non-fallback identity (fail closed)"
                )
            elif version == _FALLBACK_IDENTITY_KEY_VERSION:
                findings.append(
                    f"security_id {sid} registered with fallback identity key version {version}"
                )
    return findings


def _evaluator_blocking_dq(
    conn: DuckDBPyConnection,
    data_root: Path,
    feature_artifact_set_id: str,
    data_snapshot_id: str,
) -> list[str]:
    """BLOCKING_DQ evaluator - authoritative input: the snapshot's
    canonical fact tables' ``quality_flags`` column (the artifact's
    bound data snapshot). Any row carrying a blocking DQ flag is a
    finding."""
    findings: list[str] = []
    flags = list(BLOCKING_DQ_FLAG_NAMES)
    for table in _BLOCKING_DQ_FACT_TABLES:
        rows = conn.execute(
            f"SELECT count(*) FROM {table} WHERE data_snapshot_id = ? "
            f"AND quality_flags IS NOT NULL AND quality_flags <> ''",
            [data_snapshot_id],
        ).fetchone()
        flagged = int(rows[0]) if rows else 0
        if not flagged:
            continue
        # inspect the flagged rows for the blocking flag names
        sample = conn.execute(
            f"SELECT DISTINCT quality_flags FROM {table} "
            f"WHERE data_snapshot_id = ? AND quality_flags IS NOT NULL "
            f"AND quality_flags <> ''",
            [data_snapshot_id],
        ).fetchall()
        for (quality_flags,) in sample:
            tokens = {
                token.strip() for token in str(quality_flags or "").split(",") if token.strip()
            }
            hit = sorted(tokens & set(flags))
            if hit:
                findings.append(
                    f"{table} rows carry blocking DQ flags {hit} (quality_flags={quality_flags!r})"
                )
    return findings


#: the STATIC production checker registry (audit section 5): NOT a
#: caller-injectable parameter. Adding/removing a checker or changing
#: an evaluator changes the checker/contract identity and invalidates
#: prior completion proofs (validator checks current-contract match).
ARTIFACT_DQ_CHECKERS: tuple[ArtifactDQCheckerSpec, ...] = (
    ArtifactDQCheckerSpec(
        check_id=ArtifactDQCheckId.IDENTITY_FALLBACK,
        finding_class="IDENTITY_FALLBACK",
        checker_version="identity-fallback-checker-v1",
        evaluator=_evaluator_identity_fallback,
    ),
    ArtifactDQCheckerSpec(
        check_id=ArtifactDQCheckId.BLOCKING_DQ,
        finding_class="BLOCKING_DQ",
        checker_version="blocking-dq-checker-v1",
        evaluator=_evaluator_blocking_dq,
    ),
)


def run_required_artifact_dq_scan(
    conn: DuckDBPyConnection,
    *,
    data_root: Path,
    feature_artifact_set_id: str,
) -> dict[str, str]:
    """R4-B2.2: the ONE governed DQ scan execution boundary.

    Executes every check in the STATIC production registry against the
    artifact's authoritative inputs, persists every detected finding
    (deduplicated - append-only facts), and writes the
    execution-completion proof LAST - all inside ONE transaction. A
    check whose evaluator cannot run (raises) leaves NO completion
    proof for that check (the validator will see NOT_TESTABLE).

    Caller inputs are (conn, data_root, feature_artifact_set_id)
    ONLY. The scanned component identity is computed INTERNALLY from
    the CURRENT registry; the scan contract / checker / producer
    identities are SYSTEM-DERIVED from the static registry.

    Returns {check_id: execution_id} for every check that completed.
    """
    from ashare_state.pipeline.artifact_validation import (
        compute_component_manifest_hash,
    )

    data_root = Path(data_root)
    art = conn.execute(
        "SELECT data_snapshot_id FROM meta_feature_artifact_set WHERE feature_artifact_set_id = ?",
        [feature_artifact_set_id],
    ).fetchone()
    if art is None:
        msg = f"feature_artifact_set {feature_artifact_set_id} not registered"
        raise ArtifactDQScanError(msg)
    data_snapshot_id = str(art[0])
    components = _resolve_components(conn, feature_artifact_set_id)
    scanned_manifest = compute_component_manifest_hash(components)

    executions: dict[str, str] = {}
    conn.execute("BEGIN TRANSACTION")
    try:
        for spec in ARTIFACT_DQ_CHECKERS:
            # execute the production-owned evaluator over authoritative
            # input - a raise means "cannot establish the check": no
            # findings are fabricated, no completion proof is written
            findings = spec.evaluator(conn, data_root, feature_artifact_set_id, data_snapshot_id)
            # persist every detected finding (append-only facts,
            # deduplicated against existing rows so rescans do not
            # inflate the derived counts)
            for detail in findings:
                exists = conn.execute(
                    "SELECT 1 FROM meta_artifact_dq_finding "
                    "WHERE feature_artifact_set_id = ? AND finding_class = ? "
                    "AND detail = ?",
                    [feature_artifact_set_id, spec.finding_class, detail],
                ).fetchone()
                if exists is None:
                    conn.execute(
                        "INSERT INTO meta_artifact_dq_finding VALUES (?, ?, ?, ?, ?)",
                        [
                            f"dqf-{uuid.uuid4()}",
                            feature_artifact_set_id,
                            spec.finding_class,
                            datetime.now(UTC),
                            detail,
                        ],
                    )
            # completion proof LAST - only after the scan (and its
            # finding persistence) actually completed
            execution_id = f"dqexec-{uuid.uuid4()}"
            conn.execute(
                "INSERT INTO meta_artifact_check_execution VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    execution_id,
                    feature_artifact_set_id,
                    spec.check_id.value,
                    DQ_SCAN_CONTRACT_VERSION,  # system-derived
                    spec.producer,  # system-derived checker identity
                    scanned_manifest,  # computed INTERNALLY from the registry
                    datetime.now(UTC),
                    f"scan executed over {len(components)} components; "
                    f"detected findings: {len(findings)}",
                ],
            )
            executions[spec.check_id.value] = execution_id
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return executions
