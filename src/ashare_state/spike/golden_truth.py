"""Built-in golden truth cases (audit R3 sections 16/17/37 R3-0E).

Each GoldenCase carries an EXTERNAL truth source independent of the
provider under test. Dates/facts below are PUBLIC, verifiable market
events; before the FIRST production spike the operator must re-verify
each source_ref and record source_hash (the production run refuses
unverified golden cases - see B4).

Golden quantities required by the core gate (task book 7.1A):
    50 ST cap/removal | 20 delisted | 30 limit regime | 20 corporate action
The built-in set is the SEED; the production spike freezes the full
sample from provider data first (candidate discovery), then attaches
expected truth per case before validation.
"""

from __future__ import annotations

from ashare_state.spike.validators import GoldenCase

__all__ = ["BUILTIN_GOLDEN_CASES", "golden_cases_by_type"]


BUILTIN_GOLDEN_CASES: tuple[GoldenCase, ...] = (
    # ---- ST transitions (public, verifiable) ---------------------------
    GoldenCase(
        golden_case_id="GOLDEN-ST-600518-20190506",
        case_type="golden_st_transition",
        provider_symbol="600518.SH",
        trade_date="20190506",
        truth_source="SSE announcement: Kangmei Pharmaceutical *ST from 2019-05-06",
        source_ref="sse.com.cn disclosure 2019-04-30 annual report qualified opinion",
        expected_fields={"IS_ST_SEC": True},
    ),
    GoldenCase(
        golden_case_id="GOLDEN-ST-000018-20200107",
        case_type="golden_st_transition",
        provider_symbol="000018.SZ",
        trade_date="20200107",
        truth_source="SZSE announcement: Shenzen Shen Cheng A ST removal",
        source_ref="szse.cn disclosure",
        expected_fields={"IS_ST_SEC": True},
    ),
    # ---- delisted (survivorship) ----------------------------------------
    GoldenCase(
        golden_case_id="GOLDEN-DELIST-300104-20200720",
        case_type="golden_delisted",
        provider_symbol="300104.SZ",
        trade_date="20200720",
        truth_source="SZSE delisting: LeEco (Leshi Internet) delisted 2020-07-21",
        source_ref="szse.cn delisting announcement",
        expected_fields={"IS_LISTED": "3"},
    ),
    # ---- limit regime (structural: main board 10%) ----------------------
    GoldenCase(
        golden_case_id="GOLDEN-LIMIT-MAIN-10PCT",
        case_type="golden_limit_regime",
        provider_symbol="600000.SH",
        trade_date="20240102",
        truth_source="SSE trading rules: main board +/-10% (round to 0.01)",
        source_ref="sse.com.cn trading rules 2023 revision",
        expected_fields={"PRICE_HIGH_LMT_RATE": 0.10},
    ),
    GoldenCase(
        golden_case_id="GOLDEN-LIMIT-STAR-20PCT",
        case_type="golden_limit_regime",
        provider_symbol="688981.SH",
        trade_date="20200722",
        truth_source="SSE STAR rules: +/-20% after first 5 no-limit days",
        source_ref="sse.com.cn STAR market rules",
        expected_fields={"PRICE_HIGH_LMT_RATE": 0.20},
    ),
    GoldenCase(
        golden_case_id="GOLDEN-LIMIT-STAR-FIRSTDAY-NO-LIMIT",
        case_type="golden_limit_regime",
        provider_symbol="688981.SH",
        trade_date="20200722",
        truth_source="SSE STAR rules: IPO first 5 trading days have NO price limit",
        source_ref="sse.com.cn STAR market rules",
        expected_fields={"HIGH_LIMITED": None},  # None = field absent on no-limit days
    ),
    # ---- corporate action (dividend ex-date, public) --------------------
    GoldenCase(
        golden_case_id="GOLDEN-CA-600519-20220630",
        case_type="golden_corporate_action",
        provider_symbol="600519.SH",
        trade_date="20220630",
        truth_source="Kweichow Moutai 2021 annual dividend: ex-date 2022-06-30",
        source_ref="sse.com.cn company announcement 2022-06-23",
        expected_fields={"IS_WD_SEC": True},
    ),
)


def golden_cases_by_type(case_type: str) -> list[GoldenCase]:
    return [c for c in BUILTIN_GOLDEN_CASES if c.case_type == case_type]
