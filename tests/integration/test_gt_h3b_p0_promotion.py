"""GT-H3B-P0 existing-candidate promotion and fail-closed tests."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import GoldenTruthStore

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_GOLDEN = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
REMEDIATION_ROOT = REPO_ROOT / "docs" / "golden" / "gt_h3" / "remediation"
CANDIDATE_SCRIPT = REPO_ROOT / "scripts" / "golden" / "candidate.py"

V5_VERSION = "v5-candidate-20260907"
V6_VERSION = "v6-candidate-20260908"


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "golden"
    root.mkdir()
    for name in (
        "golden_cases_v4.jsonl",
        "truth_manifest_v4.json",
        "golden_cases_v5.jsonl",
        "truth_manifest_v5.json",
        "golden_cases_v6.jsonl",
        "truth_manifest_v6.json",
        "truth_manifest.json",
    ):
        shutil.copy2(REPO_GOLDEN / name, root / name)
    return root


def _run_promotion(
    root: Path,
    *,
    plan: Path | None = None,
    carry_forward: Path | None = None,
    transition_audit: Path | None = None,
    truth_version: str = V6_VERSION,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CANDIDATE_SCRIPT),
            "--root",
            str(root),
            "promote-existing",
            "--truth-version",
            truth_version,
            "--plan",
            str(plan or (REMEDIATION_ROOT / "v5_to_v6_rebuild_plan.json")),
            "--carry-forward",
            str(carry_forward or (REMEDIATION_ROOT / "v5_to_v6_human_review_carry_forward.jsonl")),
            "--transition-audit",
            str(transition_audit or (REMEDIATION_ROOT / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl")),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _load_candidate_module():
    spec = importlib.util.spec_from_file_location("gt_h3b_candidate", CANDIDATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_v6_promotion_is_idempotent_and_preserves_versioned_bytes(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    versioned_names = (
        "golden_cases_v4.jsonl",
        "truth_manifest_v4.json",
        "golden_cases_v5.jsonl",
        "truth_manifest_v5.json",
        "golden_cases_v6.jsonl",
        "truth_manifest_v6.json",
    )
    before = {name: (root / name).read_bytes() for name in versioned_names}
    assert (root / "truth_manifest.json").read_bytes() == before["truth_manifest_v5.json"]

    first = _run_promotion(root)
    assert first.returncode == 0, first.stderr
    assert "promoted existing candidate to ACTIVE" in first.stdout
    assert (root / "truth_manifest.json").read_bytes() == before["truth_manifest_v6.json"]
    assert {name: (root / name).read_bytes() for name in versioned_names} == before

    second = _run_promotion(root)
    assert second.returncode == 0, second.stderr
    assert "promotion no-op" in second.stdout
    assert (root / "truth_manifest.json").read_bytes() == before["truth_manifest_v6.json"]


@pytest.mark.parametrize(
    "tampered_name",
    ["golden_cases_v6.jsonl", "truth_manifest_v6.json", "golden_cases_v4.jsonl"],
)
def test_tampered_immutable_bytes_fail_closed(tmp_path: Path, tampered_name: str) -> None:
    root = _make_root(tmp_path)
    victim = root / tampered_name
    victim.write_bytes(victim.read_bytes() + b"\n")
    active_before = (root / "truth_manifest.json").read_bytes()

    result = _run_promotion(root)

    assert result.returncode != 0
    assert (root / "truth_manifest.json").read_bytes() == active_before


def test_wrong_active_pointer_fails_closed(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    active = root / "truth_manifest.json"
    active.write_text('{"truth_version":"wrong-active"}', encoding="utf-8")
    active_before = active.read_bytes()

    result = _run_promotion(root)

    assert result.returncode != 0
    assert active.read_bytes() == active_before


def test_plan_set_drift_fails_closed(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    plan = tmp_path / "drifted-plan.json"
    payload = json.loads((REMEDIATION_ROOT / "v5_to_v6_rebuild_plan.json").read_text(encoding="utf-8"))
    drop = next(operation for operation in payload["operations"] if operation["op"] == "DROP")
    drop["op"] = "KEEP"
    plan.write_text(json.dumps(payload), encoding="utf-8")
    active_before = (root / "truth_manifest.json").read_bytes()

    result = _run_promotion(root, plan=plan)

    assert result.returncode != 0
    assert (root / "truth_manifest.json").read_bytes() == active_before


def test_carry_forward_drift_fails_closed(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    carry = tmp_path / "drifted-carry.jsonl"
    rows = [
        json.loads(line)
        for line in (REMEDIATION_ROOT / "v5_to_v6_human_review_carry_forward.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    rows[0]["carry_forward_eligible"] = False
    carry.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    active_before = (root / "truth_manifest.json").read_bytes()

    result = _run_promotion(root, carry_forward=carry)

    assert result.returncode != 0
    assert (root / "truth_manifest.json").read_bytes() == active_before


def test_audit_49_of_50_fails_closed(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    audit = tmp_path / "short-audit.jsonl"
    lines = (
        (REMEDIATION_ROOT / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    audit.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    active_before = (root / "truth_manifest.json").read_bytes()

    result = _run_promotion(root, transition_audit=audit)

    assert result.returncode != 0
    assert (root / "truth_manifest.json").read_bytes() == active_before


def test_duplicate_st_identity_fails_closed() -> None:
    module = _load_candidate_module()
    cases, _ = GoldenTruthStore(REPO_GOLDEN).load_bound(
        "golden_cases_v6.jsonl",
        V6_VERSION,
        "0b3952f9f82ee4f6a55a7f060c47af3cc781b0054ed1f83b5868246c0642a343",
    )
    st_cases = [case for case in cases if case.event_class == "ST_TRANSITION"]
    duplicate = replace(
        st_cases[1],
        provider_symbol=st_cases[0].provider_symbol,
        event_effective_date=st_cases[0].event_effective_date,
        event_subtype=st_cases[0].event_subtype,
    )
    mutated = [
        duplicate if case.golden_case_id == duplicate.golden_case_id else case for case in cases
    ]
    manifest = json.loads((REPO_GOLDEN / "truth_manifest_v6.json").read_text(encoding="utf-8"))

    with pytest.raises(module.CandidateError, match="recomputation distinct_events"):
        module._validate_promotion_stats(manifest, mutated, "v6")


def test_failed_pointer_write_keeps_old_active_pointer(tmp_path: Path, monkeypatch) -> None:
    root = _make_root(tmp_path)
    module = _load_candidate_module()
    monkeypatch.setattr(module, "GOLDEN_ROOT", root)
    active_before = (root / "truth_manifest.json").read_bytes()

    def fail_pointer_write(manifest: dict) -> None:
        raise OSError("injected pointer write failure")

    monkeypatch.setattr(module, "_atomic_active_pointer", fail_pointer_write)

    with pytest.raises(module.CandidateError, match="promotion failed atomically"):
        module.cmd_promote_existing(
            V6_VERSION,
            REMEDIATION_ROOT / "v5_to_v6_rebuild_plan.json",
            REMEDIATION_ROOT / "v5_to_v6_human_review_carry_forward.jsonl",
            REMEDIATION_ROOT / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl",
        )
    assert (root / "truth_manifest.json").read_bytes() == active_before
