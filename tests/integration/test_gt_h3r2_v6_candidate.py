from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.golden.gt_h3r2_v6_verify import verify

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data/golden/provider/amazingdata"
REMEDIATION_ROOT = REPO_ROOT / "docs/golden/gt_h3/remediation"


def test_staged_v6_verifier_reports_exact_invariants() -> None:
    summary = verify(REPO_ROOT)
    assert summary == {
        "v5_truth_version": "v5-candidate-20260907",
        "v5_dataset_hash": ("5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c"),
        "v6_truth_version": "v6-candidate-20260908",
        "v6_dataset_hash": ("d11b6cd0314e9a1b63e1728668f61bfacc29f97b255f00f40fcdb98e9d0b1b0c"),
        "active_truth_version": "v5-candidate-20260907",
        "case_count": 125,
        "st_transition": 50,
        "st_add_events": 38,
        "st_remove_events": 12,
        "unchanged_other_cases": 75,
        "carry_forward_eligible": 110,
        "carry_forward_not_eligible": 15,
        "audit_summary": {"PASS": 50},
        "review_summary": {"COMPILED": 125},
        "review_seal": "NOT_RUN",
    }


def test_candidate_rebuild_reproduces_committed_v6(tmp_path: Path) -> None:
    temporary_golden_root = tmp_path / "golden"
    temporary_golden_root.mkdir()
    shutil.copy2(
        GOLDEN_ROOT / "golden_cases_v5.jsonl",
        temporary_golden_root / "golden_cases_v5.jsonl",
    )
    shutil.copy2(
        GOLDEN_ROOT / "truth_manifest_v5.json",
        temporary_golden_root / "truth_manifest_v5.json",
    )
    shutil.copy2(
        GOLDEN_ROOT / "truth_manifest.json",
        temporary_golden_root / "truth_manifest.json",
    )
    plan_path = REMEDIATION_ROOT / "v5_to_v6_rebuild_plan.json"
    audit_path = REMEDIATION_ROOT / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/golden/candidate.py"),
        "--root",
        str(temporary_golden_root),
        "rebuild",
        "--plan",
        str(plan_path),
        "--truth-version",
        "v6-candidate-20260908",
        "--transition-audit",
        str(audit_path),
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (temporary_golden_root / "golden_cases_v6.jsonl").read_bytes() == (
        GOLDEN_ROOT / "golden_cases_v6.jsonl"
    ).read_bytes()
    assert (temporary_golden_root / "truth_manifest_v6.json").read_bytes() == (
        GOLDEN_ROOT / "truth_manifest_v6.json"
    ).read_bytes()
    assert json.loads(
        (temporary_golden_root / "truth_manifest.json").read_text(encoding="utf-8")
    ) == json.loads((GOLDEN_ROOT / "truth_manifest_v6.json").read_text(encoding="utf-8"))
