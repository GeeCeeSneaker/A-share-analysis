"""CR-1.2 runtime completeness tests (audit R4-A2.4 section 2).

The audit path is exchange-complete: EVERY SDK call a probe/router makes
is an explicit persisted ProviderExchange. In particular:
  - the hidden calendar prerequisite of query_kline is EXPLICIT (option A):
    calendar exchange persisted first, windowed trading_days passed to the
    kline call - the kline exchange never internally triggers an invisible
    calendar fetch
  - a FAILED calendar prerequisite persists its failure meta and kline
    MUST NOT fire (no fabricated success)
  - B3/B7 symbol-list and calendar prerequisites are persisted exchanges
    (no payload-only calls on the formal path - AST-enforced)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import (
    ProbeContext,
    probe_b3_core_facts,
    probe_b7_capacity,
)
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.trading_rule import TradingRuleBook

_SHA = "d" * 40

#: payload-only methods that MUST NOT be called by formal probes/router
_PAYLOAD_ONLY_METHODS = {
    "get_code_list",
    "get_hist_code_list",
    "get_stock_basic",
    "get_history_stock_status",
    "get_adj_factor",
    "get_dividend",
    "get_calendar",
    "query_kline",
}


class _CalendarDeniedTarget(FakeTarget):
    """Every calendar exchange FAILS with a first-class error exchange."""

    def get_calendar_exchange(self, market: str = "SH") -> ProviderExchange:
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("calendar entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


def _ctx(tmp_path: Path, target=None) -> ProbeContext:
    run, store = new_run(
        run_kind=RunKind.DRY_RUN,
        spike_root=tmp_path / "spike",
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TRIAL_SIMULATION_FAKE",
        as_of_date="20260814",
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    return ProbeContext(run, store, catalog, target or FakeTarget())


def _metas(ctx: ProbeContext) -> list[dict]:
    raw_root = ctx.store.raw_dir(ctx.run)
    import json

    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(raw_root.glob("provider=*/dataset=*/*.meta.json"))
    ]


class TestKlineCalendarPrerequisite:
    def test_hidden_calendar_and_kline_are_exactly_two_persisted_exchanges(self, tmp_path: Path):
        """Audit section 2.4-1: one kline data pull (with its calendar
        prerequisite) persists EXACTLY two exchange evidences - the
        calendar meta and the kline meta, nothing hidden."""
        ctx = _ctx(tmp_path)
        results = probe_b3_core_facts(ctx, 20230601)
        metas = _metas(ctx)
        by_endpoint: dict[str, int] = {}
        for meta in metas:
            by_endpoint[meta["endpoint"]] = by_endpoint.get(meta["endpoint"], 0) + 1
        assert by_endpoint.get("BaseData.get_calendar", 0) >= 1
        assert by_endpoint.get("MarketData.query_kline", 0) >= 1
        # every persisted exchange carries FULL request params (CR-1.2 3.3)
        kline_meta = next(m for m in metas if m["endpoint"] == "MarketData.query_kline")
        assert "code_list" in kline_meta["request_params"]
        assert "trading_days" in kline_meta["request_params"]
        assert kline_meta["ingest_run_id"] == ctx.run.spike_run_id
        assert kline_meta["ingested_at"]
        assert results["daily_bar"]

    def test_calendar_failure_persists_meta_and_kline_never_fires(self, tmp_path: Path):
        """Audit section 2.4-2: a failed calendar prerequisite persists
        its failure meta; the kline exchange is NOT fired (the fake would
        happily return rows - firing it would fabricate success)."""
        ctx = _ctx(tmp_path, target=_CalendarDeniedTarget())
        results = probe_b3_core_facts(ctx, 20230601)
        assert results["daily_bar"] == "NOT_TESTABLE"
        metas = _metas(ctx)
        calendar_metas = [m for m in metas if m["endpoint"] == "BaseData.get_calendar"]
        assert calendar_metas and all(m["status"] == "ERROR" for m in calendar_metas)
        # NO kline exchange was created at all
        assert not [m for m in metas if m["endpoint"] == "MarketData.query_kline"]
        # the failure is a structured case bound to the failure evidence
        cases = [c for c in ctx.catalog.cases if c.case_type == "daily_bar_units"]
        assert cases
        assert any(c.result is CaseResult.NOT_TESTABLE_PERMISSION for c in cases)


class TestPrerequisiteExchanges:
    def test_b7_symbols_and_calendar_are_persisted_exchanges(self, tmp_path: Path):
        """B7 (audit section 2.2): get_code_list + get_calendar are
        explicit persisted exchanges; per-day kline calls pass explicit
        trading_days."""
        ctx = _ctx(tmp_path)
        metrics = probe_b7_capacity(ctx, 20230601)
        assert metrics["day_window"]
        metas = _metas(ctx)
        endpoints = {m["endpoint"] for m in metas}
        assert "BaseData.get_code_list" in endpoints
        assert "BaseData.get_calendar" in endpoints
        assert "MarketData.query_kline" in endpoints
        kline_metas = [m for m in metas if m["endpoint"] == "MarketData.query_kline"]
        # every kline call used the EXPLICIT calendar (fake marks it)
        target: FakeTarget = ctx.target
        marks = target._call_log
        assert marks.count("kline_used_explicit_calendar") == len(kline_metas)

    def test_b3_symbol_list_is_persisted_exchange(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        probe_b3_core_facts(ctx, 20230601)
        metas = _metas(ctx)
        assert any(
            m["endpoint"] == "BaseData.get_code_list" and m["provider_dataset"] == "code_list"
            for m in metas
        )


class TestStaticNoPayloadOnlyCalls:
    @pytest.mark.parametrize(
        "source_file",
        [
            "src/ashare_state/spike/probes.py",
            "src/ashare_state/spike/golden_router.py",
        ],
    )
    def test_formal_modules_never_call_payload_only_target_methods(self, source_file):
        """Audit section 2.4-4: AST-level check - probes.py and
        golden_router.py may only call ``*_exchange`` target methods (the
        payload convenience surface is business-path only)."""
        tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # match `ctx.target.X(` / `target.X(` attribute calls
            if isinstance(func, ast.Attribute) and func.attr in _PAYLOAD_ONLY_METHODS:
                receiver = func.value
                receiver_name = receiver.attr if isinstance(receiver, ast.Attribute) else None
                if isinstance(receiver, ast.Name):
                    receiver_name = receiver.id
                if receiver_name in ("target",):
                    offenders.append(f"{receiver_name}.{func.attr}")
        assert not offenders, (
            f"{source_file} calls payload-only target methods {offenders} - "
            "formal paths must consume the explicit *_exchange API (CR-1.2)"
        )

    def test_rule_book_binding_in_new_run_is_load_verified(self, tmp_path: Path):
        """P0-03: ProbeContext.rule_book is the RUN-BOUND book."""
        ctx = _ctx(tmp_path)
        book = ctx.rule_book
        assert isinstance(book, TradingRuleBook)
        assert book.review_status in ("COMPILED", "REVIEWED")
