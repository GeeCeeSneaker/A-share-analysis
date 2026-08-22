"""Golden review workflow contract tests (R4-A2 sections 6-8, review scope)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import GoldenTruthStore

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_GOLDEN = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "golden" / "review.py"


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "data" / "golden" / "provider" / "amazingdata"
    shutil.copytree(REPO_GOLDEN, root)
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


def _make_artifact(root: Path, name: str, content: str) -> Path:
    art = root.parent / f"{name}.txt"
    art.write_text(content, encoding="utf-8")
    return art


class TestReviewWorkflow:
    def test_review_seals_real_artifact_bytes(self, golden_env: Path):
        art = _make_artifact(
            golden_env,
            "kangmei",
            "SSE announcement snapshot: Kangmei *ST effective 2019-05-06",
        )
        result = _run_review(
            golden_env,
            "--case",
            "GT-ST-600518-20190506",
            "--artifact",
            str(art),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
            "--note",
            "verified against SSE disclosure page",
        )
        assert result.returncode == 0, result.stderr
        cases, manifest = GoldenTruthStore(golden_env).load()
        case = next(c for c in cases if c.golden_case_id == "GT-ST-600518-20190506")
        assert case.review_status == "REVIEWED"
        assert case.reviewed_by == "alice"
        assert case.compiled_by  # compiled provenance preserved
        # the sealed hash equals the REAL artifact bytes hash
        stored = golden_env / "evidence" / case.source_artifact_ref
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == case.source_artifact_hash
        # formal gate: artifact resolves and hash-verifies
        store = GoldenTruthStore(golden_env)
        assert store._verify_artifact(case) == []
        # new version is append-only: v3 file untouched, v4 created + ACTIVE
        assert (golden_env / "golden_cases_v3.jsonl").is_file()
        assert manifest.dataset_file != "golden_cases_v3.jsonl"

    def test_no_hash_parameter_exists(self):
        """Review section 6: the workflow must not accept hand-typed hashes."""
        source = REVIEW_SCRIPT.read_text(encoding="utf-8")
        assert '"--hash"' not in source
        assert "--source-artifact-hash" not in source

    def test_review_twice_rejected(self, golden_env: Path):
        art = _make_artifact(golden_env, "kangmei", "snapshot")
        args = (
            "--case",
            "GT-ST-600518-20190506",
            "--artifact",
            str(art),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
        )
        assert _run_review(golden_env, *args).returncode == 0
        result = _run_review(golden_env, *args)
        assert result.returncode != 0
        assert "already REVIEWED" in result.stderr

    def test_missing_artifact_rejected(self, golden_env: Path):
        result = _run_review(
            golden_env,
            "--case",
            "GT-ST-600518-20190506",
            "--artifact",
            str(golden_env / "nonexistent.txt"),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "alice",
        )
        assert result.returncode != 0
        assert "does not exist" in result.stderr


class TestFormalArtifactGate:
    def test_hand_typed_hash_fails_artifact_gate(self, golden_env: Path):
        """A REVIEWED entry whose sealed hash does not match the artifact
        bytes is REVIEW_INCOMPLETE (formal gate)."""
        art = _make_artifact(golden_env, "kangmei", "REAL snapshot bytes")
        assert (
            _run_review(
                golden_env,
                "--case",
                "GT-ST-600518-20190506",
                "--artifact",
                str(art),
                "--kind",
                "SSE_ANNOUNCEMENT",
                "--reviewer",
                "alice",
            ).returncode
            == 0
        )
        # tamper the stored artifact after sealing
        cases, _ = GoldenTruthStore(golden_env).load()
        case = next(c for c in cases if c.golden_case_id == "GT-ST-600518-20190506")
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
        doc = next(d for d in lines if d["golden_case_id"] == "GT-ST-600518-20190506")
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
        problems = GoldenTruthStore(REPO_GOLDEN).event_coverage_gate()
        assert any("no ST_REMOVE/STAR_ST_REMOVE" in p for p in problems)

    def test_delist_gate_requires_distinct_symbols(self):
        problems = GoldenTruthStore(REPO_GOLDEN).event_coverage_gate()
        assert any("distinct delisted securities" in p for p in problems)


class TestReviewGateAllCases:
    """R4A2-P0-01: review_gate must verify EVERY reviewed case."""

    def _review_two(self, golden_env: Path) -> None:
        """Review two cases (real artifacts) against the dataset."""
        art1 = _make_artifact(golden_env, "a1", "artifact one")
        art2 = _make_artifact(golden_env, "a2", "artifact two")
        batch = golden_env.parent / "batch.json"
        batch.write_text(
            json.dumps(
                [
                    {
                        "case": "GT-ST-600518-20190506",
                        "artifact": str(art1),
                        "kind": "SSE_ANNOUNCEMENT",
                        "note": "n1",
                    },
                    {
                        "case": "GT-ST-600518-20190603",
                        "artifact": str(art2),
                        "kind": "SSE_ANNOUNCEMENT",
                        "note": "n2",
                    },
                ]
            ),
            encoding="utf-8",
        )
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode == 0, result.stderr

    def test_review_gate_checks_every_reviewed_case(self, golden_env: Path):
        self._review_two(golden_env)
        store = GoldenTruthStore(golden_env)
        problems = store.review_gate()
        # both artifacts valid -> no PER-CASE artifact problems
        # (the dataset-wide "not fully reviewed" note may remain)
        assert not [p for p in problems if "GT-ST" in p]

    def test_first_artifact_valid_second_tampered_blocks(self, golden_env: Path):
        self._review_two(golden_env)
        # tamper the SECOND artifact only
        cases, _ = GoldenTruthStore(golden_env).load()
        second = next(c for c in cases if c.golden_case_id == "GT-ST-600518-20190603")
        stored = golden_env / "evidence" / second.source_artifact_ref
        stored.write_text("TAMPERED", encoding="utf-8")
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("hash mismatch" in p for p in problems)

    def test_first_artifact_valid_later_missing_blocks(self, golden_env: Path):
        self._review_two(golden_env)
        cases, _ = GoldenTruthStore(golden_env).load()
        second = next(c for c in cases if c.golden_case_id == "GT-ST-600518-20190603")
        (golden_env / "evidence" / second.source_artifact_ref).unlink()
        problems = GoldenTruthStore(golden_env).review_gate()
        assert any("does not resolve" in p for p in problems)

    def test_batch_review_rejects_unknown_artifact_kind(self, golden_env: Path):
        art = _make_artifact(golden_env, "k", "bytes")
        batch = golden_env.parent / "bad_batch.json"
        batch.write_text(
            json.dumps(
                [{"case": "GT-ST-600518-20190506", "artifact": str(art), "kind": "FAKE_KIND"}]
            ),
            encoding="utf-8",
        )
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode != 0
        assert "not in allowlist" in result.stderr

    def test_batch_failure_leaves_no_orphan_evidence(self, golden_env: Path):
        """P1-05: a failing second entry must not write the first artifact."""
        art1 = _make_artifact(golden_env, "ok1", "good bytes")
        art2 = golden_env / "missing-artifact.txt"  # does not exist
        batch = golden_env.parent / "mixed.json"
        batch.write_text(
            json.dumps(
                [
                    {
                        "case": "GT-ST-600518-20190506",
                        "artifact": str(art1),
                        "kind": "SSE_ANNOUNCEMENT",
                    },
                    {
                        "case": "GT-ST-600518-20190603",
                        "artifact": str(art2),
                        "kind": "SSE_ANNOUNCEMENT",
                    },
                ]
            ),
            encoding="utf-8",
        )
        result = _run_review(golden_env, "--manifest", str(batch), "--reviewer", "bob")
        assert result.returncode != 0
        evidence_dir = golden_env / "evidence"
        if evidence_dir.exists():
            assert not any(evidence_dir.rglob("sha256/*")), "orphan evidence written"


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
        self._hand_seal_reviewed(golden_env, "GT-ST-600518-20190506", {"reviewed_by": ""})
        with pytest.raises(Exception, match="reviewed_by is empty"):
            GoldenTruthStore(golden_env).load()

    def test_bad_kind_fails_load(self, golden_env: Path):
        self._hand_seal_reviewed(
            golden_env, "GT-ST-600518-20190506", {"source_artifact_kind": "MYSTERY"}
        )
        with pytest.raises(Exception, match="not in allowlist"):
            GoldenTruthStore(golden_env).load()

    def test_short_hash_fails_load(self, golden_env: Path):
        self._hand_seal_reviewed(
            golden_env, "GT-ST-600518-20190506", {"source_artifact_hash": "abc"}
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

    def _traversal_seal(self, golden_env: Path, ref: str) -> None:
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        dataset_path = golden_env / str(active["dataset_file"])
        lines = [
            json.loads(x)
            for x in dataset_path.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        doc = next(d for d in lines if d["golden_case_id"] == "GT-ST-600518-20190506")
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
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        num = "".join(ch for ch in str(active["truth_version"]).split("-")[0][1:] if ch.isdigit())
        next_file = golden_env / f"golden_cases_v{int(num) + 1}.jsonl"
        next_file.write_text("CONFLICTING PREEXISTING BYTES\n", encoding="utf-8", newline="\n")
        art = _make_artifact(golden_env, "x", "bytes")
        result = _run_review(
            golden_env,
            "--case",
            "GT-ST-600518-20190506",
            "--artifact",
            str(art),
            "--kind",
            "SSE_ANNOUNCEMENT",
            "--reviewer",
            "bob",
        )
        assert result.returncode != 0
        assert "different bytes" in result.stderr
        # the conflicting file was NOT overwritten
        assert "CONFLICTING" in next_file.read_text(encoding="utf-8")


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
