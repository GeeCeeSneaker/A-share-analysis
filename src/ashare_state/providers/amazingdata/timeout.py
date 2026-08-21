"""Timeout and retry policy for provider calls (task book section 4).

The SDK is known to retry internally for minutes before failing, and Python
timers do NOT necessarily cancel the underlying SDK call (task book 4.2).
This module centralizes budgets; the subprocess-isolation experiment is
recorded separately (see docs/adr/ candidates) and NOT introduced here.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from ashare_state.providers.amazingdata.errors import ProviderTimeoutError


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
    """Run fn under a wall-clock budget with bounded retries.

    NOTE (task book 4.2): if fn internally blocks past the deadline we can
    only abandon waiting at the Python layer - the SDK thread may still be
    running underneath. Callers must observe and record that experiment;
    this function never pretends the underlying call was cancelled.
    """
    _default_retryable = lambda exc: not isinstance(exc, (KeyboardInterrupt, SystemExit))  # noqa: E731
    is_retryable = retryable or _default_retryable
    deadline = budget.deadline()
    attempt = 0
    last_exc: Exception | None = None
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - boundary
            last_exc = exc
            if not is_retryable(exc):
                raise
            attempt += 1
            if attempt > retry.max_retries or time.monotonic() >= deadline:
                break
            sleep(retry.sleep_for(attempt))
    raise ProviderTimeoutError(
        f"{endpoint}: budget exhausted after {attempt} attempt(s): {last_exc}",
        context={"attempts": attempt, "budget_seconds": budget.query_timeout_seconds},
    ) from last_exc
