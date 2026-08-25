"""R4-A2.7 P0-03: REQUIRED rule-metadata coherence (audit 20260825 #3
section 4).

manifest source_version / dataset_version are REQUIRED (non-empty) and
compared UNCONDITIONALLY - "only compare when filled" optional semantics
let a manifest with empty fields smuggle a real dataset lineage. Formal
provenance requires the dataset content version AND the source lineage;
bound replay re-verifies source_version / review_status too.
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
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"


def _make_root(tmp_path: Path) -> tuple[Path, dict]:
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


class TestRequiredCoherence:
    def test_source_version_missing_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        del manifest["source_version"]
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="source_version"):
            load_active_rules(root)

    def test_source_version_empty_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["source_version"] = ""
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="source_version"):
            load_active_rules(root)

    def test_dataset_version_missing_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        del manifest["dataset_version"]
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="dataset_version"):
            load_active_rules(root)

    def test_dataset_version_empty_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["dataset_version"] = ""
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="dataset_version"):
            load_active_rules(root)

    def test_source_version_mismatch_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["source_version"] = "DIFFERENT consolidation"
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="source_version"):
            load_active_rules(root)

    def test_dataset_version_mismatch_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        manifest["dataset_version"] = "9999-01-01.0"
        _write(root, manifest)
        with pytest.raises(RuleUnresolvedError, match="dataset_version"):
            load_active_rules(root)

    def test_coherent_root_loads(self, tmp_path: Path):
        root, _manifest = _make_root(tmp_path)
        book, manifest = load_active_rules(root)
        assert book.review_status == "COMPILED"
        assert manifest.source_version


class TestProvenanceRequirements:
    _base = {
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
        "trading_rule_version": "v1-compiled",
        "trading_rule_dataset_files": ["versions/v1-compiled/rules.yaml"],
        "trading_rule_dataset_hash": "b" * 64,
        "trading_rule_review_status": "COMPILED",
    }

    def test_empty_source_version_incomplete(self):
        run = SpikeRun(**self._base, trading_rule_dataset_version="2026-08-24.1")
        assert run.provenance_complete() is False  # source_version missing

    def test_empty_dataset_version_incomplete(self):
        run = SpikeRun(**self._base, trading_rule_source_version="official-src")
        assert run.provenance_complete() is False  # dataset_version missing

    def test_full_binding_complete(self):
        run = SpikeRun(
            **self._base,
            trading_rule_dataset_version="2026-08-24.1",
            trading_rule_source_version="official-src",
        )
        assert run.provenance_complete() is True


class TestBoundIdentityDisagreement:
    def test_bound_source_version_disagreement_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        with pytest.raises(RuleUnresolvedError, match="source_version mismatch"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=manifest["dataset_files"],
                dataset_hash=manifest["dataset_hash"],
                dataset_version=manifest["dataset_version"],
                source_version="NOT-THE-BOUND-SOURCE",
                rules_root=root,
            )

    def test_bound_review_status_disagreement_blocks(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        with pytest.raises(RuleUnresolvedError, match="review_status mismatch"):
            load_bound_rule_book(
                rule_version="v1-compiled",
                dataset_files=manifest["dataset_files"],
                dataset_hash=manifest["dataset_hash"],
                dataset_version=manifest["dataset_version"],
                source_version=manifest["source_version"],
                review_status="REVIEWED",  # the bound files are COMPILED
                rules_root=root,
            )

    def test_bound_full_identity_agreement_loads(self, tmp_path: Path):
        root, manifest = _make_root(tmp_path)
        book = load_bound_rule_book(
            rule_version="v1-compiled",
            dataset_files=manifest["dataset_files"],
            dataset_hash=manifest["dataset_hash"],
            dataset_version=manifest["dataset_version"],
            source_version=manifest["source_version"],
            review_status="COMPILED",
            rules_root=root,
        )
        assert isinstance(book, TradingRuleBook)
