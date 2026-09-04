"""CR-6 deterministic State identities, findings, and result models."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ashare_state.features.models import canonical_json, semantic_hash

__all__ = [
    "STATE_CONTRACT_VERSION",
    "STATE_NAMESPACE",
    "StateBuildResult",
    "StateBuilderError",
    "StateFinding",
    "StateVerifierError",
    "VerifiedStateRun",
    "canonical_json",
    "semantic_hash",
    "state_base_hash_from_primitives",
    "state_id_from_base_hash",
    "state_input_lineage_hash",
]


STATE_CONTRACT_VERSION = "state-v1"
STATE_NAMESPACE = uuid.UUID("7e1bd3a4-6d5f-4f81-9be3-1c42f5a7d9e8")


class StateBuilderError(RuntimeError):
    """A State run cannot be built from an unverified Feature world."""


class StateVerifierError(RuntimeError):
    """A State artifact or its upstream provenance is not consumable."""


def state_base_hash_from_primitives(
    *,
    feature_run_id: str,
    feature_manifest_hash: str,
    feature_semantic_hash: str,
    feature_set_id: str,
    feature_registry_hash: str,
    state_set_id: str,
    state_set_version: str,
    state_registry_version: str,
    state_registry_hash: str,
    state_contract_version: str,
    state_builder_code_fingerprint: str,
) -> str:
    """Build the deterministic identity hash for one State world."""
    payload = {
        "feature_run_id": feature_run_id,
        "feature_manifest_hash": feature_manifest_hash,
        "feature_semantic_hash": feature_semantic_hash,
        "feature_set_id": feature_set_id,
        "feature_registry_hash": feature_registry_hash,
        "state_set_id": state_set_id,
        "state_set_version": state_set_version,
        "state_registry_version": state_registry_version,
        "state_registry_hash": state_registry_hash,
        "state_contract_version": state_contract_version,
        "state_builder_code_fingerprint": state_builder_code_fingerprint,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def state_id_from_base_hash(state_base_hash: str) -> str:
    """Derive a stable UUID5 state_run_id from the identity hash."""
    return str(uuid.uuid5(STATE_NAMESPACE, state_base_hash))


def state_input_lineage_hash(
    *,
    source_feature_run_id: str,
    trade_date: date,
    source_feature_input_lineage_hash: str,
    source_feature_available_at: Any,
    evidence: Mapping[str, Any],
    state_registry_version: str,
    state_registry_hash: str,
    state_rule_ids: Sequence[str],
) -> str:
    """Hash exact State inputs without adding wall-clock correctness metadata."""
    payload = {
        "source_feature_run_id": source_feature_run_id,
        "trade_date": trade_date,
        "source_feature_input_lineage_hash": source_feature_input_lineage_hash,
        "source_feature_available_at": source_feature_available_at,
        "evidence": dict(evidence),
        "state_registry_version": state_registry_version,
        "state_registry_hash": state_registry_hash,
        "state_rule_ids": list(state_rule_ids),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StateFinding:
    trade_date: date
    state_name: str
    finding_class: str
    detail_json: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "state_name": self.state_name,
            "finding_class": self.finding_class,
            "detail_json": self.detail_json,
        }


@dataclass(frozen=True)
class StateBuildResult:
    state_run_id: str
    feature_run_id: str
    state_set_id: str
    manifest_uri: str
    manifest_hash: str
    artifact_set_hash: str
    state_semantic_hash: str
    finding_set_hash: str
    state_row_count: int
    finding_count: int
    status: str
    idempotent_replay: bool


@dataclass(frozen=True)
class VerifiedStateRun:
    """Hash-verified State truth and its upstream verified Feature world."""

    state_run_id: str
    feature_run_id: str
    state_set_id: str
    manifest: dict[str, Any]
    ledger_record: dict[str, Any]
    state_rows: tuple[dict[str, Any], ...]
    finding_rows: tuple[dict[str, Any], ...]
