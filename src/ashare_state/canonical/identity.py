"""Governed identity bridge (CR-3, audit 20260901 CR3-P0-05).

Provider symbol -> ``security_id`` resolution is a GOVERNED mapping
built from the CR-2 verified ``security_master`` output, resolved
through the deterministic ADR-002 identity (uuidv5 over
``EXCHANGE:ASSET:SYMBOL:F<list_date>``).

Fail-closed rulings:

- exchange attribution comes ONLY from the provider's own market
  suffix on the normalized provider symbol (``600000.SH`` -> SSE),
  which is verified provider semantics (CR-2 mapper ``_MARKET_SUFFIX``)
  - NEVER from bare-code prefix guessing;
- a symbol with no security_master entry is a MISSING identity ->
  canonical finding + row excluded (the bare provider symbol is never
  used as a canonical key fallback);
- relisting (same symbol, several list dates) resolves PIT: the latest
  identity whose list_date <= the row's trade_date; none applies ->
  missing;
- a conflicting dataset (same provider_symbol + list_date resolving to
  different security ids - unreachable through ADR-002 but kept as a
  defensive branch) is AMBIGUOUS -> finding + excluded.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from ashare_state.identity.security_id import resolve_security_identity

__all__ = [
    "IDENTITY_BRIDGE_POLICY_VERSION",
    "IdentityBridge",
    "IdentityResolutionError",
    "ResolvedIdentityOutcome",
]


#: versioned identity of the bridge policy (PIT selection rule)
IDENTITY_BRIDGE_POLICY_VERSION = "identity-bridge-v1"

#: provider market suffix -> exchange literal (verified provider
#: semantics shared with the CR-2 mapper; NOT code-prefix guessing)
_SUFFIX_TO_EXCHANGE = {".SH": "SSE", ".SZ": "SZSE", ".BJ": "BSE"}

#: the security_master dataset feeds A-share stocks (verified dataset
#: semantics of BaseData.get_code_list / hist / stock_basic)
_ASSET_TYPE = "STOCK"


class IdentityResolutionError(RuntimeError):
    """The identity bridge contract was violated."""


@dataclass(frozen=True)
class ResolvedIdentityOutcome:
    security_id: str
    provider_symbol: str


@dataclass(frozen=True)
class _IdentityEntry:
    security_id: str
    list_date: date


class IdentityBridge:
    """The immutable provider-symbol -> security_id mapping for one
    canonical run, built from the CR-2 verified security_master rows."""

    def __init__(self, master_rows: list[dict[str, Any]], *, dataset_hash: str) -> None:
        self._dataset_hash = str(dataset_hash)
        self._by_symbol: dict[str, list[_IdentityEntry]] = {}
        for row in master_rows:
            symbol = str(row.get("provider_symbol") or "")
            list_date_raw = row.get("list_date")
            if not symbol or not list_date_raw:
                # security_master rows without a list_date cannot build a
                # publishable identity (ADR-002 fallback ruling) - the
                # symbol simply has no governed entry here
                continue
            list_date = _as_date(list_date_raw)
            suffix = symbol[symbol.rfind(".") :] if "." in symbol else ""
            exchange = _SUFFIX_TO_EXCHANGE.get(suffix)
            if exchange is None:
                msg = (
                    f"security_master row carries provider symbol {symbol!r} "
                    "without a known market suffix - cannot attribute exchange"
                )
                raise IdentityResolutionError(msg)
            resolved = resolve_security_identity(
                exchange, _ASSET_TYPE, symbol[: symbol.rfind(".")], list_date
            )
            entry = _IdentityEntry(str(resolved.security_id), list_date)
            self._by_symbol.setdefault(symbol, []).append(entry)

    @property
    def dataset_hash(self) -> str:
        """Identity of the underlying dataset + bridge policy (enters
        the canonical run identity)."""
        return hashlib.sha256(
            f"{IDENTITY_BRIDGE_POLICY_VERSION}|{self._dataset_hash}".encode()
        ).hexdigest()

    def resolve(self, provider_symbol: str, trade_date: date) -> str | None:
        """PIT resolution: the latest identity whose list_date <=
        trade_date, or None (missing). Deterministic - relisted symbols
        resolve to the identity valid AT the row's trade date.

        BARE codes (no market suffix - e.g. the CR-2 adj_factor surface
        carries provider symbols without market attribution) resolve
        through a UNIQUE-market match only: exactly one of the three
        suffixed variants exists in the dataset. Two variants existing
        is AMBIGUOUS (fail closed) - never a code-prefix guess, never a
        list-date tiebreak between markets."""
        symbol = str(provider_symbol)
        if "." in symbol:
            entries = self._by_symbol.get(symbol, [])
        else:
            present = [
                variant
                for variant in (f"{symbol}.SH", f"{symbol}.SZ", f"{symbol}.BJ")
                if self._by_symbol.get(variant)
            ]
            if len(present) > 1:
                return None  # ambiguous bare code - fail closed
            entries = self._by_symbol.get(present[0], []) if present else []
        if not entries:
            return None
        ids_at_date = [e for e in entries if e.list_date <= trade_date]
        if not ids_at_date:
            return None
        latest = max(e.list_date for e in ids_at_date)
        candidates = {e.security_id for e in ids_at_date if e.list_date == latest}
        if len(candidates) > 1:
            # defensive: ADR-002 makes this unreachable, but a conflicting
            # dataset must fail closed, never pick one
            return None
        return next(iter(candidates))


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        return date.fromisoformat(text[:10])
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    msg = f"unparsable date {value!r} in security_master identity dataset"
    raise IdentityResolutionError(msg)
