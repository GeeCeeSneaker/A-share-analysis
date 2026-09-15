"""Direct bridge from a reviewed acquisition receipt to coverage input.

The materializer already owns ``CoverageBasisDescriptor``. This module keeps
one small function for the only enabled source instead of maintaining a
stateful adapter hierarchy and a second descriptor replay protocol.
"""

from __future__ import annotations

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
from ashare_state.research.models import canonical_json, sha256_hex

__all__ = ["build_authoritative_coverage_basis_descriptor"]


def build_authoritative_coverage_basis_descriptor(
    partition: PartitionKey,
    evidence: AuthoritativeCoverageEvidence,
) -> CoverageBasisDescriptor:
    """Validate one reviewed receipt and bridge it to the materializer.

    The provider path establishes the receipt; this function only checks the
    already-issued receipt's identity/scope and builds the existing coverage
    descriptor. It does not introduce a new evidence or authority object.
    """
    if not isinstance(partition, PartitionKey):
        raise CoverageBasisError("authoritative coverage needs a typed partition")
    if not isinstance(evidence, AuthoritativeCoverageEvidence):
        raise CoverageBasisError("authoritative coverage needs typed acquisition evidence")
    selection = AuthoritativeSourceSelection.reviewed_amazingdata_history()
    if evidence.source_selection != selection:
        raise CoverageBasisError("authoritative evidence source-selection binding changed")
    if evidence.source_selection_fingerprint != selection.selection_fingerprint:
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
    return CoverageBasisDescriptor.from_mapping(
        base | {"coverage_basis_artifact_hash": sha256_hex(artifact_bytes)},
        artifact_bytes=artifact_bytes,
        authoritative_evidence=evidence,
    )
