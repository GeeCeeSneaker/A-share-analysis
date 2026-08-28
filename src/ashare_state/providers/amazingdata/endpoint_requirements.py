"""Explicit Endpoint Requirement Contract (R4-B1, audit 20260828).

B1-01: the capability -> endpoint mapping is a TYPED, auditable
contract - NOT scattered if/else interpretations of registry tuples.

Every registered capability declares its endpoint requirements here.
The formal ENDPOINT_AVAILABLE gate consumes THIS table (B1-02): one
EXACT probe per requirement - a probe exchange whose
``envelope.endpoint`` does not match the declared endpoint is a
blocking FAIL (a stand-in endpoint - e.g. ``get_stock_basic`` proving
``industry_taxonomy`` - can never again mark the gate PASS). Official
endpoint alternatives are declared EXPLICITLY as an ALTERNATIVE_GROUP
(e.g. the security-master listing surface: current snapshot
``get_code_list`` vs historical rebuild ``get_hist_code_list`` - either
satisfies the capability's endpoint proof).

Capability approval consumes the same contract (B1-04): each REQUIRED
requirement must have a persisted, tamper-checked endpoint proof case;
each ALTERNATIVE_GROUP must have at least one passing member case.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "ENDPOINT_REQUIREMENTS",
    "EndpointRequirement",
    "EndpointRequirementMode",
    "ProofRole",
    "endpoint_requirement_case_id",
    "endpoint_requirements_for",
    "validate_endpoint_requirements",
]


class EndpointRequirementMode(StrEnum):
    """How a requirement must be satisfied.

    - REQUIRED: this exact endpoint MUST be proven available.
    - ALTERNATIVE_GROUP: the declared group of endpoints are official
      alternatives of each other - at least ONE member must be proven.
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
    # security-master listing surface: the CURRENT snapshot
    # (get_code_list) and the HISTORICAL rebuild (get_hist_code_list)
    # are official alternatives of each other - either satisfies the
    # capability's endpoint proof (B1-01 ALTERNATIVE_GROUP semantics).
    EndpointRequirement(
        requirement_id="security_master:BaseData.get_code_list",
        capability="security_master",
        endpoint="BaseData.get_code_list",
        provider_dataset="code_list",
        mode=EndpointRequirementMode.ALTERNATIVE_GROUP,
        group_id="listing_surface",
    ),
    EndpointRequirement(
        requirement_id="security_master:BaseData.get_hist_code_list",
        capability="security_master",
        endpoint="BaseData.get_hist_code_list",
        provider_dataset="hist_code_list",
        mode=EndpointRequirementMode.ALTERNATIVE_GROUP,
        group_id="listing_surface",
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
    # index_daily: official endpoint is the kline surface with an
    # index code list (dataset label is the provider fact "daily_bar").
    EndpointRequirement(
        requirement_id="index_daily:MarketData.query_kline",
        capability="index_daily",
        endpoint="MarketData.query_kline",
        provider_dataset="daily_bar",
    ),
)


def validate_endpoint_requirements() -> list[str]:
    """Structural self-check of the contract. Returns the list of
    violations (empty = valid). Checked by the B1 structural guard
    test - a malformed contract can never silently ship."""
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
    return violations


def endpoint_requirements_for(capability: str) -> tuple[EndpointRequirement, ...]:
    """The ENDPOINT_PROOF requirements of one capability, declaration
    order preserved."""
    return tuple(
        req
        for req in ENDPOINT_REQUIREMENTS
        if req.capability == capability and req.proof_role is ProofRole.ENDPOINT_PROOF
    )


def endpoint_requirement_case_id(req: EndpointRequirement) -> str:
    """The proof case id of one requirement (consumed by the formal
    gate emitter AND by capability approval - single source of truth)."""
    return f"GATE-{req.requirement_id.replace(':', '-')}"
