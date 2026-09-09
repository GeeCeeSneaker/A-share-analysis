"""Tests for the per-rule trading-rule evidence contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ashare_state.spike.rule_evidence import (
    RULE_EVIDENCE_BUNDLE_HASH,
    RULE_EVIDENCE_BUNDLE_REF,
    RULE_EVIDENCE_BUNDLE_SCHEMA,
    prepare_rule_evidence_bundle,
    validate_rule_evidence_bundle,
)
from ashare_state.spike.trading_rule import TradingRuleBook, trading_rule_review_gate

RULES_FILE = Path("configs/trading_rules/versions/v20260824-compiled/rules.yaml")


def _rule_ids() -> tuple[str, ...]:
    document = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return tuple(str(entry["rule_id"]) for entry in document["rules"])


def _input_manifest(tmp_path: Path, *, url: str = "https://www.sse.com.cn/rules") -> Path:
    artifact = tmp_path / "source.html"
    artifact.write_bytes(b"official fixture bytes")
    document = {
        "schema_version": RULE_EVIDENCE_BUNDLE_SCHEMA,
        "dataset_version": "2026-08-24.1",
        "entries": [
            {
                "rule_id": rule_id,
                "sources": [
                    {
                        "artifact_kind": "EXCHANGE_RULEBOOK",
                        "artifact_path": artifact.name,
                        "role": "RULE",
                        "source_url": url,
                    }
                ],
            }
            for rule_id in _rule_ids()
        ],
    }
    manifest = tmp_path / "bundle-input.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return manifest


def _publish_bundle(tmp_path: Path, manifest_path: Path) -> tuple[Path, str, str]:
    prepared = prepare_rule_evidence_bundle(
        manifest_path,
        expected_rule_ids=_rule_ids(),
        expected_dataset_version="2026-08-24.1",
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for raw in prepared.raw_artifacts:
        (evidence / raw.artifact_ref).parent.mkdir(parents=True, exist_ok=True)
        (evidence / raw.artifact_ref).write_bytes(raw.content)
    bundle_hash = hashlib.sha256(prepared.content).hexdigest()
    bundle_ref = f"sha256/{bundle_hash}"
    (evidence / bundle_ref).parent.mkdir(parents=True, exist_ok=True)
    (evidence / bundle_ref).write_bytes(prepared.content)
    return evidence, bundle_ref, bundle_hash


def test_prepare_and_validate_bundle_is_deterministic(tmp_path: Path):
    manifest = _input_manifest(tmp_path)
    prepared = prepare_rule_evidence_bundle(
        manifest,
        expected_rule_ids=_rule_ids(),
        expected_dataset_version="2026-08-24.1",
    )
    evidence, bundle_ref, bundle_hash = _publish_bundle(tmp_path, manifest)
    assert prepared.content == (evidence / bundle_ref).read_bytes()
    assert (
        validate_rule_evidence_bundle(
            bundle_ref=bundle_ref,
            bundle_hash=bundle_hash,
            expected_rule_ids=_rule_ids(),
            expected_dataset_version="2026-08-24.1",
            rules_root=tmp_path,
        )
        == []
    )


def test_input_manifest_rejects_non_official_source(tmp_path: Path):
    manifest = _input_manifest(tmp_path, url="https://example.com/not-official")
    try:
        prepare_rule_evidence_bundle(
            manifest,
            expected_rule_ids=_rule_ids(),
            expected_dataset_version="2026-08-24.1",
        )
    except ValueError as exc:
        assert "allowed first-party host" in str(exc)
    else:
        raise AssertionError("non-official source host was accepted")


def test_input_manifest_rejects_wrong_role(tmp_path: Path):
    manifest = _input_manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"][0]["sources"][0]["role"] = "NOT_A_ROLE"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    try:
        prepare_rule_evidence_bundle(
            manifest,
            expected_rule_ids=_rule_ids(),
            expected_dataset_version="2026-08-24.1",
        )
    except ValueError as exc:
        assert "role 'NOT_A_ROLE'" in str(exc)
    else:
        raise AssertionError("invalid source role was accepted")


def test_bundle_validation_rejects_missing_and_extra_rule_ids(tmp_path: Path):
    manifest = _input_manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["entries"] = document["entries"][:-1]
    document["entries"].append(
        {"rule_id": "NOT_A_RULE", "sources": document["entries"][0]["sources"]}
    )
    manifest.write_text(json.dumps(document), encoding="utf-8")
    try:
        prepare_rule_evidence_bundle(
            manifest,
            expected_rule_ids=_rule_ids(),
            expected_dataset_version="2026-08-24.1",
        )
    except ValueError as exc:
        assert "missing rule_id entries" in str(exc)
        assert "extra rule_id entries" in str(exc)
    else:
        raise AssertionError("incomplete rule-id set was accepted")


def test_bundle_validation_rechecks_raw_hash_and_size(tmp_path: Path):
    manifest = _input_manifest(tmp_path)
    evidence, bundle_ref, bundle_hash = _publish_bundle(tmp_path, manifest)
    bundle = json.loads((evidence / bundle_ref).read_text(encoding="utf-8"))
    first_source = bundle["entries"][0]["sources"][0]
    (evidence / first_source["artifact_ref"]).write_bytes(b"tampered")
    problems = validate_rule_evidence_bundle(
        bundle_ref=bundle_ref,
        bundle_hash=bundle_hash,
        expected_rule_ids=_rule_ids(),
        expected_dataset_version="2026-08-24.1",
        rules_root=tmp_path,
    )
    assert any("sha256 mismatch" in problem for problem in problems)


def test_bundle_validation_rejects_wrong_declared_raw_hash(tmp_path: Path):
    manifest = _input_manifest(tmp_path)
    evidence, bundle_ref, _bundle_hash = _publish_bundle(tmp_path, manifest)
    bundle = json.loads((evidence / bundle_ref).read_text(encoding="utf-8"))
    bundle["entries"][0]["sources"][0]["sha256"] = "0" * 64
    bundle_content = (
        json.dumps(bundle, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    new_hash = hashlib.sha256(bundle_content).hexdigest()
    new_ref = f"sha256/{new_hash}"
    (evidence / new_ref).parent.mkdir(parents=True, exist_ok=True)
    (evidence / new_ref).write_bytes(bundle_content)
    problems = validate_rule_evidence_bundle(
        bundle_ref=new_ref,
        bundle_hash=new_hash,
        expected_rule_ids=_rule_ids(),
        expected_dataset_version="2026-08-24.1",
        rules_root=tmp_path,
    )
    assert any("sha256 mismatch" in problem for problem in problems)


def test_production_gate_requires_bundle_for_reviewed_dataset(tmp_path: Path):
    document = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    document["review_status"] = "REVIEWED"
    source = tmp_path / "source.txt"
    source.write_text("official fixture", encoding="utf-8")
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    document.update(
        {
            "reviewed_by": "fixture-reviewer",
            "reviewed_at": "2026-09-09T00:00:00+00:00",
            "source_artifact_ref": f"sha256/{source_hash}",
            "source_artifact_hash": source_hash,
            "source_artifact_kind": "OTHER_OFFICIAL",
            "source_retrieved_at": "2026-09-09T00:00:00+00:00",
        }
    )
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(yaml.safe_dump(document), encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / f"sha256/{source_hash}").parent.mkdir(parents=True)
    (evidence / f"sha256/{source_hash}").write_bytes(source_bytes)
    book = TradingRuleBook.load(rules_file)
    problems = trading_rule_review_gate(
        book,
        rules_root=tmp_path,
        require_evidence_bundle=True,
    )
    assert any("per-rule evidence bundle provenance" in problem for problem in problems)


def test_bundle_provenance_keys_are_named_constants():
    assert RULE_EVIDENCE_BUNDLE_REF == "rule_evidence_bundle_ref"
    assert RULE_EVIDENCE_BUNDLE_HASH == "rule_evidence_bundle_hash"
