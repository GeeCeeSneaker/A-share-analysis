"""Narrow CR-7 adapter for sealed authoritative coverage evidence.

This module has no SDK, Provider, network, or credential dependency.  It only
turns an already retained upstream inventory/range statement and its typed
PIT metadata into the existing ``CoverageBasisDescriptor``.  Missing or
unverifiable source evidence is intentionally not representable as an
authoritative descriptor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ashare_state.research.historical import (
    AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD,
    COMPLETE_OBSERVED_DAILY_BAR_SCOPE,
    COVERAGE_BASIS_VERSION,
    AuthoritativeCoverageEvidence,
    AuthoritativeSourceSelection,
    CoverageBasisDescriptor,
    CoverageBasisError,
    PartitionKey,
)
from ashare_state.research.models import canonical_json, ensure_utc_timestamp, sha256_hex

__all__ = [
    "AuthoritativeCoverageBasisAdapter",
    "build_authoritative_coverage_basis_descriptor",
]


@dataclass(frozen=True)
class AuthoritativeCoverageBasisAdapter:
    """Bind one reviewed source-selection identity to coverage evidence."""

    source_selection: AuthoritativeSourceSelection

    def __post_init__(self) -> None:
        if self.source_selection != AuthoritativeSourceSelection.reviewed_amazingdata_history():
            raise CoverageBasisError(
                "authoritative adapter received an unreviewed source-selection binding"
            )

    @classmethod
    def reviewed_amazingdata_history(cls) -> AuthoritativeCoverageBasisAdapter:
        """Return the only authoritative adapter enabled in this release."""
        return cls(AuthoritativeSourceSelection.reviewed_amazingdata_history())

    def build_descriptor(
        self,
        partition: PartitionKey,
        evidence: AuthoritativeCoverageEvidence,
    ) -> CoverageBasisDescriptor:
        """Emit the existing descriptor only after exact evidence binding."""
        if not isinstance(evidence, AuthoritativeCoverageEvidence):
            raise CoverageBasisError("authoritative adapter requires typed coverage evidence")
        if evidence.source_selection != self.source_selection:
            raise CoverageBasisError("authoritative evidence source-selection fingerprint changed")
        if evidence.source_selection_fingerprint != self.source_selection.selection_fingerprint:
            raise CoverageBasisError("authoritative evidence source-selection fingerprint is wrong")
        if (
            evidence.claimed_scope_start != partition.scope_start
            or evidence.claimed_scope_end != partition.scope_end
        ):
            raise CoverageBasisError("authoritative evidence scope does not match the partition")
        if evidence.completeness_method != AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD:
            raise CoverageBasisError("authoritative evidence completeness method is not recognized")
        if evidence.completeness_claim != COMPLETE_OBSERVED_DAILY_BAR_SCOPE:
            raise CoverageBasisError("authoritative evidence is not explicitly complete")
        base = {
            "coverage_basis_id": evidence.coverage_basis_id,
            "coverage_basis_version": COVERAGE_BASIS_VERSION,
            "research_split": partition.research_split.value,
            "calendar_year": partition.calendar_year,
            "calendar_month": partition.calendar_month,
            "source_snapshot_id": evidence.source_snapshot_id,
            "source_snapshot_manifest_hash": evidence.source_snapshot_manifest_hash,
            "source_domain": evidence.source_domain,
            "claimed_scope_start": partition.scope_start,
            "claimed_scope_end": partition.scope_end,
            "source_selection_fingerprint": evidence.source_selection_fingerprint,
            "completeness_method": evidence.completeness_method,
            "completeness_claim": evidence.completeness_claim,
            "coverage_basis_artifact_uri": (
                f"coverage_basis/{partition.research_split.value}/"
                f"{partition.calendar_year:04d}-{partition.calendar_month:02d}.json"
            ),
        }
        artifact_bytes = canonical_json(base).encode("utf-8")
        descriptor = CoverageBasisDescriptor.from_mapping(
            base | {"coverage_basis_artifact_hash": sha256_hex(artifact_bytes)},
            artifact_bytes=artifact_bytes,
            authoritative_evidence=evidence,
        )
        self.verify_descriptor(
            descriptor,
            source_snapshot_id=evidence.source_snapshot_id,
            source_snapshot_manifest_hash=evidence.source_snapshot_manifest_hash,
            source_snapshot_as_of=evidence.source_snapshot_as_of,
        )
        return descriptor

    def verify_descriptor(
        self,
        descriptor: CoverageBasisDescriptor,
        *,
        source_snapshot_id: str,
        source_snapshot_manifest_hash: str,
        source_snapshot_as_of: datetime,
    ) -> CoverageBasisDescriptor:
        """Re-verify descriptor, sidecar binding and snapshot PIT facts."""
        if descriptor.evidence_class.value != "AUTHORITATIVE_UPSTREAM":
            raise CoverageBasisError("descriptor is not authoritative upstream evidence")
        evidence = descriptor.authoritative_evidence
        if evidence is None:  # pragma: no cover - descriptor constructor guards this
            raise CoverageBasisError("authoritative descriptor is missing its evidence sidecar")
        if descriptor.source_snapshot_id != source_snapshot_id:
            raise CoverageBasisError("authoritative descriptor source snapshot is stale")
        if descriptor.source_snapshot_manifest_hash != source_snapshot_manifest_hash:
            raise CoverageBasisError("authoritative descriptor source snapshot hash is stale")
        if evidence.source_snapshot_as_of != ensure_utc_timestamp(source_snapshot_as_of):
            raise CoverageBasisError("authoritative evidence snapshot PIT is stale")
        expected_descriptor = self._descriptor_without_rebuilding(descriptor, evidence)
        if descriptor.as_dict() != expected_descriptor.as_dict():
            raise CoverageBasisError("authoritative descriptor binding changed")
        if descriptor.artifact_bytes != expected_descriptor.artifact_bytes:
            raise CoverageBasisError("authoritative descriptor bytes changed")
        return descriptor

    @staticmethod
    def _descriptor_without_rebuilding(
        descriptor: CoverageBasisDescriptor,
        evidence: AuthoritativeCoverageEvidence,
    ) -> CoverageBasisDescriptor:
        """Recreate the descriptor from its own typed fields for replay checks."""
        base = descriptor.as_dict(include_artifact_hash=False)
        artifact_bytes = canonical_json(base).encode("utf-8")
        return CoverageBasisDescriptor.from_mapping(
            base | {"coverage_basis_artifact_hash": sha256_hex(artifact_bytes)},
            artifact_bytes=artifact_bytes,
            authoritative_evidence=evidence,
        )


def build_authoritative_coverage_basis_descriptor(
    partition: PartitionKey,
    evidence: AuthoritativeCoverageEvidence,
) -> CoverageBasisDescriptor:
    """Convenience entry point for the reviewed AmazingData binding."""
    return AuthoritativeCoverageBasisAdapter.reviewed_amazingdata_history().build_descriptor(
        partition, evidence
    )
