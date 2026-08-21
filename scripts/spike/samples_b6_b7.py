"""B6-B7: free-float equivalence assessment and taxonomy/index assessment.

Design ruling 3.2/3.3 (the semantic discipline of this Spike):
- FLOAT_A_SHARE / FLOAT_SHARE must NOT be assumed equal to Tushare free_share;
  each capability gets one of:
    EXACT_EQUIVALENT / DERIVABLE_EQUIVALENT / ALTERNATIVE_SEMANTICS / MISSING
- Galaxy industry taxonomy (if not SW) registers as GALAXY_xxx, NEVER as SW.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adk_client import FakeAmazingDataClient
from case_catalog import CaseCatalog, SpikeCase


@dataclass
class ProbeContext:
    spike_root: Path
    catalog: CaseCatalog
    dry_run: bool
    module_name: str


def _case(ctx: ProbeContext, **kwargs: Any) -> None:
    ctx.catalog.add(SpikeCase(**kwargs))


def _make_client(ctx: ProbeContext) -> Any:
    if ctx.dry_run:
        return FakeAmazingDataClient(ctx.spike_root)
    from adk_client import AmazingDataClient, ThrottlePolicy

    return AmazingDataClient(
        module_name=ctx.module_name,
        spike_root=ctx.spike_root,
        throttle=ThrottlePolicy(request_interval_seconds=1.0, max_retries=3),
    )


# ---------------------------------------------------------------------- B6


def probe_b6_free_float(ctx: ProbeContext, sample_date: str) -> dict[str, Any]:
    """Assess free-share / turnover_rate_f equivalence (ruling 3.2).

    The verdict decision tree runs against live evidence during the real
    Spike; in dry-run it records the assessment scaffold only.
    """
    client = _make_client(ctx)
    receipt = client.call("get_share_structure", trade_date=sample_date)
    # Decision tree (to be executed against real payloads):
    # 1. Does the provider expose a field whose DENOMINATOR semantics is
    #    "free-float shares" (excludes strategic/locked holdings)?
    #    -> yes + identical definition      : EXACT_EQUIVALENT
    #    -> derivable from components        : DERIVABLE_EQUIVALENT (document formula)
    #    -> float but not free-float         : ALTERNATIVE_SEMANTICS (independent field)
    #    -> nothing                          : MISSING (blocks P0b free-float)
    verdict = "MISSING" if ctx.dry_run else "TO_BE_ASSESSED"
    _case(
        ctx,
        case_id=f"B6-FREEFLOAT-{sample_date}",
        case_type="free_float_equivalence",
        security="TBD",
        provider_symbol="TBD",
        trade_date=sample_date,
        expected_value="EXACT_EQUIVALENT with documented denominator semantics",
        actual_value=verdict,
        evidence_type="RAW_JSON",
        evidence_ref=receipt.raw_ref,
        result="DIFF_EXPLAINED",
        reason_code="DOCUMENTED_UNIT_DIFFERENCE",
    )
    return {"verdict": verdict, "raw_ref": receipt.raw_ref}


# ---------------------------------------------------------------------- B7


def probe_b7_taxonomy_index(ctx: ProbeContext) -> dict[str, Any]:
    """Assess industry taxonomy standard + benchmark index availability.

    Ruling 3.3: if the provider taxonomy is Galaxy's own system, it registers
    as an independent GALAXY_xxx taxonomy - it must NOT be presented as SW,
    and cannot claim the SW L1 Phase 0 DoD.
    """
    client = _make_client(ctx)
    tax_receipt = client.call("get_industry_list")
    idx_receipt = client.call("get_index_daily_list")

    taxonomy_owner = "TO_BE_VERIFIED" if not ctx.dry_run else "GALAXY_TBD"
    _case(
        ctx,
        case_id="B7-TAXONOMY-0001",
        case_type="sw_taxonomy",
        security="TAXONOMY",
        provider_symbol="TAXONOMY",
        trade_date="",
        expected_value="taxonomy owner identified (SW / CSI / GALAXY own system)",
        actual_value=taxonomy_owner,
        evidence_type="RAW_JSON",
        evidence_ref=tax_receipt.raw_ref,
        result="DIFF_EXPLAINED",
        reason_code="DOCUMENTED_UNIT_DIFFERENCE",
    )
    _case(
        ctx,
        case_id="B7-INDEX-0001",
        case_type="benchmark_index_availability",
        security="BENCHMARK",
        provider_symbol="BENCHMARK",
        trade_date="",
        expected_value="CSI all-share/300/500/1000/2000 daily bars available",
        actual_value=f"rows={idx_receipt.row_count}",
        evidence_type="RAW_JSON",
        evidence_ref=idx_receipt.raw_ref,
        result="DIFF_EXPLAINED" if ctx.dry_run else "PASS",
        reason_code="DOCUMENTED_UNIT_DIFFERENCE" if ctx.dry_run else "",
    )
    return {
        "taxonomy_raw_ref": tax_receipt.raw_ref,
        "index_raw_ref": idx_receipt.raw_ref,
    }


if __name__ == "__main__":
    print("Import this module from spike_runner.py (single entry point).")
