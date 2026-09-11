"""Regression tests for native AmazingData row shapes in spike validation."""

from __future__ import annotations

import pytest

from ashare_state.spike import validators
from ashare_state.spike.golden_router import DomainData, validate_case_in_domain
from ashare_state.spike.model import CaseResult
from ashare_state.spike.probes import _observe_units
from ashare_state.spike.row_adapter import (
    ProviderRowShapeError,
    canonical_daily_bar_view,
    canonical_status_view,
    date_key,
    key_preserving_table_rows,
    provider_symbol,
    row_date,
)
from ashare_state.spike.validators import first_applicable_trading_day


def _case(case_type: str, symbol: str, trade_date: str, expected: dict):
    return validators.GoldenCase(
        golden_case_id="NATIVE-SHAPE-1",
        case_type=case_type,
        provider_symbol=symbol,
        trade_date=trade_date,
        truth_source="test truth",
        source_ref="test source",
        expected_fields=expected,
    )


def _native_status() -> dict[str, object]:
    return {
        "MARKET_CODE": "600000.SH",
        "TRADE_DATE": "2024-01-02",
        "PRECLOSE": 10.0,
        "HIGH_LIMITED": 11.0,
        "LOW_LIMITED": 9.0,
        "IS_ST_SEC": 0,
        "IS_SUSP_SEC": 0,
    }


class TestProviderRowAdapter:
    def test_full_market_code_is_the_row_identity(self):
        assert provider_symbol({"MARKET_CODE": "600518.SH"}) == "600518.SH"

    def test_scalar_code_list_value_is_supported_explicitly(self):
        assert provider_symbol({"value": "000540.SZ"}) == "000540.SZ"

    def test_multi_column_row_never_uses_an_arbitrary_value(self):
        assert provider_symbol({"name": "example", "value": "000540.SZ"}) == ""

    def test_conflicting_code_and_market_are_rejected(self):
        assert provider_symbol({"SECURITY_CODE": "600518", "MARKET_CODE": "000001.SZ"}) == ""

    def test_full_code_and_conflicting_numeric_market_are_rejected(self):
        assert provider_symbol({"SECURITY_CODE": "600518.SH", "MARKET_CODE": "2"}) == ""

    def test_unknown_market_with_bare_code_is_rejected(self):
        assert provider_symbol({"SECURITY_CODE": "600518", "MARKET_CODE": "9"}) == ""

    def test_numeric_and_text_market_aliases_are_consistent(self):
        assert (
            provider_symbol({"SECURITY_CODE": "600518", "MARKET_CODE": "1", "market": "SH"})
            == "600518.SH"
        )

    def test_timestamp_and_date_keys_normalize_to_yyyymmdd(self):
        row = {"kline_time": "2020-01-02 09:30:00"}
        assert date_key(row["kline_time"]) == "20200102"
        assert row_date(row, "KLINE_TIME", "kline_time") == "20200102"

    def test_status_view_normalizes_sh_and_preserves_native_row(self):
        native = _native_status()
        view = canonical_status_view([native])
        assert view[0]["SECURITY_CODE"] == "600000"
        assert view[0]["MARKET_CODE"] == "1"
        assert view[0]["EXCHANGE_CODE"] == "SH"
        assert view[0]["PROVIDER_SYMBOL"] == "600000.SH"
        assert view[0]["TRADE_DATE"] == "20240102"
        assert "SECURITY_CODE" not in native

    @pytest.mark.parametrize(
        ("native_symbol", "exchange", "market"),
        [("000001.SZ", "SZ", "2"), ("835185.BJ", "BJ", "3")],
    )
    def test_status_view_covers_sz_and_bj(self, native_symbol, exchange, market):
        row = {
            "market_code": native_symbol,
            "trade_date": "2024-01-02",
            "pre_close": 10.0,
            "high_limited": 11.0,
            "low_limited": 9.0,
        }
        canonical = canonical_status_view([row])[0]
        assert canonical["SECURITY_CODE"] == native_symbol.split(".")[0]
        assert canonical["MARKET_CODE"] == market
        assert canonical["EXCHANGE_CODE"] == exchange
        assert canonical["PROVIDER_SYMBOL"] == native_symbol

    def test_status_view_rejects_bare_identity_without_exchange(self):
        with pytest.raises(ProviderRowShapeError, match="exchange-qualified identity"):
            canonical_status_view([{"SECURITY_CODE": "600000", "TRADE_DATE": "20240102"}])

    def test_status_view_skips_identity_and_date_free_non_observation_row(self):
        row = {
            "MARKET_CODE": None,
            "TRADE_DATE": None,
            "PRICE_HIGH_LMT_RATE": 0.1,
            "PRICE_LOW_LMT_RATE": 0.1,
            "IS_ST_SEC": "0",
        }
        assert canonical_status_view([row]) == []

    def test_status_view_does_not_skip_partial_observation_shape(self):
        with pytest.raises(ProviderRowShapeError, match="missing or invalid TRADE_DATE"):
            canonical_status_view([{"MARKET_CODE": "600000.SH", "TRADE_DATE": None}])

    def test_status_view_does_not_skip_unrecognized_empty_shape(self):
        with pytest.raises(ProviderRowShapeError, match="exchange-qualified identity"):
            canonical_status_view([{}])


class TestNativeRowsReachValidators:
    def test_golden_comparison_accepts_full_market_code(self):
        case = _case("golden_st_transition", "600000.SH", "20240102", {"IS_ST_SEC": False})
        out = validators.validate_golden_cases([case], canonical_status_view([_native_status()]))[0]
        assert out.result is CaseResult.VALIDATED_PASS

    def test_st_facts_accept_full_market_code(self):
        facts = [validators.GoldenSTFact("600518.SH", "2024-01-02", expected_is_st=True)]
        row = {
            "MARKET_CODE": "600518.SH",
            "TRADE_DATE": "2024-01-02",
            "IS_ST_SEC": 1,
            "IS_SUSP_SEC": 0,
        }
        out = validators.validate_st_suspend_flags(canonical_status_view([row]), golden_facts=facts)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_limit_validation_accepts_full_market_code(self):
        from ashare_state.spike.trading_rule import load_active_rules

        book, _manifest = load_active_rules()
        out = validators.validate_limit_rule(canonical_status_view([_native_status()]), book=book)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_router_exact_status_match_accepts_native_market_code(self):
        from ashare_state.spike.trading_rule import load_active_rules

        case = _case("golden_limit_regime", "600000.SH", "20240102", {"PRICE_HIGH_LMT_RATE": 0.1})
        data = DomainData(
            domain="LIMIT_PIT_RULE",
            status_rows=canonical_status_view([_native_status()]),
            hist_code_rows=[{"SECURITY_CODE": "600000", "LISTING_DATE": "19991110"}],
            calendar_days=[20240102],
        )
        book, _manifest = load_active_rules()
        out = validate_case_in_domain(case, data, rule_book=book)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_delisted_golden_keeps_scalar_code_list_nonsemantic(self):
        case = _case("golden_delisted", "000540.SZ", "20230630", {"IS_LISTED": "3"})
        data = DomainData(domain="DELISTED_MASTER", hist_code_rows=[{"value": "000540.SZ"}])
        out = validate_case_in_domain(case, data)
        assert out.result is CaseResult.MISSING
        assert out.reason_code == "DELISTED_SEMANTIC_FIELD_MISSING"

    def test_delisted_golden_accepts_provider_semantic_field(self):
        case = _case("golden_delisted", "000540.SZ", "20230630", {"IS_LISTED": "3"})
        data = DomainData(
            domain="DELISTED_MASTER",
            hist_code_rows=[{"SECURITY_CODE": "000540", "MARKET_CODE": "2", "IS_LISTED": "3"}],
        )
        out = validate_case_in_domain(case, data)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_keyed_kline_view_preserves_symbol_and_none_member(self):
        polars = pytest.importorskip("polars")
        payload = {
            "600519.SH": polars.DataFrame(
                {
                    "security_code": ["600519"],
                    "kline_time": ["2020-01-02 00:00:00"],
                    "close": [100.0],
                    "volume": [10.0],
                    "amount": [1000.0],
                }
            ),
            "000001.SZ": polars.DataFrame(
                {
                    "kline_time": ["2020-01-03 00:00:00"],
                    "close": [20.0],
                    "volume": [5.0],
                    "amount": [100.0],
                }
            ),
            "835185.BJ": None,
            "300000.SZ": polars.DataFrame(
                {"kline_time": [], "close": [], "volume": [], "amount": []}
            ),
        }
        rows = key_preserving_table_rows(payload)
        assert {row["PROVIDER_SYMBOL"] for row in rows} == {
            "600519.SH",
            "000001.SZ",
            "835185.BJ",
            "300000.SZ",
        }
        assert (
            next(row for row in rows if row["PROVIDER_SYMBOL"] == "835185.BJ")["_TABLE_NONE"]
            is True
        )
        assert (
            next(row for row in rows if row["PROVIDER_SYMBOL"] == "300000.SZ")["_TABLE_EMPTY"]
            is True
        )
        bars = canonical_daily_bar_view(rows)
        assert {row["PROVIDER_SYMBOL"] for row in bars if row.get("TRADE_DATE")} == {
            "600519.SH",
            "000001.SZ",
        }
        keyed_bare_row = next(row for row in bars if row.get("TRADE_DATE") == "20200102")
        assert keyed_bare_row["PROVIDER_SYMBOL"] == "600519.SH"

    def test_keyed_kline_view_rejects_conflicting_embedded_identity(self):
        polars = pytest.importorskip("polars")
        payload = {
            "600519.SH": polars.DataFrame(
                {
                    "security_code": ["000001.SZ"],
                    "kline_time": ["2020-01-02"],
                    "close": [100.0],
                }
            )
        }
        with pytest.raises(ProviderRowShapeError, match="identity conflict"):
            key_preserving_table_rows(payload)

    def test_lowercase_daily_bar_fields_are_observed(self):
        rows = [{"close": 10.0, "volume": 100.0, "amount": 1000.0}]
        assert _observe_units(rows) == {"volume": "shares", "amount": "CNY"}

    def test_uppercase_daily_bar_fields_are_observed(self):
        rows = [{"CLOSE_PRICE": 10.0, "VOLUME": 100.0, "AMOUNT": 1000.0}]
        assert _observe_units(rows) == {"volume": "shares", "amount": "CNY"}

    def test_lowercase_kline_time_reaches_canonical_history_date(self):
        view = canonical_daily_bar_view(
            [{"security_code": "600000.SH", "kline_time": "2020-01-02 09:30:00"}]
        )
        assert view[0]["TRADE_DATE"] == "20200102"
        assert view[0]["PROVIDER_SYMBOL"] == "600000.SH"

    def test_scalar_history_membership_does_not_prove_delisted_state(self):
        out = validators.validate_security_master_delisted([{"value": "000540.SZ"}])
        assert out.result is CaseResult.MISSING
        assert out.reason_code == "DELISTED_SEMANTIC_FIELD_MISSING"

    def test_history_baseline_uses_first_trading_session_after_new_year_holiday(self):
        calendar = [20200102, 20200103, 20200106]
        assert first_applicable_trading_day(calendar) == "20200102"
        assert (
            validators.validate_history_coverage("20200102", calendar_days=calendar).result
            is CaseResult.VALIDATED_PASS
        )
        assert (
            validators.validate_history_coverage("20200103", calendar_days=calendar).result
            is CaseResult.VALIDATED_FAIL
        )

    def test_history_fixture_can_start_at_its_market_applicability_boundary(self):
        out = validators.validate_history_coverage_by_symbol(
            {"600000.SH": "20200102", "835185.BJ": "20211115"},
            expected_symbols=["600000.SH", "835185.BJ"],
            calendar_days=[20200102, 20200103, 20211115, 20211116],
            applicable_from_by_symbol={"835185.BJ": "20211115"},
        )
        assert out.result is CaseResult.VALIDATED_PASS

    def test_empty_bse_status_stays_an_unresolved_missing_case(self):
        case = _case(
            "golden_limit_regime",
            "835185.BJ",
            "20220601",
            {"PRICE_HIGH_LMT_RATE": 0.3},
        )
        out = validate_case_in_domain(
            case,
            DomainData(domain="LIMIT_PIT_RULE", status_rows=[]),
        )
        assert out.result is CaseResult.MISSING
        assert out.reason_code == "PROVIDER_EMPTY_STATUS_UNRESOLVED"
