"""Golden truth access (audit R4-A1.1).

DEPRECATED shim: formal gates load the versioned dataset via
ashare_state.spike.golden_store.GoldenTruthStore exclusively. This module
keeps a tiny seed ONLY for validator unit tests.
"""

from __future__ import annotations

from ashare_state.spike.validators import GoldenCase

__all__ = ["BUILTIN_GOLDEN_CASES", "golden_cases_by_type"]


def _seed(
    golden_case_id: str,
    case_type: str,
    symbol: str,
    date: str,
    source: str,
    ref: str,
    expected: dict,
    event_id: str,
    event_class: str,
) -> GoldenCase:
    return GoldenCase(
        golden_case_id=golden_case_id,
        case_type=case_type,
        provider_symbol=symbol,
        trade_date=date,
        truth_source=source,
        source_ref=ref,
        expected_fields=expected,
        case_semantic_hash="seed",
        source_artifact_hash="",
        truth_version="seed",
        reviewed_by="seed",
        reviewed_at="1970-01-01T00:00:00+00:00",
        review_status="SEED",
        event_id=event_id,
        event_class=event_class,
    )


#: validator-unit-test seed (NOT used by any gate)
BUILTIN_GOLDEN_CASES: tuple[GoldenCase, ...] = (
    _seed(
        "GT-ST-600518-20190506",
        "golden_st_transition",
        "600518.SH",
        "20190506",
        "Kangmei: *ST cap effective 2019-05-06 (SSE)",
        "sse.com.cn Kangmei 2018 annual report",
        {"IS_ST_SEC": True},
        "ST_CAP-600518-2019",
        "ST_CAP",
    ),
    _seed(
        "GT-DELIST-300104-20200720",
        "golden_delisted",
        "300104.SZ",
        "20200720",
        "LeEco/Leshi delisted 2020-07-21 (SZSE)",
        "szse.cn delisting announcement",
        {"IS_LISTED": "3"},
        "DELIST-300104.SZ",
        "DELIST",
    ),
)


def golden_cases_by_type(case_type: str) -> list[GoldenCase]:
    return [c for c in BUILTIN_GOLDEN_CASES if c.case_type == case_type]
