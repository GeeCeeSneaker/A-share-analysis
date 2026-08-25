"""R4-A2.10 / CR-1.2.6: review PUBLISH INTEGRITY tests (audit 20260825 #6).

P0-01 persisted byte identity: the transformed REVIEWED identity is the
immutable in-memory ``reviewed_bytes`` object; every formal dataset write
uses write_bytes (NO text-mode newline translation); the persisted final
bytes equal reviewed_bytes exactly; the manifest hash is derived from
reviewed_bytes and independently recomputes.

P0-02 manifest seal identity: the post-rename filesystem read-back is
VERIFICATION ONLY - a tampered final file can never have its bytes
re-hashed into the manifest (fail closed + rollback, ACTIVE unchanged,
retry deterministic).

P1-01 publish failure cleanup: pre-commit failures (tmp manifest write /
manifest replace) leave the old ACTIVE, no finalized new version, no
orphan evidence/tmp - and a same-version retry succeeds.

P1-02 single-writer: a concurrent review is blocked by the lock; the lock
is released after the run.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"


def _load_review_module():
    spec = importlib.util.spec_from_file_location(
        "rule_review_tool_publish", REPO_ROOT / "scripts" / "rules" / "review.py"
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


def _argv(root: Path, artifact: Path, version: str = "v2-reviewed") -> list[str]:
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
        version,
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


def _expected_reviewed_bytes(module, root: Path) -> bytes:
    """Independently rebuild the expected reviewed_bytes from the ACTIVE
    snapshot (same deterministic provenance transform)."""
    rel = "versions/v1-compiled/rules.yaml"
    active_bytes = (root / rel).read_bytes()
    # read the provenance the run sealed off the OUTPUT (yaml parses ISO
    # timestamps into datetime objects - restore the exact isoformat text
    # the tool originally f-string'ed into the reviewed copy)
    reviewed_path = root / "versions" / "v2-reviewed" / "rules.yaml"
    out = yaml.safe_load(reviewed_path.read_text(encoding="utf-8"))
    reviewed_at = out["reviewed_at"]
    if not isinstance(reviewed_at, str):
        reviewed_at = reviewed_at.isoformat()
    text = module._build_reviewed_text(
        active_bytes,
        reviewer="tester",
        now=reviewed_at,
        artifact_ref=out["source_artifact_ref"],
        artifact_hash=out["source_artifact_hash"],
        kind=out["source_artifact_kind"],
    )
    return text.encode("utf-8")


class TestPersistedByteIdentity:
    def test_final_bytes_lf_only_and_equal_reviewed_bytes(self, tmp_path, capsys):
        """P0-01: the persisted REVIEWED file is byte-identical to the
        in-memory reviewed_bytes (LF-only; no OS newline translation) -
        verified at the BYTE level, not via text lines."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact)) == 0
        capsys.readouterr()
        final = root / "versions" / "v2-reviewed" / "rules.yaml"
        final_bytes = final.read_bytes()
        assert b"\r\n" not in final_bytes, "CRLF leaked into the REVIEWED dataset"
        expected = _expected_reviewed_bytes(module, root)
        assert final_bytes == expected

    def test_manifest_hash_derives_from_reviewed_bytes(self, tmp_path, capsys):
        """P0-02: manifest.dataset_hash independently recomputes from
        (final_rel, reviewed_bytes) - NOT from a publish-time reread of
        arbitrary disk bytes."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact)) == 0
        capsys.readouterr()
        expected = _expected_reviewed_bytes(module, root)
        digest = hashlib.sha256()
        digest.update(b"versions/v2-reviewed/rules.yaml")
        digest.update(expected)
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["dataset_hash"] == digest.hexdigest()

    def test_generated_version_replays_on_lf_semantics(self, tmp_path, capsys):
        """Cross-platform replay: the generated version + manifest load
        through the runtime gates with hash agreement (byte-truth is
        platform-independent because the identity is the bytes object)."""
        from ashare_state.spike.trading_rule import load_active_rules, load_bound_rule_book

        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact)) == 0
        capsys.readouterr()
        book, manifest = load_active_rules(root)
        assert manifest.review_status == "REVIEWED"
        bound = load_bound_rule_book(
            rule_version=manifest.rule_version,
            dataset_files=manifest.dataset_files,
            dataset_hash=manifest.dataset_hash,
            dataset_version=manifest.dataset_version,
            source_version=manifest.source_version,
            review_status="REVIEWED",
            rules_root=root,
        )
        assert bound.review_status == "REVIEWED"

    def test_formal_dataset_writes_use_write_bytes_only(self):
        """Static guard: the review tool's formal dataset write path never
        uses Path.write_text (text mode = OS newline translation = broken
        byte identity)."""
        tree = ast.parse((REPO_ROOT / "scripts" / "rules" / "review.py").read_text("utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
        ]
        assert not offenders, (
            f"review.py uses Path.write_text at lines {offenders} - formal "
            "dataset bytes must be written with write_bytes (R4-A2.10 P0-01)"
        )


class TestPublishWindowTamper:
    def test_post_rename_tamper_fails_closed_and_rolls_back(self, tmp_path, monkeypatch, capsys):
        """P0-02 adversarial: after the staging rename publishes the
        version dir, the final rules.yaml is swapped; the read-back
        verification must FAIL CLOSED (rollback: no finalized version, no
        new evidence, ACTIVE stays on the old COMPILED selector)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        version_dir = root / "versions" / "v2-reviewed"
        original_replace = Path.replace

        def tampering_replace(self, target, *args, **kwargs):
            result = original_replace(self, target, *args, **kwargs)
            if Path(target) == version_dir and (version_dir / "rules.yaml").is_file():
                # swap the published bytes AFTER the rename, BEFORE the
                # read-back verification
                (version_dir / "rules.yaml").write_bytes(b"version: tampered\n")
            return result

        monkeypatch.setattr(Path, "replace", tampering_replace)
        code = _run_module(module, _argv(root, artifact))
        monkeypatch.undo()
        capsys.readouterr()
        assert code != 0
        # rolled back: no finalized tampered version, no new evidence
        assert not version_dir.exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.glob("*"))
        # ACTIVE never advanced
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"
        assert doc["review_status"] == "COMPILED"
        # the tampered bytes are NOT blessed into any manifest hash
        assert doc["dataset_files"] == ["versions/v1-compiled/rules.yaml"]

    def test_tampered_retry_is_deterministic(self, tmp_path, monkeypatch, capsys):
        """After a tamper-rollback failure, a clean retry on the SAME root
        with the SAME version succeeds (immutable-version collision is
        impossible because the rollback removed the published dir)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        version_dir = root / "versions" / "v2-reviewed"
        original_replace = Path.replace

        def tampering_replace(self, target, *args, **kwargs):
            result = original_replace(self, target, *args, **kwargs)
            if Path(target) == version_dir and (version_dir / "rules.yaml").is_file():
                (version_dir / "rules.yaml").write_bytes(b"version: tampered\n")
            return result

        monkeypatch.setattr(Path, "replace", tampering_replace)
        assert _run_module(module, _argv(root, artifact)) != 0
        monkeypatch.undo()
        capsys.readouterr()
        # clean retry
        assert _run_module(module, _argv(root, artifact)) == 0
        capsys.readouterr()
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v2-reviewed"
        assert (root / "versions" / "v2-reviewed" / "rules.yaml").is_file()


class TestPreCommitFailureCleanup:
    def test_manifest_write_failure_full_cleanup_and_retry(self, tmp_path, monkeypatch, capsys):
        """P1-01: the tmp-manifest WRITE fails after the version dir was
        published -> uncommitted cleanup (no finalized version, no new
        evidence, no tmp residue, old ACTIVE) and a same-version retry
        succeeds."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        original_write = Path.write_bytes
        tmp_name = ".rule_manifest.json.tmp-v2-reviewed"

        def failing_write(self, data, *args, **kwargs):
            if self.name == tmp_name:
                raise OSError("injected manifest write failure")
            return original_write(self, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_bytes", failing_write)
        with pytest.raises(OSError, match="injected manifest write failure"):
            _run_module(module, _argv(root, artifact))
        monkeypatch.undo()
        capsys.readouterr()
        # uncommitted cleanup
        assert not (root / "versions" / "v2-reviewed").exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.glob("*"))
        assert not [p for p in root.iterdir() if p.name.startswith(".rule_manifest")]
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"
        # same-version retry succeeds
        assert _run_module(module, _argv(root, artifact)) == 0
        doc2 = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc2["rule_version"] == "v2-reviewed"

    def test_manifest_replace_failure_full_cleanup_and_retry(self, tmp_path, monkeypatch, capsys):
        """P1-01: the manifest REPLACE fails after the version dir was
        published -> same uncommitted cleanup + retry semantics."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        original_replace = Path.replace

        def failing_replace(self, target, *args, **kwargs):
            if self.name == ".rule_manifest.json.tmp-v2-reviewed":
                raise OSError("injected manifest replace failure")
            return original_replace(self, target, *args, **kwargs)

        monkeypatch.setattr(Path, "replace", failing_replace)
        with pytest.raises(OSError, match="injected manifest replace failure"):
            _run_module(module, _argv(root, artifact))
        monkeypatch.undo()
        capsys.readouterr()
        assert not (root / "versions" / "v2-reviewed").exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.glob("*"))
        assert not [p for p in root.iterdir() if p.name.startswith(".rule_manifest")]
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"
        assert _run_module(module, _argv(root, artifact)) == 0
        doc2 = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc2["rule_version"] == "v2-reviewed"


class TestSingleWriterLock:
    def test_concurrent_review_blocked_by_lock(self, tmp_path, capsys):
        """P1-02 Option A: a second review while the lock exists fails
        fast with an explicit message."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        (root / ".review.lock").write_text("pid=999 started=stale", encoding="utf-8")
        module = _load_review_module()
        code = _run_module(module, _argv(root, artifact))
        err = capsys.readouterr().err
        assert code != 0
        assert "another review appears to be in progress" in err
        # nothing was mutated
        assert not (root / "versions" / "v2-reviewed").exists()
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"
        # the foreign lock is NOT removed by the failed run
        assert (root / ".review.lock").exists()

    def test_lock_released_after_successful_run(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact)) == 0
        capsys.readouterr()
        assert not (root / ".review.lock").exists()

    def test_lock_released_after_failed_run(self, tmp_path, capsys):
        """Even a failing run (gate failure) releases the lock (finally)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                module,
                "trading_rule_review_gate",
                lambda book, **kwargs: ["synthetic gate failure"],
            )
            assert _run_module(module, _argv(root, artifact)) != 0
        capsys.readouterr()
        assert not (root / ".review.lock").exists()
