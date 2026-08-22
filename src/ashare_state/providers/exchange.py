"""ProviderExchange: the unified audit unit for ONE SDK exchange (CR-1).

Contract (audit R4-A2 section 42-44):
    1 SDK exchange = 1 request_id = 1 RawEnvelope = <=1 payload

- call_exchange(...) RETURNS the ProviderExchange (no thread-local
  'last_exchange' pattern, no consume_last_exchange()).
- Business convenience wrappers (get_xxx) return exchange.payload.
- Spike probes and RawWriter MUST consume ProviderExchange (they reuse
  the envelope's request_id - never regenerate one).
- Every REAL SDK call gets its own exchange: hidden calls inside an SDK
  method (e.g. query_kline -> get_calendar -> query_kline) are separate
  exchanges with their own request ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderExchange:
    """One SDK exchange: envelope + at-most-one payload."""

    envelope: Any  # RawEnvelope (duck-typed to avoid a circular import)
    payload: Any

    @property
    def request_id(self) -> str:
        return getattr(self.envelope, "request_id", "")
