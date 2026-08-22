"""Mapper strict-semantic tests (audit R2-P1-05, section 33 Mapper group)."""

from __future__ import annotations

import pytest

from ashare_state.providers.amazingdata.mapper import (
    map_daily_bar_row,
    map_security_master_row,
    map_trade_calendar,
    normalize_provider_symbol,
)
from ashare_state.providers.errors import MappingValidationError


class TestProviderSymbolNormalizer:
    def test_bare_code_with_market(self):
        assert normalize_provider_symbol("600000", "1") == "600000.SH"
        assert normalize_provider_symbol("000001", "2") == "000001.SZ"
        assert normalize_provider_symbol("830799", "3") == "830799.BJ"

    def test_suffixed_symbol_validated_passthrough(self):
        assert normalize_provider_symbol("600000.SH") == "600000.SH"

    def test_unknown_suffix_blocks(self):
        with pytest.raises(MappingValidationError, match="unknown suffix"):
            normalize_provider_symbol("600000.XX")

    def test_bare_code_without_market_blocks(self):
        with pytest.raises(MappingValidationError, match="unknown/missing market"):
            normalize_provider_symbol("600000", None)

    def test_non_numeric_code_blocks(self):
        with pytest.raises(MappingValidationError, match="non-numeric"):
            normalize_provider_symbol("6000XX.SH")


class TestSecurityMasterMarket:
    def test_missing_market_blocks(self):
        with pytest.raises(MappingValidationError, match="MARKET_CODE"):
            map_security_master_row({"SECURITY_CODE": "600000"}, source="x")

    def test_unknown_market_blocks(self):
        with pytest.raises(MappingValidationError, match="MARKET_CODE"):
            map_security_master_row({"SECURITY_CODE": "600000", "MARKET_CODE": "9"}, source="x")

    def test_known_market_normalizes(self):
        dto = map_security_master_row({"SECURITY_CODE": "600000", "MARKET_CODE": "1"}, source="x")
        assert dto.provider_symbol == "600000.SH"


class TestDailyBarSymbolNormalized:
    def test_bare_symbol_gets_suffix(self):
        row = {
            "SECURITY_CODE": "600000",
            "MARKET_CODE": "1",
            "KLINE_TIME": 20260814,
            "OPEN_PRICE": 10.0,
            "HIGH_PRICE": 11.0,
            "LOW_PRICE": 9.0,
            "CLOSE_PRICE": 10.5,
            "VOLUME": 1000,
            "AMOUNT": 10500.0,
        }
        bar = map_daily_bar_row(row)
        assert bar.provider_symbol == "600000.SH"

    def test_no_market_blocks(self):
        row = {
            "SECURITY_CODE": "600000",
            "KLINE_TIME": 20260814,
            "OPEN_PRICE": 10.0,
            "HIGH_PRICE": 11.0,
            "LOW_PRICE": 9.0,
            "CLOSE_PRICE": 10.5,
            "VOLUME": 1000,
            "AMOUNT": 10500.0,
        }
        with pytest.raises(MappingValidationError, match="market"):
            map_daily_bar_row(row)


class TestStrictTradeCalendar:
    def test_valid_days_pass(self):
        dto = map_trade_calendar("SH", [20260810, 20260811])
        assert len(dto.trading_days) == 2

    def test_one_bad_date_quarantines_whole_payload(self):
        with pytest.raises(MappingValidationError, match="whole payload quarantined"):
            map_trade_calendar("SH", [20260810, "garbage", 20260811])
