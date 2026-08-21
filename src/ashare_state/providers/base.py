"""Provider protocols (V1.3.2 section 7.7) and DTOs.

Providers are dumb pipes: external connection, DTOs, unit/code/time
interpretation, source-level freshness/quality. NO market feature logic.

The AmazingData adapter (P0a) will lazy-import the broker SDK:
    try:
        import AmazingData  # noqa
    except ImportError:
        raise ProviderUnavailableError(...)
Core package, Mock and CI must never fail due to SDK absence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


class ProviderUnavailableError(RuntimeError):
    """Provider SDK/credentials not installed or not reachable."""


@dataclass(frozen=True)
class SecurityMasterEntry:
    """Reference data DTO (provider-normalized shape)."""

    provider_symbol: str
    exchange: str  # SSE / SZSE / BSE
    asset_type: str  # STOCK / ETF / INDEX / ...
    name: str
    list_date: date | None
    delist_date: date | None
    is_st: bool = False


@dataclass(frozen=True)
class DailyBar:
    """Daily OHLCV DTO in canonical units (shares / CNY).

    Unit conversion happens in the adapter via meta_provider_field_map,
    never in feature code.
    """

    provider_symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    volume_shares: int
    amount_cny: float


@runtime_checkable
class ReferenceDataProvider(Protocol):
    def capabilities(self) -> set[str]: ...

    def get_security_master(
        self, start: date | None = None, end: date | None = None
    ) -> list[SecurityMasterEntry]: ...

    def get_trade_calendar(self, start: date, end: date) -> list[tuple[date, bool]]: ...


@runtime_checkable
class BatchMarketDataProvider(Protocol):
    def get_daily_bars(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> list[DailyBar]: ...


@runtime_checkable
class IntradayHistoryProvider(Protocol):
    def get_minute_bars(self, start: date, end: date, symbols: list[str] | None = None) -> list: ...

    def get_historical_snapshots(
        self, start: date, end: date, symbols: list[str] | None = None
    ) -> list: ...


@runtime_checkable
class RealtimeMarketDataProvider(Protocol):
    def subscribe_l1(self, symbols_or_markets: object, callback: object) -> None: ...

    def subscribe_l2(self, symbols_or_markets: object, callback: object) -> None: ...

    def health(self) -> dict[str, object]: ...
