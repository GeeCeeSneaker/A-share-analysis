"""Retry budget for provider calls (task book section 4, audit P0-03).

Honest semantics (audit P0-03): this is a RETRY BUDGET, not a hard
timeout. Python timers cannot cancel a blocking native SDK call; if the
SDK blocks past the deadline we can only abandon waiting at the Python
layer - the SDK thread may still be running underneath. The subprocess
isolation experiment (task book 4.2) is tracked separately; do NOT
represent query_timeout_seconds as a hard timeout in any doc.

Retry discipline (audit P0-03): errors are CLASSIFIED FIRST, then the
retry decision consults is_retryable() - ProviderPermissionError /
ProviderAuthError / ProviderSchemaError / ProviderSdkInternalError are
never retried, so a permission denial can no longer surface as a
timeout after budget exhaustion.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from ashare_state.providers.errors import ProviderError, ProviderTimeoutError, is_retryable


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry with exponential backoff and jitter."""

    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    jitter_fraction: float = 0.25  # +/- 25% jitter

    def sleep_for(self, attempt: int) -> float:
        base = self.backoff_base_seconds**attempt
        jitter = base * self.jitter_fraction
        return max(0.0, base + random.uniform(-jitter, jitter))  # noqa: S311


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
    RETRYABLE_ERRORS (network/timeout/rate-limit) retry; raw exceptions
    and non-retryable typed errors propagate IMMEDIATELY so their true
    class is never masked by a budget-exhaustion timeout.
    """
    is_retryable_exc = retryable or _default_retryable
    deadline = budget.deadline()
    attempt = 0
    last_exc: Exception | None = None
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - boundary
            last_exc = exc
            if not is_retryable_exc(exc):
                raise
            attempt += 1
            if attempt > retry.max_retries or time.monotonic() >= deadline:
                break
            sleep(retry.sleep_for(attempt))
    raise ProviderTimeoutError(
        f"{endpoint}: budget exhausted after {attempt} attempt(s): {last_exc}",
        context={"attempts": attempt, "budget_seconds": budget.query_timeout_seconds},
    ) from last_exc


def _default_retryable(exc: Exception) -> bool:
    if isinstance(exc, ProviderError):
        return is_retryable(exc)
    # raw SDK exceptions: classify happens in the provider layer BEFORE
    # reaching here; a raw exception at this level is a programming error
    # and must not retry (audit P0-03: no silent retry of unknowns).
    return False
