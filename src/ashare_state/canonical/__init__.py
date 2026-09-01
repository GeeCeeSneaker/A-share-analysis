"""Canonical runtime (CR-3, audit 20260901): Provider-Normalized ->
Canonical with typed availability policy, governed identity bridge,
versioned static source policy and exact-replay canonical runs.

Boundary summary::

    CR-2 verified Provider-Normalized runs (SUCCESS only)
      -> read-only closure verification
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
    CanonicalRunner,
    CanonicalRunnerError,
    CanonicalRunResult,
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
    "CanonicalRunner",
    "CanonicalRunnerError",
    "CanonicalRunResult",
    "CanonicalSourcePolicy",
    "DomainEligibility",
    "IDENTITY_BRIDGE_POLICY_VERSION",
    "IdentityBridge",
    "IdentityResolutionError",
    "SOURCE_POLICY_VERSION",
    "availability_policy_entries",
    "availability_policy_hash",
    "availability_policy_version",
    "canonical_code_fingerprint",
    "derive_available_at",
    "domain_spec",
    "domain_specs",
    "source_policy_for",
    "source_policy_hash",
    "source_policies",
    "source_policy_version",
    "supported_domains",
    "tolerance_policy_identity",
]
