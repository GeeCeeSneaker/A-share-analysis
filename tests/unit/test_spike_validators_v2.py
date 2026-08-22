"""Spike validator v2 semantic tests (R3 audit section 57, Validators group)."""

from __future__ import annotations

from ashare_state.spike import validators
from ashare_state.spike.model import CaseResult
from ashare_state.spike.validators import GoldenSTFact

DOCUMENTED = {"volume": "shares", "amount": "CNY"}


def _bar_row(**overrides):
    row = {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "KLINE_TIME": 20260814,
        "OPEN_PRICE": 10.0,
        "HIGH_PRICE": 10.5,
        "LOW_PRICE": 9.8,
        "CLOSE_PRICE": 10.2,
        "VOLUME": 1000000,
        "AMOUNT": 10200000.0,
    }
    row.update(overrides)
    return row


class TestSymbolMapping:
    def test_symbol_600000_sh_passes(self):
        out = validators.validate_symbol_mapping(["600000.SH", "000001.SZ", "830799.BJ"])
        assert out.result is CaseResult.VALIDATED_PASS

    def test_bare_code_on_two_markets_is_not_an_error(self):
        """R3-P0-06: same bare code on different markets is legal."""
        out = validators.validate_symbol_mapping(["000001.SZ", "000001.SH"])
        assert out.result is CaseResult.VALIDATED_PASS

    def test_duplicate_full_symbol_fails(self):
        out = validators.validate_symbol_mapping(["600000.SH", "600000.SH"])
        assert out.result is CaseResult.VALIDATED_FAIL
        assert "duplicate" in out.actual

    def test_bare_symbol_without_market_fails(self):
        out = validators.validate_symbol_mapping(["600000"])
        assert out.result is CaseResult.VALIDATED_FAIL


class TestDailyBarUnits:
    def test_independent_sources_pass(self):
        rows = [_bar_row()]
        out = validators.validate_daily_bar_units(
            rows, documented_units=DOCUMENTED, observed_units={"volume": "shares", "amount": "CNY"}
        )
        assert out.result is CaseResult.VALIDATED_PASS

    def test_documented_vs_observed_mismatch_fails(self):
        rows = [_bar_row()]
        out = validators.validate_daily_bar_units(
            rows,
            documented_units=DOCUMENTED,
            observed_units={"volume": "hands", "amount": "CNY"},  # live scale says hands
        )
        assert out.result is CaseResult.VALIDATED_FAIL
        assert "documented" in out.actual

    def test_self_referential_pass_is_impossible(self):
        """R3-P0-07: same dict for both sides cannot pass when the numeric
        consistency rows are absent (field drift must fail)."""
        rows = [{"SECURITY_CODE": "600000", "KLINE_TIME": 20260814}]  # no OHLCV fields
        out = validators.validate_daily_bar_units(
            rows, documented_units=DOCUMENTED, observed_units=DOCUMENTED
        )
        assert out.result is CaseResult.VALIDATED_FAIL
        assert "checked_n=0" in out.actual

    def test_checked_zero_not_pass(self):
        rows = [{"SECURITY_CODE": "600000", "VOLUME": "n/a", "AMOUNT": None}]
        out = validators.validate_daily_bar_units(
            rows, documented_units=DOCUMENTED, observed_units={"volume": "shares", "amount": "CNY"}
        )
        assert out.result is CaseResult.VALIDATED_FAIL


class TestSTSuspend:
    def test_all_zero_sample_without_facts_is_observed_not_pass(self):
        """R3-P0-08: five normal stocks all 0 -> OBSERVED, never PASS."""
        rows = [
            {
                "SECURITY_CODE": f"60000{i}",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20260814",
                "IS_ST_SEC": 0,
                "IS_SUSP_SEC": 0,
            }
            for i in range(5)
        ]
        out = validators.validate_st_suspend_flags(rows)
        assert out.result is CaseResult.OBSERVED

    def test_golden_fact_mismatch_fails(self):
        rows = [
            {
                "SECURITY_CODE": "600518",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20190506",
                "IS_ST_SEC": 0,  # provider says NOT st on the *ST cap day
                "IS_SUSP_SEC": 0,
            }
        ]
        facts = [GoldenSTFact("600518.SH", "20190506", expected_is_st=True)]
        out = validators.validate_st_suspend_flags(rows, golden_facts=facts)
        assert out.result is CaseResult.VALIDATED_FAIL
        assert "ST expected True" in out.actual

    def test_golden_fact_match_passes(self):
        rows = [
            {
                "SECURITY_CODE": "600518",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20190506",
                "IS_ST_SEC": 1,
                "IS_SUSP_SEC": 0,
            }
        ]
        facts = [GoldenSTFact("600518.SH", "20190506", expected_is_st=True)]
        out = validators.validate_st_suspend_flags(rows, golden_facts=facts)
        assert out.result is CaseResult.VALIDATED_PASS


def _status_row(code: str, market: str, pre: float, up: float, down: float, st: int = 0):
    return {
        "SECURITY_CODE": code,
        "MARKET_CODE": market,
        "TRADE_DATE": "20240102",
        "PRECLOSE": pre,
        "HIGH_LIMITED": up,
        "LOW_LIMITED": down,
        "IS_ST_SEC": st,
        "IS_SUSP_SEC": 0,
        "CLOSE_PRICE": min(up, max(down, pre)),
    }


class TestLimitRule:
    def test_limit_missing_all_not_pass(self):
        """R3-P0-09: all rows missing limit fields -> FAIL (never silent pass)."""
        rows = [{"SECURITY_CODE": "600000", "MARKET_CODE": "1", "TRADE_DATE": "20240102"}]
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_FAIL

    def test_known_mainboard_limit_case(self):
        # 600000 main board: pre 10.00 -> up 11.00 / down 9.00
        rows = [_status_row("600000", "1", 10.00, 11.00, 9.00)]
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_known_star_limit_case(self):
        # 688981 STAR: pre 50.00 -> 20%: up 60.00 / down 40.00
        rows = [_status_row("688981", "1", 50.00, 60.00, 40.00)]
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_known_st_limit_case(self):
        # ST main board: pre 10.00 -> 5%: up 10.50 / down 9.50
        rows = [_status_row("600518", "1", 10.00, 10.50, 9.50, st=1)]
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_st_limit_at_10pct_fails(self):
        """ST stock priced at the 10% board rate -> regime violation."""
        rows = [_status_row("600518", "1", 10.00, 11.00, 9.00, st=1)]
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_FAIL

    def test_wrong_mainboard_limit_fails(self):
        rows = [_status_row("600000", "1", 10.00, 11.50, 8.50)]  # not 10%
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_FAIL

    def test_rounding_to_tick(self):
        # pre 9.99 -> up = round(9.99 * 1.1) = round(10.989) = 10.99
        rows = [_status_row("600000", "1", 9.99, 10.99, 8.99)]
        out = validators.validate_limit_rule(rows)
        assert out.result is CaseResult.VALIDATED_PASS


class TestAdjContinuity:
    def test_requires_price_context_for_semantic_verdict(self):
        """R3-P0-10: factors alone are OBSERVED, never PASS."""
        events = [{"SECURITY_CODE": "600000", "EX_DATE": "20240615", "EX_FACTOR": 1.05}]
        out = validators.validate_adj_continuity(events)
        assert out.result is CaseResult.OBSERVED

    def test_price_continuity_pass(self):
        events = [{"SECURITY_CODE": "600000", "EX_DATE": "20240617", "EX_FACTOR": 1.05}]
        prices = [
            {"SECURITY_CODE": "600000", "TRADE_DATE": "20240614", "CLOSE_PRICE": 10.00},
            {"SECURITY_CODE": "600000", "TRADE_DATE": "20240617", "CLOSE_PRICE": 10.51},
        ]
        out = validators.validate_adj_continuity(events, price_context=prices)
        assert out.result is CaseResult.VALIDATED_PASS

    def test_price_discontinuity_fails(self):
        events = [{"SECURITY_CODE": "600000", "EX_DATE": "20240617", "EX_FACTOR": 1.05}]
        prices = [
            {"SECURITY_CODE": "600000", "TRADE_DATE": "20240614", "CLOSE_PRICE": 10.00},
            {"SECURITY_CODE": "600000", "TRADE_DATE": "20240617", "CLOSE_PRICE": 20.00},
        ]
        out = validators.validate_adj_continuity(events, price_context=prices)
        assert out.result is CaseResult.VALIDATED_FAIL

    def test_context_not_bracketing_fails(self):
        """Price context that does not bracket any ex date -> FAIL (not pass)."""
        events = [{"SECURITY_CODE": "600000", "EX_DATE": "20240617", "EX_FACTOR": 1.05}]
        prices = [
            {"SECURITY_CODE": "600000", "TRADE_DATE": "20250101", "CLOSE_PRICE": 10.00},
        ]
        out = validators.validate_adj_continuity(events, price_context=prices)
        assert out.result is CaseResult.VALIDATED_FAIL


class TestSdkBehavior:
    def test_uses_real_permission_codes(self):
        """R3-P0-11: permission codes must NOT duplicate the profile id."""
        record = {
            "account_profile_id": "ACCOUNT_abc123",
            "permission_codes": "ACCOUNT_abc123",  # placeholder bug
            "cache_behavior": "local",
        }
        out = validators.validate_sdk_behavior_record(record)
        assert out.result is CaseResult.VALIDATED_FAIL
        assert "placeholder bug" in out.actual

    def test_real_codes_pass(self):
        record = {
            "account_profile_id": "ACCOUNT_abc123",
            "permission_codes": "1|2|3|4|32|33",
            "cache_behavior": "local",
        }
        out = validators.validate_sdk_behavior_record(record)
        assert out.result is CaseResult.VALIDATED_PASS


class TestGoldenCases:
    def test_golden_comparison_pass_and_fail(self):
        from ashare_state.spike.validators import GoldenCase

        cases = [
            GoldenCase(
                golden_case_id="G1",
                case_type="golden_st_transition",
                provider_symbol="600518.SH",
                trade_date="20190506",
                truth_source="SSE announcement",
                source_ref="ref",
                expected_fields={"IS_ST_SEC": True},
            ),
            GoldenCase(
                golden_case_id="G2",
                case_type="golden_st_transition",
                provider_symbol="000018.SZ",
                trade_date="20200107",
                truth_source="SZSE announcement",
                source_ref="ref",
                expected_fields={"IS_ST_SEC": True},
            ),
        ]
        rows = [
            {
                "SECURITY_CODE": "600518",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20190506",
                "IS_ST_SEC": 1,
            },
            {
                "SECURITY_CODE": "000018",
                "MARKET_CODE": "2",
                "TRADE_DATE": "20200107",
                "IS_ST_SEC": 0,  # mismatch
            },
        ]
        outcomes = validators.validate_golden_cases(cases, rows)
        assert outcomes[0].result is CaseResult.VALIDATED_PASS
        assert outcomes[1].result is CaseResult.VALIDATED_FAIL

    def test_missing_provider_row_is_fail(self):
        from ashare_state.spike.validators import GoldenCase

        cases = [
            GoldenCase(
                golden_case_id="G1",
                case_type="golden_delisted",
                provider_symbol="300104.SZ",
                trade_date="20200720",
                truth_source="SZSE delisting",
                source_ref="ref",
                expected_fields={"IS_LISTED": "3"},
            ),
        ]
        outcomes = validators.validate_golden_cases(cases, [])
        assert outcomes[0].result is CaseResult.VALIDATED_FAIL
