"""Provider capability registry (task book sections 3.1 / 10).

Discipline: an AmazingData capability that has not passed the REAL-account
Spike may only ever be CANDIDATE. Approval flow:
    real account -> spike -> golden -> provider verification ->
    source-policy dry-run -> APPROVED
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityStatus(StrEnum):
    CANDIDATE = "CANDIDATE"  # API surface exists; data NOT yet verified
    APPROVED = "APPROVED"  # real-account spike + golden passed
    RETIRED = "RETIRED"  # deprecated / replaced by another endpoint


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


def approve_capability(name: str, *, verified_at: str, account_profile_id: str) -> Capability:
    """Governance transition (only via explicit call - tests guard this)."""
    cap = CAPABILITY_REGISTRY[name]
    approved = Capability(
        name=cap.name,
        sdk_methods=cap.sdk_methods,
        canonical_domains=cap.canonical_domains,
        status=CapabilityStatus.APPROVED,
        verified_at=verified_at,
        account_profile_id=account_profile_id,
    )
    CAPABILITY_REGISTRY[name] = approved
    return approved
