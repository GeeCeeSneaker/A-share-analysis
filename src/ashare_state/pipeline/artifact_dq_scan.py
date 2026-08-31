"""Governed artifact DQ scan execution boundary (R4-B2.2, audit
20260831; R4-B2.3 authoritative-input seal, audit 20260831 13:37).

R4-B2.2 removed the production caller-facing completion writer: the
completion proof is the SCANNER's internal product (static registry,
internally-computed identity, system-derived contract/producer).

R4-B2.3 closes the remaining correctness gap: the completion proof
previously sealed only the scanned COMPONENT manifest, but the real
checkers also read -

- IDENTITY_FALLBACK: ``dim_security.identity_key_version`` per
  security (can change after a genuine zero scan), and
- BLOCKING_DQ: the artifact's bound ``data_snapshot_id`` and the
  snapshot-bound canonical fact ``quality_flags`` (also mutable),

so a component-manifest match did NOT prove the checker inputs are
unchanged (stale proof -> false PASS).

The boundary now:

    BEGIN TRANSACTION                       (FIRST - order-guarded)
      read CURRENT artifact snapshot + components   (inside)
      compute component manifest (internally)
      for each static checker:
        resolve the checker's AUTHORITATIVE INPUT STATE (shared
          resolution - fingerprint and evaluator consume the SAME
          state, they cannot drift)
        fingerprint that state (canonical JSON -> SHA-256)
        execute the evaluator over the SAME state
        persist findings (append-only, deduplicated)
        INSERT completion proof LAST:
          component_manifest_hash
          scanned_data_snapshot_id (explicit audit field)
          authoritative_input_hash (checker-specific input seal)
          scan contract / checker producer (system-derived)
    COMMIT

The validator (``artifact_validation``) recomputes the CURRENT input
fingerprint per check and rejects stale / missing / legacy proofs; the
publish final recheck re-verifies the DQ input seal again inside the
publish transaction (input changes AFTER validation block publish).
"""

from __future__ import annotations

import hashlib
import json
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


#: R4-B2.3 (audit 20260831 13:37 section 6): the scan contract identity
#: evolves with the input seal - the validator accepts a proof only
#: when it equals the CURRENT version; legacy rows without the
#: authoritative-input seal are NOT compatible (rescan required).
DQ_SCAN_CONTRACT_VERSION = "dq-scan-b2.3-v1"


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

#: explicit marker for a security_id absent from dim_security
_IDENTITY_MISSING = "__MISSING__"


@dataclass(frozen=True)
class _ScanContext:
    """The CURRENT registry state resolved INSIDE the governed
    transaction - the single source both the manifest computation and
    every checker consume (no pre-transaction reads are trusted)."""

    feature_artifact_set_id: str
    data_snapshot_id: str
    components: list[dict[str, Any]]
    component_manifest_hash: str


def _canonical_hash(payload: Any) -> str:
    """Stable, provider/machine-independent fingerprint (sorted
    canonical JSON -> SHA-256)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_identity_input(
    conn: DuckDBPyConnection, data_root: Path, ctx: _ScanContext
) -> list[dict[str, Any]]:
    """IDENTITY_FALLBACK authoritative input state (§4.1): the exact
    security_id set read from the components, with each security's
    CURRENT dim_security.identity_key_version (or an explicit MISSING
    marker). Fingerprint and evaluator consume the SAME resolution -
    they cannot drift (audit §4.3)."""
    import pyarrow.parquet as pq

    security_ids: set[str] = set()
    for comp in ctx.components:
        path = physical_from_logical_uri(data_root, str(comp["file_uri"]))
        table = pq.read_table(path, columns=["security_id"])
        security_ids.update(str(v) for v in table.column("security_id").to_pylist())
    state: list[dict[str, Any]] = []
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
            state.append(
                {
                    "security_id": sid,
                    "identity_key_version": version if version is not None else _IDENTITY_MISSING,
                }
            )
    return state


def _resolve_blocking_dq_input(
    conn: DuckDBPyConnection, data_root: Path, ctx: _ScanContext
) -> list[dict[str, Any]]:
    """BLOCKING_DQ authoritative input state (§4.2): the artifact's
    CURRENT bound data snapshot id plus the quality_flags input state
    the evaluator actually reads - per fact table, the stable
    aggregation (table_name, quality_flags, row_count) over the
    snapshot's rows, NULL/empty normalized to the evaluator's rules.
    Fingerprint and evaluator consume the SAME resolution."""
    state: list[dict[str, Any]] = [{"input": "data_snapshot_id", "value": ctx.data_snapshot_id}]
    for table in _BLOCKING_DQ_FACT_TABLES:
        rows = conn.execute(
            f"SELECT quality_flags, count(*) FROM {table} "
            f"WHERE data_snapshot_id = ? "
            f"GROUP BY quality_flags ORDER BY quality_flags",
            [ctx.data_snapshot_id],
        ).fetchall()
        for quality_flags, row_count in rows:
            normalized = _normalize_quality_flags(quality_flags)
            state.append(
                {
                    "input": "fact_quality_flags",
                    "table": table,
                    "quality_flags": normalized,
                    "row_count": int(row_count),
                }
            )
    return state


def _normalize_quality_flags(quality_flags: Any) -> str:
    """Normalize NULL/empty quality_flags per the evaluator's current
    rules (NULL and '' both mean 'no flags')."""
    tokens = [token.strip() for token in str(quality_flags or "").split(",") if token.strip()]
    return ",".join(sorted(tokens))


@dataclass(frozen=True)
class ArtifactDQCheckerSpec:
    """The STATIC production checker registration for one DQ required
    check. Input resolution, fingerprint and evaluation live in the
    SAME production-owned spec - the fingerprint always describes the
    exact state the evaluator consumed (audit §4.3).

    The registry is module-level and NOT caller-injectable."""

    check_id: ArtifactDQCheckId
    finding_class: str
    checker_version: str
    resolve_input: Callable[[DuckDBPyConnection, Path, _ScanContext], list[dict[str, Any]]]
    evaluate: Callable[[list[dict[str, Any]]], list[str]]
    scans_data_snapshot: bool = False

    def fingerprint(self, input_state: list[dict[str, Any]]) -> str:
        """Checker-specific authoritative-input seal (§4): canonical
        hash over the resolved input state."""
        return _canonical_hash(
            {
                "check_id": self.check_id.value,
                "checker_version": self.checker_version,
                "input_state": input_state,
            }
        )

    @property
    def producer(self) -> str:
        """SYSTEM-DERIVED producer identity recorded in the completion
        proof (checker identity, not a caller declaration)."""
        return f"artifact-dq-scanner/{self.check_id.value}@{self.checker_version}"


def _evaluate_identity_fallback(input_state: list[dict[str, Any]]) -> list[str]:
    """IDENTITY_FALLBACK evaluation over the resolved input state: a
    security registered with the FALLBACK identity key version, or one
    that is NOT registered at all (unprovable -> fail closed), is a
    finding."""
    findings: list[str] = []
    for entry in input_state:
        sid = entry["security_id"]
        version = entry["identity_key_version"]
        if version == _IDENTITY_MISSING:
            findings.append(
                f"security_id {sid} not registered in dim_security - "
                "cannot prove non-fallback identity (fail closed)"
            )
        elif version == _FALLBACK_IDENTITY_KEY_VERSION:
            findings.append(
                f"security_id {sid} registered with fallback identity key version {version}"
            )
    return findings


def _evaluate_blocking_dq(input_state: list[dict[str, Any]]) -> list[str]:
    """BLOCKING_DQ evaluation over the resolved input state: any
    quality_flags group (of the artifact's bound snapshot) carrying a
    blocking DQ flag is a finding."""
    findings: list[str] = []
    blocking = set(BLOCKING_DQ_FLAG_NAMES)
    for entry in input_state:
        if entry.get("input") != "fact_quality_flags":
            continue
        tokens = {token for token in str(entry["quality_flags"]).split(",") if token}
        hit = sorted(tokens & blocking)
        if hit:
            findings.append(
                f"{entry['table']} rows carry blocking DQ flags {hit} "
                f"(quality_flags={entry['quality_flags']!r})"
            )
    return findings


#: the STATIC production checker registry (audit section 5): NOT a
#: caller-injectable parameter. Adding/removing a checker, changing an
#: evaluator, or changing the input resolution changes the
#: checker/contract identity and invalidates prior completion proofs
#: (validator checks current-contract match + input-seal match).
ARTIFACT_DQ_CHECKERS: tuple[ArtifactDQCheckerSpec, ...] = (
    ArtifactDQCheckerSpec(
        check_id=ArtifactDQCheckId.IDENTITY_FALLBACK,
        finding_class="IDENTITY_FALLBACK",
        checker_version="identity-fallback-checker-v2",
        resolve_input=_resolve_identity_input,
        evaluate=_evaluate_identity_fallback,
    ),
    ArtifactDQCheckerSpec(
        check_id=ArtifactDQCheckId.BLOCKING_DQ,
        finding_class="BLOCKING_DQ",
        checker_version="blocking-dq-checker-v2",
        resolve_input=_resolve_blocking_dq_input,
        evaluate=_evaluate_blocking_dq,
        scans_data_snapshot=True,
    ),
)


def current_authoritative_input_fingerprints(
    conn: DuckDBPyConnection,
    *,
    data_root: Path,
    feature_artifact_set_id: str,
) -> dict[str, str]:
    """Recompute the CURRENT checker input fingerprints for one
    artifact set (validator + publish final recheck consume this).

    Reads the CURRENT artifact snapshot / components / checker inputs
    and returns {check_id: authoritative_input_hash}. The scanner
    writes exactly these values into its completion proofs - a proof
    whose seal differs from the current value is stale (rescan
    required). NOT a caller input anywhere."""
    ctx = _resolve_scan_context(conn, feature_artifact_set_id)
    fingerprints: dict[str, str] = {}
    for spec in ARTIFACT_DQ_CHECKERS:
        input_state = spec.resolve_input(conn, Path(data_root), ctx)
        fingerprints[spec.check_id.value] = spec.fingerprint(input_state)
    return fingerprints


def _resolve_scan_context(conn: DuckDBPyConnection, feature_artifact_set_id: str) -> _ScanContext:
    """Resolve the CURRENT registry state (artifact snapshot + ...
    components) - callers must invoke this INSIDE the governed
    transaction; values read before BEGIN are never trusted as proof
    identity (audit section 5)."""
    from ashare_state.pipeline.artifact_validation import (
        compute_component_manifest_hash,
    )

    art = conn.execute(
        "SELECT data_snapshot_id FROM meta_feature_artifact_set WHERE feature_artifact_set_id = ?",
        [feature_artifact_set_id],
    ).fetchone()
    if art is None:
        msg = f"feature_artifact_set {feature_artifact_set_id} not registered"
        raise ArtifactDQScanError(msg)
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
    components = [dict(zip(keys, row, strict=True)) for row in rows]
    return _ScanContext(
        feature_artifact_set_id=feature_artifact_set_id,
        data_snapshot_id=str(art[0]),
        components=components,
        component_manifest_hash=compute_component_manifest_hash(components),
    )


def run_required_artifact_dq_scan(
    conn: DuckDBPyConnection,
    *,
    data_root: Path,
    feature_artifact_set_id: str,
) -> dict[str, str]:
    """R4-B2.2 + R4-B2.3: the ONE governed DQ scan execution boundary.

    R4-B2.3 section 5 ordering: ``BEGIN TRANSACTION`` FIRST; the
    authoritative artifact-snapshot/component reads happen INSIDE the
    governed transaction (nothing read before BEGIN is trusted as
    proof identity); for every static checker the input state is
    resolved once (fingerprint == evaluator input), findings persist
    (append-only, deduplicated), and the completion proof - now
    carrying the checker-specific authoritative-input seal and the
    scanned data snapshot id - is written LAST. An evaluator failure
    rolls the whole scan back (zero completion rows).

    Caller inputs are (conn, data_root, feature_artifact_set_id)
    ONLY. Returns {check_id: execution_id} for every check that
    completed."""
    data_root = Path(data_root)
    executions: dict[str, str] = {}
    conn.execute("BEGIN TRANSACTION")
    try:
        ctx = _resolve_scan_context(conn, feature_artifact_set_id)
        for spec in ARTIFACT_DQ_CHECKERS:
            # resolve the checker's authoritative input state ONCE -
            # the fingerprint seals exactly what the evaluator consumes
            input_state = spec.resolve_input(conn, data_root, ctx)
            authoritative_input_hash = spec.fingerprint(input_state)
            findings = spec.evaluate(input_state)
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
            # finding persistence) actually completed; the proof seals
            # the checker-specific authoritative input (B2.3)
            execution_id = f"dqexec-{uuid.uuid4()}"
            scanned_snapshot = ctx.data_snapshot_id if spec.scans_data_snapshot else ""
            conn.execute(
                "INSERT INTO meta_artifact_check_execution "
                "(execution_id, feature_artifact_set_id, check_id, "
                "scan_contract_version, producer, scanned_component_manifest_hash, "
                "completed_at, detail, authoritative_input_hash, scanned_data_snapshot_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    execution_id,
                    feature_artifact_set_id,
                    spec.check_id.value,
                    DQ_SCAN_CONTRACT_VERSION,  # system-derived
                    spec.producer,  # system-derived checker identity
                    ctx.component_manifest_hash,  # computed INSIDE the txn
                    datetime.now(UTC),
                    f"scan executed over {len(ctx.components)} components; "
                    f"detected findings: {len(findings)}",
                    authoritative_input_hash,  # checker input seal (B2.3)
                    scanned_snapshot,  # explicit audit field (B2.3)
                ],
            )
            executions[spec.check_id.value] = execution_id
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return executions
