"""GT-H3B-P1 review-manifest and raw-byte bundle contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest

from ashare_state.spike.evidence_bundle import (
    EvidenceBundleError,
    read_evidence_bundle,
    write_evidence_bundle,
)
from ashare_state.spike.golden_store import GoldenTruthStore

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_GOLDEN = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "golden" / "review.py"


def _load_review_module():
    spec = importlib.util.spec_from_file_location("gt_h3b_review", REVIEW_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sources(tmp_path: Path) -> list[dict[str, str]]:
    first = tmp_path / "rule.pdf"
    second = tmp_path / "applicability.html"
    first.write_bytes(b"%PDF-raw-official-rule")
    second.write_bytes(b"<html>raw-official-applicability</html>")
    return [
        {
            "path": str(first),
            "source_ref": "https://www.sse.com.cn/test/rule.pdf",
            "kind": "EXCHANGE_RULEBOOK",
        },
        {
            "path": str(second),
            "source_ref": "https://star.sse.com.cn/test/applicability.html",
            "kind": "COMPANY_ANNOUNCEMENT",
        },
    ]


def test_bundle_is_deterministic_and_rehashes_raw_members(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    left = tmp_path / "left.zip"
    right = tmp_path / "right.zip"
    write_evidence_bundle(left, sources)
    write_evidence_bundle(right, sources)

    assert left.read_bytes() == right.read_bytes()
    entries = read_evidence_bundle(left, expected_sources=sources)
    assert [entry.source_ref for entry in entries] == [
        "https://www.sse.com.cn/test/rule.pdf",
        "https://star.sse.com.cn/test/applicability.html",
    ]
    assert all(len(entry.sha256) == 64 for entry in entries)


def test_bundle_rejects_non_allowlisted_source(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    invalid = [
        {**sources[0], "source_ref": "https://official.example/rule.pdf"},
        sources[1],
    ]
    with pytest.raises(EvidenceBundleError, match="official allowlist"):
        write_evidence_bundle(tmp_path / "invalid.zip", invalid)


def test_bundle_tamper_and_declaration_drift_fail_closed(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    bundle = tmp_path / "bundle.zip"
    tampered = tmp_path / "tampered.zip"
    write_evidence_bundle(bundle, sources)
    with (
        zipfile.ZipFile(bundle) as source_archive,
        zipfile.ZipFile(tampered, mode="w", compression=zipfile.ZIP_STORED) as target_archive,
    ):
        for info in source_archive.infolist():
            data = source_archive.read(info.filename)
            if info.filename != "manifest.json":
                data += b"tampered"
            target_archive.writestr(info, data)

    with pytest.raises(EvidenceBundleError, match="does not match"):
        read_evidence_bundle(tampered)
    with pytest.raises(EvidenceBundleError, match="source list"):
        read_evidence_bundle(
            bundle,
            expected_sources=[sources[1], sources[0]],
        )


def test_gt_h3b_batch_manifest_rejects_expect_fields_even_when_null(tmp_path: Path) -> None:
    module = _load_review_module()
    manifest = tmp_path / "review.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case": "GT-H3B-CASE",
                    "artifact": "artifact.zip",
                    "kind": "EVIDENCE_BUNDLE",
                    "bundle_sources": [
                        {
                            "source_ref": "https://www.sse.com.cn/test/rule.pdf",
                            "kind": "EXCHANGE_RULEBOOK",
                        },
                        {
                            "source_ref": "https://star.sse.com.cn/test/app.html",
                            "kind": "COMPANY_ANNOUNCEMENT",
                        },
                    ],
                    "expect_fields": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    args = Namespace(
        manifest=manifest,
        case=None,
        artifact=None,
        kind=None,
        expect_fields=None,
        note="",
    )
    with pytest.raises(module.ReviewError, match="must not contain expect_fields"):
        module._load_review_requests(args)


def _make_v4_root(tmp_path: Path) -> Path:
    root = tmp_path / "golden"
    root.mkdir()
    for name in ("golden_cases_v4.jsonl", "truth_manifest_v4.json"):
        shutil.copy2(REPO_GOLDEN / name, root / name)
    (root / "truth_manifest.json").write_bytes(
        (REPO_GOLDEN / "truth_manifest_v4.json").read_bytes()
    )
    return root


def _write_test_source_contract(
    path: Path,
    *,
    dataset: Path,
    truth_version: str,
    case_ids: list[str],
    composite_sources: list[dict[str, str]],
) -> None:
    records: list[dict[str, object]] = [
        {
            "record_type": "contract_header",
            "schema": 1,
            "format": "GT-H3B-CASE-EVIDENCE-CONTRACT/v1",
            "truth_version": truth_version,
            "dataset_file": dataset.name,
            "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "case_count": len(case_ids),
        }
    ]
    for index, case_id in enumerate(case_ids):
        sources = (
            composite_sources
            if index == 0
            else [
                {
                    "source_ref": f"https://www.sse.com.cn/test/{case_id}.html",
                    "kind": "OTHER_OFFICIAL",
                }
            ]
        )
        records.append(
            {
                "record_type": "case",
                "golden_case_id": case_id,
                "sources": sources,
            }
        )
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


@pytest.mark.parametrize("variant", ["exact", "dot", "parent"])
def test_custom_contract_cannot_target_production_root(
    tmp_path: Path, variant: str
) -> None:
    module = _load_review_module()
    if variant == "exact":
        root = REPO_GOLDEN
    elif variant == "dot":
        root = REPO_GOLDEN / "."
    else:
        root = REPO_GOLDEN / ".." / REPO_GOLDEN.name

    args = Namespace(
        contract=tmp_path / "not-read.jsonl",
        root=root,
    )
    with pytest.raises(module.ReviewError, match="production Golden root"):
        module._load_evidence_source_contract(args, Path("unused"), {}, [])


def test_review_seals_a_declared_evidence_bundle(tmp_path: Path) -> None:
    root = _make_v4_root(tmp_path)
    sources = _sources(tmp_path)
    bundle = tmp_path / "composite.zip"
    write_evidence_bundle(bundle, sources)
    ordinary = tmp_path / "ordinary.html"
    ordinary.write_bytes(b"one official raw response body")
    active = json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))
    dataset = root / active["dataset_file"]
    case_ids = [
        json.loads(line)["golden_case_id"]
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contract = tmp_path / "source-contract.jsonl"
    _write_test_source_contract(
        contract,
        dataset=dataset,
        truth_version=active["truth_version"],
        case_ids=case_ids,
        composite_sources=[
            {"source_ref": source["source_ref"], "kind": source["kind"]} for source in sources
        ],
    )
    review_manifest = tmp_path / "gt_h3b_review.json"
    entries: list[dict[str, object]] = []
    for index, case_id in enumerate(case_ids):
        entry: dict[str, object] = {
            "case": case_id,
            "artifact": str(bundle if index == 0 else ordinary),
            "kind": "EVIDENCE_BUNDLE" if index == 0 else "OTHER_OFFICIAL",
        }
        if index == 0:
            entry["bundle_sources"] = [
                {"source_ref": source["source_ref"], "kind": source["kind"]} for source in sources
            ]
        else:
            entry["sources"] = [
                {
                    "source_ref": f"https://www.sse.com.cn/test/{case_id}.html",
                    "kind": "OTHER_OFFICIAL",
                }
            ]
        entries.append(entry)
    review_manifest.write_text(
        json.dumps(entries, ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(REVIEW_SCRIPT),
            "--manifest",
            str(review_manifest),
            "--reviewer",
            "project-owner",
            "--root",
            str(root),
            "--contract",
            str(contract),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    cases, manifest = GoldenTruthStore(root).load()
    assert manifest.review_summary == {"REVIEWED": 125}
    assert cases[0].source_artifact_kind == "EVIDENCE_BUNDLE"
    evidence = root / "evidence" / cases[0].source_artifact_ref
    assert evidence.is_file()
    assert manifest.fully_reviewed


def test_review_pointer_failure_rolls_back_new_outputs(tmp_path: Path, monkeypatch) -> None:
    root = _make_v4_root(tmp_path)
    module = _load_review_module()
    sources = _sources(tmp_path)
    bundle = tmp_path / "composite.zip"
    write_evidence_bundle(bundle, sources)
    ordinary = tmp_path / "ordinary.html"
    ordinary.write_bytes(b"one official raw response body")

    active = json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))
    dataset = root / active["dataset_file"]
    case_ids = [
        json.loads(line)["golden_case_id"]
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contract = tmp_path / "source-contract.jsonl"
    _write_test_source_contract(
        contract,
        dataset=dataset,
        truth_version=active["truth_version"],
        case_ids=case_ids,
        composite_sources=[
            {"source_ref": source["source_ref"], "kind": source["kind"]} for source in sources
        ],
    )
    review_manifest = tmp_path / "gt_h3b_review.json"
    entries: list[dict[str, object]] = []
    for index, case_id in enumerate(case_ids):
        entry: dict[str, object] = {
            "case": case_id,
            "artifact": str(bundle if index == 0 else ordinary),
            "kind": "EVIDENCE_BUNDLE" if index == 0 else "OTHER_OFFICIAL",
        }
        if index == 0:
            entry["bundle_sources"] = [
                {"source_ref": source["source_ref"], "kind": source["kind"]} for source in sources
            ]
        else:
            entry["sources"] = [
                {
                    "source_ref": f"https://www.sse.com.cn/test/{case_id}.html",
                    "kind": "OTHER_OFFICIAL",
                }
            ]
        entries.append(entry)
    review_manifest.write_text(
        json.dumps(entries, ensure_ascii=False),
        encoding="utf-8",
    )

    def fail_pointer(manifest: dict) -> None:
        raise OSError("injected pointer write failure")

    active_before = (root / "truth_manifest.json").read_bytes()
    monkeypatch.setattr(module, "_atomic_active_pointer", fail_pointer)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(REVIEW_SCRIPT),
            "--manifest",
            str(review_manifest),
            "--reviewer",
            "project-owner",
            "--root",
            str(root),
            "--contract",
            str(contract),
        ],
    )

    with pytest.raises(module.ReviewError, match="before ACTIVE pointer commit"):
        module.main()

    assert (root / "truth_manifest.json").read_bytes() == active_before
    assert not (root / "golden_cases_v5.jsonl").exists()
    assert not (root / "truth_manifest_v5.json").exists()
    evidence = root / "evidence"
    if evidence.exists():
        assert not any(path.is_file() for path in evidence.rglob("*"))
