"""Canonical domain registry (CR-3, audit 20260901 sections 5/7).

The STATIC, versioned classification of every CR-2 provider-normalized
surface that could enter CR-3, and the typed natural key of each
canonical domain.

Rulings (audit CR3-P0-06 / section 7):

- every domain is EXPLICITLY classified as
  ``CANONICAL_SUPPORTED`` / ``AUXILIARY_ONLY`` /
  ``BLOCKED_PENDING_SEMANTICS`` / ``NOT_APPLICABLE`` - nothing is
  silently skipped;
- natural keys are derived ONLY from DTO fields with verified provider
  semantics; a domain lacking verified key semantics is
  ``BLOCKED_PENDING_SEMANTICS`` and NEVER guessed
  (index_daily: the provider INDEX_CODE carries no verified market
  attribution, so a deterministic index identity cannot be built;
  industry_member: the effective interval lacks a verified out_date
  semantics; equity_structure: report vs effective date semantics are
  B6-pending; corporate_action direct dividend/right-issue mappers are
  still BLOCKED_PENDING_MAPPER in CR-2 - CR-3 must NOT bypass them by
  reading Raw directly);
- ``security_master`` and the CA ``STATUS_FLAG_PROJECTION`` are
  ``AUXILIARY_ONLY``: the first feeds the governed identity bridge,
  the second is an evidence TIER below DIRECT_EVENT (CR3-P0-11) and
  must never be laundered into canonical corporate_action truth.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "CANONICAL_CONTRACT_VERSION",
    "CanonicalDomainSpec",
    "DomainEligibility",
    "domain_spec",
    "domain_specs",
    "supported_domains",
]


#: CR-3 canonical contract identity.
CANONICAL_CONTRACT_VERSION = "cr3-v1"


class DomainEligibility(StrEnum):
    CANONICAL_SUPPORTED = "CANONICAL_SUPPORTED"
    AUXILIARY_ONLY = "AUXILIARY_ONLY"
    BLOCKED_PENDING_SEMANTICS = "BLOCKED_PENDING_SEMANTICS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class CanonicalDomainSpec:
    """One canonical domain: its CR-2 source surface(s), output table,
    typed natural key and eligibility."""

    domain: str
    eligibility: DomainEligibility
    provider: str = "amazingdata"
    normalization_surface: str = ""
    provider_datasets: tuple[str, ...] = ()
    output_name: str = "main"
    #: CR-2 output columns promoted into canonical rows (order-stable)
    payload_fields: tuple[str, ...] = ()
    #: canonical natural-key field names (on the canonical row)
    key_fields: tuple[str, ...] = ()
    requires_security_identity: bool = False
    #: rationale recorded in the manifest for blocked/auxiliary domains
    note: str = ""


def _calendar_key(row: dict[str, Any], security_id: str | None) -> tuple[Any, ...]:
    return (str(row["market"]), str(row["trade_date"]))


def _bar_key(row: dict[str, Any], security_id: str | None) -> tuple[Any, ...]:
    return (str(security_id), str(row["trade_date"]))


def _factor_key(row: dict[str, Any], security_id: str | None) -> tuple[Any, ...]:
    return (str(security_id), str(row["ex_date"]), str(row["factor_type"]))


#: key builders exposed for tests
KEY_BUILDERS: dict[str, Callable[[dict[str, Any], str | None], tuple[Any, ...]]] = {
    "trade_calendar": _calendar_key,
    "daily_bar": _bar_key,
    "security_status": _bar_key,
    "limit_price": _bar_key,
    "adj_factor": _factor_key,
}


_DOMAIN_SPECS: tuple[CanonicalDomainSpec, ...] = (
    CanonicalDomainSpec(
        domain="trade_calendar",
        eligibility=DomainEligibility.CANONICAL_SUPPORTED,
        normalization_surface="trade_calendar",
        provider_datasets=("trade_calendar",),
        output_name="main",
        payload_fields=("market",),
        key_fields=("market", "trade_date"),
    ),
    CanonicalDomainSpec(
        domain="daily_bar",
        eligibility=DomainEligibility.CANONICAL_SUPPORTED,
        normalization_surface="daily_bar",
        provider_datasets=("daily_bar",),
        output_name="main",
        payload_fields=("open", "high", "low", "close", "pre_close", "volume", "amount"),
        key_fields=("security_id", "trade_date"),
        requires_security_identity=True,
    ),
    CanonicalDomainSpec(
        domain="security_status",
        eligibility=DomainEligibility.CANONICAL_SUPPORTED,
        normalization_surface="security_status_history",
        provider_datasets=("history_stock_status",),
        output_name="security_status",
        payload_fields=(
            "pre_close",
            "high_limited",
            "low_limited",
            "price_high_lmt_rate",
            "price_low_lmt_rate",
            "is_st_sec",
            "is_susp_sec",
            "is_wd_sec",
            "is_xr_sec",
        ),
        key_fields=("security_id", "trade_date"),
        requires_security_identity=True,
    ),
    CanonicalDomainSpec(
        domain="limit_price",
        eligibility=DomainEligibility.CANONICAL_SUPPORTED,
        normalization_surface="security_status_history",
        provider_datasets=("history_stock_status",),
        output_name="limit_price",
        payload_fields=("pre_close", "up_limit", "down_limit", "up_limit_rate", "down_limit_rate"),
        key_fields=("security_id", "trade_date"),
        requires_security_identity=True,
    ),
    CanonicalDomainSpec(
        domain="adj_factor",
        eligibility=DomainEligibility.CANONICAL_SUPPORTED,
        normalization_surface="adj_factor",
        provider_datasets=("adj_factor", "backward_factor"),
        output_name="main",
        payload_fields=("adj_factor", "backward_factor"),
        key_fields=("security_id", "ex_date", "factor_type"),
        requires_security_identity=True,
    ),
    # ---- auxiliary surfaces: consumed for governance, never canonical facts
    CanonicalDomainSpec(
        domain="security_master",
        eligibility=DomainEligibility.AUXILIARY_ONLY,
        normalization_surface="security_master",
        provider_datasets=("code_list", "hist_code_list", "stock_basic"),
        output_name="main",
        note=(
            "identity dataset only: feeds the governed provider-symbol -> "
            "security_id bridge; never emits canonical market-fact rows"
        ),
    ),
    CanonicalDomainSpec(
        domain="ca_projection",
        eligibility=DomainEligibility.AUXILIARY_ONLY,
        normalization_surface="security_status_history",
        provider_datasets=("history_stock_status",),
        output_name="corporate_action",
        note=(
            "STATUS_FLAG_PROJECTION evidence tier (CR3-P0-11): an auxiliary "
            "indicator surface, never equivalent to a DIRECT_EVENT corporate "
            "action truth while the direct dividend/right-issue mappers are "
            "BLOCKED_PENDING_MAPPER"
        ),
    ),
    # ---- blocked pending verified canonical semantics (never guessed)
    CanonicalDomainSpec(
        domain="corporate_action",
        eligibility=DomainEligibility.BLOCKED_PENDING_SEMANTICS,
        normalization_surface="corporate_action",
        provider_datasets=("corporate_action",),
        note=(
            "direct dividend/right-issue mappers are BLOCKED_PENDING_MAPPER "
            "in CR-2; CR-3 must not bypass them by reading Raw directly"
        ),
    ),
    CanonicalDomainSpec(
        domain="index_daily",
        eligibility=DomainEligibility.BLOCKED_PENDING_SEMANTICS,
        normalization_surface="index_daily",
        provider_datasets=("daily_bar",),
        output_name="main",
        note=(
            "provider INDEX_CODE carries no verified market attribution - "
            "a deterministic index identity cannot be built without guessing"
        ),
    ),
    CanonicalDomainSpec(
        domain="industry_member",
        eligibility=DomainEligibility.BLOCKED_PENDING_SEMANTICS,
        normalization_surface="industry_taxonomy",
        provider_datasets=("industry_taxonomy",),
        output_name="main",
        note=(
            "effective-interval semantics (out_date / current_sign "
            "interpretation) unverified - taxonomy owner is "
            "GALAXY_UNVERIFIED"
        ),
    ),
    CanonicalDomainSpec(
        domain="equity_structure",
        eligibility=DomainEligibility.BLOCKED_PENDING_SEMANTICS,
        normalization_surface="equity_structure",
        provider_datasets=("equity_structure",),
        output_name="main",
        note="report vs effective date semantics pending B6 verification",
    ),
    CanonicalDomainSpec(
        domain="bj_code_mapping",
        eligibility=DomainEligibility.BLOCKED_PENDING_SEMANTICS,
        normalization_surface="code_mapping_bj",
        provider_datasets=("code_mapping_bj",),
        note="BJ mapping identity surface has no verified mapper in CR-2",
    ),
    CanonicalDomainSpec(
        domain="industry_taxonomy_definition",
        eligibility=DomainEligibility.BLOCKED_PENDING_SEMANTICS,
        normalization_surface="industry_taxonomy",
        provider_datasets=("industry_taxonomy",),
        note=("taxonomy DEFINITION surface (industry_base_info) has no verified mapper in CR-2"),
    ),
)


_INDEX: dict[str, CanonicalDomainSpec] = {spec.domain: spec for spec in _DOMAIN_SPECS}


def domain_specs() -> tuple[CanonicalDomainSpec, ...]:
    """Read-only snapshot of the production domain matrix."""
    return _DOMAIN_SPECS


def domain_spec(domain: str) -> CanonicalDomainSpec:
    spec = _INDEX.get(domain)
    if spec is None:
        msg = f"unknown canonical domain {domain!r} - the domain matrix is static"
        raise KeyError(msg)
    return spec


def supported_domains() -> tuple[str, ...]:
    """Domains eligible to produce canonical rows (in matrix order)."""
    return tuple(
        spec.domain
        for spec in _DOMAIN_SPECS
        if spec.eligibility is DomainEligibility.CANONICAL_SUPPORTED
    )
