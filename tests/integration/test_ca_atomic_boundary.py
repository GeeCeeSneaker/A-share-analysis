"""R4-A2.8 P0-01: golden domain ATOMIC exchange persistence tests (audit
20260825 #4 section 2).

Call+persist is ONE boundary operation (collector.call): every successful
real provider exchange is persisted BEFORE the next provider call fires.
Adversarial orderings:
  - dividend success + right_issue permission failure -> BOTH persisted
  - dividend success + RawWriter persistence failure   -> right_issue
    provider call MUST NOT fire
  - dividend failure                                    -> no right_issue call
  - full success -> lineage (request_id/endpoint) points at the EXACT
    persisted exchange
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _anchored_ctx import anchored_conn

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.golden_router import route_all
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.validators import GoldenCase

_SHA = "a" * 40


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
    return ProbeContext(run, store, catalog, target or FakeTarget(), anchored_conn())


def _ca_case(case_id: str = "GT-CA-A1") -> GoldenCase:
    return GoldenCase(
        golden_case_id=case_id,
        case_type="golden_corporate_action",
        provider_symbol="600519.SH",
        trade_date="20220630",
        truth_source="test-truth",
        source_ref="test-source",
        expected_fields={"IS_WD_SEC": True},
        event_class="DIVIDEND_EX_DATE",
    )


def _bundle(ctx: ProbeContext, evidence: dict) -> dict:
    path = ctx.store.spike_root / evidence["evidence_ref"]
    return json.loads(path.read_text(encoding="utf-8"))


def _exchange_metas(ctx: ProbeContext) -> list[dict]:
    raw_root = ctx.store.raw_dir(ctx.run)
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(raw_root.glob("provider=*/dataset=*/*.meta.json"))
    ]


class _RightIssueDeniedTarget(FakeTarget):
    """dividend succeeds; right_issue fails with a first-class error."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def get_dividend_exchange(self, code_list):
        self.calls.append("dividend")
        return super().get_dividend_exchange(code_list)

    def get_right_issue_exchange(self, code_list):
        self.calls.append("right_issue")
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="corporate_action",
            endpoint="InfoData.get_right_issue",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("right-issue entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


class _PersistFailsAfterFirstDomainExchange(FakeTarget):
    """dividend provider call succeeds; its RawWriter persistence fails.

    The atomic boundary means the persistence failure surfaces from
    collector.call BEFORE the right_issue provider call fires."""

    def __init__(self, ctx_holder: dict) -> None:
        super().__init__()
        self.ctx_holder = ctx_holder
        self.calls: list[str] = []
        self._dividend_fired = False

    def get_dividend_exchange(self, code_list):
        self.calls.append("dividend")
        # the real provider call succeeds; make the PERSISTENCE of this
        # exchange blow up inside collector.call

        def failing_persist(exchange):
            raise OSError("injected RawWriter persistence failure")

        self.ctx_holder["evidence_from_exchange"] = failing_persist
        return super().get_dividend_exchange(code_list)

    def get_right_issue_exchange(self, code_list):
        self.calls.append("right_issue")
        return super().get_right_issue_exchange(code_list)


class _DividendDeniedTarget(FakeTarget):
    """The FIRST event endpoint fails - the second must never fire."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def get_dividend_exchange(self, code_list):
        self.calls.append("dividend")
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="corporate_action",
            endpoint="InfoData.get_dividend",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("dividend entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error

    def get_right_issue_exchange(self, code_list):
        self.calls.append("right_issue")
        return super().get_right_issue_exchange(code_list)


class TestAtomicExchangeBoundary:
    def test_dividend_success_right_issue_failure_both_persisted(self, tmp_path: Path):
        """The exact audit scenario: mid-sequence provider failure must
        not orphan the prior real success exchange."""
        target = _RightIssueDeniedTarget()
        ctx = _ctx(tmp_path, target=target)
        outcomes = route_all(ctx, [_ca_case()])
        assert len(outcomes) == 1
        _case, outcome, evidence = outcomes[0]
        # the case is classified via the first-class failure
        assert outcome.result is CaseResult.NOT_TESTABLE_PERMISSION
        assert target.calls == ["dividend", "right_issue"]
        # BOTH exchanges are persisted evidence (success + failure)
        bundle = _bundle(ctx, evidence)
        endpoints = {e["endpoint"]: e["status"] for e in bundle["exchanges"]}
        assert endpoints.get("InfoData.get_dividend") == "OK"
        assert endpoints.get("InfoData.get_right_issue") == "ERROR"
        # call count == persisted exchange evidence count (the two event
        # endpoints this scenario exercised)
        metas = _exchange_metas(ctx)
        event_metas = [
            m
            for m in metas
            if m["endpoint"] in ("InfoData.get_dividend", "InfoData.get_right_issue")
        ]
        assert len(target.calls) == len(event_metas)

    def test_persistence_failure_prevents_later_provider_calls(self, tmp_path: Path):
        """First exchange succeeds at the PROVIDER level but its
        persistence fails inside the atomic boundary -> the second
        provider call MUST NOT fire (no unpersisted real exchange)."""
        ctx = _ctx(tmp_path)
        holder = {"evidence_from_exchange": ctx.evidence_from_exchange}
        target = _PersistFailsAfterFirstDomainExchange(holder)
        ctx.target = target
        # redirect the ctx evidence pipeline through the holder

        ctx.evidence_from_exchange = lambda exchange: holder["evidence_from_exchange"](exchange)
        with pytest.raises(OSError, match="injected RawWriter persistence failure"):
            route_all(ctx, [_ca_case("GT-CA-A2")])
        assert target.calls == ["dividend"]  # right_issue NEVER fired

    def test_first_endpoint_failure_no_second_call(self, tmp_path: Path):
        target = _DividendDeniedTarget()
        ctx = _ctx(tmp_path, target=target)
        outcomes = route_all(ctx, [_ca_case()])
        assert len(outcomes) == 1
        _case, outcome, evidence = outcomes[0]
        assert outcome.result is CaseResult.NOT_TESTABLE_PERMISSION
        # the second event endpoint never fired
        assert target.calls == ["dividend"]
        bundle = _bundle(ctx, evidence)
        endpoints = [e["endpoint"] for e in bundle["exchanges"]]
        assert "InfoData.get_right_issue" not in endpoints
        assert "InfoData.get_dividend" in endpoints

    def test_full_success_lineage_points_at_persisted_exchange(self, tmp_path: Path):
        """The semantic view's request_id/endpoint lineage resolves to the
        EXACT persisted exchange meta (atomic boundary view)."""
        ctx = _ctx(tmp_path)
        outcomes = route_all(ctx, [_ca_case()])
        _case, outcome, _evidence = outcomes[0]
        assert outcome.result is CaseResult.VALIDATED_PASS
        metas = _exchange_metas(ctx)
        by_endpoint = {m["endpoint"]: m for m in metas}
        dividend_meta = by_endpoint["InfoData.get_dividend"]
        # the bundle entry for the dividend exchange carries that meta's
        # request id (lineage closure)
        bundle = _bundle(ctx, _evidence)
        dividend_entry = next(
            e for e in bundle["exchanges"] if e["endpoint"] == "InfoData.get_dividend"
        )
        assert dividend_entry["request_id"] == dividend_meta["request_id"]
        assert dividend_entry["meta_hash"]


class TestEmptyFrameSchema:
    def test_zero_rows_with_required_columns_is_legitimate_empty(self):
        """0-row list payloads with the documented columns present parse
        as a legitimate empty event stream (EVENT_SOURCE_MISSING later,
        not PROVIDER_SCHEMA)."""
        from ashare_state.spike.golden_router import _ca_provider_view

        rows: list[dict] = []
        view = _ca_provider_view(
            "dividend",
            rows,
            source_endpoint="InfoData.get_dividend",
            raw_request_id="r-1",
            payload_columns={"MARKET_CODE", "DATE_EX"},
        )
        assert view == []

    def test_zero_rows_missing_required_columns_is_schema_error(self):
        from ashare_state.spike.golden_router import CAProviderShapeError, _ca_provider_view

        with pytest.raises(CAProviderShapeError, match="zero rows"):
            _ca_provider_view(
                "right_issue",
                [],
                source_endpoint="InfoData.get_right_issue",
                raw_request_id="r-2",
                payload_columns={"MARKET_CODE"},  # EX_DIVIDEND_DATE missing
            )

    def test_empty_dataframe_with_schema_columns_ok(self):
        import polars as pl

        from ashare_state.spike.golden_router import _ca_provider_view, _payload_columns

        frame = pl.DataFrame(schema={"MARKET_CODE": pl.String, "DATE_EX": pl.String})
        assert _payload_columns(frame) == {"MARKET_CODE", "DATE_EX"}
        view = _ca_provider_view(
            "dividend",
            [],
            source_endpoint="InfoData.get_dividend",
            raw_request_id="r-3",
            payload_columns=_payload_columns(frame),
        )
        assert view == []


class TestEndpointIdentityCrossCheck:
    def test_right_issue_payload_cannot_be_labelled_dividend(self):
        """P1-01: the stream label must agree with the endpoint identity -
        a right-issue payload fetched from InfoData.get_right_issue can
        never be normalized through the dividend stream."""
        from ashare_state.spike.golden_router import CAProviderShapeError, _ca_provider_view

        with pytest.raises(CAProviderShapeError, match="never be relabelled"):
            _ca_provider_view(
                "dividend",
                [{"MARKET_CODE": "600519", "DATE_EX": "20220630"}],
                source_endpoint="InfoData.get_right_issue",  # WRONG endpoint
                raw_request_id="r-4",
            )

    def test_matching_endpoint_passes(self):
        from ashare_state.spike.golden_router import _ca_provider_view

        view = _ca_provider_view(
            "dividend",
            [{"MARKET_CODE": "600519", "DATE_EX": "20220630"}],
            source_endpoint="InfoData.get_dividend",
            raw_request_id="r-5",
        )
        assert view[0]["event_type"] == "DIVIDEND"
