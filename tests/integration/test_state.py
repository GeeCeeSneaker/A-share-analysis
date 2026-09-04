"""CR-6.1 Registry and deterministic State rule contract tests."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from ashare_state.features.models import VerifiedFeatureRun
from ashare_state.state import (
    STATE_REGISTRY_VERSION,
    STATE_SET_ID,
    STATE_SET_VERSION,
    StateRegistryError,
    StateSet,
    StateSpec,
    compile_state_execution_plan,
    compute_state_set,
    get_state_set,
)

pytestmark = pytest.mark.unit

_AVAILABLE_AT = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)


def _market_row(trade_date: date = date(2026, 3, 12), **changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_date": trade_date,
        "source_snapshot_id": "snapshot-1",
        "feature_set_id": "market-state-base-v1",
        "feature_available_at": _AVAILABLE_AT,
        "input_lineage_hash": "a" * 64,
        "universe_rule_id": "OBSERVED_DAILY_BAR_UNIVERSE",
        "observed_security_count": 10,
        "valid_raw_return_count": 10,
        "advancer_count": 6,
        "decliner_count": 3,
        "unchanged_count": 1,
        "advancer_ratio_observed": 0.6,
        "mean_raw_return_observed": 0.01,
        "median_raw_return_observed": 0.005,
        "valid_ma20_count": 10,
        "pct_above_ma20_observed": 0.7,
        "valid_mom20_count": 10,
        "pct_positive_mom20_observed": 0.8,
    }
    row.update(changes)
    return row


def _feature_run(*rows: dict[str, object]) -> VerifiedFeatureRun:
    return VerifiedFeatureRun(
        feature_run_id="feature-run-1",
        snapshot_id="snapshot-1",
        canonical_run_id="canonical-run-1",
        feature_set_id="market-state-base-v1",
        manifest={},
        ledger_record={},
        security_rows=(),
        market_rows=tuple(rows),
        finding_rows=(),
    )


def _compute(*rows: dict[str, object]):
    return compute_state_set(
        _feature_run(*rows),
        state_run_id="state-run-1",
        state_set=get_state_set(STATE_SET_ID),
    )


def test_registry_declares_exact_v1_order_and_fields():
    state_set = get_state_set(STATE_SET_ID)
    assert state_set.state_names == (
        "return_center_state",
        "daily_participation_state",
        "trend_participation_state",
        "market_structure_state",
    )
    plan = compile_state_execution_plan(state_set)
    assert [entry.handler for entry in plan.entries] == [
        "return_center",
        "daily_participation",
        "trend_participation",
        "market_structure",
    ]
    assert state_set.registry_hash == get_state_set(STATE_SET_ID).registry_hash
    for spec in state_set.states:
        assert spec.output_enum
        assert spec.required_feature_inputs
        assert spec.rule_id
        assert spec.threshold_policy
        assert spec.missingness_policy
        assert spec.availability_rule
        assert spec.interpretation
        assert spec.non_predictive_statement
        assert spec.eligibility == "SUPPORTED"


def test_unknown_state_set_refused():
    with pytest.raises(StateRegistryError):
        get_state_set("state-set-does-not-exist")


@pytest.mark.parametrize(
    "field",
    (
        "state_set_id",
        "state_set_version",
        "state_registry_version",
        "contract_version",
    ),
)
def test_state_set_metadata_drift_refused(field: str):
    state_set = get_state_set(STATE_SET_ID)
    changed = replace(state_set, **{field: "foreign-value"})
    with pytest.raises(StateRegistryError):
        compile_state_execution_plan(changed)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda spec: replace(spec, rule_id="FOREIGN_RULE"),
        lambda spec: replace(spec, required_feature_inputs=("foreign_feature",)),
        lambda spec: replace(spec, threshold_policy="BACKTEST_OPTIMIZED"),
        lambda spec: replace(spec, missingness_policy="SILENT_DROP"),
        lambda spec: replace(spec, availability_rule="TRADE_DATE"),
        lambda spec: replace(spec, output_enum=("BULL", "BEAR")),
        lambda spec: replace(spec, eligibility="BLOCKED"),
    ),
)
def test_registry_field_drift_refused(mutation):
    state_set = get_state_set(STATE_SET_ID)
    changed_states = list(state_set.states)
    changed_states[0] = mutation(changed_states[0])
    changed = replace(state_set, states=tuple(changed_states))
    with pytest.raises(StateRegistryError):
        compile_state_execution_plan(changed)


def test_extra_state_declaration_refused():
    state_set = get_state_set(STATE_SET_ID)
    extra = StateSpec(
        state_name="unsupported_state",
        output_enum=("UNKNOWN",),
        required_feature_inputs=(),
        rule_id="UNSUPPORTED",
        threshold_policy="NONE",
        missingness_policy="NONE",
        availability_rule="NONE",
        interpretation="",
        non_predictive_statement="",
        eligibility="BLOCKED",
    )
    with pytest.raises(StateRegistryError):
        compile_state_execution_plan(replace(state_set, states=(*state_set.states, extra)))


def test_supported_declaration_without_handler_refused():
    state_set = get_state_set(STATE_SET_ID)
    changed_states = list(state_set.states)
    changed_states[0] = replace(changed_states[0], rule_id="UNSUPPORTED_HANDLER")
    with pytest.raises(StateRegistryError):
        compile_state_execution_plan(replace(state_set, states=tuple(changed_states)))


def test_caller_cannot_inject_thresholds_or_weights():
    parameters = inspect.signature(compute_state_set).parameters
    assert "threshold" not in parameters
    assert "weight" not in parameters
    assert "feature_run_id" not in parameters


@pytest.mark.parametrize(
    ("mean", "median", "expected"),
    (
        (0.01, 0.001, "POSITIVE_CENTER"),
        (-0.01, -0.001, "NEGATIVE_CENTER"),
        (0.01, -0.001, "MIXED_CENTER"),
        (0.0, 0.001, "MIXED_CENTER"),
        (0.0, 0.0, "MIXED_CENTER"),
    ),
)
def test_return_center_exact_sign_semantics(mean: float, median: float, expected: str):
    result = _compute(_market_row(mean_raw_return_observed=mean, median_raw_return_observed=median))
    assert result.state_rows[0]["return_center_state"] == expected


def test_return_center_null_is_unknown_with_finding():
    result = _compute(_market_row(mean_raw_return_observed=None))
    assert result.state_rows[0]["return_center_state"] == "UNKNOWN"
    assert result.finding_rows == (
        {
            "trade_date": date(2026, 3, 12),
            "state_name": "return_center_state",
            "finding_class": "STATE_INPUT_NULL",
            "detail_json": '{"inputs":["mean_raw_return_observed"]}',
        },
    )


@pytest.mark.parametrize(
    ("advancers", "decliners", "expected"),
    ((6, 3, "ADVANCE_DOMINANT"), (3, 6, "DECLINE_DOMINANT"), (4, 4, "BALANCED")),
)
def test_daily_participation_exact_dominance(advancers: int, decliners: int, expected: str):
    result = _compute(
        _market_row(
            valid_raw_return_count=advancers + decliners,
            advancer_count=advancers,
            decliner_count=decliners,
            unchanged_count=0,
            advancer_ratio_observed=advancers / (advancers + decliners),
        )
    )
    assert result.state_rows[0]["daily_participation_state"] == expected


def test_daily_participation_count_invariant_fails_closed():
    with pytest.raises(Exception, match="invariant"):
        _compute(_market_row(unchanged_count=2))


def test_daily_participation_zero_valid_is_unknown_with_finding():
    result = _compute(
        _market_row(
            valid_raw_return_count=0,
            advancer_count=0,
            decliner_count=0,
            unchanged_count=0,
            advancer_ratio_observed=None,
        )
    )
    assert result.state_rows[0]["daily_participation_state"] == "UNKNOWN"
    assert any(
        row["finding_class"] == "STATE_INPUT_EMPTY_DENOMINATOR"
        for row in result.finding_rows
    )


@pytest.mark.parametrize(
    ("ma_ratio", "mom_ratio", "expected"),
    (
        (0.7, 0.8, "BROAD_POSITIVE"),
        (0.3, 0.2, "BROAD_NEGATIVE"),
        (0.5, 0.5, "MIXED"),
        (0.7, 0.3, "MIXED"),
    ),
)
def test_trend_participation_majority_semantics(
    ma_ratio: float, mom_ratio: float, expected: str
):
    result = _compute(
        _market_row(
            pct_above_ma20_observed=ma_ratio,
            pct_positive_mom20_observed=mom_ratio,
        )
    )
    assert result.state_rows[0]["trend_participation_state"] == expected


def test_trend_null_and_empty_denominator_are_unknown():
    null_result = _compute(_market_row(pct_above_ma20_observed=None))
    assert null_result.state_rows[0]["trend_participation_state"] == "UNKNOWN"
    assert any(
        row["state_name"] == "trend_participation_state"
        and row["finding_class"] == "STATE_INPUT_NULL"
        for row in null_result.finding_rows
    )
    empty_result = _compute(_market_row(valid_ma20_count=0))
    assert empty_result.state_rows[0]["trend_participation_state"] == "UNKNOWN"
    assert any(
        row["state_name"] == "trend_participation_state"
        and row["finding_class"] == "STATE_INPUT_EMPTY_DENOMINATOR"
        for row in empty_result.finding_rows
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, "BROAD_ADVANCE"),
        (
            {
                "mean_raw_return_observed": -0.01,
                "median_raw_return_observed": -0.005,
                "advancer_count": 3,
                "decliner_count": 6,
                "unchanged_count": 1,
                "advancer_ratio_observed": 0.3,
                "pct_above_ma20_observed": 0.3,
                "pct_positive_mom20_observed": 0.2,
            },
            "BROAD_DECLINE",
        ),
        (
            {
                "advancer_count": 4,
                "decliner_count": 5,
                "unchanged_count": 1,
                "advancer_ratio_observed": 0.4,
            },
            "POSITIVE_MIXED_PARTICIPATION",
        ),
        (
            {
                "mean_raw_return_observed": -0.01,
                "median_raw_return_observed": -0.005,
            },
            "NEGATIVE_MIXED_PARTICIPATION",
        ),
        (
            {"mean_raw_return_observed": 0.01, "median_raw_return_observed": -0.005},
            "MIXED",
        ),
    ),
)
def test_market_structure_exact_composition(changes, expected: str):
    assert _compute(_market_row(**changes)).state_rows[0]["market_structure_state"] == expected


def test_market_structure_unknown_when_dimension_unknown():
    result = _compute(_market_row(mean_raw_return_observed=None))
    assert result.state_rows[0]["market_structure_state"] == "UNKNOWN"


def test_every_feature_market_date_produces_one_state_row():
    result = _compute(
        _market_row(date(2026, 3, 12)),
        _market_row(date(2026, 3, 13), input_lineage_hash="b" * 64),
    )
    assert [row["trade_date"] for row in result.state_rows] == [
        date(2026, 3, 12),
        date(2026, 3, 13),
    ]


def test_evidence_projection_is_exact():
    row = _market_row(
        observed_security_count=123,
        valid_raw_return_count=100,
        advancer_count=55,
        decliner_count=40,
        unchanged_count=5,
        advancer_ratio_observed=0.55,
    )
    output = _compute(row).state_rows[0]
    assert output["evidence_observed_security_count"] == 123
    assert output["evidence_valid_raw_return_count"] == 100
    assert output["evidence_advancer_ratio_observed"] == 0.55
    assert output["evidence_mean_raw_return_observed"] == row["mean_raw_return_observed"]


def test_source_lineage_and_evidence_lineage_are_separate():
    first = _compute(_market_row())
    changed_feature_lineage = _compute(_market_row(input_lineage_hash="b" * 64))
    changed_evidence = _compute(_market_row(mean_raw_return_observed=0.02))
    assert first.state_rows[0]["source_feature_input_lineage_hash"] != (
        changed_feature_lineage.state_rows[0]["source_feature_input_lineage_hash"]
    )
    assert first.state_rows[0]["input_lineage_hash"] != changed_feature_lineage.state_rows[0][
        "input_lineage_hash"
    ]
    assert first.state_rows[0]["input_lineage_hash"] != changed_evidence.state_rows[0][
        "input_lineage_hash"
    ]


def test_state_available_at_is_feature_available_at():
    row = _market_row()
    assert _compute(row).state_rows[0]["state_available_at"] == row["feature_available_at"]


def test_input_order_does_not_change_semantic_hash():
    first = _compute(
        _market_row(date(2026, 3, 12)),
        _market_row(date(2026, 3, 13), input_lineage_hash="b" * 64),
    )
    second = _compute(
        _market_row(date(2026, 3, 13), input_lineage_hash="b" * 64),
        _market_row(date(2026, 3, 12)),
    )
    assert first.state_semantic_hash == second.state_semantic_hash
    assert first.finding_set_hash == second.finding_set_hash


def test_state_run_identity_primitives_are_explicit():
    parameters = inspect.signature(compute_state_set).parameters
    assert tuple(parameters) == ("feature_run", "state_run_id", "state_set")


def test_constants_are_immutable_contract_values():
    assert STATE_SET_VERSION == "1"
    assert STATE_REGISTRY_VERSION == "state-registry-v1"
