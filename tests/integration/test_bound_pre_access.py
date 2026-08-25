"""R4-A2.7 P0-01: bound-rule confinement BEFORE any filesystem access
(audit 20260825 #3 section 2).

A tampered historical binding (dataset_files[0]="../../outside.yaml")
must be rejected WITHOUT a single filesystem probe/read on the escape
path - proven by spying on Path methods.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    TradingRuleBook,
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


class _FsSpy:
    """Count filesystem probes that touch paths OUTSIDE the rules root."""

    def __init__(self, root: Path, monkeypatch) -> None:
        self.root = root.resolve()
        self.outside_probes: list[str] = []
        for name in ("is_file", "read_bytes", "open"):
            original = getattr(Path, name)
            wrapper = self._make_wrapper(original, name)
            monkeypatch.setattr(Path, name, wrapper)

    def _make_wrapper(self, original, label):
        spy = self

        def wrapper(self_path, *args, **kwargs):
            try:
                resolved = self_path.resolve()
            except OSError:
                resolved = self_path
            if not resolved.is_relative_to(spy.root):
                spy.outside_probes.append(f"{label}:{self_path}")
            return original(self_path, *args, **kwargs)

        return wrapper


class TestBoundPreAccessConfinement:
    def test_traversal_outside_file_exists_blocked_without_probe(self, tmp_path, monkeypatch):
        """dataset_files[0] = ../../outside.yaml with the outside file
        ACTUALLY PRESENT: the rejection must happen before ANY filesystem
        access outside the rules root."""
        root, dataset_hash = _make_root(tmp_path)
        outside = tmp_path / "outside.yaml"
        outside.write_text("version: evil\n", encoding="utf-8")  # EXISTS
        spy = _FsSpy(root, monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=["../../outside.yaml"],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert spy.outside_probes == [], (
            "filesystem probed OUTSIDE the rules root before confinement "
            f"rejected the binding: {spy.outside_probes}"
        )

    def test_absolute_path_blocked_without_probe(self, tmp_path, monkeypatch):
        root, dataset_hash = _make_root(tmp_path)
        victim = tmp_path / "abs.yaml"
        victim.write_text("version: evil\n", encoding="utf-8")
        spy = _FsSpy(root, monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=[str(victim)],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert spy.outside_probes == []

    def test_foreign_version_dir_blocked_without_probe(self, tmp_path, monkeypatch):
        """versions/<other>/... - the file exists INSIDE the root but the
        structural mismatch still rejects before reading it."""
        root, dataset_hash = _make_root(tmp_path)
        other = root / "versions" / "v2-other"
        other.mkdir()
        shutil.copy(root / "versions" / "v1-compiled" / "rules.yaml", other / "rules.yaml")
        spy = _FsSpy(root, monkeypatch)
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=["versions/v2-other/rules.yaml"],
                dataset_hash=dataset_hash,
                rules_root=root,
            )
        assert spy.outside_probes == []

    def test_valid_bound_multi_file_version_passes(self, tmp_path: Path):
        """A valid version-local MULTI-file dataset loads and re-verifies
        (hash covers every file)."""
        root, _ = _make_root(tmp_path)
        vdir = root / "versions" / "v1-compiled"
        main_doc = yaml.safe_load((vdir / "rules.yaml").read_text(encoding="utf-8"))
        extra = vdir / "rules_extra.yaml"
        # companion file: same governance metadata (the loader requires the
        # version identity to be coherent across the dataset's files)
        extra.write_text(
            "version: "
            + str(main_doc["version"])
            + "\nsource_version: "
            + str(main_doc["source_version"])
            + "\nreview_status: COMPILED\nrules: []\n",
            encoding="utf-8",
        )
        files = ["versions/v1-compiled/rules.yaml", "versions/v1-compiled/rules_extra.yaml"]
        digest = hashlib.sha256()
        for rel in sorted(files):
            digest.update(rel.encode("utf-8"))
            digest.update((root / rel).read_bytes())
        book = load_bound_rule_book(
            rule_version="v1-compiled",
            dataset_files=files,
            dataset_hash=digest.hexdigest(),
            rules_root=root,
        )
        assert isinstance(book, TradingRuleBook)
        assert book.review_status == "COMPILED"
