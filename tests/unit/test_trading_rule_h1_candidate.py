"""PIT boundary tests for the non-ACTIVE Trading Rule H1 candidate."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ashare_state.spike.rule_evidence import source_urls_from_ref
from ashare_state.spike.trading_rule import RuleUnresolvedError, TradingRuleBook

CANDIDATE = Path("configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml")
H1R2_CANDIDATE = Path("configs/trading_rules/versions/v20260909-h1r2-compiled/rules.yaml")
OLD_CANDIDATE_HASH = "75d21777f1f135c47b963868641dfffc5428c5c5d897e17480a91ebaec1edd51"
H1R2_CANDIDATE_HASH = "6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f"


def _candidate_hash(path: Path, version: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"versions/{version}/rules.yaml".encode())
    digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(scope="module")
def h1_book() -> TradingRuleBook:
    return TradingRuleBook.load(CANDIDATE)


@pytest.fixture(scope="module")
def h1r2_book() -> TradingRuleBook:
    return TradingRuleBook.load(H1R2_CANDIDATE)


def test_candidate_is_compiled_and_not_active(h1_book: TradingRuleBook):
    assert h1_book.version == "2026-09-09.1"
    assert h1_book.review_status == "COMPILED"
    assert h1_book.evidence_contract == "RULE_EVIDENCE_BUNDLE.v1"
    assert len(h1_book.rules) == 14
    assert _candidate_hash(CANDIDATE, "v20260909-h1-compiled") == OLD_CANDIDATE_HASH


def test_candidate_source_refs_have_no_unresolved_review_markers(h1_book: TradingRuleBook):
    markers = ("to be checked", "todo", "tbd", "待确认", "待核")
    assert all(
        not any(marker in rule.source_ref.casefold() for marker in markers)
        for rule in h1_book.rules
    )


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


def test_main_board_first_five_is_st_state_agnostic(h1_book: TradingRuleBook):
    calendar = [20230410, 20230411, 20230412, 20230413, 20230414, 20230417]
    first_normal = h1_book.resolve(
        exchange="SZ",
        code="000001.SZ",
        trade_date="20230410",
        is_st=False,
        listing_date="20230410",
        calendar=calendar,
    )
    first_st = h1_book.resolve(
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
    assert first_normal.rule_id == first_st.rule_id == "MAIN_BOARD_FIRST5_NO_LIMIT"
    assert first_normal.is_no_limit and first_st.is_no_limit
    assert sixth.rule_id == "MAIN_BOARD_ST_HISTORICAL_SZ"
    assert sixth.up_rate == Decimal("0.05")


@pytest.mark.parametrize(
    ("exchange", "code", "historical_rule_id"),
    [
        ("SH", "600001.SH", "MAIN_BOARD_ST_HISTORICAL_SH"),
        ("SZ", "000001.SZ", "MAIN_BOARD_ST_HISTORICAL_SZ"),
    ],
)
def test_main_board_st_pit_transition_for_both_venues(
    h1_book: TradingRuleBook,
    exchange: str,
    code: str,
    historical_rule_id: str,
):
    historical = h1_book.resolve_limit_regime(
        exchange=exchange,
        code=code,
        trade_date="20260703",
        is_st=True,
    )
    current = h1_book.resolve_limit_regime(
        exchange=exchange,
        code=code,
        trade_date="20260706",
        is_st=True,
    )
    as_of = h1_book.resolve_limit_regime(
        exchange=exchange,
        code=code,
        trade_date="20260908",
        is_st=True,
    )
    assert historical.rule_id == historical_rule_id
    assert historical.up_rate == Decimal("0.05")
    assert current.rule_id == as_of.rule_id == "MAIN_BOARD_ST_CURRENT"
    assert current.up_rate == as_of.up_rate == Decimal("0.10")


@pytest.mark.parametrize(
    ("exchange", "code", "before_date", "start_date", "historical_rule_id"),
    [
        ("SH", "600001.SH", "19980421", "19980422", "MAIN_BOARD_ST_HISTORICAL_SH"),
        ("SZ", "000001.SZ", "19980427", "19980428", "MAIN_BOARD_ST_HISTORICAL_SZ"),
    ],
)
def test_main_board_st_historical_venue_start_boundaries(
    h1_book: TradingRuleBook,
    exchange: str,
    code: str,
    before_date: str,
    start_date: str,
    historical_rule_id: str,
):
    with pytest.raises(RuleUnresolvedError, match="no applicable rule"):
        h1_book.resolve_limit_regime(
            exchange=exchange,
            code=code,
            trade_date=before_date,
            is_st=True,
        )
    first_day = h1_book.resolve_limit_regime(
        exchange=exchange,
        code=code,
        trade_date=start_date,
        is_st=True,
    )
    assert first_day.rule_id == historical_rule_id
    assert first_day.up_rate == Decimal("0.05")


@pytest.mark.parametrize("trade_date", ["20260703", "20260706", "20260908"])
@pytest.mark.parametrize(
    ("exchange", "code"),
    [("SH", "600001.SH"), ("SZ", "000001.SZ")],
)
def test_main_board_normal_remains_ten_percent_at_st_transition(
    h1_book: TradingRuleBook, trade_date: str, exchange: str, code: str
):
    rule = h1_book.resolve_limit_regime(
        exchange=exchange,
        code=code,
        trade_date=trade_date,
        is_st=False,
    )
    assert rule.rule_id == "MAIN_BOARD_NORMAL"
    assert rule.up_rate == Decimal("0.10")


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


def test_h1r2_candidate_is_scoped_and_keeps_old_candidate_separate(
    h1r2_book: TradingRuleBook,
):
    assert h1r2_book.version == "2026-09-09.2"
    assert h1r2_book.review_status == "COMPILED"
    assert h1r2_book.evidence_contract == "RULE_EVIDENCE_BUNDLE.v1"
    assert len(h1r2_book.rules) == 14
    assert _candidate_hash(H1R2_CANDIDATE, "v20260909-h1r2-compiled") == H1R2_CANDIDATE_HASH
    assert all(rule.effective_from >= 20200101 for rule in h1r2_book.rules)
    assert not h1r2_book.rules[0].source_ref.startswith("SSE/SZSE")


@pytest.mark.parametrize(
    ("exchange", "code", "historical_rule_id"),
    [
        ("SH", "600001.SH", "MAIN_BOARD_ST_HISTORICAL_SH"),
        ("SZ", "000001.SZ", "MAIN_BOARD_ST_HISTORICAL_SZ"),
    ],
)
def test_h1r2_main_board_st_2020_scope_is_fail_closed_before_start(
    h1r2_book: TradingRuleBook,
    exchange: str,
    code: str,
    historical_rule_id: str,
):
    with pytest.raises(RuleUnresolvedError, match="no matching rule"):
        h1r2_book.resolve_limit_regime(
            exchange=exchange,
            code=code,
            trade_date="20191231",
            is_st=True,
        )
    start = h1r2_book.resolve_limit_regime(
        exchange=exchange,
        code=code,
        trade_date="20200101",
        is_st=True,
    )
    assert start.rule_id == historical_rule_id
    assert start.up_rate == Decimal("0.05")


def test_h1r2_st_transition_remains_2026_pit_exact(h1r2_book: TradingRuleBook):
    historical = h1r2_book.resolve_limit_regime(
        exchange="SH",
        code="600001.SH",
        trade_date="20260705",
        is_st=True,
    )
    current = h1r2_book.resolve_limit_regime(
        exchange="SH",
        code="600001.SH",
        trade_date="20260706",
        is_st=True,
    )
    assert historical.rule_id == "MAIN_BOARD_ST_HISTORICAL_SH"
    assert historical.up_rate == Decimal("0.05")
    assert current.rule_id == "MAIN_BOARD_ST_CURRENT"
    assert current.up_rate == Decimal("0.10")


def test_h1r2_source_contract_matches_candidate_source_refs(h1r2_book: TradingRuleBook):
    document = json.loads(
        Path("docs/provider_verification/trading_rule_h1_evidence_input.json").read_text(
            encoding="utf-8"
        )
    )
    entries = {str(entry["rule_id"]): entry for entry in document["entries"]}
    assert set(entries) == {rule.rule_id for rule in h1r2_book.rules}
    for rule in h1r2_book.rules:
        declared = tuple(source_urls_from_ref(rule.source_ref))
        supplied = tuple(str(source["source_url"]) for source in entries[rule.rule_id]["sources"])
        assert set(supplied) == set(declared)
    all_source_urls = {
        str(source["source_url"]) for entry in document["entries"] for source in entry["sources"]
    }
    assert {
        "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx",
        "https://docs.static.szse.cn/www/disclosure/notice/general/W020200612831351578076.pdf",
        "https://www.bse.cn/uploads/6/file/public/202209/20220924113331_fwbg1kr3qu.docx",
        "https://www.bse.cn/uploads/6/file/public/202209/20220924123627_d6405jicv9.docx",
        "https://www.bse.cn/uploads/6/file/public/202604/20260424170528_52kqyhc7p9.docx",
    } <= all_source_urls
