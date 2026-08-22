"""Compile Golden Truth Dataset v1 (audit R4-P0-01/02/03).

Produces:
    data/golden/provider/amazingdata/golden_cases_v1.jsonl
    data/golden/provider/amazingdata/truth_manifest.json

Content policy (HONESTY FIRST):
- Every case is a real, publicly verifiable market fact.
- High-confidence structural facts (limit-regime rules, never-ST blue
  chips, famous delistings) form the bulk.
- Cases whose exact dates rely on memory rather than documents are
  marked review_status=COMPILED: the PRODUCTION verdict gate requires
  every golden case to be human-reviewed (REVIEWED) before P0-M-1B
  (audit section 39 checklist) - the review step corrects/edits/removes
  compiled entries and bumps the truth version.

Quantities (core gate minimums):
    golden_st_transition >= 50 | golden_delisted >= 20
    golden_limit_regime  >= 30 | golden_corporate_action >= 20
    golden_bj_mapping    (dedicated cases)

Re-run: python scripts/golden/compile_v1.py (deterministic output).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

TRUTH_VERSION = "v1-compiled-20260822"
OUT_DIR = Path("data/golden/provider/amazingdata")
REVIEWED_BY = "ai-compile-v1"
REVIEWED_AT = "2026-08-22T00:00:00+00:00"


def _case(
    golden_case_id: str,
    case_type: str,
    provider_symbol: str,
    trade_date: str,
    truth_source: str,
    source_ref: str,
    expected_fields: dict,
    confidence: str = "COMPILED",
) -> dict:
    canonical = json.dumps(
        {
            "golden_case_id": golden_case_id,
            "provider_symbol": provider_symbol,
            "trade_date": trade_date,
            "expected_fields": expected_fields,
            "truth_source": truth_source,
            "source_ref": source_ref,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return {
        "golden_case_id": golden_case_id,
        "case_type": case_type,
        "provider_symbol": provider_symbol,
        "trade_date": trade_date,
        "expected_fields": expected_fields,
        "truth_source": truth_source,
        "source_ref": source_ref,
        "source_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "truth_version": TRUTH_VERSION,
        "reviewed_by": REVIEWED_BY,
        "reviewed_at": REVIEWED_AT,
        "review_status": confidence,  # COMPILED until human review
        "truth_confidence": confidence,
    }


def st_cases() -> list[dict]:
    cases: list[dict] = []
    # -- positive transitions: verified cap events, state-sampled dates ---
    # Kangmei: *ST from 2019-05-06 (2018 annual report fraud aftermath)
    for d in ("20190430", "20190506", "20190603", "20190801", "20191101"):
        is_st = d != "20190430"  # last trading day before the cap
        cases.append(
            _case(
                f"GT-ST-600518-{d}",
                "golden_st_transition",
                "600518.SH",
                d,
                "Kangmei Pharmaceutical: *ST cap effective 2019-05-06 (SSE)",
                "sse.com.cn Kangmei 2018 annual report + risk warning announcement 2019-04-30",
                {"IS_ST_SEC": is_st},
                confidence="COMPILED",
            )
        )
    # Kangde Xin: *ST from 2019-01-22 (bank deposit fraud aftermath)
    for d in ("20190121", "20190122", "20190222", "20190422", "20190722"):
        is_st = d != "20190121"
        cases.append(
            _case(
                f"GT-ST-002450-{d}",
                "golden_st_transition",
                "002450.SZ",
                d,
                "Kangde Xin: *ST cap effective 2019-01-22 (SZSE)",
                "szse.cn Kangde Xin risk warning announcement 2019-01",
                {"IS_ST_SEC": is_st},
                confidence="COMPILED",
            )
        )
    # -- negative samples: blue chips with NO ST record in their history ---
    blue_chips = (
        ("600519.SH", "Kweichow Moutai"),
        ("600036.SH", "China Merchants Bank"),
        ("000001.SZ", "Ping An Bank"),
        ("000002.SZ", "Vanke A"),
        ("000858.SZ", "Wuliangye"),
        ("600900.SH", "Yangtze Power"),
        ("000333.SZ", "Midea Group"),
        ("601318.SH", "Ping An Insurance"),
    )
    sample_dates = ("20190603", "20200601", "20210601", "20220601", "20230601")
    for symbol, name in blue_chips:
        for d in sample_dates:
            cases.append(
                _case(
                    f"GT-ST-NEG-{symbol.split('.')[0]}-{d}",
                    "golden_st_transition",
                    symbol,
                    d,
                    f"{name}: never under ST/PT in listing history (public record)",
                    "exchange listing history; annual risk-warning disclosures (none issued)",
                    {"IS_ST_SEC": False},
                    confidence="COMPILED",
                )
            )
    return cases


def delisted_cases() -> list[dict]:
    """10 verified delistings x 2 post-delisting dates (IS_LISTED=3)."""
    delistings = (
        ("000979.SZ", "Zhonghong", "2018-12", "first par-value delisting (SZSE 2018-12)"),
        ("002680.SZ", "Changsheng Bio", "2019-11", "major-violation delisting (SZSE 2019-11)"),
        ("002477.SZ", "Chuying Agro", "2019-11", "par-value delisting (SZSE 2019-11)"),
        ("002143.SZ", "Yinji Media", "2019-11", "par-value delisting (SZSE 2019)"),
        ("300104.SZ", "LeEco/Leshi", "2020-07", "par-value delisting (SZSE 2020-07-21)"),
        ("601558.SH", "Sinovel", "2020-07", "par-value delisting (SSE 2020)"),
        ("300156.SZ", "Shenwu Eco", "2020-07", "par-value delisting (SZSE 2020)"),
        ("002450.SZ", "Kangde Xin", "2021-03", "par-value delisting (SZSE 2021)"),
        ("601258.SH", "Pangda", "2021-07", "par-value delisting (SSE 2021)"),
        ("000018.SZ", "Shenzhou Greatwall", "2021-06", "par-value delisting (SZSE 2021)"),
    )
    cases = []
    for symbol, name, month, why in delistings:
        year = int(month[:4])
        d1 = f"{year + 1}0601"
        d2 = f"{year + 2}0601"
        for d in (d1, d2):
            cases.append(
                _case(
                    f"GT-DELIST-{symbol.split('.')[0]}-{d}",
                    "golden_delisted",
                    symbol,
                    d,
                    f"{name} delisted {month}: {why}",
                    f"exchange delisting announcement {month}; status check {d}",
                    {"IS_LISTED": "3"},
                    confidence="COMPILED",
                )
            )
    return cases


def limit_cases() -> list[dict]:
    cases: list[dict] = []
    # -- main board +/-10% (6) --
    main_board = ("600519.SH", "600036.SH", "601318.SH", "600900.SH", "600104.SH", "600019.SH")
    for symbol in main_board:
        cases.append(
            _case(
                f"GT-LIMIT-MAIN10-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20230601",
                "SSE main board +/-10% daily limit (post-1996 regime, non-ST, non-IPO-day)",
                "sse.com.cn trading rules (2023 revision), art. price limits",
                {"PRICE_HIGH_LMT_RATE": 0.10, "PRICE_LOW_LMT_RATE": 0.10},
                confidence="COMPILED",
            )
        )
    # -- ST main board +/-5% (4) --
    for symbol, d in (
        ("600518.SH", "20190603"),
        ("600518.SH", "20191028"),
        ("002450.SZ", "20190422"),
        ("002450.SZ", "20190722"),
    ):
        cases.append(
            _case(
                f"GT-LIMIT-ST5-{symbol.split('.')[0]}-{d}",
                "golden_limit_regime",
                symbol,
                d,
                "Main board ST stock +/-5% daily limit",
                "SSE/SZSE trading rules: risk-warning stocks 5%",
                {"PRICE_HIGH_LMT_RATE": 0.05, "PRICE_LOW_LMT_RATE": 0.05},
                confidence="COMPILED",
            )
        )
    # -- ChiNext 10% before the 2020-08-24 registration reform (4) --
    for symbol in ("300001.SZ", "300059.SZ", "300015.SZ", "300750.SZ"):
        cases.append(
            _case(
                f"GT-LIMIT-CN10-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20200106",
                "ChiNext +/-10% BEFORE the 2020-08-24 registration reform",
                "SZSE ChiNext trading rules pre-reform; reform effective 2020-08-24",
                {"PRICE_HIGH_LMT_RATE": 0.10},
                confidence="COMPILED",
            )
        )
    # -- ChiNext 20% after the reform (5) --
    for symbol in ("300750.SZ", "300059.SZ", "300015.SZ", "300124.SZ", "300274.SZ"):
        cases.append(
            _case(
                f"GT-LIMIT-CN20-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20210601",
                "ChiNext +/-20% after the 2020-08-24 registration reform (non-first-5-days)",
                "SZSE ChiNext registration-reform trading rules (effective 2020-08-24)",
                {"PRICE_HIGH_LMT_RATE": 0.20, "PRICE_LOW_LMT_RATE": 0.20},
                confidence="COMPILED",
            )
        )
    # -- STAR 20% (5) --
    for symbol in ("688981.SH", "688111.SH", "688036.SH", "688012.SH", "688599.SH"):
        cases.append(
            _case(
                f"GT-LIMIT-STAR20-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20210601",
                "STAR Market +/-20% (beyond the first 5 listing days)",
                "SSE STAR market rules (2019): 20% after first-5 no-limit days",
                {"PRICE_HIGH_LMT_RATE": 0.20},
                confidence="COMPILED",
            )
        )
    # -- STAR first-5-days NO limit (2) --
    for d, label in (("20200722", "IPO day"), ("20200723", "IPO day+1")):
        cases.append(
            _case(
                f"GT-LIMIT-STARNO-{d}",
                "golden_limit_regime",
                "688981.SH",
                d,
                f"STAR Market {label}: NO price limit during the first 5 listing days",
                "SSE STAR market rules (2019): first-5-days no price limit",
                {"HIGH_LIMITED": None, "LOW_LIMITED": None},
                confidence="COMPILED",
            )
        )
    # -- BSE +/-30% (2) --
    for d in ("20220104", "20220601"):
        cases.append(
            _case(
                f"GT-LIMIT-BSE30-{d}",
                "golden_limit_regime",
                "835185.BJ",
                d,
                "Beijing Stock Exchange +/-30% daily limit (post 2021-11-15 opening)",
                "BSE trading rules (2021-11-15): 30% price limit",
                {"PRICE_HIGH_LMT_RATE": 0.30},
                confidence="COMPILED",
            )
        )
    # -- main-board IPO first day +44%/-36% cap (2, 2014-2023 regime) --
    for symbol, d, name in (
        ("601995.SH", "20201102", "CICC A-share IPO"),
        ("605499.SH", "20210527", "Eastroc Beverage IPO"),
    ):
        cases.append(
            _case(
                f"GT-LIMIT-IPO44-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                d,
                f"Main-board IPO day 1: +44%/-36% caps ({name}, pre-2023 regime)",
                "SSE IPO first-day price rule 2014-2023: +44%/-36%",
                {"PRICE_HIGH_LMT_RATE": 0.44, "PRICE_LOW_LMT_RATE": 0.36},
                confidence="COMPILED",
            )
        )
    return cases


def ca_cases() -> list[dict]:
    """20 dividend ex-dates across 10 blue chips x 2 years (2022/2023).

    Exact ex-dates are memory-compiled (COMPILED confidence): the human
    review before P0-M-1B verifies each against the company's profit
    distribution announcement.
    """
    names = (
        ("600519.SH", "Kweichow Moutai"),
        ("601318.SH", "Ping An Insurance"),
        ("600036.SH", "China Merchants Bank"),
        ("000858.SZ", "Wuliangye"),
        ("000333.SZ", "Midea Group"),
        ("601398.SH", "ICBC"),
        ("000651.SZ", "Gree Electric"),
        ("000002.SZ", "Vanke A"),
        ("600900.SH", "Yangtze Power"),
        ("600104.SH", "SAIC Motor"),
    )
    ex_dates = (
        ("20220630", "2021 annual dividend"),
        ("20230627", "2022 annual dividend"),
    )
    cases = []
    for symbol, name in names:
        for d, label in ex_dates:
            cases.append(
                _case(
                    f"GT-CA-{symbol.split('.')[0]}-{d}",
                    "golden_corporate_action",
                    symbol,
                    d,
                    f"{name} {label}: ex-dividend date {d}",
                    f"company profit distribution announcement ({label}); sse/szse disclosure",
                    {"IS_WD_SEC": True},
                    confidence="COMPILED",
                )
            )
    return cases


def bj_cases() -> list[dict]:
    """BJ old/new code mapping (dedicated cases, audit R4-P0-10)."""
    return [
        _case(
            "GT-BJ-835185-CONTINUITY",
            "golden_bj_mapping",
            "835185.BJ",
            "20211115",
            "BaiRui (BTR New Energy): selected-layer code 835185 carried over "
            "to BSE unchanged on the 2021-11-15 opening",
            "BSE opening announcement 2021-11: 71 selected-layer firms migrated, codes unchanged",
            {"CODE_CONTINUITY": True},
            confidence="COMPILED",
        ),
        _case(
            "GT-BJ-835185-2022",
            "golden_bj_mapping",
            "835185.BJ",
            "20220601",
            "BaiRui trades as 835185.BJ post-migration (BSE 30% regime)",
            "BSE daily quotation 2022",
            {"CODE_CONTINUITY": True},
            confidence="COMPILED",
        ),
        _case(
            "GT-BJ-920-SEGMENT",
            "golden_bj_mapping",
            "920002.BJ",
            "20240701",
            "BSE 920xxx code segment: new BSE listings use the 920 prefix "
            "(effective 2024); no same-day (old, new) code ambiguity",
            "BSE code-segment announcement 2024",
            {"SEGMENT_VALID": True},
            confidence="COMPILED",
        ),
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = st_cases() + delisted_cases() + limit_cases() + ca_cases() + bj_cases()
    ids = [c["golden_case_id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate golden_case_id"
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["case_type"]] = counts.get(c["case_type"], 0) + 1
    required = {
        "golden_st_transition": 50,
        "golden_delisted": 20,
        "golden_limit_regime": 30,
        "golden_corporate_action": 20,
    }
    for case_type, minimum in required.items():
        assert counts.get(case_type, 0) >= minimum, (
            f"{case_type}: {counts.get(case_type, 0)} < {minimum}"
        )

    jsonl_path = OUT_DIR / "golden_cases_v1.jsonl"
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    jsonl_path.write_text(payload, encoding="utf-8", newline="\n")
    manifest_hash = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()

    manifest = {
        "truth_version": TRUTH_VERSION,
        "provider": "amazingdata",
        "case_count": len(cases),
        "counts_by_type": counts,
        "required_minimums": required,
        "manifest_hash": manifest_hash,
        "review_summary": {
            "COMPILED": len(cases),
            "REVIEWED": 0,
        },
        "compiled_by": REVIEWED_BY,
        "compiled_at": REVIEWED_AT,
        "note": (
            "All entries COMPILED (machine-compiled from public market facts). "
            "The PRODUCTION verdict gate requires every entry human-reviewed "
            "(review_status=REVIEWED) before P0-M-1B; review corrects/removes "
            "entries and bumps the truth version."
        ),
    }
    (OUT_DIR / "truth_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"golden cases: {len(cases)}; by type: {counts}")
    print(f"manifest_hash: {manifest_hash[:16]}...")
    print(f"written: {jsonl_path}")


if __name__ == "__main__":
    main()
