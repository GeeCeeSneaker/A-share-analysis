"""R4-A2.8 P0-03: trading-rule REVIEW INPUT integrity gate tests (audit
20260825 #4 section 4).

The review tool's preflight runs load_active_rules FIRST (full dataset
hash re-verification + manifest<->dataset coherence). A tampered or
incoherent ACTIVE can NEVER be re-sealed into a fresh REVIEWED version -
and a failed preflight leaves ZERO new review artifacts (no evidence
copy, no versions/<new>/ dir, no manifest mutation).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from ashare_state.spike.trading_rule import load_rule_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "rules"
    vdir = root / "versions" / "v1-compiled"
    vdir.mkdir(parents=True)
    shutil.copy(RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml", vdir / "rules.yaml")
    doc = yaml.safe_load((vdir / "rules.yaml").read_text(encoding="utf-8"))
    rel = "versions/v1-compiled/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    (root / "rule_manifest.json").write_text(
        json.dumps(
            {
                "rule_version": "v1-compiled",
                "review_status": "COMPILED",
                "dataset_files": [rel],
                "dataset_hash": digest.hexdigest(),
                "source_version": str(doc.get("source_version", "")),
                "dataset_version": str(doc.get("version", "")),
                "review_provenance": {
                    "source_retrieved_at": str(doc.get("source_retrieved_at", ""))
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _run_review(root: Path, artifact: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "rules" / "review.py"),
            "--rules",
            str(root / "versions" / "v1-compiled" / "rules.yaml"),
            "--artifact",
            str(artifact),
            "--kind",
            "EXCHANGE_NOTICE",
            "--reviewer",
            "tester",
            "--version",
            "v2-reviewed",
            "--rules-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
    )


def _assert_zero_output_mutation(root: Path, artifact: Path) -> None:
    """No evidence artifact copy, no new version dir, manifest unchanged."""
    evidence = root / "evidence"
    assert not evidence.exists() or not list(evidence.glob("*")), (
        "preflight failure must not copy the evidence artifact"
    )
    assert not (root / "versions" / "v2-reviewed").exists(), (
        "preflight failure must not create the reviewed version directory"
    )
    assert not [p for p in root.iterdir() if p.name.startswith(".rule_manifest")], (
        "preflight failure must not write a temp manifest"
    )
    # manifest BYTES unchanged (read the raw json - the schema-invalid
    # variants must stay exactly as the test tampered them)
    doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
    assert doc["rule_version"] == "v1-compiled"
    assert doc["review_status"] == "COMPILED"


class TestReviewInputIntegrity:
    def test_tampered_active_bytes_refused_zero_mutation(self, tmp_path: Path):
        """ACTIVE dataset bytes modified but manifest hash unchanged: the
        runtime load_active_rules gate would BLOCK - the review tool must
        refuse identically and leave ZERO output."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        # tamper the ACTIVE dataset bytes (manifest hash now stale)
        victim = root / "versions" / "v1-compiled" / "rules.yaml"
        victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        assert "integrity preflight" in result.stderr
        _assert_zero_output_mutation(root, artifact)

    def test_manifest_hash_tampered_refused_zero_mutation(self, tmp_path: Path):
        """Manifest's dataset_hash altered (dataset intact): re-verification
        fails -> refuse."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        manifest_path = root / "rule_manifest.json"
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc["dataset_hash"] = "0" * 64
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        assert "integrity preflight" in result.stderr
        _assert_zero_output_mutation(root, artifact)

    def test_source_version_missing_in_manifest_refused(self, tmp_path: Path):
        """R4-A2.8 section 4.4: required schema fields are enforced at
        load_rule_manifest level - the review preflight inherits it."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        manifest_path = root / "rule_manifest.json"
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        del doc["source_version"]
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        _assert_zero_output_mutation(root, artifact)

    def test_dataset_version_empty_in_manifest_refused(self, tmp_path: Path):
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        manifest_path = root / "rule_manifest.json"
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc["dataset_version"] = ""
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        _assert_zero_output_mutation(root, artifact)

    def test_coherence_source_version_mismatch_refused(self, tmp_path: Path):
        """Manifest source_version disagrees with the dataset file."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        manifest_path = root / "rule_manifest.json"
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc["source_version"] = "A DIFFERENT CONSOLIDATION"
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        assert "integrity preflight" in result.stderr
        _assert_zero_output_mutation(root, artifact)

    def test_coherence_review_status_mismatch_refused(self, tmp_path: Path):
        """Manifest says COMPILED, dataset says REVIEWED (provenance lie)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        # flip the DATASET to REVIEWED (manifest still COMPILED)
        vpath = root / "versions" / "v1-compiled" / "rules.yaml"
        doc = yaml.safe_load(vpath.read_text(encoding="utf-8"))
        doc["review_status"] = "REVIEWED"
        doc["reviewed_by"] = "someone"
        vpath.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        # keep the manifest hash consistent with the new bytes (so the
        # HASH passes and only the COHERENCE check bites)
        rel = "versions/v1-compiled/rules.yaml"
        digest = hashlib.sha256()
        digest.update(rel.encode("utf-8"))
        digest.update(vpath.read_bytes())
        manifest_path = root / "rule_manifest.json"
        mdoc = json.loads(manifest_path.read_text(encoding="utf-8"))
        mdoc["dataset_hash"] = digest.hexdigest()
        manifest_path.write_text(json.dumps(mdoc), encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        assert "integrity preflight" in result.stderr
        _assert_zero_output_mutation(root, artifact)

    def test_coherence_provenance_mismatch_refused(self, tmp_path: Path):
        """Manifest review_provenance disagrees with the dataset file."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        manifest_path = root / "rule_manifest.json"
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        doc["review_provenance"] = {"source_retrieved_at": "1999-01-01"}
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode != 0
        _assert_zero_output_mutation(root, artifact)

    def test_healthy_compiled_active_reviews_normally(self, tmp_path: Path):
        """A healthy, fully verified COMPILED ACTIVE completes the review
        flow (new REVIEWED version + ACTIVE flip)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode == 0, result.stderr
        manifest = load_rule_manifest(root)
        assert manifest.rule_version == "v2-reviewed"
        assert manifest.review_status == "REVIEWED"
        # the COMPILED original is untouched
        compiled = yaml.safe_load(
            (root / "versions" / "v1-compiled" / "rules.yaml").read_text(encoding="utf-8")
        )
        assert compiled["review_status"] == "COMPILED"

    def test_reviewed_active_refused_not_compiled(self, tmp_path: Path):
        """An ACTIVE that is already REVIEWED cannot be re-reviewed
        (review once, seal forever)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        result = _run_review(root, artifact)
        assert result.returncode == 0  # first review succeeds
        # second review on the now-REVIEWED ACTIVE
        result2 = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "rules" / "review.py"),
                "--rules",
                str(root / "versions" / "v2-reviewed" / "rules.yaml"),
                "--artifact",
                str(artifact),
                "--kind",
                "EXCHANGE_NOTICE",
                "--reviewer",
                "tester",
                "--version",
                "v3-reviewed",
                "--rules-root",
                str(root),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )
        assert result2.returncode != 0
        assert "COMPILED" in result2.stderr
