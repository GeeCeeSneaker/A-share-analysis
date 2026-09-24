"""Issue #90 regressions for status keys, duplicates, and routing semantics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from runpy import run_path
from typing import Any

import pytest

from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.spike.row_adapter import ProviderRowShapeError, canonical_status_view

_ROOT = Path(__file__).parents[2]


def _status_row(symbol: str, day: str) -> dict[str, object]:
    return {
        "MARKET_CODE": symbol,
        "TRADE_DATE": day,
        "IS_ST_SEC": 0,
        "IS_SUSP_SEC": 0,
    }


class TestStatusNaturalKeyBoundary:
    @pytest.mark.parametrize(
        ("symbol", "market", "exchange"),
        [
            ("600000.SH", "1", "SH"),
            ("000001.SZ", "2", "SZ"),
        ],
    )
    def test_keyed_sh_sz_rows_form_exactly_one_natural_key(self, symbol, market, exchange):
        rows = canonical_status_view([_status_row(symbol, "2024-01-02")])

        assert len(rows) == 1
        assert (
            rows[0]["PROVIDER_SYMBOL"],
            rows[0]["TRADE_DATE"],
            rows[0]["MARKET_CODE"],
            rows[0]["EXCHANGE_CODE"],
        ) == (symbol, "20240102", market, exchange)

    def test_missing_both_identity_and_date_fails_closed(self):
        row = {
            "MARKET_CODE": None,
            "TRADE_DATE": None,
            "IS_ST_SEC": 0,
            "PRICE_HIGH_LMT_RATE": 0.1,
        }

        with pytest.raises(ProviderRowShapeError):
            canonical_status_view([row])

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            (
                {"SECURITY_CODE": "600000", "TRADE_DATE": "20240102"},
                "exchange-qualified identity",
            ),
            (
                {"MARKET_CODE": "600000.SH", "TRADE_DATE": None},
                "missing or invalid TRADE_DATE",
            ),
        ],
    )
    def test_either_one_sided_missing_key_fails_closed(self, row, message):
        with pytest.raises(ProviderRowShapeError, match=message):
            canonical_status_view([row])

    def test_empty_response_stays_empty_and_is_not_a_negative_fact(self):
        assert canonical_status_view([]) == []

    def test_duplicate_symbol_date_key_fails_closed(self):
        with pytest.raises(ProviderRowShapeError, match="duplicates canonical natural key"):
            canonical_status_view(
                [
                    _status_row("600000.SH", "2024-01-02"),
                    _status_row("600000.SH", "20240102"),
                ]
            )


@dataclass
class _FakeSession:
    profile: Any = None
    lifecycle: Any = None

    def __post_init__(self) -> None:
        from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState

        self.lifecycle = SdkLifecycle()
        self.lifecycle.transition(SdkLifecycleState.SESSION_READY, reason="issue #90 fake session")


@dataclass
class _FakeIdentity:
    sdk_version: str = "fake-1.1.9"
    tgw_runtime_version: str = "fake-runtime"


def _provider_with_history_result(
    calls: list[dict[str, object]], payload: Any
) -> AmazingDataProvider:
    from ashare_state.providers.amazingdata.session import AccountProfile

    class FakeInfo:
        def get_history_stock_status(
            self,
            code_list: list[str],
            *,
            begin_date: int,
            end_date: int,
            is_local: bool,
        ) -> Any:
            calls.append(
                {
                    "code_list": list(code_list),
                    "begin_date": begin_date,
                    "end_date": end_date,
                    "is_local": is_local,
                }
            )
            return payload

    class FakeSdk:
        InfoData = FakeInfo

    provider = AmazingDataProvider(
        _FakeSession(profile=AccountProfile()),
        identity=_FakeIdentity(),
        use_mode=ProviderUseMode.SPIKE,
    )
    provider.session.__dict__["sdk"] = FakeSdk()
    return provider


def test_sh_sz_facade_forwards_one_bounded_mixed_exchange_call_without_rechunking():
    symbols = ["600000.SH", "000001.SZ"]
    returned = {"600000.SH": [], "000001.SZ": []}
    calls: list[dict[str, object]] = []
    provider = _provider_with_history_result(calls, returned)

    exchange = provider.get_history_stock_status_exchange(20240102, 20240131, symbols)

    assert calls == [
        {
            "code_list": symbols,
            "begin_date": 20240102,
            "end_date": 20240131,
            "is_local": False,
        }
    ]
    assert exchange.payload == returned
    assert exchange.envelope.request_params == calls[0]


def test_bse_probe_uses_current_code_verbatim_and_preserves_empty_response():
    probe = run_path(str(_ROOT / "scripts" / "spike" / "capability_closure_probe.py"))
    symbols = probe["_BSE_SYMBOLS"]
    assert symbols == ["920185.BJ"]

    returned = {"920185.BJ": []}
    calls: list[dict[str, object]] = []
    provider = _provider_with_history_result(calls, returned)
    exchange = provider.get_history_stock_status_exchange(20220101, 20221231, symbols)

    assert calls == [
        {
            "code_list": ["920185.BJ"],
            "begin_date": 20220101,
            "end_date": 20221231,
            "is_local": False,
        }
    ]
    assert exchange.payload == returned
