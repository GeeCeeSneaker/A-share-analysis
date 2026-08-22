"""AmazingData error layer: classification + retry policy (task book 3.2).

Audit fixes (2026-08-22):
- P1-10: taxonomy lives in ashare_state.providers.errors; this module only
  adds SDK-error classification and re-exports.
- P1-09: classification is CONSERVATIVE - only the two VERIFIED denial
  shapes observed on 2026-08-21 (TypeError/NoneType from entitlement
  denial, and unhashable-list was RECLASSIFIED to internal) map to
  Permission; unknown shapes default to ProviderSdkInternalError.
- P0-03: retry decisions use is_retryable() - permission/auth/schema/
  internal errors never retry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ashare_state.providers.errors import (
    NON_RETRYABLE_ERRORS,
    RETRYABLE_ERRORS,
    ProviderAuthError,
    ProviderCapabilityNotApprovedError,
    ProviderEmptyResultError,
    ProviderError,
    ProviderGovernanceError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderSchemaError,
    ProviderSdkInternalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    is_retryable,
)

__all__ = [
    "NON_RETRYABLE_ERRORS",
    "RETRYABLE_ERRORS",
    "ProviderAuthError",
    "ProviderCapabilityNotApprovedError",
    "ProviderEmptyResultError",
    "ProviderError",
    "ProviderGovernanceError",
    "ProviderNetworkError",
    "ProviderPermissionError",
    "ProviderRateLimitError",
    "ProviderSchemaError",
    "ProviderSdkInternalError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "classify_sdk_error",
    "is_retryable",
    "wrap_sdk_call",
]

# ---------------------------------------------------------------- mapping

_NET_HINTS = ("connect", "connection", "refused", "timeout", "unreachable", "reset")
_AUTH_HINTS = ("login fail", "logon fail", "password", "auth")
_RATE_HINTS = ("flow", "bandwidth", "rate", "limit num", "limitnum", "too fast")
_QUERY_FAIL = "查询失败"

#: verified denial signatures (2026-08-21 connectivity evidence): only
#: these may classify as ProviderPermissionError (audit R2-P1-03)
_VERIFIED_DENIAL_SIGNATURES = ("nonetype",)


def classify_sdk_error(
    exc: BaseException,
    *,
    endpoint: str = "",
    response: Any = None,
    account_context: dict[str, Any] | None = None,
) -> ProviderError:
    """Map an arbitrary SDK exception to a typed provider error.

    The original exception is preserved as __cause__.

    Conservative mapping (audit P1-09):
    - TypeError with 'NoneType' -> the VERIFIED entitlement-denial shape
      (2026-08-21 evidence) -> ProviderPermissionError.
    - '查询失败' with limited permission context -> ProviderPermissionError
      (verified shape); without context -> ProviderTimeoutError.
    - network-ish / auth-ish / rate-ish substrings map accordingly.
    - everything else (including 'unhashable list', which looks like an
      interface-signature issue) -> ProviderSdkInternalError.
    """
    mapped = _classify(exc, endpoint=endpoint, response=response, account_context=account_context)
    mapped.__cause__ = exc
    return mapped


def _classify(
    exc: BaseException,
    *,
    endpoint: str,
    response: Any,
    account_context: dict[str, Any] | None,
) -> ProviderError:
    msg = str(exc)
    lowered = msg.lower()
    name = type(exc).__name__
    context: dict[str, Any] = {"endpoint": endpoint, "sdk_exception_type": name}
    if account_context:
        context["account_context"] = account_context

    if isinstance(exc, TimeoutError):
        return ProviderTimeoutError(f"{endpoint}: timeout: {msg}", context=context)

    # VERIFIED denial shape #1: server returns None; SDK subscripts it.
    # (R2-P1-03: only VERIFIED signatures may classify as Permission)
    if name == "TypeError" and any(s in lowered for s in _VERIFIED_DENIAL_SIGNATURES):
        return ProviderPermissionError(
            f"{endpoint}: server returned no data (entitlement denial, "
            f"verified signature); sdk raised {name}: {msg}",
            context={
                **context,
                "classification_rule_id": "VERIFIED_NONE_SUBSCRIPT",
                "classification_confidence": "HIGH",
            },
        )

    # NOTE (audit P1-09): 'unhashable' was previously lumped into Permission;
    # it is NOT a verified denial shape - it stays unclassified/internal.
    if any(h in lowered for h in _AUTH_HINTS):
        return ProviderAuthError(f"{endpoint}: auth failure: {msg}", context=context)

    if _QUERY_FAIL in msg:
        # R2-P1-03: '查询失败' is NOT a verified denial signature - a
        # production account also has permission codes, so param errors /
        # server faults must not masquerade as entitlement problems.
        # Without an explicit endpoint-entitlement map the shape is
        # UNCLASSIFIED; the long-retry timeout note stays for diagnosis.
        return ProviderSdkInternalError(
            f"{endpoint}: generic query failure (unclassified; could be "
            f"params/server/entitlement): {msg}",
            context={
                **context,
                "classification_rule_id": "QUERY_FAIL_UNCLASSIFIED",
                "classification_confidence": "LOW",
                "note": "re-classify only with an explicit endpoint entitlement map",
            },
        )

    if any(h in lowered for h in _RATE_HINTS):
        return ProviderRateLimitError(f"{endpoint}: rate/flow limit: {msg}", context=context)

    if any(h in lowered for h in _NET_HINTS):
        return ProviderNetworkError(f"{endpoint}: network error: {msg}", context=context)

    if response is None and "no data" in lowered:
        return ProviderEmptyResultError(f"{endpoint}: empty result: {msg}", context=context)

    return ProviderSdkInternalError(
        f"{endpoint}: unclassified sdk error {name}: {msg}",
        context=context,
    )


def wrap_sdk_call(endpoint: str) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Decorator: catch anything, re-raise typed (cause preserved)."""

    def decorator(fn: Callable[..., object]) -> Callable[..., object]:
        import functools

        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            try:
                return fn(*args, **kwargs)
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001 - classification boundary
                raise classify_sdk_error(exc, endpoint=endpoint) from exc

        return wrapper

    return decorator
