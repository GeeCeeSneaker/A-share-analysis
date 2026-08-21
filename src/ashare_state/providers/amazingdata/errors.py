"""Unified provider error layer (task book section 3.2).

SDK-internal errors (TypeError, opaque strings) must NEVER cross the
provider boundary unclassified. Every failure is mapped to one of the
typed errors below; when classification is impossible it becomes
ProviderSdkInternalError with the original exception preserved as
__cause__.
"""

from __future__ import annotations

from collections.abc import Callable
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


class ProviderEmptyResultError(ProviderError):
    """Call succeeded but returned an empty/None payload legitimately."""


class ProviderSdkInternalError(ProviderError):
    """SDK raised an internal/unclassifiable error; original preserved as cause."""


# ---------------------------------------------------------------- mapping

_PERMISSION_NONE_HINTS = ("nonetype", "unhashable")
_AUTH_HINTS = ("login fail", "logon fail", "password", "auth", "token")
_NET_HINTS = ("connect", "connection", "refused", "timeout", "unreachable", "reset")
_RATE_HINTS = ("flow", "bandwidth", "rate", "limit num", "limitnum", "too fast")
_QUERY_FAIL = "查询失败"
_EMPTY_HINTS = ("no data", "empty")


def classify_sdk_error(
    exc: BaseException,
    *,
    endpoint: str = "",
    response: Any = None,
    account_context: dict[str, Any] | None = None,
) -> ProviderError:
    """Map an arbitrary SDK exception to a typed provider error.

    The original exception is preserved as __cause__ on the returned error.

    Mapping heuristics (documented so behavior is auditable):
    - TypeError with 'NoneType' -> the observed shape of entitlement denial
      (server returns None; SDK then subscripts it). If account_context
      shows limited PermissionCode, this is ProviderPermissionError.
    - Chinese '查询失败' after long retries -> permission or timeout;
      classified as ProviderPermissionError when the endpoint is outside
      the account's known permission set, else ProviderTimeoutError.
    - network-ish substrings -> ProviderNetworkError.
    - everything else -> ProviderSdkInternalError (cause preserved).
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

    if name == "TypeError" and any(h in lowered for h in _PERMISSION_NONE_HINTS):
        # observed entitlement-denial shape (connectivity evidence 2026-08-21)
        return ProviderPermissionError(
            f"{endpoint}: server returned no data (likely entitlement "
            f"denial); sdk raised {name}: {msg}",
            context=context,
        )

    if any(h in lowered for h in _AUTH_HINTS) and "token" not in lowered:
        return ProviderAuthError(f"{endpoint}: auth failure: {msg}", context=context)

    if _QUERY_FAIL in msg:
        if account_context and account_context.get("permission_codes"):
            return ProviderPermissionError(
                f"{endpoint}: query failed; endpoint outside PermissionCode "
                f"{account_context.get('permission_codes')}: {msg}",
                context=context,
            )
        return ProviderTimeoutError(
            f"{endpoint}: query failed after long retries: {msg}", context=context
        )

    if any(h in lowered for h in _RATE_HINTS):
        return ProviderRateLimitError(f"{endpoint}: rate/flow limit: {msg}", context=context)

    if any(h in lowered for h in _NET_HINTS):
        return ProviderNetworkError(f"{endpoint}: network error: {msg}", context=context)

    if response is None and any(h in lowered for h in _EMPTY_HINTS):
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
