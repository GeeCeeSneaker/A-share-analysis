"""R4-A2.3 P0-06/P0-07: trading-rule data layer tests (audit section 8).

Institutional facts live in configs/trading_rules/*.yaml; Python only
loads/validates/PIT-matches/conflict-detects/resolves/computes. All
failures are RULE_UNRESOLVED (fail closed) - never a silent fallback to
"MAIN 10%".

Session-index tests (audit section 8.5): the first-N window uses TRADING
SESSIONS from the PIT calendar - Spring Festival / National Day / weekend
crossing / 5th-vs-6th session / missing calendar row.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    TradingRuleBook,
    first_n_sessions,
)

RULES_DIR = Path("configs/trading_rules")


@pytest.fixture(scope="module")
def book() -> TradingRuleBook:
    return TradingRuleBook.load(RULES_DIR)


@pytest.fixture(scope="module")
def book_docs() -> dict:
    doc_file = RULES_DIR / "a_share_limit_v1.yaml"
    return yaml.safe_load(doc_file.read_text(encoding="utf-8"))


class TestRuleDataLayer:
    def test_loads_versioned_dataset(self, book: TradingRuleBook, book_docs: dict):
        assert len(book.rules) >= 9
        assert book.version == str(book_docs["version"])
        assert book.source_version
        assert book.review_status == "COMPILED"

    def test_no_hardcoded_rates_in_python(self):
        """P0-06: the institutional rates must NOT live in trading_rule.py."""
        source = Path("src/ashare_state/spike/trading_rule.py").read_text(encoding="utf-8")
        # the literal rate tables of the old implementation must be gone
        assert "BOARD_LIMIT_RATES" not in source
        assert '"MAIN": 0.10' not in source
        assert "0.20," not in source.replace("up_rate: 0.20", "")  # yaml-only values

    def test_board_regimes_resolve_from_data(self, book: TradingRuleBook):
        # MAIN normal 10% / ST 5%
        rule = book.resolve_limit_regime(exchange="SH", code="600519.SH", trade_date="20230601")
        assert rule.rule_id == "MAIN_BOARD_NORMAL"
        assert rule.up_rate == Decimal("0.10")
        st = book.resolve_limit_regime(
            exchange="SH", code="600518.SH", trade_date="20230601", is_st=True
        )
        assert st.rule_id == "MAIN_BOARD_ST"
        assert st.up_rate == Decimal("0.05")
        # ChiNext pre/post registration reform (PIT date-driven)
        pre = book.resolve_limit_regime(exchange="SZ", code="300001.SZ", trade_date="20200821")
        assert pre.up_rate == Decimal("0.10")
        post = book.resolve_limit_regime(exchange="SZ", code="300001.SZ", trade_date="20200824")
        assert post.up_rate == Decimal("0.20")
        # STAR 20% / BSE 30%
        star = book.resolve_limit_regime(exchange="SH", code="688001.SH", trade_date="20230601")
        assert star.up_rate == Decimal("0.20")
        bse = book.resolve_limit_regime(exchange="BJ", code="835185.BJ", trade_date="20220601")
        assert (bse.up_rate, bse.down_rate) == (Decimal("0.30"), Decimal("0.30"))

    def test_ipo_day_44_36_window(self, book: TradingRuleBook):
        inside = book.resolve(
            exchange="SH",
            code="605499.SH",
            trade_date="20210819",
            is_st=False,
            listing_date="20210819",
            calendar=[20210819, 20210820, 20210823],
        )
        assert inside.rule_id == "MAIN_BOARD_IPO_DAY"
        assert (inside.up_rate, inside.down_rate) == (Decimal("0.44"), Decimal("0.36"))
        outside = book.resolve(
            exchange="SH",
            code="605499.SH",
            trade_date="20210820",
            is_st=False,
            listing_date="20210819",
            calendar=[20210819, 20210820, 20210823],
        )
        assert outside.rule_id == "MAIN_BOARD_NORMAL"

    def test_first5_no_limit_via_sessions(self, book: TradingRuleBook):
        calendar = [20230801, 20230802, 20230803, 20230804, 20230807, 20230808]
        day5 = book.resolve(
            exchange="SH",
            code="688001.SH",
            trade_date="20230807",  # 5th session after listing 20230801
            listing_date="20230801",
            calendar=calendar,
        )
        assert day5.rule_id == "STAR_MARKET_FIRST5"
        assert day5.is_no_limit
        day6 = book.resolve(
            exchange="SH",
            code="688001.SH",
            trade_date="20230808",  # 6th session -> 20% regime
            listing_date="20230801",
            calendar=calendar,
        )
        assert day6.rule_id == "STAR_MARKET"
        assert day6.up_rate == Decimal("0.20")

    def test_listing_context_required_for_age_dependent_rules(self, book):
        """P0-06/audit 8.3: refusing to guess beats silent degradation."""
        with pytest.raises(RuleUnresolvedError, match="listing_date/trading calendar"):
            book.resolve(exchange="SH", code="688001.SH", trade_date="20230601")
        # MAIN normal stock without listing context still resolves (its
        # candidates carry no listing-age rules)
        plain = book.resolve_limit_regime(exchange="SH", code="600519.SH", trade_date="20230601")
        assert plain.rule_id == "MAIN_BOARD_NORMAL"


class TestFailClosed:
    def test_unknown_board_fails(self, book: TradingRuleBook):
        with pytest.raises(RuleUnresolvedError, match="no matching rule"):
            book.resolve_limit_regime(exchange="SH", code="999999.SH", trade_date="20230601")

    def test_unknown_exchange_fails(self, book: TradingRuleBook):
        with pytest.raises(RuleUnresolvedError, match="unknown exchange"):
            book.resolve_limit_regime(exchange="HK", code="00700.HK", trade_date="20230601")

    def test_date_outside_every_window_fails(self, book: TradingRuleBook):
        # 600xxx on 1996-01-02: before the 1996-12-16 price-limit rule
        with pytest.raises(RuleUnresolvedError):
            book.resolve_limit_regime(exchange="SH", code="600600.SH", trade_date="19960102")

    def test_ambiguous_duplicate_rules_fail_closed(self, tmp_path: Path, book_docs: dict):
        docs = copy.deepcopy(book_docs)
        docs["rules"].append(
            {
                "rule_id": "MAIN_BOARD_NORMAL_DUP",
                "board": "MAIN",
                "exchanges": ["SH", "SZ"],
                "code_patterns": ["60xxxx"],
                "effective_from": "19961216",
                "effective_to": "20991231",
                "st_state": False,
                "listing_age_rule": "NONE",
                "up_rate": 0.10,
                "down_rate": 0.10,
                "tick_size": "0.01",
                "rounding_mode": "ROUND_HALF_UP",
                "source_ref": "test duplicate",
            }
        )
        target = tmp_path / "rules.yaml"
        target.write_text(yaml.safe_dump(docs), encoding="utf-8")
        loaded = TradingRuleBook.load(target)
        with pytest.raises(RuleUnresolvedError, match=">1 equally-valid"):
            loaded.resolve_limit_regime(exchange="SH", code="600519.SH", trade_date="20230601")

    def test_invalid_schema_rejected(self, tmp_path: Path, book_docs: dict):
        docs = copy.deepcopy(book_docs)
        docs["rules"][0]["up_rate"] = 1.5  # out of [0,1]
        target = tmp_path / "rules.yaml"
        target.write_text(yaml.safe_dump(docs), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid"):
            TradingRuleBook.load(target)

    def test_missing_rules_file_rejected(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            TradingRuleBook.load(tmp_path / "nonexistent.yaml")


class TestFirstNSessions:
    def test_session_index_not_calendar_days(self):
        # listing Friday, weekend in between: sessions are Mon..Fri
        calendar = [20240202, 20240205, 20240206, 20240207, 20240208, 20240209]
        # listing day IS the 1st session: 5th session = 20240208 (diff 4)
        assert first_n_sessions(20240208, 20240202, calendar, n=5)
        assert first_n_sessions(20240209, 20240202, calendar, n=5) is False
        # mid-window sessions are inside too
        assert first_n_sessions(20240205, 20240202, calendar, n=5)

    def test_spring_festival_gap(self):
        # Spring Festival holiday 0205-0216 removed from the calendar:
        # a calendar-day approximation would misjudge the 5th session
        calendar = [
            20240201, 20240202,
            # holiday gap (no sessions between 0202 and 0219)
            20240219, 20240220, 20240221, 20240222, 20240223,
        ]
        # listing 20240202: sessions are 0202, 0219, 0220, 0221, 0222 (5th)
        assert first_n_sessions(20240222, 20240202, calendar, n=5)
        assert first_n_sessions(20240223, 20240202, calendar, n=5) is False

    def test_national_day_gap(self):
        calendar = [
            20230928, 20230929,
            # National Day holiday 1001-1006
            20231009, 20231010, 20231011, 20231012, 20231013,
        ]
        # listing 20230928: sessions 0928, 0929, 1009, 1010, 1011 (5th)
        assert first_n_sessions(20231011, 20230928, calendar, n=5)
        assert first_n_sessions(20231012, 20230928, calendar, n=5) is False

    def test_missing_calendar_row_fails_closed(self):
        calendar = [20220801, 20220802, 20220804, 20220805]  # 20220803 missing
        with pytest.raises(RuleUnresolvedError, match="missing from trading calendar"):
            first_n_sessions(20220803, 20220801, calendar, n=5)
        with pytest.raises(RuleUnresolvedError, match="missing from trading calendar"):
            first_n_sessions(20220804, 20220803, calendar, n=5)

    def test_trade_date_before_listing_fails(self):
        with pytest.raises(RuleUnresolvedError, match="before listing"):
            first_n_sessions(20220729, 20220801, [20220729, 20220801, 20220802], n=5)

    def test_listing_before_calendar_window_is_past_first_n(self):
        # long-listed security: listing predates the calendar window
        calendar = [20230101, 20230102, 20230103]
        assert first_n_sessions(20230103, 19901219, calendar, n=5) is False

    def test_empty_calendar_fails(self):
        with pytest.raises(RuleUnresolvedError, match="empty trading calendar"):
            first_n_sessions(20230103, 20230101, [], n=5)


class TestDecimalLimitPrices:
    def test_round_half_up_exact_cases(self, book: TradingRuleBook):
        rule = book.resolve_limit_regime(exchange="SH", code="600519.SH", trade_date="20230601")
        # 9.87 * 1.10 = 10.857 -> 10.86 (ROUND_HALF_UP, not banker's)
        up, down = rule.limit_prices(Decimal("9.87"))
        assert (up, down) == (Decimal("10.86"), Decimal("8.88"))
        # 3.33 * 1.05 = 3.4965 -> 3.50 (half-up at the 0.01 tick)
        st = book.resolve_limit_regime(
            exchange="SZ", code="000001.SZ", trade_date="20230601", is_st=True
        )
        up, down = st.limit_prices(Decimal("3.33"))
        assert (up, down) == (Decimal("3.50"), Decimal("3.16"))
        # BSE 30%: 10.0 -> 13.00 / 7.00
        bse = book.resolve_limit_regime(exchange="BJ", code="835185.BJ", trade_date="20220601")
        assert bse.limit_prices(Decimal("10.0")) == (Decimal("13.00"), Decimal("7.00"))

    def test_no_limit_rule_prices_are_pre_close(self, book: TradingRuleBook):
        rule = book.resolve(
            exchange="SZ",
            code="301236.SZ",
            trade_date="20220805",
            listing_date="20220801",
            calendar=[20220801, 20220802, 20220803, 20220804, 20220805, 20220808],
        )
        assert rule.is_no_limit
        assert rule.limit_prices(Decimal("12.34")) == (Decimal("12.34"), Decimal("12.34"))
