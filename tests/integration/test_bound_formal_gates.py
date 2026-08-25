"""R4-A2.3 P0-05: run-bound golden gates (audit section 7).

All FORMAL golden gates are bound-aware:
    quantity_gate(cases, manifest)
    event_coverage_gate(cases, manifest)
    review_gate(cases, manifest)
    production_formal_gate(bound_cases, bound_manifest)

RUNNING/RESUME/CLOSE/VERDICT/REPLAY use ONLY the run-bound dataset.
Adversarial scenarios (audit section 7.4 - MANDATORY):
  - an ACTIVE advance must NOT affect a historical run's verdict
  - tampering a BOUND artifact must BLOCK the verdict
  - tampering/advancing the ACTIVE dataset must NOT leak into a healthy
    run-bound verdict
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import (
    GoldenTruthStore,
    semantic_hash_of,
)

REPO_GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden" / "provider" / "amazingdata"

_NOW = "2026-08-24T00:00:00+00:00"


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "golden"
    shutil.copytree(REPO_GOLDEN, root)
    monkeypatch.setattr("ashare_state.spike.golden_store.GOLDEN_ROOT", root)
    monkeypatch.chdir(tmp_path)
    return root


def _make_reviewed_version(root: Path, version: str) -> str:
    """Create a fully-REVIEWED sibling dataset version (simulating the
    completed human review workflow) and repoint ACTIVE at it."""
    src = (
        root
        / json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))["dataset_file"]
    )
    evidence_dir = root / "evidence" / "reviewed"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []
    review_summary: dict[str, int] = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        artifact_bytes = f"official-source::{doc['golden_case_id']}".encode()
        artifact_name = f"{doc['golden_case_id']}.txt"
        (evidence_dir / artifact_name).write_bytes(artifact_bytes)
        doc.update(
            {
                "truth_version": version,
                "review_status": "REVIEWED",
                "reviewed_by": "human-reviewer",
                "reviewed_at": _NOW,
                "source_artifact_ref": f"reviewed/{artifact_name}",
                "source_artifact_hash": hashlib.sha256(artifact_bytes).hexdigest(),
                "source_artifact_kind": "OTHER_OFFICIAL",
                "source_retrieved_at": _NOW,
            }
        )
        # recompute the semantic seal (it covers source_artifact_hash)
        from ashare_state.spike.golden_store import _case_from_doc

        case = _case_from_doc(doc, version)
        doc["case_semantic_hash"] = semantic_hash_of(case)
        review_summary["REVIEWED"] = review_summary.get("REVIEWED", 0) + 1
        out_lines.append(json.dumps(doc, ensure_ascii=False, sort_keys=True))
    dataset_name = f"golden_cases_{version}.jsonl"
    (root / dataset_name).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    dataset_hash = hashlib.sha256((root / dataset_name).read_bytes()).hexdigest()
    counts: dict[str, int] = {}
    for line in out_lines:
        doc = json.loads(line)
        counts[doc["case_type"]] = counts.get(doc["case_type"], 0) + 1
    manifest = {
        "truth_version": version,
        "dataset_file": dataset_name,
        "dataset_hash": dataset_hash,
        "case_count": len(out_lines),
        "counts_by_type": counts,
        "review_summary": review_summary,
        "distinct_events": {},
        "distinct_securities": {},
    }
    (root / "truth_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8", newline="\n"
    )
    return dataset_name


class TestBoundFormalGates:
    def test_gates_accept_bound_dataset_explicitly(self, golden_env: Path):
        """The gates re-verify whatever (cases, manifest) they are handed:
        ACTIVE (no args) and BOUND (explicit args) both work."""
        store = GoldenTruthStore(golden_env)
        active_cases, active_manifest = store.load()
        problems = store.production_formal_gate(active_cases, active_manifest)
        # v3 candidate is COMPILED -> review gate must flag it (fail closed)
        assert any("not fully human-reviewed" in p for p in problems)
        assert store.quantity_gate(active_cases, active_manifest) == []

    def test_active_advance_never_leaks_into_bound_verdict(self, golden_env: Path):
        """Adversarial: a run bound to a REVIEWED dataset evaluates its
        formal gates over the BOUND data - before AND after ACTIVE
        advances/regresses. The verdict never follows the pointer."""
        reviewed_file = _make_reviewed_version(golden_env, "v4-reviewed")
        store = GoldenTruthStore(golden_env)
        bound_cases, bound_manifest = store.load_bound(
            dataset_file=reviewed_file,
            truth_version="v4-reviewed",
            dataset_hash=hashlib.sha256((golden_env / reviewed_file).read_bytes()).hexdigest(),
        )
        bound_verdict_1 = store.production_formal_gate(bound_cases, bound_manifest)
        # the BOUND dataset is fully REVIEWED: the review complaint is gone
        # (it would be present if the gate read the ACTIVE COMPILED set)
        assert not any("not fully human-reviewed" in p for p in bound_verdict_1)
        # NOW advance ACTIVE back to the COMPILED v3 candidate
        shutil.copy(REPO_GOLDEN / "truth_manifest.json", golden_env / "truth_manifest.json")
        bound_verdict_2 = store.production_formal_gate(bound_cases, bound_manifest)
        # identical result: the ACTIVE advance changed nothing for the
        # bound run (no leakage in either direction)
        assert bound_verdict_2 == bound_verdict_1
        assert not any("not fully human-reviewed" in p for p in bound_verdict_2)

    def test_bound_compiled_state_blocks_even_when_active_is_reviewed(self, golden_env: Path):
        """Reverse direction: a run bound to the COMPILED candidate must
        fail its formal gate even after ACTIVE becomes a REVIEWED version
        (no ACTIVE-success leakage into an unreviewed run)."""
        from ashare_state.spike.golden_store import GoldenTruthStore as Store

        compiled_store = Store(golden_env)
        bound_cases, bound_manifest = compiled_store.load()
        assert bound_manifest.review_summary.get("REVIEWED", 0) == 0
        _make_reviewed_version(golden_env, "v4-reviewed")
        # ACTIVE is now REVIEWED, but the BOUND dataset stays COMPILED
        problems = compiled_store.production_formal_gate(bound_cases, bound_manifest)
        assert any("not fully human-reviewed" in p for p in problems)

    def test_bound_artifact_tamper_blocks_verdict_gate(self, golden_env: Path):
        """Adversarial: tampering a BOUND case's source artifact must block
        the formal gate (the artifact hash no longer matches the bytes)."""
        reviewed_file = _make_reviewed_version(golden_env, "v4-reviewed")
        store = GoldenTruthStore(golden_env)
        bound_cases, bound_manifest = store.load_bound(
            dataset_file=reviewed_file,
            truth_version="v4-reviewed",
            dataset_hash=hashlib.sha256((golden_env / reviewed_file).read_bytes()).hexdigest(),
        )
        before = store.production_formal_gate(bound_cases, bound_manifest)
        assert not any("source artifact hash mismatch" in p for p in before)
        # tamper ONE bound artifact's bytes
        artifacts = sorted((golden_env / "evidence" / "reviewed").glob("*.txt"))
        victim = artifacts[0]
        victim.write_bytes(b"tampered-bytes")
        problems = store.production_formal_gate(bound_cases, bound_manifest)
        assert any("source artifact hash mismatch" in p for p in problems)

    def test_active_tamper_does_not_affect_healthy_bound_run(self, golden_env: Path):
        """Adversarial: corrupting the ACTIVE dataset (breaking the pointer
        hash) must NOT affect a healthy run-bound gate evaluation."""
        reviewed_file = _make_reviewed_version(golden_env, "v4-reviewed")
        store = GoldenTruthStore(golden_env)
        bound_cases, bound_manifest = store.load_bound(
            dataset_file=reviewed_file,
            truth_version="v4-reviewed",
            dataset_hash=hashlib.sha256((golden_env / reviewed_file).read_bytes()).hexdigest(),
        )
        bound_verdict_1 = store.production_formal_gate(bound_cases, bound_manifest)
        # corrupt the ACTIVE dataset + pointer (an ACTIVE-side attack)
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        (golden_env / active["dataset_file"]).write_text("corrupted\n", encoding="utf-8")
        # ACTIVE is now broken (store.load() would raise), but the BOUND
        # gate keeps evaluating the healthy bound dataset unchanged
        bound_verdict_2 = store.production_formal_gate(bound_cases, bound_manifest)
        assert bound_verdict_2 == bound_verdict_1

    def test_bound_dataset_file_tamper_raises_on_load_bound(self, golden_env: Path):
        """Tampering the bound DATASET FILE itself is detected at load."""
        reviewed_file = _make_reviewed_version(golden_env, "v4-reviewed")
        store = GoldenTruthStore(golden_env)
        bound_hash = hashlib.sha256((golden_env / reviewed_file).read_bytes()).hexdigest()
        with (golden_env / reviewed_file).open("a", encoding="utf-8") as handle:
            handle.write("\n")
        from ashare_state.spike.golden_store import GoldenTruthError

        with pytest.raises(GoldenTruthError, match="hash mismatch"):
            store.load_bound(
                dataset_file=reviewed_file,
                truth_version="v4-reviewed",
                dataset_hash=bound_hash,
            )

    def test_event_coverage_gate_uses_bound_dataset(self, golden_env: Path):
        """The bound invocation evaluates exactly the dataset it is handed
        (same dataset -> same verdict as the ACTIVE path)."""
        store = GoldenTruthStore(golden_env)
        cases, manifest = store.load()
        problems = store.event_coverage_gate(cases, manifest)
        active_problems = store.event_coverage_gate()
        assert problems == active_problems


class TestTimestampUtil:
    def test_fixture_timestamp_is_iso(self):
        datetime.fromisoformat(_NOW)
