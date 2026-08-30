"""Formal artifact validation boundary (R4-B2, audit 20260830).

The pre-B2 world: ``record_artifact_validation()`` accepted
caller-supplied ``identity_fallback_count`` / ``blocking_dq_count``
and appended a PASS-shaped ledger row WITHOUT executing any artifact
validation - the same structural bypass shape R4-B1 closed for
capability approval.

B2-01: ``validate_artifact_for_publish`` is the ONE formal artifact
validation execution boundary. It resolves the artifact identity from
the registry, RE-VERIFIES the physical component bytes against the
registered identity, executes the typed required-check contract,
DERIVES the counts from the persisted DQ-finding facts, seals the
exact artifact/component identity into the ledger row and a persisted
hash-bound report, and returns the artifact_validation_id. The ledger
INSERT lives INSIDE this function - there is no caller-facing
callable that can write a validation row.

B2-02: the required checks are typed
(:class:`ArtifactValidationCheckId`); a missing / failing /
NOT_TESTABLE required check makes the record non-eligible (publish
fail-closes on it). Aggregate counts are report SUMMARY, never the
eligibility truth.

B2-03/B2-04: the validation seals
``artifact_manifest_hash``/``component_manifest_hash`` (stable hash of
the full component identity) / ``validation_contract_hash`` and
persists ``validation/<artifact_validation_id>.json``; the ledger row
binds ``report_uri`` + ``report_hash`` so publish can machine-verify
the PASS still describes the CURRENT artifact bytes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.storage.atomic_files import write_file_atomic

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

__all__ = [
    "ArtifactValidationError",
    "ArtifactValidationCheckId",
    "CheckStatus",
    "REQUIRED_VALIDATION_CHECKS",
    "VALIDATION_CONTRACT_VERSION",
    "compute_component_manifest_hash",
    "record_artifact_dq_finding",
    "validation_contract_hash",
    "validate_artifact_for_publish",
]


class ArtifactValidationError(RuntimeError):
    """The formal artifact validation boundary contract was violated."""


class ArtifactValidationCheckId(StrEnum):
    """B2-02: the typed required-check contract."""

    ARTIFACT_MANIFEST_INTEGRITY = "ARTIFACT_MANIFEST_INTEGRITY"
    COMPONENT_EXISTENCE = "COMPONENT_EXISTENCE"
    COMPONENT_CONTENT_HASH = "COMPONENT_CONTENT_HASH"
    COMPONENT_SCHEMA_HASH = "COMPONENT_SCHEMA_HASH"
    COMPONENT_ROW_COUNT = "COMPONENT_ROW_COUNT"
    FEATURE_FAMILY_COVERAGE = "FEATURE_FAMILY_COVERAGE"
    FEATURE_SET_VERSION_MATCH = "FEATURE_SET_VERSION_MATCH"
    DATA_SNAPSHOT_BINDING = "DATA_SNAPSHOT_BINDING"
    IDENTITY_FALLBACK_ZERO = "IDENTITY_FALLBACK_ZERO"
    BLOCKING_DQ_ZERO = "BLOCKING_DQ_ZERO"


#: every required check must appear (and PASS) in a publish-eligible
#: validation report - missing/unknown checks can never substitute.
REQUIRED_VALIDATION_CHECKS: tuple[ArtifactValidationCheckId, ...] = tuple(
    ArtifactValidationCheckId,
)

#: B2-02: the contract identity itself. Changing the required-check
#: set / seal fields changes this hash and invalidates prior seals.
VALIDATION_CONTRACT_VERSION = "b2-exact-v1"

_CONTRACT_TEXT = json.dumps(
    {
        "contract_version": VALIDATION_CONTRACT_VERSION,
        "required_checks": [c.value for c in REQUIRED_VALIDATION_CHECKS],
        "seal_fields": [
            "feature_artifact_set_id",
            "artifact_manifest_hash",
            "component_manifest_hash",
            "validation_contract_hash",
            "validator_code_commit",
            "required_checks_hash",
        ],
        "count_source": "meta_artifact_dq_finding (append-only facts)",
    },
    sort_keys=True,
    separators=(",", ":"),
)


def validation_contract_hash() -> str:
    """Stable identity of the validation contract (B2-03 seal input)."""
    return hashlib.sha256(_CONTRACT_TEXT.encode("utf-8")).hexdigest()


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTABLE = "NOT_TESTABLE"  # unprovable == blocking (fail closed)


@dataclass(frozen=True)
class _CheckOutcome:
    check_id: ArtifactValidationCheckId
    status: CheckStatus
    detail: str


#: finding classes the DQ fact table accepts (validator count source)
_DQ_FINDING_CLASSES = ("IDENTITY_FALLBACK", "BLOCKING_DQ")

# arrow -> duckdb type-name mapping for parquet schema re-verification
_ARROW_TO_DUCKDB_TYPE = {
    "string": "VARCHAR",
    "large_string": "VARCHAR",
    "date32[day]": "DATE",
    "double": "DOUBLE",
    "float": "FLOAT",
    "int64": "BIGINT",
    "int32": "INTEGER",
    "bool": "BOOLEAN",
    "timestamp[us]": "TIMESTAMP",
}


def _parquet_schema_text(schema: Any) -> str:
    """Canonical 'name TYPE, ...' text of a parquet (arrow) schema -
    the SAME formula the registration-time schema_hash used for the
    skeleton schema texts."""
    parts = []
    for field in schema:
        arrow_type = str(field.type)
        duck_type = _ARROW_TO_DUCKDB_TYPE.get(arrow_type)
        if duck_type is None:
            msg = f"unmapped arrow type {arrow_type!r} - schema hash not verifiable"
            raise ArtifactValidationError(msg)
        parts.append(f"{field.name} {duck_type}")
    return ", ".join(parts)


def _component_rows(conn: DuckDBPyConnection, artifact_set_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT layer, feature_family, feature_family_version, partition_key, "
        "file_uri, content_hash, schema_hash, row_count "
        "FROM meta_feature_artifact_component WHERE feature_artifact_set_id = ? "
        "ORDER BY file_uri",
        [artifact_set_id],
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


def compute_component_manifest_hash(
    components: list[dict[str, Any]],
) -> str:
    """B2-03: stable hash of the FULL component identity (sorted by
    the identity tuple, canonical JSON). Covers file_uri, content /
    schema hashes, row_count, feature family/version, layer and
    partition key - any component addition/removal/change alters it."""
    payload = sorted(
        (dict(component) for component in components),
        key=lambda c: (
            str(c["file_uri"]),
            str(c["content_hash"]),
            str(c["schema_hash"]),
            int(c["row_count"]),
            str(c["feature_family"]),
            str(c["feature_family_version"]),
            str(c["layer"]),
            str(c["partition_key"] or ""),
        ),
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_artifact_dq_finding(
    conn: DuckDBPyConnection,
    *,
    feature_artifact_set_id: str,
    finding_class: str,
    detail: str | None = None,
) -> str:
    """APPEND a DQ finding FACT (B2-01 count source).

    This writes BAD facts only: a caller can make validation stricter
    (more findings -> higher derived counts -> publish blocked) but can
    NEVER fabricate a PASS through this path. The completeness of the
    fact stream is the feature-pipeline's own governance chain; the
    validator merely derives the counts from what was persisted."""
    if finding_class not in _DQ_FINDING_CLASSES:
        msg = (
            f"finding_class {finding_class!r} not in {_DQ_FINDING_CLASSES} - "
            "the DQ fact table records validation count sources only"
        )
        raise ArtifactValidationError(msg)
    finding_id = f"dqf-{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO meta_artifact_dq_finding VALUES (?, ?, ?, ?, ?)",
        [
            finding_id,
            feature_artifact_set_id,
            finding_class,
            datetime.now(UTC),
            detail,
        ],
    )
    return finding_id


def _required_checks_hash(outcomes: list[_CheckOutcome]) -> str:
    payload = [{"check_id": o.check_id.value, "status": o.status.value} for o in outcomes]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_artifact_for_publish(
    conn: DuckDBPyConnection,
    *,
    data_root: Path,
    feature_artifact_set_id: str,
    validator_code_commit: str,
    validation_version: str = VALIDATION_CONTRACT_VERSION,
) -> str:
    """B2-01: the ONE formal artifact validation execution boundary.

    Executes the typed required-check contract against the ACTUAL
    artifact registry + physical component bytes, derives the counts
    from the persisted DQ-finding facts, seals the exact
    artifact/component identity, persists the hash-bound report, and
    appends the ledger row INLINE (there is no separate
    caller-reachable persistence helper). Returns the new
    artifact_validation_id.

    The record is publish-eligible ONLY if every required check PASSed;
    a FAIL / NOT_TESTABLE record is still appended (honest history) but
    publish fail-closes on it."""
    import pyarrow.parquet as pq

    from ashare_state.storage.atomic_files import file_sha256, schema_hash_of

    data_root = Path(data_root)
    if not validator_code_commit:
        msg = "validator_code_commit is required (the seal records WHO validated)"
        raise ArtifactValidationError(msg)

    # -------------------------------------------------- resolve identity
    art = conn.execute(
        "SELECT data_snapshot_id, feature_set_version, artifact_manifest_hash, status "
        "FROM meta_feature_artifact_set WHERE feature_artifact_set_id = ?",
        [feature_artifact_set_id],
    ).fetchone()
    if art is None:
        msg = f"feature_artifact_set {feature_artifact_set_id} not registered"
        raise ArtifactValidationError(msg)
    data_snapshot_id, feature_set_version, artifact_manifest_hash, _status = art
    components = _component_rows(conn, feature_artifact_set_id)

    outcomes: list[_CheckOutcome] = []

    # 1. ARTIFACT_MANIFEST_INTEGRITY --------------------------------
    # the registration-time manifest identity exists and is sealed as-is;
    # every component identity is re-verified item by item below, and the
    # publish-time final recheck re-derives BOTH hashes from the CURRENT
    # registry and compares them to this seal.
    if artifact_manifest_hash and components:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.ARTIFACT_MANIFEST_INTEGRITY,
                CheckStatus.PASS,
                f"registered manifest {str(artifact_manifest_hash)[:16]}... "
                f"over {len(components)} components (sealed)",
            )
        )
    else:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.ARTIFACT_MANIFEST_INTEGRITY,
                CheckStatus.FAIL,
                "artifact set has no registered manifest hash or no components",
            )
        )

    # 2-5. COMPONENT_*: physical bytes vs registered identity -------
    missing: list[str] = []
    content_bad: list[str] = []
    schema_bad: list[str] = []
    rows_bad: list[str] = []
    for comp in components:
        uri = str(comp["file_uri"])
        path = data_root / uri
        if not path.is_file():
            missing.append(uri)
            continue
        actual_hash = file_sha256(path)
        if actual_hash != str(comp["content_hash"]):
            content_bad.append(uri)
        try:
            parquet_schema = pq.read_schema(path)
            schema_text = _parquet_schema_text(parquet_schema)
        except Exception:  # noqa: BLE001 - unreadable parquet = unprovable
            schema_bad.append(uri)
            rows_bad.append(uri)
            continue
        if schema_hash_of(schema_text) != str(comp["schema_hash"]):
            schema_bad.append(uri)
        try:
            num_rows = pq.read_metadata(path).num_rows
        except Exception:  # noqa: BLE001
            rows_bad.append(uri)
            continue
        if int(num_rows) != int(comp["row_count"]):
            rows_bad.append(uri)

    outcomes.append(
        _CheckOutcome(
            ArtifactValidationCheckId.COMPONENT_EXISTENCE,
            CheckStatus.PASS if not missing else CheckStatus.FAIL,
            "all component files exist"
            if not missing
            else f"missing component files: {missing[:5]}",
        )
    )
    outcomes.append(
        _CheckOutcome(
            ArtifactValidationCheckId.COMPONENT_CONTENT_HASH,
            CheckStatus.PASS if not content_bad else CheckStatus.FAIL,
            "every component's bytes hash to the registered content_hash"
            if not content_bad
            else f"content hash mismatch: {content_bad[:5]}",
        )
    )
    if schema_bad and any(uri not in missing for uri in schema_bad):
        # distinguish unreadable/mismatched from simply missing
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.COMPONENT_SCHEMA_HASH,
                CheckStatus.FAIL,
                f"schema hash mismatch or unreadable parquet: {schema_bad[:5]}",
            )
        )
    elif missing:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.COMPONENT_SCHEMA_HASH,
                CheckStatus.NOT_TESTABLE,
                "component files missing - schema unprovable",
            )
        )
    else:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.COMPONENT_SCHEMA_HASH,
                CheckStatus.PASS,
                "every component's parquet schema hashes to the registered schema_hash",
            )
        )
    if rows_bad and any(uri not in missing for uri in rows_bad):
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.COMPONENT_ROW_COUNT,
                CheckStatus.FAIL,
                f"row count mismatch or unreadable parquet: {rows_bad[:5]}",
            )
        )
    elif missing:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.COMPONENT_ROW_COUNT,
                CheckStatus.NOT_TESTABLE,
                "component files missing - row counts unprovable",
            )
        )
    else:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.COMPONENT_ROW_COUNT,
                CheckStatus.PASS,
                "every component's parquet row count equals the registered row_count",
            )
        )

    # 6. FEATURE_FAMILY_COVERAGE -----------------------------------
    members = {
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT feature_id, feature_version FROM meta_feature_set_member "
            "WHERE feature_set_version = ?",
            [feature_set_version],
        ).fetchall()
    }
    covered = {(str(c["feature_family"]), str(c["feature_family_version"])) for c in components}
    if members and covered == members:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.FEATURE_FAMILY_COVERAGE,
                CheckStatus.PASS,
                f"components cover every member of feature set {feature_set_version}",
            )
        )
    else:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.FEATURE_FAMILY_COVERAGE,
                CheckStatus.FAIL,
                f"coverage mismatch: members={sorted(members)}, covered={sorted(covered)}",
            )
        )

    # 7. FEATURE_SET_VERSION_MATCH ---------------------------------
    fset = conn.execute(
        "SELECT 1 FROM meta_feature_set WHERE feature_set_version = ?",
        [feature_set_version],
    ).fetchone()
    outcomes.append(
        _CheckOutcome(
            ArtifactValidationCheckId.FEATURE_SET_VERSION_MATCH,
            CheckStatus.PASS if fset is not None else CheckStatus.FAIL,
            f"feature set {feature_set_version} registered"
            if fset is not None
            else f"feature set {feature_set_version} NOT registered",
        )
    )

    # 8. DATA_SNAPSHOT_BINDING --------------------------------------
    snap = conn.execute(
        "SELECT status FROM meta_data_snapshot WHERE data_snapshot_id = ?",
        [data_snapshot_id],
    ).fetchone()
    if snap is not None and snap[0] == "DATA_VALIDATED":
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.DATA_SNAPSHOT_BINDING,
                CheckStatus.PASS,
                f"artifact bound to DATA_VALIDATED snapshot {data_snapshot_id}",
            )
        )
    else:
        outcomes.append(
            _CheckOutcome(
                ArtifactValidationCheckId.DATA_SNAPSHOT_BINDING,
                CheckStatus.FAIL,
                f"snapshot {data_snapshot_id} missing or not DATA_VALIDATED",
            )
        )

    # 9-10. IDENTITY_FALLBACK_ZERO / BLOCKING_DQ_ZERO --------------
    # B2-01: counts are DERIVED from the persisted DQ facts, never inputs.
    fallback_row = conn.execute(
        "SELECT count(*) FROM meta_artifact_dq_finding "
        "WHERE feature_artifact_set_id = ? AND finding_class = 'IDENTITY_FALLBACK'",
        [feature_artifact_set_id],
    ).fetchone()
    fallback_count = int(fallback_row[0]) if fallback_row else 0
    dq_row = conn.execute(
        "SELECT count(*) FROM meta_artifact_dq_finding "
        "WHERE feature_artifact_set_id = ? AND finding_class = 'BLOCKING_DQ'",
        [feature_artifact_set_id],
    ).fetchone()
    blocking_dq_count = int(dq_row[0]) if dq_row else 0
    outcomes.append(
        _CheckOutcome(
            ArtifactValidationCheckId.IDENTITY_FALLBACK_ZERO,
            CheckStatus.PASS if fallback_count == 0 else CheckStatus.FAIL,
            f"identity fallback findings: {fallback_count}",
        )
    )
    outcomes.append(
        _CheckOutcome(
            ArtifactValidationCheckId.BLOCKING_DQ_ZERO,
            CheckStatus.PASS if blocking_dq_count == 0 else CheckStatus.FAIL,
            f"blocking DQ findings: {blocking_dq_count}",
        )
    )

    # ------------------------------------------------- seal + report
    component_manifest_hash = compute_component_manifest_hash(components)
    checks_hash = _required_checks_hash(outcomes)
    validation_id = f"val-{uuid.uuid4()}"
    now = datetime.now(UTC)
    contract_hash = validation_contract_hash()

    report_doc = {
        "artifact_validation_id": validation_id,
        "feature_artifact_set_id": feature_artifact_set_id,
        "validation_version": validation_version,
        "validation_contract_hash": contract_hash,
        "validator_code_commit": validator_code_commit,
        "artifact_manifest_hash": str(artifact_manifest_hash or ""),
        "component_manifest_hash": component_manifest_hash,
        "required_checks_hash": checks_hash,
        "checks": [
            {"check_id": o.check_id.value, "status": o.status.value, "detail": o.detail}
            for o in outcomes
        ],
        "summary": {
            "identity_fallback_count": fallback_count,
            "blocking_dq_count": blocking_dq_count,
            "checks_passed": sum(1 for o in outcomes if o.status is CheckStatus.PASS),
            "checks_failed": sum(1 for o in outcomes if o.status is CheckStatus.FAIL),
            "checks_not_testable": sum(1 for o in outcomes if o.status is CheckStatus.NOT_TESTABLE),
        },
        "validated_at": now.isoformat(),
    }
    report_bytes = json.dumps(report_doc, sort_keys=True, indent=2).encode("utf-8")
    report_uri = f"validation/{validation_id}.json"
    report_hash = write_file_atomic(data_root / report_uri, report_bytes)

    # --------------------------------------- inline ledger persistence
    # B2-01: the INSERT lives HERE - no separate callable can receive
    # caller-built counts/results and write a validation row.
    conn.execute(
        "INSERT INTO meta_artifact_validation "
        "(artifact_validation_id, feature_artifact_set_id, validation_version, "
        "validator_code_commit, identity_fallback_count, blocking_dq_count, "
        "validated_at, detail, artifact_manifest_hash, component_manifest_hash, "
        "validation_contract_hash, report_uri, report_hash, required_checks_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            validation_id,
            feature_artifact_set_id,
            validation_version,
            validator_code_commit,
            fallback_count,
            blocking_dq_count,
            now,
            f"checks_hash={checks_hash[:16]}...",
            str(artifact_manifest_hash or ""),
            component_manifest_hash,
            contract_hash,
            report_uri,
            report_hash,
            checks_hash,
        ],
    )
    return validation_id
