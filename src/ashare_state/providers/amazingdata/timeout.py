"""Retry budget for provider calls (task book section 4, audit P0-03).

Honest semantics (audit P0-03): this is a RETRY BUDGET, not a hard
timeout. Python timers cannot cancel a blocking native SDK call; if the
SDK blocks past the deadline we can only abandon waiting at the Python
layer - the SDK thread may still be running underneath. The subprocess
isolation experiment (task book 4.2) is tracked separately; do NOT
represent query_timeout_seconds as a hard timeout in any doc.

Retry discipline (audit P0-03): errors are CLASSIFIED FIRST, then the
retry decision consults is_retryable() - ProviderPermissionError /
ProviderAuthError / ProviderSchemaError / ProviderSdkInternalError remain
non-retryable by default.  A known endpoint may opt in to a narrowly
scoped, bounded retry for the SDK's unclassified ``查询失败`` response;
that exception is never enabled globally.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from ashare_state.providers.errors import (
    ProviderError,
    ProviderSdkInternalError,
    ProviderTimeoutError,
    is_retryable,
)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry with exponential backoff, jitter, and endpoint gates.

    ``ProviderSdkInternalError`` is deliberately not retryable in the
    general case.  The AmazingData SDK currently reports some server-side
    failures only as the generic ``查询失败`` message, so a caller that has
    separately accepted that risk may opt in *for exact endpoints* through
    ``retryable_generic_query_failure_endpoints``.  This prevents a broad
    classifier relaxation from turning parameter or entitlement errors into
    repeated provider traffic.
    """

    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    jitter_fraction: float = 0.25  # +/- 25% jitter
    max_backoff_seconds: float = 60.0
    retryable_generic_query_failure_endpoints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds must be non-negative")
        if self.max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be non-negative")
        if self.jitter_fraction < 0:
            raise ValueError("jitter_fraction must be non-negative")

    def should_retry(self, exc: Exception, *, endpoint: str) -> bool:
        """Return whether ``exc`` may be retried for ``endpoint``.

        The endpoint allowlist is the only escape hatch for the otherwise
        non-retryable generic query failure.  Its classification rule ID is
        checked as well, so an unrelated internal SDK error cannot inherit
        the exception merely because it came from the same endpoint.
        """
        if isinstance(exc, ProviderError) and is_retryable(exc):
            return True
        return (
            endpoint in self.retryable_generic_query_failure_endpoints
            and isinstance(exc, ProviderSdkInternalError)
            and exc.context.get("classification_rule_id") == "QUERY_FAIL_UNCLASSIFIED"
        )

    def sleep_for(self, attempt: int) -> float:
        if attempt <= 0:
            raise ValueError("attempt must be positive")
        # Standard exponential backoff: base, 2*base, 4*base, ... .  The
        # cap applies after jitter too, so a retry can never exceed the
        # configured maximum wait.
        base = min(
            self.max_backoff_seconds,
            self.backoff_base_seconds * (2 ** (attempt - 1)),
        )
        jitter = base * self.jitter_fraction
        return min(
            self.max_backoff_seconds,
            max(0.0, base + random.uniform(-jitter, jitter)),  # noqa: S311
        )


@dataclass(frozen=True)
class TimeBudget:
    """Per-call time budget (wall clock across retries)."""

    query_timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 15.0

    def deadline(self, *, connecting: bool = False) -> float:
        return time.monotonic() + (
            self.connect_timeout_seconds if connecting else self.query_timeout_seconds
        )


def run_with_budget(
    fn: Callable[[], object],
    *,
    budget: TimeBudget,
    retry: RetryPolicy,
    endpoint: str,
    retryable: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Run fn under a wall-clock budget with class-aware bounded retries.

    Default retry policy (audit P0-03): only ProviderError subclasses in
    RETRYABLE_ERRORS (network/timeout/rate-limit) retry.  The policy may
    additionally allow the explicitly configured endpoint-specific generic
    query failure.  Raw exceptions and other non-retryable typed errors
    propagate IMMEDIATELY so their true class is never masked by a
    budget-exhaustion timeout.
    """
    is_retryable_exc = retryable or (lambda exc: retry.should_retry(exc, endpoint=endpoint))
    deadline = budget.deadline()
    attempt = 0
    last_exc: Exception | None = None
    while True:
        # A sleep implementation may overshoot its requested duration.  Do
        # not start another native SDK call once the retry budget has ended.
        if attempt > 0 and time.monotonic() >= deadline:
            break
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - boundary
            last_exc = exc
            if not is_retryable_exc(exc):
                raise
            attempt += 1
            if attempt > retry.max_retries:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep(min(retry.sleep_for(attempt), remaining))
    # The endpoint-specific generic query-failure exception is allowed to
    # retry only as a controlled policy exception.  If it remains broken,
    # preserve its true class instead of relabeling a persistent server/SDK
    # response as a timeout; attach the retry outcome for the audit trail.
    if (
        isinstance(last_exc, ProviderSdkInternalError)
        and last_exc.context.get("classification_rule_id") == "QUERY_FAIL_UNCLASSIFIED"
    ):
        last_exc.context.update(
            {
                "retry_exhausted": True,
                "retry_attempts": attempt,
                "retry_budget_seconds": budget.query_timeout_seconds,
            }
        )
        raise last_exc
    raise ProviderTimeoutError(
        f"{endpoint}: budget exhausted after {attempt} attempt(s): {last_exc}",
        context={
            "attempts": attempt,
            "budget_seconds": budget.query_timeout_seconds,
            "last_error_class": type(last_exc).__name__ if last_exc else None,
            "last_error_rule_id": (
                last_exc.context.get("classification_rule_id")
                if isinstance(last_exc, ProviderError)
                else None
            ),
        },
    ) from last_exc


def _default_retryable(exc: Exception) -> bool:
    if isinstance(exc, ProviderError):
        return is_retryable(exc)
    # raw SDK exceptions: classify happens in the provider layer BEFORE
    # reaching here; a raw exception at this level is a programming error
    # and must not retry (audit P0-03: no silent retry of unknowns).
    return False
