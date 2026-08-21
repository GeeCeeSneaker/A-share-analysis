"""Deterministic security identity (ADR-002, V1.3.2 section 6.2, design ruling 6).

Rules frozen by design ruling 2026-08-21:

1. PROJECT_SECURITY_NAMESPACE is a fixed literal UUID in code; generating it
   at startup or using uuid4 is FORBIDDEN. Once fixed it never changes.
2. initial_symbol must be the internal normalized exchange code (e.g. "000001"),
   never "000001.SZ" / "SZ000001" / a provider-specific code. Provider symbols
   live only in bridge_security_provider_symbol.
3. A-share securities missing first_list_date may get a temporary identity
   with IDENTITY_FALLBACK in STAGING/Spike contexts, but PUBLISHED output
   MUST be blocked.
4. After the first official publish, identity key inputs are frozen: no
   re-keying; corrections go to identity errata / DQ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid5

from ashare_state.domain.types import IdentityKeyVersion, QualityFlag

# ADR-002: permanent namespace, generated once via
#   uuid.uuid5(uuid.NAMESPACE_DNS, "ashare-state.security-identity.v1")
# and then frozen as a literal. NEVER regenerate, NEVER derive at runtime.
PROJECT_SECURITY_NAMESPACE: UUID = UUID("b2e7b5e4-28f5-5384-8508-bcc20755d552")

_VALID_SYMBOL = re.compile(r"^\d{6}$")

# Suffixes stripped when normalizing provider-style symbols to internal codes.
_SYMBOL_SUFFIXES = (".SZ", ".SH", ".BJ", ".SS")

_VALID_EXCHANGES = frozenset({"SSE", "SZSE", "BSE"})

# A-share stock asset type (Phase 0 scope).
_ASSET_TYPE_STOCK = "STOCK"


class IdentityError(ValueError):
    """Base error for identity resolution failures."""


class InvalidSymbolError(IdentityError):
    """Symbol is not a normalizable internal exchange code."""


class MissingListDateError(IdentityError):
    """first_list_date is required for a non-fallback identity."""


class IdentityPublishBlockedError(IdentityError):
    """Fallback identity is not allowed in PUBLISHED output (ruling 6.3)."""


def normalize_symbol(symbol: str) -> str:
    """Normalize a provider-style or internal symbol to the internal code.

    Accepts "000001", "000001.SZ", "SZ000001" and returns "000001".
    The result must be exactly 6 digits (A-share stock code space).
    """
    s = symbol.strip().upper()
    for suffix in _SYMBOL_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    else:
        if s.startswith(("SZ", "SH", "BJ")) and len(s) == 8:
            s = s[2:]
    if not _VALID_SYMBOL.match(s):
        msg = f"symbol {symbol!r} does not normalize to a 6-digit internal code"
        raise InvalidSymbolError(msg)
    return s


def build_identity_key(
    exchange: str,
    asset_type: str,
    initial_symbol: str,
    first_list_date: date,
) -> str:
    """Build the V1 identity key: EXCHANGE:ASSET_TYPE:SYMBOL:YYYYMMDD."""
    ex = exchange.strip().upper()
    if ex not in _VALID_EXCHANGES:
        msg = f"exchange {exchange!r} not in {_VALID_EXCHANGES}"
        raise IdentityError(msg)
    at = asset_type.strip().upper()
    if not at:
        msg = "asset_type must not be empty"
        raise IdentityError(msg)
    sym = normalize_symbol(initial_symbol)
    return f"{ex}:{at}:{sym}:{first_list_date.strftime('%Y%m%d')}"


def build_identity_key_fallback(
    exchange: str,
    asset_type: str,
    initial_symbol: str,
    first_seen_trade_date: date,
) -> str:
    """Build the FALLBACK identity key (ruling 6.3, V1.3.2 section 6.2).

    Used only in Spike/STAGING contexts when list_date is unavailable.
    The resulting identity carries IDENTITY_FALLBACK and cannot be published.
    """
    ex = exchange.strip().upper()
    if ex not in _VALID_EXCHANGES:
        msg = f"exchange {exchange!r} not in {_VALID_EXCHANGES}"
        raise IdentityError(msg)
    at = asset_type.strip().upper() or _ASSET_TYPE_STOCK
    sym = normalize_symbol(initial_symbol)
    return f"{ex}:{at}:{sym}:F{first_seen_trade_date.strftime('%Y%m%d')}"


def security_id_v1(identity_key: str) -> UUID:
    """Deterministic security_id = UUIDv5(PROJECT_SECURITY_NAMESPACE, identity_key)."""
    return uuid5(PROJECT_SECURITY_NAMESPACE, identity_key)


@dataclass(frozen=True)
class ResolvedIdentity:
    """Outcome of identity resolution."""

    security_id: UUID
    identity_key: str
    identity_key_version: IdentityKeyVersion
    quality_flags: tuple[str, ...]

    @property
    def is_fallback(self) -> bool:
        return self.identity_key_version is IdentityKeyVersion.SECURITY_IDENTITY_V1_FALLBACK

    def assert_publishable(self) -> None:
        """Ruling 6.3: fallback identities must never enter PUBLISHED output."""
        if self.is_fallback:
            msg = (
                "security identity uses IDENTITY_FALLBACK (missing first_list_date); "
                "PUBLISHED output is BLOCKED until a reliable list_date resolves the identity"
            )
            raise IdentityPublishBlockedError(msg)


def resolve_security_identity(
    exchange: str,
    asset_type: str,
    initial_symbol: str,
    first_list_date: date | None,
    *,
    first_seen_trade_date: date | None = None,
) -> ResolvedIdentity:
    """Resolve a deterministic security identity.

    - With first_list_date: SECURITY_IDENTITY_V1 (publishable).
    - Without it: SECURITY_IDENTITY_V1_FALLBACK with IDENTITY_FALLBACK flag
      (Spike/STAGING only; call assert_publishable() before publishing).
    """
    if first_list_date is not None:
        key = build_identity_key(exchange, asset_type, initial_symbol, first_list_date)
        version = IdentityKeyVersion.SECURITY_IDENTITY_V1
        flags: tuple[str, ...] = ()
    else:
        if first_seen_trade_date is None:
            msg = "first_seen_trade_date is required for fallback identity"
            raise MissingListDateError(msg)
        key = build_identity_key_fallback(
            exchange, asset_type, initial_symbol, first_seen_trade_date
        )
        version = IdentityKeyVersion.SECURITY_IDENTITY_V1_FALLBACK
        flags = (QualityFlag.IDENTITY_FALLBACK.value,)
    return ResolvedIdentity(
        security_id=security_id_v1(key),
        identity_key=key,
        identity_key_version=version,
        quality_flags=flags,
    )
