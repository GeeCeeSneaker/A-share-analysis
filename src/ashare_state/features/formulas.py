"""Pure deterministic numeric rules for CR-5 V1."""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "amplitude_preclose_raw",
    "gap_open_raw",
    "amount_to_mean",
    "close_to_mean",
    "intraday_return_raw",
    "lag_return",
    "ordered_mean",
    "ordered_median",
    "ordered_population_std",
    "raw_return_1",
    "safe_ratio",
]


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def safe_ratio(numerator: float, denominator: float) -> float | None:
    """Return a finite ratio only for a positive finite denominator."""
    if not _finite(numerator) or not _finite(denominator) or denominator <= 0:
        return None
    result = numerator / denominator
    return result if _finite(result) else None


def raw_return_1(close: float, pre_close: float) -> float | None:
    ratio = safe_ratio(close, pre_close)
    return None if ratio is None else ratio - 1.0


def gap_open_raw(open_price: float, pre_close: float) -> float | None:
    ratio = safe_ratio(open_price, pre_close)
    return None if ratio is None else ratio - 1.0


def intraday_return_raw(close: float, open_price: float) -> float | None:
    ratio = safe_ratio(close, open_price)
    return None if ratio is None else ratio - 1.0


def amplitude_preclose_raw(high: float, low: float, pre_close: float) -> float | None:
    if not _finite(high) or not _finite(low):
        return None
    return safe_ratio(high - low, pre_close)


def ordered_mean(values: Sequence[float]) -> float | None:
    if not values or any(not _finite(value) for value in values):
        return None
    result = math.fsum(values) / len(values)
    return result if _finite(result) else None


def ordered_median(values: Sequence[float]) -> float | None:
    if not values or any(not _finite(value) for value in values):
        return None
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        result = ordered[middle]
    else:
        result = (ordered[middle - 1] + ordered[middle]) / 2.0
    return result if _finite(result) else None


def ordered_population_std(values: Sequence[float]) -> float | None:
    if not values or any(not _finite(value) for value in values):
        return None
    mean = math.fsum(values) / len(values)
    variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
    result = math.sqrt(variance)
    return result if _finite(result) else None


def close_to_mean(close: float, mean: float) -> float | None:
    ratio = safe_ratio(close, mean)
    return None if ratio is None else ratio - 1.0


def lag_return(current_close: float, prior_close: float) -> float | None:
    ratio = safe_ratio(current_close, prior_close)
    return None if ratio is None else ratio - 1.0


def amount_to_mean(current_amount: float, mean_amount: float) -> float | None:
    return safe_ratio(current_amount, mean_amount)
