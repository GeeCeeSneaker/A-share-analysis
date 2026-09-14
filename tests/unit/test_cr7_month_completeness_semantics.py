"""Offline tests for the versioned CR-7 expected-bar-set rule."""

from __future__ import annotations

import json

import polars as pl
import pytest

from ashare_state.providers.amazingdata.month_completeness import (
    CompletenessPairClass,
    MonthCompletenessError,
    MonthCompletenessEvaluation,
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
    assert result.applicable_pair_count == 3
    assert result.suspended_pair_count == 1
    assert result.not_applicable_pair_count == 1
    assert result.required_bar_pair_count == 2
    assert result.returned_bar_pair_count == 2
    assert result.classification_counts == {
        CompletenessPairClass.SUSPENSION_NON_TRADING.value: 1,
        CompletenessPairClass.NOT_APPLICABLE_SESSION.value: 1,
        CompletenessPairClass.PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH.value: 0,
        CompletenessPairClass.UNEXPLAINED_MISSING.value: 0,
        CompletenessPairClass.UNRESOLVED.value: 0,
        CompletenessPairClass.EXTRA_RETURNED.value: 0,
    }


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
    assert result.not_applicable_pair_count == 1


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
    assert result.not_applicable_pair_count == 2


def test_empty_status_for_an_applicable_security_remains_unresolved() -> None:
    values = _valid_inputs()
    status = values["status_payload"]
    assert isinstance(status, dict)
    status["000001.SZ"] = _status(day_values=[], flags=[])

    result = evaluate_month_completeness(**values)

    assert not result.accepted
    assert result.unresolved_pair_count == 1


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
    assert result.suspended_pair_count == 2
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
