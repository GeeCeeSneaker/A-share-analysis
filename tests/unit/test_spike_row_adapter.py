"""Regression tests for native AmazingData row shapes in spike validation."""

from __future__ import annotations

from ashare_state.spike import validators
from ashare_state.spike.golden_router import DomainData, validate_case_in_domain
from ashare_state.spike.model import CaseResult
from ashare_state.spike.probes import _observe_units
from ashare_state.spike.row_adapter import date_key, provider_symbol, row_date


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

    def test_timestamp_and_date_keys_normalize_to_yyyymmdd(self):
        row = {"kline_time": "2020-01-02 09:30:00"}
        assert date_key(row["kline_time"]) == "20200102"
        assert row_date(row, "KLINE_TIME", "kline_time") == "20200102"


class TestNativeRowsReachValidators:
    def test_golden_comparison_accepts_full_market_code(self):
        case = _case("golden_st_transition", "600000.SH", "20240102", {"IS_ST_SEC": False})
        out = validators.validate_golden_cases([case], [_native_status()])[0]
        assert out.result is CaseResult.VALIDATED_PASS

    def test_st_facts_accept_full_market_code(self):
        facts = [validators.GoldenSTFact("600518.SH", "2024-01-02", expected_is_st=True)]
        row = {
            "MARKET_CODE": "600518.SH",
            "TRADE_DATE": "2024-01-02",
            "IS_ST_SEC": 1,
            "IS_SUSP_SEC": 0,
        }
        out = validators.validate_st_suspend_flags([row], golden_facts=facts)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_limit_validation_accepts_full_market_code(self):
        from ashare_state.spike.trading_rule import load_active_rules

        book, _manifest = load_active_rules()
        out = validators.validate_limit_rule([_native_status()], book=book)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_router_exact_status_match_accepts_native_market_code(self):
        from ashare_state.spike.trading_rule import load_active_rules

        case = _case("golden_limit_regime", "600000.SH", "20240102", {"PRICE_HIGH_LMT_RATE": 0.1})
        data = DomainData(
            domain="LIMIT_PIT_RULE",
            status_rows=[_native_status()],
            hist_code_rows=[{"SECURITY_CODE": "600000", "LISTING_DATE": "19991110"}],
            calendar_days=[20240102],
        )
        book, _manifest = load_active_rules()
        out = validate_case_in_domain(case, data, rule_book=book)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_delisted_golden_accepts_scalar_code_list(self):
        case = _case("golden_delisted", "000540.SZ", "20230630", {"IS_LISTED": "3"})
        data = DomainData(domain="DELISTED_MASTER", hist_code_rows=[{"value": "000540.SZ"}])
        out = validate_case_in_domain(case, data)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_lowercase_daily_bar_fields_are_observed(self):
        rows = [{"close": 10.0, "volume": 100.0, "amount": 1000.0}]
        assert _observe_units(rows) == {"volume": "shares", "amount": "CNY"}
