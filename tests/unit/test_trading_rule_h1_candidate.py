"""PIT boundary tests for the non-ACTIVE Trading Rule H1 candidate."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ashare_state.spike.trading_rule import RuleUnresolvedError, TradingRuleBook

CANDIDATE = Path("configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml")


@pytest.fixture(scope="module")
def h1_book() -> TradingRuleBook:
    return TradingRuleBook.load(CANDIDATE)


def test_candidate_is_compiled_and_not_active(h1_book: TradingRuleBook):
    assert h1_book.version == "2026-09-09.1"
    assert h1_book.review_status == "COMPILED"
    assert h1_book.evidence_contract == "RULE_EVIDENCE_BUNDLE.v1"
    assert len(h1_book.rules) == 13


def test_main_board_registration_first_five_and_day_six(h1_book: TradingRuleBook):
    calendar = [20230410, 20230411, 20230412, 20230413, 20230414, 20230417]
    day_one = h1_book.resolve(
        exchange="SH",
        code="601900.SH",
        trade_date="20230410",
        listing_date="20230410",
        calendar=calendar,
    )
    day_five = h1_book.resolve(
        exchange="SH",
        code="601900.SH",
        trade_date="20230414",
        listing_date="20230410",
        calendar=calendar,
    )
    day_six = h1_book.resolve(
        exchange="SH",
        code="601900.SH",
        trade_date="20230417",
        listing_date="20230410",
        calendar=calendar,
    )
    assert day_one.rule_id == day_five.rule_id == "MAIN_BOARD_FIRST5_NO_LIMIT"
    assert day_one.is_no_limit and day_five.is_no_limit
    assert day_six.rule_id == "MAIN_BOARD_NORMAL"
    assert day_six.up_rate == Decimal("0.10")


def test_main_board_st_first_five_does_not_select_five_percent(h1_book: TradingRuleBook):
    calendar = [20230410, 20230411, 20230412, 20230413, 20230414, 20230417]
    first = h1_book.resolve(
        exchange="SZ",
        code="000001.SZ",
        trade_date="20230410",
        is_st=True,
        listing_date="20230410",
        calendar=calendar,
    )
    sixth = h1_book.resolve(
        exchange="SZ",
        code="000001.SZ",
        trade_date="20230417",
        is_st=True,
        listing_date="20230410",
        calendar=calendar,
    )
    assert first.rule_id == "MAIN_BOARD_ST_FIRST5_NO_LIMIT"
    assert first.is_no_limit
    assert sixth.rule_id == "MAIN_BOARD_ST"
    assert sixth.up_rate == Decimal("0.05")


def test_old_main_board_ipo_regime_ends_before_registration_first_listing(
    h1_book: TradingRuleBook,
):
    old = h1_book.resolve(
        exchange="SH",
        code="605499.SH",
        trade_date="20230407",
        listing_date="20230407",
        calendar=[20230407],
    )
    assert old.rule_id == "MAIN_BOARD_IPO_DAY"
    assert (old.up_rate, old.down_rate) == (Decimal("0.44"), Decimal("0.36"))


def test_chinext_pre_registration_separates_st_semantics(h1_book: TradingRuleBook):
    normal = h1_book.resolve_limit_regime(
        exchange="SZ",
        code="300001.SZ",
        trade_date="20200821",
    )
    st = h1_book.resolve_limit_regime(
        exchange="SZ",
        code="300001.SZ",
        trade_date="20200821",
        is_st=True,
    )
    assert normal.rule_id == "CHINEXT_PRE_REGISTRATION_NORMAL"
    assert normal.up_rate == Decimal("0.10")
    assert st.rule_id == "CHINEXT_PRE_REGISTRATION_ST"
    assert st.up_rate == Decimal("0.05")


def test_bse_boundary_and_listing_day(h1_book: TradingRuleBook):
    calendar = [20211115, 20211116]
    listing_day = h1_book.resolve(
        exchange="BJ",
        code="835185.BJ",
        trade_date="20211115",
        listing_date="20211115",
        calendar=calendar,
    )
    next_day = h1_book.resolve(
        exchange="BJ",
        code="835185.BJ",
        trade_date="20211116",
        listing_date="20211115",
        calendar=calendar,
    )
    assert listing_day.rule_id == "BSE_IPO_DAY_NO_LIMIT"
    assert listing_day.is_no_limit
    assert next_day.rule_id == "BSE_LIMIT"
    assert next_day.up_rate == Decimal("0.30")
    with pytest.raises(RuleUnresolvedError, match="no matching rule"):
        h1_book.resolve_limit_regime(
            exchange="BJ",
            code="835185.BJ",
            trade_date="20211112",
        )
