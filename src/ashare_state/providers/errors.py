"""Shared provider error taxonomy (audit P1-10).

Single authoritative definition: every provider adapter subclasses /
re-exports from here so callers can catch ONE exception hierarchy
regardless of which broker SDK sits underneath.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ashare_state.providers.exchange import ProviderExchange


class ProviderError(RuntimeError):
    """Base class for all provider-layer errors.

    CR-1.1 (audit R4-A2.3 §3.2-D): a FAILED SDK exchange is a first-class
    object. When the failure happened inside a real SDK exchange,
    ``call_exchange`` attaches the failed ProviderExchange (error envelope,
    payload=None) to the raised error, so callers obtain the exchange's
    request_id / envelope / attempt_count / error_class / requested_at /
    received_at WITHOUT any shared-state lookup (no last_envelopes
    reverse-search on the correctness path).
    """

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        exchange: ProviderExchange | None = None,
    ) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = context or {}
        self.exchange: ProviderExchange | None = exchange


class ProviderUnavailableError(ProviderError):
    """SDK not installed / not importable (expected outside controlled machine)."""


class ProviderNetworkError(ProviderError):
    """Connection cannot be established to the access server."""


class ProviderAuthError(ProviderError):
    """Authentication failed (bad credentials, expired account)."""


class ProviderPermissionError(ProviderError):
    """Server refused the dataset: entitlement missing (PermissionCode scope)."""


class ProviderTimeoutError(ProviderError):
    """Call exceeded its configured time budget (SDK may retry internally)."""


class ProviderRateLimitError(ProviderError):
    """Provider-side flow/bandwidth/rate limit hit."""


class ProviderSchemaError(ProviderError):
    """Response shape does not match the documented SDK contract."""


class MappingValidationError(ProviderSchemaError):
    """A REQUIRED source field is missing/unparsable (audit P0-04).

    Critical fields (security_code, trade_date, OHLC, adj-factor keys)
    must NEVER be silently coerced to sentinel values (1970-01-01 / 0.0):
    the row is quarantined by raising, and the caller records evidence.
    """


class ProviderEmptyResultError(ProviderError):
    """Call succeeded but returned an empty/None payload legitimately."""


class ProviderSdkInternalError(ProviderError):
    """SDK raised an internal/unclassifiable error; original preserved as cause."""


class ProviderGovernanceError(ProviderError):
    """INTERNAL governance refusal (audit R2-P1-02).

    Distinct from ProviderPermissionError (broker-side entitlement):
    this class means OUR governance layer refused the call, e.g. a
    CANDIDATE capability used in PRODUCTION mode. Provider-entitlement
    statistics must count only ProviderPermissionError.
    """


class ProviderCapabilityNotApprovedError(ProviderGovernanceError):
    """Capability is not APPROVED for the requested use mode (R2-P1-02)."""


#: error classes that must NEVER be retried (audit P0-03)
NON_RETRYABLE_ERRORS: tuple[type[ProviderError], ...] = (
    ProviderAuthError,
    ProviderPermissionError,
    ProviderSchemaError,
    ProviderEmptyResultError,
    ProviderSdkInternalError,
)

#: error classes whose retry is a POLICY decision (audit P0-03)
RETRYABLE_ERRORS: tuple[type[ProviderError], ...] = (
    ProviderNetworkError,
    ProviderTimeoutError,
    ProviderRateLimitError,
)


def is_retryable(error: ProviderError) -> bool:
    """Default retry policy: only network/timeout/rate-limit classes retry."""
    return isinstance(error, RETRYABLE_ERRORS)
