"""CR-6 static State Registry skeleton.

CR-6.0 defines the typed declaration surface. The four supported V1
declarations and their handlers are completed in CR-6.1 after ADR-026
review; this module deliberately contains no interpretation logic yet.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from ashare_state.features.models import canonical_json

__all__ = [
    "STATE_CONTRACT_VERSION",
    "STATE_REGISTRY_VERSION",
    "STATE_SET_ID",
    "STATE_SET_VERSION",
    "SUPPORTED_STATE_NAMES",
    "StateExecutionPlan",
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
    """The requested State set is unknown or not yet executable."""


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


@dataclass(frozen=True)
class StateExecutionPlan:
    """Typed declaration container; handler binding is a CR-6.1 concern."""

    state_set: StateSet
    declarations: tuple[StateSpec, ...]


def compile_state_execution_plan(state_set: StateSet) -> StateExecutionPlan:
    """Validate the type boundary before CR-6.1 runtime execution exists."""
    if not isinstance(state_set, StateSet):
        raise StateRegistryError("State execution plan requires a StateSet")
    if (
        state_set.state_set_id != STATE_SET_ID
        or state_set.state_set_version != STATE_SET_VERSION
        or state_set.state_registry_version != STATE_REGISTRY_VERSION
        or state_set.contract_version != STATE_CONTRACT_VERSION
    ):
        raise StateRegistryError("State set metadata is not the CR-6 V1 contract")
    return StateExecutionPlan(state_set=state_set, declarations=state_set.states)


def get_state_set(state_set_id: str) -> StateSet:
    """Return a registered State set once CR-6.1 installs its declarations."""
    raise StateRegistryError(
        f"state_set_id {state_set_id!r} is not executable in CR-6.0; "
        "the CR-6.1 registry is required"
    )
