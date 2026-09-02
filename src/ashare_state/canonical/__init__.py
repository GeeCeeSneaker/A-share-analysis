"""Canonical runtime (CR-3 / CR-3.1, audit 20260901): Provider-Normalized
-> Canonical with typed availability policy, governed identity bridge,
versioned static source policy and exact-replay canonical runs over ONE
authoritative input snapshot.

Boundary summary::

    ONE CanonicalInputSnapshot (requested domain set + verified CR-2
      source runs + verified identity master runs + policy identities)
      -> read-only closure verification + anchored availability evidence
      -> identity bridge (security_master -> security_id, fail closed)
      -> availability derivation + as_of filter (BEFORE selection)
      -> source selection / EXACT reconciliation (static policy)
      -> immutable canonical artifacts + canonicalization ledger
"""

from ashare_state.canonical.availability import (
    AVAILABILITY_POLICY_VERSION,
    AvailabilityBasis,
    AvailabilityPolicyEntry,
    availability_policy_entries,
    availability_policy_hash,
    availability_policy_version,
    derive_available_at,
)
from ashare_state.canonical.canonicalizer import (
    CanonicalFinding,
    CanonicalInputSnapshot,
    CanonicalRunner,
    CanonicalRunnerError,
    CanonicalRunResult,
    CanonicalRunSeal,
    InputRunSeal,
    InputVerificationEvidence,
    MaterializedOutput,
    SnapshotRun,
    canonical_code_fingerprint,
)
from ashare_state.canonical.eligibility import (
    CANONICAL_CONTRACT_VERSION,
    CanonicalDomainSpec,
    DomainEligibility,
    domain_spec,
    domain_specs,
    supported_domains,
)
from ashare_state.canonical.identity import (
    IDENTITY_BRIDGE_POLICY_VERSION,
    IdentityBridge,
    IdentityResolutionError,
    identity_bridge_policy_hash,
    identity_bridge_policy_version,
    identity_dataset_hash,
)
from ashare_state.canonical.source_policy import (
    SOURCE_POLICY_VERSION,
    CanonicalSourcePolicy,
    source_policies,
    source_policy_for,
    source_policy_hash,
    source_policy_version,
    tolerance_policy_identity,
)

__all__ = [
    "AVAILABILITY_POLICY_VERSION",
    "AvailabilityBasis",
    "AvailabilityPolicyEntry",
    "CANONICAL_CONTRACT_VERSION",
    "CanonicalDomainSpec",
    "CanonicalFinding",
    "CanonicalInputSnapshot",
    "CanonicalRunner",
    "CanonicalRunnerError",
    "CanonicalRunResult",
    "CanonicalRunSeal",
    "CanonicalSourcePolicy",
    "DomainEligibility",
    "IDENTITY_BRIDGE_POLICY_VERSION",
    "IdentityBridge",
    "IdentityResolutionError",
    "InputRunSeal",
    "InputVerificationEvidence",
    "MaterializedOutput",
    "SOURCE_POLICY_VERSION",
    "SnapshotRun",
    "availability_policy_entries",
    "availability_policy_hash",
    "availability_policy_version",
    "canonical_code_fingerprint",
    "derive_available_at",
    "domain_spec",
    "domain_specs",
    "identity_bridge_policy_hash",
    "identity_bridge_policy_version",
    "identity_dataset_hash",
    "source_policy_for",
    "source_policy_hash",
    "source_policies",
    "source_policy_version",
    "supported_domains",
    "tolerance_policy_identity",
]
