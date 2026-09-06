"""The human-facing GT-H3 table must stay aligned with the 125-case bundle."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = REPO_ROOT / "docs/golden/gt_h3/review_bundle_index.jsonl"
TABLE_PATH = REPO_ROOT / "docs/golden/gt_h3/GT_H3_HUMAN_REVIEW_TABLE.md"
DATA_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|")


def _index_case_ids() -> list[str]:
    groups = [json.loads(line) for line in INDEX_PATH.read_text(encoding="utf-8").splitlines()]
    return [
        str(case["case"]) for group in groups for case in group["case_specific_expected_semantics"]
    ]


def test_human_review_table_covers_each_bundle_case_once():
    assert TABLE_PATH.is_file()
    rows = []
    for line in TABLE_PATH.read_text(encoding="utf-8").splitlines():
        match = DATA_ROW.match(line)
        if match:
            rows.append((int(match.group(1)), match.group(2)))

    assert len(rows) == 125
    assert [number for number, _ in rows] == list(range(1, 126))
    table_case_ids = [case_id for _, case_id in rows]
    index_case_ids = _index_case_ids()
    assert len(set(table_case_ids)) == 125
    assert set(table_case_ids) == set(index_case_ids)


def test_human_review_table_exposes_official_locator_and_simple_feedback_fields():
    lines = TABLE_PATH.read_text(encoding="utf-8").splitlines()
    data_lines = [line for line in lines if DATA_ROW.match(line)]

    assert len(data_lines) == 125
    assert all("打开官方原文" in line for line in data_lines)
    assert all(len(line.split("|")) >= 15 for line in data_lines)
