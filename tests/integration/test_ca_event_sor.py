"""R4-A2.4 P0-05: Corporate-action EVENT source of record tests.

The CA evidence combination includes an EVENT FACT SOURCE (provider
dividend/right-issue records) - the adj-factor stream alone can NEVER
prove an event (audit section 6.2):
  - adj-only (no event record)            -> VALIDATED_FAIL(EVENT_SOURCE_MISSING)
  - event record exists but EX_DATE != T  -> VALIDATED_FAIL(EVENT_DATE_MISMATCH)
  - event + adj + kline all consistent    -> VALIDATED_PASS
  - suspension on the event day           -> NOT_TESTABLE_TIME(SUSPENSION)
  - the domain bundle lists the dividend exchange (event lineage closes)
"""

from __future__ import annotations

from pathlib import Path

from ashare_state.providers.exchange import ProviderExchange
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.golden_router import route_all
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run, verify_evidence_closure
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.validators import GoldenCase

_SHA = "f" * 40


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


def _ca_case(case_id: str, symbol: str, trade_date: str) -> GoldenCase:
    return GoldenCase(
        golden_case_id=case_id,
        case_type="golden_corporate_action",
        provider_symbol=symbol,
        trade_date=trade_date,
        truth_source="test-truth",
        source_ref="test-source",
        expected_fields={"IS_WD_SEC": True},
        # R4-A2.6 P0-02: the formal CA type resolves from event_class
        event_class="DIVIDEND_EX_DATE",
    )


def _route_one(ctx, symbol: str, trade_date: str):
    outcomes = route_all(ctx, [_ca_case("GT-CA-X", symbol, trade_date)])
    assert len(outcomes) == 1
    _case, outcome, evidence = outcomes[0]
    return outcome, evidence


class TestEventSourceRequired:
    def test_consistent_event_adj_kline_passes(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, evidence = _route_one(ctx, "600519.SH", "20220630")
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert outcome.validator_id == "corp_action_context_v2"
        # bundle lineage includes the dividend event exchange
        assert evidence.get("bundle") is True
        bundle_path = ctx.store.spike_root / evidence["evidence_ref"]
        import json

        doc = json.loads(bundle_path.read_text(encoding="utf-8"))
        endpoints = {e["endpoint"] for e in doc["exchanges"]}
        assert "InfoData.get_dividend" in endpoints
        assert "BaseData.get_adj_factor" in endpoints
        assert "MarketData.query_kline" in endpoints
        assert "BaseData.get_calendar" in endpoints

    def test_adj_only_never_passes(self, tmp_path: Path):
        """No provider event record -> FAIL even though the adj factor
        transitions exactly at T (adj movement alone is not an event SoR)."""

        class _NoEventsTarget(FakeTarget):
            def get_dividend_exchange(self, code_list):
                from ashare_state.spike.target import _fake_exchange

                self._mark("get_dividend")
                return _fake_exchange(
                    "InfoData.get_dividend",
                    "corporate_action",
                    [],
                    params={"code_list": list(code_list)},
                )

        ctx = _ctx(tmp_path, target=_NoEventsTarget())
        outcome, _evidence = _route_one(ctx, "600519.SH", "20220630")
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_SOURCE_MISSING"
        assert "not a sufficient event SoR" in outcome.actual

    def test_event_date_mismatch_fails(self, tmp_path: Path):
        """Event records exist for the symbol but none matches the case's
        exact event date (e.g. a different dividend)."""

        class _WrongDateTarget(FakeTarget):
            def get_dividend_exchange(self, code_list):
                from ashare_state.spike.target import _fake_exchange

                self._mark("get_dividend")
                rows = [
                    {
                        "SECURITY_CODE": code.split(".")[0],
                        "EX_DATE": "20230627",  # the OTHER ex-date, not T
                        "EVENT_TYPE": "DIVIDEND",
                    }
                    for code in code_list
                    if code in ("600519.SH",)
                ]
                return _fake_exchange(
                    "InfoData.get_dividend",
                    "corporate_action",
                    rows,
                    params={"code_list": list(code_list)},
                )

        ctx = _ctx(tmp_path, target=_WrongDateTarget())
        outcome, _evidence = _route_one(ctx, "600519.SH", "20220630")
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_DATE_MISMATCH"

    def test_suspension_on_event_day_is_not_testable(self, tmp_path: Path):
        class _SuspendedTarget(FakeTarget):
            def query_kline_exchange(
                self, code_list, *, begin_date, end_date, kline_type, trading_days=None
            ):
                exchange = super().query_kline_exchange(
                    code_list,
                    begin_date=begin_date,
                    end_date=end_date,
                    kline_type=kline_type,
                    trading_days=trading_days,
                )
                payload = [r for r in exchange.payload if str(r["KLINE_TIME"]) != "20220630"]
                return ProviderExchange(envelope=exchange.envelope, payload=payload)

            def get_history_stock_status_exchange(self, start_date, end_date, code_list):
                exchange = super().get_history_stock_status_exchange(
                    start_date, end_date, code_list
                )
                payload = [
                    (
                        {**r, "IS_SUSP_SEC": 1}
                        if r.get("SECURITY_CODE") == "600519"
                        and str(r.get("TRADE_DATE")) == "20220630"
                        else r
                    )
                    for r in exchange.payload
                ]
                return ProviderExchange(envelope=exchange.envelope, payload=payload)

        ctx = _ctx(tmp_path, target=_SuspendedTarget())
        outcome, _evidence = _route_one(ctx, "600519.SH", "20220630")
        assert outcome.result is CaseResult.NOT_TESTABLE_TIME
        assert outcome.reason_code == "SUSPENSION_AT_EVENT"

    def test_event_bundle_evidence_closes(self, tmp_path: Path):
        """The event-source exchange is part of the closing bundle: case
        evidence closure re-verifies meta AND every declared payload."""
        ctx = _ctx(tmp_path)
        cases = [
            _ca_case("GT-CA-CL", "600519.SH", "20220630"),
            _ca_case("GT-CA-CL2", "600519.SH", "20230627"),
        ]
        for case, outcome, evidence in route_all(ctx, cases):
            ctx.case(
                case_id=case.golden_case_id,
                case_type=case.case_type,
                security=case.provider_symbol,
                provider_symbol=case.provider_symbol,
                trade_date=case.trade_date,
                expected=case.truth_source,
                actual=outcome.actual,
                result=outcome.result,
                evidence_meta=evidence,
            )
        ctx.catalog.flush(ctx.store.run_dir(ctx.run))
        assert verify_evidence_closure(ctx.store, ctx.run, ctx.catalog) == []
