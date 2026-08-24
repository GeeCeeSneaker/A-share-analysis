"""Spike target: the SINGLE SDK access path for all probes (R2-P0-02).

Real runs go through the hardened production adapter:

    AmazingDataSession -> AmazingDataProvider(use_mode=ProviderUseMode.SPIKE)

Dry runs use FakeTarget (framework self-test) and are physically
isolated under data/spike/dry-run/<run-id>/ - they can never enter a
production verdict (RunStore.assert_verdict_eligible).

No probe may import the SDK directly.

CR-1.1 (audit R4-A2.3 section 3.2-A): every target exposes an EXPLICIT
``*_exchange`` API returning the ProviderExchange. Business convenience
methods keep returning payloads, but probes / RawWriter / audit paths
MUST consume the exchange variants - the runtime never reverse-searches
``provider.last_envelopes`` for lineage (that list is diagnostic-only).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Protocol

from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
    RawEnvelope,
)
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.errors import ProviderUnavailableError
from ashare_state.providers.exchange import ProviderExchange


class SpikeTarget(Protocol):
    """The call surface probes are allowed to use (SDK manual surface).

    Each business method has an ``*_exchange`` twin returning the explicit
    ProviderExchange (CR-1.1); the payload methods remain as convenience.
    """

    # explicit exchange surface (probes / RawWriter consume THIS)
    def get_code_list_exchange(self, security_type: str | None = None) -> Any: ...
    def get_hist_code_list_exchange(
        self, security_type: str, start_date: int, end_date: int
    ) -> Any: ...
    def get_stock_basic_exchange(self, code_list: list[str]) -> Any: ...
    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> Any: ...
    def get_adj_factor_exchange(self, code_list: list[str]) -> Any: ...
    def get_calendar_exchange(self, market: str = "SH") -> Any: ...
    def query_kline_exchange(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        kline_type: str,
    ) -> Any: ...

    # payload convenience surface
    def get_code_list(self, security_type: str | None = None) -> Any: ...
    def get_hist_code_list(self, security_type: str, start_date: int, end_date: int) -> Any: ...
    def get_stock_basic(self, code_list: list[str]) -> Any: ...
    def get_history_stock_status(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> Any: ...
    def get_adj_factor(self, code_list: list[str]) -> Any: ...
    def get_calendar(self, market: str = "SH") -> Any: ...
    def query_kline(
        self, code_list: list[str], *, begin_date: int, end_date: int, kline_type: str
    ) -> Any: ...
    def identity(self) -> dict[str, Any]: ...


class RealTarget:
    """Wraps AmazingDataProvider(use_mode=SPIKE) - the ONLY real path."""

    def __init__(self, session: AmazingDataSession) -> None:
        self.provider = AmazingDataProvider(session, use_mode=ProviderUseMode.SPIKE)

    # ---- explicit exchange surface (CR-1.1 audit section 3.2-A) ----
    def get_code_list_exchange(self, security_type: str | None = None) -> ProviderExchange:
        return self.provider.get_code_list_exchange(security_type)

    def get_hist_code_list_exchange(
        self, security_type: str, start_date: int, end_date: int
    ) -> ProviderExchange:
        return self.provider.get_hist_code_list_exchange(
            security_type=security_type, start_date=start_date, end_date=end_date
        )

    def get_stock_basic_exchange(self, code_list: list[str]) -> ProviderExchange:
        return self.provider.get_stock_basic_exchange(code_list)

    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> ProviderExchange:
        return self.provider.get_history_stock_status_exchange(
            start_date=start_date, end_date=end_date, code_list=code_list
        )

    def get_adj_factor_exchange(self, code_list: list[str]) -> ProviderExchange:
        return self.provider.get_adj_factor_exchange(code_list)

    def get_calendar_exchange(self, market: str = "SH") -> ProviderExchange:
        return self.provider.get_calendar_exchange(market)

    def query_kline_exchange(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        kline_type: str,
    ) -> ProviderExchange:
        return self.provider.query_kline_exchange(
            code_list=code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
        )

    # ---- payload convenience surface ----
    def get_code_list(self, security_type: str | None = None) -> Any:
        return self.get_code_list_exchange(security_type).payload

    def get_hist_code_list(self, security_type: str, start_date: int, end_date: int) -> Any:
        return self.get_hist_code_list_exchange(security_type, start_date, end_date).payload

    def get_stock_basic(self, code_list: list[str]) -> Any:
        return self.get_stock_basic_exchange(code_list).payload

    def get_history_stock_status(self, start_date: int, end_date: int, code_list: list[str]) -> Any:
        return self.get_history_stock_status_exchange(start_date, end_date, code_list).payload

    def get_adj_factor(self, code_list: list[str]) -> Any:
        return self.get_adj_factor_exchange(code_list).payload

    def get_calendar(self, market: str = "SH") -> Any:
        return self.get_calendar_exchange(market).payload

    def query_kline(
        self, code_list: list[str], *, begin_date: int, end_date: int, kline_type: str
    ) -> Any:
        return self.query_kline_exchange(
            code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
        ).payload

    def identity(self) -> dict[str, Any]:
        identity = self.provider.identity
        profile = self.provider.session.profile
        return {
            "sdk_version": identity.sdk_version if identity else None,
            "runtime_version": identity.tgw_runtime_version if identity else None,
            "account_profile_id": profile.account_profile_id,
            # R3-P0-11: REAL permission codes from the parsed logon profile
            "permission_codes": profile.permission_codes,
        }


# --------------------------------------------------------------------- fake

#: fake trading calendar window (weekdays only - a deterministic stand-in
#: for the SDK calendar; must cover the golden v3 case dates 2022-2023)
_FAKE_CAL_START = date(2022, 1, 4)
_FAKE_CAL_END = date(2023, 12, 29)


def _fake_trading_days() -> list[int]:
    days: list[int] = []
    current = _FAKE_CAL_START
    while current <= _FAKE_CAL_END:
        if current.weekday() < 5:
            days.append(int(current.strftime("%Y%m%d")))
        current += timedelta(days=1)
    return days


_FAKE_CALENDAR = _fake_trading_days()

#: deterministic fake quote base per symbol: (preclose, up_rate, is_st)
_FAKE_QUOTES: dict[str, tuple[float, float, int]] = {
    "600519.SH": (1800.0, 0.10, 0),
    "600036.SH": (35.0, 0.10, 0),
    "600000.SH": (10.0, 0.10, 0),
    "000001.SZ": (15.0, 0.10, 0),
    "600518.SH": (10.0, 0.05, 1),  # ST main board: +/-5%
    "835185.BJ": (10.0, 0.30, 0),  # BSE: +/-30%
}

#: fake ex-dividend events (symbol -> [(ex_date, factor)])
_FAKE_ADJ_EVENTS: dict[str, list[tuple[int, float]]] = {
    "600519.SH": [(20220630, 0.9737), (20230627, 0.9714)],
}

#: fake closes around ex dates (symbol -> {date: close})
_FAKE_CLOSES: dict[str, dict[int, float]] = {
    "600519.SH": {
        20220629: 1900.0,
        20220630: 1850.0,
        20220701: 1860.0,
        20230626: 1750.0,
        20230627: 1700.0,
        20230628: 1710.0,
    },
}

#: fake historical security master rows (survivorship evidence included)
_FAKE_HIST_ROWS: list[dict[str, Any]] = [
    {
        "SECURITY_CODE": "600070",
        "MARKET_CODE": "1",
        "IS_LISTED": "3",  # terminated - survivorship evidence
        "DELISTING_DATE": "20190712",
        "LISTING_DATE": "19970501",
    },
    {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "IS_LISTED": "1",
        "LISTING_DATE": "19901219",
    },
    {
        "SECURITY_CODE": "600519",
        "MARKET_CODE": "1",
        "IS_LISTED": "1",
        "LISTING_DATE": "20010827",
    },
    {
        "SECURITY_CODE": "600036",
        "MARKET_CODE": "1",
        "IS_LISTED": "1",
        "LISTING_DATE": "20020409",
    },
    {
        "SECURITY_CODE": "600518",
        "MARKET_CODE": "1",
        "IS_LISTED": "1",
        "LISTING_DATE": "20010430",
    },
    {
        "SECURITY_CODE": "835185",
        "MARKET_CODE": "3",  # BJ
        "IS_LISTED": "1",
        "LISTING_DATE": "20211115",  # BSE opening migration
    },
]


def _fake_exchange(
    endpoint: str,
    dataset: str,
    payload: Any,
    *,
    row_count: int | None = None,
) -> ProviderExchange:
    """Deterministic fake exchange: every FakeTarget call produces a REAL
    ProviderExchange (own request_id), so the dry-run exercises the SAME
    RawWriter evidence pipeline as formal runs (CR-1.1)."""
    if row_count is not None:
        count: int = row_count
    elif hasattr(payload, "__len__"):
        count = len(payload)
    else:
        count = 1
    env = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=str(uuid.uuid4()),
        requested_at="2026-08-24T00:00:00+00:00",
        received_at="2026-08-24T00:00:01+00:00",
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TRIAL_SIMULATION_FAKE",
        row_count=count if isinstance(count, int) else 0,
    )
    return ProviderExchange(envelope=env, payload=payload)


class FakeTarget:
    """Deterministic fake for DRY_RUN framework validation only.

    Produces clearly-marked FAKE payloads shaped like the documented SDK
    responses so validators/probes/catalog/reporting are exercised end to
    end WITHOUT any network or credential. Every call returns a REAL
    ProviderExchange so dry-run covers the explicit-exchange RawWriter
    pipeline (CR-1.1).
    """

    def __init__(self) -> None:
        self._call_log: list[str] = []

    def _mark(self, method: str) -> None:
        self._call_log.append(method)

    def identity(self) -> dict[str, Any]:
        return {
            "sdk_version": "FAKE-1.1.9",
            "runtime_version": "FAKE-V4.3.0",
            "account_profile_id": "TRIAL_SIMULATION_FAKE",
            "permission_codes": "3|4|32|33",
        }

    # ------------------------------------------------ exchange surface
    def get_code_list_exchange(self, security_type: str | None = None) -> ProviderExchange:
        self._mark("get_code_list")
        return _fake_exchange(
            "BaseData.get_code_list", "code_list", ["600519.SH", "600000.SH", "000001.SZ"]
        )

    def get_hist_code_list_exchange(
        self, security_type: str, start_date: int, end_date: int
    ) -> ProviderExchange:
        self._mark("get_hist_code_list")
        return _fake_exchange("BaseData.get_hist_code_list", "hist_code_list", _FAKE_HIST_ROWS)

    def get_stock_basic_exchange(self, code_list: list[str]) -> ProviderExchange:
        self._mark("get_stock_basic")
        rows = [
            {"SECURITY_CODE": code.split(".")[0], "IS_LISTED": "1"} for code in code_list
        ]
        return _fake_exchange("InfoData.get_stock_basic", "stock_basic", rows)

    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> ProviderExchange:
        self._mark("get_history_stock_status")
        rows = self._status_rows(start_date, end_date, code_list)
        return _fake_exchange("InfoData.get_history_stock_status", "history_stock_status", rows)

    def get_adj_factor_exchange(self, code_list: list[str]) -> ProviderExchange:
        self._mark("get_adj_factor")
        rows: list[dict[str, Any]] = []
        for code in code_list:
            for ex_date, factor in _FAKE_ADJ_EVENTS.get(code, [(20240615, 1.05)]):
                rows.append(
                    {
                        "SECURITY_CODE": code.split(".")[0],
                        "EX_DATE": str(ex_date),
                        "EX_FACTOR": factor,
                    }
                )
        return _fake_exchange("BaseData.get_adj_factor", "adj_factor", rows)

    def get_calendar_exchange(self, market: str = "SH") -> ProviderExchange:
        self._mark("get_calendar")
        return _fake_exchange("BaseData.get_calendar", "trade_calendar", list(_FAKE_CALENDAR))

    def query_kline_exchange(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        kline_type: str,
    ) -> ProviderExchange:
        self._mark("query_kline")
        rows = self._kline_rows(code_list, begin_date, end_date)
        return _fake_exchange("MarketData.query_kline", "daily_bar", rows)

    # ------------------------------------------------ payload surface
    def get_code_list(self, security_type: str | None = None) -> list[str]:
        return self.get_code_list_exchange(security_type).payload

    def get_hist_code_list(
        self, security_type: str, start_date: int, end_date: int
    ) -> list[dict[str, Any]]:
        return self.get_hist_code_list_exchange(security_type, start_date, end_date).payload

    def get_stock_basic(self, code_list: list[str]) -> list[dict[str, Any]]:
        return self.get_stock_basic_exchange(code_list).payload

    def get_history_stock_status(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> list[dict[str, Any]]:
        return self.get_history_stock_status_exchange(start_date, end_date, code_list).payload

    def get_adj_factor(self, code_list: list[str]) -> list[dict[str, Any]]:
        return self.get_adj_factor_exchange(code_list).payload

    def get_calendar(self, market: str = "SH") -> list[int]:
        return self.get_calendar_exchange(market).payload

    def query_kline(
        self, code_list: list[str], *, begin_date: int, end_date: int, kline_type: str
    ) -> list[dict[str, Any]]:
        return self.query_kline_exchange(
            code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
        ).payload

    # ------------------------------------------------ data synthesis
    @staticmethod
    def _status_rows(
        start_date: int, end_date: int, code_list: list[str]
    ) -> list[dict[str, Any]]:
        days = [d for d in _FAKE_CALENDAR if start_date <= d <= end_date]
        if not days:
            # out-of-calendar sample dates still produce ONE end-date row so
            # structural probes have data (dry-run smoke; clearly FAKE)
            days = [end_date]
        rows: list[dict[str, Any]] = []
        for code in code_list:
            base = _FAKE_QUOTES.get(code, (10.0, 0.10, 0))
            pre, rate, is_st = base
            for day in days:
                row: dict[str, Any] = {
                    "MARKET_CODE": {"SH": "1", "SZ": "2", "BJ": "3"}.get(
                        code.split(".")[1] if "." in code else "SH", "1"
                    ),
                    "SECURITY_CODE": code.split(".")[0],
                    "TRADE_DATE": str(day),
                    "PRECLOSE": pre,
                    "HIGH_LIMITED": round(pre * (1 + rate), 2),
                    "LOW_LIMITED": round(pre * (1 - rate), 2),
                    "IS_ST_SEC": is_st,
                    "IS_SUSP_SEC": 0,
                }
                # ex-dividend marker days for CA golden fixtures
                if code == "600519.SH" and day in (20220630, 20230627):
                    row["IS_WD_SEC"] = 1
                rows.append(row)
        return rows

    @staticmethod
    def _kline_rows(
        code_list: list[str], begin_date: int, end_date: int
    ) -> list[dict[str, Any]]:
        days = [d for d in _FAKE_CALENDAR if begin_date <= d <= end_date]
        if not days:
            days = [end_date]
        rows: list[dict[str, Any]] = []
        for code in code_list:
            closes = _FAKE_CLOSES.get(code, {})
            base = _FAKE_QUOTES.get(code, (10.0, 0.10, 0))[0]
            for day in days:
                close = closes.get(day, base)
                rows.append(
                    {
                        "SECURITY_CODE": code,
                        "KLINE_TIME": day,
                        "OPEN_PRICE": close * 0.99,
                        "HIGH_PRICE": close * 1.02,
                        "LOW_PRICE": close * 0.98,
                        "CLOSE_PRICE": close,
                        "PRE_CLOSE_PRICE": base,
                        "VOLUME": 1000000,  # shares (documented unit map placeholder)
                        "AMOUNT": close * 1000000,  # CNY - keeps amount/volume ~ close
                    }
                )
        return rows


def make_real_target(session: AmazingDataSession) -> RealTarget:
    return RealTarget(session)


def make_dry_run_target() -> FakeTarget:
    return FakeTarget()


__all__ = [
    "FakeTarget",
    "RealTarget",
    "SpikeTarget",
    "ProviderUnavailableError",
    "make_dry_run_target",
    "make_real_target",
]
