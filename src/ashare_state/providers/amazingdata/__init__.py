"""AmazingData provider package (task book section 3.1).

Layout:
    errors.py        typed provider error layer + SDK error classification
    sdk_loader.py    lazy import + runtime identity probe
    stdout_capture.py fd-level SDK stdout isolation (Token never escapes)
    session.py       login/logout lifecycle + scrubbed account profile
    capability.py    capability registry (CANDIDATE discipline)
    timeout.py       time budgets + bounded retry with jitter
    dto.py           provider-normalized DTOs (faithful provider fields)
    provider.py      facade: every SDK exchange -> typed + budgeted + recorded
"""

from ashare_state.providers.amazingdata.capability import (
    CAPABILITY_REGISTRY,
    Capability,
    CapabilityStatus,
)
from ashare_state.providers.amazingdata.errors import (
    ProviderAuthError,
    ProviderEmptyResultError,
    ProviderError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderSchemaError,
    ProviderSdkInternalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    classify_sdk_error,
    wrap_sdk_call,
)
from ashare_state.providers.amazingdata.provider import AmazingDataProvider, RawEnvelope
from ashare_state.providers.amazingdata.session import AccountProfile, AmazingDataSession
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget, run_with_budget

__all__ = [
    "CAPABILITY_REGISTRY",
    "AmazingDataProvider",
    "AmazingDataSession",
    "AccountProfile",
    "Capability",
    "CapabilityStatus",
    "ProviderAuthError",
    "ProviderEmptyResultError",
    "ProviderError",
    "ProviderNetworkError",
    "ProviderPermissionError",
    "ProviderRateLimitError",
    "ProviderSchemaError",
    "ProviderSdkInternalError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RawEnvelope",
    "RetryPolicy",
    "TimeBudget",
    "classify_sdk_error",
    "run_with_budget",
    "wrap_sdk_call",
]
