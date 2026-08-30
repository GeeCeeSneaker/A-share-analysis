"""Explicit Endpoint Requirement Contract (R4-B1, audit 20260828;
R4-B1.1 semantic reconciliation, audit 20260830).

B1-01: the capability -> endpoint mapping is a TYPED, auditable
contract - NOT scattered if/else interpretations of registry tuples.

Every registered capability declares its endpoint requirements here.
The formal ENDPOINT_AVAILABLE gate consumes THIS table (B1-02): one
EXACT probe per requirement - a probe exchange whose
``envelope.endpoint`` does not match the declared endpoint is a
blocking FAIL (a stand-in endpoint - e.g. ``get_stock_basic`` proving
``industry_taxonomy`` - can never again mark the gate PASS).

R4-B1.1 (audit 20260830 P0-01) - semantic corrections:

- ``security_master``: the spike capability is
  ``security_master_with_delisted`` - the master MUST contain delisted
  securities (survivorship). The HISTORICAL listing endpoint
  (``BaseData.get_hist_code_list``) is therefore REQUIRED - the
  current-snapshot ``get_code_list`` alone can never satisfy the
  endpoint proof (the R4-B1 "official alternatives" grouping was
  wrong and is withdrawn).
- ``adj_factor``: ADR-020 originally claimed get_adj_factor and
  get_backward_factor were "each REQUIRED" while the runtime contract
  declared only get_adj_factor - a double truth. Resolved per Option
  B: the capability approval requires the forward-adjustment factor
  endpoint only; backward factor is explicitly classified
  OPTIONAL_NON_APPROVAL_SURFACE (documented, not consumed by the
  approval chain).
- EVERY registry ``sdk_methods`` entry now has an EXPLICIT
  classification (``SDK_METHOD_CLASSIFICATIONS``): no method may be
  silently present-or-absent from the proof contract. The structural
  guards verify registry <-> classification <-> requirements
  three-way consistency, so adding/removing an SDK method forces a
  contract decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "ENDPOINT_REQUIREMENTS",
    "EndpointRequirement",
    "EndpointRequirementMode",
    "ProofRole",
    "SDK_METHOD_CLASSIFICATIONS",
    "SdkMethodClassification",
    "SdkMethodProofClass",
    "endpoint_requirement_case_id",
    "endpoint_requirements_for",
    "sdk_method_classifications_for",
    "validate_endpoint_requirements",
]


class EndpointRequirementMode(StrEnum):
    """How a requirement must be satisfied.

    - REQUIRED: this exact endpoint MUST be proven available.
    - ALTERNATIVE_GROUP: the declared group of endpoints are official
      alternatives of each other - at least ONE member must be proven.
      (No capability currently uses a group: security_master's R4-B1
      grouping was withdrawn by audit 20260830 P0-01. The primitive
      stays for future GENUINELY interchangeable endpoints.)
    """

    REQUIRED = "REQUIRED"
    ALTERNATIVE_GROUP = "ALTERNATIVE_GROUP"


class ProofRole(StrEnum):
    """What a requirement proves on the formal path.

    - ENDPOINT_PROOF: consumed by the formal ENDPOINT_AVAILABLE gate.
    - BUSINESS_PROOF: the business fetch's expected endpoint identity
      (consumed by the business-side proof chain; reserved for the
      B2-B7 semantic probes).
    """

    ENDPOINT_PROOF = "ENDPOINT_PROOF"
    BUSINESS_PROOF = "BUSINESS_PROOF"


class SdkMethodProofClass(StrEnum):
    """R4-B1.1 (audit 20260830 section 2.3): the explicit proof
    classification of every registry sdk_method.

    - REQUIRED_ENDPOINT_PROOF: the method is a REQUIRED endpoint
      requirement of its capability (exact probe + persisted proof +
      approval consumption).
    - ALTERNATIVE_GROUP_MEMBER: the method satisfies its capability's
      proof as a member of a declared ALTERNATIVE_GROUP.
    - OPTIONAL_NON_APPROVAL_SURFACE: the method is documented in the
      registry but is NOT a condition of capability approval
      (convenience/detail/alternative surface). Explicitly reconciled
      so a reviewer never has to guess why it is absent from the
      proof contract.
    - BUSINESS_SEMANTIC_ONLY: the method is consumed by the B2-B7
      semantic probes but is not an endpoint-proof condition.
    - DEPRECATED_NOT_USED: the method is documented but not consumed
      anywhere in the current pipeline.
    """

    REQUIRED_ENDPOINT_PROOF = "REQUIRED_ENDPOINT_PROOF"
    ALTERNATIVE_GROUP_MEMBER = "ALTERNATIVE_GROUP_MEMBER"
    OPTIONAL_NON_APPROVAL_SURFACE = "OPTIONAL_NON_APPROVAL_SURFACE"
    BUSINESS_SEMANTIC_ONLY = "BUSINESS_SEMANTIC_ONLY"
    DEPRECATED_NOT_USED = "DEPRECATED_NOT_USED"


@dataclass(frozen=True)
class EndpointRequirement:
    """One declared endpoint identity of one capability.

    ``endpoint`` is the SDK endpoint identity (``Class.method``) that
    MUST appear on the probe exchange envelope - exact match, no
    stand-in. ``provider_dataset`` is the provider-side dataset label
    the exchange must carry. ``mode`` decides satisfiability; members
    of the same ``group_id`` are official alternatives of each other.
    """

    requirement_id: str
    capability: str
    endpoint: str
    provider_dataset: str
    mode: EndpointRequirementMode = EndpointRequirementMode.REQUIRED
    group_id: str | None = None
    proof_role: ProofRole = ProofRole.ENDPOINT_PROOF


@dataclass(frozen=True)
class SdkMethodClassification:
    """R4-B1.1: the auditable proof decision for ONE registry
    sdk_method - classification + reason. Every registry method has
    exactly one entry; the reason is the recorded justification."""

    capability: str
    endpoint: str
    classification: SdkMethodProofClass
    reason: str


#: The explicit contract (B1-01). Derived from the capability registry's
#: documented SDK surfaces - but declared HERE as the auditable truth
#: the formal gate and the approval path both consume.
ENDPOINT_REQUIREMENTS: tuple[EndpointRequirement, ...] = (
    EndpointRequirement(
        requirement_id="trade_calendar:BaseData.get_calendar",
        capability="trade_calendar",
        endpoint="BaseData.get_calendar",
        provider_dataset="trade_calendar",
    ),
    # R4-B1.1 (audit 20260830 P0-01): security_master is
    # security_master_with_delisted - the survivorship requirement
    # makes the HISTORICAL listing endpoint REQUIRED. get_code_list
    # (current snapshot) is a non-approval surface (see
    # SDK_METHOD_CLASSIFICATIONS) - it can no longer satisfy this
    # capability's endpoint proof on its own.
    EndpointRequirement(
        requirement_id="security_master:BaseData.get_hist_code_list",
        capability="security_master",
        endpoint="BaseData.get_hist_code_list",
        provider_dataset="hist_code_list",
    ),
    # B1-02: the dedicated BJ code-mapping endpoint - a generic
    # stock-code list can never stand in for it.
    EndpointRequirement(
        requirement_id="code_mapping_bj:InfoData.get_bj_code_mapping",
        capability="code_mapping_bj",
        endpoint="InfoData.get_bj_code_mapping",
        provider_dataset="code_mapping_bj",
    ),
    EndpointRequirement(
        requirement_id="daily_bar:MarketData.query_kline",
        capability="daily_bar",
        endpoint="MarketData.query_kline",
        provider_dataset="daily_bar",
    ),
    EndpointRequirement(
        requirement_id="security_status_history:InfoData.get_history_stock_status",
        capability="security_status_history",
        endpoint="InfoData.get_history_stock_status",
        provider_dataset="history_stock_status",
    ),
    # R4-B1.1 (audit 20260830 P0-01, Option B): adj_factor approval
    # requires the forward-adjustment endpoint only; get_backward_factor
    # is classified OPTIONAL_NON_APPROVAL_SURFACE below.
    EndpointRequirement(
        requirement_id="adj_factor:BaseData.get_adj_factor",
        capability="adj_factor",
        endpoint="BaseData.get_adj_factor",
        provider_dataset="adj_factor",
    ),
    # corporate_action: TWO independent event streams (R4-A2.5) - both
    # endpoints are REQUIRED members of the capability surface.
    EndpointRequirement(
        requirement_id="corporate_action:InfoData.get_dividend",
        capability="corporate_action",
        endpoint="InfoData.get_dividend",
        provider_dataset="corporate_action",
    ),
    EndpointRequirement(
        requirement_id="corporate_action:InfoData.get_right_issue",
        capability="corporate_action",
        endpoint="InfoData.get_right_issue",
        provider_dataset="corporate_action",
    ),
    # B1-02: the dedicated equity-structure endpoint - stock_basic is
    # a stand-in and is FORBIDDEN as its proof.
    EndpointRequirement(
        requirement_id="equity_structure:InfoData.get_equity_structure",
        capability="equity_structure",
        endpoint="InfoData.get_equity_structure",
        provider_dataset="equity_structure",
    ),
    # B1-02: the dedicated industry-taxonomy endpoint - stock_basic is
    # a stand-in and is FORBIDDEN as its proof.
    EndpointRequirement(
        requirement_id="industry_taxonomy:InfoData.get_industry_base_info",
        capability="industry_taxonomy",
        endpoint="InfoData.get_industry_base_info",
        provider_dataset="industry_taxonomy",
    ),
    # R4-B1.2 (audit 20260830 P0-02): the canonical deliverable of
    # industry_taxonomy is bridge_industry_member - security <->
    # industry MEMBERSHIP. base_info alone proves the taxonomy
    # definition/identity surface; the constituent membership surface
    # is REQUIRED: with base_info PASS and constituent DENIED the
    # capability cannot reliably build bridge_industry_member, so the
    # endpoint proof must FAIL.
    EndpointRequirement(
        requirement_id="industry_taxonomy:InfoData.get_industry_constituent",
        capability="industry_taxonomy",
        endpoint="InfoData.get_industry_constituent",
        provider_dataset="industry_taxonomy",
    ),
    # index_daily: official endpoint is the kline surface with an
    # index code list (dataset label is the provider fact "daily_bar").
    EndpointRequirement(
        requirement_id="index_daily:MarketData.query_kline",
        capability="index_daily",
        endpoint="MarketData.query_kline",
        provider_dataset="daily_bar",
    ),
)


#: R4-B1.1 (audit 20260830 section 2.3): the explicit reconciliation of
#: EVERY registry sdk_method. Structural guards verify that this table
#: covers the registry exactly (no silent presence/absence), and that
#: REQUIRED_ENDPOINT_PROOF classifications coincide with the
#: ENDPOINT_REQUIREMENTS table.
SDK_METHOD_CLASSIFICATIONS: tuple[SdkMethodClassification, ...] = (
    SdkMethodClassification(
        capability="trade_calendar",
        endpoint="BaseData.get_calendar",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="the capability's single official endpoint",
    ),
    SdkMethodClassification(
        capability="security_master",
        endpoint="BaseData.get_code_list",
        classification=SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE,
        reason=(
            "current-snapshot listing (convenience/permission surface); "
            "survivorship core of security_master_with_delisted is proven "
            "by the HISTORICAL endpoint - the snapshot alone never "
            "satisfies the endpoint proof (audit 20260830 P0-01)"
        ),
    ),
    SdkMethodClassification(
        capability="security_master",
        endpoint="BaseData.get_hist_code_list",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason=(
            "historical listing rebuild including delisted securities - "
            "the survivorship requirement of security_master_with_delisted"
        ),
    ),
    SdkMethodClassification(
        capability="security_master",
        endpoint="InfoData.get_stock_basic",
        classification=SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE,
        reason=(
            "per-security detail convenience surface; not a condition of "
            "capability approval (was the R4-A3.1-era stand-in probe - "
            "removed by R4-B1)"
        ),
    ),
    SdkMethodClassification(
        capability="code_mapping_bj",
        endpoint="InfoData.get_bj_code_mapping",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="the dedicated BJ code-mapping endpoint",
    ),
    SdkMethodClassification(
        capability="daily_bar",
        endpoint="MarketData.query_kline",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="the kline surface carrying daily bars",
    ),
    SdkMethodClassification(
        capability="security_status_history",
        endpoint="InfoData.get_history_stock_status",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="the single endpoint feeding three status fact domains",
    ),
    SdkMethodClassification(
        capability="adj_factor",
        endpoint="BaseData.get_adj_factor",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="forward-adjustment factor - the pipeline's adjustment path",
    ),
    SdkMethodClassification(
        capability="adj_factor",
        endpoint="BaseData.get_backward_factor",
        classification=SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE,
        reason=(
            "backward-adjustment factor is a DIFFERENT data stream the "
            "current pipeline does not consume; R4-B1.1 Option B resolves "
            "the ADR-020 'each REQUIRED' overclaim (audit 20260830 P0-01)"
        ),
    ),
    SdkMethodClassification(
        capability="corporate_action",
        endpoint="InfoData.get_dividend",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="dividend event stream - one of two REQUIRED streams (R4-A2.5)",
    ),
    SdkMethodClassification(
        capability="corporate_action",
        endpoint="InfoData.get_right_issue",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="rights-issue event stream - one of two REQUIRED streams (R4-A2.5)",
    ),
    SdkMethodClassification(
        capability="equity_structure",
        endpoint="InfoData.get_equity_structure",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="the dedicated equity-structure endpoint",
    ),
    SdkMethodClassification(
        capability="industry_taxonomy",
        endpoint="InfoData.get_industry_base_info",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="taxonomy definition/identity surface of bridge_industry_member",
    ),
    SdkMethodClassification(
        capability="industry_taxonomy",
        endpoint="InfoData.get_industry_constituent",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason=(
            "security <-> industry MEMBERSHIP surface - the core "
            "deliverable of bridge_industry_member (R4-B1.2 audit "
            "20260830 P0-02: proving a representative endpoint != "
            "proving the capability's necessary delivery surface)"
        ),
    ),
    SdkMethodClassification(
        capability="industry_taxonomy",
        endpoint="InfoData.get_industry_weight",
        classification=SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE,
        reason=(
            "index-weight detail is NOT consumed by the current "
            "bridge_industry_member construction (membership is built "
            "from base_info + constituent); revisit if a canonical/feature "
            "consumer starts requiring weights"
        ),
    ),
    SdkMethodClassification(
        capability="industry_taxonomy",
        endpoint="InfoData.get_industry_daily",
        classification=SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE,
        reason=(
            "industry daily series is NOT consumed by the current "
            "bridge_industry_member construction; revisit if a "
            "canonical/feature consumer starts requiring it"
        ),
    ),
    SdkMethodClassification(
        capability="index_daily",
        endpoint="InfoData.get_index_daily",
        classification=SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE,
        reason=(
            "documented SDK alternative; the pipeline consumes "
            "MarketData.query_kline with index code lists instead"
        ),
    ),
    SdkMethodClassification(
        capability="index_daily",
        endpoint="MarketData.query_kline",
        classification=SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF,
        reason="the kline surface carrying index daily bars",
    ),
)


def validate_endpoint_requirements() -> list[str]:
    """Structural self-check of the contract. Returns the list of
    violations (empty = valid). Checked by the B1/B1.1 structural guard
    tests - a malformed contract can never silently ship."""
    violations: list[str] = []
    seen_ids: set[str] = set()
    groups: dict[str, list[str]] = {}
    for req in ENDPOINT_REQUIREMENTS:
        if req.requirement_id in seen_ids:
            violations.append(f"duplicate requirement_id {req.requirement_id!r}")
        seen_ids.add(req.requirement_id)
        if not req.endpoint or "." not in req.endpoint:
            violations.append(f"{req.requirement_id}: endpoint must be a Class.method identity")
        if not req.provider_dataset:
            violations.append(f"{req.requirement_id}: provider_dataset must be declared")
        if req.mode is EndpointRequirementMode.ALTERNATIVE_GROUP:
            if not req.group_id:
                violations.append(f"{req.requirement_id}: ALTERNATIVE_GROUP requires group_id")
            else:
                groups.setdefault(req.group_id, []).append(req.requirement_id)
        elif req.group_id:
            violations.append(
                f"{req.requirement_id}: REQUIRED requirement must not carry a group_id"
            )
    for group_id, members in groups.items():
        if len(members) < 2:
            violations.append(
                f"alternative group {group_id!r} has fewer than two members: {members}"
            )
    # R4-B1.1: classification table internal consistency
    seen_class: set[tuple[str, str]] = set()
    for entry in SDK_METHOD_CLASSIFICATIONS:
        key = (entry.capability, entry.endpoint)
        if key in seen_class:
            violations.append(f"duplicate classification for {key}")
        seen_class.add(key)
        if not entry.reason.strip():
            violations.append(f"{key}: classification reason must be recorded")
    # requirements <-> classification consistency
    required_classified = {
        (e.capability, e.endpoint)
        for e in SDK_METHOD_CLASSIFICATIONS
        if e.classification is SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF
    }
    required_declared = {
        (r.capability, r.endpoint)
        for r in ENDPOINT_REQUIREMENTS
        if r.mode is EndpointRequirementMode.REQUIRED
    }
    if required_classified != required_declared:
        violations.append(
            f"REQUIRED classification != REQUIRED requirements: "
            f"classified-only={sorted(required_classified - required_declared)}, "
            f"declared-only={sorted(required_declared - required_classified)}"
        )
    group_classified = {
        (e.capability, e.endpoint)
        for e in SDK_METHOD_CLASSIFICATIONS
        if e.classification is SdkMethodProofClass.ALTERNATIVE_GROUP_MEMBER
    }
    group_declared = {
        (r.capability, r.endpoint)
        for r in ENDPOINT_REQUIREMENTS
        if r.mode is EndpointRequirementMode.ALTERNATIVE_GROUP
    }
    if group_classified != group_declared:
        violations.append(
            f"ALTERNATIVE_GROUP classification != grouped requirements: "
            f"classified-only={sorted(group_classified - group_declared)}, "
            f"declared-only={sorted(group_declared - group_classified)}"
        )
    return violations


def endpoint_requirements_for(capability: str) -> tuple[EndpointRequirement, ...]:
    """The ENDPOINT_PROOF requirements of one capability, declaration
    order preserved."""
    return tuple(
        req
        for req in ENDPOINT_REQUIREMENTS
        if req.capability == capability and req.proof_role is ProofRole.ENDPOINT_PROOF
    )


def sdk_method_classifications_for(capability: str) -> tuple[SdkMethodClassification, ...]:
    """The proof classifications of one capability's SDK methods."""
    return tuple(e for e in SDK_METHOD_CLASSIFICATIONS if e.capability == capability)


def endpoint_requirement_case_id(req: EndpointRequirement) -> str:
    """The proof case id of one requirement (consumed by the formal
    gate emitter AND by capability approval - single source of truth)."""
    return f"GATE-{req.requirement_id.replace(':', '-')}"
