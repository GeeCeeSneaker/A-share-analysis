"""Deterministic CR-5 feature computation from typed ReadModel rows.

DuckDB is used only to retrieve an explicitly ordered, verified input
projection. Formula truth lives here in Python so aggregation order and
missingness behavior are declared rather than delegated to a query planner.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import polars as pl

from ashare_state.features import formulas
from ashare_state.features.models import (
    FEATURE_CONTRACT_VERSION,
    FeatureBuilderError,
    FeatureFinding,
    canonical_json,
    lineage_hash,
    semantic_hash,
)
from ashare_state.features.registry import (
    FEATURE_SET_ID,
    UNIVERSE_RULE_ID,
    FeatureSet,
)

__all__ = [
    "FEATURE_ARTIFACT_NAMES",
    "FINDING_COLUMNS",
    "MARKET_FEATURE_COLUMNS",
    "SECURITY_FEATURE_COLUMNS",
    "ComputedFeatureSet",
    "FeatureEngineError",
    "compute_feature_set",
    "feature_artifact_columns",
    "feature_artifact_schema",
    "frame_for_artifact",
]


SECURITY_FEATURE_COLUMNS = (
    "security_id",
    "trade_date",
    "source_snapshot_id",
    "source_canonical_run_id",
    "feature_run_id",
    "feature_set_id",
    "feature_contract_version",
    "feature_available_at",
    "input_lineage_hash",
    "raw_return_1",
    "gap_open_raw",
    "intraday_return_raw",
    "amplitude_preclose_raw",
    "ma_close_obs_5",
    "ma_close_obs_20",
    "ma_close_obs_60",
    "close_to_ma_obs_5",
    "close_to_ma_obs_20",
    "close_to_ma_obs_60",
    "return_lag_obs_5",
    "return_lag_obs_20",
    "return_lag_obs_60",
    "amount_to_mean_obs_20",
    "vol_raw_return_obs_20",
)

MARKET_FEATURE_COLUMNS = (
    "trade_date",
    "source_snapshot_id",
    "feature_run_id",
    "feature_set_id",
    "feature_available_at",
    "input_lineage_hash",
    "universe_rule_id",
    "observed_security_count",
    "valid_raw_return_count",
    "advancer_count",
    "decliner_count",
    "unchanged_count",
    "advancer_ratio_observed",
    "mean_raw_return_observed",
    "median_raw_return_observed",
    "valid_ma20_count",
    "pct_above_ma20_observed",
    "valid_mom20_count",
    "pct_positive_mom20_observed",
    "total_amount_observed",
)

FINDING_COLUMNS = (
    "scope",
    "security_id",
    "trade_date",
    "feature_name",
    "finding_class",
    "detail_json",
)

FEATURE_ARTIFACT_NAMES = (
    "security_daily_features",
    "market_daily_features",
    "feature_findings",
)


class FeatureEngineError(FeatureBuilderError):
    """The verified ReadModel rows violate the feature input contract."""


@dataclass(frozen=True)
class ComputedFeatureSet:
    security_rows: tuple[dict[str, Any], ...]
    market_rows: tuple[dict[str, Any], ...]
    finding_rows: tuple[dict[str, Any], ...]

    @property
    def feature_semantic_hash(self) -> str:
        return semantic_hash(
            (
                *self.security_rows,
                *self.market_rows,
            )
        )

    @property
    def finding_set_hash(self) -> str:
        return semantic_hash(self.finding_rows)


Reason = tuple[str, dict[str, Any]] | None
NumericState = tuple[str, float | None]


def _numeric(row: Mapping[str, Any], name: str) -> NumericState:
    value = row.get(name)
    if value is None:
        return "null", None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FeatureEngineError(f"daily_bar input {name} has an invalid typed value: {value!r}")
    converted = float(value)
    if not math.isfinite(converted):
        return "nonfinite", None
    return "ok", converted


def _reason_for_input(state: str, name: str) -> Reason:
    if state == "null":
        return "INPUT_NULL", {"input": name}
    if state == "nonfinite":
        return "NON_FINITE_RESULT", {"input": name, "reason": "non-finite input"}
    return None


def _binary_feature(
    row: Mapping[str, Any],
    *,
    feature_name: str,
    numerator_name: str,
    denominator_name: str,
    formula: Callable[[float, float], float | None],
) -> tuple[float | None, Reason]:
    numerator_state, numerator = _numeric(row, numerator_name)
    denominator_state, denominator = _numeric(row, denominator_name)
    if denominator_state != "ok":
        if denominator_state == "nonfinite":
            return None, (
                "NON_FINITE_RESULT",
                {"input": denominator_name, "reason": "non-finite denominator"},
            )
        return None, (
            "UNSAFE_DENOMINATOR",
            {"denominator": denominator_name, "reason": "null denominator"},
        )
    assert denominator is not None
    if denominator <= 0:
        return None, (
            "UNSAFE_DENOMINATOR",
            {"denominator": denominator_name, "reason": "must be greater than zero"},
        )
    reason = _reason_for_input(numerator_state, numerator_name)
    if reason is not None:
        return None, reason
    assert numerator is not None
    value = formula(numerator, denominator)
    if value is None or not math.isfinite(value):
        return None, (
            "NON_FINITE_RESULT",
            {"formula": feature_name, "reason": "formula returned non-finite"},
        )
    return value, None


def _amplitude_feature(row: Mapping[str, Any]) -> tuple[float | None, Reason]:
    high_state, high = _numeric(row, "high")
    low_state, low = _numeric(row, "low")
    denominator_state, denominator = _numeric(row, "pre_close")
    if denominator_state != "ok":
        if denominator_state == "nonfinite":
            return None, (
                "NON_FINITE_RESULT",
                {"input": "pre_close", "reason": "non-finite denominator"},
            )
        return None, (
            "UNSAFE_DENOMINATOR",
            {"denominator": "pre_close", "reason": "null denominator"},
        )
    assert denominator is not None
    if denominator <= 0:
        return None, (
            "UNSAFE_DENOMINATOR",
            {"denominator": "pre_close", "reason": "must be greater than zero"},
        )
    for state, name in ((high_state, "high"), (low_state, "low")):
        reason = _reason_for_input(state, name)
        if reason is not None:
            return None, reason
    assert high is not None and low is not None
    value = formulas.amplitude_preclose_raw(high, low, denominator)
    if value is None or not math.isfinite(value):
        return None, (
            "NON_FINITE_RESULT",
            {"formula": "amplitude_preclose_raw", "reason": "formula returned non-finite"},
        )
    return value, None


def _fixed_close_window(
    rows: Sequence[Mapping[str, Any]],
    *,
    index: int,
    length: int,
) -> tuple[float | None, Reason, tuple[Mapping[str, Any], ...]]:
    window = tuple(rows[max(0, index + 1 - length) : index + 1])
    if len(window) != length:
        return (
            None,
            (
                "INSUFFICIENT_HISTORY",
                {"window_basis": "OBSERVED_SECURITY_BARS", "required": length},
            ),
            window,
        )
    values: list[float] = []
    for row in window:
        state, value = _numeric(row, "close")
        reason = _reason_for_input(state, "close")
        if reason is not None:
            return None, reason, window
        assert value is not None
        values.append(value)
    value = formulas.ordered_mean(values)
    if value is None:
        return (
            None,
            ("NON_FINITE_RESULT", {"formula": f"ma_close_obs_{length}"}),
            window,
        )
    return value, None, window


def _lag_close_feature(
    rows: Sequence[Mapping[str, Any]],
    *,
    index: int,
    lag: int,
) -> tuple[float | None, Reason, tuple[Mapping[str, Any], ...]]:
    if index < lag:
        return (
            None,
            (
                "INSUFFICIENT_HISTORY",
                {"window_basis": "OBSERVED_SECURITY_BARS", "required_prior_bars": lag},
            ),
            tuple(rows[: index + 1]),
        )
    inputs = tuple(rows[index - lag : index + 1])
    current_state, current = _numeric(rows[index], "close")
    prior_state, prior = _numeric(rows[index - lag], "close")
    for state, name in ((current_state, "close"), (prior_state, "close")):
        reason = _reason_for_input(state, name)
        if reason is not None:
            return None, reason, inputs
    assert current is not None and prior is not None
    value = formulas.lag_return(current, prior)
    if value is None:
        return None, ("NON_FINITE_RESULT", {"formula": f"return_lag_obs_{lag}"}), inputs
    return value, None, inputs


def _add_finding(
    findings: list[FeatureFinding],
    *,
    scope: str,
    security_id: str | None,
    trade_date: date,
    feature_name: str,
    reason: Reason,
) -> None:
    if reason is None:
        return
    finding_class, detail = reason
    findings.append(
        FeatureFinding(
            scope=scope,
            security_id=security_id,
            trade_date=trade_date,
            feature_name=feature_name,
            finding_class=finding_class,
            detail_json=canonical_json(detail),
        )
    )


def _prepare_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_id: str,
    canonical_run_id: str,
    snapshot_as_of: datetime,
) -> list[dict[str, Any]]:
    if snapshot_as_of.tzinfo is None:
        raise FeatureEngineError("snapshot_as_of must be timezone-aware")
    as_of = snapshot_as_of.astimezone(UTC)
    required = (
        "canonical_domain",
        "canonical_key",
        "security_id",
        "trade_date",
        "available_at",
        "snapshot_id",
        "canonical_run_id",
        "source_row_identity_hash",
    )
    prepared: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise FeatureEngineError(f"ReadModel row is not a mapping: {raw!r}")
        row = dict(raw)
        missing = [name for name in required if name not in row]
        if missing:
            raise FeatureEngineError(f"ReadModel daily_bar row misses columns: {missing}")
        if row["canonical_domain"] != "daily_bar":
            raise FeatureEngineError("Feature input carries a foreign canonical_domain")
        if row["snapshot_id"] != snapshot_id:
            raise FeatureEngineError("Feature input carries a foreign snapshot_id")
        if row["canonical_run_id"] != canonical_run_id:
            raise FeatureEngineError("Feature input carries a foreign canonical_run_id")
        security_id = row["security_id"]
        if not isinstance(security_id, str) or not security_id:
            raise FeatureEngineError("Feature input has no typed security_id")
        trade_date = row["trade_date"]
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise FeatureEngineError("Feature input trade_date is not a date")
        available_at = row["available_at"]
        if not isinstance(available_at, datetime) or available_at.tzinfo is None:
            raise FeatureEngineError("Feature input available_at is not timezone-aware")
        available_at = available_at.astimezone(UTC)
        if available_at > as_of:
            raise FeatureEngineError(
                f"Feature input {row.get('canonical_key')!r} is available after snapshot_as_of"
            )
        canonical_key = row["canonical_key"]
        if not isinstance(canonical_key, str) or not canonical_key:
            raise FeatureEngineError("Feature input has no canonical_key")
        source_identity = row["source_row_identity_hash"]
        if not isinstance(source_identity, str) or not source_identity:
            raise FeatureEngineError("Feature input has no source_row_identity_hash")
        row["available_at"] = available_at
        prepared.append(row)
    prepared.sort(
        key=lambda row: (
            str(row["security_id"]),
            row["trade_date"],
            str(row["canonical_key"]),
        )
    )
    seen_security_dates: set[tuple[str, date]] = set()
    seen_keys: set[str] = set()
    for row in prepared:
        key = str(row["canonical_key"])
        security_date = (str(row["security_id"]), row["trade_date"])
        if key in seen_keys:
            raise FeatureEngineError(f"duplicate ReadModel canonical_key {key!r}")
        if security_date in seen_security_dates:
            raise FeatureEngineError(
                f"duplicate ReadModel security/date identity {security_date!r}"
            )
        seen_keys.add(key)
        seen_security_dates.add(security_date)
    return prepared


def _ordered_unique_inputs(
    input_rows: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    ordered = sorted(
        input_rows.values(),
        key=lambda row: (row["trade_date"], str(row["canonical_key"])),
    )
    result: list[dict[str, Any]] = []
    for row in ordered:
        result.append(
            {
                "domain": "daily_bar",
                "canonical_key": str(row["canonical_key"]),
                "source_row_identity_hash": str(row["source_row_identity_hash"]),
                "available_at": row["available_at"],
            }
        )
    return tuple(result)


def _security_features(
    rows: Sequence[dict[str, Any]],
    *,
    snapshot_id: str,
    canonical_run_id: str,
    feature_run_id: str,
    feature_set: FeatureSet,
    snapshot_as_of: datetime,
) -> tuple[list[dict[str, Any]], list[FeatureFinding], list[dict[str, Any]]]:
    findings: list[FeatureFinding] = []
    result_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["security_id"]), []).append(row)

    for security_id in sorted(grouped):
        security_rows = grouped[security_id]
        valid_raw_rows: list[tuple[dict[str, Any], float]] = []
        for index, row in enumerate(security_rows):
            trade_date = row["trade_date"]
            input_rows: dict[str, Mapping[str, Any]] = {str(row["canonical_key"]): row}
            feature_values: dict[str, float | None] = {}
            reasons: dict[str, Reason] = {}

            def store(
                name: str,
                value: float | None,
                reason: Reason,
                *,
                feature_values: dict[str, float | None] = feature_values,
                reasons: dict[str, Reason] = reasons,
                security_id: str = security_id,
                trade_date: date = trade_date,
            ) -> None:
                feature_values[name] = value
                reasons[name] = reason
                _add_finding(
                    findings,
                    scope="security_daily",
                    security_id=security_id,
                    trade_date=trade_date,
                    feature_name=name,
                    reason=reason,
                )

            raw_value, raw_reason = _binary_feature(
                row,
                feature_name="raw_return_1",
                numerator_name="close",
                denominator_name="pre_close",
                formula=formulas.raw_return_1,
            )
            store("raw_return_1", raw_value, raw_reason)
            if raw_value is not None:
                valid_raw_rows.append((row, raw_value))

            gap_value, gap_reason = _binary_feature(
                row,
                feature_name="gap_open_raw",
                numerator_name="open",
                denominator_name="pre_close",
                formula=formulas.gap_open_raw,
            )
            store("gap_open_raw", gap_value, gap_reason)

            intraday_value, intraday_reason = _binary_feature(
                row,
                feature_name="intraday_return_raw",
                numerator_name="close",
                denominator_name="open",
                formula=formulas.intraday_return_raw,
            )
            store("intraday_return_raw", intraday_value, intraday_reason)

            amplitude_value, amplitude_reason = _amplitude_feature(row)
            store("amplitude_preclose_raw", amplitude_value, amplitude_reason)

            ma_reasons: dict[int, Reason] = {}
            ma_inputs: dict[int, tuple[Mapping[str, Any], ...]] = {}
            for length in (5, 20, 60):
                name = f"ma_close_obs_{length}"
                ma_value, ma_reason, window = _fixed_close_window(
                    security_rows,
                    index=index,
                    length=length,
                )
                ma_inputs[length] = window
                for input_row in window:
                    input_rows[str(input_row["canonical_key"])] = input_row
                ma_reasons[length] = ma_reason
                store(name, ma_value, ma_reason)

            for length in (5, 20, 60):
                name = f"close_to_ma_obs_{length}"
                window = ma_inputs[length]
                for input_row in window:
                    input_rows[str(input_row["canonical_key"])] = input_row
                close_state, close = _numeric(row, "close")
                reason = _reason_for_input(close_state, "close")
                if reason is None and feature_values[f"ma_close_obs_{length}"] is None:
                    reason = ma_reasons[length] or (
                        "INPUT_NULL",
                        {"dependency": f"ma_close_obs_{length}"},
                    )
                if reason is not None:
                    close_to_ma_value = None
                else:
                    assert close is not None
                    mean_value = feature_values[f"ma_close_obs_{length}"]
                    assert mean_value is not None
                    close_to_ma_value = formulas.close_to_mean(close, mean_value)
                    if close_to_ma_value is None:
                        reason = (
                            "NON_FINITE_RESULT",
                            {"formula": f"close_to_ma_obs_{length}"},
                        )
                store(name, close_to_ma_value, reason)

            for lag in (5, 20, 60):
                name = f"return_lag_obs_{lag}"
                lag_value, lag_reason, inputs = _lag_close_feature(
                    security_rows,
                    index=index,
                    lag=lag,
                )
                for input_row in inputs:
                    input_rows[str(input_row["canonical_key"])] = input_row
                store(name, lag_value, lag_reason)

            amount_state, current_amount = _numeric(row, "amount")
            if amount_state != "ok":
                amount_reason = _reason_for_input(amount_state, "amount")
                if amount_reason is None:
                    amount_reason = (
                        "INPUT_NULL",
                        {"input": "amount"},
                    )
                amount_value = None
            else:
                assert current_amount is not None
                valid_amount_rows: list[tuple[dict[str, Any], float]] = []
                for candidate in security_rows[: index + 1]:
                    candidate_state, candidate_amount = _numeric(candidate, "amount")
                    if candidate_state == "ok":
                        assert candidate_amount is not None
                        valid_amount_rows.append((candidate, candidate_amount))
                if len(valid_amount_rows) < 20:
                    amount_reason = (
                        "INSUFFICIENT_HISTORY",
                        {
                            "window_basis": "OBSERVED_SECURITY_BARS",
                            "required_valid_amounts": 20,
                        },
                    )
                    amount_value = None
                    for input_row, _ in valid_amount_rows:
                        input_rows[str(input_row["canonical_key"])] = input_row
                else:
                    amount_window = valid_amount_rows[-20:]
                    for input_row, _ in amount_window:
                        input_rows[str(input_row["canonical_key"])] = input_row
                    mean_amount = formulas.ordered_mean([value for _, value in amount_window])
                    amount_value = (
                        formulas.amount_to_mean(current_amount, mean_amount)
                        if mean_amount is not None
                        else None
                    )
                    amount_reason = (
                        None
                        if amount_value is not None
                        else (
                            "UNSAFE_DENOMINATOR",
                            {"denominator": "mean(last_20_valid_amounts)"},
                        )
                    )
                    missing_amounts = (index + 1) - len(valid_amount_rows)
                    if missing_amounts:
                        findings.append(
                            FeatureFinding(
                                scope="security_daily",
                                security_id=security_id,
                                trade_date=trade_date,
                                feature_name="amount_to_mean_obs_20",
                                finding_class="OPTIONAL_INPUT_MISSING",
                                detail_json=canonical_json(
                                    {"skipped_invalid_or_null_amount_rows": missing_amounts}
                                ),
                            )
                        )
            store("amount_to_mean_obs_20", amount_value, amount_reason)

            if len(valid_raw_rows) < 20:
                volatility_reason: Reason = (
                    "INSUFFICIENT_HISTORY",
                    {
                        "window_basis": "OBSERVED_SECURITY_BARS",
                        "required_valid_raw_returns": 20,
                    },
                )
                volatility_value = None
                volatility_inputs = valid_raw_rows
            else:
                volatility_inputs = valid_raw_rows[-20:]
                volatility_value = formulas.ordered_population_std(
                    [value for _, value in volatility_inputs]
                )
                volatility_reason = (
                    None
                    if volatility_value is not None
                    else (
                        "NON_FINITE_RESULT",
                        {"formula": "vol_raw_return_obs_20"},
                    )
                )
            for input_row, _ in volatility_inputs:
                input_rows[str(input_row["canonical_key"])] = input_row
            if len(valid_raw_rows) != index + 1:
                findings.append(
                    FeatureFinding(
                        scope="security_daily",
                        security_id=security_id,
                        trade_date=trade_date,
                        feature_name="vol_raw_return_obs_20",
                        finding_class="OPTIONAL_INPUT_MISSING",
                        detail_json=canonical_json(
                            {"skipped_invalid_raw_return_rows": (index + 1) - len(valid_raw_rows)}
                        ),
                    )
                )
            store("vol_raw_return_obs_20", volatility_value, volatility_reason)

            ordered_inputs = _ordered_unique_inputs(input_rows)
            available_at = max(item["available_at"] for item in ordered_inputs)
            if available_at > snapshot_as_of.astimezone(UTC):
                raise FeatureEngineError(
                    f"feature row {security_id}/{trade_date} is available after snapshot_as_of"
                )
            row_lineage_hash = lineage_hash(ordered_inputs)
            output = {
                "security_id": security_id,
                "trade_date": trade_date,
                "source_snapshot_id": snapshot_id,
                "source_canonical_run_id": canonical_run_id,
                "feature_run_id": feature_run_id,
                "feature_set_id": feature_set.feature_set_id,
                "feature_contract_version": FEATURE_CONTRACT_VERSION,
                "feature_available_at": available_at,
                "input_lineage_hash": row_lineage_hash,
            }
            output.update(feature_values)
            result_rows.append(output)
            records.append(
                {
                    "security_id": security_id,
                    "trade_date": trade_date,
                    "feature_row": output,
                    "features": feature_values,
                    "input_lineage_hash": row_lineage_hash,
                    "feature_available_at": available_at,
                    "source_row": row,
                    "reasons": reasons,
                }
            )
    result_rows.sort(key=lambda row: (row["security_id"], row["trade_date"]))
    records.sort(key=lambda record: (record["security_id"], record["trade_date"]))
    return result_rows, findings, records


def _market_features(
    records: Sequence[Mapping[str, Any]],
    *,
    snapshot_id: str,
    feature_run_id: str,
    feature_set: FeatureSet,
) -> tuple[list[dict[str, Any]], list[FeatureFinding]]:
    by_date: dict[date, list[Mapping[str, Any]]] = {}
    for record in records:
        by_date.setdefault(record["trade_date"], []).append(record)

    market_rows: list[dict[str, Any]] = []
    findings: list[FeatureFinding] = []

    def append_missing(
        trade_date: date,
        feature_name: str,
        finding_class: str,
        detail: Mapping[str, Any],
    ) -> None:
        findings.append(
            FeatureFinding(
                scope="market_daily",
                security_id=None,
                trade_date=trade_date,
                feature_name=feature_name,
                finding_class=finding_class,
                detail_json=canonical_json(detail),
            )
        )

    for trade_date in sorted(by_date):
        day_records = sorted(
            by_date[trade_date],
            key=lambda record: str(record["security_id"]),
        )
        raw_values = [
            record["features"]["raw_return_1"]
            for record in day_records
            if record["features"]["raw_return_1"] is not None
            and math.isfinite(float(record["features"]["raw_return_1"]))
        ]
        observed_count = len(day_records)
        valid_raw_count = len(raw_values)
        advancers = sum(value > 0 for value in raw_values)
        decliners = sum(value < 0 for value in raw_values)
        unchanged = sum(value == 0 for value in raw_values)

        if valid_raw_count:
            advancer_ratio = formulas.safe_ratio(advancers, valid_raw_count)
            mean_raw = formulas.ordered_mean(raw_values)
            median_raw = formulas.ordered_median(raw_values)
        else:
            advancer_ratio = None
            mean_raw = None
            median_raw = None
            detail = {"denominator": "valid_raw_return_count", "value": 0}
            append_missing(
                trade_date,
                "advancer_ratio_observed",
                "UNSAFE_DENOMINATOR",
                detail,
            )
            append_missing(
                trade_date,
                "mean_raw_return_observed",
                "UNSAFE_DENOMINATOR",
                detail,
            )
            append_missing(
                trade_date,
                "median_raw_return_observed",
                "UNSAFE_DENOMINATOR",
                detail,
            )

        ma_records = [
            record for record in day_records if record["features"]["ma_close_obs_20"] is not None
        ]
        valid_ma_count = len(ma_records)
        if valid_ma_count:
            pct_above_ma = formulas.safe_ratio(
                sum(record["features"]["close_to_ma_obs_20"] > 0 for record in ma_records),
                valid_ma_count,
            )
        else:
            pct_above_ma = None
            append_missing(
                trade_date,
                "pct_above_ma20_observed",
                "UNSAFE_DENOMINATOR",
                {"denominator": "valid_ma20_count", "value": 0},
            )

        mom_records = [
            record for record in day_records if record["features"]["return_lag_obs_20"] is not None
        ]
        valid_mom_count = len(mom_records)
        if valid_mom_count:
            pct_positive_mom = formulas.safe_ratio(
                sum(record["features"]["return_lag_obs_20"] > 0 for record in mom_records),
                valid_mom_count,
            )
        else:
            pct_positive_mom = None
            append_missing(
                trade_date,
                "pct_positive_mom20_observed",
                "UNSAFE_DENOMINATOR",
                {"denominator": "valid_mom20_count", "value": 0},
            )

        amount_values: list[float] = []
        for record in day_records:
            state, value = _numeric(record["source_row"], "amount")
            if state == "ok":
                assert value is not None
                amount_values.append(value)
        total_amount = math.fsum(amount_values) if amount_values else None
        if total_amount is None or not math.isfinite(total_amount):
            append_missing(
                trade_date,
                "total_amount_observed",
                "INPUT_NULL",
                {"input": "amount", "valid_observed_amounts": 0},
            )
        if len(amount_values) < observed_count:
            append_missing(
                trade_date,
                "total_amount_observed",
                "OPTIONAL_INPUT_MISSING",
                {"missing_observed_amounts": observed_count - len(amount_values)},
            )

        lineage_members = [
            {
                "security_id": str(record["security_id"]),
                "trade_date": record["trade_date"],
                "input_lineage_hash": str(record["input_lineage_hash"]),
            }
            for record in day_records
        ]
        available_at = max(record["feature_available_at"] for record in day_records)
        market_rows.append(
            {
                "trade_date": trade_date,
                "source_snapshot_id": snapshot_id,
                "feature_run_id": feature_run_id,
                "feature_set_id": feature_set.feature_set_id,
                "feature_available_at": available_at,
                "input_lineage_hash": lineage_hash(lineage_members),
                "universe_rule_id": UNIVERSE_RULE_ID,
                "observed_security_count": observed_count,
                "valid_raw_return_count": valid_raw_count,
                "advancer_count": advancers,
                "decliner_count": decliners,
                "unchanged_count": unchanged,
                "advancer_ratio_observed": advancer_ratio,
                "mean_raw_return_observed": mean_raw,
                "median_raw_return_observed": median_raw,
                "valid_ma20_count": valid_ma_count,
                "pct_above_ma20_observed": pct_above_ma,
                "valid_mom20_count": valid_mom_count,
                "pct_positive_mom20_observed": pct_positive_mom,
                "total_amount_observed": total_amount,
            }
        )
    return market_rows, findings


def compute_feature_set(
    readmodel_rows: Sequence[Mapping[str, Any]],
    *,
    snapshot_id: str,
    canonical_run_id: str,
    feature_run_id: str,
    feature_set: FeatureSet,
    snapshot_as_of: datetime,
) -> ComputedFeatureSet:
    """Compute V1 features from one explicitly verified ReadModel world."""
    if feature_set.feature_set_id != FEATURE_SET_ID:
        raise FeatureEngineError(
            f"feature set {feature_set.feature_set_id!r} is not supported by the V1 engine"
        )
    prepared = _prepare_rows(
        readmodel_rows,
        snapshot_id=snapshot_id,
        canonical_run_id=canonical_run_id,
        snapshot_as_of=snapshot_as_of,
    )
    security_rows, security_findings, records = _security_features(
        prepared,
        snapshot_id=snapshot_id,
        canonical_run_id=canonical_run_id,
        feature_run_id=feature_run_id,
        feature_set=feature_set,
        snapshot_as_of=snapshot_as_of,
    )
    market_rows, market_findings = _market_features(
        records,
        snapshot_id=snapshot_id,
        feature_run_id=feature_run_id,
        feature_set=feature_set,
    )
    findings = [
        finding.as_dict()
        for finding in (
            *security_findings,
            *market_findings,
        )
    ]
    findings.sort(
        key=lambda row: (
            row["scope"],
            row["security_id"] or "",
            row["trade_date"],
            row["feature_name"],
            row["finding_class"],
            row["detail_json"],
        )
    )
    return ComputedFeatureSet(
        security_rows=tuple(security_rows),
        market_rows=tuple(market_rows),
        finding_rows=tuple(findings),
    )


def _feature_schemas() -> dict[str, pl.Schema]:
    return {
        "security_daily_features": pl.Schema(
            [
                ("security_id", pl.String()),
                ("trade_date", pl.Date()),
                ("source_snapshot_id", pl.String()),
                ("source_canonical_run_id", pl.String()),
                ("feature_run_id", pl.String()),
                ("feature_set_id", pl.String()),
                ("feature_contract_version", pl.String()),
                ("feature_available_at", pl.Datetime(time_unit="us", time_zone="UTC")),
                ("input_lineage_hash", pl.String()),
                *[(name, pl.Float64()) for name in SECURITY_FEATURE_COLUMNS[9:]],
            ]
        ),
        "market_daily_features": pl.Schema(
            [
                ("trade_date", pl.Date()),
                ("source_snapshot_id", pl.String()),
                ("feature_run_id", pl.String()),
                ("feature_set_id", pl.String()),
                ("feature_available_at", pl.Datetime(time_unit="us", time_zone="UTC")),
                ("input_lineage_hash", pl.String()),
                ("universe_rule_id", pl.String()),
                ("observed_security_count", pl.Int64()),
                ("valid_raw_return_count", pl.Int64()),
                ("advancer_count", pl.Int64()),
                ("decliner_count", pl.Int64()),
                ("unchanged_count", pl.Int64()),
                ("advancer_ratio_observed", pl.Float64()),
                ("mean_raw_return_observed", pl.Float64()),
                ("median_raw_return_observed", pl.Float64()),
                ("valid_ma20_count", pl.Int64()),
                ("pct_above_ma20_observed", pl.Float64()),
                ("valid_mom20_count", pl.Int64()),
                ("pct_positive_mom20_observed", pl.Float64()),
                ("total_amount_observed", pl.Float64()),
            ]
        ),
        "feature_findings": pl.Schema(
            [
                ("scope", pl.String()),
                ("security_id", pl.String()),
                ("trade_date", pl.Date()),
                ("feature_name", pl.String()),
                ("finding_class", pl.String()),
                ("detail_json", pl.String()),
            ]
        ),
    }


_SCHEMAS = _feature_schemas()


def feature_artifact_columns(name: str) -> tuple[str, ...]:
    if name == "security_daily_features":
        return SECURITY_FEATURE_COLUMNS
    if name == "market_daily_features":
        return MARKET_FEATURE_COLUMNS
    if name == "feature_findings":
        return FINDING_COLUMNS
    raise FeatureEngineError(f"unknown feature artifact {name!r}")


def feature_artifact_schema(name: str) -> pl.Schema:
    try:
        return _SCHEMAS[name]
    except KeyError as exc:
        raise FeatureEngineError(f"unknown feature artifact {name!r}") from exc


def frame_for_artifact(
    name: str,
    rows: Sequence[Mapping[str, Any]],
) -> pl.DataFrame:
    columns = feature_artifact_columns(name)
    schema = feature_artifact_schema(name)
    aligned = [{column: row.get(column) for column in columns} for row in rows]
    return pl.DataFrame(aligned, schema=schema)
