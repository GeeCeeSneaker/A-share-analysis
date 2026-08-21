"""Provider registry: name -> provider instance + capability lookup.

M0 registers only the deterministic Mock fixture provider. Real adapters
register themselves at enablement time (P0a for AmazingData).
"""

from __future__ import annotations

from typing import Any

from ashare_state.providers.base import ProviderUnavailableError


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, name: str, provider: Any) -> None:
        if name in self._providers:
            msg = f"provider {name!r} already registered"
            raise ValueError(msg)
        self._providers[name] = provider

    def get(self, name: str) -> Any:
        if name not in self._providers:
            msg = (
                f"provider {name!r} is not available; installed providers: "
                f"{sorted(self._providers)}"
            )
            raise ProviderUnavailableError(msg)
        return self._providers[name]

    def available(self) -> list[str]:
        return sorted(self._providers)


_default_registry = ProviderRegistry()


def default_registry() -> ProviderRegistry:
    return _default_registry
