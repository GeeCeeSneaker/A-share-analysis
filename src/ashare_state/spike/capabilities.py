"""Spike capability definitions: Gate Contract == Probe Contract (R2 §8).

Every core capability declares the case types its verdict REQUIRES; the
verdict first checks coverage == 100%. Missing coverage is
SPIKE_INCOMPLETE (not NO_GO); NO_GO is reserved for "adequately verified
and genuinely failed".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpikeCapabilityDefinition:
    capability_id: str
    core: bool  # core capabilities gate P0a
    required_case_types: tuple[str, ...]
    min_valid_cases: int = 1
    validator_id: str = ""
    blocking_rule: str = "CORE_FAIL_BLOCKS_P0A"  # informational
    description: str = ""


CORE_CAPABILITIES: tuple[SpikeCapabilityDefinition, ...] = (
    SpikeCapabilityDefinition(
        capability_id="security_master_with_delisted",
        core=True,
        # R3-P0-13: golden delisted cases are REQUIRED for the core gate
        required_case_types=("security_master_with_delisted", "golden_delisted"),
        min_valid_cases=20,  # 20 delisted golden cases (task book 7.1A)
        validator_id="security_master_delisted_v1",
        description="master must contain delisted securities (survivorship)",
    ),
    SpikeCapabilityDefinition(
        capability_id="daily_bar_units",
        core=True,
        required_case_types=("daily_bar_units",),
        min_valid_cases=1,
        validator_id="daily_bar_units_v2",
        description="volume/amount units verified between independent sources",
    ),
    SpikeCapabilityDefinition(
        capability_id="historical_st_suspend",
        core=True,
        required_case_types=("historical_st_suspend", "golden_st_transition"),
        min_valid_cases=50,  # 50 ST cap/removal golden cases
        validator_id="st_suspend_v2",
        description="daily ST/suspension semantics correct vs golden facts",
    ),
    SpikeCapabilityDefinition(
        capability_id="limit_price_and_no_limit_days",
        core=True,
        required_case_types=("limit_price_and_no_limit_days", "golden_limit_regime"),
        min_valid_cases=30,  # 30 limit-regime golden cases
        validator_id="limit_rule_v2",
        description="limit prices match the exchange regime (board rates)",
    ),
    SpikeCapabilityDefinition(
        capability_id="adj_factor_corporate_action_continuity",
        core=True,
        required_case_types=(
            "adj_factor_corporate_action_continuity",
            "golden_corporate_action",
        ),
        min_valid_cases=20,  # 20 corporate-action golden cases
        validator_id="adj_continuity_v2",
        description="adj factor + corporate action price continuity",
    ),
    SpikeCapabilityDefinition(
        capability_id="history_start_2018_plus_warmup",
        core=True,
        required_case_types=("history_start_2018_plus_warmup",),
        min_valid_cases=1,
        validator_id="history_coverage_v1",
        description="history depth covers 2018 + warmup to 2014/2015",
    ),
    SpikeCapabilityDefinition(
        capability_id="symbol_mapping_unambiguous",
        core=True,
        required_case_types=("symbol_mapping_unambiguous",),
        min_valid_cases=1,
        validator_id="symbol_mapping_v2",
        description="provider symbol mapping unambiguous incl. BJ old/new codes",
    ),
    SpikeCapabilityDefinition(
        capability_id="sdk_permission_cache_freshness",
        core=True,
        required_case_types=("sdk_permission_cache_freshness",),
        min_valid_cases=1,
        validator_id="sdk_behavior_v2",
        description="SDK permission/cache/freshness behavior recorded & verified",
    ),
)

OPTIONAL_CAPABILITIES: tuple[SpikeCapabilityDefinition, ...] = (
    SpikeCapabilityDefinition(
        capability_id="free_float_equivalence",
        core=False,
        required_case_types=("free_float_equivalence",),
        validator_id="free_float_equivalence_v1",
        description="four-level equivalence vs Tushare free_share semantics",
    ),
    SpikeCapabilityDefinition(
        capability_id="sw_taxonomy",
        core=False,
        required_case_types=("sw_taxonomy",),
        validator_id="taxonomy_owner_v1",
        description="industry taxonomy owner identified (SW vs GALAXY)",
    ),
    SpikeCapabilityDefinition(
        capability_id="benchmark_index_availability",
        core=False,
        required_case_types=("benchmark_index_availability",),
        validator_id="benchmark_index_v1",
        description="benchmark index daily bars available",
    ),
    SpikeCapabilityDefinition(
        capability_id="capacity_backfill",
        core=False,
        required_case_types=("capacity_backfill",),
        validator_id="capacity_v1",
        description="ALL_A x 1 month capacity/backfill metrics (R2 section 9)",
    ),
)

ALL_CAPABILITIES: tuple[SpikeCapabilityDefinition, ...] = CORE_CAPABILITIES + OPTIONAL_CAPABILITIES


@dataclass(frozen=True)
class CoverageReport:
    capability_id: str
    core: bool
    covered_case_types: tuple[str, ...]
    missing_case_types: tuple[str, ...]
    pass_count: int
    fail_count: int


def coverage(
    definitions: tuple[SpikeCapabilityDefinition, ...],
    case_stats: dict[str, dict[str, int]],
) -> list[CoverageReport]:
    """Coverage of required case types + pass/fail counts per capability."""
    reports: list[CoverageReport] = []
    for cap in definitions:
        covered: list[str] = []
        missing: list[str] = []
        pass_count = 0
        fail_count = 0
        for case_type in cap.required_case_types:
            bucket = case_stats.get(case_type)
            if not bucket:
                missing.append(case_type)
                continue
            covered.append(case_type)
            pass_count += bucket.get("VALIDATED_PASS", 0)
            pass_count += bucket.get("DIFF_EXPLAINED", 0)  # equivalence decided per-case
            fail_count += bucket.get("VALIDATED_FAIL", 0)
        reports.append(
            CoverageReport(
                capability_id=cap.capability_id,
                core=cap.core,
                covered_case_types=tuple(covered),
                missing_case_types=tuple(missing),
                pass_count=pass_count,
                fail_count=fail_count,
            )
        )
    return reports
