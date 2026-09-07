"""GT-H3R v5 candidate remediation and carry-forward contracts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from ashare_state.spike.golden_store import review_identity_hash_for_doc, semantic_hash_for_doc

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data/golden/provider/amazingdata"
REMEDIATION_ROOT = REPO_ROOT / "docs/golden/gt_h3/remediation"
V4_VERSION = "v4-candidate-20260906"
V4_HASH = "8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b"
V5_VERSION = "v5-candidate-20260907"
V5_HASH = "5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c"


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _run_verifier() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/golden/gt_h3_remediate.py"), "verify"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_committed_v5_remediation_verifier_passes():
    result = _run_verifier()
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary == {
        "carry_forward_eligible": 113,
        "carry_forward_not_eligible": 12,
        "case_count": 125,
        "delta_human_review_cases": 12,
        "review_seal": "NOT_RUN",
        "review_summary": {"COMPILED": 125},
        "v4_dataset_hash": V4_HASH,
        "v4_truth_version": V4_VERSION,
        "v5_dataset_hash": V5_HASH,
        "v5_truth_version": V5_VERSION,
    }


def test_v4_is_immutable_and_v5_scope_is_exact():
    v4_bytes = (GOLDEN_ROOT / "golden_cases_v4.jsonl").read_bytes()
    assert hashlib.sha256(v4_bytes).hexdigest() == V4_HASH
    assert (
        json.loads((GOLDEN_ROOT / "truth_manifest_v4.json").read_text(encoding="utf-8"))[
            "dataset_hash"
        ]
        == V4_HASH
    )

    old_rows = _jsonl(GOLDEN_ROOT / "golden_cases_v4.jsonl")
    new_rows = _jsonl(GOLDEN_ROOT / "golden_cases_v5.jsonl")
    old_by_id = {row["golden_case_id"]: row for row in old_rows}
    new_by_id = {row["golden_case_id"]: row for row in new_rows}
    rekeys = {
        "GT-LIMIT-STARNO-20200723": "GT-LIMIT-STAR20-688981-20200723",
        "GT-H2-ST-ST_ADD-300965-20240429": "GT-H2-ST-ST_ADD-300965-20240426",
    }
    rejected = {
        "GT-LIMIT-CN20-300015",
        "GT-LIMIT-CN20-300059",
        "GT-LIMIT-CN20-300124",
        "GT-LIMIT-CN20-300274",
        "GT-LIMIT-CN20-300750",
        "GT-LIMIT-ST5-600518-20190603",
        "GT-LIMIT-ST5-600518-20191028",
        "GT-LIMIT-IPO44-601995",
        "GT-LIMIT-IPO44-605499",
        "GT-H2-ST-ST_ADD-002022-20220506",
        *rekeys,
    }
    assert len(old_rows) == len(new_rows) == 125
    assert set(new_by_id) == {rekeys.get(case_id, case_id) for case_id in old_by_id}
    for old_id, old in old_by_id.items():
        new = new_by_id[rekeys.get(old_id, old_id)]
        if old_id not in rejected:
            assert review_identity_hash_for_doc(old) == review_identity_hash_for_doc(new)
            assert old["expected_fields"] == new["expected_fields"]
            assert old["source_ref"] == new["source_ref"]
        assert new["review_status"] == "COMPILED"
        assert not new["reviewed_by"] and not new["reviewed_at"] and not new["review_note"]

    star = new_by_id[rekeys["GT-LIMIT-STARNO-20200723"]]
    assert (
        star["provider_symbol"],
        star["trade_date"],
        star["event_id"],
        star["expected_fields"],
    ) == (
        "688981.SH",
        "20200723",
        "REGIME-STAR-20",
        {"PRICE_HIGH_LMT_RATE": 0.2},
    )
    st = new_by_id[rekeys["GT-H2-ST-ST_ADD-300965-20240429"]]
    assert (st["trade_date"], st["event_effective_date"], st["event_subtype"]) == (
        "20240426",
        "20240426",
        "ST_ADD",
    )


def test_review_identity_is_version_neutral_but_dataset_seal_is_not():
    row = _jsonl(GOLDEN_ROOT / "golden_cases_v4.jsonl")[0]
    next_version = dict(row, truth_version=V5_VERSION)
    assert review_identity_hash_for_doc(row) == review_identity_hash_for_doc(next_version)
    assert semantic_hash_for_doc(row) != semantic_hash_for_doc(next_version)
    changed_source = dict(next_version, source_ref=next_version["source_ref"] + "?changed")
    assert review_identity_hash_for_doc(next_version) != review_identity_hash_for_doc(
        changed_source
    )


def test_governed_candidate_rebuild_reproduces_committed_v5(tmp_path: Path):
    golden_root = tmp_path / "golden"
    golden_root.mkdir(parents=True)
    for name in ("golden_cases_v4.jsonl", "truth_manifest_v4.json"):
        shutil.copy2(GOLDEN_ROOT / name, golden_root / name)
    shutil.copy2(GOLDEN_ROOT / "truth_manifest_v4.json", golden_root / "truth_manifest.json")
    plan = tmp_path / "v4_to_v5_rebuild_plan.json"
    shutil.copy2(REMEDIATION_ROOT / plan.name, plan)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/golden/candidate.py"),
            "--root",
            str(golden_root),
            "rebuild",
            "--plan",
            str(plan),
            "--truth-version",
            V5_VERSION,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (golden_root / "golden_cases_v5.jsonl").read_bytes() == (
        GOLDEN_ROOT / "golden_cases_v5.jsonl"
    ).read_bytes()
    assert json.loads(
        (golden_root / "truth_manifest_v5.json").read_text(encoding="utf-8")
    ) == json.loads((GOLDEN_ROOT / "truth_manifest_v5.json").read_text(encoding="utf-8"))
