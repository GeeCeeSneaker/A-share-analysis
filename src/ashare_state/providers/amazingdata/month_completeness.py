"""Versioned AmazingData month-completeness semantics.

The month-level historical code list is an interval-overlap universe, not a
daily bar expectation.  This module derives a deterministic security/session
set from two positive provider observations:

* an exact-session historical code-list observation; and
* the historical stock-status table, whose ``IS_SUSP_SEC`` flag identifies a
  legitimate non-trading session.

Absence from either response is never treated as a lifecycle fact.  A missing
status row for an applicable pair is unresolved, and malformed or mismatched
responses fail closed.  The output contains only hashes/counts so it is safe
to use as a sanitized diagnostic or bind to an acquisition receipt.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, cast

__all__ = [
    "AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION",
    "AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION",
    "CompletenessPairClass",
    "MonthCompletenessError",
    "MonthCompletenessEvaluation",
    "evaluate_month_completeness",
]


AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION = "amazingdata-month-completeness-rule-v1"
AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION = "amazingdata-hist-code-list-exact-session-v2"

_SYMBOL_PATTERN = re.compile(r"^\d{6}\.(?:SH|SZ)$")
_STATUS_COLUMNS = frozenset(
    {
        "HIGH_LIMITED",
        "IS_ST_SEC",
        "IS_SUSP_SEC",
        "IS_WD_SEC",
        "IS_XR_SEC",
        "LOW_LIMITED",
        "MARKET_CODE",
        "PRECLOSE",
        "PRICE_HIGH_LMT_RATE",
        "PRICE_LOW_LMT_RATE",
        "TRADE_DATE",
    }
)
_DAILY_COLUMNS = frozenset(
    {"amount", "close", "code", "high", "kline_time", "low", "open", "volume"}
)


class MonthCompletenessError(ValueError):
    """The provider responses cannot establish a safe month-completeness set."""


class CompletenessPairClass(StrEnum):
    """Classifications used by the fail-closed semantic gate."""

    SUSPENSION_NON_TRADING = "SUSPENSION_NON_TRADING"
    NOT_APPLICABLE_SESSION = "NOT_APPLICABLE_SESSION"
    PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH = "PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH"
    UNEXPLAINED_MISSING = "UNEXPLAINED_MISSING"
    UNRESOLVED = "UNRESOLVED"
    EXTRA_RETURNED = "EXTRA_RETURNED"


@dataclass(frozen=True)
class MonthCompletenessEvaluation:
    """Deterministic counts and hashes for one bounded month."""

    rule_version: str
    applicability_semantics_version: str
    status: str
    monthly_security_count: int
    session_count: int
    monthly_security_set_hash: str
    session_set_hash: str
    applicable_pair_count: int
    applicable_pair_set_hash: str
    suspended_pair_count: int
    suspended_pair_set_hash: str
    not_applicable_pair_count: int
    not_applicable_pair_set_hash: str
    required_bar_pair_count: int
    required_bar_pair_set_hash: str
    returned_bar_pair_count: int
    returned_bar_pair_set_hash: str
    returned_first_date: date | None
    returned_last_date: date | None
    returned_trading_day_count: int
    returned_trading_days_hash: str
    returned_row_count: int
    missing_required_pair_count: int
    missing_required_pair_set_hash: str
    extra_returned_pair_count: int
    extra_returned_pair_set_hash: str
    unresolved_pair_count: int
    classification_counts: dict[str, int]
    structural_error_codes: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        """Return whether no semantic or structural blocker remains."""
        return self.status == "PASS"

    def require_accepted(self) -> None:
        if not self.accepted:
            raise MonthCompletenessError(
                "AmazingData month completeness is not accepted; "
                "the expected-bar set remains fail-closed"
            )

    def as_dict(self) -> dict[str, Any]:
        """Return a sanitized, canonical-friendly representation."""
        return {
            "rule_version": self.rule_version,
            "applicability_semantics_version": self.applicability_semantics_version,
            "status": self.status,
            "monthly_security_count": self.monthly_security_count,
            "session_count": self.session_count,
            "monthly_security_set_hash": self.monthly_security_set_hash,
            "session_set_hash": self.session_set_hash,
            "applicable_pair_count": self.applicable_pair_count,
            "applicable_pair_set_hash": self.applicable_pair_set_hash,
            "suspended_pair_count": self.suspended_pair_count,
            "suspended_pair_set_hash": self.suspended_pair_set_hash,
            "not_applicable_pair_count": self.not_applicable_pair_count,
            "not_applicable_pair_set_hash": self.not_applicable_pair_set_hash,
            "required_bar_pair_count": self.required_bar_pair_count,
            "required_bar_pair_set_hash": self.required_bar_pair_set_hash,
            "returned_bar_pair_count": self.returned_bar_pair_count,
            "returned_bar_pair_set_hash": self.returned_bar_pair_set_hash,
            "returned_first_date": self.returned_first_date,
            "returned_last_date": self.returned_last_date,
            "returned_trading_day_count": self.returned_trading_day_count,
            "returned_trading_days_hash": self.returned_trading_days_hash,
            "returned_row_count": self.returned_row_count,
            "missing_required_pair_count": self.missing_required_pair_count,
            "missing_required_pair_set_hash": self.missing_required_pair_set_hash,
            "extra_returned_pair_count": self.extra_returned_pair_count,
            "extra_returned_pair_set_hash": self.extra_returned_pair_set_hash,
            "unresolved_pair_count": self.unresolved_pair_count,
            "classification_counts": dict(self.classification_counts),
            "structural_error_codes": list(self.structural_error_codes),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> MonthCompletenessEvaluation:
        """Rehydrate a receipt-bound evaluation with exact fields."""
        fields = {
            "rule_version",
            "applicability_semantics_version",
            "status",
            "monthly_security_count",
            "session_count",
            "monthly_security_set_hash",
            "session_set_hash",
            "applicable_pair_count",
            "applicable_pair_set_hash",
            "suspended_pair_count",
            "suspended_pair_set_hash",
            "not_applicable_pair_count",
            "not_applicable_pair_set_hash",
            "required_bar_pair_count",
            "required_bar_pair_set_hash",
            "returned_bar_pair_count",
            "returned_bar_pair_set_hash",
            "returned_first_date",
            "returned_last_date",
            "returned_trading_day_count",
            "returned_trading_days_hash",
            "returned_row_count",
            "missing_required_pair_count",
            "missing_required_pair_set_hash",
            "extra_returned_pair_count",
            "extra_returned_pair_set_hash",
            "unresolved_pair_count",
            "classification_counts",
            "structural_error_codes",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise MonthCompletenessError("month completeness evaluation fields are not exact")
        counts = payload["classification_counts"]
        errors = payload["structural_error_codes"]
        if not isinstance(counts, Mapping) or set(counts) != {
            item.value for item in CompletenessPairClass
        }:
            raise MonthCompletenessError("month completeness classification counts are malformed")
        if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
            raise MonthCompletenessError("month completeness structural errors are malformed")
        try:
            parsed_counts = {
                str(key): _require_nonnegative_int(value, "classification count")
                for key, value in counts.items()
            }
            values = {
                "rule_version": _require_text(payload["rule_version"], "rule_version"),
                "applicability_semantics_version": _require_text(
                    payload["applicability_semantics_version"],
                    "applicability_semantics_version",
                ),
                "status": _require_status(payload["status"]),
                "monthly_security_count": _require_positive_int(
                    payload["monthly_security_count"], "monthly_security_count"
                ),
                "session_count": _require_positive_int(payload["session_count"], "session_count"),
                "monthly_security_set_hash": _require_hash(
                    payload["monthly_security_set_hash"], "monthly_security_set_hash"
                ),
                "session_set_hash": _require_hash(payload["session_set_hash"], "session_set_hash"),
                "applicable_pair_count": _require_nonnegative_int(
                    payload["applicable_pair_count"], "applicable_pair_count"
                ),
                "applicable_pair_set_hash": _require_hash(
                    payload["applicable_pair_set_hash"], "applicable_pair_set_hash"
                ),
                "suspended_pair_count": _require_nonnegative_int(
                    payload["suspended_pair_count"], "suspended_pair_count"
                ),
                "suspended_pair_set_hash": _require_hash(
                    payload["suspended_pair_set_hash"], "suspended_pair_set_hash"
                ),
                "not_applicable_pair_count": _require_nonnegative_int(
                    payload["not_applicable_pair_count"], "not_applicable_pair_count"
                ),
                "not_applicable_pair_set_hash": _require_hash(
                    payload["not_applicable_pair_set_hash"], "not_applicable_pair_set_hash"
                ),
                "required_bar_pair_count": _require_nonnegative_int(
                    payload["required_bar_pair_count"], "required_bar_pair_count"
                ),
                "required_bar_pair_set_hash": _require_hash(
                    payload["required_bar_pair_set_hash"], "required_bar_pair_set_hash"
                ),
                "returned_bar_pair_count": _require_nonnegative_int(
                    payload["returned_bar_pair_count"], "returned_bar_pair_count"
                ),
                "returned_bar_pair_set_hash": _require_hash(
                    payload["returned_bar_pair_set_hash"], "returned_bar_pair_set_hash"
                ),
                "returned_first_date": _optional_date(payload["returned_first_date"]),
                "returned_last_date": _optional_date(payload["returned_last_date"]),
                "returned_trading_day_count": _require_nonnegative_int(
                    payload["returned_trading_day_count"], "returned_trading_day_count"
                ),
                "returned_trading_days_hash": _require_hash(
                    payload["returned_trading_days_hash"], "returned_trading_days_hash"
                ),
                "returned_row_count": _require_nonnegative_int(
                    payload["returned_row_count"], "returned_row_count"
                ),
                "missing_required_pair_count": _require_nonnegative_int(
                    payload["missing_required_pair_count"], "missing_required_pair_count"
                ),
                "missing_required_pair_set_hash": _require_hash(
                    payload["missing_required_pair_set_hash"], "missing_required_pair_set_hash"
                ),
                "extra_returned_pair_count": _require_nonnegative_int(
                    payload["extra_returned_pair_count"], "extra_returned_pair_count"
                ),
                "extra_returned_pair_set_hash": _require_hash(
                    payload["extra_returned_pair_set_hash"], "extra_returned_pair_set_hash"
                ),
                "unresolved_pair_count": _require_nonnegative_int(
                    payload["unresolved_pair_count"], "unresolved_pair_count"
                ),
                "classification_counts": parsed_counts,
                "structural_error_codes": tuple(sorted(set(errors))),
            }
        except (TypeError, ValueError) as exc:
            raise MonthCompletenessError("month completeness evaluation is malformed") from exc
        result = cls(**cast(Any, values))
        if result.rule_version != AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION:
            raise MonthCompletenessError("unknown month completeness rule version")
        if result.applicability_semantics_version != AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION:
            raise MonthCompletenessError("unknown applicability semantics version")
        return result


def evaluate_month_completeness(
    *,
    monthly_symbols: Collection[str],
    trading_days: Collection[int],
    exact_day_universes: Mapping[int, Collection[str]],
    status_payload: Mapping[str, Any],
    daily_bar_payload: Mapping[str, Any],
) -> MonthCompletenessEvaluation:
    """Evaluate one month without converting absence into a semantic fact.

    ``exact_day_universes`` must contain one successful historical code-list
    observation for every calendar session.  Its set membership is the
    positive applicability fact.  ``status_payload`` must contain a validated
    status row for every applicable pair; ``IS_SUSP_SEC=1`` removes that pair
    from the required-bar set.  The daily-bar response is checked against the
    resulting set, including extra rows.
    """
    symbols, symbol_errors = _validate_symbols(monthly_symbols)
    sessions, session_errors = _validate_days(trading_days)
    structural_errors = list(symbol_errors) + list(session_errors)
    symbol_set = set(symbols)
    session_set = set(sessions)

    applicable: set[tuple[str, int]] = set()
    exact_universe_errors: list[str] = []
    if set(exact_day_universes) != session_set:
        exact_universe_errors.append("EXACT_DAY_UNIVERSE_KEYS_MISMATCH")
    for day in sessions:
        values = exact_day_universes.get(day)
        if values is None:
            continue
        day_symbols, errors = _validate_symbols(values)
        if errors:
            exact_universe_errors.extend(errors)
            continue
        day_set = set(day_symbols)
        if not day_set.issubset(symbol_set):
            exact_universe_errors.append("EXACT_DAY_UNIVERSE_OUTSIDE_MONTH_UNIVERSE")
        applicable.update((symbol, day) for symbol in day_set & symbol_set)
    structural_errors.extend(exact_universe_errors)

    status_by_pair: dict[tuple[str, int], int] = {}
    status_errors: list[str] = []
    if not isinstance(status_payload, Mapping) or set(status_payload) != symbol_set:
        status_errors.append("STATUS_RESPONSE_KEYS_MISMATCH")
    else:
        for symbol in symbols:
            frame = status_payload.get(symbol)
            if frame is None:
                status_errors.append("STATUS_NULL_TABLE")
                continue
            rows, errors = _status_rows(frame, session_set=session_set)
            status_errors.extend(errors)
            for day, flag in rows:
                status_by_pair[(symbol, day)] = flag
    structural_errors.extend(status_errors)

    status_pairs = set(status_by_pair)
    if status_pairs - applicable:
        structural_errors.append("STATUS_OUTSIDE_APPLICABILITY_SET")
    unresolved = applicable - status_pairs
    suspended = {pair for pair, flag in status_by_pair.items() if pair in applicable and flag == 1}
    required = {pair for pair, flag in status_by_pair.items() if pair in applicable and flag == 0}
    if suspended | required | unresolved != applicable:
        structural_errors.append("STATUS_APPLICABILITY_PARTITION_INCOMPLETE")

    returned, daily_errors = _daily_bar_pairs(
        daily_bar_payload,
        symbols=symbols,
        session_set=session_set,
        required_pairs=required,
    )
    structural_errors.extend(daily_errors)

    full_cross_product = {(symbol, day) for symbol in symbols for day in sessions}
    not_applicable = full_cross_product - applicable
    missing_required = required - returned
    extra_returned = returned - required

    classification_counts = {
        CompletenessPairClass.SUSPENSION_NON_TRADING.value: len(suspended),
        CompletenessPairClass.NOT_APPLICABLE_SESSION.value: len(not_applicable),
        CompletenessPairClass.PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH.value: len(structural_errors),
        CompletenessPairClass.UNEXPLAINED_MISSING.value: len(missing_required),
        CompletenessPairClass.UNRESOLVED.value: len(unresolved),
        CompletenessPairClass.EXTRA_RETURNED.value: len(extra_returned),
    }
    status = (
        "PASS"
        if not structural_errors and not unresolved and not missing_required and not extra_returned
        else "FAIL_CLOSED"
    )
    returned_days = {day for _symbol, day in returned}
    returned_dates = sorted(returned_days)
    return MonthCompletenessEvaluation(
        rule_version=AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION,
        applicability_semantics_version=AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION,
        status=status,
        monthly_security_count=len(symbols),
        session_count=len(sessions),
        monthly_security_set_hash=_hash_values(symbols),
        session_set_hash=_hash_values(sessions),
        applicable_pair_count=len(applicable),
        applicable_pair_set_hash=_hash_pairs(applicable),
        suspended_pair_count=len(suspended),
        suspended_pair_set_hash=_hash_pairs(suspended),
        not_applicable_pair_count=len(not_applicable),
        not_applicable_pair_set_hash=_hash_pairs(not_applicable),
        required_bar_pair_count=len(required),
        required_bar_pair_set_hash=_hash_pairs(required),
        returned_bar_pair_count=len(returned),
        returned_bar_pair_set_hash=_hash_pairs(returned),
        returned_first_date=_date_from_day(returned_dates[0]) if returned_dates else None,
        returned_last_date=_date_from_day(returned_dates[-1]) if returned_dates else None,
        returned_trading_day_count=len(returned_days),
        returned_trading_days_hash=_hash_values(returned_dates),
        returned_row_count=len(returned),
        missing_required_pair_count=len(missing_required),
        missing_required_pair_set_hash=_hash_pairs(missing_required),
        extra_returned_pair_count=len(extra_returned),
        extra_returned_pair_set_hash=_hash_pairs(extra_returned),
        unresolved_pair_count=len(unresolved),
        classification_counts=classification_counts,
        structural_error_codes=tuple(sorted(set(structural_errors))),
    )


def _validate_symbols(values: Collection[str]) -> tuple[list[str], list[str]]:
    if isinstance(values, (str, bytes)):
        return [], ["SYMBOL_COLLECTION_SHAPE_INVALID"]
    try:
        raw = list(values)
    except TypeError:
        return [], ["SYMBOL_COLLECTION_SHAPE_INVALID"]
    symbols: list[str] = []
    errors: list[str] = []
    for value in raw:
        if not isinstance(value, str) or _SYMBOL_PATTERN.fullmatch(value.strip()) is None:
            errors.append("SYMBOL_VALUE_INVALID")
            continue
        symbols.append(value.strip())
    if len(symbols) != len(set(symbols)):
        errors.append("SYMBOL_DUPLICATE")
    if not symbols:
        errors.append("SYMBOL_COLLECTION_EMPTY")
    return sorted(set(symbols)), errors


def _validate_days(values: Collection[int]) -> tuple[list[int], list[str]]:
    if isinstance(values, (str, bytes)):
        return [], ["SESSION_COLLECTION_SHAPE_INVALID"]
    try:
        raw = list(values)
    except TypeError:
        return [], ["SESSION_COLLECTION_SHAPE_INVALID"]
    days: list[int] = []
    errors: list[str] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or len(str(value)) != 8:
            errors.append("SESSION_VALUE_INVALID")
            continue
        try:
            date(value // 10000, (value // 100) % 100, value % 100)
        except ValueError:
            errors.append("SESSION_VALUE_INVALID")
            continue
        days.append(value)
    if len(days) != len(set(days)):
        errors.append("SESSION_DUPLICATE")
    if not days:
        errors.append("SESSION_COLLECTION_EMPTY")
    return sorted(set(days)), errors


def _status_rows(
    frame: Any,
    *,
    session_set: set[int],
) -> tuple[list[tuple[int, int]], list[str]]:
    columns = _frame_columns(frame)
    if columns != _STATUS_COLUMNS:
        return [], ["STATUS_SCHEMA_MISMATCH"]
    try:
        dates = _column_values(frame, "TRADE_DATE")
        flags = _column_values(frame, "IS_SUSP_SEC")
    except MonthCompletenessError:
        return [], ["STATUS_COLUMN_UNREADABLE"]
    if len(dates) != len(flags):
        return [], ["STATUS_ROW_SHAPE_INVALID"]
    if not dates:
        # An empty, schema-valid status table does not establish a lifecycle
        # fact.  It is harmless for a security that the exact-session
        # applicability observations exclude for the entire month; if it is
        # applicable, the unresolved-pair calculation below fails closed.
        return [], []
    rows: list[tuple[int, int]] = []
    errors: list[str] = []
    normalized_days: set[int] = set()
    for raw_day, raw_flag in zip(dates, flags, strict=True):
        day = _normalize_day(raw_day)
        flag = _normalize_flag(raw_flag)
        if day is None or day not in session_set:
            errors.append("STATUS_DATE_OUT_OF_SCOPE")
            continue
        if day in normalized_days:
            errors.append("STATUS_DUPLICATE_DATE")
            continue
        normalized_days.add(day)
        if flag is None:
            errors.append("STATUS_SUSPENSION_FLAG_INVALID")
            continue
        rows.append((day, flag))
    if "STATUS_DUPLICATE_DATE" in errors:
        # Do not let a contradictory or repeated provider row become an
        # order-dependent status fact.  The caller still receives the
        # structural error and fails closed, while no duplicate row is
        # allowed to populate ``status_by_pair``.
        return [], errors
    return rows, errors


def _daily_bar_pairs(
    payload: Mapping[str, Any],
    *,
    symbols: list[str],
    session_set: set[int],
    required_pairs: set[tuple[str, int]],
) -> tuple[set[tuple[str, int]], list[str]]:
    if not isinstance(payload, Mapping) or set(payload) != set(symbols):
        return set(), ["DAILY_RESPONSE_KEYS_MISMATCH"]
    pairs: set[tuple[str, int]] = set()
    errors: list[str] = []
    for symbol in symbols:
        frame = payload.get(symbol)
        if frame is None:
            # The reviewed SDK explicitly permits a null member in its
            # dict[str, dataframe|None] response.  It is an explicit zero-row
            # observation, not evidence that a security is inapplicable.  A
            # security that still has required pairs must nevertheless fail
            # closed as a provider/API shape problem; fully suspended or
            # otherwise non-required members may legitimately have no table.
            if any(pair[0] == symbol for pair in required_pairs):
                errors.append("DAILY_NULL_TABLE_FOR_REQUIRED_SECURITY")
            continue
        columns = _frame_columns(frame)
        if columns != _DAILY_COLUMNS:
            errors.append("DAILY_SCHEMA_MISMATCH")
            continue
        try:
            codes = _column_values(frame, "code")
            values = _column_values(frame, "kline_time")
            numeric = {
                name: _column_values(frame, name)
                for name in ("open", "high", "low", "close", "volume", "amount")
            }
        except MonthCompletenessError:
            errors.append("DAILY_COLUMN_UNREADABLE")
            continue
        if len(codes) != len(values):
            errors.append("DAILY_SECURITY_IDENTITY_INVALID")
            continue
        if not values:
            # A schema-valid empty table is a valid zero-row observation.  A
            # required pair remains missing below; an inapplicable security
            # may legitimately have no daily rows.
            continue
        if any(str(value).strip() != symbol for value in codes):
            errors.append("DAILY_SECURITY_IDENTITY_INVALID")
            continue
        if any(len(values) != len(column) for column in numeric.values()) or any(
            not _is_finite_number(value) for column in numeric.values() for value in column
        ):
            errors.append("DAILY_NUMERIC_VALUE_INVALID")
            continue
        dates: list[int] = []
        for raw_day in values:
            day = _normalize_day(raw_day)
            if day is None or day not in session_set:
                errors.append("DAILY_DATE_OUT_OF_SCOPE")
                continue
            dates.append(day)
        if len(dates) != len(set(dates)):
            errors.append("DAILY_DUPLICATE_DATE")
        pairs.update((symbol, day) for day in dates)
    return pairs, errors


def _frame_columns(frame: Any) -> frozenset[str]:
    columns = getattr(frame, "columns", None)
    if columns is None:
        return frozenset()
    return frozenset(str(column) for column in columns)


def _column_values(frame: Any, name: str) -> list[Any]:
    try:
        column = frame.get_column(name) if hasattr(frame, "get_column") else frame[name]
        if hasattr(column, "to_list"):
            values = column.to_list()
        elif hasattr(column, "tolist"):
            values = column.tolist()
        elif hasattr(column, "to_pylist"):
            values = column.to_pylist()
        else:
            values = list(column)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise MonthCompletenessError("provider table column is unreadable") from exc
    return list(values)


def _normalize_day(value: Any) -> int | None:
    if isinstance(value, datetime):
        return value.year * 10000 + value.month * 100 + value.day
    if isinstance(value, date):
        return value.year * 10000 + value.month * 100 + value.day
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and len(str(value)) == 8:
        return value
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit())
        if len(digits) >= 8:
            return int(digits[:8])
    return None


def _normalize_flag(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str) and value.strip() in {"0", "1"}:
        return int(value.strip())
    return None


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _hash_values(values: Collection[Any]) -> str:
    return _sha256_hex(_canonical_json(sorted(values)))


def _hash_pairs(values: Collection[tuple[str, int]]) -> str:
    return _sha256_hex(_canonical_json([[symbol, day] for symbol, day in sorted(values)]))


def _date_from_day(value: int) -> date:
    return date(value // 10000, (value // 100) % 100, value % 100)


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise MonthCompletenessError("optional date is malformed")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise MonthCompletenessError("optional date is malformed") from exc
    raise MonthCompletenessError("optional date is malformed")


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise MonthCompletenessError(f"{field_name} is malformed")
    return value


def _require_status(value: Any) -> str:
    status = _require_text(value, "status")
    if status not in {"PASS", "FAIL_CLOSED"}:
        raise MonthCompletenessError("status is not a recognized completeness state")
    return status


def _require_hash(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise MonthCompletenessError(f"{field_name} is not a sha256")
    return text


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MonthCompletenessError(f"{field_name} must be positive")
    return value


def _require_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MonthCompletenessError(f"{field_name} must be nonnegative")
    return value


def _canonical_json(value: Any) -> str:
    """Load the shared canonical serializer only after package initialization.

    ``ashare_state.research`` eagerly exposes historical contracts from its
    package initializer.  Importing that package at module import time here
    would therefore recurse through this provider module.  The semantic
    evaluator is imported safely first, and the shared serializer is resolved
    only when an evaluation is actually hashed.
    """
    from ashare_state.research.models import canonical_json

    return canonical_json(value)


def _sha256_hex(value: str) -> str:
    from ashare_state.research.models import sha256_hex

    return sha256_hex(value)
