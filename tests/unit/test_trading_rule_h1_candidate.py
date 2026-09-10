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
H1R3_CANDIDATE = Path("configs/trading_rules/versions/v20260910-h1r3-compiled/rules.yaml")
H1R3_EVIDENCE_INPUT = Path(
    "docs/provider_verification/trading_rule_h1r3_evidence_input_20260910.json"
)
H1R3_SOURCE_CATALOG = Path(
    "docs/provider_verification/trading_rule_h1r3_source_catalog_20260910.json"
)
OLD_CANDIDATE_HASH = "75d21777f1f135c47b963868641dfffc5428c5c5d897e17480a91ebaec1edd51"
H1R2_CANDIDATE_HASH = "6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f"
H1R3_CANDIDATE_HASH = "f2ca5504f8282cc25941b910593b8548160b1dabdffe5e9666093b6a3807ebf9"
CHINEXT_IMPLEMENTATION_DATE_URL = "https://www.szse.cn/aboutus/trends/news/t20200821_580924.html"


def _candidate_hash(path: Path, version: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"versions/{version}/rules.yaml".encode())
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@pytest.fixture(scope="module")
def h1_book() -> TradingRuleBook:
    return TradingRuleBook.load(CANDIDATE)


@pytest.fixture(scope="module")
def h1r2_book() -> TradingRuleBook:
    return TradingRuleBook.load(H1R2_CANDIDATE)


@pytest.fixture(scope="module")
def h1r3_book() -> TradingRuleBook:
    return TradingRuleBook.load(H1R3_CANDIDATE)


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


def test_h1r3_candidate_is_source_contract_correction_only(
    h1r2_book: TradingRuleBook,
    h1r3_book: TradingRuleBook,
):
    assert h1r3_book.version == "2026-09-10.1"
    assert h1r3_book.review_status == "COMPILED"
    assert h1r3_book.evidence_contract == "RULE_EVIDENCE_BUNDLE.v1"
    assert len(h1r3_book.rules) == 14
    assert _candidate_hash(H1R3_CANDIDATE, "v20260910-h1r3-compiled") == H1R3_CANDIDATE_HASH

    previous = {rule.rule_id: rule for rule in h1r2_book.rules}
    corrected_rule_ids = {
        "CHINEXT_PRE_REGISTRATION_NORMAL",
        "CHINEXT_PRE_REGISTRATION_ST",
        "CHINEXT_REGISTRATION",
        "CHINEXT_REGISTRATION_FIRST5",
    }
    semantic_fields = (
        "rule_id",
        "board",
        "exchanges",
        "code_patterns",
        "effective_from",
        "effective_to",
        "st_state",
        "listing_age_rule",
        "up_rate",
        "down_rate",
        "tick_size",
        "rounding_mode",
    )
    for rule in h1r3_book.rules:
        old_rule = previous[rule.rule_id]
        assert all(getattr(rule, field) == getattr(old_rule, field) for field in semantic_fields)
        old_urls = set(source_urls_from_ref(old_rule.source_ref))
        new_urls = set(source_urls_from_ref(rule.source_ref))
        if rule.rule_id in corrected_rule_ids:
            assert new_urls - old_urls == {CHINEXT_IMPLEMENTATION_DATE_URL}
        else:
            assert new_urls == old_urls


def test_h1r3_implementation_date_source_is_archived_and_cataloged():
    source_path = Path("docs/provider_verification/trading_rule_h1_sources/direct_17.html")
    content = source_path.read_bytes()
    assert len(content) == 34508
    assert hashlib.sha256(content).hexdigest() == (
        "cba74610a5c582e2ac94f3bb21a04f2e5fa1fa175131b0cd287f9bbfc311b1ae"
    )
    text = content.decode("utf-8")
    assert "深交所新闻发言人就创业板改革并试点注册制相关问题答记者问" in text
    assert '2020</span>年<span lang="EN-US">8</span>月<span lang="EN-US">24</span>日起' in text

    catalog = json.loads(H1R3_SOURCE_CATALOG.read_text(encoding="utf-8"))
    assert catalog["source_count"] == len(catalog["catalog"]) == 20
    entry = next(
        item for item in catalog["catalog"] if item["url"] == CHINEXT_IMPLEMENTATION_DATE_URL
    )
    assert entry["initial_http_status"] == 200
    assert entry["final_url"] == CHINEXT_IMPLEMENTATION_DATE_URL
    assert entry["artifact_path"].endswith("direct_17.html")
    assert entry["byte_size"] == len(content)
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()


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


@pytest.mark.parametrize(
    "path",
    [
        Path("docs/provider_verification/trading_rule_h1_evidence_input.json"),
        H1R3_EVIDENCE_INPUT,
    ],
)
def test_h1_evidence_inputs_have_no_duplicate_json_keys(path: Path):
    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)


def _assert_source_contract_matches_candidate_source_refs(book: TradingRuleBook, path: Path):
    document = json.loads(path.read_text(encoding="utf-8"))
    entries = {str(entry["rule_id"]): entry for entry in document["entries"]}
    assert set(entries) == {rule.rule_id for rule in book.rules}
    for rule in book.rules:
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


def test_h1r2_source_contract_matches_candidate_source_refs(h1r2_book: TradingRuleBook):
    _assert_source_contract_matches_candidate_source_refs(
        h1r2_book, Path("docs/provider_verification/trading_rule_h1_evidence_input.json")
    )


def test_h1r3_source_contract_matches_candidate_source_refs(h1r3_book: TradingRuleBook):
    _assert_source_contract_matches_candidate_source_refs(h1r3_book, H1R3_EVIDENCE_INPUT)
