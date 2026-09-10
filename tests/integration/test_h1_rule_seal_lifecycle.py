"""H1 non-ACTIVE candidate seal lifecycle contract tests.

These tests use an isolated temporary rule store and synthetic bytes behind
the already-declared first-party URLs; no network or real evidence is used.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from ashare_state.spike.rule_evidence import (
    RULE_EVIDENCE_BUNDLE_SCHEMA,
    prepare_rule_evidence_bundle,
    source_urls_from_ref,
)
from ashare_state.spike.trading_rule import TradingRuleBook, load_active_rules, load_rule_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"
CANDIDATE_VERSION = "h1-compiled"
PARENT_VERSION = "v1-compiled"
REVIEWED_VERSION = "h1-reviewed"


def _load_review_module():
    spec = importlib.util.spec_from_file_location(
        "rule_review_tool_h1_lifecycle", REPO_ROOT / "scripts" / "rules" / "review.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset_hash(root: Path, rel: str) -> str:
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    return digest.hexdigest()


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "rules"
    parent_dir = root / "versions" / PARENT_VERSION
    candidate_dir = root / "versions" / CANDIDATE_VERSION
    parent_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)
    shutil.copy(
        RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml",
        parent_dir / "rules.yaml",
    )
    shutil.copy(
        RULES_DIR / "versions" / "v20260909-h1-compiled" / "rules.yaml",
        candidate_dir / "rules.yaml",
    )
    parent_rel = f"versions/{PARENT_VERSION}/rules.yaml"
    parent_doc = yaml.safe_load((root / parent_rel).read_text(encoding="utf-8"))
    manifest = {
        "rule_version": PARENT_VERSION,
        "review_status": "COMPILED",
        "dataset_files": [parent_rel],
        "dataset_hash": _dataset_hash(root, parent_rel),
        "source_version": str(parent_doc["source_version"]),
        "dataset_version": str(parent_doc["version"]),
        "review_provenance": {"source_retrieved_at": str(parent_doc["source_retrieved_at"])},
    }
    (root / "rule_manifest.json").write_bytes((json.dumps(manifest) + "\n").encode("utf-8"))
    return root


def _candidate_path(root: Path) -> Path:
    return root / "versions" / CANDIDATE_VERSION / "rules.yaml"


def _candidate_hash(root: Path) -> str:
    return _dataset_hash(root, f"versions/{CANDIDATE_VERSION}/rules.yaml")


def _move_active_parent(root: Path, version: str = "moved-compiled") -> None:
    source = root / "versions" / PARENT_VERSION / "rules.yaml"
    target_dir = root / "versions" / version
    target_dir.mkdir()
    shutil.copy(source, target_dir / "rules.yaml")
    rel = f"versions/{version}/rules.yaml"
    doc = yaml.safe_load((target_dir / "rules.yaml").read_text(encoding="utf-8"))
    manifest = {
        "rule_version": version,
        "review_status": "COMPILED",
        "dataset_files": [rel],
        "dataset_hash": _dataset_hash(root, rel),
        "source_version": str(doc["source_version"]),
        "dataset_version": str(doc["version"]),
        "review_provenance": {"source_retrieved_at": str(doc["source_retrieved_at"])},
    }
    (root / "rule_manifest.json").write_bytes((json.dumps(manifest) + "\n").encode())


def _make_bundle(tmp_path: Path, root: Path) -> Path:
    candidate_doc = yaml.safe_load(_candidate_path(root).read_text(encoding="utf-8"))
    input_dir = tmp_path / "bundle-input"
    input_dir.mkdir()
    entries: list[dict[str, object]] = []
    for rule_index, rule in enumerate(candidate_doc["rules"]):
        sources: list[dict[str, object]] = []
        urls = source_urls_from_ref(rule["source_ref"])
        for source_index, source_url in enumerate(urls):
            name = f"source-{rule_index:02d}-{source_index:02d}.bin"
            (input_dir / name).write_bytes(
                f"synthetic official source {rule['rule_id']} {source_url}".encode()
            )
            roles = ("RULE", "APPLICABILITY", "TRANSITION")
            sources.append(
                {
                    "artifact_kind": "EXCHANGE_NOTICE",
                    "artifact_path": name,
                    "role": roles[source_index % len(roles)],
                    "source_url": source_url,
                }
            )
        entries.append({"rule_id": rule["rule_id"], "sources": sources})
    manifest = input_dir / "bundle.json"
    manifest.write_bytes(
        (
            json.dumps(
                {
                    "schema_version": RULE_EVIDENCE_BUNDLE_SCHEMA,
                    "dataset_version": candidate_doc["version"],
                    "entries": entries,
                }
            )
            + "\n"
        ).encode("utf-8")
    )
    return manifest


def _prepare_candidate_bundle(root: Path, bundle: Path):
    candidate_doc = yaml.safe_load(_candidate_path(root).read_text(encoding="utf-8"))
    return prepare_rule_evidence_bundle(
        bundle,
        expected_rule_ids=[str(rule["rule_id"]) for rule in candidate_doc["rules"]],
        expected_dataset_version=str(candidate_doc["version"]),
        expected_source_urls_by_rule={
            str(rule["rule_id"]): source_urls_from_ref(rule["source_ref"])
            for rule in candidate_doc["rules"]
        },
    )


def _argv(
    root: Path,
    bundle: Path,
    *,
    candidate: Path | None = None,
    candidate_version: str = CANDIDATE_VERSION,
    expected_candidate_hash: str | None = None,
    expected_active_version: str = PARENT_VERSION,
    reviewed_version: str = REVIEWED_VERSION,
    reviewer: str = "project-owner",
) -> list[str]:
    candidate = candidate or _candidate_path(root)
    expected_candidate_hash = expected_candidate_hash or _candidate_hash(root)
    return [
        "review.py",
        "--candidate",
        str(candidate),
        "--candidate-version",
        candidate_version,
        "--expected-candidate-hash",
        expected_candidate_hash,
        "--evidence-bundle",
        str(bundle),
        "--reviewer",
        reviewer,
        "--version",
        reviewed_version,
        "--from-version",
        expected_active_version,
        "--rules-root",
        str(root),
    ]


def _run(module, argv: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = argv
    try:
        return module.main()
    finally:
        sys.argv = old_argv


def _assert_old_state(root: Path, parent_bytes: bytes, candidate_bytes: bytes) -> None:
    assert (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes() == parent_bytes
    assert _candidate_path(root).read_bytes() == candidate_bytes
    assert load_rule_manifest(root).rule_version == PARENT_VERSION
    assert not (root / "versions" / REVIEWED_VERSION).exists()
    evidence = root / "evidence"
    assert not evidence.exists() or not list(evidence.rglob("*"))
    assert not list((root / "versions").glob(".staging-*"))
    assert not list(root.glob(".rule_manifest.json.tmp-*"))


class TestH1CandidateSealHappyPath:
    def test_non_active_candidate_seals_directly_to_new_reviewed(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        parent_path = root / "versions" / PARENT_VERSION / "rules.yaml"
        candidate_path = _candidate_path(root)
        parent_bytes = parent_path.read_bytes()
        candidate_bytes = candidate_path.read_bytes()
        module = _load_review_module()

        assert _run(module, _argv(root, bundle)) == 0
        capsys.readouterr()

        manifest = load_rule_manifest(root)
        assert manifest.rule_version == REVIEWED_VERSION
        assert manifest.review_status == "REVIEWED"
        assert manifest.dataset_files == (f"versions/{REVIEWED_VERSION}/rules.yaml",)
        assert candidate_path.read_bytes() == candidate_bytes
        assert parent_path.read_bytes() == parent_bytes
        candidate_book = TradingRuleBook.load(candidate_path)
        assert candidate_book.review_status == "COMPILED"
        reviewed_book, reviewed_manifest = load_active_rules(root)
        assert reviewed_manifest.rule_version == REVIEWED_VERSION
        assert reviewed_book.review_status == "REVIEWED"
        assert tuple(reviewed_book.rules) == tuple(candidate_book.rules)
        assert (
            module.trading_rule_review_gate(
                reviewed_book, rules_root=root, require_evidence_bundle=True
            )
            == []
        )
        assert CANDIDATE_VERSION not in (root / "rule_manifest.json").read_text(encoding="utf-8")

    def test_owner_authorized_ai_reviewer_marker_is_accepted(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        module = _load_review_module()

        assert (
            _run(
                module,
                _argv(root, bundle, reviewer="owner-authorized-ai-reviewer"),
            )
            == 0
        )
        capsys.readouterr()
        manifest = load_rule_manifest(root)
        assert manifest.rule_version == REVIEWED_VERSION
        assert manifest.review_status == "REVIEWED"
        reviewed_text = (root / "versions" / REVIEWED_VERSION / "rules.yaml").read_text(
            encoding="utf-8"
        )
        assert "reviewed_by: owner-authorized-ai-reviewer" in reviewed_text
        assert "Candidate only" not in reviewed_text
        assert "human-reviewed" not in reviewed_text
        assert (
            "Evidence was sealed under the owner-authorized AI reviewer provenance marker."
            in reviewed_text
        )

    def test_post_snapshot_candidate_mutation_fails_closed(self, tmp_path, monkeypatch, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        candidate = _candidate_path(root)
        original_candidate_bytes = candidate.read_bytes()
        expected_candidate_hash = _candidate_hash(root)
        module = _load_review_module()
        original_read_bytes = Path.read_bytes
        state = {"candidate_reads": 0}

        def swapping_read(path: Path, *args, **kwargs):
            if path.resolve() == candidate.resolve():
                state["candidate_reads"] += 1
                result = original_read_bytes(path, *args, **kwargs)
                if state["candidate_reads"] == 1:
                    candidate.write_bytes(result + b"\n# changed after snapshot\n")
                return result
            return original_read_bytes(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", swapping_read)
        assert (
            _run(
                module,
                _argv(root, bundle, expected_candidate_hash=expected_candidate_hash),
            )
            != 0
        )
        monkeypatch.undo()
        capsys.readouterr()

        assert state["candidate_reads"] == 2
        assert candidate.read_bytes() != original_candidate_bytes
        assert load_rule_manifest(root).rule_version == PARENT_VERSION
        assert not (root / "versions" / REVIEWED_VERSION).exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.rglob("*"))
        assert not list((root / "versions").glob(".staging-*"))

    def test_candidate_mutation_after_precommit_check_is_commit_inconsistent(
        self, tmp_path, monkeypatch, capsys
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        candidate = _candidate_path(root)
        original_candidate_bytes = candidate.read_bytes()
        module = _load_review_module()
        original_replace = Path.replace

        def mutate_after_manifest_replace(path: Path, target: Path, *args, **kwargs):
            result = original_replace(path, target, *args, **kwargs)
            if path.name.startswith(".rule_manifest.json.tmp-"):
                candidate.write_bytes(original_candidate_bytes + b"\n# changed after commit\n")
            return result

        monkeypatch.setattr(Path, "replace", mutate_after_manifest_replace)
        assert _run(module, _argv(root, bundle)) == 3
        monkeypatch.undo()
        captured = capsys.readouterr()

        assert "REVIEW_COMMIT_INCONSISTENT" in captured.err
        assert candidate.read_bytes() != original_candidate_bytes
        assert load_rule_manifest(root).rule_version == REVIEWED_VERSION
        assert (root / "versions" / REVIEWED_VERSION / "rules.yaml").is_file()

    def test_parent_mutation_after_manifest_commit_is_commit_inconsistent(
        self, tmp_path, monkeypatch, capsys
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        parent = root / "versions" / PARENT_VERSION / "rules.yaml"
        original_parent_bytes = parent.read_bytes()
        module = _load_review_module()
        original_replace = Path.replace

        def mutate_parent_after_manifest_replace(path: Path, target: Path, *args, **kwargs):
            result = original_replace(path, target, *args, **kwargs)
            if path.name.startswith(".rule_manifest.json.tmp-"):
                parent.write_bytes(original_parent_bytes + b"\n# changed after commit\n")
            return result

        monkeypatch.setattr(Path, "replace", mutate_parent_after_manifest_replace)
        assert _run(module, _argv(root, bundle)) == 3
        monkeypatch.undo()
        captured = capsys.readouterr()

        assert "REVIEW_COMMIT_INCONSISTENT" in captured.err
        assert parent.read_bytes() != original_parent_bytes
        assert load_rule_manifest(root).rule_version == REVIEWED_VERSION
        assert (root / "versions" / REVIEWED_VERSION / "rules.yaml").is_file()


class TestH1CandidateSealPreflight:
    def test_wrong_expected_parent_has_zero_mutation(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()

        assert _run(module, _argv(root, bundle, expected_active_version="moved-parent")) != 0
        capsys.readouterr()
        _assert_old_state(root, parent_bytes, candidate_bytes)

    def test_parent_movement_during_seal_is_rejected_before_publish(
        self, tmp_path, capsys, monkeypatch
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()
        original_check = module._expected_parent_problem
        moved = {"done": False}

        def move_before_core_publish(**kwargs):
            if not moved["done"]:
                _move_active_parent(root)
                moved["done"] = True
            return original_check(**kwargs)

        monkeypatch.setattr(module, "_expected_parent_problem", move_before_core_publish)
        assert _run(module, _argv(root, bundle)) != 0
        capsys.readouterr()

        assert load_rule_manifest(root).rule_version == "moved-compiled"
        assert _candidate_path(root).read_bytes() == candidate_bytes
        assert not (root / "versions" / REVIEWED_VERSION).exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.rglob("*"))

    def test_parent_movement_after_staging_rolls_back_new_outputs(
        self, tmp_path, capsys, monkeypatch
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()
        original_check = module._expected_parent_problem
        checks = {"count": 0}

        def move_after_first_parent_check(**kwargs):
            checks["count"] += 1
            if checks["count"] == 2:
                _move_active_parent(root)
            return original_check(**kwargs)

        monkeypatch.setattr(module, "_expected_parent_problem", move_after_first_parent_check)
        assert _run(module, _argv(root, bundle)) != 0
        capsys.readouterr()

        assert checks["count"] == 2
        assert load_rule_manifest(root).rule_version == "moved-compiled"
        assert _candidate_path(root).read_bytes() == candidate_bytes
        assert not (root / "versions" / REVIEWED_VERSION).exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.rglob("*"))

    @pytest.mark.parametrize("path_kind", ["outside", "traversal"])
    def test_candidate_path_must_be_exactly_confined(self, tmp_path, path_kind, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        if path_kind == "outside":
            candidate = tmp_path / "outside.yaml"
            candidate.write_bytes(_candidate_path(root).read_bytes())
        else:
            candidate = Path(
                str(root / "versions" / CANDIDATE_VERSION / ".." / CANDIDATE_VERSION)
                + os.sep
                + "rules.yaml"
            )
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()

        assert _run(module, _argv(root, bundle, candidate=candidate)) != 0
        capsys.readouterr()
        _assert_old_state(root, parent_bytes, candidate_bytes)

    def test_symlinked_candidate_version_is_rejected(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        source_dir = tmp_path / "escaped-candidate"
        source_dir.mkdir()
        (source_dir / "rules.yaml").write_bytes(_candidate_path(root).read_bytes())
        shutil.rmtree(root / "versions" / CANDIDATE_VERSION)
        try:
            (root / "versions" / CANDIDATE_VERSION).symlink_to(source_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        module = _load_review_module()

        assert _run(module, _argv(root, bundle)) != 0
        capsys.readouterr()
        assert load_rule_manifest(root).rule_version == PARENT_VERSION
        assert not (root / "versions" / REVIEWED_VERSION).exists()

    def test_candidate_hash_mismatch_has_zero_mutation(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()

        assert _run(module, _argv(root, bundle, expected_candidate_hash="0" * 64)) != 0
        capsys.readouterr()
        _assert_old_state(root, parent_bytes, candidate_bytes)

    def test_reviewed_candidate_is_not_resealed(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        candidate = _candidate_path(root)
        candidate.write_bytes(
            candidate.read_bytes().replace(
                b'review_status: "COMPILED"', b'review_status: "REVIEWED"', 1
            )
        )
        bundle = _make_bundle(tmp_path, root)
        module = _load_review_module()
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = candidate.read_bytes()

        assert _run(module, _argv(root, bundle)) != 0
        capsys.readouterr()
        _assert_old_state(root, parent_bytes, candidate_bytes)

    def test_held_lock_blocks_before_candidate_read(self, tmp_path, capsys, monkeypatch):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        candidate = _candidate_path(root)
        (root / ".review.lock").write_bytes(b"pid=999")
        expected_candidate_hash = _candidate_hash(root)
        module = _load_review_module()
        original = Path.read_bytes
        reads = {"candidate": 0}

        def counting(path: Path, *args, **kwargs):
            if path.resolve() == candidate.resolve():
                reads["candidate"] += 1
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", counting)
        assert (
            _run(
                module,
                _argv(root, bundle, expected_candidate_hash=expected_candidate_hash),
            )
            != 0
        )
        assert reads["candidate"] == 0
        assert (root / ".review.lock").is_file()


class TestH1CandidateEvidenceFailures:
    @pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
    def test_malformed_input_bundle_fails_through_candidate_entry_point(
        self, tmp_path, mutation, capsys
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        document = json.loads(bundle.read_text(encoding="utf-8"))
        first_sources = document["entries"][0]["sources"]
        if mutation == "missing":
            first_sources.pop()
        elif mutation == "extra":
            extra_name = "extra-source.bin"
            (bundle.parent / extra_name).write_bytes(b"undeclared extra source")
            extra = dict(first_sources[0])
            extra["artifact_path"] = extra_name
            extra["source_url"] = "https://www.sse.com.cn/not-declared-by-rule"
            first_sources.append(extra)
        else:
            first_sources.append(dict(first_sources[0]))
        bundle.write_text(json.dumps(document), encoding="utf-8")

        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()

        assert _run(module, _argv(root, bundle)) != 0
        capsys.readouterr()
        _assert_old_state(root, parent_bytes, candidate_bytes)

    def test_preexisting_bundle_wrong_hash_fails_closed(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        prepared = _prepare_candidate_bundle(root, bundle)
        bundle_hash = hashlib.sha256(prepared.content).hexdigest()
        wrong_bundle_path = root / "evidence" / f"sha256/{bundle_hash}"
        wrong_bundle_path.parent.mkdir(parents=True)
        wrong_bundle_path.write_bytes(b"wrong bundle bytes")
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()

        assert _run(module, _argv(root, bundle)) != 0
        capsys.readouterr()

        assert load_rule_manifest(root).rule_version == PARENT_VERSION
        assert (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes() == parent_bytes
        assert _candidate_path(root).read_bytes() == candidate_bytes
        assert not (root / "versions" / REVIEWED_VERSION).exists()
        assert wrong_bundle_path.read_bytes() == b"wrong bundle bytes"
        assert [path for path in (root / "evidence").rglob("*") if path.is_file()] == [
            wrong_bundle_path
        ]
        assert not list((root / "versions").glob(".staging-*"))

    def test_raw_evidence_tamper_during_candidate_seal_fails_closed(
        self, tmp_path, monkeypatch, capsys
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        prepared = _prepare_candidate_bundle(root, bundle)
        target = root / "evidence" / prepared.raw_artifacts[0].artifact_ref
        module = _load_review_module()
        original_write = Path.write_bytes
        tampered = {"done": False}

        def write_then_tamper(path: Path, data: bytes, *args, **kwargs):
            result = original_write(path, data, *args, **kwargs)
            if path == target and not tampered["done"]:
                original_write(path, b"tampered raw source")
                tampered["done"] = True
            return result

        monkeypatch.setattr(Path, "write_bytes", write_then_tamper)
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        assert _run(module, _argv(root, bundle)) != 0
        monkeypatch.undo()
        capsys.readouterr()

        assert tampered["done"]
        _assert_old_state(root, parent_bytes, candidate_bytes)


class TestH1CandidateSealRollback:
    def test_staged_gate_failure_removes_every_new_output(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        parent_bytes = (root / "versions" / PARENT_VERSION / "rules.yaml").read_bytes()
        candidate_bytes = _candidate_path(root).read_bytes()
        module = _load_review_module()
        original_gate = module.trading_rule_review_gate
        module.trading_rule_review_gate = lambda *args, **kwargs: ["synthetic gate failure"]
        try:
            assert _run(module, _argv(root, bundle)) != 0
        finally:
            module.trading_rule_review_gate = original_gate
        capsys.readouterr()
        _assert_old_state(root, parent_bytes, candidate_bytes)

    def test_manifest_write_failure_rolls_back_and_releases_lock(
        self, tmp_path, monkeypatch, capsys
    ):
        root = _make_root(tmp_path)
        bundle = _make_bundle(tmp_path, root)
        module = _load_review_module()
        original_write = Path.write_bytes
        tmp_name = f".rule_manifest.json.tmp-{REVIEWED_VERSION}"

        def failing_write(path: Path, data: bytes, *args, **kwargs):
            if path.name == tmp_name:
                raise OSError("injected candidate manifest write failure")
            return original_write(path, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_bytes", failing_write)
        with pytest.raises(OSError, match="injected candidate manifest write failure"):
            _run(module, _argv(root, bundle))
        monkeypatch.undo()
        capsys.readouterr()

        assert load_rule_manifest(root).rule_version == PARENT_VERSION
        assert not (root / "versions" / REVIEWED_VERSION).exists()
        assert not (root / ".review.lock").exists()
        evidence = root / "evidence"
        assert not evidence.exists() or not list(evidence.rglob("*"))
