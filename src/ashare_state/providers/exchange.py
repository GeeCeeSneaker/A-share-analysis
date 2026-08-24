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

import uuid
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


def synthetic_failure_exchange(
    *, endpoint: str, dataset: str, error: BaseException
) -> ProviderExchange:
    """Honest envelope for a call that NEVER reached a real SDK exchange
    (e.g. a governance/capability gate rejection raised before any SDK
    invocation).

    The fresh request_id explicitly does NOT claim to be a real SDK
    exchange; the envelope records the endpoint/dataset that was ATTEMPTED
    and the error class observed. This keeps failure evidence first-class
    (audit R4-A2.3 section 3.2-D) without any shared-state lookup.

    Real SDK failures carry the exchange attached by call_exchange on the
    raised ProviderError - this helper is only the no-SDK-yet fallback.
    """
    from ashare_state.providers.amazingdata.provider import RawEnvelope

    env = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=str(uuid.uuid4()),
        requested_at="",
        received_at="",
        status="ERROR",
        error_class=type(error).__name__,
        account_profile_id="UNKNOWN",
        row_count=0,
    )
    return ProviderExchange(envelope=env, payload=None)
