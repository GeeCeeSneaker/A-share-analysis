"""Deterministic Mock/Fixture provider.

Drives ALL CI tests without any real SDK or credentials (M0 exit criterion).
Data is generated from a fixed seed via stable hashing - no random state,
so two clean rebuilds produce byte-identical parquet outputs.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from ashare_state.providers.base import DailyBar, SecurityMasterEntry


def _stable_float(*parts: object, low: float, high: float) -> float:
    """Map a stable hash of parts into [low, high)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    frac = int.from_bytes(digest[:8], "big") / 2**64
    return low + frac * (high - low)


class FixtureProvider:
    """Deterministic A-share-like reference + daily bar source."""

    provider_name = "mock"

    # small fixed universe: live / delisted / ST / code-reuse cases
    SECURITIES: list[dict[str, object]] = [
        {
            "symbol": "000001",
            "exchange": "SZSE",
            "name": "FIX-LIVE-A",
            "list_date": date(1991, 4, 3),
        },
        {
            "symbol": "600000",
            "exchange": "SSE",
            "name": "FIX-LIVE-B",
            "list_date": date(1990, 12, 19),
        },
        {
            "symbol": "300750",
            "exchange": "SZSE",
            "name": "FIX-LIVE-C",
            "list_date": date(2018, 6, 11),
        },
        {
            "symbol": "688981",
            "exchange": "SSE",
            "name": "FIX-LIVE-D",
            "list_date": date(2020, 7, 22),
        },
        {
            "symbol": "600070",
            "exchange": "SSE",
            "name": "FIX-DELISTED",
            "list_date": date(1997, 5, 1),
            "delist_date": date(2019, 7, 12),
        },
        {
            "symbol": "000018",
            "exchange": "SZSE",
            "name": "FIX-ST",
            "list_date": date(2004, 6, 25),
            "is_st": True,
        },
    ]

    def __init__(self, *, base_price: float = 10.0) -> None:
        self._base_price = base_price

    def capabilities(self) -> set[str]:
        return {"SECURITY_MASTER", "TRADE_CALENDAR", "DAILY_BAR"}

    def get_security_master(
        self, start: date | None = None, end: date | None = None
    ) -> list[SecurityMasterEntry]:
        entries = [
            SecurityMasterEntry(
                provider_symbol=str(s["symbol"]),
                exchange=str(s["exchange"]),
                asset_type="STOCK",
                name=str(s["name"]),
                list_date=s.get("list_date"),  # type: ignore[arg-type]
                delist_date=s.get("delist_date"),  # type: ignore[arg-type]
                is_st=bool(s.get("is_st", False)),
            )
            for s in self.SECURITIES
        ]
        return [
            e
            for e in entries
            if (start is None or (e.list_date and e.list_date >= start))
            and (end is None or (e.list_date and e.list_date <= end))
        ]

    def get_trade_calendar(self, start: date, end: date) -> list[tuple[date, bool]]:
        """Weekday calendar (no holiday logic - fixtures do not need it)."""
        out: list[tuple[date, bool]] = []
        d = start
        while d <= end:
            out.append((d, d.weekday() < 5))
            d += timedelta(days=1)
        return out

    def _is_active(self, symbol: str, d: date) -> bool:
        for s in self.SECURITIES:
            if str(s["symbol"]) == symbol:
                listed: date | None = s.get("list_date")  # type: ignore[assignment]
                delisted: date | None = s.get("delist_date")  # type: ignore[assignment]
                if listed is not None and d < listed:
                    return False
                return not (delisted is not None and d > delisted)
        return False

    def get_daily_bars(
        self,
        start: date,
        end: date,
        symbols: list[str] | None = None,
    ) -> list[DailyBar]:
        wanted = symbols or [str(s["symbol"]) for s in self.SECURITIES]
        bars: list[DailyBar] = []
        for symbol in wanted:
            prev_close = self._base_price + _stable_float(symbol, "seed", low=-1.0, high=1.0)
            d = start
            while d <= end:
                if self._is_active(symbol, d):
                    close = max(
                        0.5,
                        prev_close * (1 + _stable_float(symbol, d, "ret", low=-0.05, high=0.05)),
                    )
                    hi = close * (1 + _stable_float(symbol, d, "hi", low=0.0, high=0.02))
                    lo = close * (1 - _stable_float(symbol, d, "lo", low=0.0, high=0.02))
                    opn = lo + _stable_float(symbol, d, "open", low=0.0, high=1.0) * (hi - lo)
                    volume = int(_stable_float(symbol, d, "vol", low=1e5, high=1e7))
                    amount = close * volume
                    bars.append(
                        DailyBar(
                            provider_symbol=symbol,
                            trade_date=d,
                            open=round(opn, 4),
                            high=round(hi, 4),
                            low=round(lo, 4),
                            close=round(close, 4),
                            pre_close=round(prev_close, 4),
                            volume_shares=volume,
                            amount_cny=round(amount, 2),
                        )
                    )
                    prev_close = close
                d += timedelta(days=1)
        return bars
