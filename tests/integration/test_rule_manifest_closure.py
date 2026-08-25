"""R4-A2.6 P0-03/P0-04 + P1 tests: rule manifest confinement + metadata
coherence (audit 20260825 #2 sections 4-5, 7).

Confinement: dataset_files[] may only reference version-local files under
versions/<rule_version>/ - absolute / '..' / symlink escapes are BLOCKED
BEFORE any filesystem read.

Coherence: manifest and dataset governance metadata (review_status /
source_version / review_provenance / dataset_version) must describe ONE
version identity; the run binds BOTH the selector version and the dataset
content version.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from ashare_state.spike.model import RunKind, SpikeRun
from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    TradingRuleBook,
    load_active_rules,
    load_bound_rule_book,
    load_rule_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"
_SHA = "f" * 40


def _make_root(tmp_path: Path) -> tuple[Path, dict]:
    """A coherent COMPILED rules root (manifest + one version)."""
    root = tmp_path / "rules"
    vdir = root / "versions" / "v1-compiled"
    vdir.mkdir(parents=True)
    shutil.copy(RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml", vdir / "rules.yaml")
    doc = yaml.safe_load((vdir / "rules.yaml").read_text(encoding="utf-8"))
    rel = "versions/v1-compiled/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    manifest = {
        "rule_version": "v1-compiled",
        "review_status": "COMPILED",
        "dataset_files": [rel],
        "dataset_hash": digest.hexdigest(),
        "source_version": str(doc.get("source_version", "")),
        "dataset_version": str(doc.get("version", "")),
        "review_provenance": {"source_retrieved_at": str(doc.get("source_retrieved_at", ""))},
    }
    _write(root, manifest)
    return root, manifest


def _write(root: Path, manifest: dict) -> None:
    (root / "rule_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )


class TestManifestConfinement:
    def test_traversal_blocked_before_fs_read(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        # an outside file that EXISTS (so a mere existence check would pass)
        outside = tmp_path / "outside.yaml"
        outside.write_text("version: evil\n", encoding="utf-8")
        manifest["dataset_files"] = ["../../outside.yaml"]
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="escapes the rule SoR boundary"):
            load_rule_manifest(root)

    def test_absolute_path_blocked(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["dataset_files"] = [str(root / "versions" / "v1-compiled" / "rules.yaml")]
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="escapes the rule SoR boundary"):
            load_rule_manifest(root)

    def test_symlink_escape_blocked(self, tmp_path: Path):
        """A dataset_files entry that is a symlink pointing OUTSIDE the
        rules root is blocked (the resolved-path confinement catches it)."""
        try:
            root, manifest = _make_root(tmp_path)
            outside = tmp_path / "outside.yaml"
            outside.write_text("version: evil\n", encoding="utf-8")
            link = root / "versions" / "v1-compiled" / "linked.yaml"
            link.symlink_to(outside)
        except OSError:
            pytest.skip("creating symlinks requires elevated privileges on this OS")
        rel = "versions/v1-compiled/linked.yaml"
        digest = hashlib.sha256()
        digest.update(rel.encode("utf-8"))
        digest.update(link.read_bytes())
        manifest["dataset_files"] = [rel]
        manifest["dataset_hash"] = digest.hexdigest()
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="escapes the rule SoR boundary"):
            load_rule_manifest(root)

    def test_version_dir_mismatch_blocked(self, tmp_path: Path):
        """dataset_files under a DIFFERENT version dir than the selector
        id are rejected (structural selector/dataset identity)."""
        root, manifest = _make_root(tmp_path)
        manifest["dataset_files"] = ["versions/other-version/rules.yaml"]
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="not under versions/v1-compiled/"):
            load_rule_manifest(root)

    def test_valid_version_local_dataset_passes(self, tmp_path: Path):
        root, _manifest = _make_root(tmp_path)
        book, manifest = load_active_rules(root)
        assert book.review_status == "COMPILED"
        assert manifest.rule_version == "v1-compiled"

    def test_bound_load_rejects_foreign_version_dir(self, tmp_path: Path):
        """The SAME confinement is enforced by the BOUND loader (one
        helper, two entry points - no drift between ACTIVE and bound
        rules). The foreign file EXISTS - only the structural mismatch
        rejects it."""
        root, manifest = _make_root(tmp_path)
        moved = root / "versions" / "v2-moved"
        moved.mkdir()
        shutil.copy(root / "versions" / "v1-compiled" / "rules.yaml", moved / "rules.yaml")
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=["versions/v2-moved/rules.yaml"],
                dataset_hash=manifest["dataset_hash"],
                rules_root=root,
            )


class TestMetadataCoherence:
    def test_manifest_reviewed_dataset_compiled_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["review_status"] = "REVIEWED"  # dataset stays COMPILED
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="review_status"):
            load_active_rules(root)

    def test_manifest_compiled_dataset_reviewed_blocks(self, tmp_path: Path):
        """Provenance lie direction: a REVIEWED dataset behind a COMPILED
        manifest must NOT enter runs with the weaker status."""
        root, manifest = _make_root(tmp_path)
        vdir = root / "versions" / "v1-compiled"
        doc = yaml.safe_load((vdir / "rules.yaml").read_text(encoding="utf-8"))
        doc["review_status"] = "REVIEWED"
        doc["reviewed_by"] = "someone"
        (vdir / "rules.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        rel = manifest["dataset_files"][0]
        digest = hashlib.sha256()
        digest.update(rel.encode("utf-8"))
        digest.update((root / rel).read_bytes())
        manifest["dataset_hash"] = digest.hexdigest()
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="review_status"):
            load_active_rules(root)

    def test_source_version_mismatch_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["source_version"] = "a DIFFERENT consolidation"
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="source_version"):
            load_active_rules(root)

    def test_review_provenance_mismatch_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["review_provenance"] = {
            "source_retrieved_at": "1999-01-01"  # disagrees with the dataset
        }
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="review_provenance"):
            load_active_rules(root)

    def test_dataset_version_mismatch_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["dataset_version"] = "9999-01-01.0"
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="dataset_version"):
            load_active_rules(root)

    def test_coherent_manifest_loads(self, tmp_path: Path):
        root, _manifest = _make_root(tmp_path)
        book, manifest = load_active_rules(root)
        assert book.review_status == manifest.review_status == "COMPILED"
        assert book.source_version == manifest.source_version


class TestRunBindsBothVersions:
    def test_run_json_binds_selector_and_dataset_version(self, tmp_path: Path, monkeypatch):
        root, _manifest = _make_root(tmp_path)
        monkeypatch.setattr(TradingRuleBook, "_default_rules_dir", classmethod(lambda cls: root))
        from ashare_state.spike.runner import new_run

        run, store = new_run(
            run_kind=RunKind.TRIAL,
            spike_root=tmp_path / "spike",
            code_commit=_SHA,
            environment_lock_hash="e" * 64,
            config_hash="c" * 64,
            sdk_version="1.1.9",
            runtime_version="V4.3.0",
            account_profile_id="TRIAL_TEST",
            as_of_date="20260814",
        )
        # selector id != dataset content version - BOTH are bound
        assert run.trading_rule_version == "v1-compiled"
        assert run.trading_rule_dataset_version == "2026-08-24.1"
        assert run.trading_rule_version != run.trading_rule_dataset_version
        assert run.trading_rule_source_version
        doc = json.loads((store.run_dir(run) / "spike_run.json").read_text(encoding="utf-8"))
        assert doc["trading_rule_version"] == "v1-compiled"
        assert doc["trading_rule_dataset_version"] == "2026-08-24.1"
        assert doc["trading_rule_source_version"]


class TestProvenanceComplete:
    def test_production_provenance_requires_rule_binding(self):
        """R4-A2.6 P1-01: provenance_complete() includes the rule binding
        (selector + files + hash + review status)."""
        base = {
            "spike_run_id": "r",
            "run_kind": RunKind.PRODUCTION,
            "code_commit": "c" * 40,
            "environment_lock_hash": "e" * 64,
            "config_hash": "f" * 64,
            "sdk_version": "1.1.9",
            "runtime_version": "V4.3.0",
            "account_profile_id": "TRIAL_X",
            "as_of_date": "20260814",
            "golden_truth_version": "v3",
            "golden_dataset_hash": "a" * 64,
        }
        # full golden binding, NO rule binding -> incomplete
        unbound = SpikeRun(**base)
        assert unbound.provenance_complete() is False
        # add the rule binding -> complete
        bound = SpikeRun(
            **base,
            trading_rule_version="v1-compiled",
            trading_rule_dataset_version="2026-08-24.1",
            trading_rule_dataset_files=["versions/v1-compiled/rules.yaml"],
            trading_rule_dataset_hash="b" * 64,
            trading_rule_review_status="COMPILED",
            trading_rule_source_version="src",
        )
        assert bound.provenance_complete() is True
        # a partially-bound rule identity is still incomplete
        partial = SpikeRun(
            **base,
            trading_rule_version="v1-compiled",
            trading_rule_dataset_files=["versions/v1-compiled/rules.yaml"],
            trading_rule_dataset_hash="b" * 64,
            # review status missing
        )
        assert partial.provenance_complete() is False


class TestReviewScriptHardening:
    def _run_review(self, root: Path, extra: list[str], artifact: Path, version: str) -> object:
        import subprocess
        import sys

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
                version,
                "--rules-root",
                str(root),
                *extra,
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )

    def test_from_version_mismatch_refused(self, tmp_path: Path):
        """--from-version pointing at a different ACTIVE is refused (no
        silent lineage jump)."""
        root, _manifest = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        result = self._run_review(
            root, ["--from-version", "v0-something-else"], artifact, "v1-reviewed"
        )
        assert result.returncode != 0
        assert "ACTIVE manifest is" in result.stderr

    def test_non_active_input_refused(self, tmp_path: Path):
        """Reviewing an arbitrary yaml that is NOT the ACTIVE dataset is
        refused (explicit lineage transitions only)."""
        root, _manifest = _make_root(tmp_path)
        # an extra compiled copy NOT referenced by the manifest
        stray = root / "versions" / "v1-stray"
        stray.mkdir()
        shutil.copy(root / "versions" / "v1-compiled" / "rules.yaml", stray / "rules.yaml")
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "rules" / "review.py"),
                "--rules",
                str(stray / "rules.yaml"),
                "--artifact",
                str(artifact),
                "--kind",
                "EXCHANGE_NOTICE",
                "--reviewer",
                "tester",
                "--version",
                "v1-reviewed",
                "--rules-root",
                str(root),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )
        assert result.returncode != 0
        assert "not the ACTIVE dataset" in result.stderr

    def test_successful_review_flips_active_coherently(self, tmp_path: Path):
        root, _manifest = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        result = self._run_review(root, [], artifact, "v1-reviewed")
        assert result.returncode == 0, result.stderr
        # ACTIVE flipped, no temp residue, coherence holds
        book, manifest = load_active_rules(root)
        assert manifest.rule_version == "v1-reviewed"
        assert book.review_status == "REVIEWED"
        assert not [p for p in (root).iterdir() if p.name.startswith(".rule_manifest")]
        # the COMPILED original is untouched
        compiled = yaml.safe_load(
            (root / "versions" / "v1-compiled" / "rules.yaml").read_text(encoding="utf-8")
        )
        assert compiled["review_status"] == "COMPILED"
