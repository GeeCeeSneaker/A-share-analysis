"""CR-4.2 snapshot result models + identity derivation."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ashare_state.canonical.canonicalizer import _canonical_json

__all__ = [
    "SNAPSHOT_NAMESPACE",
    "SnapshotBuildResult",
    "SnapshotBuilderError",
    "VerifiedSnapshot",
    "SnapshotVerifierError",
    "snapshot_base_hash_from_primitives",
    "snapshot_id_from_base_hash",
]


#: CR-4 snapshot run-id namespace (fixed, versioned with the contract).
SNAPSHOT_NAMESPACE = uuid.UUID("e9f5a3b7-2c4d-4e6f-8a1b-3c5d7e9f1a23")


class SnapshotBuilderError(Exception):
    """The snapshot cannot be built from the verified canonical truth:
    duplicate identity, unexpected domain, non-empty table expected,
    immutable-target violation or ledger inconsistency. Fail closed."""


class SnapshotVerifierError(Exception):
    """A snapshot ledger row / manifest / artifact cannot be verified.
    Fail closed - no partial truth escapes to the ReadModel."""


@dataclass(frozen=True)
class SnapshotBuildResult:
    snapshot_id: str
    canonical_run_id: str
    manifest_uri: str
    manifest_hash: str
    artifact_set_hash: str
    snapshot_semantic_hash: str
    row_count_total: int
    status: str
    idempotent_replay: bool


@dataclass(frozen=True)
class VerifiedSnapshot:
    """The verified snapshot truth the DuckDB ReadModel consumes."""

    snapshot_id: str
    canonical_run_id: str
    as_of: datetime
    requested_domains: tuple[str, ...]
    ledger_record: dict[str, Any]
    manifest: dict[str, Any]
    domain_rows: dict[str, tuple[dict[str, Any], ...]]


def snapshot_base_hash_from_primitives(
    *,
    canonical_run_id: str,
    canonical_manifest_hash: str,
    canonical_requested_domains_hash: str,
    canonical_selected_semantic_hash: str,
    canonical_as_of: str,
    snapshot_contract_version: str,
    snapshot_builder_code_fingerprint: str,
) -> str:
    """P0-A04: the snapshot base identity hash - a canonical JSON over
    the canonical run id + canonical manifest hash + canonical
    requested domains hash + canonical selected semantic hash +
    canonical as_of + the snapshot contract version + the snapshot
    builder code fingerprint. Deliberately derived from the canonical
    RUN-LEVEL seals (not from the projected rows) so the identity is
    computable BEFORE any artifact is written and verifiable from the
    manifest primitives afterwards."""
    return hashlib.sha256(
        _canonical_json(
            {
                "canonical_run_id": canonical_run_id,
                "canonical_manifest_hash": canonical_manifest_hash,
                "canonical_requested_domains_hash": canonical_requested_domains_hash,
                "canonical_selected_semantic_hash": canonical_selected_semantic_hash,
                "canonical_as_of": canonical_as_of,
                "snapshot_contract_version": snapshot_contract_version,
                "snapshot_builder_code_fingerprint": snapshot_builder_code_fingerprint,
            }
        ).encode("utf-8")
    ).hexdigest()


def snapshot_id_from_base_hash(snapshot_base_hash: str) -> str:
    """P0-A04: snapshot_id = UUID5(SNAPSHOT_NAMESPACE, base hash)."""
    return str(uuid.uuid5(SNAPSHOT_NAMESPACE, snapshot_base_hash))
