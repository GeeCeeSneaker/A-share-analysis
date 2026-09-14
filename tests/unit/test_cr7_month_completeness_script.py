"""Offline tests for the CR-7 bounded diagnostic scheduler gate."""

from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

import pytest

from ashare_state.providers.amazingdata.month_completeness import (
    AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION,
    AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION,
)

_ROOT = Path(__file__).parents[2]
_SCRIPT = run_path(str(_ROOT / "scripts" / "spike" / "cr7_month_completeness_semantics.py"))
_stage_a_gate = _SCRIPT["_stage_a_gate"]


def _stage_a_report(status: str) -> dict[str, object]:
    return {
        "schema": "cr7.month_completeness_semantics.v1",
        "stage": "A",
        "scope": {"month": "2024-01"},
        "code_head": "a" * 40,
        "evaluation": {
            "status": status,
            "rule_version": AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION,
            "applicability_semantics_version": AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION,
        },
    }


def test_stage_b_gate_rejects_fail_closed_stage_a(tmp_path: Path) -> None:
    path = tmp_path / "stage-a.json"
    path.write_text(json.dumps(_stage_a_report("FAIL_CLOSED")), encoding="utf-8")

    with pytest.raises(ValueError, match="STAGE_A_EVALUATION_NOT_ACCEPTED"):
        _stage_a_gate(path)


def test_stage_b_gate_accepts_only_pass_stage_a(tmp_path: Path) -> None:
    path = tmp_path / "stage-a.json"
    path.write_text(json.dumps(_stage_a_report("PASS")), encoding="utf-8")

    gate = _stage_a_gate(path)

    assert gate["status"] == "ACCEPTED_FOR_STAGE_B_BOUNDARY"
    assert gate["evaluation_status"] == "PASS"


def test_stage_b_gate_rejects_old_applicability_semantics(tmp_path: Path) -> None:
    path = tmp_path / "stage-a.json"
    report = _stage_a_report("PASS")
    evaluation = report["evaluation"]
    assert isinstance(evaluation, dict)
    evaluation["applicability_semantics_version"] = "amazingdata-hist-code-list-exact-session-v1"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="STAGE_A_APPLICABILITY_VERSION_MISMATCH"):
        _stage_a_gate(path)
