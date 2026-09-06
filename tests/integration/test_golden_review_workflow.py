"""Golden review workflow contract tests (R4-A2 sections 6-8, review scope)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import (
    GoldenTruthStore,
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    semantic_hash_for_doc,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_GOLDEN = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
V3_VERSION = "v3-candidate-20260822"
V3_HASH = "ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e"
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "golden" / "review.py"
CANDIDATE_SCRIPT = REPO_ROOT / "scripts" / "golden" / "candidate.py"


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "data" / "golden" / "provider" / "amazingdata"
    shutil.copytree(REPO_GOLDEN, root)
    # Review workflow fixtures start from immutable v3; GT-H2 moves the
    # repository ACTIVE pointer to v4 while preserving the old source.
    for name in ("golden_cases_v4.jsonl", "truth_manifest_v4.json"):
        (root / name).unlink(missing_ok=True)
    (root / "truth_manifest.json").write_text(
        (root / "truth_manifest_v3.json").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr("ashare_state.spike.golden_store.GOLDEN_ROOT", root)
    monkeypatch.chdir(tmp_path)
    return root


def _run_review(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REVIEW_SCRIPT), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


def _run_candidate(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CANDIDATE_SCRIPT), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


def _make_artifact(root: Path, name: str, content: str) -> Path:
    art = root.parent / f"{name}.txt"
    art.write_text(content, encoding="utf-8")
    return art


def _prepare_clean_v4_candidate(root: Path) -> None:
    """Build a synthetic clean v4 candidate without adding corpus facts."""
    active = json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))
    dataset = root / str(active["dataset_file"])
    source = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line]
    operations = [
        {
            "op": "DROP" if doc["event_class"] in {"ST_TRANSITION", "DELIST"} else "KEEP",
            "golden_case_id": doc["golden_case_id"],
        }
        for doc in source
    ]
    operations.extend(
        [
            {
                "op": "ADD",
                "case": {
                    "golden_case_id": "GT-H11-SYN-ST-1",
                    "case_type": "golden_st_transition",
                    "provider_symbol": "600000.SH",
                    "trade_date": "20240102",
                    "truth_source": "synthetic test fixture",
                    "source_ref": "synthetic://st",
                    "expected_fields": {"IS_ST_SEC": True},
                    "event_id": "synthetic-st-event",
                    "event_class": "ST_TRANSITION",
                    "event_subtype": "ST_ADD",
                    "event_effective_date": "20240101",
                },
            },
            {
                "op": "ADD",
                "case": {
                    "golden_case_id": "GT-H11-SYN-DELIST-1",
                    "case_type": "golden_delisted",
                    "provider_symbol": "600001.SH",
                    "trade_date": "20240202",
                    "truth_source": "synthetic test fixture",
                    "source_ref": "synthetic://delist",
                    "expected_fields": {"IS_DELISTED": True},
                    "event_id": "synthetic-delist-event",
                    "event_class": "DELIST",
                    "event_effective_date": "20240201",
                },
            },
        ]
    )
    plan = root.parent / "clean-v4-plan.json"
    plan.write_text(
        json.dumps(
            {
                "source_truth_version": active["truth_version"],
                "source_dataset_hash": active["dataset_hash"],
                "operations": operations,
            }
        ),
        encoding="utf-8",
    )
    result = _run_candidate(
        root,
        "rebuild",
        "--plan",
        str(plan),
        "--truth-version",
        "v4-candidate-20260906",
    )
    assert result.returncode == 0, result.stderr
    cases, manifest = GoldenTruthStore(root).load()
    assert manifest.manifest_schema == 2
    assert manifest.truth_version.startswith("v4-")
    assert recompute_manifest_statistics(cases)["invalid_structural_cases"] == []


def _prepare_incomplete_v4_candidate(root: Path) -> None:
    """Create a loadable schema-v2 v4 candidate with one invalid ST row."""
    _prepare_clean_v4_candidate(root)
    active_path = root / "truth_manifest.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    dataset_path = root / str(active["dataset_file"])
    lines = [
        json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line
    ]
    doc = next(d for d in lines if d["event_class"] == "ST_TRANSITION")
    doc.pop("event_effective_date")
    doc["case_semantic_hash"] = semantic_hash_for_doc(doc)
    payload = "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in lines)
    dataset_path.write_text(payload, encoding="utf-8", newline="\n")
    cases = cases_from_dataset_bytes(payload.encode("utf-8"), active["truth_version"])
    stats = recompute_manifest_statistics(cases)
    active.update(
        {
            "dataset_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "case_count": stats["case_count"],
            "counts_by_type": stats["counts_by_type"],
            "review_summary": stats["review_summary"],
            "distinct_events": stats["distinct_events"],
            "distinct_securities": stats["distinct_securities"],
            "st_add_events": stats["st_add_events"],
            "st_remove_events": stats["st_remove_events"],
            "distinct_delisted_securities": stats["distinct_delisted_securities"],
        }
    )
    active_path.write_text(json.dumps(active, indent=2), encoding="utf-8", newline="\n")


def _prepare_single_case_v4_candidate(root: Path) -> str:
    """Reduce the synthetic clean candidate to one valid case."""
    _prepare_clean_v4_candidate(root)
    active_path = root / "truth_manifest.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    dataset_path = root / str(active["dataset_file"])
    source = [
        json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line
    ]
    selected = next(
        doc for doc in source if doc.get("event_class") not in {"ST_TRANSITION", "DELIST"}
    )
    payload = json.dumps(selected, ensure_ascii=False, sort_keys=True) + "\n"
    dataset_path.write_text(payload, encoding="utf-8", newline="\n")
    cases = cases_from_dataset_bytes(payload.encode("utf-8"), active["truth_version"])
    stats = recompute_manifest_statistics(cases)
    active.update(
        {
            "dataset_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "case_count": stats["case_count"],
            "counts_by_type": stats["counts_by_type"],
            "review_summary": stats["review_summary"],
            "distinct_events": stats["distinct_events"],
            "distinct_securities": stats["distinct_securities"],
            "st_add_events": stats["st_add_events"],
            "st_remove_events": stats["st_remove_events"],
            "distinct_delisted_securities": stats["distinct_delisted_securities"],
        }
    )
    active_path.write_text(json.dumps(active, indent=2), encoding="utf-8", newline="\n")
    return selected["golden_case_id"]


def _review_state_snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and (
            path.name.startswith("golden_cases_v") or path.name.startswith("truth_manifest")
        ):
            snapshot[str(path.relative_to(root))] = path.read_bytes()
    evidence = root / "evidence"
    if evidence.is_dir():
        for path in sorted(evidence.rglob("*")):
            if path.is_file():
                snapshot[str(path.relative_to(root))] = path.read_bytes()
    return snapshot


def _active_case_ids(root: Path) -> list[str]:
    active = json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))
    dataset = root / str(active["dataset_file"])
    return [
        json.loads(line)["golden_case_id"]
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_review_batch(root: Path, entries: list[dict], name: str = "review-batch") -> Path:
    batch = root.parent / f"{name}.json"
    batch.write_text(json.dumps(entries), encoding="utf-8")
    return batch


def _full_review_batch(
    root: Path,
    artifact: Path,
    *,
    artifact_by_case: dict[str, Path] | None = None,
    name: str = "full-review-batch",
) -> Path:
    artifact_by_case = artifact_by_case or {}
    entries = [
        {
            "case": case_id,
            "artifact": str(artifact_by_case.get(case_id, artifact)),
            "kind": "SSE_ANNOUNCEMENT",
        }
        for case_id in _active_case_ids(root)
    ]
    return _write_review_batch(root, entries, name)


def _run_full_review(
    root: Path,
    *,
    reviewer: str = "alice",
    artifact_name: str = "full-review",
    content: str = "full review artifact",
    artifact_by_case: dict[str, Path] | None = None,
) -> tuple[subprocess.CompletedProcess, Path]:
    artifact = _make_artifact(root, artifact_name, content)
    batch = _full_review_batch(root, artifact, artifact_by_case=artifact_by_case)
    result = _run_review(root, "--manifest", str(batch), "--reviewer", reviewer)
    return result, artifact


class TestReviewWorkflow:
    def test_review_seals_real_artifact_bytes(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        result, _ = _run_full_review(
            golden_env,
            reviewer="alice",
            artifact_name="kangmei",
            content="SSE announcement snapshot: Kangmei *ST effective 2019-05-06",
        )
        assert result.returncode == 0, result.stderr
        cases, manifest = GoldenTruthStore(golden_env).load()
        case = next(c for c in cases if c.golden_case_id == "GT-LIMIT-MAIN10-600519")
        assert case.review_status == "REVIEWED"
        assert case.reviewed_by == "alice"
        assert case.compiled_by  # compiled provenance preserved
        # the sealed hash equals the REAL artifact bytes hash
        stored = golden_env / "evidence" / case.source_artifact_ref
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == case.source_artifact_hash
        # formal gate: artifact resolves and hash-verifies
        store = GoldenTruthStore(golden_env)
        assert manifest.review_summary == {"REVIEWED": len(cases)}
        assert not store.review_gate()
        assert all(store._verify_artifact(reviewed_case) == [] for reviewed_case in cases)
        # new version is append-only: v3 file untouched, v4 created + ACTIVE
        assert (golden_env / "golden_cases_v3.jsonl").is_file()
        assert manifest.dataset_file != "golden_cases_v3.jsonl"

    def test_no_hash_parameter_exists(self):
        """Review section 6: the workflow must not accept hand-typed hashes."""
        source = REVIEW_SCRIPT.read_text(encoding="utf-8")
        assert '"--hash"' not in source
        assert "--source-artifact-hash" not in source

    def test_partial_single_case_publish_rejected_before_any_mutation(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        art = _make_artifact(golden_env, "kangmei", "snapshot")
        before = _review_state_snapshot(golden_env)
        result = _run_review(
            golden_env,
            "--case",
            "GT-LIMIT-MAIN10-600519",
            "--artifact",
            str(art),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
        )
        assert result.returncode != 0
        assert "must cover every active case exactly once" in result.stderr
        assert _review_state_snapshot(golden_env) == before


class TestReviewCoverage:
    def test_single_case_dataset_allows_single_case_publish(self, golden_env: Path):
        case_id = _prepare_single_case_v4_candidate(golden_env)
        artifact = _make_artifact(golden_env, "single", "single case")
        result = _run_review(
            golden_env,
            "--case",
            case_id,
            "--artifact",
            str(artifact),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
        )
        assert result.returncode == 0, result.stderr
        cases, manifest = GoldenTruthStore(golden_env).load()
        assert len(cases) == 1
        assert manifest.review_summary == {"REVIEWED": 1}

    def test_partial_batch_rejected_before_any_mutation(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        artifact = _make_artifact(golden_env, "partial", "partial batch")
        ids = _active_case_ids(golden_env)
        entries = [
            {"case": case_id, "artifact": str(artifact), "kind": "SSE_ANNOUNCEMENT"}
            for case_id in ids[:-1]
        ]
        batch = _write_review_batch(golden_env, entries, "partial-review-batch")
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "alice")
        assert result.returncode != 0
        assert "must cover every active case exactly once" in result.stderr
        assert _review_state_snapshot(golden_env) == before

    def test_duplicate_case_batch_rejected_before_any_mutation(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        artifact = _make_artifact(golden_env, "duplicate", "duplicate batch")
        ids = _active_case_ids(golden_env)
        entries = [
            {"case": case_id, "artifact": str(artifact), "kind": "SSE_ANNOUNCEMENT"}
            for case_id in ids
        ]
        entries[-1]["case"] = entries[0]["case"]
        batch = _write_review_batch(golden_env, entries, "duplicate-review-batch")
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "alice")
        assert result.returncode != 0
        assert "duplicate case IDs" in result.stderr
        assert _review_state_snapshot(golden_env) == before

    def test_foreign_case_batch_rejected_before_any_mutation(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        artifact = _make_artifact(golden_env, "foreign", "foreign batch")
        ids = _active_case_ids(golden_env)
        entries = [
            {"case": case_id, "artifact": str(artifact), "kind": "SSE_ANNOUNCEMENT"}
            for case_id in ids
        ]
        entries[-1]["case"] = "GT-H12-FOREIGN-CASE"
        batch = _write_review_batch(golden_env, entries, "foreign-review-batch")
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "alice")
        assert result.returncode != 0
        assert "foreign case IDs" in result.stderr
        assert _review_state_snapshot(golden_env) == before

    def test_missing_artifact_rejected(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        artifact = _make_artifact(golden_env, "present", "present artifact")
        missing = golden_env / "nonexistent.txt"
        batch = _full_review_batch(
            golden_env,
            artifact,
            artifact_by_case={_active_case_ids(golden_env)[-1]: missing},
            name="missing-artifact-batch",
        )
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "alice")
        assert result.returncode != 0
        assert "does not exist" in result.stderr
        assert _review_state_snapshot(golden_env) == before

    def test_review_refuses_legacy_v3_before_any_mutation(self, golden_env: Path):
        art = _make_artifact(golden_env, "incomplete-st", "snapshot")
        before = _review_state_snapshot(golden_env)
        result = _run_review(
            golden_env,
            "--case",
            "GT-LIMIT-MAIN10-600519",
            "--artifact",
            str(art),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
        )
        assert result.returncode != 0
        assert "v4+ truth_version is required" in result.stderr
        assert _review_state_snapshot(golden_env) == before

    def test_review_refuses_incomplete_v4_before_any_mutation(self, golden_env: Path):
        _prepare_incomplete_v4_candidate(golden_env)
        art = _make_artifact(golden_env, "incomplete-v4", "snapshot")
        before = _review_state_snapshot(golden_env)
        result = _run_review(
            golden_env,
            "--case",
            "GT-H11-SYN-ST-1",
            "--artifact",
            str(art),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
        )
        assert result.returncode != 0
        assert "invalid structural cases" in result.stderr
        assert _review_state_snapshot(golden_env) == before


class TestFormalArtifactGate:
    def test_hand_typed_hash_fails_artifact_gate(self, golden_env: Path):
        """A REVIEWED entry whose sealed hash does not match the artifact
        bytes is REVIEW_INCOMPLETE (formal gate)."""
        _prepare_clean_v4_candidate(golden_env)
        result, _ = _run_full_review(
            golden_env,
            reviewer="alice",
            artifact_name="kangmei",
            content="REAL snapshot bytes",
        )
        assert result.returncode == 0, result.stderr
        # tamper the stored artifact after sealing
        cases, _ = GoldenTruthStore(golden_env).load()
        case = next(c for c in cases if c.golden_case_id == "GT-LIMIT-MAIN10-600519")
        stored = golden_env / "evidence" / case.source_artifact_ref
        stored.write_text("TAMPERED different bytes", encoding="utf-8")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("hash mismatch" in p for p in problems)

    def test_unresolvable_artifact_ref_is_incomplete(self, golden_env: Path):
        """REVIEWED pointing at a missing artifact file -> gate problem."""
        dataset_path = golden_env / "golden_cases_v3.jsonl"
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        lines = [
            json.loads(x)
            for x in dataset_path.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        doc = next(d for d in lines if d["golden_case_id"] == "GT-LIMIT-MAIN10-600519")
        doc["review_status"] = "REVIEWED"
        doc["reviewed_by"] = "hand-edit"
        doc["reviewed_at"] = "2026-08-22T00:00:00+00:00"
        doc["source_artifact_ref"] = "ghost.txt"
        doc["source_artifact_hash"] = "0" * 64
        doc["source_artifact_kind"] = "SSE_ANNOUNCEMENT"
        doc["source_retrieved_at"] = "2026-08-22T00:00:00+00:00"
        # rebuild semantic hash so load() passes; the ARTIFACT gate must fail
        statement = json.dumps(
            {
                "golden_case_id": doc["golden_case_id"],
                "case_type": doc["case_type"],
                "provider_symbol": doc["provider_symbol"],
                "trade_date": doc["trade_date"],
                "expected_fields": doc["expected_fields"],
                "truth_source": doc["truth_source"],
                "source_ref": doc["source_ref"],
                "source_artifact_hash": doc["source_artifact_hash"],
                "truth_version": doc["truth_version"],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        doc["case_semantic_hash"] = hashlib.sha256(statement.encode("utf-8")).hexdigest()
        payload = "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in lines)
        dataset_path.write_text(payload, encoding="utf-8", newline="\n")
        active["dataset_hash"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        active["review_summary"] = {"REVIEWED": 1, "COMPILED": 122}
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active, indent=2), encoding="utf-8", newline="\n"
        )
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("does not resolve" in p for p in problems)


class TestEventSemantics:
    def test_st_gate_requires_remove_subtype(self):
        store = GoldenTruthStore(REPO_GOLDEN)
        cases, manifest = store.load_bound("golden_cases_v3.jsonl", V3_VERSION, V3_HASH)
        problems = store.event_coverage_gate(cases, manifest)
        assert any("no ST_REMOVE/STAR_ST_REMOVE" in p for p in problems)

    def test_delist_gate_requires_distinct_symbols(self):
        store = GoldenTruthStore(REPO_GOLDEN)
        cases, manifest = store.load_bound("golden_cases_v3.jsonl", V3_VERSION, V3_HASH)
        problems = store.event_coverage_gate(cases, manifest)
        assert any("distinct delisted securities" in p for p in problems)


class TestReviewGateAllCases:
    """R4A2-P0-01: review_gate must verify EVERY reviewed case."""

    def _review_two(self, golden_env: Path) -> None:
        """Review the full dataset, with distinct bytes for two cases."""
        _prepare_clean_v4_candidate(golden_env)
        art1 = _make_artifact(golden_env, "a1", "artifact one")
        art2 = _make_artifact(golden_env, "a2", "artifact two")
        shared = _make_artifact(golden_env, "shared", "shared artifact")
        batch = _full_review_batch(
            golden_env,
            shared,
            artifact_by_case={
                "GT-LIMIT-MAIN10-600519": art1,
                "GT-LIMIT-MAIN10-600036": art2,
            },
            name="batch",
        )
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode == 0, result.stderr

    def test_review_gate_checks_every_reviewed_case(self, golden_env: Path):
        self._review_two(golden_env)
        store = GoldenTruthStore(golden_env)
        problems = store.review_gate()
        cases, manifest = store.load()
        assert manifest.review_summary == {"REVIEWED": len(cases)}
        assert not problems

    def test_first_artifact_valid_second_tampered_blocks(self, golden_env: Path):
        self._review_two(golden_env)
        # tamper the SECOND artifact only; every other artifact remains valid
        cases, _ = GoldenTruthStore(golden_env).load()
        second = next(c for c in cases if c.golden_case_id == "GT-LIMIT-MAIN10-600036")
        stored = golden_env / "evidence" / second.source_artifact_ref
        stored.write_text("TAMPERED", encoding="utf-8")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("hash mismatch" in p for p in problems)

    def test_first_artifact_valid_later_missing_blocks(self, golden_env: Path):
        self._review_two(golden_env)
        cases, _ = GoldenTruthStore(golden_env).load()
        second = next(c for c in cases if c.golden_case_id == "GT-LIMIT-MAIN10-600036")
        (golden_env / "evidence" / second.source_artifact_ref).unlink()
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("does not resolve" in p for p in problems)

    def test_batch_review_rejects_unknown_artifact_kind(self, golden_env: Path):
        _prepare_clean_v4_candidate(golden_env)
        art = _make_artifact(golden_env, "k", "bytes")
        batch = _full_review_batch(golden_env, art, name="bad_batch")
        entries = json.loads(batch.read_text(encoding="utf-8"))
        entries[0]["kind"] = "FAKE_KIND"
        batch.write_text(json.dumps(entries), encoding="utf-8")
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode != 0
        assert "not in allowlist" in result.stderr
        assert _review_state_snapshot(golden_env) == before

    def test_batch_failure_leaves_no_orphan_evidence(self, golden_env: Path):
        """P1-05: a failing second entry must not write the first artifact."""
        _prepare_clean_v4_candidate(golden_env)
        art1 = _make_artifact(golden_env, "ok1", "good bytes")
        art2 = golden_env / "missing-artifact.txt"  # does not exist
        batch = _full_review_batch(
            golden_env,
            art1,
            artifact_by_case={"GT-LIMIT-MAIN10-600036": art2},
            name="mixed",
        )
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode != 0
        evidence_dir = golden_env / "evidence"
        if evidence_dir.exists():
            assert not any(evidence_dir.rglob("sha256/*")), "orphan evidence written"
        assert _review_state_snapshot(golden_env) == before


class TestReviewProvenanceCompleteness:
    """R4A2-P1-02: REVIEWED provenance must be complete at LOAD time."""

    def _hand_seal_reviewed(self, golden_env: Path, case_id: str, mutate: dict) -> None:
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        dataset_path = golden_env / str(active["dataset_file"])
        lines = [
            json.loads(x)
            for x in dataset_path.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        doc = next(d for d in lines if d["golden_case_id"] == case_id)
        doc.update(
            {
                "review_status": "REVIEWED",
                "reviewed_by": "alice",
                "reviewed_at": "2026-08-22T10:00:00+00:00",
                "source_artifact_ref": "sha256/" + "a" * 64 + ".txt",
                "source_artifact_hash": "a" * 64,
                "source_artifact_kind": "SSE_ANNOUNCEMENT",
                "source_retrieved_at": "2026-08-22T09:00:00+00:00",
            }
        )
        doc.update(mutate)
        doc["case_semantic_hash"] = _semantic_hash(doc)
        payload = "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in lines)
        dataset_path.write_text(payload, encoding="utf-8", newline="\n")
        active["dataset_hash"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active, indent=2), encoding="utf-8", newline="\n"
        )

    def test_missing_reviewer_fails_load(self, golden_env: Path):
        self._hand_seal_reviewed(golden_env, "GT-LIMIT-MAIN10-600519", {"reviewed_by": ""})
        with pytest.raises(Exception, match="reviewed_by is empty"):
            GoldenTruthStore(golden_env).load()

    def test_bad_kind_fails_load(self, golden_env: Path):
        self._hand_seal_reviewed(
            golden_env, "GT-LIMIT-MAIN10-600519", {"source_artifact_kind": "MYSTERY"}
        )
        with pytest.raises(Exception, match="not in allowlist"):
            GoldenTruthStore(golden_env).load()

    def test_short_hash_fails_load(self, golden_env: Path):
        self._hand_seal_reviewed(
            golden_env, "GT-LIMIT-MAIN10-600519", {"source_artifact_hash": "abc"}
        )
        with pytest.raises(Exception, match="64-hex"):
            GoldenTruthStore(golden_env).load()


class TestArtifactPathConfinement:
    """R4A2-P1-03: artifact refs must resolve inside the evidence store."""

    def test_artifact_ref_path_traversal_rejected(self, golden_env: Path):
        self._traversal_seal(golden_env, "../escape.txt")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("escapes the evidence store" in p for p in problems)

    def test_absolute_artifact_ref_rejected(self, golden_env: Path):
        self._traversal_seal(golden_env, "C:/Windows/system32/evil.txt")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("escapes the evidence store" in p for p in problems)

    def test_drive_letter_ref_rejected_platform_independent(self, golden_env: Path):
        """R4-A2.9 CI root cause #2: on Linux ``evidence_dir / "C:/evil"``
        is a RELATIVE join (the resolved check saw no escape); the gate
        must reject drive-letter refs LEXICALLY on every platform."""
        self._traversal_seal(golden_env, "C:/evil.txt")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("escapes the evidence store" in p for p in problems)
        assert any("drive-letter" in p for p in problems)

    def test_posix_absolute_ref_rejected_platform_independent(self, golden_env: Path):
        """Leading-slash refs (absolute on POSIX, odd-but-relative via
        pathlib on Windows) are rejected lexically everywhere."""
        self._traversal_seal(golden_env, "/etc/passwd")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("escapes the evidence store" in p for p in problems)
        assert any("absolute path" in p for p in problems)

    def _traversal_seal(self, golden_env: Path, ref: str) -> None:
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        dataset_path = golden_env / str(active["dataset_file"])
        lines = [
            json.loads(x)
            for x in dataset_path.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        doc = next(d for d in lines if d["golden_case_id"] == "GT-LIMIT-MAIN10-600519")
        doc.update(
            {
                "review_status": "REVIEWED",
                "reviewed_by": "alice",
                "reviewed_at": "2026-08-22T10:00:00+00:00",
                "source_artifact_ref": ref,
                "source_artifact_hash": "a" * 64,
                "source_artifact_kind": "SSE_ANNOUNCEMENT",
                "source_retrieved_at": "2026-08-22T09:00:00+00:00",
            }
        )
        doc["case_semantic_hash"] = _semantic_hash(doc)
        payload = "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in lines)
        dataset_path.write_text(payload, encoding="utf-8", newline="\n")
        active["dataset_hash"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        active["review_summary"] = {"REVIEWED": 1, "COMPILED": 122}
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active, indent=2), encoding="utf-8", newline="\n"
        )


class TestVersionImmutability:
    """R4A2-P1-04: versioned files are create-only."""

    def test_existing_version_file_with_different_bytes_blocks(self, golden_env: Path):
        # pre-plant a conflicting next-version file
        _prepare_clean_v4_candidate(golden_env)
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        num = "".join(ch for ch in str(active["truth_version"]).split("-")[0][1:] if ch.isdigit())
        next_file = golden_env / f"golden_cases_v{int(num) + 1}.jsonl"
        next_file.write_text("CONFLICTING PREEXISTING BYTES\n", encoding="utf-8", newline="\n")
        art = _make_artifact(golden_env, "x", "bytes")
        batch = _full_review_batch(golden_env, art, name="conflict")
        before = _review_state_snapshot(golden_env)
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode != 0
        assert "different bytes" in result.stderr
        # the conflicting file was NOT overwritten
        assert "CONFLICTING" in next_file.read_text(encoding="utf-8")
        assert _review_state_snapshot(golden_env) == before


def _semantic_hash(doc: dict) -> str:
    statement = json.dumps(
        {
            "golden_case_id": doc["golden_case_id"],
            "case_type": doc["case_type"],
            "provider_symbol": doc["provider_symbol"],
            "trade_date": doc["trade_date"],
            "expected_fields": doc["expected_fields"],
            "truth_source": doc["truth_source"],
            "source_ref": doc["source_ref"],
            "source_artifact_hash": doc.get("source_artifact_hash", ""),
            "truth_version": doc["truth_version"],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


class TestDatasetHashRename:
    def test_spike_run_field_is_dataset_hash(self):
        from ashare_state.spike.model import SpikeRun

        fields = {f.name for f in SpikeRun.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        assert "golden_dataset_hash" in fields
        assert "golden_manifest_hash" not in fields

    def test_legacy_run_json_still_loads(self, tmp_path: Path):
        """Runs created before the rename load via the legacy key."""
        from ashare_state.spike.model import RunKind, SpikeRun
        from ashare_state.spike.run_store import RunStore

        run = SpikeRun(
            spike_run_id="legacy-run",
            run_kind=RunKind.TRIAL,
            golden_truth_version="v2-candidate-20260822",
            golden_dataset_hash="a" * 64,
        )
        store = RunStore(tmp_path / "spike")
        store.save_run(run)
        # simulate legacy json on disk
        run_file = store.run_dir(run) / "spike_run.json"
        doc = json.loads(run_file.read_text(encoding="utf-8"))
        doc["golden_manifest_hash"] = doc.pop("golden_dataset_hash")
        run_file.write_text(json.dumps(doc, indent=2), encoding="utf-8", newline="\n")
        loaded = store.load_run("legacy-run", RunKind.TRIAL)
        assert loaded.golden_dataset_hash == "a" * 64
