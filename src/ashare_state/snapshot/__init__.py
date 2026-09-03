"""CR-4.2: the governed snapshot layer.

SnapshotBuilder builds domain-partitioned point-in-time snapshots from
VERIFIED canonical SUCCESS runs (the CR-4.1 public consumption
verifier is the ONLY canonical input); verify_snapshot is the ONLY
supported read path for downstream construction. No providers, no
Raw access, no CR-2 re-implementation, no feature computation.
"""

from ashare_state.snapshot.builder import (
    SNAPSHOT_LEDGER_COLUMNS,
    SnapshotBuilder,
    snapshot_base_dir,
    snapshot_builder_code_fingerprint,
    snapshot_manifest_uri,
)
from ashare_state.snapshot.models import (
    SNAPSHOT_NAMESPACE,
    SnapshotBuilderError,
    SnapshotBuildResult,
    SnapshotVerifierError,
    VerifiedSnapshot,
    snapshot_base_hash_from_primitives,
    snapshot_id_from_base_hash,
)
from ashare_state.snapshot.schema import (
    SNAPSHOT_CONTRACT_VERSION,
    ColumnSpec,
    DomainSnapshotSchema,
    DType,
    SnapshotSchemaError,
    domain_snapshot_schema,
    polars_domain_schema,
    project_selected_row,
    snapshot_domains,
    validate_canonical_key,
)
from ashare_state.snapshot.verifier import verify_snapshot

__all__ = [
    "ColumnSpec",
    "DomainSnapshotSchema",
    "DType",
    "SNAPSHOT_CONTRACT_VERSION",
    "SNAPSHOT_LEDGER_COLUMNS",
    "SNAPSHOT_NAMESPACE",
    "SnapshotBuildResult",
    "SnapshotBuilder",
    "SnapshotBuilderError",
    "SnapshotSchemaError",
    "SnapshotVerifierError",
    "VerifiedSnapshot",
    "domain_snapshot_schema",
    "polars_domain_schema",
    "project_selected_row",
    "snapshot_base_dir",
    "snapshot_base_hash_from_primitives",
    "snapshot_builder_code_fingerprint",
    "snapshot_domains",
    "snapshot_id_from_base_hash",
    "snapshot_manifest_uri",
    "validate_canonical_key",
    "verify_snapshot",
]
