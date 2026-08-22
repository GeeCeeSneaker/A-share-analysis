"""Golden truth access (audit R4-P0-01).

DEPRECATED shim: the built-in constant seed was replaced by the VERSIONED
golden dataset at data/golden/provider/amazingdata/ (golden_cases_v1.jsonl
+ truth_manifest.json). Use ashare_state.spike.golden_store.GoldenTruthStore.

This module keeps a tiny verified seed ONLY for unit tests of the
validator layer; formal gates load the dataset store exclusively.
"""

from __future__ import annotations

from ashare_state.spike.validators import GoldenCase

__all__ = ["BUILTIN_GOLDEN_CASES", "golden_cases_by_type"]

#: validator-unit-test seed (NOT used by any gate; R4-P0-03 conflicts fixed)
BUILTIN_GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        golden_case_id="GT-ST-600518-20190506",
        case_type="golden_st_transition",
        provider_symbol="600518.SH",
        trade_date="20190506",
        truth_source="Kangmei Pharmaceutical: *ST cap effective 2019-05-06 (SSE)",
        source_ref="sse.com.cn Kangmei 2018 annual report + risk warning 2019-04-30",
        expected_fields={"IS_ST_SEC": True},
        source_hash="seed",
        truth_version="seed",
        reviewed_by="seed",
        reviewed_at="1970-01-01T00:00:00+00:00",
        review_status="SEED",
    ),
    GoldenCase(
        golden_case_id="GT-DELIST-300104-20200720",
        case_type="golden_delisted",
        provider_symbol="300104.SZ",
        trade_date="20200720",
        truth_source="LeEco/Leshi delisted 2020-07-21 (SZSE)",
        source_ref="szse.cn delisting announcement",
        expected_fields={"IS_LISTED": "3"},
        source_hash="seed",
        truth_version="seed",
        reviewed_by="seed",
        reviewed_at="1970-01-01T00:00:00+00:00",
        review_status="SEED",
    ),
)


def golden_cases_by_type(case_type: str) -> list[GoldenCase]:
    return [c for c in BUILTIN_GOLDEN_CASES if c.case_type == case_type]
