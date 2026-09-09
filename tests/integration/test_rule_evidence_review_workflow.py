"""End-to-end tests for the RULE_EVIDENCE_BUNDLE review path."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from ashare_state.spike.rule_evidence import (
    RULE_EVIDENCE_BUNDLE_HASH,
    RULE_EVIDENCE_BUNDLE_REF,
    RULE_EVIDENCE_BUNDLE_SCHEMA,
)
from ashare_state.spike.trading_rule import load_active_rules, trading_rule_review_gate

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_RULES = (
    REPO_ROOT / "configs" / "trading_rules" / "versions" / "v20260824-compiled" / "rules.yaml"
)


def _rules_root(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "rules"
    version_dir = root / "versions" / "v1-compiled"
    version_dir.mkdir(parents=True)
    shutil.copy(SOURCE_RULES, version_dir / "rules.yaml")
    document = yaml.safe_load((version_dir / "rules.yaml").read_text(encoding="utf-8"))
    for rule in document["rules"]:
        rule["source_ref"] = "synthetic H1 source: https://www.sse.com.cn/rules"
    (version_dir / "rules.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    rel = "versions/v1-compiled/rules.yaml"
    digest = hashlib.sha256(rel.encode("utf-8") + (root / rel).read_bytes()).hexdigest()
    manifest = {
        "rule_version": "v1-compiled",
        "review_status": "COMPILED",
        "dataset_files": [rel],
        "dataset_hash": digest,
        "source_version": str(document["source_version"]),
        "dataset_version": str(document["version"]),
        "review_provenance": {"source_retrieved_at": str(document["source_retrieved_at"])},
    }
    (root / "rule_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return root, document


def test_bundle_review_stages_all_sources_and_binds_manifest(tmp_path: Path):
    root, document = _rules_root(tmp_path)
    artifact = tmp_path / "source.html"
    artifact.write_bytes(b"official source fixture")
    bundle_input = tmp_path / "bundle-input.json"
    bundle_input.write_text(
        json.dumps(
            {
                "schema_version": RULE_EVIDENCE_BUNDLE_SCHEMA,
                "dataset_version": str(document["version"]),
                "entries": [
                    {
                        "rule_id": rule["rule_id"],
                        "sources": [
                            {
                                "artifact_kind": "EXCHANGE_RULEBOOK",
                                "artifact_path": artifact.name,
                                "role": "RULE",
                                "source_url": "https://www.sse.com.cn/rules",
                            }
                        ],
                    }
                    for rule in document["rules"]
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "rules" / "review.py"),
            "--rules",
            str(root / "versions" / "v1-compiled" / "rules.yaml"),
            "--evidence-bundle",
            str(bundle_input),
            "--reviewer",
            "fixture-reviewer",
            "--version",
            "v1-bundle-reviewed",
            "--rules-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
    )
    assert result.returncode == 0, result.stderr
    book, manifest = load_active_rules(root)
    assert manifest.rule_version == "v1-bundle-reviewed"
    assert manifest.evidence_contract == RULE_EVIDENCE_BUNDLE_SCHEMA
    assert book.evidence_contract == RULE_EVIDENCE_BUNDLE_SCHEMA
    assert (
        trading_rule_review_gate(
            book,
            rules_root=root,
            require_evidence_bundle=True,
        )
        == []
    )
    bundle_ref = book.review_provenance[RULE_EVIDENCE_BUNDLE_REF]
    bundle_hash = book.review_provenance[RULE_EVIDENCE_BUNDLE_HASH]
    assert (root / "evidence" / bundle_ref).is_file()
    assert len(bundle_hash) == 64
    bundle = json.loads((root / "evidence" / bundle_ref).read_text(encoding="utf-8"))
    raw_ref = bundle["entries"][0]["sources"][0]["artifact_ref"]
    assert (root / "evidence" / raw_ref).read_bytes() == artifact.read_bytes()
    compiled = yaml.safe_load(
        (root / "versions" / "v1-compiled" / "rules.yaml").read_text(encoding="utf-8")
    )
    assert compiled["review_status"] == "COMPILED"
