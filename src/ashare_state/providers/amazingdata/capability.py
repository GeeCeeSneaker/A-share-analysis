"""Provider capability registry (task book sections 3.1 / 10, audit P1-03).

Discipline: an AmazingData capability that has not passed the REAL-account
Spike may only ever be CANDIDATE. Approval flow:
    real account -> spike -> golden -> provider verification ->
    source-policy dry-run -> APPROVED

Audit P1-03: meta_provider_capability (migration 007 columns) is the
AUTHORITATIVE state; the in-memory registry is a session cache synced
explicitly via load_approvals()/persist_approval().
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.providers.amazingdata import production_identity as _production_identity

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


class CapabilityStatus(StrEnum):
    CANDIDATE = "CANDIDATE"  # API surface exists; data NOT yet verified
    APPROVED = "APPROVED"  # real-account spike + golden passed
    RETIRED = "RETIRED"  # deprecated / replaced by another endpoint


@dataclass(frozen=True)
class CapabilityEvidence:
    """Mandatory bundle for APPROVED (audit P1-03)."""

    spike_report_ref: str
    provider_verification_ref: str
    golden_case_refs: tuple[str, ...]
    dry_run_ref: str
    approved_by: str
    approved_at: str
    account_profile_id: str


class CapabilityGovernanceError(RuntimeError):
    """Illegal capability governance transition / incomplete evidence."""


@dataclass(frozen=True)
class Capability:
    name: str  # e.g. "security_master"
    sdk_methods: tuple[str, ...]
    canonical_domains: tuple[str, ...]  # fact domains this capability feeds
    status: CapabilityStatus = CapabilityStatus.CANDIDATE
    verified_at: str | None = None  # set only on APPROVED
    account_profile_id: str | None = None  # which account verified it


# Registry seeded from the 2026-08-21 manual + smoke evidence.
# EVERYTHING is CANDIDATE until the production-account Spike (task book 21.1).
CAPABILITY_REGISTRY: dict[str, Capability] = {
    cap.name: cap
    for cap in [
        Capability(
            name="trade_calendar",
            sdk_methods=("BaseData.get_calendar",),
            canonical_domains=("fact_trade_calendar",),
        ),
        Capability(
            name="security_master",
            sdk_methods=(
                "BaseData.get_code_list",
                "BaseData.get_hist_code_list",
                "InfoData.get_stock_basic",
            ),
            canonical_domains=("dim_security", "bridge_security_provider_symbol"),
        ),
        Capability(
            name="code_mapping_bj",
            sdk_methods=("InfoData.get_bj_code_mapping",),
            canonical_domains=("bridge_security_provider_symbol",),
        ),
        Capability(
            name="daily_bar",
            sdk_methods=("MarketData.query_kline",),
            canonical_domains=("fact_daily_bar",),
        ),
        Capability(
            name="security_status_history",
            sdk_methods=("InfoData.get_history_stock_status",),
            # task book 1.3: one endpoint, THREE fact domains - never merged
            canonical_domains=(
                "fact_security_status_daily",
                "fact_limit_price",
                "fact_corporate_action",
            ),
        ),
        Capability(
            name="adj_factor",
            sdk_methods=("BaseData.get_adj_factor", "BaseData.get_backward_factor"),
            canonical_domains=("fact_adj_factor",),
        ),
        Capability(
            name="corporate_action",
            sdk_methods=("InfoData.get_dividend", "InfoData.get_right_issue"),
            canonical_domains=("fact_corporate_action",),
        ),
        Capability(
            name="equity_structure",
            sdk_methods=("InfoData.get_equity_structure",),
            canonical_domains=("fact_equity_structure",),  # B6 assessment
        ),
        Capability(
            name="industry_taxonomy",
            sdk_methods=(
                "InfoData.get_industry_base_info",
                "InfoData.get_industry_constituent",
                "InfoData.get_industry_weight",
                "InfoData.get_industry_daily",
            ),
            canonical_domains=("bridge_industry_member",),
        ),
        Capability(
            name="index_daily",
            sdk_methods=("InfoData.get_index_daily", "MarketData.query_kline"),
            canonical_domains=("fact_index_daily",),
        ),
    ]
}


def capability_status(name: str) -> CapabilityStatus:
    cap = CAPABILITY_REGISTRY.get(name)
    if cap is None:
        msg = f"unknown capability {name!r}; registered: {sorted(CAPABILITY_REGISTRY)}"
        raise KeyError(msg)
    return cap.status


def _validate_evidence(name: str, evidence: CapabilityEvidence) -> Capability:
    """Pure validation: raise on incomplete evidence / RETIRED capability.

    R3-P1-05: NEVER mutates the registry - the persisted path validates
    first, writes the DB, then rebuilds the cache from the DB.
    """
    cap = CAPABILITY_REGISTRY[name]
    missing = [
        field
        for field, value in (
            ("spike_report_ref", evidence.spike_report_ref),
            ("provider_verification_ref", evidence.provider_verification_ref),
            ("golden_case_refs", evidence.golden_case_refs),
            ("dry_run_ref", evidence.dry_run_ref),
            ("approved_by", evidence.approved_by),
            ("approved_at", evidence.approved_at),
            ("account_profile_id", evidence.account_profile_id),
        )
        if not value
    ]
    if missing:
        msg = (
            f"capability approval evidence incomplete for {name!r}; "
            f"missing: {missing} (audit P1-03: real spike + golden + "
            "verification + dry-run + account profile required)"
        )
        raise CapabilityGovernanceError(msg)
    if cap.status is CapabilityStatus.RETIRED:
        msg = f"capability {name!r} is RETIRED; approval refused"
        raise CapabilityGovernanceError(msg)
    # R4-A3 A3-04 (audit 20260826 section 7.2): Fake/Trial success can
    # NEVER produce PRODUCTION capability truth. R4-A3.1 P0-03 (audit
    # 20260827): the refusal is a POSITIVE allowlist, not a blacklist -
    # approval requires an EXACT match with the frozen production
    # identity; with no frozen identity configured the gate fails closed
    # (an arbitrary ACCOUNT_*/UNKNOWN_* id can never approve).
    frozen = _production_identity.load_frozen_production_identity()
    if frozen is None:
        msg = (
            f"capability approval refused for {name!r}: no frozen production "
            "account identity is configured - production truth is NOT_TESTABLE "
            "(fail closed, audit R4-A3.1 P0-03: 'not Trial' is not 'Production')"
        )
        raise CapabilityGovernanceError(msg)
    if evidence.account_profile_id != frozen.account_profile_id:
        msg = (
            f"capability approval refused for {name!r}: account_profile_id "
            f"{evidence.account_profile_id!r} does not match the frozen "
            "production identity - only the positive exact match grants "
            "PRODUCTION truth (audit R4-A3.1 P0-03)"
        )
        raise CapabilityGovernanceError(msg)
    if frozen.account_profile_id.startswith(("TRIAL_", "TRIAL_SIMULATION", "FAKE")):
        msg = (
            "capability approval refused: the frozen production identity itself "
            f"looks non-production ({frozen.account_profile_id!r}) - fix the "
            "configs/production_account.yaml governance configuration"
        )
        raise CapabilityGovernanceError(msg)
    return cap


def _approve_capability_in_memory_testonly(name: str, evidence: CapabilityEvidence) -> Capability:
    """TEST-ONLY in-memory approval with FULL evidence bundle.

    R4-B1.1 (audit 20260830 P0-02): this is NOT a production approval
    path. The ONLY production-reachable APPROVED transition is
    ``approve_from_spike_run`` -> ``_persist_verified_capability``
    (verified internal proof object). This helper exists solely so
    tests can exercise evidence validation / registry mechanics
    without fabricating an entire spike run; it performs the same
    evidence validation but CANNOT substitute for the formal-run
    proof chain (endpoint requirements, gate REPORT, Raw identity
    cross-binding are NOT checked here - by design, the production
    gate consumes the DB/registry state that only the verified path
    writes).
    """
    _validate_evidence(name, evidence)
    cap = CAPABILITY_REGISTRY[name]
    approved = Capability(
        name=cap.name,
        sdk_methods=cap.sdk_methods,
        canonical_domains=cap.canonical_domains,
        status=CapabilityStatus.APPROVED,
        verified_at=evidence.approved_at,
        account_profile_id=evidence.account_profile_id,
    )
    CAPABILITY_REGISTRY[name] = approved
    return approved


@dataclass(frozen=True)
class VerifiedCapabilityApproval:
    """R4-B1.1 (audit 20260830 P0-02): the internal sealed approval
    proof object.

    Constructed ONLY inside ``approve_from_spike_run`` AFTER the full
    verification chain (closed production run / provenance / verdict /
    formal gate proof / exact endpoint identity cross-binding). The
    private persistence boundary ``_persist_verified_capability``
    accepts THIS object - never a caller-constructed
    ``CapabilityEvidence`` - so a production APPROVED transition cannot
    be self-declared."""

    name: str
    evidence: CapabilityEvidence
    verified_from_run: str
    endpoint_requirements_proven: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.verified_from_run:
            msg = "VerifiedCapabilityApproval requires the source spike run id"
            raise CapabilityGovernanceError(msg)
        if not self.endpoint_requirements_proven:
            msg = (
                "VerifiedCapabilityApproval requires the proven endpoint "
                "requirement ids - fabricating an empty proof is forbidden"
            )
            raise CapabilityGovernanceError(msg)


def _persist_verified_capability(
    conn: DuckDBPyConnection, verified: VerifiedCapabilityApproval
) -> Capability:
    """R4-B1.1 (audit 20260830 P0-02): the PRIVATE persistence boundary
    for production APPROVED transitions.

    Only accepts the internal ``VerifiedCapabilityApproval`` constructed
    by ``approve_from_spike_run`` after its full verification chain. A
    caller-constructed ``CapabilityEvidence`` can never reach the DB
    write through this boundary.

    R3-P1-05 validate-before-mutate semantics are preserved: evidence is
    validated WITHOUT touching the in-memory registry; the DB
    transaction writes; only AFTER commit is the cache rebuilt from the
    DB. A failed write leaves the cache exactly as the DB says."""
    name = verified.name
    evidence = verified.evidence
    # pure validation - NO memory mutation (R3-P1-05)
    _validate_evidence(name, evidence)
    existing = conn.execute(
        "SELECT 1 FROM meta_provider_capability WHERE provider = 'amazingdata' AND capability = ?",
        [name],
    ).fetchone()
    conn.execute("BEGIN TRANSACTION")
    try:
        if existing is None:
            conn.execute(
                "INSERT INTO meta_provider_capability "
                "(provider, capability, status, spike_report_ref, "
                "provider_verification_ref, golden_case_refs, dry_run_ref, "
                "account_profile_id, approved_by, adapter_version, verified_at) "
                "VALUES ('amazingdata', ?, 'APPROVED', ?, ?, ?, ?, ?, ?, NULL, ?)",
                [
                    name,
                    evidence.spike_report_ref,
                    evidence.provider_verification_ref,
                    ",".join(evidence.golden_case_refs),
                    evidence.dry_run_ref,
                    evidence.account_profile_id,
                    evidence.approved_by,
                    evidence.approved_at,
                ],
            )
        else:
            # R2-P1-01 12.3: UPDATE touches ONLY governance fields -
            # existing metadata columns can never be erased
            conn.execute(
                "UPDATE meta_provider_capability SET status = 'APPROVED', "
                "spike_report_ref = ?, provider_verification_ref = ?, "
                "golden_case_refs = ?, dry_run_ref = ?, account_profile_id = ?, "
                "approved_by = ?, verified_at = ? "
                "WHERE provider = 'amazingdata' AND capability = ?",
                [
                    evidence.spike_report_ref,
                    evidence.provider_verification_ref,
                    ",".join(evidence.golden_case_refs),
                    evidence.dry_run_ref,
                    evidence.account_profile_id,
                    evidence.approved_by,
                    evidence.approved_at,
                    name,
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        # restore the cache from the authoritative DB so it never says
        # APPROVED while the DB does not (R2-P1-01 12.2)
        load_approvals(conn)
        raise
    # post-commit: rebuild the cache from the authoritative table
    load_approvals(conn)
    return CAPABILITY_REGISTRY[name]


def _approve_and_persist_capability_testonly(
    conn: DuckDBPyConnection,
    name: str,
    evidence: CapabilityEvidence,
) -> Capability:
    """TEST-ONLY persisted approval from a caller-built evidence bundle.

    R4-B1.1 (audit 20260830 P0-02): production code MUST use
    ``approve_from_spike_run`` (verified proof object -> private
    persistence boundary). This helper exists so tests can exercise
    the evidence-validation / DB-transaction / cache-rebuild mechanics
    WITHOUT the formal-run chain. It performs the SAME validation as
    the old public path (including the positive frozen production
    identity), so it can never be used to smuggle a fake account - but
    it deliberately does NOT verify endpoint requirements, because it
    is not the production gate."""
    verified = VerifiedCapabilityApproval(
        name=name,
        evidence=evidence,
        verified_from_run=f"testonly:{evidence.spike_report_ref}",
        endpoint_requirements_proven=("TESTONLY",),
    )
    return _persist_verified_capability(conn, verified)


# ------------------------------------------ persistence (P1-03 / R2-P1-01)

#: registry capability name -> spike capability_id (R3-P0-17 mapping)
SPIKE_CAPABILITY_BY_REGISTRY: dict[str, str] = {
    "trade_calendar": "trade_calendar",
    "security_master": "security_master_with_delisted",
    "code_mapping_bj": "symbol_mapping_unambiguous",
    "daily_bar": "daily_bar_units",
    "security_status_history": "historical_st_suspend",
    "adj_factor": "adj_factor_corporate_action_continuity",
    "corporate_action": "adj_factor_corporate_action_continuity",
    "equity_structure": "free_float_equivalence",
    "industry_taxonomy": "sw_taxonomy",
    "index_daily": "benchmark_index_availability",
}


#: case-type marker emitted by the formal runtime gate boundary
FORMAL_GATE_CASE_TYPE = "formal_runtime_gate"

#: gate proof case ids per capability (R4-A3.1 P0-01/P0-02 + R4-B1):
#: PERMISSION / BUSINESS (each bound to RawWriter persisted evidence),
#: REPORT (the full gate-report artifact covering all six gate kinds),
#: and - R4-B1 B1-04 - one ENDPOINT case PER declared endpoint
#: requirement (see ``endpoint_requirements``; case ids come from
#: ``endpoint_requirement_case_id``).
FORMAL_GATE_PROOF_SUFFIXES = ("PERMISSION", "BUSINESS", "REPORT")


def _require_formal_gate_proof(
    catalog: Any,
    name: str,
    run_dir: Any = None,
    spike_root: Any = None,
) -> list[str]:
    """R4-A3.1 P0-01 + R4-B1 B1-04 + R4-B1.1 P0-03: approval requires the
    capability's formal gate proof.

    The proof is emitted ONLY by ``spike.formal_gates`` (the single
    formal gate execution boundary built on RuntimeGatePipeline). A run
    without them never executed the gate boundary for this capability
    -> approval is refused. Early stop is also caught: a blocked
    pipeline leaves probe-gate cases missing or non-PASS.

    Endpoint proofs are consumed by EXACT ENDPOINT IDENTITY, not by
    case-id naming alone:

    - each REQUIRED endpoint requirement must have a passing proof
      case bound to persisted RawWriter evidence;
    - each ALTERNATIVE_GROUP must have at least one passing member;
    - the REPORT artifact (``{run}/gates/{capability}.json``) carries
      the structured identity of every requirement - the artifact is
      re-hashed and compared against the REPORT case's evidence_hash,
      then every entry is re-checked against the CONTRACT.

    R4-B1.1 (audit 20260830 P0-03) - FULL cross-binding. For every
    requirement used to satisfy the proof, ALL four layers must agree
    EXACTLY:

    .. code-block:: text

        contract        <-> REPORT entry
        proof case      <-> REPORT entry (evidence URI/hash equality)
        REPORT entry    <-> persisted Raw meta (re-hashed on disk)
        Raw meta        <-> contract (endpoint + provider_dataset)

    Specifically re-verified: entry provider_dataset/actual_dataset
    against the contract; the proof case's evidence_ref/evidence_hash
    against the REPORT entry; the persisted .meta.json bytes against
    the entry hash; and the meta's request_id / endpoint /
    provider_dataset against the entry and the contract. Any single
    tamper fails CLOSED.

    Returns the list of requirement ids PROVEN (REQUIRED members plus
    the group members that actually satisfied their group) - consumed
    by the verified-approval proof object (R4-B1.1 P0-02)."""
    import hashlib
    import json
    from typing import NoReturn

    from ashare_state.providers.amazingdata.endpoint_requirements import (
        EndpointRequirementMode,
        endpoint_requirement_case_id,
        endpoint_requirements_for,
    )
    from ashare_state.spike.model import CaseResult

    def _refuse(detail: str) -> NoReturn:
        raise CapabilityGovernanceError(f"approval refused: {detail}")

    by_id = {c.case_id: c for c in catalog.cases}
    for suffix in FORMAL_GATE_PROOF_SUFFIXES:
        case_id = f"GATE-{name}-{suffix}"
        case = by_id.get(case_id)
        if case is None:
            _refuse(
                f"formal runtime gate proof missing for {name!r} ({case_id} "
                "not in the run's cases - the formal gate boundary is "
                "mandatory and cannot be bypassed, audit R4-A3.1 P0-01)"
            )
        if case.case_type != FORMAL_GATE_CASE_TYPE:
            _refuse(
                f"gate proof case {case_id} has type {case.case_type!r}, "
                f"expected {FORMAL_GATE_CASE_TYPE!r}"
            )
        if case.result is not CaseResult.VALIDATED_PASS:
            _refuse(
                f"formal gate proof {case_id} result is {case.result} - the "
                "runtime gate chain did not fully pass (audit R4-A3.1 P0-01)"
            )

    # ------------------------------------------------ endpoint proofs (B1-04)
    requirements = endpoint_requirements_for(name)
    if not requirements:
        _refuse(
            f"no endpoint requirements declared for {name!r} - the Endpoint "
            "Requirement Contract is the auditable truth and must cover "
            "every registered capability (audit R4-B1 B1-01)"
        )

    group_satisfied: dict[str, str | None] = {}
    for req in requirements:
        case_id = endpoint_requirement_case_id(req)
        case = by_id.get(case_id)
        case_ok = (
            case is not None
            and case.case_type == FORMAL_GATE_CASE_TYPE
            and case.result is CaseResult.VALIDATED_PASS
            and bool(case.evidence_ref)
            and bool(case.evidence_hash)
        )
        if req.mode is not EndpointRequirementMode.ALTERNATIVE_GROUP:
            if not case_ok:
                _refuse(
                    f"endpoint requirement proof {case_id} for {name!r} is "
                    "missing or not a persisted-evidence PASS - the exact "
                    "endpoint identity is a mandatory approval input "
                    "(audit R4-B1 B1-04)"
                )
            continue
        group_id = req.group_id or ""
        if case_ok and group_id and group_id not in group_satisfied:
            group_satisfied[group_id] = req.requirement_id
    for req in requirements:
        group_id = req.group_id or ""
        if (
            req.mode is EndpointRequirementMode.ALTERNATIVE_GROUP
            and group_id
            and group_id not in group_satisfied
        ):
            _refuse(
                f"alternative group {group_id!r} for {name!r} has no "
                "passing member endpoint - the capability's endpoint "
                "surface is not proven (audit R4-B1 B1-04)"
            )

    # ------------------------------------------- REPORT artifact re-check
    # B1-04: re-verify the structured endpoint identities from the
    # hash-anchored artifact - case-id naming alone is NOT trusted.
    report_case = by_id.get(f"GATE-{name}-REPORT")
    if run_dir is None or report_case is None or spike_root is None:
        # defensive: the formal-run path always supplies both; refuse
        # rather than skip the cross-binding (fail closed)
        _refuse(
            f"gate proof cross-binding for {name!r} requires the run "
            "directory and spike root - incomplete verification inputs "
            "(audit R4-B1.1 P0-03)"
        )
    artifact_path = Path(run_dir) / "gates" / f"{name}.json"
    if not artifact_path.exists():
        _refuse(
            f"gate report artifact missing for {name!r} ({artifact_path} - "
            "the REPORT case binds it by hash, audit R4-B1 B1-04)"
        )
    artifact_bytes = artifact_path.read_bytes()
    if hashlib.sha256(artifact_bytes).hexdigest() != report_case.evidence_hash:
        _refuse(
            f"gate report artifact for {name!r} does not match the REPORT "
            "case evidence hash - tampered or stale endpoint identity "
            "(audit R4-B1 B1-04, fail closed)"
        )
    doc = json.loads(artifact_bytes.decode("utf-8"))
    entries = {e.get("requirement_id"): e for e in doc.get("endpoint_requirements", [])}

    proven: list[str] = []
    for req in requirements:
        entry = entries.get(req.requirement_id)
        if entry is None:
            _refuse(
                f"gate report artifact for {name!r} has no entry for "
                f"requirement {req.requirement_id!r} (audit R4-B1 B1-04)"
            )
        # ---- contract <-> REPORT entry (B1-04 + B1.1 P0-03: datasets too)
        if entry.get("expected_endpoint") != req.endpoint:
            _refuse(
                f"requirement {req.requirement_id!r} expected_endpoint "
                f"{entry.get('expected_endpoint')!r} != contract endpoint "
                f"{req.endpoint!r} (audit R4-B1 B1-04, fail closed)"
            )
        if entry.get("provider_dataset") != req.provider_dataset:
            _refuse(
                f"requirement {req.requirement_id!r} provider_dataset "
                f"{entry.get('provider_dataset')!r} != contract dataset "
                f"{req.provider_dataset!r} (audit R4-B1.1 P0-03, fail closed)"
            )
        if entry.get("capability") != req.capability:
            _refuse(
                f"requirement {req.requirement_id!r} artifact capability "
                f"{entry.get('capability')!r} != contract capability "
                f"{req.capability!r} (audit R4-B1.1 P0-03, fail closed)"
            )
        # ---- is this requirement the one satisfying the proof?
        group_member_not_satisfying = (
            req.mode is EndpointRequirementMode.ALTERNATIVE_GROUP
            and group_satisfied.get(req.group_id or "") != req.requirement_id
        )
        if group_member_not_satisfying:
            # a failing member: tolerated only if another member
            # satisfies the group - never recorded as proven
            continue
        if entry.get("status") != "PASS":
            _refuse(
                f"requirement {req.requirement_id!r} artifact status is "
                f"{entry.get('status')!r} (audit R4-B1 B1-04, fail closed)"
            )
        if entry.get("actual_endpoint") != req.endpoint:
            _refuse(
                f"requirement {req.requirement_id!r} actual_endpoint "
                f"{entry.get('actual_endpoint')!r} does not match the "
                f"declared endpoint {req.endpoint!r} - stand-in endpoints "
                "are forbidden (audit R4-B1 B1-02, fail closed)"
            )
        if entry.get("actual_dataset") != req.provider_dataset:
            _refuse(
                f"requirement {req.requirement_id!r} actual_dataset "
                f"{entry.get('actual_dataset')!r} != contract dataset "
                f"{req.provider_dataset!r} (audit R4-B1.1 P0-03, fail closed)"
            )
        if not entry.get("evidence_uri") or not entry.get("evidence_hash"):
            _refuse(
                f"requirement {req.requirement_id!r} artifact entry has no "
                "persisted evidence binding (audit R4-B1 B1-04, fail closed)"
            )
        if not entry.get("request_id"):
            _refuse(
                f"requirement {req.requirement_id!r} artifact entry has no "
                "request id (audit R4-B1.1 P0-03, fail closed)"
            )
        # ---- proof case <-> REPORT entry identity equality (B1.1 P0-03)
        case = by_id.get(endpoint_requirement_case_id(req))
        if case is None:
            _refuse(
                f"endpoint proof case for {req.requirement_id!r} vanished "
                "between the case scan and the artifact re-check"
            )
        if case.evidence_ref != entry.get("evidence_uri"):
            _refuse(
                f"requirement {req.requirement_id!r} proof case "
                f"evidence_ref {case.evidence_ref!r} != REPORT entry "
                f"evidence_uri {entry.get('evidence_uri')!r} - the case and "
                "the report disagree about which evidence proves the "
                "endpoint (audit R4-B1.1 P0-03, fail closed)"
            )
        if case.evidence_hash != entry.get("evidence_hash"):
            _refuse(
                f"requirement {req.requirement_id!r} proof case "
                f"evidence_hash != REPORT entry evidence_hash - the case "
                "and the report disagree about the evidence bytes (audit "
                "R4-B1.1 P0-03, fail closed)"
            )
        # ---- REPORT entry <-> persisted Raw meta reverse verification
        meta_path = Path(spike_root) / str(entry.get("evidence_uri"))
        if not meta_path.exists():
            _refuse(
                f"requirement {req.requirement_id!r} persisted evidence "
                f"{meta_path} does not exist (audit R4-B1.1 P0-03)"
            )
        meta_bytes = meta_path.read_bytes()
        if hashlib.sha256(meta_bytes).hexdigest() != entry.get("evidence_hash"):
            _refuse(
                f"requirement {req.requirement_id!r} persisted evidence "
                "bytes do not match the REPORT entry hash - tampered raw "
                "meta (audit R4-B1.1 P0-03, fail closed)"
            )
        meta_doc = json.loads(meta_bytes.decode("utf-8"))
        if meta_doc.get("request_id") != entry.get("request_id"):
            _refuse(
                f"requirement {req.requirement_id!r} raw meta request_id "
                f"{meta_doc.get('request_id')!r} != REPORT entry "
                f"{entry.get('request_id')!r} (audit R4-B1.1 P0-03, fail closed)"
            )
        if meta_doc.get("endpoint") != req.endpoint:
            _refuse(
                f"requirement {req.requirement_id!r} raw meta endpoint "
                f"{meta_doc.get('endpoint')!r} != contract endpoint "
                f"{req.endpoint!r} (audit R4-B1.1 P0-03, fail closed)"
            )
        if meta_doc.get("provider_dataset") != req.provider_dataset:
            _refuse(
                f"requirement {req.requirement_id!r} raw meta "
                f"provider_dataset {meta_doc.get('provider_dataset')!r} != "
                f"contract dataset {req.provider_dataset!r} (audit "
                "R4-B1.1 P0-03, fail closed)"
            )
        proven.append(req.requirement_id)
    if not proven:
        _refuse(f"no endpoint requirement was actually proven for {name!r} (audit R4-B1.1 P0-03)")
    return proven


def approve_from_spike_run(
    conn: DuckDBPyConnection,
    name: str,
    *,
    spike_root: Path,
    spike_run_id: str,
    approved_by: str,
    capability_case_refs: tuple[str, ...] = (),
) -> Capability:
    """R3-P0-17: approval that PROVES itself from a closed production run.

    The caller does NOT assert "it passed" - this function queries the
    spike run itself and requires:
      - run kind PRODUCTION, status CLOSED
      - run provenance complete
      - evidence closure clean (hashes re-verified)
      - the capability PASSes the verdict engine over that run's cases
      - each listed golden case ref EXISTS in the catalog and is a
        VALIDATED_PASS / equivalent DIFF_EXPLAINED
    Only then is the evidence bundle built from the RUN's facts and
    persisted (single transaction, cache rebuilt after commit).
    """
    from ashare_state.spike.model import RunKind, RunStatus
    from ashare_state.spike.run_store import RunStore
    from ashare_state.spike.runner import compute_verdict

    store = RunStore(spike_root)
    run = store.load_run(spike_run_id, RunKind.PRODUCTION)
    if run.status != RunStatus.CLOSED.value:
        msg = f"approval refused: spike run {spike_run_id} is {run.status}, not CLOSED"
        raise CapabilityGovernanceError(msg)
    if not run.provenance_complete():
        msg = f"approval refused: spike run {spike_run_id} provenance incomplete"
        raise CapabilityGovernanceError(msg)
    # R4-A3 A3-04 + R4-A3.1 P0-03: a PRODUCTION-kind run does not itself
    # constitute production truth - the run's account must POSITIVELY
    # match the frozen production identity (allowlist, not blacklist);
    # with no frozen identity configured approval fails closed.
    frozen = _production_identity.load_frozen_production_identity()
    if frozen is None:
        msg = (
            "approval refused: no frozen production account identity is "
            "configured - capability approval is blocked (fail closed, audit "
            "R4-A3.1 P0-03: RunKind.PRODUCTION never substitutes for account "
            "identity)"
        )
        raise CapabilityGovernanceError(msg)
    if run.account_profile_id != frozen.account_profile_id:
        msg = (
            f"approval refused: spike run {spike_run_id} account_profile_id "
            f"{run.account_profile_id!r} does not match the frozen production "
            f"identity - run kind PRODUCTION alone is not production truth "
            "(audit R4-A3.1 P0-03)"
        )
        raise CapabilityGovernanceError(msg)
    verdict = compute_verdict(store, run)
    spike_capability = SPIKE_CAPABILITY_BY_REGISTRY.get(name, name)
    status = verdict.capability_status.get(spike_capability)
    if status != "PASS":
        msg = (
            f"approval refused: capability {name!r} (spike capability "
            f"{spike_capability!r}) is {status} in spike run "
            f"{spike_run_id} (verdict {verdict.verdict})"
        )
        raise CapabilityGovernanceError(msg)
    # golden case refs must exist AND be valid in this run
    from ashare_state.spike.catalog import CaseCatalog
    from ashare_state.spike.model import core_gate_satisfied

    catalog = CaseCatalog(store, run.spike_run_id)
    catalog.load(store.run_dir(run))
    # R4-A3.1 P0-01 (audit 20260827): the formal gate boundary is a
    # MANDATORY prerequisite of capability approval - a run whose
    # capability proof never executed the RuntimeGatePipeline cannot
    # approve anything. This closes the bypass: gate evidence is not an
    # optional helper, it is consumed by the approval path.
    # R4-B1 B1-04 + R4-B1.1 P0-03: run_dir AND spike_root are passed so
    # the endpoint identities are cross-bound against the hash-anchored
    # REPORT artifact AND the persisted Raw meta (contract <-> case <->
    # REPORT <-> raw meta, all four layers exact).
    proven_requirements = _require_formal_gate_proof(
        catalog, name, run_dir=store.run_dir(run), spike_root=store.spike_root
    )
    cases = {c.case_id: c for c in catalog.cases}
    for ref in capability_case_refs:
        case = cases.get(ref)
        if case is None:
            msg = f"approval refused: golden case ref {ref!r} not in run {spike_run_id}"
            raise CapabilityGovernanceError(msg)
        if not core_gate_satisfied(case.result, equivalent_pass=case.equivalent_pass):
            msg = f"approval refused: golden case {ref} result is {case.result}"
            raise CapabilityGovernanceError(msg)
    evidence = CapabilityEvidence(
        spike_report_ref=f"spike-run:{spike_run_id}",
        provider_verification_ref="docs/provider_verification/amazingdata.md",
        golden_case_refs=tuple(capability_case_refs),
        dry_run_ref=f"verdict:{verdict.verdict}",
        approved_by=approved_by,
        approved_at=run.ended_at or "",
        account_profile_id=run.account_profile_id,
    )
    # R4-B1.1 (audit 20260830 P0-02): the ONLY production-reachable
    # APPROVED transition - build the internal verified proof object
    # (only constructible here, after the full verification chain) and
    # hand it to the private persistence boundary.
    verified = VerifiedCapabilityApproval(
        name=name,
        evidence=evidence,
        verified_from_run=spike_run_id,
        endpoint_requirements_proven=tuple(proven_requirements),
    )
    return _persist_verified_capability(conn, verified)


def load_approvals(conn: DuckDBPyConnection) -> dict[str, CapabilityStatus]:
    """Sync the in-memory registry from the authoritative table.

    Full sync semantics (audit R2-P1-01 12.4):
    - restores complete provenance (verified_at / account_profile_id)
    - DB status OVERRIDES the cached state in BOTH directions: a DB
      CANDIDATE row actively demotes a stale cached APPROVED.
    """
    rows = conn.execute(
        "SELECT capability, status, verified_at, account_profile_id "
        "FROM meta_provider_capability WHERE provider = 'amazingdata'"
    ).fetchall()
    loaded: dict[str, CapabilityStatus] = {}
    for capability, status, verified_at, account_profile_id in rows:
        key = str(capability)
        try:
            db_status = CapabilityStatus(str(status))
        except ValueError:
            # unknown status literal in db: fail safe to CANDIDATE
            db_status = CapabilityStatus.CANDIDATE
        loaded[key] = db_status
        cap = CAPABILITY_REGISTRY.get(key)
        if cap is not None:
            # unconditional override: DB is authoritative, cache is cache
            CAPABILITY_REGISTRY[key] = Capability(
                name=cap.name,
                sdk_methods=cap.sdk_methods,
                canonical_domains=cap.canonical_domains,
                status=db_status,
                verified_at=str(verified_at) if verified_at else cap.verified_at,
                account_profile_id=str(account_profile_id)
                if account_profile_id
                else cap.account_profile_id,
            )
    return loaded
