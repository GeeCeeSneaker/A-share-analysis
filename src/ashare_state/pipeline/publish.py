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

R4-B2 (audit 20260830) Publish Validation Exactness:

- validation records are written ONLY by the formal boundary
  ``pipeline.artifact_validation.validate_artifact_for_publish`` (the old
  caller-facing count-writer ``record_artifact_validation`` is GONE);
- the publish-critical validation recheck (report bytes hash, ledger
  identity, exact artifact/component seal, required-check completeness) runs
  as a preflight before the short publish transaction and returns a
  ``PublishValidationSeal``; the transaction consumes that seal again against
  current DB heads and immutable registry identities;
- the latest-head policy is deterministic (validated_at DESC,
  artifact_validation_id DESC): a newer FAIL record makes an older PASS
  non-publishable, and legacy rows without the B2 seal require
  revalidation.

R4-B2.1 closures (audit 20260830 19:13):

- **P0-02 full seal consumption**: the recheck reads the COMPLETE seal
  from the ledger row and cross-verifies it against the persisted
  report AND the CURRENT contract - validation_contract_hash (ledger
  == report == current), required_checks_hash (ledger == report ==
  recomputed over the report's check set, duplicates rejected),
  validator_code_commit (ledger == report, non-empty),
  validation_version (ledger == report == the current supported
  version). "Wrote the seal" is now "the seal is a correctness input".
- **P0-03 short transaction boundary**: expensive report parsing, physical
  artifact/component hashing and DQ-input validation happen before
  ``BEGIN``. ``_consume_b2_seal`` then re-reads the validation head,
  component registry, artifact manifest identity and small DQ completion
  proofs inside the transaction; the write consumes only the re-bound values.
  This keeps the transaction short without treating an unbound preflight as
  authoritative.
- The preflight-to-transaction hand-off assumes registered artifact and
  component files are immutable once published in their registry. A full
  deep audit remains an explicit read-only operation; it is not repeated in
  the publish transaction.
- **P0-04 logical-URI confinement**: every registry file_uri and the
  validation report_uri resolve through the frozen
  ``physical_from_logical_uri`` helper - escaped/absolute/drive/
  backslash/alias URIs fail closed before any filesystem read outside
  the data root.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.storage.paths import physical_from_logical_uri

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


class PublishError(RuntimeError):
    """Base error for publish contract violations."""


class PublishStateError(PublishError):
    """Preconditions for publishing are not met."""


@dataclass(frozen=True)
class PublishValidationSeal:
    """Small DB-bound hand-off from validation preflight to publish."""

    feature_artifact_set_id: str
    validation_id: str
    identity_fallback_count: int
    blocking_dq_count: int
    report_uri: str
    report_hash: str
    artifact_manifest_hash: str
    component_manifest_hash: str
    validation_contract_hash: str
    required_checks_hash: str
    validator_code_commit: str
    validation_version: str
    dq_execution_seal_hash: str


def _dq_execution_seal_hash(seals: list[dict[str, Any]]) -> str:
    """Hash the small set of DQ completion-proof rows, not data artifacts."""
    canonical = json.dumps(
        sorted(seals, key=lambda seal: str(seal.get("check_id") or "")),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _b2_recheck(
    conn: DuckDBPyConnection,
    *,
    data_root: Path,
    feature_artifact_set_id: str,
) -> PublishValidationSeal:
    """B2-05 + R4-B2.1 P0-02/P0-04: prevalidate the publish seal.

    This is deliberately a preflight operation.  It performs the expensive
    report parsing, component hashing and current DQ-input resolution before
    the short publication transaction.  ``_consume_b2_seal`` then checks the
    returned DB-bound identity inside that transaction.  Registered data
    files are immutable; a deep physical re-audit remains an explicit audit
    operation.

    Reads the COMPLETE seal from the ledger row and cross-verifies it
    against the persisted report AND the CURRENT contract. Returns the
    artifact_validation_id the publish will bind. Raises
    PublishStateError (fail closed) on:

    - no validation record at all;
    - legacy record without the B2 exact seal - requires revalidation;
    - report file missing / bytes tampered (sha256 != ledger report_hash);
    - report/ledger identity mismatch (id or artifact set);
    - validation_contract_hash: ledger != report, or != CURRENT contract
      hash (a semantic contract change invalidates old seals even when
      the check IDs are unchanged);
    - required_checks_hash: ledger != report, or != recomputed hash of
      the report's check set (a status change without re-sealing is
      caught), or the report contains duplicate check ids;
    - validator_code_commit: ledger != report or empty;
    - validation_version: ledger != report, or != the current supported
      validation contract version (no silent grandfather);
    - sealed artifact manifest != CURRENT registered manifest;
    - sealed component manifest != manifest re-derived from the CURRENT
      component registry (component added/removed/changed);
    - required-check set incomplete or any check not PASS (a DQ check
      with no positive execution proof is NOT_TESTABLE here);
    - derived counts non-zero;
    - any component file_uri / the report_uri violating the frozen
      logical-URI confinement, or a component file missing / its bytes
      no longer hashing to the registered content_hash.
    """
    from ashare_state.pipeline.artifact_validation import (
        REQUIRED_VALIDATION_CHECKS,
        VALIDATION_CONTRACT_VERSION,
        compute_component_manifest_hash,
        validation_contract_hash,
    )

    validation = conn.execute(
        "SELECT artifact_validation_id, identity_fallback_count, blocking_dq_count, "
        "report_uri, report_hash, artifact_manifest_hash, component_manifest_hash, "
        "validation_contract_hash, required_checks_hash, validator_code_commit, "
        "validation_version "
        "FROM meta_artifact_validation WHERE feature_artifact_set_id = ? "
        "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1",
        [feature_artifact_set_id],
    ).fetchone()
    if validation is None:
        msg = (
            "ARTIFACT_VALIDATION_REQUIRED violated: no meta_artifact_validation "
            f"record for {feature_artifact_set_id}; publish is blocked until the "
            "formal artifact validator (validate_artifact_for_publish) records "
            "a validation for this artifact set"
        )
        raise PublishStateError(msg)
    (
        validation_id,
        fallback_count,
        dq_count,
        report_uri,
        report_hash,
        seal_artifact_hash,
        seal_component_hash,
        ledger_contract_hash,
        ledger_checks_hash,
        ledger_validator_commit,
        ledger_validation_version,
    ) = validation
    # B2-03: legacy pre-B2 rows carry no exact seal - they can never be
    # publish-eligible without revalidation through the formal boundary.
    if not report_uri or not report_hash:
        msg = (
            "ARTIFACT_VALIDATION_SEAL_REQUIRED violated: the latest validation "
            f"record {validation_id} for {feature_artifact_set_id} has no B2 "
            "exact seal (legacy pre-B2 row) - revalidate the artifact through "
            "validate_artifact_for_publish before publishing"
        )
        raise PublishStateError(msg)
    # B2-04 + P0-04: report bytes must still hash to the ledger-bound
    # value; the URI resolves through the frozen confinement helper.
    try:
        report_path = physical_from_logical_uri(Path(data_root), str(report_uri))
    except Exception as exc:  # noqa: BLE001 - confinement violation
        msg = (
            "ARTIFACT_VALIDATION_REPORT_URI_INVALID violated: report uri "
            f"{report_uri!r} is not a canonical logical uri ({exc})"
        )
        raise PublishStateError(msg) from exc
    if not report_path.is_file():
        msg = (
            "ARTIFACT_VALIDATION_REPORT_MISSING violated: validation report "
            f"{report_path} not found (bound to {validation_id})"
        )
        raise PublishStateError(msg)
    report_bytes = report_path.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != str(report_hash):
        msg = (
            "ARTIFACT_VALIDATION_REPORT_TAMPERED violated: report bytes for "
            f"{validation_id} do not match the ledger report_hash"
        )
        raise PublishStateError(msg)
    try:
        report = json.loads(report_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"ARTIFACT_VALIDATION_REPORT_TAMPERED violated: unreadable report ({exc})"
        raise PublishStateError(msg) from exc
    if report.get("artifact_validation_id") != str(validation_id):
        msg = (
            "ARTIFACT_VALIDATION_IDENTITY violated: report artifact_validation_id "
            f"{report.get('artifact_validation_id')!r} != ledger {validation_id!r}"
        )
        raise PublishStateError(msg)
    if report.get("feature_artifact_set_id") != feature_artifact_set_id:
        msg = (
            "ARTIFACT_VALIDATION_IDENTITY violated: report belongs to artifact "
            f"set {report.get('feature_artifact_set_id')!r}, not "
            f"{feature_artifact_set_id!r}"
        )
        raise PublishStateError(msg)

    # ------------------------- P0-02: FULL seal cross-verification
    current_contract_hash = validation_contract_hash()
    if (
        str(ledger_contract_hash) != current_contract_hash
        or report.get("validation_contract_hash") != current_contract_hash
    ):
        msg = (
            "ARTIFACT_VALIDATION_CONTRACT_STALE violated: the validation seal's "
            f"contract hash (ledger={str(ledger_contract_hash)[:16]}..., "
            f"report={str(report.get('validation_contract_hash'))[:16]}...) does "
            f"not match the CURRENT validation contract {current_contract_hash[:16]}... "
            "- the validation contract changed after this validation; "
            "revalidation required (audit R4-B2.1 P0-02)"
        )
        raise PublishStateError(msg)
    report_checks = report.get("checks", [])
    report_check_ids = [c.get("check_id") for c in report_checks]
    if len(report_check_ids) != len(set(report_check_ids)):
        msg = (
            "ARTIFACT_VALIDATION_DUPLICATE_CHECKS violated: the report contains "
            "duplicate check ids - the typed check set must be exact "
            "(audit R4-B2.1 P0-02)"
        )
        raise PublishStateError(msg)
    recomputed_checks_hash = hashlib.sha256(
        json.dumps(
            [{"check_id": c.get("check_id"), "status": c.get("status")} for c in report_checks],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if str(ledger_checks_hash) != str(recomputed_checks_hash) or report.get(
        "required_checks_hash"
    ) != str(recomputed_checks_hash):
        msg = (
            "ARTIFACT_VALIDATION_CHECKS_HASH violated: the required-checks hash "
            f"(ledger={str(ledger_checks_hash)[:16]}..., report="
            f"{str(report.get('required_checks_hash'))[:16]}...) != hash recomputed "
            f"over the report's check set {recomputed_checks_hash[:16]}... - the "
            "checks were altered after sealing (audit R4-B2.1 P0-02)"
        )
        raise PublishStateError(msg)
    if not str(ledger_validator_commit or "") or report.get("validator_code_commit") != str(
        ledger_validator_commit
    ):
        msg = (
            "ARTIFACT_VALIDATION_PROVENANCE violated: validator_code_commit "
            f"ledger={ledger_validator_commit!r} vs report="
            f"{report.get('validator_code_commit')!r} (audit R4-B2.1 P0-02)"
        )
        raise PublishStateError(msg)
    if (
        str(ledger_validation_version) != VALIDATION_CONTRACT_VERSION
        or report.get("validation_version") != VALIDATION_CONTRACT_VERSION
    ):
        msg = (
            "ARTIFACT_VALIDATION_VERSION_STALE violated: validation_version "
            f"(ledger={ledger_validation_version!r}, report="
            f"{report.get('validation_version')!r}) != the current supported "
            f"contract version {VALIDATION_CONTRACT_VERSION!r} (audit "
            "R4-B2.1 P0-02, no silent grandfather)"
        )
        raise PublishStateError(msg)

    # --------------------------------- B2-03: identity vs registry
    current_row = conn.execute(
        "SELECT artifact_manifest_hash FROM meta_feature_artifact_set "
        "WHERE feature_artifact_set_id = ?",
        [feature_artifact_set_id],
    ).fetchone()
    current_artifact_hash = str(current_row[0]) if current_row else ""
    if current_artifact_hash != str(seal_artifact_hash) or report.get(
        "artifact_manifest_hash"
    ) != str(seal_artifact_hash):
        msg = (
            "ARTIFACT_IDENTITY_CHANGED violated: sealed artifact manifest "
            f"{str(seal_artifact_hash)[:16]}... != current registered manifest "
            f"{current_artifact_hash[:16]}... - the artifact changed after "
            "validation; revalidation required"
        )
        raise PublishStateError(msg)
    components = conn.execute(
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
    component_rows = [dict(zip(keys, r, strict=True)) for r in components]
    current_component_hash = compute_component_manifest_hash(component_rows)
    if current_component_hash != str(seal_component_hash) or report.get(
        "component_manifest_hash"
    ) != str(seal_component_hash):
        msg = (
            "ARTIFACT_COMPONENTS_CHANGED violated: sealed component manifest "
            f"{str(seal_component_hash)[:16]}... != manifest re-derived from "
            f"the CURRENT registry {current_component_hash[:16]}... - a "
            "component was added/removed/changed after validation; "
            "revalidation required"
        )
        raise PublishStateError(msg)
    # B2-02: required-check completeness + all PASS
    report_checks_by_id = {c.get("check_id"): c.get("status") for c in report_checks}
    required_ids = {c.value for c in REQUIRED_VALIDATION_CHECKS}
    missing = required_ids - set(report_checks_by_id)
    not_pass = sorted(
        cid
        for cid, status in report_checks_by_id.items()
        if cid in required_ids and status != "PASS"
    )
    if missing or not_pass:
        msg = (
            "ARTIFACT_VALIDATION_CHECKS violated: required check set incomplete "
            f"or not PASS (missing={sorted(missing)}, not_pass={not_pass}) for "
            f"{validation_id}"
        )
        raise PublishStateError(msg)
    # R4-B2.3 (audit section 3): the DQ authoritative-input seal must
    # still describe the CURRENT inputs - the validation report binds
    # the execution seals it consumed; a checker input (identity
    # registry / snapshot DQ facts) that changed AFTER validation makes
    # the whole report stale (fail closed inside the publish
    # transaction). This runs AFTER the physical bytes verification so
    # a missing/tampered component reports its specific failure first.
    report_seals = {
        str(seal.get("check_id")): str(seal.get("authoritative_input_hash") or "")
        for seal in report.get("dq_execution_seals", [])
    }
    required_dq_check_ids = {
        c.value for c in REQUIRED_VALIDATION_CHECKS if c.value.endswith("_ZERO")
    }
    if set(report_seals) != required_dq_check_ids or any(not v for v in report_seals.values()):
        msg = (
            "ARTIFACT_VALIDATION_DQ_SEAL_INCOMPLETE violated: the validation "
            f"report for {validation_id} does not bind a complete set of DQ "
            "execution input seals (audit R4-B2.3 section 3)"
        )
        raise PublishStateError(msg)
    # counts remain the system invariant gate (validator-derived values)
    if int(fallback_count) != 0 or int(dq_count) != 0:
        msg = (
            "ARTIFACT_VALIDATION_GATE violated: "
            f"identity_fallback_count={fallback_count}, blocking_dq_count={dq_count}; "
            "fallback identities and blocking DQ findings may never be PUBLISHED"
        )
        raise PublishStateError(msg)
    # B2-05 + P0-04: the physical bytes must STILL hash to the registered
    # content_hash - a component replaced on disk after validation (with
    # the registry row untouched) fails closed here; every file_uri
    # resolves through the frozen logical-URI confinement helper.
    from ashare_state.storage.atomic_files import file_sha256

    for component in component_rows:
        uri = str(component["file_uri"])
        try:
            comp_path = physical_from_logical_uri(Path(data_root), uri)
        except Exception as exc:  # noqa: BLE001 - confinement violation
            msg = (
                "ARTIFACT_COMPONENT_URI_INVALID violated: component file_uri "
                f"{uri!r} is not a canonical logical uri ({exc}) - frozen P0-4 "
                "confinement (audit R4-B2.1 P0-04)"
            )
            raise PublishStateError(msg) from exc
        if not comp_path.is_file():
            msg = (
                "ARTIFACT_COMPONENT_MISSING violated: component file "
                f"{comp_path} of {feature_artifact_set_id} is missing at "
                "publish time"
            )
            raise PublishStateError(msg)
        if file_sha256(comp_path) != str(component["content_hash"]):
            msg = (
                "ARTIFACT_COMPONENT_TAMPERED violated: component file "
                f"{comp_path} bytes do not hash to the registered "
                "content_hash - the file changed after validation; "
                "revalidation required"
            )
            raise PublishStateError(msg)
    from ashare_state.pipeline.artifact_dq_scan import (
        current_authoritative_input_fingerprints,
    )

    try:
        current_input_seals = current_authoritative_input_fingerprints(
            conn, data_root=Path(data_root), feature_artifact_set_id=feature_artifact_set_id
        )
    except Exception as exc:  # noqa: BLE001 - unresolvable = stale/unprovable
        msg = (
            "ARTIFACT_DQ_INPUT_UNRESOLVABLE violated: the current checker "
            f"authoritative input cannot be resolved for {feature_artifact_set_id} "
            f"({exc}) - the DQ input seal cannot be verified; rescan and "
            "revalidation required (audit R4-B2.3 section 3)"
        )
        raise PublishStateError(msg) from exc
    stale_inputs = sorted(
        check_id
        for check_id, seal in report_seals.items()
        if current_input_seals.get(check_id, "") != seal
    )
    if stale_inputs:
        msg = (
            "ARTIFACT_DQ_INPUT_STALE violated: the checker authoritative "
            f"inputs changed after validation (stale checks: {stale_inputs}) - "
            "rescan and revalidation required before publish (audit "
            "R4-B2.3 section 3)"
        )
        raise PublishStateError(msg)
    return PublishValidationSeal(
        feature_artifact_set_id=feature_artifact_set_id,
        validation_id=str(validation_id),
        identity_fallback_count=int(fallback_count),
        blocking_dq_count=int(dq_count),
        report_uri=str(report_uri),
        report_hash=str(report_hash),
        artifact_manifest_hash=str(seal_artifact_hash),
        component_manifest_hash=str(seal_component_hash),
        validation_contract_hash=str(ledger_contract_hash),
        required_checks_hash=str(ledger_checks_hash),
        validator_code_commit=str(ledger_validator_commit),
        validation_version=str(ledger_validation_version),
        dq_execution_seal_hash=_dq_execution_seal_hash(
            [
                {
                    "check_id": str(item.get("check_id") or ""),
                    "execution_id": str(item.get("execution_id") or ""),
                    "scan_contract_version": str(item.get("scan_contract_version") or ""),
                    "producer": str(item.get("producer") or ""),
                    "authoritative_input_hash": str(item.get("authoritative_input_hash") or ""),
                    "scanned_component_manifest_hash": str(
                        item.get("scanned_component_manifest_hash") or ""
                    ),
                    "scanned_data_snapshot_id": str(item.get("scanned_data_snapshot_id") or ""),
                }
                for item in report.get("dq_execution_seals", [])
            ]
        ),
    )


def _consume_b2_seal(
    conn: DuckDBPyConnection,
    *,
    seal: PublishValidationSeal,
) -> None:
    """Consume a prevalidated seal using only current DB state.

    This is the transaction-side half of B2.  It intentionally does not read
    or hash report/component files: the formal validator already produced the
    physical seal, and the registry identities/proof rows are re-read here to
    close a DB-level change between preflight and commit.
    """
    from ashare_state.pipeline.artifact_validation import (
        REQUIRED_VALIDATION_CHECKS,
        compute_component_manifest_hash,
    )

    validation = conn.execute(
        "SELECT artifact_validation_id, identity_fallback_count, blocking_dq_count, "
        "report_uri, report_hash, artifact_manifest_hash, component_manifest_hash, "
        "validation_contract_hash, required_checks_hash, validator_code_commit, "
        "validation_version "
        "FROM meta_artifact_validation WHERE feature_artifact_set_id = ? "
        "ORDER BY validated_at DESC, artifact_validation_id DESC LIMIT 1",
        [seal.feature_artifact_set_id],
    ).fetchone()
    expected_validation = (
        seal.validation_id,
        seal.identity_fallback_count,
        seal.blocking_dq_count,
        seal.report_uri,
        seal.report_hash,
        seal.artifact_manifest_hash,
        seal.component_manifest_hash,
        seal.validation_contract_hash,
        seal.required_checks_hash,
        seal.validator_code_commit,
        seal.validation_version,
    )
    if validation is None or tuple(validation) != expected_validation:
        raise PublishStateError(
            "ARTIFACT_VALIDATION_PRECHECK_STALE violated: the validation head "
            f"for {seal.feature_artifact_set_id} changed after physical preflight; "
            "revalidate before publish"
        )

    current_artifact = conn.execute(
        "SELECT artifact_manifest_hash FROM meta_feature_artifact_set "
        "WHERE feature_artifact_set_id = ?",
        [seal.feature_artifact_set_id],
    ).fetchone()
    current_artifact_hash = str(current_artifact[0]) if current_artifact else ""
    if current_artifact_hash != seal.artifact_manifest_hash:
        raise PublishStateError(
            "ARTIFACT_IDENTITY_CHANGED violated: the registered artifact manifest "
            "changed after validation preflight; revalidation required"
        )

    components = conn.execute(
        "SELECT layer, feature_family, feature_family_version, partition_key, "
        "file_uri, content_hash, schema_hash, row_count "
        "FROM meta_feature_artifact_component WHERE feature_artifact_set_id = ? "
        "ORDER BY file_uri",
        [seal.feature_artifact_set_id],
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
    component_rows = [dict(zip(keys, row, strict=True)) for row in components]
    current_component_hash = compute_component_manifest_hash(component_rows)
    if current_component_hash != seal.component_manifest_hash:
        raise PublishStateError(
            "ARTIFACT_COMPONENTS_CHANGED violated: the component registry changed "
            "after validation preflight; revalidation required"
        )

    required_dq_ids = sorted(
        check.value for check in REQUIRED_VALIDATION_CHECKS if check.value.endswith("_ZERO")
    )
    current_proofs: list[dict[str, str]] = []
    for check_id in required_dq_ids:
        proof = conn.execute(
            "SELECT scan_contract_version, producer, scanned_component_manifest_hash, "
            "authoritative_input_hash, scanned_data_snapshot_id, execution_id "
            "FROM meta_artifact_check_execution "
            "WHERE feature_artifact_set_id = ? AND check_id = ? "
            "ORDER BY completed_at DESC, execution_id DESC LIMIT 1",
            [seal.feature_artifact_set_id, check_id],
        ).fetchone()
        if proof is None:
            raise PublishStateError(
                "ARTIFACT_VALIDATION_PRECHECK_STALE violated: a required DQ "
                f"completion proof {check_id} disappeared after preflight"
            )
        current_proofs.append(
            {
                "check_id": check_id,
                "execution_id": str(proof[5] or ""),
                "scan_contract_version": str(proof[0] or ""),
                "producer": str(proof[1] or ""),
                "authoritative_input_hash": str(proof[3] or ""),
                "scanned_component_manifest_hash": str(proof[2] or ""),
                "scanned_data_snapshot_id": str(proof[4] or ""),
            }
        )
    if _dq_execution_seal_hash(current_proofs) != seal.dq_execution_seal_hash:
        raise PublishStateError(
            "ARTIFACT_VALIDATION_PRECHECK_STALE violated: required DQ completion "
            "proofs changed after physical preflight; revalidate before publish"
        )

    for field, finding_class in (
        ("identity_fallback_count", "IDENTITY_FALLBACK"),
        ("blocking_dq_count", "BLOCKING_DQ"),
    ):
        count_row = conn.execute(
            "SELECT count(*) FROM meta_artifact_dq_finding "
            "WHERE feature_artifact_set_id = ? AND finding_class = ?",
            [seal.feature_artifact_set_id, finding_class],
        ).fetchone()
        current_count = int(count_row[0]) if count_row else 0
        expected_count = getattr(seal, field)
        if current_count != expected_count:
            raise PublishStateError(
                "ARTIFACT_VALIDATION_PRECHECK_STALE violated: DQ finding counts "
                "changed after physical preflight; revalidate before publish"
            )


def _resolve_publish_preconditions(
    conn: DuckDBPyConnection,
    *,
    trade_date: date,
    data_snapshot_id: str,
    feature_artifact_set_id: str,
    feature_set_version: str,
    universes: list[tuple[str, str]],
    pipeline_run_id: str,
) -> None:
    """R4-B2.1 P0-03 (Option A authoritative re-read): ALL publish
    preconditions, resolved from the CURRENT database state. MUST be
    called INSIDE the publish transaction - the values it reads are
    the authoritative facts the writes consume; nothing read before
    ``BEGIN TRANSACTION`` is a correctness input.

    Full lineage gate (R1 P0-02 + R2 P0-05/P0-06 + R3 P0-18/P1-01/P1-03):
      - snapshot exists, status DATA_VALIDATED
      - artifact exists, status FEATURE_VALIDATED
      - artifact.data_snapshot_id == data_snapshot_id (no cross-snapshot mix)
      - artifact.feature_set_version == feature_set_version
      - meta_feature_set exists, is ACTIVE, and its members STILL hash to
        the registered definition_hash (P1-03 self-check)
      - pipeline_run REQUIRED - NO exceptions (R3-P0-18)
      - pipeline_run exists, status FEATURE_VALIDATED
      - artifact.calc_run_id == pipeline_run_id (RECOVERY runs exempt)
      - run/artifact (code_commit, environment_lock_hash, config_hash) match
      - run/snapshot (source_policy_version, availability_policy_version) match
      - every (universe_id, universe_version) exists in dim_universe
    """
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


def publish_snapshot(
    conn: DuckDBPyConnection,
    *,
    trade_date: date,
    data_snapshot_id: str,
    feature_artifact_set_id: str,
    feature_set_version: str,
    universes: list[tuple[str, str]],
    pipeline_run_id: str,
    data_root: Path,
    quality_grade: str | None = None,
    publish_id: str | None = None,
) -> str:
    """Atomically publish one trade_date. Returns the publish_id.

    R4-B2.1 P0-03/P0-04: the heavy validation preflight (report and
    component bytes) completes before the short transaction.  The
    transaction then re-reads all lineage/status facts and consumes the
    DB-bound validation seal before changing publication rows.  Physical
    artifacts are immutable once registered; a deep physical re-audit is
    owned by the validator/audit path.  Any failure rolls everything back
    and the previous PUBLISHED publish stays visible.
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

    # P0-04: expensive report/component/DQ-input verification is a
    # preflight.  The returned seal is checked again against current DB
    # identities after BEGIN; no physical file hashing occurs in the write
    # transaction.
    validation_seal = _b2_recheck(
        conn,
        data_root=data_root,
        feature_artifact_set_id=feature_artifact_set_id,
    )

    conn.execute("BEGIN TRANSACTION")
    try:
        # P0-03: authoritative lineage/status preconditions - INSIDE the
        # transaction.
        _resolve_publish_preconditions(
            conn,
            trade_date=trade_date,
            data_snapshot_id=data_snapshot_id,
            feature_artifact_set_id=feature_artifact_set_id,
            feature_set_version=feature_set_version,
            universes=universes,
            pipeline_run_id=pipeline_run_id,
        )
        # P0-04: consume the preflight result using only current registry,
        # validation-head and completion-proof identities.
        _consume_b2_seal(conn, seal=validation_seal)
        artifact_validation_id = validation_seal.validation_id
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
