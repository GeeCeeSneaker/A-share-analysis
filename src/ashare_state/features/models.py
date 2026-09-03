"""Deterministic CR-5 feature identities, findings, and result models."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

__all__ = [
    "FEATURE_CONTRACT_VERSION",
    "FEATURE_NAMESPACE",
    "FeatureBuildResult",
    "FeatureBuilderError",
    "FeatureFinding",
    "FeatureVerifierError",
    "VerifiedFeatureRun",
    "canonical_json",
    "feature_base_hash_from_primitives",
    "feature_id_from_base_hash",
    "lineage_hash",
    "semantic_hash",
]


FEATURE_CONTRACT_VERSION = "feature-v1"
FEATURE_NAMESPACE = uuid.UUID("f4a1c7d9-2e83-4b65-9a17-6c0d5e8f2b34")


class FeatureBuilderError(RuntimeError):
    """A feature run cannot be built without verified, deterministic inputs."""


class FeatureVerifierError(RuntimeError):
    """A feature artifact or its upstream provenance is not consumable."""


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime cannot enter deterministic JSON")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float cannot enter deterministic JSON")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values with explicit date/time handling."""
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def semantic_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash rows in their already-governed deterministic physical order."""
    return hashlib.sha256(
        canonical_json([dict(row) for row in rows]).encode("utf-8")
    ).hexdigest()


def lineage_hash(members: Sequence[Mapping[str, Any]]) -> str:
    """Hash the ordered set of actual upstream identities used by a row."""
    return hashlib.sha256(
        canonical_json([dict(member) for member in members]).encode("utf-8")
    ).hexdigest()


def feature_base_hash_from_primitives(
    *,
    snapshot_id: str,
    snapshot_manifest_hash: str,
    snapshot_semantic_hash: str,
    snapshot_as_of: str,
    readmodel_contract_version: str,
    readmodel_builder_code_fingerprint: str,
    feature_set_id: str,
    feature_set_version: str,
    feature_registry_version: str,
    feature_registry_hash: str,
    feature_contract_version: str,
    feature_builder_code_fingerprint: str,
) -> str:
    """Build the deterministic identity hash for one feature world."""
    payload = {
        "snapshot_id": snapshot_id,
        "snapshot_manifest_hash": snapshot_manifest_hash,
        "snapshot_semantic_hash": snapshot_semantic_hash,
        "snapshot_as_of": snapshot_as_of,
        "readmodel_contract_version": readmodel_contract_version,
        "readmodel_builder_code_fingerprint": readmodel_builder_code_fingerprint,
        "feature_set_id": feature_set_id,
        "feature_set_version": feature_set_version,
        "feature_registry_version": feature_registry_version,
        "feature_registry_hash": feature_registry_hash,
        "feature_contract_version": feature_contract_version,
        "feature_builder_code_fingerprint": feature_builder_code_fingerprint,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def feature_id_from_base_hash(feature_base_hash: str) -> str:
    """Derive a stable UUID5 feature_run_id from the identity hash."""
    return str(uuid.uuid5(FEATURE_NAMESPACE, feature_base_hash))


@dataclass(frozen=True)
class FeatureFinding:
    scope: str
    security_id: str | None
    trade_date: date
    feature_name: str
    finding_class: str
    detail_json: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "security_id": self.security_id,
            "trade_date": self.trade_date,
            "feature_name": self.feature_name,
            "finding_class": self.finding_class,
            "detail_json": self.detail_json,
        }


@dataclass(frozen=True)
class FeatureBuildResult:
    feature_run_id: str
    snapshot_id: str
    feature_set_id: str
    manifest_uri: str
    manifest_hash: str
    artifact_set_hash: str
    feature_semantic_hash: str
    finding_set_hash: str
    security_row_count: int
    market_row_count: int
    finding_count: int
    status: str
    idempotent_replay: bool


@dataclass(frozen=True)
class VerifiedFeatureRun:
    """Hash-verified feature truth and its upstream verified world."""

    feature_run_id: str
    snapshot_id: str
    canonical_run_id: str
    feature_set_id: str
    manifest: dict[str, Any]
    ledger_record: dict[str, Any]
    security_rows: tuple[dict[str, Any], ...]
    market_rows: tuple[dict[str, Any], ...]
    finding_rows: tuple[dict[str, Any], ...]
