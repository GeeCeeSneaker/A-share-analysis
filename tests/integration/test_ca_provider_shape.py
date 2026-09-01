"""R4-A2.7 P0-04: corporate-action provider-shape adapter tests (audit
20260825 #3 section 5).

The documented AmazingData payload contracts (3.5.7.1 get_dividend:
MARKET_CODE / DATE_EX; 3.5.7.2 get_right_issue: MARKET_CODE /
EX_DIVIDEND_DATE) reach the typed validator through an EPHEMERAL
normalized view. The raw evidence keeps the provider-native fields; the
event TYPE is endpoint identity (never a fabricated payload field).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _anchored_ctx import anchored_conn

from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.golden_router import (
    CAProviderShapeError,
    _ca_provider_view,
    route_all,
)
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.validators import GoldenCase

_SHA = "b" * 40


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


def _ca_case(
    case_id: str,
    symbol: str,
    trade_date: str,
    event_class: str = "DIVIDEND_EX_DATE",
):
    return GoldenCase(
        golden_case_id=case_id,
        case_type="golden_corporate_action",
        provider_symbol=symbol,
        trade_date=trade_date,
        truth_source="test-truth",
        source_ref="test-source",
        expected_fields={"IS_WD_SEC": True},
        event_class=event_class,
    )


def _route_one(ctx: ProbeContext, case: GoldenCase):
    outcomes = route_all(ctx, [case])
    assert len(outcomes) == 1
    _case, outcome, evidence = outcomes[0]
    return outcome, evidence


class TestProviderView:
    def test_dividend_documented_fields_normalize(self):
        rows = [{"MARKET_CODE": "600519", "DATE_EX": "20220630"}]
        view = _ca_provider_view(
            "dividend", rows, source_endpoint="InfoData.get_dividend", raw_request_id="req-1"
        )
        assert view == [
            {
                "security_code": "600519",
                "ex_date": "20220630",
                "event_type": "DIVIDEND",
                "source_endpoint": "InfoData.get_dividend",
                "raw_request_id": "req-1",
            }
        ]

    def test_right_issue_documented_fields_normalize(self):
        rows = [{"MARKET_CODE": "600036", "EX_DIVIDEND_DATE": "20220630"}]
        view = _ca_provider_view(
            "right_issue", rows, source_endpoint="InfoData.get_right_issue", raw_request_id="req-2"
        )
        assert view[0]["security_code"] == "600036"
        assert view[0]["ex_date"] == "20220630"
        assert view[0]["event_type"] == "RIGHT_ISSUE"

    def test_event_type_derives_from_endpoint_not_payload(self):
        """A payload carrying a FAKE EVENT_TYPE column is IGNORED - the
        type comes from the endpoint identity alone."""
        rows = [{"MARKET_CODE": "600519", "DATE_EX": "20220630", "EVENT_TYPE": "LIES"}]
        view = _ca_provider_view("dividend", rows)
        assert view[0]["event_type"] == "DIVIDEND"

    def test_missing_market_code_fails_loud(self):
        with pytest.raises(CAProviderShapeError, match="MARKET_CODE"):
            _ca_provider_view("dividend", [{"DATE_EX": "20220630"}])

    def test_dividend_missing_date_ex_fails_loud(self):
        with pytest.raises(CAProviderShapeError, match="DATE_EX"):
            _ca_provider_view("dividend", [{"MARKET_CODE": "600519"}])

    def test_right_issue_missing_ex_dividend_date_fails_loud(self):
        with pytest.raises(CAProviderShapeError, match="EX_DIVIDEND_DATE"):
            _ca_provider_view("right_issue", [{"MARKET_CODE": "600036"}])

    def test_unknown_stream_rejected(self):
        with pytest.raises(CAProviderShapeError, match="unknown corporate-action stream"):
            _ca_provider_view("splits", [])


class _ShapeBrokenDividendTarget(FakeTarget):
    def get_dividend_exchange(self, code_list):
        from ashare_state.spike.target import _fake_exchange

        self._mark("get_dividend")
        # documented-contract violation: no DATE_EX
        rows = [{"MARKET_CODE": code.split(".")[0]} for code in code_list]
        return _fake_exchange(
            "InfoData.get_dividend",
            "corporate_action",
            rows,
            params={"code_list": list(code_list)},
        )


class TestProviderShapeEndToEnd:
    def test_fake_target_uses_documented_provider_fields(self):
        """The dry-run fake itself carries the provider-native documented
        fields (no SECURITY_CODE/EX_DATE/EVENT_TYPE fabrication)."""
        target = FakeTarget()
        dividend = target.get_dividend_exchange(["600519.SH"]).payload
        right = target.get_right_issue_exchange(["600036.SH"]).payload
        assert dividend and all(set(r) == {"MARKET_CODE", "DATE_EX"} for r in dividend)
        assert right and all(set(r) == {"MARKET_CODE", "EX_DIVIDEND_DATE"} for r in right)

    def test_raw_evidence_retains_provider_native_fields(self, tmp_path: Path):
        """The persisted parquet keeps the provider's OWN field names - the
        adapter is ephemeral (never persisted)."""
        ctx = _ctx(tmp_path)
        _outcome, evidence = _route_one(ctx, _ca_case("GT-SH-1", "600519.SH", "20220630"))
        bundle_path = ctx.store.spike_root / evidence["evidence_ref"]
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        dividend_meta_ref = next(
            e["evidence_ref"]
            for e in bundle["exchanges"]
            if e["endpoint"] == "InfoData.get_dividend"
        )
        meta_path = ctx.store.spike_root / dividend_meta_ref
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        payload_ref = meta["tables"][0]["file"]
        import polars as pl

        frame = pl.read_parquet(meta_path.parent / payload_ref)
        assert set(frame.columns) == {"MARKET_CODE", "DATE_EX"}

    def test_documented_dividend_case_reaches_typed_validator(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(ctx, _ca_case("GT-SH-2", "600519.SH", "20220630"))
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert outcome.validator_id == "corp_action_context_v2"
        assert outcome.validator_version == "6"

    def test_opposite_endpoint_never_satisfies_case(self, tmp_path: Path):
        """A RIGHT_ISSUE case for 600519.SH (which only has a DIVIDEND
        record at T) fails with a typed mismatch."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-SH-3", "600519.SH", "20220630", event_class="RIGHT_ISSUE_EX_DATE")
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_MISMATCH"

    def test_broken_provider_shape_structured_fail(self, tmp_path: Path):
        """A provider payload violating the documented contract produces a
        structured VALIDATED_FAIL for every case (never silent empty)."""
        ctx = _ctx(tmp_path, target=_ShapeBrokenDividendTarget())
        outcome, _evidence = _route_one(ctx, _ca_case("GT-SH-4", "600519.SH", "20220630"))
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "PROVIDER_SCHEMA"
        assert "DATE_EX" in outcome.actual

    def test_actual_v3_case_with_provider_shape_passes(self, tmp_path: Path):
        """An ACTUAL golden v3 CA case (event_class=DIVIDEND_EX_DATE)
        validates against the provider-shaped fake end to end."""
        from ashare_state.spike.golden_store import GoldenTruthStore

        store = GoldenTruthStore()
        cases, _manifest = store.load()
        v3_case = next(
            c
            for c in cases
            if c.case_type == "golden_corporate_action" and c.provider_symbol == "600519.SH"
        )
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(ctx, v3_case)
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert outcome.validator_version == "6"
