"""Typed availability policy (CR-3, audit 20260901 CR3-P0-03/P0-04).

PIT ordering is machine-enforced::

    candidate -> derive available_at -> filter available_at <= as_of
              -> ONLY THEN source selection / reconciliation

``available_at`` derivation is TYPED per domain and never fabricated:

- ``SOURCE_PUBLISHED_AT``  : a verified provider publish timestamp
  exists and is used. NO current amazingdata surface carries one, so
  no domain uses this basis yet.
- ``OBSERVED_AT_INGEST``   : the conservative default - the provider
  answer time persisted on the raw envelope (``received_at``), read
  from the CR-2 verified raw evidence. This is later than any true
  publish moment, hence conservative for PIT (never leaks future
  knowledge as available-too-early).
- ``DOMAIN_RULE_DERIVED``  : requires a VERSIONED Trading Rule /
  Calendar fact reference + policy version. Not used yet - deriving
  availability from market close times would hard-code institutional
  facts without a governed source.
- ``NOT_VERIFIABLE``       : may NEVER enter PIT canonical truth
  (enforced structurally - the basis is absent from the registry).

Forbidden and structurally guarded (tests):
- writing ``trade_date 00:00`` / ``1970-01-01`` / a fixed close time as
  available_at;
- selecting a source first and checking availability afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
    "AVAILABILITY_POLICY_VERSION",
    "AvailabilityBasis",
    "AvailabilityPolicyEntry",
    "availability_policy_entries",
    "availability_policy_hash",
    "availability_policy_version",
    "derive_available_at",
]


#: versioned identity of the availability policy (changes bump this)
AVAILABILITY_POLICY_VERSION = "availability-v1"


class AvailabilityBasis(StrEnum):
    SOURCE_PUBLISHED_AT = "SOURCE_PUBLISHED_AT"
    OBSERVED_AT_INGEST = "OBSERVED_AT_INGEST"
    DOMAIN_RULE_DERIVED = "DOMAIN_RULE_DERIVED"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"


@dataclass(frozen=True)
class AvailabilityPolicyEntry:
    domain: str
    basis: AvailabilityBasis


#: the STATIC production availability policy. Every CANONICAL_SUPPORTED
#: domain uses the conservative OBSERVED_AT_INGEST basis - the provider
#: publishes no verified source publish timestamp for any surface.
_POLICY: tuple[AvailabilityPolicyEntry, ...] = (
    AvailabilityPolicyEntry("trade_calendar", AvailabilityBasis.OBSERVED_AT_INGEST),
    AvailabilityPolicyEntry("daily_bar", AvailabilityBasis.OBSERVED_AT_INGEST),
    AvailabilityPolicyEntry("security_status", AvailabilityBasis.OBSERVED_AT_INGEST),
    AvailabilityPolicyEntry("limit_price", AvailabilityBasis.OBSERVED_AT_INGEST),
    AvailabilityPolicyEntry("adj_factor", AvailabilityBasis.OBSERVED_AT_INGEST),
)

_INDEX = {entry.domain: entry for entry in _POLICY}


def availability_policy_entries() -> tuple[AvailabilityPolicyEntry, ...]:
    return _POLICY


def availability_policy_version() -> str:
    """Current policy identity (module-level indirection so tests can
    monkeypatch the version and assert new-run semantics)."""
    return AVAILABILITY_POLICY_VERSION


def availability_policy_hash() -> str:
    import hashlib

    canonical = "|".join(f"{e.domain}:{e.basis.value}" for e in _POLICY)
    return hashlib.sha256(f"{availability_policy_version()}|{canonical}".encode()).hexdigest()


def derive_available_at(domain: str, received_at: datetime) -> datetime:
    """Derive the PIT availability moment for one candidate row.

    The ONLY basis in production is OBSERVED_AT_INGEST: the raw
    envelope's provider answer time. This function exists so the
    derivation is a typed, single, inspectable policy decision - the
    canonicalizer never invents a timestamp at a call site.
    """
    entry = _INDEX.get(domain)
    if entry is None or entry.basis is not AvailabilityBasis.OBSERVED_AT_INGEST:
        msg = (
            f"domain {domain!r} has no OBSERVED_AT_INGEST availability basis - "
            "NOT_VERIFIABLE/unregistered bases can never enter PIT canonical "
            "truth (CR3-P0-04)"
        )
        raise ValueError(msg)
    return received_at
