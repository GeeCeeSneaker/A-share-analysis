"""Typed canonical source policy (CR-3, audit 20260901 CR3-P0-07..P0-09).

The STATIC, versioned source-selection policy per canonical domain.
Ordinary callers can NOT inject provider priority / tolerance /
fallback / partial allowances - the runtime accepts no such parameters
(structurally asserted by tests), exactly like the frozen CR-2 static
registries.

Current production reality: ONE provider (amazingdata), so the policy
declares single-source EXACT reconciliation with no fallback. The
policy fields exist as typed slots so a second provider arrives as a
versioned POLICY CHANGE (new policy version -> new canonical run
identity -> history preserved), never as a caller argument.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "SOURCE_POLICY_VERSION",
    "CanonicalSourcePolicy",
    "source_policy_for",
    "source_policy_hash",
    "source_policy_version",
    "source_policies",
]


#: versioned identity of the source policy
SOURCE_POLICY_VERSION = "source-policy-v1"


@dataclass(frozen=True)
class CanonicalSourcePolicy:
    """Source-selection truth for ONE canonical domain."""

    domain: str
    priority_providers: tuple[str, ...] = ("amazingdata",)
    allowed_fallback_providers: tuple[str, ...] = ()
    #: PARTIAL CR-2 runs are consumed only when the domain policy says
    #: so (CR3-P0-02); no domain allows it in this version.
    partial_run_allowed: bool = False
    #: single-provider EXACT comparison; cross-value disagreement at the
    #: same key is a SOURCE_CONFLICT finding (never last-write-wins)
    reconciliation: str = "SINGLE_SOURCE_EXACT"
    tolerance_rule_id: str = "exact-v1"
    tolerance_rule_version: str = "1"
    #: IDENTITY_MISSING/AMBIGUOUS findings above this count BLOCK the run
    identity_missing_max: int = 0
    conflict_action: str = "BLOCK"
    required_evidence_class: str = "PROVIDER_NORMALIZED_VERIFIED"


_POLICY: tuple[CanonicalSourcePolicy, ...] = tuple(
    CanonicalSourcePolicy(domain=domain)
    for domain in (
        "trade_calendar",
        "daily_bar",
        "security_status",
        "limit_price",
        "adj_factor",
    )
)

_INDEX = {policy.domain: policy for policy in _POLICY}


def source_policies() -> tuple[CanonicalSourcePolicy, ...]:
    return _POLICY


def source_policy_for(domain: str) -> CanonicalSourcePolicy:
    policy = _INDEX.get(domain)
    if policy is None:
        msg = f"no source policy for canonical domain {domain!r}"
        raise KeyError(msg)
    return policy


def source_policy_version() -> str:
    """Current policy identity (module-level indirection for tests)."""
    return SOURCE_POLICY_VERSION


def source_policy_hash() -> str:
    import hashlib

    canonical = "|".join(
        f"{p.domain}:{'>'.join(p.priority_providers)}:{p.reconciliation}:"
        f"{p.tolerance_rule_id}:{int(p.partial_run_allowed)}:{p.conflict_action}"
        for p in _POLICY
    )
    return hashlib.sha256(f"{source_policy_version()}|{canonical}".encode()).hexdigest()


def tolerance_policy_identity() -> tuple[str, str]:
    """(tolerance version, hash) entering the canonical run identity."""
    import hashlib

    rules = {p.domain: (p.tolerance_rule_id, p.tolerance_rule_version) for p in _POLICY}
    canonical = "|".join(f"{d}:{r[0]}@{r[1]}" for d, r in sorted(rules.items()))
    version = "tolerance-v1"
    return version, hashlib.sha256(canonical.encode("utf-8")).hexdigest()
