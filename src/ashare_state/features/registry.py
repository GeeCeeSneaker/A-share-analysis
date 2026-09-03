"""Static CR-5 Feature Registry.

The registry is the only source of V1 feature names, formulas, windows,
missingness rules, and availability rules. Callers cannot inject any of
those parameters.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ashare_state.features.models import canonical_json

__all__ = [
    "BLOCKED_FEATURE_SEMANTICS",
    "FEATURE_REGISTRY_VERSION",
    "FEATURE_SET_ID",
    "FeatureRegistryError",
    "FeatureSet",
    "FeatureSpec",
    "get_feature_set",
]


FEATURE_SET_ID = "market-state-base-v1"
FEATURE_SET_VERSION = "1"
FEATURE_REGISTRY_VERSION = "feature-registry-v1"
PRICE_BASIS = "UNADJUSTED_CANONICAL"
WINDOW_BASIS = "OBSERVED_SECURITY_BARS"
UNIVERSE_RULE_ID = "OBSERVED_DAILY_BAR_UNIVERSE"

BLOCKED_FEATURE_SEMANTICS = (
    "adjusted OHLC",
    "adjusted return",
    "total return",
    "corporate-action neutralized return",
    "strict market-session window",
    "ALL_A_SHARES denominator",
    "board/ST/tick-size limit hit",
    "near-limit tolerance classification",
    "industry breadth",
    "index-relative alpha/beta",
    "ungoverned cross-sectional z-score",
    "strategy signal/score/rank",
)


class FeatureRegistryError(ValueError):
    """The requested feature set is unknown or semantically unsupported."""


@dataclass(frozen=True)
class FeatureSpec:
    feature_name: str
    output_dtype: str
    required_inputs: tuple[str, ...]
    window_basis: str | None
    window_length: int | None
    lag: int | None
    formula_rule_id: str
    denominator_policy: str
    missingness_policy: str
    availability_rule: str
    eligibility: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "output_dtype": self.output_dtype,
            "required_inputs": list(self.required_inputs),
            "window_basis": self.window_basis,
            "window_length": self.window_length,
            "lag": self.lag,
            "formula_rule_id": self.formula_rule_id,
            "denominator_policy": self.denominator_policy,
            "missingness_policy": self.missingness_policy,
            "availability_rule": self.availability_rule,
            "eligibility": self.eligibility,
        }


@dataclass(frozen=True)
class FeatureSet:
    feature_set_id: str
    feature_set_version: str
    feature_registry_version: str
    price_basis: str
    universe_rule_id: str
    features: tuple[FeatureSpec, ...]
    blocked_semantics: tuple[str, ...]

    @property
    def registry_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict()).encode("utf-8")).hexdigest()

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(spec.feature_name for spec in self.features)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature_set_id": self.feature_set_id,
            "feature_set_version": self.feature_set_version,
            "feature_registry_version": self.feature_registry_version,
            "price_basis": self.price_basis,
            "universe_rule_id": self.universe_rule_id,
            "features": [spec.as_dict() for spec in self.features],
            "blocked_semantics": list(self.blocked_semantics),
        }


def _spec(
    name: str,
    inputs: tuple[str, ...],
    *,
    window_length: int | None = None,
    lag: int | None = None,
    rule: str,
    window_basis: str | None = None,
    denominator: str = "NON_NULL_AND_GREATER_THAN_ZERO",
    availability: str = "MAX_ACTUAL_INPUT_AVAILABLE_AT",
    output_dtype: str = "float64",
) -> FeatureSpec:
    return FeatureSpec(
        feature_name=name,
        output_dtype=output_dtype,
        required_inputs=inputs,
        window_basis=window_basis,
        window_length=window_length,
        lag=lag,
        formula_rule_id=rule,
        denominator_policy=denominator,
        missingness_policy="NULL_WITH_TYPED_FINDING_NO_FILL_OR_DROP",
        availability_rule=availability,
        eligibility="SUPPORTED",
    )


_FEATURES: tuple[FeatureSpec, ...] = (
    _spec(
        "raw_return_1",
        ("close", "pre_close"),
        rule="RAW_RETURN_1",
    ),
    _spec(
        "gap_open_raw",
        ("open", "pre_close"),
        rule="GAP_OPEN_RAW",
    ),
    _spec(
        "intraday_return_raw",
        ("close", "open"),
        rule="INTRADAY_RETURN_RAW",
    ),
    _spec(
        "amplitude_preclose_raw",
        ("high", "low", "pre_close"),
        rule="AMPLITUDE_PRECLOSE_RAW",
    ),
    _spec(
        "ma_close_obs_5",
        ("close",),
        window_length=5,
        rule="MEAN_ORDERED_OBSERVED_CLOSE",
        window_basis=WINDOW_BASIS,
        denominator="EXACT_N_OBSERVED_BARS",
    ),
    _spec(
        "ma_close_obs_20",
        ("close",),
        window_length=20,
        rule="MEAN_ORDERED_OBSERVED_CLOSE",
        window_basis=WINDOW_BASIS,
        denominator="EXACT_N_OBSERVED_BARS",
    ),
    _spec(
        "ma_close_obs_60",
        ("close",),
        window_length=60,
        rule="MEAN_ORDERED_OBSERVED_CLOSE",
        window_basis=WINDOW_BASIS,
        denominator="EXACT_N_OBSERVED_BARS",
    ),
    _spec(
        "close_to_ma_obs_5",
        ("close", "ma_close_obs_5"),
        window_length=5,
        rule="CLOSE_TO_MEAN",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "close_to_ma_obs_20",
        ("close", "ma_close_obs_20"),
        window_length=20,
        rule="CLOSE_TO_MEAN",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "close_to_ma_obs_60",
        ("close", "ma_close_obs_60"),
        window_length=60,
        rule="CLOSE_TO_MEAN",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "return_lag_obs_5",
        ("close",),
        lag=5,
        rule="RETURN_FROM_N_PRIOR_OBSERVED_CLOSE",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "return_lag_obs_20",
        ("close",),
        lag=20,
        rule="RETURN_FROM_N_PRIOR_OBSERVED_CLOSE",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "return_lag_obs_60",
        ("close",),
        lag=60,
        rule="RETURN_FROM_N_PRIOR_OBSERVED_CLOSE",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "amount_to_mean_obs_20",
        ("amount",),
        window_length=20,
        rule="CURRENT_AMOUNT_OVER_LAST_20_VALID_AMOUNT_MEAN",
        window_basis=WINDOW_BASIS,
    ),
    _spec(
        "vol_raw_return_obs_20",
        ("raw_return_1",),
        window_length=20,
        rule="POPULATION_STDDEV_LAST_20_VALID_RAW_RETURN",
        window_basis=WINDOW_BASIS,
        denominator="EXACT_N_VALID_RAW_RETURNS",
    ),
)

_MARKET_FEATURES: tuple[FeatureSpec, ...] = (
    _spec(
        "observed_security_count",
        ("daily_bar",),
        rule="COUNT_OBSERVED_DAILY_BAR_UNIVERSE",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "valid_raw_return_count",
        ("raw_return_1",),
        rule="COUNT_VALID_RAW_RETURN",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "advancer_count",
        ("raw_return_1",),
        rule="COUNT_RAW_RETURN_GREATER_THAN_ZERO",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "decliner_count",
        ("raw_return_1",),
        rule="COUNT_RAW_RETURN_LESS_THAN_ZERO",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "unchanged_count",
        ("raw_return_1",),
        rule="COUNT_RAW_RETURN_EQUAL_ZERO",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "advancer_ratio_observed",
        ("raw_return_1",),
        rule="ADVANCER_COUNT_OVER_VALID_RAW_RETURN_COUNT",
        denominator="VALID_RAW_RETURN_COUNT_GREATER_THAN_ZERO",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
    ),
    _spec(
        "mean_raw_return_observed",
        ("raw_return_1",),
        rule="ORDERED_MEAN_VALID_RAW_RETURN",
        denominator="EXACT_VALID_RAW_RETURN_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
    ),
    _spec(
        "median_raw_return_observed",
        ("raw_return_1",),
        rule="ORDERED_MEDIAN_VALID_RAW_RETURN",
        denominator="EXACT_VALID_RAW_RETURN_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
    ),
    _spec(
        "valid_ma20_count",
        ("ma_close_obs_20",),
        rule="COUNT_VALID_MA_CLOSE_OBS_20",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "pct_above_ma20_observed",
        ("close_to_ma_obs_20",),
        rule="COUNT_ABOVE_MA20_OVER_VALID_MA20_COUNT",
        denominator="VALID_MA20_COUNT_GREATER_THAN_ZERO",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
    ),
    _spec(
        "valid_mom20_count",
        ("return_lag_obs_20",),
        rule="COUNT_VALID_RETURN_LAG_OBS_20",
        denominator="NOT_APPLICABLE_COUNT",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
        output_dtype="int64",
    ),
    _spec(
        "pct_positive_mom20_observed",
        ("return_lag_obs_20",),
        rule="COUNT_POSITIVE_MOM20_OVER_VALID_MOM20_COUNT",
        denominator="VALID_MOM20_COUNT_GREATER_THAN_ZERO",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
    ),
    _spec(
        "total_amount_observed",
        ("amount",),
        rule="ORDERED_SUM_OBSERVED_AMOUNT",
        denominator="NOT_APPLICABLE_SUM",
        availability="MAX_PARTICIPATING_SECURITY_AVAILABLE_AT",
    ),
)

_FEATURE_SET = FeatureSet(
    feature_set_id=FEATURE_SET_ID,
    feature_set_version=FEATURE_SET_VERSION,
    feature_registry_version=FEATURE_REGISTRY_VERSION,
    price_basis=PRICE_BASIS,
    universe_rule_id=UNIVERSE_RULE_ID,
    features=(*_FEATURES, *_MARKET_FEATURES),
    blocked_semantics=BLOCKED_FEATURE_SEMANTICS,
)

_FEATURE_SETS = {FEATURE_SET_ID: _FEATURE_SET}


def get_feature_set(feature_set_id: str) -> FeatureSet:
    """Return one statically declared feature set or fail closed."""
    feature_set = _FEATURE_SETS.get(feature_set_id)
    if feature_set is None:
        raise FeatureRegistryError(
            f"feature_set_id {feature_set_id!r} is not registered; "
            "caller-defined formulas and windows are forbidden"
        )
    return feature_set
