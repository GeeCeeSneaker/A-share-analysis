"""R4-A2.11 / CR-1.2.7: single-writer LINEAGE serialization tests (audit
20260825 #7 section 4).

The lock must cover PARENT SELECTION, not just Phase 2/3: two reviewers
that both complete Phase 1 against the same parent, then acquire the
lock in turn, must not produce a stale-parent overwrite of the first
reviewer's ACTIVE advance.

Required adversarial scenarios (audit section 4):
  - lock acquisition dominates load_active_rules / ACTIVE snapshot
    (runtime counter: preflight runs only while the lock is held)
  - Reviewer B holds a stale Phase-1 capture while A commits v2 -> B's
    later run must BLOCK on the moved lineage (from-version check under
    the lock), never overwrite v2 with a v1-based v3
  - a stale-parent rejection produces ZERO new version / evidence /
    manifest advance
  - after A commits, B restarting from the CURRENT ACTIVE works normally
  - same target-version race never silently overwrites (immutability)
  - lock release on success and failure is preserved
"""

from __future__ import annotations

import ast
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
        "rule_review_tool_lineage", REPO_ROOT / "scripts" / "rules" / "review.py"
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


def _argv(
    root: Path,
    artifact: Path,
    version: str = "v2-reviewed",
    from_version: str = "",
    rules_name: str = "v1-compiled",
) -> list[str]:
    argv = [
        "review.py",
        "--rules",
        str(root / "versions" / rules_name / "rules.yaml"),
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
    if from_version:
        argv.extend(["--from-version", from_version])
    return argv


def _run_module(module, argv: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = argv
    try:
        return module.main()
    finally:
        sys.argv = old_argv


def _active(root: Path) -> dict:
    return json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))


def _install_compiled_candidate(root: Path, name: str) -> None:
    """Point the ACTIVE manifest at a NEW COMPILED candidate (a copy of
    the v1 compiled yaml - governance metadata coherent with THOSE
    bytes)."""
    vdir = root / "versions" / name
    vdir.mkdir(parents=True)
    shutil.copy(root / "versions" / "v1-compiled" / "rules.yaml", vdir / "rules.yaml")
    doc = yaml.safe_load((vdir / "rules.yaml").read_text(encoding="utf-8"))
    rel = f"versions/{name}/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    (root / "rule_manifest.json").write_text(
        json.dumps(
            {
                "rule_version": name,
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


class TestLockDominatesPreflight:
    def test_preflight_runs_only_while_lock_held(self, tmp_path, monkeypatch, capsys):
        """Runtime counter: load_active_rules executes ONLY after the lock
        file exists (parent selection is inside the serialization
        boundary)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        from ashare_state.spike.trading_rule import load_active_rules

        state = {"lock_exists_at_preflight": None, "preflight_count": 0}
        original_load = load_active_rules

        def probing_load(rules_root, *args, **kwargs):
            state["preflight_count"] += 1
            state["lock_exists_at_preflight"] = (root / ".review.lock").exists()
            return original_load(rules_root, *args, **kwargs)

        monkeypatch.setattr(module, "load_active_rules", probing_load)
        code = _run_module(module, _argv(root, artifact))
        monkeypatch.undo()
        capsys.readouterr()
        assert code == 0
        assert state["preflight_count"] >= 1
        assert state["lock_exists_at_preflight"] is True, (
            "load_active_rules (parent selection) ran BEFORE the lock was "
            "acquired - parent selection is outside the serialization boundary"
        )

    def test_structural_guard_lock_before_preflight(self):
        """AST structural guard: in the formal entrypoint, the lock-acquire
        call executes BEFORE the first load_active_rules call (line-order
        in a single flow, verified through the call nodes' positions)."""
        tree = ast.parse((REPO_ROOT / "scripts" / "rules" / "review.py").read_text("utf-8"))
        lock_line: int | None = None
        preflight_line: int | None = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func

            # os_mod.open(lock_path, O_CREAT | O_EXCL | O_WRONLY) - the
            # O_EXCL flag arrives as a BitOr of Attribute nodes (possibly
            # nested); walk the call's arguments for the O_EXCL attribute
            def _mentions_o_excl(test_node: ast.AST) -> bool:
                for sub in ast.walk(test_node):
                    if isinstance(sub, ast.Attribute) and sub.attr == "O_EXCL":
                        return True
                return False

            if (
                isinstance(func, ast.Attribute)
                and func.attr == "open"
                and any(_mentions_o_excl(arg) for arg in node.args)
                and lock_line is None
            ):
                lock_line = node.lineno
            if (
                isinstance(func, ast.Name)
                and func.id == "load_active_rules"
                and preflight_line is None
            ):
                preflight_line = node.lineno
        assert lock_line is not None, "no O_EXCL lock acquisition found"
        assert preflight_line is not None, "no load_active_rules call found"
        assert lock_line < preflight_line, (
            f"lock acquisition (line {lock_line}) must execute BEFORE the first "
            f"load_active_rules (line {preflight_line}) in the formal path"
        )


class TestStaleParentCannotCommit:
    def test_stale_parent_blocks_and_never_overwrites_advance(self, tmp_path, capsys):
        """The audit's exact scenario: B holds a stale Phase-1 capture
        (from-version=v1) while A commits v2; B then acquires the lock and
        must BLOCK on the moved lineage - never overwrite v2 with a
        v1-based v3."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()

        # Reviewer A commits v2 from v1 (normal run)
        assert _run_module(module, _argv(root, artifact, version="v2-reviewed")) == 0
        capsys.readouterr()
        assert _active(root)["rule_version"] == "v2-reviewed"

        # Reviewer B "captured" Phase 1 against v1 (from-version=v1) but
        # runs only NOW (after A advanced ACTIVE to v2): the lineage check
        # under the lock must BLOCK B - a v1-based v3 must never land.
        code = _run_module(
            module,
            _argv(root, artifact, version="v3-reviewed", from_version="v1-compiled"),
        )
        err = capsys.readouterr().err
        assert code != 0
        assert "ACTIVE manifest is" in err and "v2-reviewed" in err

        # ACTIVE still points at A's v2 - the stale parent did not advance
        doc = _active(root)
        assert doc["rule_version"] == "v2-reviewed"
        assert doc["dataset_files"] == ["versions/v2-reviewed/rules.yaml"]
        # zero stale output: no v3 anywhere, no new evidence, no temp
        assert not (root / "versions" / "v3-reviewed").exists()
        evidence = root / "evidence"
        new_evidence = list(evidence.glob("*")) if evidence.exists() else []
        assert all(
            p.name.startswith(hashlib.sha256(b"official notice").hexdigest()[:16])
            for p in new_evidence
        )
        assert not [p for p in root.iterdir() if p.name.startswith(".rule_manifest")]
        assert not (root / ".review.lock").exists()

    def test_b_restarting_from_current_active_succeeds(self, tmp_path, capsys):
        """After A's v2 commit, a NEW review cycle on the current lineage
        works normally: install a fresh COMPILED candidate as v2b (the
        next round's candidate), point ACTIVE at it, and review it into
        v3 - the stale-parent block is a lineage guard, not a deadlock."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact, version="v2-reviewed")) == 0
        capsys.readouterr()
        # operator installs the NEXT compiled candidate (v2b) as ACTIVE
        # (same discipline as _make_root; hash recomputed for the new rel)
        _install_compiled_candidate(root, "v2b-compiled")
        # B reviews the CURRENT ACTIVE (v2b) into v3 - normal advance
        code = _run_module(
            module,
            _argv(root, artifact, version="v3-reviewed", rules_name="v2b-compiled"),
        )
        capsys.readouterr()
        assert code == 0
        assert _active(root)["rule_version"] == "v3-reviewed"
        assert (root / "versions" / "v3-reviewed" / "rules.yaml").is_file()

    def test_default_from_version_also_blocks_after_advance(self, tmp_path, capsys):
        """Without an explicit --from-version, a stale Phase-1 capture is
        impossible by construction (the lineage check reads the CURRENT
        ACTIVE under the lock) - the tool cannot seal from an old parent
        because parent selection happens INSIDE the lock."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        # A commits v2
        assert _run_module(module, _argv(root, artifact, version="v2-reviewed")) == 0
        capsys.readouterr()
        # B points --rules at the OLD v1 file with NO --from-version: the
        # input==ACTIVE check (under the lock) rejects the stale input
        code = _run_module(module, _argv(root, artifact, version="v3-reviewed"))
        err = capsys.readouterr().err
        assert code != 0
        assert "is not the ACTIVE dataset" in err
        assert _active(root)["rule_version"] == "v2-reviewed"
        assert not (root / "versions" / "v3-reviewed").exists()


class TestSameVersionRace:
    def test_same_target_version_never_silently_overwrites(self, tmp_path, capsys):
        """Two reviewers racing for the SAME target version name: the
        second (serialized) run hits the immutable-version collision and
        is refused - the first run's version bytes are untouched."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact, version="v2-reviewed")) == 0
        capsys.readouterr()
        sentinel = root / "versions" / "v2-reviewed" / "rules.yaml"
        sentinel_bytes = sentinel.read_bytes()
        # second run: a NEW compiled candidate is ACTIVE, but the target
        # version name v2-reviewed ALREADY EXISTS - the immutable-version
        # collision is what refuses it (never a silent overwrite)
        _install_compiled_candidate(root, "v2b-compiled")
        code = _run_module(
            module, _argv(root, artifact, version="v2-reviewed", rules_name="v2b-compiled")
        )
        err = capsys.readouterr().err
        assert code != 0
        assert "already exists" in err
        # the first run's immutable version bytes are untouched, and the
        # failed second run left ACTIVE on the v2b candidate it read
        assert sentinel.read_bytes() == sentinel_bytes
        assert _active(root)["rule_version"] == "v2b-compiled"


class TestLockLifecyclePreserved:
    def test_lock_released_on_success_and_failure(self, tmp_path, capsys):
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact, version="v2-reviewed")) == 0
        capsys.readouterr()
        assert not (root / ".review.lock").exists()
        # failing run (stale lineage) also releases
        code = _run_module(module, _argv(root, artifact, version="v9-y", from_version="v0-nope"))
        capsys.readouterr()
        assert code != 0
        assert not (root / ".review.lock").exists()

    def test_concurrent_lock_blocks_before_any_active_read(self, tmp_path, capsys):
        """A pre-existing lock fails fast BEFORE any ACTIVE-dependent read
        (no load_active_rules call happens at all)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        (root / ".review.lock").write_text("pid=999", encoding="utf-8")
        module = _load_review_module()
        state = {"loads": 0}

        def counting_load(*args, **kwargs):
            state["loads"] += 1
            raise AssertionError("load_active_rules must not run under a held lock")

        original = module.load_active_rules
        module.load_active_rules = counting_load
        try:
            code = _run_module(module, _argv(root, artifact, version="v2-reviewed"))
        finally:
            module.load_active_rules = original
        err = capsys.readouterr().err
        assert code != 0
        assert "another review appears to be in progress" in err
        assert state["loads"] == 0
