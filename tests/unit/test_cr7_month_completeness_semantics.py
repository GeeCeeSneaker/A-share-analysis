"""Offline tests for the versioned CR-7 expected-bar-set rule."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date

import polars as pl
import pytest

from ashare_state.providers.amazingdata.month_completeness import (
    APPROVED_300114_SUSPENSION_EVENT,
    CompletenessPairClass,
    MonthCompletenessError,
    MonthCompletenessEvaluation,
    PositiveTradeFallback,
    _snapshot_trade_observation,
    evaluate_month_completeness,
)

_SYMBOLS = ["000001.SZ", "600000.SH"]
_DAYS = [20240102, 20240103]


def _status(*, day_values: list[int], flags: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "MARKET_CODE": ["1"] * len(day_values),
            "TRADE_DATE": day_values,
            "PRECLOSE": [10.0] * len(day_values),
            "HIGH_LIMITED": [11.0] * len(day_values),
            "LOW_LIMITED": [9.0] * len(day_values),
            "PRICE_HIGH_LMT_RATE": [0.1] * len(day_values),
            "PRICE_LOW_LMT_RATE": [-0.1] * len(day_values),
            "IS_ST_SEC": [0] * len(day_values),
            "IS_SUSP_SEC": flags,
            "IS_WD_SEC": [0] * len(day_values),
            "IS_XR_SEC": [0] * len(day_values),
        }
    )


def _bars(symbol: str, days: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "code": [symbol] * len(days),
            "kline_time": days,
            "open": [10.0] * len(days),
            "high": [11.0] * len(days),
            "low": [9.0] * len(days),
            "close": [10.5] * len(days),
            "volume": [100.0] * len(days),
            "amount": [1000.0] * len(days),
        }
    )


def _valid_inputs() -> dict[str, object]:
    return {
        "monthly_symbols": _SYMBOLS,
        "trading_days": _DAYS,
        "exact_day_universes": {
            20240102: _SYMBOLS,
            20240103: ["600000.SH"],
        },
        "status_payload": {
            "000001.SZ": _status(day_values=[20240102], flags=[0]),
            "600000.SH": _status(day_values=[20240102, 20240103], flags=[0, 1]),
        },
        "daily_bar_payload": {
            "000001.SZ": _bars("000001.SZ", [20240102]),
            "600000.SH": _bars("600000.SH", [20240102]),
        },
    }


def test_expected_bar_set_excludes_non_applicable_and_suspended_pairs() -> None:
    result = evaluate_month_completeness(**_valid_inputs())

    assert result.accepted
    assert result.required_bar_pair_count == 2
    assert result.returned_bar_pair_count == 2
    assert result.classification_counts == {
        CompletenessPairClass.SUSPENSION_NON_TRADING.value: 1,
        CompletenessPairClass.NOT_APPLICABLE_SESSION.value: 1,
        CompletenessPairClass.POSITIVE_TRADE_COUNT_ACTIVE.value: 0,
        CompletenessPairClass.PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH.value: 0,
        CompletenessPairClass.UNEXPLAINED_MISSING.value: 0,
        CompletenessPairClass.UNRESOLVED.value: 0,
        CompletenessPairClass.EXTRA_RETURNED.value: 0,
    }


def test_security_first_present_on_d_plus_one_is_not_applicable_on_d() -> None:
    values = _valid_inputs()
    values["exact_day_universes"] = {
        20240102: ["600000.SH"],
        20240103: _SYMBOLS,
    }
    values["status_payload"] = {
        "000001.SZ": _status(day_values=[20240103], flags=[0]),
        "600000.SH": _status(day_values=[20240102, 20240103], flags=[0, 1]),
    }
    values["daily_bar_payload"] = {
        "000001.SZ": _bars("000001.SZ", [20240103]),
        "600000.SH": _bars("600000.SH", [20240102]),
    }

    result = evaluate_month_completeness(**values)

    assert result.accepted
    assert result.required_bar_pair_count == 2
    assert result.returned_bar_pair_count == 2


def test_provider_list_date_excludes_a_prelisting_exact_session() -> None:
    values = _valid_inputs()
    bars = values["daily_bar_payload"]
    assert isinstance(bars, dict)
    bars["000001.SZ"] = _bars("000001.SZ", [])

    result = evaluate_month_completeness(
        **values,
        list_dates_by_symbol={"000001.SZ": date(2024, 1, 3)},
    )

    assert result.accepted
    assert result.required_bar_pair_count == 1
    assert result.returned_row_count == 1
    assert result.classification_counts[CompletenessPairClass.NOT_APPLICABLE_SESSION.value] == 2
    assert result.prelisting_list_dates == {"000001.SZ": date(2024, 1, 3)}


def test_provider_delist_date_excludes_on_and_after_delisting_session() -> None:
    values = _valid_inputs()
    result = evaluate_month_completeness(
        **values,
        delist_dates_by_symbol={"600000.SH": date(2024, 1, 3)},
    )

    assert result.accepted
    assert result.required_bar_pair_count == 2
    assert result.returned_bar_pair_count == 2
    assert result.classification_counts[CompletenessPairClass.NOT_APPLICABLE_SESSION.value] == 2
    assert result.postdelisting_delist_dates == {"600000.SH": date(2024, 1, 3)}


def test_session_before_delist_date_keeps_ordinary_status_and_bar_requirement() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["600000.SH"] = _status(day_values=[20240102, 20240103], flags=[0, 0])
    bars["600000.SH"] = _bars("600000.SH", [20240102, 20240103])

    result = evaluate_month_completeness(
        **values,
        delist_dates_by_symbol={"600000.SH": date(2024, 1, 4)},
    )

    assert result.accepted
    assert result.required_bar_pair_count == 3
    assert result.returned_bar_pair_count == 3
    assert result.postdelisting_delist_dates == {}


@pytest.mark.parametrize("delist_date", (None, "malformed-delist-date"))
def test_missing_or_malformed_delist_date_does_not_resolve_an_unresolved_pair(
    delist_date: object,
) -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["000001.SZ"] = pl.DataFrame()
    bars["000001.SZ"] = _bars("000001.SZ", [])

    result = evaluate_month_completeness(
        **values,
        delist_dates_by_symbol={"000001.SZ": delist_date},
    )

    assert not result.accepted
    assert result.unresolved_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.UNRESOLVED.value] == 1
    assert result.postdelisting_delist_dates == {}


def test_approved_official_suspension_event_resolves_only_its_exact_interval() -> None:
    symbols = ["300114.SZ"]
    days = [20230111, 20230112, 20230113, 20230130, 20230131]
    values = {
        "monthly_symbols": symbols,
        "trading_days": days,
        "exact_day_universes": dict.fromkeys(days, symbols),
        "status_payload": {
            "300114.SZ": _status(day_values=[20230111], flags=[0]),
        },
        "daily_bar_payload": {"300114.SZ": _bars("300114.SZ", [20230111])},
    }

    result = evaluate_month_completeness(
        **values,
        official_suspension_event=APPROVED_300114_SUSPENSION_EVENT,
    )

    assert result.accepted
    assert result.required_bar_pair_count == 1
    assert result.returned_row_count == 1
    assert result.unresolved_pair_count == 0
    assert result.classification_counts == {
        CompletenessPairClass.SUSPENSION_NON_TRADING.value: 4,
        CompletenessPairClass.NOT_APPLICABLE_SESSION.value: 0,
        CompletenessPairClass.POSITIVE_TRADE_COUNT_ACTIVE.value: 0,
        CompletenessPairClass.PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH.value: 0,
        CompletenessPairClass.UNEXPLAINED_MISSING.value: 0,
        CompletenessPairClass.UNRESOLVED.value: 0,
        CompletenessPairClass.EXTRA_RETURNED.value: 0,
    }
    assert result.official_suspension_event == APPROVED_300114_SUSPENSION_EVENT
    assert APPROVED_300114_SUSPENSION_EVENT.covers(date(2023, 2, 1))
    assert not APPROVED_300114_SUSPENSION_EVENT.covers(date(2023, 2, 2))


def test_official_suspension_event_is_not_a_zero_activity_heuristic() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["000001.SZ"] = pl.DataFrame()
    bars["000001.SZ"] = _bars("000001.SZ", [])

    result = evaluate_month_completeness(
        **values,
        official_suspension_event=APPROVED_300114_SUSPENSION_EVENT,
    )

    assert not result.accepted
    assert result.unresolved_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.SUSPENSION_NON_TRADING.value] == 1
    assert result.official_suspension_event is None


def test_official_suspension_event_round_trip_binds_sources() -> None:
    symbols = ["300114.SZ"]
    days = [20230111, 20230112]
    result = evaluate_month_completeness(
        monthly_symbols=symbols,
        trading_days=days,
        exact_day_universes=dict.fromkeys(days, symbols),
        status_payload={"300114.SZ": _status(day_values=[20230111], flags=[0])},
        daily_bar_payload={"300114.SZ": _bars("300114.SZ", [20230111])},
        official_suspension_event=APPROVED_300114_SUSPENSION_EVENT,
    )
    encoded = json.loads(json.dumps(result.as_dict(), ensure_ascii=False, default=str))
    replayed = MonthCompletenessEvaluation.from_mapping(encoded)

    assert replayed == result
    assert replayed.official_suspension_event == APPROVED_300114_SUSPENSION_EVENT
    assert encoded["official_suspension_event"]["source_urls"] == list(
        APPROVED_300114_SUSPENSION_EVENT.source_urls
    )


def test_tampered_official_suspension_source_is_rejected() -> None:
    symbols = ["300114.SZ"]
    days = [20230111, 20230112]
    result = evaluate_month_completeness(
        monthly_symbols=symbols,
        trading_days=days,
        exact_day_universes=dict.fromkeys(days, symbols),
        status_payload={"300114.SZ": _status(day_values=[20230111], flags=[0])},
        daily_bar_payload={"300114.SZ": _bars("300114.SZ", [20230111])},
        official_suspension_event=APPROVED_300114_SUSPENSION_EVENT,
    )
    payload = result.as_dict()
    event = payload["official_suspension_event"]
    assert isinstance(event, dict)
    event["source_urls"][0] = "https://example.invalid/not-official"

    with pytest.raises(MonthCompletenessError, match="month completeness evaluation is malformed"):
        MonthCompletenessEvaluation.from_mapping(payload)


@pytest.mark.parametrize("list_date", (date(2024, 1, 2), date(2024, 1, 1)))
def test_session_on_or_after_list_date_still_requires_normal_status_or_bar_evidence(
    list_date: date,
) -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["000001.SZ"] = pl.DataFrame()
    bars["000001.SZ"] = _bars("000001.SZ", [])

    result = evaluate_month_completeness(
        **values,
        list_dates_by_symbol={"000001.SZ": list_date},
    )

    assert not result.accepted
    assert result.unresolved_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.NOT_APPLICABLE_SESSION.value] == 1
    assert result.classification_counts[CompletenessPairClass.UNRESOLVED.value] == 1
    assert result.prelisting_list_dates == {}


@pytest.mark.parametrize("list_date", (None, "malformed-list-date"))
def test_missing_or_malformed_list_date_does_not_resolve_an_unresolved_pair(
    list_date: object,
) -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["000001.SZ"] = pl.DataFrame()
    bars["000001.SZ"] = _bars("000001.SZ", [])

    result = evaluate_month_completeness(
        **values,
        list_dates_by_symbol={"000001.SZ": list_date},
    )

    assert not result.accepted
    assert result.unresolved_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.UNRESOLVED.value] == 1
    assert result.classification_counts[CompletenessPairClass.NOT_APPLICABLE_SESSION.value] == 1
    assert result.prelisting_list_dates == {}


@pytest.mark.parametrize("duplicate_flags", ([0, 1, 1], [0, 0, 1]))
def test_duplicate_status_date_fails_closed_without_row_order_authority(
    duplicate_flags: list[int],
) -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["600000.SH"] = _status(
        day_values=[20240102, 20240102, 20240103],
        flags=duplicate_flags,
    )

    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert "STATUS_DUPLICATE_DATE" in result.structural_error_codes
    # The invalid member contributes no status facts: neither duplicate row
    # can make the pair active or suspended based on response order.
    assert result.required_bar_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.SUSPENSION_NON_TRADING.value] == 0
    assert result.unresolved_pair_count == 2


def test_active_missing_bar_is_unexplained_and_fail_closed() -> None:
    values = _valid_inputs()
    values["daily_bar_payload"] = {
        "000001.SZ": pl.DataFrame(
            {
                "code": ["000001.SZ"],
                "kline_time": [20240102],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [100.0],
                "amount": [1000.0],
            }
        ),
        "600000.SH": _bars("600000.SH", []),
    }
    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert result.missing_required_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.UNEXPLAINED_MISSING.value] == 1
    with pytest.raises(MonthCompletenessError):
        result.require_accepted()


def test_missing_status_is_unresolved_not_not_applicable() -> None:
    values = _valid_inputs()
    values["status_payload"] = {
        "000001.SZ": _status(day_values=[20240102], flags=[0]),
        "600000.SH": _status(day_values=[20240102], flags=[0]),
    }
    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert result.unresolved_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.UNRESOLVED.value] == 1
    assert result.classification_counts[CompletenessPairClass.NOT_APPLICABLE_SESSION.value] == 1


def test_schema_valid_empty_non_applicable_table_is_allowed() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["000001.SZ"] = _status(day_values=[], flags=[])
    bars["000001.SZ"] = _bars("000001.SZ", [])
    values["exact_day_universes"] = {
        20240102: ["600000.SH"],
        20240103: ["600000.SH"],
    }

    result = evaluate_month_completeness(**values)

    assert result.accepted
    assert result.classification_counts[CompletenessPairClass.NOT_APPLICABLE_SESSION.value] == 2


def test_empty_status_for_an_applicable_security_remains_unresolved() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = _status(day_values=[], flags=[])

    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert result.unresolved_pair_count == 1


def test_zero_column_status_uses_positive_num_trades_as_active_fact() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = pl.DataFrame()
    evidence = PositiveTradeFallback(
        queried_pairs={("000001.SZ", 20240102)},
        positive_pairs={("000001.SZ", 20240102)},
        request_params_by_pair={("000001.SZ", 20240102): "a" * 64},
    )

    result = evaluate_month_completeness(**values, positive_trade_fallback=evidence)

    assert result.accepted
    assert result.positive_trade_pair_count == 1
    assert (
        result.classification_counts[CompletenessPairClass.POSITIVE_TRADE_COUNT_ACTIVE.value] == 1
    )
    assert result.required_bar_pair_count == 2


def test_positive_trade_fallback_keeps_request_evidence_mapping_type() -> None:
    evidence = PositiveTradeFallback(
        queried_pairs={("000001.SZ", 20240102)},
        positive_pairs={("000001.SZ", 20240102)},
        request_params_by_pair={("000001.SZ", 20240102): "a" * 64},
    )

    assert isinstance(evidence.request_params_by_pair, Mapping)
    assert dict(evidence.request_params_by_pair) == {("000001.SZ", 20240102): "a" * 64}
    with pytest.raises(TypeError):
        evidence.request_params_by_pair[("000001.SZ", 20240103)] = "b" * 64  # type: ignore[index]


def test_zero_num_trades_does_not_resolve_an_empty_status_member() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = pl.DataFrame()
    evidence = PositiveTradeFallback(
        queried_pairs={("000001.SZ", 20240102)},
        positive_pairs=set(),
        request_params_by_pair={("000001.SZ", 20240102): "b" * 64},
    )

    result = evaluate_month_completeness(**values, positive_trade_fallback=evidence)

    assert not result.accepted
    assert result.unresolved_pair_count == 1
    assert result.positive_trade_pair_count == 0


def test_missing_snapshot_remains_unresolved() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = pl.DataFrame()
    evidence = PositiveTradeFallback(
        queried_pairs={("000001.SZ", 20240102)},
        positive_pairs=set(),
        request_params_by_pair={("000001.SZ", 20240102): "c" * 64},
    )

    result = evaluate_month_completeness(**values, positive_trade_fallback=evidence)

    assert result.unresolved_pair_count == 1
    assert result.classification_counts[CompletenessPairClass.UNRESOLVED.value] == 1


def test_partial_status_schema_cannot_use_positive_fallback() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = _status(day_values=[20240102], flags=[0])
    evidence = PositiveTradeFallback(
        queried_pairs={("000001.SZ", 20240103)},
        positive_pairs={("000001.SZ", 20240103)},
        request_params_by_pair={("000001.SZ", 20240103): "d" * 64},
    )

    result = evaluate_month_completeness(**values, positive_trade_fallback=evidence)

    assert not result.accepted
    assert result.positive_trade_pair_count == 0
    assert "POSITIVE_TRADE_FALLBACK_QUERY_SCOPE_MISMATCH" in result.structural_error_codes


def test_plain_empty_list_status_is_not_fallback_eligible() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = []
    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert result.unresolved_pair_count == 1


def test_request_hashes_must_be_bound_to_exact_pairs() -> None:
    with pytest.raises(MonthCompletenessError, match="pair-bound"):
        PositiveTradeFallback(
            queried_pairs={("000001.SZ", 20240102)},
            positive_pairs={("000001.SZ", 20240102)},
            request_params_by_pair=["a" * 64],  # type: ignore[arg-type]
        )


def test_caller_supplied_fallback_observation_is_rejected() -> None:
    with pytest.raises(MonthCompletenessError, match="typed evidence"):
        evaluate_month_completeness(**_valid_inputs(), positive_trade_fallback={"pairs": []})


def test_snapshot_identity_and_activity_checks_are_narrow() -> None:
    frame = pl.DataFrame(
        {
            "code": ["000001.SZ"],
            "trade_time": [2024_01_02],
            "num_trades": [3],
        }
    )
    positive, errors = _snapshot_trade_observation(
        {"000001.SZ": frame}, symbol="000001.SZ", trading_day=20240102
    )
    assert positive and not errors

    wrong_code, code_errors = _snapshot_trade_observation(
        {"000001.SZ": frame.with_columns(pl.lit("600000.SH").alias("code"))},
        symbol="000001.SZ",
        trading_day=20240102,
    )
    assert not wrong_code and "SNAPSHOT_SECURITY_IDENTITY_MISMATCH" in code_errors

    wrong_date, date_errors = _snapshot_trade_observation(
        {"000001.SZ": frame.with_columns(pl.lit(20240103).alias("trade_time"))},
        symbol="000001.SZ",
        trading_day=20240102,
    )
    assert not wrong_date and "SNAPSHOT_DATE_IDENTITY_MISMATCH" in date_errors

    missing_identity, identity_errors = _snapshot_trade_observation(
        {"000001.SZ": frame.drop("trade_time")},
        symbol="000001.SZ",
        trading_day=20240102,
    )
    assert not missing_identity and "SNAPSHOT_DATE_IDENTITY_MISSING" in identity_errors

    zero, zero_errors = _snapshot_trade_observation(
        {"000001.SZ": frame.with_columns(pl.lit(0).alias("num_trades"))},
        symbol="000001.SZ",
        trading_day=20240102,
    )
    assert not zero and not zero_errors

    missing_activity, missing_activity_errors = _snapshot_trade_observation(
        {"000001.SZ": frame.drop("num_trades")},
        symbol="000001.SZ",
        trading_day=20240102,
    )
    assert not missing_activity and not missing_activity_errors


def test_null_daily_member_is_allowed_when_all_pairs_are_suspended() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    bars = values["daily_bar_payload"]
    assert isinstance(status, dict)
    assert isinstance(bars, dict)
    status["000001.SZ"] = _status(day_values=[20240102], flags=[1])
    bars["000001.SZ"] = None

    result = evaluate_month_completeness(**values)

    assert result.accepted
    assert result.classification_counts[CompletenessPairClass.SUSPENSION_NON_TRADING.value] == 2
    assert result.required_bar_pair_count == 1
    assert (
        result.classification_counts[
            CompletenessPairClass.PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH.value
        ]
        == 0
    )


def test_null_daily_member_for_required_security_fails_closed() -> None:
    values = _valid_inputs()
    bars = values["daily_bar_payload"]
    assert isinstance(bars, dict)
    bars["000001.SZ"] = None

    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert "DAILY_NULL_TABLE_FOR_REQUIRED_SECURITY" in result.structural_error_codes
    assert result.missing_required_pair_count == 1


def test_shape_drift_and_extra_rows_fail_closed() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["600000.SH"] = status["600000.SH"].rename({"IS_SUSP_SEC": "SUSPENDED"})
    bars = values["daily_bar_payload"]
    assert isinstance(bars, dict)
    bars["000001.SZ"] = _bars("000001.SZ", [20240102, 20240103])
    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert (
        result.classification_counts[
            CompletenessPairClass.PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH.value
        ]
        > 0
    )
    assert result.classification_counts[CompletenessPairClass.EXTRA_RETURNED.value] > 0


def test_evaluation_round_trip_is_exact_and_sanitized() -> None:
    result = evaluate_month_completeness(**_valid_inputs())
    encoded = json.dumps(result.as_dict(), ensure_ascii=False, default=str)
    replayed = MonthCompletenessEvaluation.from_mapping(json.loads(encoded))

    assert replayed == result
    assert "000001.SZ" not in encoded
    assert "applicable_pair_set_hash" not in encoded
    assert "suspended_pair_set_hash" not in encoded
    assert "not_applicable_pair_set_hash" not in encoded
    assert "applicability_semantics_version" not in encoded
    assert "positive_trade_fallback_version" not in encoded


def test_evaluation_round_trip_preserves_used_delist_fact() -> None:
    result = evaluate_month_completeness(
        **_valid_inputs(),
        delist_dates_by_symbol={"600000.SH": date(2024, 1, 3)},
    )
    encoded = json.loads(json.dumps(result.as_dict(), ensure_ascii=False, default=str))
    replayed = MonthCompletenessEvaluation.from_mapping(encoded)

    assert replayed.as_dict() == result.as_dict()
    assert replayed.postdelisting_delist_dates == {"600000.SH": date(2024, 1, 3)}


def test_unknown_month_semantic_rule_version_cannot_replay() -> None:
    result = evaluate_month_completeness(**_valid_inputs())
    payload = result.as_dict()
    payload["rule_version"] = "amazingdata-month-completeness-rule-v1"
    with pytest.raises(MonthCompletenessError, match="unknown month completeness rule version"):
        MonthCompletenessEvaluation.from_mapping(payload)

