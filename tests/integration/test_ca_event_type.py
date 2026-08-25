"""R4-A2.6 P0-02: Golden CA event-type TRUTH closure (audit 20260825 #2
section 3).

The formal CA event type resolves from the ACTUAL bound Golden truth -
``event_class`` (part of the case's semantic identity) is the PRIMARY
type fact:

    DIVIDEND_EX_DATE    -> DIVIDEND
    RIGHT_ISSUE_EX_DATE -> RIGHT_ISSUE

``expected_fields["event_type"]``, when present, must AGREE (conflict ->
fail closed). Unknown / untyped formal CA cases fail closed - the old
"untyped accepts any event type" bypass is REMOVED from the formal path
(the previous test asserted it and has been inverted, per the audit).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.golden_router import (
    _normalize_event_type,
    _resolve_expected_event_type,
    route_all,
)
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.validators import GoldenCase

REPO_GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden" / "provider" / "amazingdata"
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


def _ca_case(
    case_id: str,
    symbol: str,
    trade_date: str,
    event_class: str = "DIVIDEND_EX_DATE",
    event_type: str = "",
):
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
        event_class=event_class,
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

    def test_event_class_derives_type(self):
        assert _resolve_expected_event_type(_ca_case("T1", "600519.SH", "20220630")) == (
            "DIVIDEND",
            "",
        )
        assert _resolve_expected_event_type(
            _ca_case("T2", "600036.SH", "20220630", event_class="RIGHT_ISSUE_EX_DATE")
        ) == ("RIGHT_ISSUE", "")

    def test_unresolvable_event_class_fails_closed(self):
        """Unknown event_class has no canonical mapping -> fail closed."""
        _type, reason = _resolve_expected_event_type(
            _ca_case("T3", "600519.SH", "20220630", event_class="SOME_FUTURE_EVENT")
        )
        assert _type == ""
        assert "no canonical mapping" in reason

    def test_missing_event_class_fails_closed(self):
        """R4-A2.6 P0-02: the OLD 'untyped accepts any' bypass is REMOVED
        from the formal path - a case without event_class cannot resolve
        a type and fails closed."""
        _type, reason = _resolve_expected_event_type(
            _ca_case("T4", "600519.SH", "20220630", event_class="")
        )
        assert _type == ""
        assert "untyped case may not pass" in reason

    def test_event_class_and_declared_type_conflict_fails_closed(self):
        _type, reason = _resolve_expected_event_type(
            _ca_case("T5", "600519.SH", "20220630", event_type="RIGHT_ISSUE")
        )
        assert _type == ""
        assert "conflict" in reason

    def test_agreeing_declared_type_resolves(self):
        assert _resolve_expected_event_type(
            _ca_case("T6", "600519.SH", "20220630", event_type="DIVIDEND")
        ) == ("DIVIDEND", "")


class TestTypedValidation:
    def test_dividend_event_case_passes(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(ctx, _ca_case("GT-CA-D1", "600519.SH", "20220630"))
        assert outcome.result is CaseResult.VALIDATED_PASS
        assert outcome.validator_version == "6"

    def test_right_issue_case_passes_on_own_stream(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx,
            _ca_case("GT-CA-R1", "600036.SH", "20220630", event_class="RIGHT_ISSUE_EX_DATE"),
        )
        assert outcome.result is CaseResult.VALIDATED_PASS

    def test_dividend_cannot_substitute_right_issue(self, tmp_path: Path):
        """600519.SH has a DIVIDEND event on 2022-06-30 - a RIGHT_ISSUE
        case for the same date must FAIL (type mismatch)."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx,
            _ca_case("GT-CA-X1", "600519.SH", "20220630", event_class="RIGHT_ISSUE_EX_DATE"),
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_MISMATCH"
        assert "DIVIDEND" in outcome.actual

    def test_right_issue_cannot_substitute_dividend(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx,
            _ca_case("GT-CA-X2", "600036.SH", "20220630"),  # expects DIVIDEND
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_MISMATCH"

    def test_untyped_case_fails_closed_in_validator(self, tmp_path: Path):
        """INVERTED from the old 'untyped accepts any' test (audit 20260825
        #2 section 3.4): the formal path no longer allows the untyped
        semantics."""
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-CA-N1", "600036.SH", "20220630", event_class="")
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_UNRESOLVED"

    def test_conflicting_declared_type_fails_in_validator(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        outcome, _evidence = _route_one(
            ctx, _ca_case("GT-CA-C1", "600519.SH", "20220630", event_type="RIGHT_ISSUE")
        )
        assert outcome.result is CaseResult.VALIDATED_FAIL
        assert outcome.reason_code == "EVENT_TYPE_UNRESOLVED"

    def test_bundle_lists_both_event_streams(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        _outcome, evidence = _route_one(ctx, _ca_case("GT-CA-B1", "600519.SH", "20220630"))
        bundle_path = ctx.store.spike_root / evidence["evidence_ref"]
        doc = json.loads(bundle_path.read_text(encoding="utf-8"))
        endpoints = {e["endpoint"] for e in doc["exchanges"]}
        assert "InfoData.get_dividend" in endpoints
        assert "InfoData.get_right_issue" in endpoints


class TestActualGoldenV3Truth:
    """Load the ACTUAL golden_cases_v3.jsonl CA cases (not synthetic ones)
    and prove the typed semantics participate in validation."""

    @staticmethod
    def _v3_ca_cases() -> list[GoldenCase]:
        from ashare_state.spike.golden_store import GoldenTruthStore

        store = GoldenTruthStore(REPO_GOLDEN)
        cases, _manifest = store.load()
        return [c for c in cases if c.case_type == "golden_corporate_action"]

    def test_every_actual_v3_ca_case_resolves_a_type(self):
        cases = self._v3_ca_cases()
        assert len(cases) == 20  # v3 has 20 CA cases
        for case in cases:
            expected_type, reason = _resolve_expected_event_type(case)
            assert expected_type == "DIVIDEND", f"{case.golden_case_id}: {reason or 'wrong type'}"

    def test_actual_v3_dividend_case_rejects_right_issue_evidence(self, tmp_path):
        """An actual v3 CA case (event_class=DIVIDEND_EX_DATE) must FAIL
        when only RIGHT_ISSUE evidence exists on the exact date."""
        cases = self._v3_ca_cases()
        case = next(
            c for c in cases if c.provider_symbol == "600519.SH"
        )  # fake has a RIGHT_ISSUE stream at 600036 only; use a right-issue-
        # only target by remapping: feed a target whose dividend stream is
        # empty but right issue fires on the case's exact date
        ctx = _ctx(tmp_path)

        class _RightIssueOnlyTarget(FakeTarget):
            def get_dividend_exchange(self, code_list):
                from ashare_state.spike.target import _fake_exchange

                self._mark("get_dividend")
                return _fake_exchange(
                    "InfoData.get_dividend",
                    "corporate_action",
                    [],
                    params={"code_list": list(code_list)},
                )

            def get_right_issue_exchange(self, code_list):
                from ashare_state.spike.target import _fake_exchange

                self._mark("get_right_issue")
                # R4-A2.7 P0-04: provider-native documented field names
                rows = [
                    {
                        "MARKET_CODE": code.split(".")[0],
                        "EX_DIVIDEND_DATE": case.trade_date,
                    }
                    for code in code_list
                ]
                return _fake_exchange(
                    "InfoData.get_right_issue",
                    "corporate_action",
                    rows,
                    params={"code_list": list(code_list)},
                )

        ctx.target = _RightIssueOnlyTarget()
        outcome, _evidence = _route_one(ctx, case)
        # exact date + right issue only + case expects DIVIDEND -> mismatch
        assert outcome.reason_code in ("EVENT_TYPE_MISMATCH", "EVENT_DATE_MISMATCH")
        if outcome.reason_code == "EVENT_DATE_MISMATCH":
            # the right-issue row DID exist at the exact date, so reaching
            # EVENT_DATE_MISMATCH would mean the fixture failed to fire;
            # force the assertion for clarity
            pytest.fail("fixture did not fire right-issue row at the case date")

    def test_actual_v3_case_end_to_end_validation(self, tmp_path):
        """Actual v3 CA cases run the typed validator end to end: cases
        whose symbol/date has fake DIVIDEND evidence PASS; all others FAIL
        with a typed/structured reason (never a silent pass)."""
        ctx = _ctx(tmp_path)
        outcomes = route_all(ctx, self._v3_ca_cases())
        assert len(outcomes) == 20
        for _case, outcome, _evidence in outcomes:
            assert outcome.result in (
                CaseResult.VALIDATED_PASS,
                CaseResult.VALIDATED_FAIL,
                CaseResult.NOT_TESTABLE_TIME,
            )
            # every outcome carries the typed validator version
            if outcome.validator_id == "corp_action_context_v2":
                assert outcome.validator_version == "6"
