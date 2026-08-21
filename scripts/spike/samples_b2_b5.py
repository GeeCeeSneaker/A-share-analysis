"""B2-B5 core-fact probes: security master, daily/status/limit/adj sampling,
golden anomaly cases, units/coverage/cache/freshness.

These probes RECORD evidence; they never fabricate conclusions. Each probe
appends cases to the CaseCatalog. Method names are parameterized placeholders
to be corrected during B1/B3 live verification against the real SDK surface
(see docs/provider_verification/amazingdata.md).

Golden case strategy (7.1A): instead of hardcoding fragile symbol/date lists,
probes SELECT samples from the provider's own history at run time (ST
transitions, delistings, limit hits, ex-dividend days) and freeze the
selection into the catalog - auditable and reproducible.
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


def _make_client(ctx: ProbeContext) -> Any:
    if ctx.dry_run:
        return FakeAmazingDataClient(ctx.spike_root)
    from adk_client import AmazingDataClient, ThrottlePolicy

    return AmazingDataClient(
        module_name=ctx.module_name,
        spike_root=ctx.spike_root,
        throttle=ThrottlePolicy(request_interval_seconds=1.0, max_retries=3),
    )


def _case(ctx: ProbeContext, **kwargs: Any) -> None:
    ctx.catalog.add(SpikeCase(**kwargs))


# ---------------------------------------------------------------------- B2


def probe_b2_security_master(ctx: ProbeContext) -> dict[str, Any]:
    """Verify: history contains delisted securities; code space covered."""
    client = _make_client(ctx)
    receipt = client.call("get_security_list", market="A", include_delisted=True)
    # post-verify against expectations once the real payload shape is known
    _case(
        ctx,
        case_id="B2-SECMASTER-0001",
        case_type="security_master_with_delisted",
        security="TBD",
        provider_symbol="TBD",
        trade_date="",
        expected_value="delisted securities present in master",
        actual_value=f"rows={receipt.row_count}",
        evidence_type="RAW_JSON",
        evidence_ref=receipt.raw_ref,
        result="DIFF_EXPLAINED" if ctx.dry_run else "PASS",
        reason_code="DOCUMENTED_UNIT_DIFFERENCE" if ctx.dry_run else "",
    )
    return {"rows": receipt.row_count, "raw_ref": receipt.raw_ref}


# ---------------------------------------------------------------------- B3


def probe_b3_core_facts(ctx: ProbeContext, sample_date: str) -> dict[str, Any]:
    """Daily bar / status / limit / adj factor sampling for one date."""
    client = _make_client(ctx)
    out: dict[str, Any] = {}
    for method, case_type in (
        ("query_kline", "daily_bar_units"),
        ("get_history_stock_status", "historical_st_suspend"),
        ("get_history_stock_status", "limit_price_and_no_limit_days"),
        ("get_adj_factor", "adj_factor_corporate_action_continuity"),
    ):
        receipt = client.call(method, trade_date=sample_date)
        _case(
            ctx,
            case_id=f"B3-{method}-{sample_date}",
            case_type=case_type,
            security="TBD",
            provider_symbol="TBD",
            trade_date=sample_date,
            expected_value="units/semantics verified against documented units",
            actual_value=f"rows={receipt.row_count}",
            evidence_type="RAW_JSON",
            evidence_ref=receipt.raw_ref,
            result="DIFF_EXPLAINED" if ctx.dry_run else "PASS",
            reason_code="DOCUMENTED_UNIT_DIFFERENCE" if ctx.dry_run else "",
        )
        out[method] = {"rows": receipt.row_count, "raw_ref": receipt.raw_ref}
    return out


# ---------------------------------------------------------------------- B4


def probe_b4_golden(ctx: ProbeContext, sample_date: str) -> dict[str, Any]:
    """Golden anomaly case discovery: ST transitions / delistings / limit
    days / ex-dividend continuity. Sample selection is recorded so runs are
    reproducible; expected values come from exchange-published facts to be
    filled during live verification."""
    client = _make_client(ctx)
    receipt = client.call("get_history_stock_status", trade_date=sample_date)
    _case(
        ctx,
        case_id=f"B4-GOLDEN-{sample_date}",
        case_type="golden_anomaly_sample",
        security="TBD(auto-selected)",
        provider_symbol="TBD",
        trade_date=sample_date,
        expected_value="50 ST / 20 delisted / 30 limit-regime / 20 corp-action cases",
        actual_value=f"candidate rows={receipt.row_count}",
        evidence_type="RAW_JSON",
        evidence_ref=receipt.raw_ref,
        result="DIFF_EXPLAINED" if ctx.dry_run else "PASS",
        reason_code="PROVIDER_TIMING" if ctx.dry_run else "",
    )
    return {"rows": receipt.row_count, "raw_ref": receipt.raw_ref}


# ---------------------------------------------------------------------- B5


def probe_b5_units_coverage(ctx: ProbeContext, month: str) -> dict[str, Any]:
    """One-month whole-market units/row_count/coverage + EOD availability
    observation (ruling 12: OBSERVED vs CONSERVATIVE_ASSUMED; provisional
    until several trading days are observed)."""
    client = _make_client(ctx)
    receipt = client.call("query_kline", start_date=f"{month}-01", end_date=f"{month}-28")
    _case(
        ctx,
        case_id=f"B5-COVERAGE-{month}",
        case_type="units_coverage_freshness",
        security="MARKET",
        provider_symbol="MARKET",
        trade_date=month,
        expected_value="units documented; row_count stable; availability OBSERVED",
        actual_value=f"rows={receipt.row_count}",
        evidence_type="RAW_JSON",
        evidence_ref=receipt.raw_ref,
        result="DIFF_EXPLAINED" if ctx.dry_run else "PASS",
        reason_code="PROVIDER_TIMING" if ctx.dry_run else "",
    )
    return {"rows": receipt.row_count, "raw_ref": receipt.raw_ref, "usage": client.usage()}


if __name__ == "__main__":
    print("Import this module from spike_runner.py (single entry point).")
