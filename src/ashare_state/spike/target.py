"""Spike target: the SINGLE SDK access path for all probes (R2-P0-02).

Real runs go through the hardened production adapter:

    AmazingDataSession -> AmazingDataProvider(use_mode=ProviderUseMode.SPIKE)

Dry runs use FakeTarget (framework self-test) and are physically
isolated under data/spike/dry-run/<run-id>/ - they can never enter a
production verdict (RunStore.assert_verdict_eligible).

No probe may import the SDK directly.
"""

from __future__ import annotations

from typing import Any, Protocol

from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.errors import ProviderUnavailableError


class SpikeTarget(Protocol):
    """The call surface probes are allowed to use (SDK manual surface)."""

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

    # passthroughs: thin, no retry/error logic of their own (adapter owns it)
    def get_code_list(self, security_type: str | None = None) -> Any:
        return self.provider.get_code_list(security_type)

    def get_hist_code_list(self, security_type: str, start_date: int, end_date: int) -> Any:
        return self.provider.get_hist_code_list(
            security_type=security_type, start_date=start_date, end_date=end_date
        )

    def get_stock_basic(self, code_list: list[str]) -> Any:
        return self.provider.get_stock_basic(code_list)

    def get_history_stock_status(self, start_date: int, end_date: int, code_list: list[str]) -> Any:
        return self.provider.get_history_stock_status(
            start_date=start_date, end_date=end_date, code_list=code_list
        )

    def get_adj_factor(self, code_list: list[str]) -> Any:
        return self.provider.get_adj_factor(code_list)

    def get_calendar(self, market: str = "SH") -> Any:
        return self.provider.get_calendar(market)

    def query_kline(
        self, code_list: list[str], *, begin_date: int, end_date: int, kline_type: str
    ) -> Any:
        return self.provider.query_kline(
            code_list=code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
        )

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


class FakeTarget:
    """Deterministic fake for DRY_RUN framework validation only.

    Produces clearly-marked FAKE payloads shaped like the documented SDK
    responses so validators/probes/catalog/reporting are exercised end to
    end WITHOUT any network or credential.
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

    def get_code_list(self, security_type: str | None = None) -> list[str]:
        self._mark("get_code_list")
        return ["600000.SH", "000001.SZ", "830799.BJ"]

    def get_hist_code_list(
        self, security_type: str, start_date: int, end_date: int
    ) -> list[dict[str, Any]]:
        self._mark("get_hist_code_list")
        return [
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
        ]

    def get_stock_basic(self, code_list: list[str]) -> list[dict[str, Any]]:
        self._mark("get_stock_basic")
        return [{"SECURITY_CODE": code.split(".")[0], "IS_LISTED": "1"} for code in code_list]

    def get_history_stock_status(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> list[dict[str, Any]]:
        self._mark("get_history_stock_status")
        rows = []
        for code in code_list:
            bare = code.split(".")[0]
            rows.append(
                {
                    "MARKET_CODE": {"SH": "1", "SZ": "2", "BJ": "3"}.get(code.split(".")[1], "1"),
                    "SECURITY_CODE": bare,
                    "TRADE_DATE": str(end_date),
                    "PRECLOSE": 10.0,
                    "HIGH_LIMITED": 11.0,
                    "LOW_LIMITED": 9.0,
                    "IS_ST_SEC": 0,
                    "IS_SUSP_SEC": 0,
                }
            )
        return rows

    def get_adj_factor(self, code_list: list[str]) -> list[dict[str, Any]]:
        self._mark("get_adj_factor")
        return [
            {"SECURITY_CODE": code.split(".")[0], "EX_DATE": "20240615", "EX_FACTOR": 1.05}
            for code in code_list
        ]

    def get_calendar(self, market: str = "SH") -> list[int]:
        self._mark("get_calendar")
        return [20260810, 20260811, 20260812, 20260813, 20260814]

    def query_kline(
        self, code_list: list[str], *, begin_date: int, end_date: int, kline_type: str
    ) -> list[dict[str, Any]]:
        self._mark("query_kline")
        return [
            {
                "SECURITY_CODE": code,
                "KLINE_TIME": end_date,
                "OPEN_PRICE": 10.0,
                "HIGH_PRICE": 10.5,
                "LOW_PRICE": 9.8,
                "CLOSE_PRICE": 10.2,
                "PRE_CLOSE_PRICE": 10.0,
                "VOLUME": 1000000,  # shares (documented unit map placeholder)
                "AMOUNT": 10200000.0,  # CNY
            }
            for code in code_list
        ]


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
