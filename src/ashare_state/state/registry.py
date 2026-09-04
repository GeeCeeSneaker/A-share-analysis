"""CR-6 static State Registry and honest execution compiler."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from ashare_state.features.models import canonical_json
from ashare_state.state.schema import STATE_ENUM_VALUES

__all__ = [
    "STATE_CONTRACT_VERSION",
    "STATE_REGISTRY_VERSION",
    "STATE_SET_ID",
    "STATE_SET_VERSION",
    "SUPPORTED_STATE_NAMES",
    "StateExecutionPlan",
    "StateExecutionSpec",
    "StateHandler",
    "StateRegistryError",
    "StateSet",
    "StateSpec",
    "compile_state_execution_plan",
    "get_state_set",
]


STATE_SET_ID = "market-state-descriptive-v1"
STATE_SET_VERSION = "1"
STATE_REGISTRY_VERSION = "state-registry-v1"
STATE_CONTRACT_VERSION = "state-v1"

SUPPORTED_STATE_NAMES = (
    "return_center_state",
    "daily_participation_state",
    "trend_participation_state",
    "market_structure_state",
)


class StateRegistryError(ValueError):
    """The requested State set is unknown or not honestly executable."""


@dataclass(frozen=True)
class StateSpec:
    state_name: str
    output_enum: tuple[str, ...]
    required_feature_inputs: tuple[str, ...]
    rule_id: str
    threshold_policy: str
    missingness_policy: str
    availability_rule: str
    interpretation: str
    non_predictive_statement: str
    eligibility: Literal["SUPPORTED", "BLOCKED"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state_name": self.state_name,
            "output_enum": list(self.output_enum),
            "required_feature_inputs": list(self.required_feature_inputs),
            "rule_id": self.rule_id,
            "threshold_policy": self.threshold_policy,
            "missingness_policy": self.missingness_policy,
            "availability_rule": self.availability_rule,
            "interpretation": self.interpretation,
            "non_predictive_statement": self.non_predictive_statement,
            "eligibility": self.eligibility,
        }


@dataclass(frozen=True)
class StateSet:
    state_set_id: str
    state_set_version: str
    state_registry_version: str
    contract_version: str
    states: tuple[StateSpec, ...]

    @property
    def registry_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict()).encode("utf-8")).hexdigest()

    @property
    def state_names(self) -> tuple[str, ...]:
        return tuple(spec.state_name for spec in self.states)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state_set_id": self.state_set_id,
            "state_set_version": self.state_set_version,
            "state_registry_version": self.state_registry_version,
            "contract_version": self.contract_version,
            "states": [spec.as_dict() for spec in self.states],
        }


StateHandler = Literal[
    "return_center",
    "daily_participation",
    "trend_participation",
    "market_structure",
]


@dataclass(frozen=True)
class StateExecutionSpec:
    """One Registry declaration paired with exactly one typed handler."""

    spec: StateSpec
    handler: StateHandler


@dataclass(frozen=True)
class StateExecutionPlan:
    """Compiled declarations consumed by the single State engine."""

    state_set: StateSet
    entries: tuple[StateExecutionSpec, ...]

    @property
    def declarations(self) -> tuple[StateSpec, ...]:
        return tuple(entry.spec for entry in self.entries)

    def by_name(self, state_name: str) -> StateExecutionSpec:
        for entry in self.entries:
            if entry.spec.state_name == state_name:
                return entry
        raise StateRegistryError(f"state {state_name!r} is absent from the compiled execution plan")


_RETURN_CENTER = StateSpec(
    state_name="return_center_state",
    output_enum=STATE_ENUM_VALUES["return_center_state"],
    required_feature_inputs=("mean_raw_return_observed", "median_raw_return_observed"),
    rule_id="RETURN_CENTER_SIGN_CONSENSUS",
    threshold_policy="SIGN_WITH_ZERO_AS_MIXED",
    missingness_policy="NULL_TO_UNKNOWN_WITH_STATE_INPUT_NULL",
    availability_rule="SOURCE_FEATURE_ROW_AVAILABLE_AT",
    interpretation=(
        "Observed cross-sectional return center has a positive, negative, or " + "mixed sign."
    ),
    non_predictive_statement=(
        "This describes the observed Feature row and does not forecast a future " + "return."
    ),
    eligibility="SUPPORTED",
)

_DAILY_PARTICIPATION = StateSpec(
    state_name="daily_participation_state",
    output_enum=STATE_ENUM_VALUES["daily_participation_state"],
    required_feature_inputs=(
        "valid_raw_return_count",
        "advancer_count",
        "decliner_count",
        "unchanged_count",
    ),
    rule_id="DAILY_ADVANCE_DECLINE_DOMINANCE",
    threshold_policy="EXACT_COUNT_DOMINANCE",
    missingness_policy="NULL_TO_UNKNOWN_WITH_STATE_INPUT_NULL",
    availability_rule="SOURCE_FEATURE_ROW_AVAILABLE_AT",
    interpretation=(
        "Observed valid daily returns are dominated by advancing, declining, or " + "equal counts."
    ),
    non_predictive_statement=(
        "This describes participation in the observed universe and is not a " + "trading signal."
    ),
    eligibility="SUPPORTED",
)

_TREND_PARTICIPATION = StateSpec(
    state_name="trend_participation_state",
    output_enum=STATE_ENUM_VALUES["trend_participation_state"],
    required_feature_inputs=(
        "valid_ma20_count",
        "pct_above_ma20_observed",
        "valid_mom20_count",
        "pct_positive_mom20_observed",
    ),
    rule_id="TREND_PARTICIPATION_MAJORITY",
    threshold_policy="MAJORITY_AT_HALF_BOUNDARY",
    missingness_policy="NULL_OR_EMPTY_TO_UNKNOWN",
    availability_rule="SOURCE_FEATURE_ROW_AVAILABLE_AT",
    interpretation=(
        "Observed securities with comparable 20-observation "
        + "trend evidence are mostly positive, negative, or mixed."
    ),
    non_predictive_statement=(
        "This describes current observed trend participation "
        + "and is not a future-regime prediction."
    ),
    eligibility="SUPPORTED",
)

_MARKET_STRUCTURE = StateSpec(
    state_name="market_structure_state",
    output_enum=STATE_ENUM_VALUES["market_structure_state"],
    required_feature_inputs=(
        "return_center_state",
        "daily_participation_state",
        "trend_participation_state",
    ),
    rule_id="EXACT_STATE_COMPOSITION",
    threshold_policy="EXACT_ENUM_COMPOSITION",
    missingness_policy="UNKNOWN_DIMENSION_TO_UNKNOWN",
    availability_rule="MAX_CONSUMED_STATE_INPUT_AVAILABILITY",
    interpretation="The first three descriptive State dimensions are jointly aligned or mixed.",
    non_predictive_statement=(
        "This is an exact descriptive composition and does not predict price " + "direction."
    ),
    eligibility="SUPPORTED",
)

_CANONICAL_SPECS = (
    _RETURN_CENTER,
    _DAILY_PARTICIPATION,
    _TREND_PARTICIPATION,
    _MARKET_STRUCTURE,
)
_STATE_BY_NAME = {spec.state_name: spec for spec in _CANONICAL_SPECS}
_STATE_HANDLER_BY_RULE: dict[str, StateHandler] = {
    "RETURN_CENTER_SIGN_CONSENSUS": "return_center",
    "DAILY_ADVANCE_DECLINE_DOMINANCE": "daily_participation",
    "TREND_PARTICIPATION_MAJORITY": "trend_participation",
    "EXACT_STATE_COMPOSITION": "market_structure",
}
_STATE_SET = StateSet(
    state_set_id=STATE_SET_ID,
    state_set_version=STATE_SET_VERSION,
    state_registry_version=STATE_REGISTRY_VERSION,
    contract_version=STATE_CONTRACT_VERSION,
    states=_CANONICAL_SPECS,
)


def compile_state_execution_plan(state_set: StateSet) -> StateExecutionPlan:
    """Validate every Registry field before any State value is computed."""
    if not isinstance(state_set, StateSet):
        raise StateRegistryError("State execution plan requires a StateSet")
    if (
        state_set.state_set_id != STATE_SET_ID
        or state_set.state_set_version != STATE_SET_VERSION
        or state_set.state_registry_version != STATE_REGISTRY_VERSION
        or state_set.contract_version != STATE_CONTRACT_VERSION
    ):
        raise StateRegistryError("State set metadata is not the CR-6 V1 contract")
    if tuple(state_set.state_names) != SUPPORTED_STATE_NAMES:
        raise StateRegistryError("State set names/order are not the exact V1 set")
    if len(state_set.states) != len(_CANONICAL_SPECS):
        raise StateRegistryError("State set has duplicate, missing, or extra declarations")
    if len(set(state_set.state_names)) != len(state_set.states):
        raise StateRegistryError("State set has duplicate declarations")

    entries: list[StateExecutionSpec] = []
    for spec in state_set.states:
        canonical = _STATE_BY_NAME.get(spec.state_name)
        if canonical is None:
            raise StateRegistryError(
                f"state {spec.state_name!r} is not declared by the V1 Registry"
            )
        if spec != canonical:
            raise StateRegistryError(
                f"state {spec.state_name!r} declaration is not honestly supported"
            )
        handler = _STATE_HANDLER_BY_RULE.get(spec.rule_id)
        if handler is None:
            raise StateRegistryError(f"state {spec.state_name!r} has no typed execution handler")
        entries.append(StateExecutionSpec(spec=spec, handler=handler))

    if tuple(entry.spec.state_name for entry in entries) != SUPPORTED_STATE_NAMES:
        raise StateRegistryError("compiled State plan does not cover exact V1 names/order")
    if len({entry.handler for entry in entries}) != len(entries):
        raise StateRegistryError("each supported State declaration must have one handler")
    return StateExecutionPlan(state_set=state_set, entries=tuple(entries))


def get_state_set(state_set_id: str) -> StateSet:
    """Return the one statically registered V1 State set or fail closed."""
    if state_set_id != STATE_SET_ID:
        raise StateRegistryError(
            f"state_set_id {state_set_id!r} is not registered; "
            "caller-defined State rules are forbidden"
        )
    return _STATE_SET
