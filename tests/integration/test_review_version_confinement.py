"""R4-A2.9 P0-02: review ``--version`` OUTPUT CONFINEMENT tests (audit
20260825 #5 section 3).

A version id is ONE safe path component (strict grammar, no '.', '..',
no separators, no drive prefixes); the output directory is resolved-
confined under versions/; ALL validation happens BEFORE any mutation -
an unsafe id must have ZERO side effects (no version dir anywhere under
or OUTSIDE the root, no evidence artifact, no manifest change).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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


def _run_review(root: Path, artifact: Path, version: str) -> subprocess.CompletedProcess:
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
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
    )


def _snapshot_tree(base: Path) -> set[Path]:
    return set(base.rglob("*"))


@pytest.mark.parametrize(
    "version",
    [
        "../escape",
        "../../escape",
        "foo/bar",
        "foo\\bar",
        "/absolute/path",
        "C:\\absolute-or-drive-like",
        "C:/drive-like",
        ".",
        "..",
        "",
        " ",
        "-leading-dash",
    ],
)
def test_unsafe_version_ids_rejected_zero_side_effects(tmp_path, version):
    root = _make_root(tmp_path)
    artifact = tmp_path / "notice.txt"
    artifact.write_text("official notice", encoding="utf-8")
    before = _snapshot_tree(tmp_path)
    result = _run_review(root, artifact, version)
    assert result.returncode != 0, f"{version!r} must be rejected"
    # ZERO side effects: no new path anywhere under tmp_path (covers both
    # versions/<id>/ creation AND escapes like ../<id> or /absolute/<id>)
    after = _snapshot_tree(tmp_path)
    new_paths = after - before
    assert not new_paths, f"unsafe version {version!r} created: {new_paths}"
    # and nothing that existed was modified
    for path in before:
        if path.is_file():
            assert path in after
    doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
    assert doc["rule_version"] == "v1-compiled"


def test_valid_version_confined_output(tmp_path):
    """A valid version id publishes ONLY under versions/<id>/ - and the
    published layout contains exactly rules.yaml."""
    root = _make_root(tmp_path)
    artifact = tmp_path / "notice.txt"
    artifact.write_text("official notice", encoding="utf-8")
    result = _run_review(root, artifact, "v20260825-reviewed")
    assert result.returncode == 0, result.stderr
    version_dir = root / "versions" / "v20260825-reviewed"
    assert version_dir.is_dir()
    assert [p.name for p in sorted(version_dir.iterdir())] == ["rules.yaml"]
    doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
    assert doc["rule_version"] == "v20260825-reviewed"
    assert doc["dataset_files"] == ["versions/v20260825-reviewed/rules.yaml"]


def test_existing_version_collision_blocks_before_other_mutation(tmp_path):
    """An immutable version name that already exists is refused BEFORE
    the evidence artifact is staged (no partial output ordering)."""
    root = _make_root(tmp_path)
    artifact = tmp_path / "notice.txt"
    artifact.write_text("official notice", encoding="utf-8")
    # pre-create the target version dir (an immutable existing version)
    existing = root / "versions" / "v2-reviewed"
    existing.mkdir()
    (existing / "rules.yaml").write_text("version: sentinel\n", encoding="utf-8")
    result = _run_review(root, artifact, "v2-reviewed")
    assert result.returncode != 0
    assert "already exists" in result.stderr
    # the sentinel content is untouched (no overwrite)
    assert (existing / "rules.yaml").read_text(encoding="utf-8") == "version: sentinel\n"
    # NO evidence artifact was staged before the collision rejection
    evidence = root / "evidence"
    assert not evidence.exists() or not list(evidence.glob("*"))
    doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
    assert doc["rule_version"] == "v1-compiled"


def test_evidence_artifacts_exempt_from_eol_normalization():
    """The .gitattributes keeps review evidence byte-exact (their sha256
    IS their name - eol normalization would break content addressing)."""
    content = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "configs/trading_rules/evidence/** -text" in content
    assert "*.yaml text eol=lf" in content
