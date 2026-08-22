"""Compile Golden CANDIDATE Dataset v3 (audit R4-A2 sections 7/9/10).

v3 changes vs v2:
- compiled_* / reviewed_* provenance SEPARATED (COMPILED cases carry no
  reviewer fields - the store enforces this).
- source evidence model fields (source_artifact_ref/kind/retrieved_at)
  present but empty until the review workflow fills them.
- ST events: event_class ST_TRANSITION with event_subtype
  (ST_ADD / ST_REMOVE); subtypes reflect the two verified cap events.
- honest event counts preserved (ST_TRANSITION=2, DELIST=10).

Re-run: python scripts/golden/compile_v3.py (deterministic).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

TRUTH_VERSION = "v3-candidate-20260822"
OUT_DIR = Path("data/golden/provider/amazingdata")
COMPILED_BY = "ai-compile-v3"
COMPILED_AT = "2026-08-22T00:00:00+00:00"


def _semantic_hash(doc: dict) -> str:
    statement = json.dumps(
        {
            "golden_case_id": doc["golden_case_id"],
            "case_type": doc["case_type"],
            "provider_symbol": doc["provider_symbol"],
            "trade_date": doc["trade_date"],
            "expected_fields": doc["expected_fields"],
            "truth_source": doc["truth_source"],
            "source_ref": doc["source_ref"],
            "source_artifact_hash": doc.get("source_artifact_hash", ""),
            "truth_version": doc["truth_version"],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _case(
    golden_case_id: str,
    case_type: str,
    provider_symbol: str,
    trade_date: str,
    truth_source: str,
    source_ref: str,
    expected_fields: dict,
    event_id: str,
    event_class: str,
    event_subtype: str = "",
) -> dict:
    doc = {
        "golden_case_id": golden_case_id,
        "case_type": case_type,
        "provider_symbol": provider_symbol,
        "trade_date": trade_date,
        "expected_fields": expected_fields,
        "truth_source": truth_source,
        "source_ref": source_ref,
        # evidence model - filled ONLY by the review workflow
        "source_artifact_ref": "",
        "source_artifact_kind": "",
        "source_retrieved_at": "",
        "source_artifact_hash": "",
        "truth_version": TRUTH_VERSION,
        "compiled_by": COMPILED_BY,
        "compiled_at": COMPILED_AT,
        "reviewed_by": "",
        "reviewed_at": "",
        "review_note": "",
        "review_status": "COMPILED",
        "event_id": event_id,
        "event_class": event_class,
        "event_subtype": event_subtype,
    }
    doc["case_semantic_hash"] = _semantic_hash(doc)
    return doc


def st_cases() -> list[dict]:
    cases: list[dict] = []
    # Kangmei: *ST cap (ST_ADD subtype - entered risk-warning state)
    for d in ("20190506", "20190603", "20190801", "20191101", "20191231"):
        cases.append(
            _case(
                f"GT-ST-600518-{d}",
                "golden_st_transition",
                "600518.SH",
                d,
                "Kangmei Pharmaceutical: *ST cap effective 2019-05-06 (SSE)",
                "sse.com.cn Kangmei 2018 annual report + risk warning 2019-04-30",
                {"IS_ST_SEC": True},
                "ST_CAP-600518-2019",
                "ST_TRANSITION",
                "ST_ADD",
            )
        )
    # Kangde Xin: *ST cap (ST_ADD subtype)
    for d in ("20190122", "20190222", "20190422", "20190722", "20191231"):
        cases.append(
            _case(
                f"GT-ST-002450-{d}",
                "golden_st_transition",
                "002450.SZ",
                d,
                "Kangde Xin: *ST cap effective 2019-01-22 (SZSE)",
                "szse.cn Kangde Xin risk warning announcement 2019-01",
                {"IS_ST_SEC": True},
                "ST_CAP-002450-2019",
                "ST_TRANSITION",
                "ST_ADD",
            )
        )
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
    for symbol, name in blue_chips:
        for d in ("20190603", "20200601", "20210601", "20220601", "20230601"):
            cases.append(
                _case(
                    f"GT-ST-NEG-{symbol.split('.')[0]}-{d}",
                    "golden_st_transition",
                    symbol,
                    d,
                    f"{name}: never under ST/PT in listing history (public record)",
                    "exchange listing history; annual risk-warning disclosures (none issued)",
                    {"IS_ST_SEC": False},
                    f"NEG-{symbol}",
                    "NEGATIVE_SAMPLE",
                )
            )
    return cases


def delisted_cases() -> list[dict]:
    delistings = (
        ("000979.SZ", "Zhonghong", "2018-12", "first par-value delisting (SZSE)"),
        ("002680.SZ", "Changsheng Bio", "2019-11", "major-violation delisting"),
        ("002477.SZ", "Chuying Agro", "2019-11", "par-value delisting"),
        ("002143.SZ", "Yinji Media", "2019-11", "par-value delisting"),
        ("300104.SZ", "LeEco/Leshi", "2020-07", "par-value delisting (SZSE 2020-07-21)"),
        ("601558.SH", "Sinovel", "2020-07", "par-value delisting (SSE)"),
        ("300156.SZ", "Shenwu Eco", "2020-07", "par-value delisting (SZSE)"),
        ("002450.SZ", "Kangde Xin", "2021-03", "par-value delisting (SZSE)"),
        ("601258.SH", "Pangda", "2021-07", "par-value delisting (SSE)"),
        ("000018.SZ", "Shenzhou Greatwall", "2021-06", "par-value delisting"),
    )
    cases = []
    for symbol, name, month, why in delistings:
        year = int(month[:4])
        for d in (f"{year + 1}0601", f"{year + 2}0601"):
            cases.append(
                _case(
                    f"GT-DELIST-{symbol.split('.')[0]}-{d}",
                    "golden_delisted",
                    symbol,
                    d,
                    f"{name} delisted {month}: {why}",
                    f"exchange delisting announcement {month}; status check {d}",
                    {"IS_LISTED": "3"},
                    f"DELIST-{symbol}",
                    "DELIST",
                )
            )
    return cases


def limit_cases() -> list[dict]:
    cases = []
    for symbol in ("600519.SH", "600036.SH", "601318.SH", "600900.SH", "600104.SH", "600019.SH"):
        cases.append(
            _case(
                f"GT-LIMIT-MAIN10-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20230601",
                "SSE main board +/-10% daily limit (non-ST, non-IPO)",
                "sse.com.cn trading rules (2023 revision), art. price limits",
                {"PRICE_HIGH_LMT_RATE": 0.10, "PRICE_LOW_LMT_RATE": 0.10},
                "REGIME-MAIN-10",
                "LIMIT_REGIME",
            )
        )
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
                "REGIME-ST-5",
                "LIMIT_REGIME",
            )
        )
    for symbol in ("300001.SZ", "300059.SZ", "300015.SZ", "300750.SZ"):
        cases.append(
            _case(
                f"GT-LIMIT-CN10-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20200106",
                "ChiNext +/-10% BEFORE the 2020-08-24 reform",
                "SZSE ChiNext trading rules pre-reform",
                {"PRICE_HIGH_LMT_RATE": 0.10},
                "REGIME-CN-PRE-10",
                "LIMIT_REGIME",
            )
        )
    for symbol in ("300750.SZ", "300059.SZ", "300015.SZ", "300124.SZ", "300274.SZ"):
        cases.append(
            _case(
                f"GT-LIMIT-CN20-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20210601",
                "ChiNext +/-20% after the 2020-08-24 reform",
                "SZSE ChiNext registration-reform trading rules",
                {"PRICE_HIGH_LMT_RATE": 0.20, "PRICE_LOW_LMT_RATE": 0.20},
                "REGIME-CN-POST-20",
                "LIMIT_REGIME",
            )
        )
    for symbol in ("688981.SH", "688111.SH", "688036.SH", "688012.SH", "688599.SH"):
        cases.append(
            _case(
                f"GT-LIMIT-STAR20-{symbol.split('.')[0]}",
                "golden_limit_regime",
                symbol,
                "20210601",
                "STAR Market +/-20% (beyond first 5 listing days)",
                "SSE STAR market rules (2019)",
                {"PRICE_HIGH_LMT_RATE": 0.20},
                "REGIME-STAR-20",
                "LIMIT_REGIME",
            )
        )
    for d, label in (("20200722", "IPO day"), ("20200723", "IPO day+1")):
        cases.append(
            _case(
                f"GT-LIMIT-STARNO-{d}",
                "golden_limit_regime",
                "688981.SH",
                d,
                f"STAR Market {label}: NO price limit during first 5 listing days",
                "SSE STAR market rules (2019): first-5-days no price limit",
                {"HIGH_LIMITED": None, "LOW_LIMITED": None},
                "NO_LIMIT_STAR_FIRST5",
                "NO_LIMIT_IPO",
            )
        )
    for d in ("20220104", "20220601"):
        cases.append(
            _case(
                f"GT-LIMIT-BSE30-{d}",
                "golden_limit_regime",
                "835185.BJ",
                d,
                "BSE +/-30% daily limit (post 2021-11-15 opening)",
                "BSE trading rules (2021-11-15)",
                {"PRICE_HIGH_LMT_RATE": 0.30},
                "REGIME-BSE-30",
                "LIMIT_REGIME",
            )
        )
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
                "SSE IPO first-day price rule 2014-2023",
                {"PRICE_HIGH_LMT_RATE": 0.44, "PRICE_LOW_LMT_RATE": 0.36},
                f"IPO44-{symbol}",
                "NO_LIMIT_IPO",
            )
        )
    return cases


def ca_cases() -> list[dict]:
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
    cases = []
    for symbol, name in names:
        for d, label in (
            ("20220630", "2021 annual dividend"),
            ("20230627", "2022 annual dividend"),
        ):
            cases.append(
                _case(
                    f"GT-CA-{symbol.split('.')[0]}-{d}",
                    "golden_corporate_action",
                    symbol,
                    d,
                    f"{name} {label}: ex-dividend date {d}",
                    f"company profit distribution announcement ({label})",
                    {"IS_WD_SEC": True},
                    f"DIV-{symbol}-{label}",
                    "DIVIDEND_EX_DATE",
                )
            )
    return cases


def bj_cases() -> list[dict]:
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
            "BJ-MIGRATION-2021",
            "BJ_CODE_MIGRATION",
        ),
        _case(
            "GT-BJ-835185-2022",
            "golden_bj_mapping",
            "835185.BJ",
            "20220601",
            "BaiRui trades as 835185.BJ post-migration (BSE 30% regime)",
            "BSE daily quotation 2022",
            {"CODE_CONTINUITY": True},
            "BJ-MIGRATION-2021",
            "BJ_CODE_MIGRATION",
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
            "BJ-920-SEGMENT-2024",
            "BJ_CODE_MIGRATION",
        ),
    ]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = st_cases() + delisted_cases() + limit_cases() + ca_cases() + bj_cases()
    ids = [c["golden_case_id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate golden_case_id"
    counts: dict[str, int] = {}
    events: dict[str, set[str]] = {}
    review: dict[str, int] = {}
    for c in cases:
        counts[c["case_type"]] = counts.get(c["case_type"], 0) + 1
        events.setdefault(c["event_class"], set()).add(c["event_id"])
        review[c["review_status"]] = review.get(c["review_status"], 0) + 1
    events = {k: len(v) for k, v in events.items()}

    dataset_file = "golden_cases_v3.jsonl"
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases)
    (OUT_DIR / dataset_file).write_text(payload, encoding="utf-8", newline="\n")
    dataset_hash = hashlib.sha256((OUT_DIR / dataset_file).read_bytes()).hexdigest()

    manifest = {
        "truth_version": TRUTH_VERSION,
        "dataset_file": dataset_file,
        "dataset_hash": dataset_hash,
        "case_count": len(cases),
        "counts_by_type": counts,
        "review_summary": review,
        "distinct_events": events,
        "candidate_status": (
            "Golden CANDIDATE dataset v3: compiled/reviewed provenance separated; "
            "ST_TRANSITION semantics with subtypes. Honest coverage: "
            f"ST_TRANSITION={events.get('ST_TRANSITION', 0)}<50 (subtypes ST_ADD only), "
            f"DELIST={events.get('DELIST', 0)}<20. The REVIEW workflow "
            "(scripts/golden/review.py) must add real distinct events, seal "
            "external artifacts, and produce the reviewed version."
        ),
    }
    (OUT_DIR / "truth_manifest_v3.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    (OUT_DIR / "truth_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"v3 candidate: {len(cases)} cases; by type: {counts}")
    print(f"distinct events: {events}")
    print(f"dataset_hash: {dataset_hash[:16]}...")


if __name__ == "__main__":
    main()
