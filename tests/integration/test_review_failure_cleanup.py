"""R4-A2.9 P1: review workflow FAILURE CLEANUP tests (audit 20260825 #5
section 4 / acceptance 8.5).

Staged flow: every deterministic validation completes before any durable
output mutation; a failure at ANY staged step removes every staged byte -
no finalized REVIEWED version, no orphan evidence, no ACTIVE advance -
and a retry after the failure behaves deterministically.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"


def _load_review_module():
    spec = importlib.util.spec_from_file_location(
        "rule_review_tool_cleanup", REPO_ROOT / "scripts" / "rules" / "review.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _argv(root: Path, artifact: Path) -> list[str]:
    return [
        "review.py",
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
    ]


def _run_module(module, argv: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = argv
    try:
        return module.main()
    finally:
        sys.argv = old_argv


def _no_temp_residue(root: Path) -> None:
    assert not [p for p in (root / "versions").iterdir() if p.name.startswith(".staging")]
    assert not [p for p in root.iterdir() if p.name.startswith(".rule_manifest")]


class TestFailureCleanup:
    def test_failed_gate_leaves_no_finalized_version_no_evidence(
        self, tmp_path, monkeypatch, capsys
    ):
        """A late (staged) review-gate failure removes the staged version
        dir AND the staged evidence artifact - nothing finalized."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        monkeypatch.setattr(
            module,
            "trading_rule_review_gate",
            lambda book, **kwargs: ["synthetic gate failure"],
        )
        code = _run_module(module, _argv(root, artifact))
        capsys.readouterr()
        assert code != 0
        assert not (root / "versions" / "v2-reviewed").exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.glob("*"))
        _no_temp_residue(root)
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"

    def test_failed_gate_never_advances_active(self, tmp_path, monkeypatch, capsys):
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        monkeypatch.setattr(
            module,
            "trading_rule_review_gate",
            lambda book, **kwargs: ["synthetic gate failure"],
        )
        assert _run_module(module, _argv(root, artifact)) != 0
        capsys.readouterr()
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"
        assert doc["review_status"] == "COMPILED"
        # the COMPILED original bytes are untouched
        original = yaml.safe_load(
            (root / "versions" / "v1-compiled" / "rules.yaml").read_text(encoding="utf-8")
        )
        assert original["review_status"] == "COMPILED"

    def test_preflight_failure_leaves_no_temp_files(self, tmp_path, capsys):
        """Deterministic preflight failure (tampered ACTIVE) leaves no
        temp/staging residue anywhere in the root."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        victim = root / "versions" / "v1-compiled" / "rules.yaml"
        victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact)) != 0
        capsys.readouterr()
        _no_temp_residue(root)
        assert not (root / "versions" / "v2-reviewed").exists()

    def test_retry_after_failure_is_deterministic(self, tmp_path, capsys):
        """After a failed run (gate failure), a clean retry on the SAME
        root succeeds and produces exactly one finalized version."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        import pytest

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                module,
                "trading_rule_review_gate",
                lambda book, **kwargs: ["synthetic gate failure"],
            )
            assert _run_module(module, _argv(root, artifact)) != 0
            capsys.readouterr()
        # retry with the REAL gate (fresh module state not needed - the
        # monkeypatch context ended)
        code = _run_module(module, _argv(root, artifact))
        capsys.readouterr()
        assert code == 0
        version_dir = root / "versions" / "v2-reviewed"
        assert version_dir.is_dir()
        assert [p.name for p in sorted(version_dir.iterdir())] == ["rules.yaml"]
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v2-reviewed"
        _no_temp_residue(root)


class TestCrossPlatformRuleBytes:
    """R4-A2.9 / audit 20260825 #5 section 5: the CI root cause."""

    def test_rule_dataset_yaml_has_no_crlf(self):
        """The committed rule dataset yaml must be LF-only: the dataset
        hash is sealed over these bytes and re-verified on every platform
        (a Windows autocrlf checkout rewrote LF->CRLF and made the Ubuntu
        CI recompute a different hash)."""
        for path in sorted(RULES_DIR.rglob("*.yaml")):
            data = path.read_bytes()
            assert b"\r\n" not in data, (
                f"{path} contains CRLF - the sealed hash breaks on LF platforms"
            )

    def test_gitattributes_forces_lf_for_yaml(self):
        content = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "*.yaml text eol=lf" in content
        assert "*.yml text eol=lf" in content

    def test_working_tree_matches_git_blob_bytes(self):
        """The hash-relevant dataset file's working-tree bytes equal the
        committed git blob bytes (no eol drift between platforms)."""
        import subprocess

        rel = "configs/trading_rules/versions/v20260824-compiled/rules.yaml"
        blob = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], capture_output=True, check=True
        ).stdout
        local = (REPO_ROOT / rel).read_bytes()
        assert local == blob, (
            "working-tree yaml differs from the git blob - the sealed "
            "dataset hash would differ across platforms"
        )
