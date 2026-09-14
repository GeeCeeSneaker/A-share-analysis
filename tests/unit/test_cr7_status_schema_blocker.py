"""Offline regressions for the bounded CR-7 status-schema blocker probe."""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

_ROOT = Path(__file__).parents[2]
_SCRIPT = run_path(str(_ROOT / "scripts" / "spike" / "cr7_status_schema_blocker.py"))
_assess_shape = _SCRIPT["_assess_shape"]
_callback_summary = _SCRIPT["_callback_summary"]


def test_kdataempty_empty_shape_stays_blocked_and_never_becomes_status_zero() -> None:
    callback = _callback_summary(
        [
            {"status": "kDataEmpty", "data_is_none": True},
            {"status": "kDataEmpty", "data_is_none": True},
        ]
    )
    assessment = _assess_shape(
        callback,
        {"type": "DataFrame", "row_count": 0, "column_count": 0, "columns": []},
        {"row_count": 0, "table_count": 1},
    )

    assert assessment["outcome"] == "STOP(BLOCKED)"
    assert assessment["reason_code"] == "NO_POSITIVE_PROVIDER_SEMANTIC_RULE"
    assert assessment["shape_attribution"]["raw_writer_shape_preserved"] is True
    assert assessment["shape_attribution"]["attribution"] == (
        "API_OR_RUNTIME_EMPTY_RESPONSE_NOT_ADAPTER_COLUMN_LOSS"
    )
    assert assessment["semantic_assessment"]["empty_response_means_is_susp_sec_zero"] is False
    assert assessment["semantic_assessment"]["empty_response_means_no_status_change"] is False


def test_non_kdataempty_callback_does_not_claim_shape_attribution() -> None:
    assessment = _assess_shape(
        {
            "event_count": 1,
            "status_counts": {"OTHER": 1},
            "data_is_none_count": 1,
        },
        {"type": "DataFrame", "row_count": 0, "column_count": 0, "columns": []},
        {"row_count": 0, "table_count": 1},
    )

    assert assessment["shape_attribution"]["attribution"] == "NOT_ESTABLISHED"
    assert assessment["outcome"] == "STOP(BLOCKED)"


def test_callback_summary_contains_counts_only() -> None:
    summary = _callback_summary(
        [{"status": "kDataEmpty", "data_is_none": True, "data_shape": {"type": "None"}}]
    )

    assert summary == {
        "event_count": 1,
        "status_counts": {"kDataEmpty": 1},
        "data_is_none_count": 1,
        "data_non_none_count": 0,
    }
