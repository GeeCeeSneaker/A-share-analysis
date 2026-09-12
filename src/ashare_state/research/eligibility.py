"""Machine-readable row-level eligibility and exclusion decisions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ashare_state.research.models import (
    DataQualityState,
    ExclusionReason,
    IdentityRecord,
    ResearchEligibility,
    ResearchSplit,
)

__all__ = ["EligibilityDecision", "evaluate_daily_bar"]


_REQUIRED_VALUE_FIELDS = ("open", "high", "low", "close", "volume", "amount")
_PRICE_FIELDS = ("open", "high", "low", "close")
_NON_NEGATIVE_FIELDS = ("open", "high", "low", "close", "pre_close", "volume", "amount")


@dataclass(frozen=True)
class EligibilityDecision:
    eligibility: ResearchEligibility
    exclusion_reason: ExclusionReason | None
    data_quality_state: DataQualityState

    @property
    def enabled(self) -> bool:
        return self.eligibility is ResearchEligibility.ENABLED


def _disabled(
    reason: ExclusionReason,
    *,
    invalid: bool = False,
) -> EligibilityDecision:
    return EligibilityDecision(
        eligibility=ResearchEligibility.DISABLED_UNRESOLVED,
        exclusion_reason=reason,
        data_quality_state=(DataQualityState.INVALID if invalid else DataQualityState.UNRESOLVED),
    )


def evaluate_daily_bar(
    row: Mapping[str, Any],
    *,
    split: ResearchSplit,
    identity: IdentityRecord | None,
    identity_conflict: bool = False,
) -> EligibilityDecision:
    """Classify one typed daily-bar row without filling or rewriting values."""
    if split not in {
        ResearchSplit.DEVELOPMENT,
        ResearchSplit.VALIDATION_A,
        ResearchSplit.HOLDOUT,
    }:
        return _disabled(ExclusionReason.OUTSIDE_RESEARCH_WINDOW)

    raw_status = row.get("research_eligibility")
    if raw_status is not None and str(raw_status) == ResearchEligibility.EXPERIMENTAL.value:
        return EligibilityDecision(
            eligibility=ResearchEligibility.EXPERIMENTAL,
            exclusion_reason=ExclusionReason.UPSTREAM_UNRESOLVED,
            data_quality_state=DataQualityState.UNRESOLVED,
        )
    if raw_status is not None and str(raw_status) != ResearchEligibility.ENABLED.value:
        return _disabled(ExclusionReason.UPSTREAM_UNRESOLVED)
    if identity_conflict:
        return _disabled(ExclusionReason.IDENTITY_CONFLICT)
    if identity is None:
        return _disabled(ExclusionReason.IDENTITY_UNRESOLVED)

    if any(row.get(field) is None for field in _REQUIRED_VALUE_FIELDS):
        return _disabled(ExclusionReason.MISSING_REQUIRED_VALUE)

    values: dict[str, float] = {}
    for field in _NON_NEGATIVE_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            return _disabled(ExclusionReason.INVALID_OHLC, invalid=True)
        numeric = float(value)
        if not math.isfinite(numeric):
            return _disabled(ExclusionReason.NON_FINITE_VALUE, invalid=True)
        if numeric < 0:
            return _disabled(ExclusionReason.INVALID_OHLC, invalid=True)
        values[field] = numeric

    if any(field not in values for field in _PRICE_FIELDS):
        return _disabled(ExclusionReason.INVALID_OHLC, invalid=True)
    if (
        values["high"] < max(values["open"], values["close"])
        or values["low"] > min(values["open"], values["close"])
        or values["low"] > values["high"]
    ):
        return _disabled(ExclusionReason.INVALID_OHLC, invalid=True)

    return EligibilityDecision(
        eligibility=ResearchEligibility.ENABLED,
        exclusion_reason=None,
        data_quality_state=DataQualityState.VERIFIED,
    )
