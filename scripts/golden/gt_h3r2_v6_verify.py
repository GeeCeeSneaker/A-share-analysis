"""Read-only verification for the staged GT-H3R2 v6 candidate.

This verifier never advances the ACTIVE pointer and never writes files.  It
binds the staged v6 bytes, rebuild plan, carry-forward ledger, and transition
audit to immutable v5 inputs and the exact reviewer-authorized invariants.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.golden_store import (  # noqa: E402
    GoldenTruthError,
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    review_identity_hash_for_doc,
    semantic_hash_for_doc,
)
from ashare_state.spike.st_transition_audit import (  # noqa: E402
    transition_audit_publication_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_RELATIVE = Path("data/golden/provider/amazingdata")
REMEDIATION_RELATIVE = Path("docs/golden/gt_h3/remediation")

V5_VERSION = "v5-candidate-20260907"
V5_DATASET = "golden_cases_v5.jsonl"
V5_MANIFEST = "truth_manifest_v5.json"
V5_HASH = "5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c"
V6_VERSION = "v6-candidate-20260908"
V6_DATASET = "golden_cases_v6.jsonl"
V6_MANIFEST = "truth_manifest_v6.json"
V6_HASH = "0b3952f9f82ee4f6a55a7f060c47af3cc781b0054ed1f83b5868246c0642a343"

REVIEW_PROVENANCE_FIELDS = (
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "source_artifact_ref",
    "source_artifact_hash",
    "source_artifact_kind",
    "source_retrieved_at",
)

INVALID_SOURCE_IDS = frozenset(
    {
        "GT-H2-ST-ST_ADD-600654-20220506",
        "GT-H2-ST-ST_ADD-300064-20210428",
        "GT-H2-ST-ST_ADD-002113-20200429",
        "GT-H2-ST-ST_ADD-000806-20220506",
        "GT-H2-ST-ST_ADD-002781-20220506",
        "GT-H2-ST-ST_ADD-000606-20220506",
        "GT-H2-ST-ST_ADD-000410-20220419",
        "GT-H2-ST-ST_ADD-000616-20230504",
        "GT-H2-ST-ST_ADD-002433-20230505",
        "GT-H2-ST-ST_ADD-002086-20230505",
        "GT-H2-ST-ST_ADD-300108-20240430",
        "GT-H2-ST-ST_ADD-300209-20240429",
        "GT-H2-ST-ST_ADD-300167-20240430",
        "GT-H2-ST-ST_ADD-000525-20240919",
        "GT-H2-ST-ST_ADD-300506-20240429",
    }
)

NEW_CASES = (
    {
        "new_id": "GT-H2-ST-ST_ADD-300495-20210507",
        "old_id": "GT-H2-ST-ST_ADD-600654-20220506",
        "symbol": "300495.SZ",
        "date": "20210507",
        "subtype": "ST_ADD",
        "before_name": "美尚生态",
        "after_name": "*ST美尚",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209893133.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-002640-20210507",
        "old_id": "GT-H2-ST-ST_ADD-300064-20210428",
        "symbol": "002640.SZ",
        "date": "20210507",
        "subtype": "ST_ADD",
        "before_name": "跨境通",
        "after_name": "*ST跨境",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209892047.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-600382-20210506",
        "old_id": "GT-H2-ST-ST_ADD-002113-20200429",
        "symbol": "600382.SH",
        "date": "20210506",
        "subtype": "ST_ADD",
        "before_name": "广东明珠",
        "after_name": "*ST广珠",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209878423.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-600291-20210506",
        "old_id": "GT-H2-ST-ST_ADD-000806-20220506",
        "symbol": "600291.SH",
        "date": "20210506",
        "subtype": "ST_ADD",
        "before_name": "西水股份",
        "after_name": "*ST西水",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209878259.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-600078-20210506",
        "old_id": "GT-H2-ST-ST_ADD-002781-20220506",
        "symbol": "600078.SH",
        "date": "20210506",
        "subtype": "ST_ADD",
        "before_name": "澄星股份",
        "after_name": "*ST澄星",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209877776.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-600896-20210506",
        "old_id": "GT-H2-ST-ST_ADD-000606-20220506",
        "symbol": "600896.SH",
        "date": "20210506",
        "subtype": "ST_ADD",
        "before_name": "览海医疗",
        "after_name": "*ST海医",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209875156.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-600615-20210506",
        "old_id": "GT-H2-ST-ST_ADD-000410-20220419",
        "symbol": "600615.SH",
        "date": "20210506",
        "subtype": "ST_ADD",
        "before_name": "丰华股份",
        "after_name": "*ST丰华",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209874374.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-000502-20210506",
        "old_id": "GT-H2-ST-ST_ADD-000616-20230504",
        "symbol": "000502.SZ",
        "date": "20210506",
        "subtype": "ST_ADD",
        "before_name": "绿景控股",
        "after_name": "*ST绿景",
        "url": "https://static.cninfo.com.cn/finalpage/2021-04-30/1209872529.PDF",
    },
    {
        "new_id": "GT-H2-ST-STAR_ST_ADD-688086-20220506",
        "old_id": "GT-H2-ST-ST_ADD-002433-20230505",
        "symbol": "688086.SH",
        "date": "20220506",
        "subtype": "STAR_ST_ADD",
        "before_name": "紫晶存储",
        "after_name": "*ST紫晶",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213274157.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-603603-20220506",
        "old_id": "GT-H2-ST-ST_ADD-002086-20230505",
        "symbol": "603603.SH",
        "date": "20220506",
        "subtype": "ST_ADD",
        "before_name": "博天环境",
        "after_name": "*ST博天",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213274090.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-002313-20220506",
        "old_id": "GT-H2-ST-ST_ADD-300108-20240430",
        "symbol": "002313.SZ",
        "date": "20220506",
        "subtype": "ST_ADD",
        "before_name": "日海智能",
        "after_name": "*ST日海",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213267451.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-300301-20220506",
        "old_id": "GT-H2-ST-ST_ADD-300209-20240429",
        "symbol": "300301.SZ",
        "date": "20220506",
        "subtype": "ST_ADD",
        "before_name": "长方集团",
        "after_name": "*ST长方",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213267090.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-002751-20220506",
        "old_id": "GT-H2-ST-ST_ADD-300167-20240430",
        "symbol": "002751.SZ",
        "date": "20220506",
        "subtype": "ST_ADD",
        "before_name": "易尚展示",
        "after_name": "*ST易尚",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213266378.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-002316-20220506",
        "old_id": "GT-H2-ST-ST_ADD-000525-20240919",
        "symbol": "002316.SZ",
        "date": "20220506",
        "subtype": "ST_ADD",
        "before_name": "亚联发展",
        "after_name": "*ST亚联",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213265483.PDF",
    },
    {
        "new_id": "GT-H2-ST-ST_ADD-002366-20220506",
        "old_id": "GT-H2-ST-ST_ADD-300506-20240429",
        "symbol": "002366.SZ",
        "date": "20220506",
        "subtype": "ST_ADD",
        "before_name": "台海核电",
        "after_name": "*ST海核",
        "url": "https://static.cninfo.com.cn/finalpage/2022-04-30/1213263830.PDF",
    },
)
NEW_CASE_BY_ID = {spec["new_id"]: spec for spec in NEW_CASES}
NEW_CASE_IDS = tuple(spec["new_id"] for spec in NEW_CASES)


class VerificationError(RuntimeError):
    """A staged v6 invariant failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read JSON {path}: {exc}")
    if not isinstance(value, dict):
        _fail(f"JSON root must be an object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _fail(f"cannot read JSONL {path}: {exc}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(f"invalid JSONL {path}:{line_number}: {exc}")
        if not isinstance(value, dict):
            _fail(f"JSONL row must be an object {path}:{line_number}")
        rows.append(value)
    return rows


def _read_dataset(
    manifest_path: Path,
    expected_version: str,
    expected_dataset: str,
    expected_hash: str,
) -> tuple[bytes, list[dict[str, Any]], list[Any]]:
    manifest = _read_json(manifest_path)
    _require(
        manifest.get("truth_version") == expected_version,
        f"{manifest_path}: wrong truth_version",
    )
    _require(
        manifest.get("dataset_file") == expected_dataset,
        f"{manifest_path}: wrong dataset_file",
    )
    _require(manifest.get("dataset_hash") == expected_hash, f"{manifest_path}: wrong dataset_hash")
    dataset_path = manifest_path.parent / expected_dataset
    try:
        payload = dataset_path.read_bytes()
    except OSError as exc:
        _fail(f"cannot read dataset {dataset_path}: {exc}")
    actual_hash = hashlib.sha256(payload).hexdigest()
    _require(actual_hash == expected_hash, f"{dataset_path}: SHA256 mismatch")
    docs = _read_jsonl(dataset_path)
    try:
        cases = cases_from_dataset_bytes(payload, expected_version)
    except GoldenTruthError as exc:
        _fail(f"{dataset_path}: loader rejected dataset: {exc}")
    _require(len(docs) == len(cases), f"{dataset_path}: JSONL/loader row count mismatch")
    for doc, case in zip(docs, cases, strict=True):
        _require(
            doc.get("golden_case_id") == case.golden_case_id,
            f"{dataset_path}: document/loader ID mismatch",
        )
    return payload, docs, cases


def _validate_compiled_docs(
    docs: list[dict[str, Any]],
    truth_version: str,
    label: str,
) -> None:
    for doc in docs:
        case_id = str(doc.get("golden_case_id", "?"))
        _require(
            doc.get("truth_version") == truth_version,
            f"{label} {case_id}: wrong truth_version",
        )
        _require(doc.get("review_status") == "COMPILED", f"{label} {case_id}: not COMPILED")
        for field in REVIEW_PROVENANCE_FIELDS:
            _require(not doc.get(field), f"{label} {case_id}: review provenance is not blank")
        _require(
            doc.get("case_semantic_hash") == semantic_hash_for_doc(doc),
            f"{label} {case_id}: case_semantic_hash mismatch",
        )


def _stats_requirements() -> dict[str, Any]:
    return {
        "case_count": 125,
        "counts_by_type": {
            "golden_limit_regime": 30,
            "golden_corporate_action": 25,
            "golden_st_transition": 50,
            "golden_delisted": 20,
        },
        "review_summary": {"COMPILED": 125},
        "distinct_events": {
            "LIMIT_REGIME": 6,
            "NO_LIMIT_IPO": 3,
            "DIVIDEND_EX_DATE": 20,
            "RIGHT_ISSUE_EX_DATE": 5,
            "ST_TRANSITION": 50,
            "DELIST": 20,
        },
        "st_add_events": 38,
        "st_remove_events": 12,
        "distinct_delisted_securities": 20,
    }


def _verify_manifest_stats(manifest: dict[str, Any], cases: list[Any]) -> None:
    stats = recompute_manifest_statistics(cases)
    required = _stats_requirements()
    for field, expected in required.items():
        _require(manifest.get(field) == expected, f"v6 manifest {field} != required value")
        _require(stats.get(field) == expected, f"v6 recomputation {field} != required value")
    _require(
        manifest.get("distinct_securities") == stats.get("distinct_securities"),
        "v6 manifest distinct_securities != recomputed values",
    )


def _comparable_row(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in doc.items()
        if key not in {"truth_version", "case_semantic_hash"}
    }


def _verify_new_case(
    row: dict[str, Any],
    spec: dict[str, Any],
) -> None:
    case_id = spec["new_id"]
    code = spec["symbol"].split(".", 1)[0]
    date = spec["date"]
    subtype = spec["subtype"]
    expected_truth = (
        f"CNINFO official announcement: {spec['before_name']} → {spec['after_name']}; "
        f"{subtype} effective {date}"
    )
    expected_ref = (
        f"CNINFO official announcement: {spec['before_name']} → {spec['after_name']}; "
        f"binary {subtype} effective {date} | {spec['url']}"
    )
    expected_lineage = {
        "source_truth_version": V5_VERSION,
        "source_case_id": spec["old_id"],
        "replacement_relation": "DROP_ADD_ACCOUNTING_ONLY_NOT_SEMANTIC_MAPPING",
    }
    expected = {
        "golden_case_id": case_id,
        "case_type": "golden_st_transition",
        "provider_symbol": spec["symbol"],
        "trade_date": date,
        "truth_source": expected_truth,
        "source_ref": expected_ref,
        "expected_fields": {"IS_ST_SEC": True},
        "event_id": f"ST-ADD-{code}-{date}",
        "event_class": "ST_TRANSITION",
        "event_subtype": subtype,
        "event_effective_date": date,
        "source_evidence_scope": "CASE_SPECIFIC_OFFICIAL_ARTIFACT",
        "lineage": expected_lineage,
    }
    for field, value in expected.items():
        _require(row.get(field) == value, f"v6 new case {case_id}: {field} mismatch")
    _require(
        row.get("compiled_by") == "candidate-rebuild",
        f"v6 new case {case_id}: wrong compiled_by",
    )
    _require(
        row.get("compiled_at") == "2026-09-08T00:00:00+00:00",
        f"v6 new case {case_id}: wrong compiled_at",
    )


def _verify_row_sets(
    v5_docs: list[dict[str, Any]],
    v6_docs: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    v5_by_id = {str(row["golden_case_id"]): row for row in v5_docs}
    v6_by_id = {str(row["golden_case_id"]): row for row in v6_docs}
    _require(len(v5_by_id) == len(v5_docs), "v5 has duplicate golden_case_id")
    _require(len(v6_by_id) == len(v6_docs), "v6 has duplicate golden_case_id")
    _require(len(v5_docs) == 125 and len(v6_docs) == 125, "v5/v6 case count must both be 125")

    expected_ids = (set(v5_by_id) - INVALID_SOURCE_IDS) | set(NEW_CASE_IDS)
    _require(set(v6_by_id) == expected_ids, "v6 ID set is not the authorized DROP + ADD set")
    _require(not INVALID_SOURCE_IDS.intersection(v6_by_id), "dropped v5 IDs remain in v6")

    for new_id, spec in NEW_CASE_BY_ID.items():
        row = v6_by_id.get(new_id)
        if row is None:
            _fail(f"missing v6 new case {new_id}")
        _verify_new_case(row, spec)

    unchanged_ids = set(v5_by_id) - INVALID_SOURCE_IDS
    _require(len(unchanged_ids) == 110, "unchanged v5 population is not 110")
    for case_id in unchanged_ids:
        old = v5_by_id[case_id]
        new = v6_by_id[case_id]
        _require(
            _comparable_row(old) == _comparable_row(new),
            f"unchanged case {case_id}: non-version fields changed",
        )
        _require(
            review_identity_hash_for_doc(old) == review_identity_hash_for_doc(new),
            f"unchanged case {case_id}: review identity changed",
        )

    other_ids = {
        case_id for case_id, row in v5_by_id.items() if row.get("event_class") != "ST_TRANSITION"
    }
    _require(len(other_ids) == 75, "v5 non-ST population is not 75")
    _require(other_ids <= unchanged_ids, "a non-ST case was not carried forward")
    for case_id in other_ids:
        _require(
            _comparable_row(v5_by_id[case_id]) == _comparable_row(v6_by_id[case_id]),
            f"other unchanged case {case_id}: semantic fields changed",
        )

    st_rows = [row for row in v6_docs if row.get("event_class") == "ST_TRANSITION"]
    st_identity = {
        (
            str(row.get("provider_symbol")),
            str(row.get("event_effective_date")),
            str(row.get("event_subtype")),
        )
        for row in st_rows
    }
    _require(
        len(st_rows) == 50 and len(st_identity) == 50,
        "v6 ST structural identity is duplicated",
    )
    delist_rows = [row for row in v6_docs if row.get("event_class") == "DELIST"]
    delist_identity = {
        (str(row.get("provider_symbol")), str(row.get("event_effective_date")))
        for row in delist_rows
    }
    _require(
        len(delist_rows) == 20 and len(delist_identity) == 20,
        "v6 DELIST identity is duplicated",
    )
    return v5_by_id, v6_by_id


def _verify_plan(
    plan: dict[str, Any],
    v5_ids: set[str],
    v5_order: list[str],
    v6_by_id: dict[str, dict[str, Any]],
) -> None:
    _require(plan.get("plan_schema") == 1, "rebuild plan schema must be 1")
    _require(plan.get("source_truth_version") == V5_VERSION, "plan source version mismatch")
    _require(plan.get("source_dataset_file") == V5_DATASET, "plan source dataset mismatch")
    _require(plan.get("source_dataset_hash") == V5_HASH, "plan source hash mismatch")
    _require(plan.get("target_truth_version") == V6_VERSION, "plan target version mismatch")
    _require(
        plan.get("operation_summary") == {"KEEP": 110, "REPLACE": 0, "DROP": 15, "ADD": 15},
        "plan operation_summary mismatch",
    )
    operations = plan.get("operations")
    _require(isinstance(operations, list), "plan operations must be a list")
    source_operations = [op for op in operations if isinstance(op, dict) and op.get("op") != "ADD"]
    add_operations = [op for op in operations if isinstance(op, dict) and op.get("op") == "ADD"]
    _require(len(source_operations) == len(v5_ids), "plan source operation count mismatch")
    _require(
        [op.get("golden_case_id") for op in source_operations] == v5_order,
        "plan source operation order/coverage mismatch",
    )
    counts = Counter(str(op.get("op")) for op in source_operations + add_operations)
    _require(
        counts == Counter({"KEEP": 110, "DROP": 15, "ADD": 15}),
        "plan operation counts mismatch",
    )
    drop_ids = {str(op.get("golden_case_id")) for op in source_operations if op.get("op") == "DROP"}
    keep_ids = {str(op.get("golden_case_id")) for op in source_operations if op.get("op") == "KEEP"}
    replace_ids = {
        str(op.get("golden_case_id")) for op in source_operations if op.get("op") == "REPLACE"
    }
    _require(drop_ids == INVALID_SOURCE_IDS, "plan DROP IDs mismatch")
    _require(keep_ids == v5_ids - INVALID_SOURCE_IDS, "plan KEEP IDs mismatch")
    _require(not replace_ids, "v6 plan unexpectedly contains REPLACE operations")
    _require(
        [str(op.get("golden_case_id")) for op in add_operations] == list(NEW_CASE_IDS),
        "plan ADD order/coverage mismatch",
    )
    for op in add_operations:
        case_id = str(op.get("golden_case_id"))
        case = op.get("case")
        _require(isinstance(case, dict), f"plan ADD {case_id}: case object missing")
        row = v6_by_id.get(case_id)
        if row is None:
            _fail(f"plan ADD {case_id}: output case missing")
        for field, value in case.items():
            _require(row.get(field) == value, f"plan ADD {case_id}: case field {field} mismatch")
        _require(op.get("lineage") == case.get("lineage"), f"plan ADD {case_id}: lineage mismatch")


def _verify_carry_forward(
    rows: list[dict[str, Any]],
    v5_by_id: dict[str, dict[str, Any]],
    v6_by_id: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    _require(len(rows) == 125, "carry-forward ledger must contain 125 rows")
    by_old: dict[str, dict[str, Any]] = {}
    expected_map = {case_id: case_id for case_id in v5_by_id if case_id not in INVALID_SOURCE_IDS}
    expected_map.update({spec["old_id"]: spec["new_id"] for spec in NEW_CASES})
    for row in rows:
        old_id = str(row.get("old_case_id", ""))
        _require(old_id and old_id not in by_old, f"carry-forward duplicate old ID {old_id}")
        by_old[old_id] = row
    _require(set(by_old) == set(v5_by_id), "carry-forward old ID coverage mismatch")
    for old_id, new_id in expected_map.items():
        row = by_old[old_id]
        _require(row.get("ledger_schema") == 2, f"carry-forward {old_id}: wrong schema")
        _require(row.get("transition") == "v5_to_v6", f"carry-forward {old_id}: wrong transition")
        _require(row.get("new_case_id") == new_id, f"carry-forward {old_id}: new ID mismatch")
        _require(
            row.get("prior_decision") == "APPROVE",
            f"carry-forward {old_id}: prior decision mismatch",
        )
        _require(
            row.get("hash_contract") == "review_identity_v1_excludes_truth_version_only",
            f"carry-forward {old_id}: wrong hash contract",
        )
        old_row = v5_by_id[old_id]
        new_row = v6_by_id[new_id]
        old_identity = review_identity_hash_for_doc(old_row)
        new_identity = review_identity_hash_for_doc(new_row)
        _require(
            row.get("old_review_identity_hash") == old_identity,
            f"carry-forward {old_id}: old identity hash",
        )
        _require(
            row.get("new_review_identity_hash") == new_identity,
            f"carry-forward {old_id}: new identity hash",
        )
        _require(
            row.get("old_dataset_case_semantic_hash") == old_row.get("case_semantic_hash"),
            f"carry-forward {old_id}: old dataset hash",
        )
        _require(
            row.get("new_dataset_case_semantic_hash") == new_row.get("case_semantic_hash"),
            f"carry-forward {old_id}: new dataset hash",
        )
        eligible = old_id == new_id and old_identity == new_identity
        _require(
            row.get("carry_forward_eligible") is eligible,
            f"carry-forward {old_id}: eligibility was not recomputed",
        )
        _require(
            row.get("new_review_required") is (not eligible),
            f"carry-forward {old_id}: new_review_required mismatch",
        )
    eligible_count = sum(1 for row in rows if row.get("carry_forward_eligible") is True)
    ineligible_count = sum(1 for row in rows if row.get("carry_forward_eligible") is False)
    _require((eligible_count, ineligible_count) == (110, 15), "carry-forward counts must be 110/15")
    return eligible_count, ineligible_count


def _verify_audit(
    rows: list[dict[str, Any]],
    v6_docs: list[dict[str, Any]],
) -> dict[str, int]:
    _require(len(rows) == 50, "GT-H3R2 audit must contain 50 rows")
    st_ids = {
        str(row["golden_case_id"]) for row in v6_docs if row.get("event_class") == "ST_TRANSITION"
    }
    audit_ids = {str(row.get("golden_case_id")) for row in rows}
    _require(audit_ids == st_ids, "GT-H3R2 audit ID set does not match v6 ST set")
    problems = transition_audit_publication_gate(rows, v6_docs)
    _require(not problems, "GT-H3R2 publication gate failed: " + "; ".join(problems[:5]))
    _require(
        Counter(str(row.get("audit_status")) for row in rows) == Counter({"PASS": 50}),
        "GT-H3R2 audit status summary is not PASS=50",
    )
    _require(
        all(row.get("transition_valid") is True for row in rows),
        "GT-H3R2 audit contains a non-valid transition",
    )
    _require(
        all(
            row.get(field, {}).get("status") == "OFFICIAL_SOURCE_REVIEWED"
            for row in rows
            for field in ("pre_state_official_evidence", "effective_state_official_evidence")
        ),
        "GT-H3R2 audit contains unreviewed evidence",
    )
    return {"PASS": 50}


def _verify_correction_text(repo_root: Path, remediation_root: Path) -> None:
    paths = (
        remediation_root / "GT_H3R2_REPLACEMENT_CANDIDATES.md",
        remediation_root / "GT_H3R2_ST_TRANSITION_AUDIT.md",
        remediation_root / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl",
        remediation_root / "v5_to_v6_rebuild_plan.json",
        remediation_root / "GT_H3R2_V6_CANDIDATE_VERIFICATION.md",
        repo_root / "data/golden/provider/amazingdata/golden_cases_v6.jsonl",
    )
    combined: list[str] = []
    for path in paths:
        try:
            combined.append(path.read_text(encoding="utf-8"))
        except OSError as exc:
            _fail(f"cannot read v6 correction artifact {path}: {exc}")
    text = "\n".join(combined)
    stale_abbreviation = "*ST" + "明珠"
    _require(stale_abbreviation not in text, "stale 600382 abbreviation remains")
    _require("*ST广珠" in text, "corrected 600382 abbreviation *ST广珠 is absent")


def verify(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    golden_root = repo_root / GOLDEN_RELATIVE
    remediation_root = repo_root / REMEDIATION_RELATIVE
    v5_manifest_path = golden_root / V5_MANIFEST
    v6_manifest_path = golden_root / V6_MANIFEST
    active_manifest_path = golden_root / "truth_manifest.json"

    active = _read_json(active_manifest_path)
    v5_manifest = _read_json(v5_manifest_path)
    _require(active == v5_manifest, "ACTIVE pointer changed: it must remain byte-equivalent to v5")
    _, v5_docs, _ = _read_dataset(v5_manifest_path, V5_VERSION, V5_DATASET, V5_HASH)
    _validate_compiled_docs(v5_docs, V5_VERSION, "v5")
    v6_payload, v6_docs, v6_cases = _read_dataset(v6_manifest_path, V6_VERSION, V6_DATASET, V6_HASH)
    _validate_compiled_docs(v6_docs, V6_VERSION, "v6")
    v6_manifest = _read_json(v6_manifest_path)
    _verify_manifest_stats(v6_manifest, v6_cases)
    v5_by_id, v6_by_id = _verify_row_sets(v5_docs, v6_docs)

    plan = _read_json(remediation_root / "v5_to_v6_rebuild_plan.json")
    _verify_plan(plan, set(v5_by_id), list(v5_by_id), v6_by_id)
    carry_rows = _read_jsonl(remediation_root / "v5_to_v6_human_review_carry_forward.jsonl")
    eligible_count, ineligible_count = _verify_carry_forward(carry_rows, v5_by_id, v6_by_id)
    audit_rows = _read_jsonl(remediation_root / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl")
    audit_summary = _verify_audit(audit_rows, v6_docs)
    _verify_correction_text(repo_root, remediation_root)

    _require(
        hashlib.sha256(v6_payload).hexdigest() == V6_HASH,
        "v6 payload changed after manifest verification",
    )
    return {
        "v5_truth_version": V5_VERSION,
        "v5_dataset_hash": V5_HASH,
        "v6_truth_version": V6_VERSION,
        "v6_dataset_hash": V6_HASH,
        "active_truth_version": str(active["truth_version"]),
        "case_count": len(v6_docs),
        "st_transition": sum(row.get("event_class") == "ST_TRANSITION" for row in v6_docs),
        "st_add_events": v6_manifest["st_add_events"],
        "st_remove_events": v6_manifest["st_remove_events"],
        "unchanged_other_cases": 75,
        "carry_forward_eligible": eligible_count,
        "carry_forward_not_eligible": ineligible_count,
        "audit_summary": audit_summary,
        "review_summary": v6_manifest["review_summary"],
        "review_seal": "NOT_RUN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify staged GT-H3R2 v6 candidate")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify")
    args = parser.parse_args()
    try:
        summary = verify(args.root)
    except VerificationError as exc:
        print(f"verification error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
