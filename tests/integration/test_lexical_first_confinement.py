"""R4-A2.8 P0-02: bound rule LEXICAL-FIRST pre-access confinement tests
(audit 20260825 #4 section 3).

An invalid lexical ref must be rejected BEFORE the candidate path ever
reaches Path.resolve() - proven by spying on Path.resolve itself. Only a
lexically VALID ref may trigger resolution (which then also performs the
symlink-escape check).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    TradingRuleBook,
    _confined_dataset_file,
    load_bound_rule_book,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"


def _make_root(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "rules"
    vdir = root / "versions" / "v1-compiled"
    vdir.mkdir(parents=True)
    shutil.copy(RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml", vdir / "rules.yaml")
    rel = "versions/v1-compiled/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    return root, digest.hexdigest()


class _ResolveSpy:
    """Record every Path.resolve() call (the candidate resolution is the
    fs-aware step that must NOT happen for lexical-invalid refs)."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[str] = []
        original = Path.resolve
        spy = self

        def wrapper(self_path, *args, **kwargs):
            spy.calls.append(str(self_path))
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", wrapper)


def _candidate_resolved(spy: _ResolveSpy, root: Path, rel: str) -> bool:
    """Did the INVALID candidate path (root/rel) itself get resolved?"""
    return any(call.replace("\\", "/").endswith(rel.replace("\\", "/")) for call in spy.calls)


class TestLexicalFirstRejection:
    def test_traversal_rejected_before_candidate_resolve(self, tmp_path, monkeypatch):
        root, dataset_hash = _make_root(tmp_path)
        outside = tmp_path / "outside.yaml"
        outside.write_text("version: evil\n", encoding="utf-8")  # EXISTS
        spy = _ResolveSpy(monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=["../../outside.yaml"],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert not _candidate_resolved(spy, root, "../../outside.yaml"), (
            "the traversal ref reached Path.resolve() before lexical rejection"
        )

    def test_absolute_path_rejected_before_resolve(self, tmp_path, monkeypatch):
        root, dataset_hash = _make_root(tmp_path)
        victim = tmp_path / "abs.yaml"
        victim.write_text("version: evil\n", encoding="utf-8")
        spy = _ResolveSpy(monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=[str(victim)],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert str(victim) not in spy.calls

    def test_drive_letter_path_rejected_before_resolve(self, tmp_path, monkeypatch):
        root, dataset_hash = _make_root(tmp_path)
        spy = _ResolveSpy(monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=["C:/evil/rules.yaml"],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert not any("C:" in call for call in spy.calls)

    def test_foreign_version_dir_rejected_before_candidate_resolve(self, tmp_path, monkeypatch):
        root, dataset_hash = _make_root(tmp_path)
        other = root / "versions" / "v2-other"
        other.mkdir()
        shutil.copy(root / "versions" / "v1-compiled" / "rules.yaml", other / "rules.yaml")
        spy = _ResolveSpy(monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=["versions/v2-other/rules.yaml"],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert not _candidate_resolved(spy, root, "versions/v2-other/rules.yaml")

    def test_valid_lexical_path_does_resolve(self, tmp_path, monkeypatch):
        """A lexically VALID ref proceeds to resolution (Step B) and loads."""
        root, dataset_hash = _make_root(tmp_path)
        spy = _ResolveSpy(monkeypatch)
        book = load_bound_rule_book(
            rule_version="v1-compiled",
            dataset_files=["versions/v1-compiled/rules.yaml"],
            dataset_hash=dataset_hash,
            rules_root=root,
        )
        assert isinstance(book, TradingRuleBook)
        assert spy.calls  # resolution actually happened

    def test_symlink_escape_blocked_at_resolved_confinement(self, tmp_path):
        """Lexically valid + symlink pointing outside -> Step B rejects."""
        try:
            root, _ = _make_root(tmp_path)
            outside = tmp_path / "outside.yaml"
            outside.write_text("version: evil\n", encoding="utf-8")
            link = root / "versions" / "v1-compiled" / "linked.yaml"
            link.symlink_to(outside)
        except OSError:
            pytest.skip("creating symlinks requires elevated privileges on this OS")
        ok, reason = _confined_dataset_file(
            root, "versions/v1-compiled/linked.yaml", rule_version="v1-compiled"
        )
        assert not ok
        assert "escapes the rules root" in reason

    def test_normal_bound_replay_still_passes(self, tmp_path: Path):
        root, dataset_hash = _make_root(tmp_path)
        book = load_bound_rule_book(
            rule_version="v1-compiled",
            dataset_files=["versions/v1-compiled/rules.yaml"],
            dataset_hash=dataset_hash,
            rules_root=root,
        )
        assert book.review_status == "COMPILED"


class TestLexicalHelperUnits:
    def test_lexical_step_a_rejects_without_fs(self, tmp_path, monkeypatch):
        """The lexical helper itself never touches the filesystem."""
        root = tmp_path / "rules"
        spy = _ResolveSpy(monkeypatch)
        ok, reason = _confined_dataset_file(root, "../../evil.yaml", rule_version="v1")
        assert not ok
        assert "'..' traversal" in reason
        assert spy.calls == []

    def test_lexical_step_a_valid_then_resolved(self, tmp_path, monkeypatch):
        root, _ = _make_root(tmp_path)
        spy = _ResolveSpy(monkeypatch)
        ok, _reason = _confined_dataset_file(
            root, "versions/v1-compiled/rules.yaml", rule_version="v1-compiled"
        )
        assert ok
        assert spy.calls  # Step B executed
