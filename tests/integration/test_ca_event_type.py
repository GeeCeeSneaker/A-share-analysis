"""R4-A2.5 P0-04: corporate-action event type taxonomy tests (audit
20260825 section 5).

The CA evidence combination distinguishes event TYPES: dividend and
right-issue are SEPARATE provider event streams; a DIVIDEND record can
NEVER substitute a RIGHT_ISSUE expectation (and vice versa). Golden CA
cases pin the expected type via ``expected_fields["event_type"]``.
"""

from __future__ import annotations

from pathlib import Path

from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.golden_router import _normalize_event_type, route_all
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.validators import GoldenCase

_SHA = "b" * 40


def _ctx(tmp_path: Path) -> ProbeContext:
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
    return ProbeContext(run, store, catalog, FakeTarget())


def _ca_case(case_id: str, symbol: str, trade_date: str, event_type: str = ""):
    expected = {"IS_WD_SEC": True}
    if event_type:
        expected["event_type"] = event_type
    return GoldenCase(
        golden_case_id=case_id,
        case_type="golden_corporate_action",
        provider_symbol=symbol,
        trade_date=trade_date,
        truth_source="test-truth",
        source_ref="test-source",
        expected_fields=expected,
    )


def _route_one(ctx: ProbeContext, case: GoldenCase):
    outcomes = route_all(ctx, [case])
    assert len(outcomes) == 1
    _case, outcome, evidence = outcomes[0]
    return outcome, evidence


class TestEventTaxonomy:
    def test_provider_literals_normalize(self):
        assert _normalize_event_type("DIVIDEND") == "DIVIDEND"
        assert _normalize_event_type("cash_dividend") == "DIVIDEND"
        assert _normalize_event_type("分红") == "DIVIDEND"
        assert _normalize_event_type("RIGHT_ISSUE") == "RIGHT_ISSUE"
        assert _normalize_event_type("rights_issue") == "RIGHT_ISSUE"
        assert _normalize_event_type("配股") == "RIGHT_ISSUE"
        assert _normalize_event_type("2") == "RIGHT_ISSUE"
        assert _normalize_event_type("") == ""
        # unknown literals pass through uppercase (fail-closed comparison)
        assert _normalize_event_type("SOME_NEW_TYPE") == "SOME_NEW_TYPE"

    def test_dividend_event_case_passes(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-CA-D1", "600519.SH", "20220630", "DIVIDEND")
        )
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert outcome.validator_version == "4"

    def test_right_issue_case_passes_on_own_stream(self, tmp_path: Path):
        """A RIGHT_ISSUE case validates against the right-issue stream
        (600036.SH 2022-06-30 fake fixture) - adj + event + kline all
        consistent on the SEPARATE stream."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-CA-R1", "600036.SH", "20220630", "RIGHT_ISSUE")
        )
        assert outcome.result is CaseResult.VALIDATED_PASS

    def test_dividend_cannot_substitute_right_issue(self, tmp_path: Path):
        """600519.SH has a DIVIDEND event on 2022-06-30 - a case expecting
        RIGHT_ISSUE for the same date must FAIL (type mismatch), never
        quietly accept the dividend record."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-CA-X1", "600519.SH", "20220630", "RIGHT_ISSUE")
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_MISMATCH"
        assert "DIVIDEND" in outcome.actual

    def test_right_issue_cannot_substitute_dividend(self, tmp_path: Path):
        """Mirror: 600036.SH has a RIGHT_ISSUE event - a DIVIDEND
        expectation on the same date FAILS."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-CA-X2", "600036.SH", "20220630", "DIVIDEND")
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_MISMATCH"

    def test_untyped_case_accepts_any_event_type(self, tmp_path: Path):
        """Cases whose golden truth did not record a type (legacy v3
        cases) still validate on the exact date - no regression."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(ctx, _ca_case("GT-CA-N1", "600036.SH", "20220630"))
        assert outcome.result is CaseResult.VALIDATED_PASS

    def test_bundle_lists_both_event_streams(self, tmp_path: Path):
        """Both event endpoints are persisted evidence in the CA bundle
        (independent lineage for dividend AND right issue)."""
        import json

        ctx = _ctx(tmp_path)
        _outcome, evidence = _route_one(ctx, _ca_case("GT-CA-B1", "600519.SH", "20220630"))
        bundle_path = ctx.store.spike_root / evidence["evidence_ref"]
        doc = json.loads(bundle_path.read_text(encoding="utf-8"))
        endpoints = {e["endpoint"] for e in doc["exchanges"]}
        assert "InfoData.get_dividend" in endpoints
        assert "InfoData.get_right_issue" in endpoints


class TestTargetSurface:
    def test_fake_target_right_issue_stream_is_independent(self, tmp_path: Path):
        """FakeTarget.get_dividend_exchange returns ONLY dividend records
        and get_right_issue_exchange ONLY right-issue records."""
        ctx = _ctx(tmp_path)
        dividend = ctx.target.get_dividend_exchange(["600519.SH", "600036.SH"])
        right = ctx.target.get_right_issue_exchange(["600519.SH", "600036.SH"])
        dividend_types = {r["EVENT_TYPE"] for r in dividend.payload}
        right_types = {r["EVENT_TYPE"] for r in right.payload}
        assert dividend_types == {"DIVIDEND"}
        assert right_types == {"RIGHT_ISSUE"}
        dividend_symbols = {r["SECURITY_CODE"] for r in dividend.payload}
        right_symbols = {r["SECURITY_CODE"] for r in right.payload}
        assert dividend_symbols == {"600519"}
        assert right_symbols == {"600036"}
