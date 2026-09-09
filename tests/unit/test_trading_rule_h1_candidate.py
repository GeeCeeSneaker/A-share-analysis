"""Trading Rule H1 corrected-candidate boundary tests.

These tests deliberately load the non-ACTIVE COMPILED candidate directly.
They do not promote it to REVIEWED or mutate the ACTIVE selector.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from ashare_state.spike.trading_rule import RuleUnresolvedError, TradingRuleBook

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "v20260909-h1-compiled"
VERSION_DIR = REPO_ROOT / "configs" / "trading_rules" / "versions" / VERSION
RULES_FILE = VERSION_DIR / "rules.yaml"
CONTRACT_FILE = VERSION_DIR / "evidence_source_contract.json"
ACTIVE_MANIFEST = REPO_ROOT / "configs" / "trading_rules" / "rule_manifest.json"


@pytest.fixture(scope="module")
def h1_book() -> TradingRuleBook:
    return TradingRuleBook.load(RULES_FILE)


def test_candidate_is_compiled_and_not_active(h1_book: TradingRuleBook):
    active = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))
    assert h1_book.review_status == "COMPILED"
    assert active["rule_version"] != VERSION


def test_source_contract_matches_rule_set_and_is_first_party(h1_book: TradingRuleBook):
    contract = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
    candidate_ids = {r.rule_id for r in h1_book.rules}
    assert candidate_ids == set(contract["rule_sources"])
    allowed = set(contract["policy"]["allowed_hosts"])
    referenced = {source_id for refs in contract["rule_sources"].values() for source_id in refs}
    assert referenced
    for source_id in referenced:
        source = contract["sources"][source_id]
        assert source["url"].startswith("https://")
        host = source["url"].split("/", 3)[2]
        assert host in allowed
        assert source["artifact_sha256"] is None
        assert source["artifact_size"] is None


def test_candidate_validator_passes():
    result = subprocess.run(
        [sys.executable, "scripts/rules/validate_h1_candidate.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["review_status"] == "COMPILED"
    assert payload["rule_count"] == 14


class TestMainBoardTransitions:
    def test_1996_normal_limit(self, h1_book: TradingRuleBook):
        rule = h1_book.resolve_limit_regime(
            exchange="SH", code="600600.SH", trade_date="19961216", is_st=False
        )
        assert rule.rule_id == "MAIN_BOARD_NORMAL"
        assert rule.up_rate == Decimal("0.10")

    def test_st_transition_is_exchange_specific(self, h1_book: TradingRuleBook):
        sh = h1_book.resolve_limit_regime(
            exchange="SH", code="600600.SH", trade_date="19980422", is_st=True
        )
        assert sh.rule_id == "MAIN_BOARD_ST_SH_5"
        assert sh.up_rate == Decimal("0.05")

        with pytest.raises(RuleUnresolvedError):
            h1_book.resolve_limit_regime(
                exchange="SZ", code="000001.SZ", trade_date="19980427", is_st=True
            )
        sz = h1_book.resolve_limit_regime(
            exchange="SZ", code="000001.SZ", trade_date="19980428", is_st=True
        )
        assert sz.rule_id == "MAIN_BOARD_ST_SZ_5"
        assert sz.up_rate == Decimal("0.05")

    def test_2026_main_st_changes_to_ten_percent(self, h1_book: TradingRuleBook):
        before_sh = h1_book.resolve_limit_regime(
            exchange="SH", code="600600.SH", trade_date="20260703", is_st=True
        )
        before_sz = h1_book.resolve_limit_regime(
            exchange="SZ", code="000001.SZ", trade_date="20260703", is_st=True
        )
        assert before_sh.up_rate == Decimal("0.05")
        assert before_sz.up_rate == Decimal("0.05")

        after_sh = h1_book.resolve_limit_regime(
            exchange="SH", code="600600.SH", trade_date="20260706", is_st=True
        )
        after_sz = h1_book.resolve_limit_regime(
            exchange="SZ", code="000001.SZ", trade_date="20260706", is_st=True
        )
        assert after_sh.rule_id == "MAIN_BOARD_ST_10_FROM_20260706"
        assert after_sz.rule_id == "MAIN_BOARD_ST_10_FROM_20260706"
        assert after_sh.up_rate == after_sz.up_rate == Decimal("0.10")

    def test_legacy_ipo_listing_day_ends_before_registration_switch(
        self, h1_book: TradingRuleBook
    ):
        old = h1_book.resolve(
            exchange="SH",
            code="605499.SH",
            trade_date="20230407",
            is_st=False,
            listing_date="20230407",
            calendar=[20230407, 20230410, 20230411],
        )
        assert old.rule_id == "MAIN_BOARD_IPO_DAY"
        assert (old.up_rate, old.down_rate) == (Decimal("0.44"), Decimal("0.36"))

    def test_registration_main_board_first_five_then_ten(self, h1_book: TradingRuleBook):
        calendar = [20230410, 20230411, 20230412, 20230413, 20230414, 20230417]
        day1 = h1_book.resolve(
            exchange="SH",
            code="603135.SH",
            trade_date="20230410",
            is_st=False,
            listing_date="20230410",
            calendar=calendar,
        )
        day5 = h1_book.resolve(
            exchange="SH",
            code="603135.SH",
            trade_date="20230414",
            is_st=False,
            listing_date="20230410",
            calendar=calendar,
        )
        day6 = h1_book.resolve(
            exchange="SH",
            code="603135.SH",
            trade_date="20230417",
            is_st=False,
            listing_date="20230410",
            calendar=calendar,
        )
        assert day1.rule_id == day5.rule_id == "MAIN_BOARD_REGISTRATION_FIRST5"
        assert day1.is_no_limit and day5.is_no_limit
        assert day6.rule_id == "MAIN_BOARD_NORMAL"
        assert day6.up_rate == Decimal("0.10")


class TestChiNextTransitions:
    def test_pre_reform_normal_vs_st(self, h1_book: TradingRuleBook):
        normal = h1_book.resolve_limit_regime(
            exchange="SZ", code="300001.SZ", trade_date="20200821", is_st=False
        )
        st = h1_book.resolve_limit_regime(
            exchange="SZ", code="300001.SZ", trade_date="20200821", is_st=True
        )
        assert normal.rule_id == "CHINEXT_PRE_REGISTRATION_NORMAL"
        assert normal.up_rate == Decimal("0.10")
        assert st.rule_id == "CHINEXT_PRE_REGISTRATION_ST"
        assert st.up_rate == Decimal("0.05")

    def test_post_reform_first_five_then_twenty(self, h1_book: TradingRuleBook):
        calendar = [20200824, 20200825, 20200826, 20200827, 20200828, 20200831]
        day5 = h1_book.resolve(
            exchange="SZ",
            code="300999.SZ",
            trade_date="20200828",
            listing_date="20200824",
            calendar=calendar,
        )
        day6 = h1_book.resolve(
            exchange="SZ",
            code="300999.SZ",
            trade_date="20200831",
            listing_date="20200824",
            calendar=calendar,
        )
        assert day5.rule_id == "CHINEXT_REGISTRATION_FIRST5"
        assert day5.is_no_limit
        assert day6.rule_id == "CHINEXT_REGISTRATION"
        assert day6.up_rate == Decimal("0.20")


class TestStarAndBse:
    def test_star_first_five_then_twenty(self, h1_book: TradingRuleBook):
        calendar = [20190722, 20190723, 20190724, 20190725, 20190726, 20190729]
        day5 = h1_book.resolve(
            exchange="SH",
            code="688001.SH",
            trade_date="20190726",
            listing_date="20190722",
            calendar=calendar,
        )
        day6 = h1_book.resolve(
            exchange="SH",
            code="688001.SH",
            trade_date="20190729",
            listing_date="20190722",
            calendar=calendar,
        )
        assert day5.rule_id == "STAR_MARKET_FIRST5" and day5.is_no_limit
        assert day6.rule_id == "STAR_MARKET" and day6.up_rate == Decimal("0.20")

    def test_pre_bse_bj_identity_fails_closed(self, h1_book: TradingRuleBook):
        with pytest.raises(RuleUnresolvedError):
            h1_book.resolve_limit_regime(
                exchange="BJ", code="835185.BJ", trade_date="20211112"
            )

    def test_new_bse_listing_day_no_limit_then_thirty(self, h1_book: TradingRuleBook):
        calendar = [20211115, 20211116, 20211117]
        listing_day = h1_book.resolve(
            exchange="BJ",
            code="835185.BJ",
            trade_date="20211115",
            listing_date="20211115",
            calendar=calendar,
        )
        day2 = h1_book.resolve(
            exchange="BJ",
            code="835185.BJ",
            trade_date="20211116",
            listing_date="20211115",
            calendar=calendar,
        )
        assert listing_day.rule_id == "BSE_LISTING_DAY_NO_LIMIT"
        assert listing_day.is_no_limit
        assert day2.rule_id == "BSE_LIMIT"
        assert day2.up_rate == Decimal("0.30")

    def test_migrated_selected_layer_share_is_thirty_on_bse_opening_day(
        self, h1_book: TradingRuleBook
    ):
        # BSE listing rules preserve the pre-BSE Selected Layer listing date.
        # Therefore a migrated company is not treated as a new BSE IPO on
        # 2021-11-15 and remains under the ordinary 30% limit.
        calendar = [20200727, 20211115, 20211116]
        migrated = h1_book.resolve(
            exchange="BJ",
            code="835185.BJ",
            trade_date="20211115",
            listing_date="20200727",
            calendar=calendar,
        )
        assert migrated.rule_id == "BSE_LIMIT"
        assert migrated.up_rate == Decimal("0.30")
