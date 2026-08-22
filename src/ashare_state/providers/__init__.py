"""Provider layer: shared error taxonomy, protocols, registry, adapters."""

from ashare_state.providers.base import (
    DailyBar,
    SecurityMasterEntry,
)
from ashare_state.providers.errors import (
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
    is_retryable,
)
from ashare_state.providers.registry import ProviderRegistry, default_registry

__all__ = [
    "DailyBar",
    "ProviderAuthError",
    "ProviderEmptyResultError",
    "ProviderError",
    "ProviderNetworkError",
    "ProviderPermissionError",
    "ProviderRateLimitError",
    "ProviderRegistry",
    "ProviderSchemaError",
    "ProviderSdkInternalError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "SecurityMasterEntry",
    "default_registry",
    "is_retryable",
]
