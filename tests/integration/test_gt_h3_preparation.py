"""GT-H3A bundle preparation remains pre-review and cannot mutate truth."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data/golden/provider/amazingdata"
PACKET = REPO_ROOT / "docs/golden/gt_h2/review_packet_index.jsonl"
PREPARE_PATH = REPO_ROOT / "scripts/golden/gt_h3_prepare.py"


def _module():
    spec = importlib.util.spec_from_file_location("gt_h3_prepare", PREPARE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load GT-H3 preparation helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_bundle_groups_all_compiled_cases_without_review(tmp_path: Path):
    module = _module()
    summary = module.prepare_bundle(GOLDEN_ROOT, PACKET, tmp_path / "gt_h3")

    assert summary["truth_version"] == "v5-candidate-20260907"
    assert summary["dataset_hash"] == (
        "5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c"
    )
    assert summary["case_count"] == 125
    assert summary["artifact_group_count"] > 0
    assert summary["retrieval_status"] == "PENDING_HUMAN_REVIEW"

    output_dir = tmp_path / "gt_h3"
    groups = [
        json.loads(line)
        for line in (output_dir / "review_bundle_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    decisions = [
        json.loads(line)
        for line in (output_dir / "review_decision_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert sum(group["case_count"] for group in groups) == 125
    assert len(decisions) == 125
    assert {row["decision"] for row in decisions} == {""}
    assert {row["review_note"] for row in decisions} == {""}
    assert all("expect_fields" not in row for row in decisions)
    assert all(group["retrieval_status"] == "PENDING_HUMAN_REVIEW" for group in groups)
    assert all(group["preflight_sha256"] is None for group in groups)


def test_prepare_bundle_rejects_packet_missing_case(tmp_path: Path):
    module = _module()
    packet_copy = tmp_path / "packet.jsonl"
    rows = PACKET.read_text(encoding="utf-8").splitlines()
    packet_copy.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(module.PreparationError, match="cover ACTIVE exactly once"):
        module.prepare_bundle(GOLDEN_ROOT, packet_copy, tmp_path / "gt_h3")


def test_prepare_bundle_rejects_reviewed_candidate(tmp_path: Path):
    module = _module()
    root = tmp_path / "golden"
    root.mkdir()
    for name in ("truth_manifest.json", "golden_cases_v5.jsonl"):
        shutil.copy2(GOLDEN_ROOT / name, root / name)
    dataset = root / "golden_cases_v5.jsonl"
    lines = dataset.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["review_status"] = "REVIEWED"
    lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    dataset.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    manifest = json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))
    manifest["dataset_hash"] = __import__("hashlib").sha256(dataset.read_bytes()).hexdigest()
    (root / "truth_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    with pytest.raises(module.PreparationError, match="must remain COMPILED"):
        module.prepare_bundle(root, PACKET, tmp_path / "gt_h3")


def test_prepare_bundle_refuses_to_overwrite_versioned_snapshot(tmp_path: Path):
    module = _module()
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    (snapshot_dir / "GT_H3_REVIEW_BUNDLE.md").write_text(
        "ACTIVE truth version: `v4-candidate-20260906`\n",
        encoding="utf-8",
        newline="\n",
    )
    module.DEFAULT_OUTPUT_DIR = snapshot_dir

    with pytest.raises(module.PreparationError, match="refusing to overwrite"):
        module.prepare_bundle(GOLDEN_ROOT, PACKET, snapshot_dir)


def test_gt_h3_seal_manifest_rejects_expect_fields_mutation():
    module = _module()
    valid = [{"case": "GT-1", "artifact": "evidence.pdf", "kind": "SSE_ANNOUNCEMENT", "note": "ok"}]
    module.validate_seal_manifest_entries(valid, ["GT-1"])

    mutated = [dict(valid[0], expect_fields={"IS_ST_SEC": False})]
    with pytest.raises(module.PreparationError, match="forbidden fields.*expect_fields"):
        module.validate_seal_manifest_entries(mutated, ["GT-1"])
