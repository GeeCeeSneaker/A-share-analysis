"""Shared provider error taxonomy (audit P1-10).

Single authoritative definition: every provider adapter subclasses /
re-exports from here so callers can catch ONE exception hierarchy
regardless of which broker SDK sits underneath.
"""

from __future__ import annotations

from typing import Any


class ProviderError(RuntimeError):
    """Base class for all provider-layer errors."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = context or {}


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
