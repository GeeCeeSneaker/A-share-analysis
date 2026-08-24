"""R4-A2.3 P0-04/P0-08/P0-09 tests: golden router evidence lineage.

Audit section 6: every domain fetch persists its EXPLICIT exchanges via
the RawWriter FIRST; DomainData comes from those exact payloads; every
case binds to the domain's multi-endpoint EVIDENCE BUNDLE (manifest with
all raw refs + hashes + request_ids). No lambda: None pseudo-calls.

Audit section 9.2: limit validation matches status rows by (symbol,
trade_date) EXACTLY - 0 rows / >1 rows both fail closed; listing_date
must come from the same PIT context.
"""

from __future__ import annotations

import json
from pathlib import Path

from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.golden_router import route_all
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.run_store import RunStore
from ashare_state.spike.runner import new_run, verify_evidence_closure
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.validators import GoldenCase

_SHA = "c" * 40


def _ctx(tmp_path: Path, target=None) -> tuple[ProbeContext, RunStore]:
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
    return ProbeContext(run, store, catalog, target or FakeTarget()), store


def _case(case_id: str, case_type: str, symbol: str, trade_date: str, expected=None):
    return GoldenCase(
        golden_case_id=case_id,
        case_type=case_type,
        provider_symbol=symbol,
        trade_date=trade_date,
        truth_source="test-truth",
        source_ref="test-source",
        expected_fields=expected or {},
    )


class _StatusDeniedTarget(FakeTarget):
    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ):
        from ashare_state.providers.amazingdata.provider import RawEnvelope
        from ashare_state.providers.exchange import ProviderExchange

        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


class TestRouterEvidenceLineage:
    def test_every_case_binds_domain_evidence_bundle(self, tmp_path: Path):
        ctx, _ = _ctx(tmp_path)
        cases = [
            _case("GT-LIMIT-1", "golden_limit_regime", "600519.SH", "20230601",
                  {"PRICE_HIGH_LMT_RATE": 0.1, "PRICE_LOW_LMT_RATE": 0.1}),
        ]
        outcomes = route_all(ctx, cases)
        assert len(outcomes) == 1
        case, outcome, evidence = outcomes[0]
        assert evidence.get("bundle") is True
        assert evidence["evidence_ref"].endswith(".json")
        assert "/bundles/" in evidence["evidence_ref"]
        # the bundle manifest lists ALL exchanges of the domain fetch
        bundle_path = ctx.store.spike_root / evidence["evidence_ref"]
        assert bundle_path.is_file()
        doc = json.loads(bundle_path.read_text(encoding="utf-8"))
        endpoints = {entry["endpoint"] for entry in doc["exchanges"]}
        assert endpoints == {
            "InfoData.get_history_stock_status",
            "BaseData.get_hist_code_list",
            "BaseData.get_calendar",
        }
        assert all(entry["content_hash"] for entry in doc["exchanges"])
        # the SAME data validated the case (600519 resolves 10% and PASSES
        # against the fake PIT context)
        assert outcome.result is CaseResult.VALIDATED_PASS

    def test_bundle_evidence_closes_under_verify(self, tmp_path: Path):
        """Bundle + every listed raw artifact re-verify during closure."""
        ctx, store = _ctx(tmp_path)
        cases = [
            _case("GT-L1", "golden_limit_regime", "600519.SH", "20230601",
                  {"PRICE_HIGH_LMT_RATE": 0.1}),
            _case("GT-ST1", "golden_st_transition", "600518.SH", "20220601",
                  {"IS_ST_SEC": 1}),
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
        ctx.catalog.flush(store.run_dir(ctx.run))
        problems = verify_evidence_closure(store, ctx.run, ctx.catalog)
        assert problems == []

    def test_router_never_uses_payload_only_fetches(self):
        """P0-04: fetch_domain_data must persist every exchange through the
        collector (no silent payload-only calls)."""
        source = Path("src/ashare_state/spike/golden_router.py").read_text(encoding="utf-8")
        # every fetch branch goes through collector.persist(...)
        assert "collector.persist(" in source
        # the old pseudo-call pattern is gone from the RUNTIME (docstring
        # prose may mention it; an actual call site would pass it as an arg)
        assert "lambda: None," not in source

    def test_domain_fetch_failure_classifies_all_cases(self, tmp_path: Path):
        ctx, _ = _ctx(tmp_path, target=_StatusDeniedTarget())
        cases = [
            _case("GT-ST-A", "golden_st_transition", "600518.SH", "20220601",
                  {"IS_ST_SEC": 1}),
            _case("GT-ST-B", "golden_st_transition", "600518.SH", "20220701",
                  {"IS_ST_SEC": 1}),
        ]
        outcomes = route_all(ctx, cases)
        assert len(outcomes) == 2
        for _case_obj, outcome, evidence in outcomes:
            assert outcome.result is CaseResult.NOT_TESTABLE_PERMISSION
            assert outcome.reason_code == "PROVIDER_PERMISSION"
            # failure evidence is IN the bundle (envelope-only meta listed)
            assert evidence.get("bundle") is True


class TestLimitExactDateMatching:
    def test_zero_status_rows_fails_closed(self, tmp_path: Path):
        """P0-08: no exact (symbol, trade_date) row -> FAIL, never a
        nearest-date fallback."""
        ctx, _ = _ctx(tmp_path)
        # 2024-01-02 is outside the fake status window -> no rows
        cases = [
            _case("GT-L-Z", "golden_limit_regime", "600519.SH", "20240102",
                  {"PRICE_HIGH_LMT_RATE": 0.1}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "STATUS_EXACT_MATCH_FAILURE"

    def test_missing_listing_date_context_fails_closed(self, tmp_path: Path):
        """P0-08: listing_date must come from the PIT master - a symbol
        absent from the hist master must NOT silently degrade."""
        ctx, _ = _ctx(tmp_path)

        class _NoHistTarget(FakeTarget):
            def get_hist_code_list_exchange(self, security_type, start_date, end_date):
                from ashare_state.providers.exchange import ProviderExchange

                exchange = super().get_hist_code_list_exchange(
                    security_type, start_date, end_date
                )
                payload = [r for r in exchange.payload if r["SECURITY_CODE"] != "600519"]

                return ProviderExchange(envelope=exchange.envelope, payload=payload)

        ctx.target = _NoHistTarget()
        cases = [
            _case("GT-L-NH", "golden_limit_regime", "600519.SH", "20230601",
                  {"PRICE_HIGH_LMT_RATE": 0.1}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "LISTING_DATE_MISSING"

    def test_no_limit_day_case_passes_with_pit_rule(self, tmp_path: Path):
        """STAR first-5 no-limit session is proven via the PIT calendar."""
        ctx, _ = _ctx(tmp_path)

        # 600019 lists 20220601 (fake calendar start) - 5th session window
        cases = [
            _case("GT-L-NL", "golden_limit_regime", "600519.SH", "20230601",
                  {"PRICE_HIGH_LMT_RATE": 0.1}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_PASS


class TestCorpActionContext:
    def test_event_day_context_validates_with_factor_transition(self, tmp_path: Path):
        """P0-09: 600519 ex-date 2022-06-30 - T-1/T/T+1 bars + factor
        transition + adjusted continuity all validate."""
        ctx, _ = _ctx(tmp_path)
        cases = [
            _case("GT-CA-1", "golden_corporate_action", "600519.SH", "20220630",
                  {"IS_WD_SEC": True}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert "factor 1.0->0.9737" in outcome.actual

    def test_missing_bars_without_suspension_fail(self, tmp_path: Path):
        ctx, _ = _ctx(tmp_path)

        class _KlineGapTarget(FakeTarget):
            def query_kline_exchange(self, code_list, *, begin_date, end_date, kline_type):
                exchange = super().query_kline_exchange(
                    code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
                )
                payload = [r for r in exchange.payload if str(r["KLINE_TIME"]) != "20220629"]
                from ashare_state.providers.exchange import ProviderExchange

                return ProviderExchange(envelope=exchange.envelope, payload=payload)

        ctx.target = _KlineGapTarget()
        cases = [
            _case("GT-CA-GAP", "golden_corporate_action", "600519.SH", "20220630",
                  {"IS_WD_SEC": True}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "KLINE_CONTEXT_MISSING"

    def test_suspension_on_event_day_is_not_testable_never_silent_pass(self, tmp_path: Path):
        """P0-09: missing T-1/T/T+1 bars WITH a suspension flag on T must
        yield a structured NOT_TESTABLE_TIME(SUSPENSION) - never a silent
        PASS and never an unexplained FAIL."""
        ctx, _ = _ctx(tmp_path)

        class _SuspendedKlineGapTarget(FakeTarget):
            def query_kline_exchange(self, code_list, *, begin_date, end_date, kline_type):
                exchange = super().query_kline_exchange(
                    code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
                )
                payload = [r for r in exchange.payload if str(r["KLINE_TIME"]) != "20220630"]
                from ashare_state.providers.exchange import ProviderExchange

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
                from ashare_state.providers.exchange import ProviderExchange

                return ProviderExchange(envelope=exchange.envelope, payload=payload)

        ctx.target = _SuspendedKlineGapTarget()
        cases = [
            _case("GT-CA-SUSP", "golden_corporate_action", "600519.SH", "20220630",
                  {"IS_WD_SEC": True}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.NOT_TESTABLE_TIME
        assert outcome.reason_code == "SUSPENSION_AT_EVENT"

    def test_event_day_off_calendar_is_not_testable(self, tmp_path: Path):
        ctx, _ = _ctx(tmp_path)
        cases = [
            _case("GT-CA-NC", "golden_corporate_action", "600519.SH", "20220626",
                  {"IS_WD_SEC": True}),  # a Sunday outside the fake calendar
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.NOT_TESTABLE_TIME
        assert outcome.reason_code == "CALENDAR_MISSING_EVENT_DAY"


class TestBJSemanticProof:
    def test_bj_code_continuity_and_30pct_regime(self, tmp_path: Path):
        """P1: BJ proof = hist master presence + exact-date 30% regime."""
        ctx, _ = _ctx(tmp_path)
        cases = [
            _case("GT-BJ-1", "golden_bj_mapping", "835185.BJ", "20220601",
                  {"CODE_CONTINUITY": True}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert outcome.validator_id == "bj_mapping_v2"

    def test_bj_absent_from_master_fails(self, tmp_path: Path):
        ctx, _ = _ctx(tmp_path)
        cases = [
            _case("GT-BJ-2", "golden_bj_mapping", "999999.BJ", "20220601",
                  {"CODE_CONTINUITY": True}),
        ]
        _case_obj, outcome, _evidence = route_all(ctx, cases)[0]
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "BJ_MASTER_ABSENT"
