"""Offline contract tests for the bounded CR-7 real-source preflight."""

from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

_ROOT = Path(__file__).parents[2]
_PREFLIGHT = run_path(str(_ROOT / "scripts" / "spike" / "cr7_authoritative_history_preflight.py"))
_WINDOWS = _PREFLIGHT["_WINDOWS"]
_base_report = _PREFLIGHT["_base_report"]
_calendar_summary = _PREFLIGHT["_calendar_summary"]
_code_list_summary = _PREFLIGHT["_code_list_summary"]
_kline_summary = _PREFLIGHT["_kline_summary"]
_not_run_month = _PREFLIGHT["_not_run_month"]


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        result = {str(key).lower() for key in value}
        for child in value.values():
            result.update(_all_keys(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result.update(_all_keys(child))
        return result
    return set()


def test_preflight_scope_is_fixed_to_the_three_scheduler_months() -> None:
    assert _WINDOWS == (
        ("development", 2020, 1),
        ("validation_a", 2024, 1),
        ("holdout", 2026, 1),
    )
    report = _base_report(code_head="a" * 40, repo_root=Path(__file__).parents[2])
    assert [(item["split"], item["year"], item["month"]) for item in report["scope"]] == list(
        _WINDOWS
    )
    assert report["preflight_verdict"] == "FAIL_CLOSED_BLOCKED"
    assert "600519.SH" not in json.dumps(report, ensure_ascii=False)
    assert "TGW_PASSWORD" not in json.dumps(report, ensure_ascii=False)
    assert not {"password", "cookie", "access_token", "secret_key"}.intersection(_all_keys(report))


def test_observation_summaries_hash_values_without_disclosing_them() -> None:
    code_summary = _code_list_summary(["600519.SH", "000001.SZ", "600519.SH"])
    assert code_summary["security_count"] == 2
    assert "600519.SH" not in json.dumps(code_summary)

    calendar_summary, window_days = _calendar_summary(
        [20200102, 20200103, 20240102], begin=20200101, end=20200131
    )
    assert window_days == [20200102, 20200103]
    assert calendar_summary["window_trading_day_count"] == 2


def test_missing_credentials_and_invalid_calendar_remain_fail_closed() -> None:
    report = _not_run_month("development", 2020, 1, "MISSING_TGW_ENV")
    assert report["status"] == "NOT_RUN"
    assert report["authoritative_completeness"]["status"] == "BLOCKED"
    assert report["materializer_gate"]["status"] == "NOT_ENTERED_FAIL_CLOSED"

    summary, days = _calendar_summary(["not-a-date"], begin=20200101, end=20200131)
    assert summary["status"] == "UNEXPECTED_SHAPE"
    assert days == []


def test_kline_summary_retains_only_shape_counts_and_hashes() -> None:
    import polars as pl

    summary = _kline_summary(
        {
            "600519.SH": pl.DataFrame({"TRADE_DATE": [20200102], "CLOSE": [100.0]}),
            "000001.SZ": None,
        }
    )
    assert summary["status"] == "OK"
    assert summary["member_count"] == 2
    assert summary["null_table_count"] == 1
    assert "600519.SH" not in json.dumps(summary)
