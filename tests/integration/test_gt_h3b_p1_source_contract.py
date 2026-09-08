"""GT-H3B-P1.1 case-bound official-source contract tests."""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.parse
from argparse import Namespace
from pathlib import Path

import pytest

from ashare_state.spike.evidence_contract import (
    CONTRACT_RELATIVE_PATH,
    KNOWN_COMPOSITE_CASE_ROLES,
    PRODUCTION_CONTRACT_SHA256,
    EvidenceSourceContractError,
    load_evidence_source_contract,
    validate_review_source_bindings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
DATASET = GOLDEN_ROOT / "golden_cases_v6.jsonl"
V6_MANIFEST = GOLDEN_ROOT / "truth_manifest_v6.json"
CONTRACT_PATH = REPO_ROOT / CONTRACT_RELATIVE_PATH
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "golden" / "review.py"

NEW_ST_CASES = {
    "GT-H2-ST-ST_ADD-300495-20210507",
    "GT-H2-ST-ST_ADD-002640-20210507",
    "GT-H2-ST-ST_ADD-600382-20210506",
    "GT-H2-ST-ST_ADD-600291-20210506",
    "GT-H2-ST-ST_ADD-600078-20210506",
    "GT-H2-ST-ST_ADD-600896-20210506",
    "GT-H2-ST-ST_ADD-600615-20210506",
    "GT-H2-ST-ST_ADD-000502-20210506",
    "GT-H2-ST-STAR_ST_ADD-688086-20220506",
    "GT-H2-ST-ST_ADD-603603-20220506",
    "GT-H2-ST-ST_ADD-002313-20220506",
    "GT-H2-ST-ST_ADD-300301-20220506",
    "GT-H2-ST-ST_ADD-002751-20220506",
    "GT-H2-ST-ST_ADD-002316-20220506",
    "GT-H2-ST-ST_ADD-002366-20220506",
}


def _production_contract():
    active = json.loads(V6_MANIFEST.read_text(encoding="utf-8"))
    case_ids = [
        json.loads(line)["golden_case_id"]
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return load_evidence_source_contract(
        CONTRACT_PATH,
        expected_truth_version=active["truth_version"],
        expected_dataset_file=DATASET.name,
        expected_dataset_hash=active["dataset_hash"],
        expected_case_ids=case_ids,
        expected_sha256=PRODUCTION_CONTRACT_SHA256,
    )


def _write_contract(
    path: Path,
    *,
    case_ids: list[str],
    source_map: dict[str, list[dict[str, str]]],
) -> None:
    records: list[dict[str, object]] = [
        {
            "record_type": "contract_header",
            "schema": 1,
            "format": "GT-H3B-CASE-EVIDENCE-CONTRACT/v1",
            "truth_version": "test-v1",
            "dataset_file": "golden_cases_test.jsonl",
            "dataset_sha256": "0" * 64,
            "case_count": len(case_ids),
        }
    ]
    for case_id in case_ids:
        records.append(
            {
                "record_type": "case",
                "golden_case_id": case_id,
                "sources": source_map[case_id],
            }
        )
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _official_source(path: str) -> dict[str, str]:
    return {"source_ref": f"https://www.sse.com.cn/test/{path}", "kind": "OTHER_OFFICIAL"}


def _load_review_module():
    spec = importlib.util.spec_from_file_location("gt_h3b_review_contract", REVIEW_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_v6_contract_has_exact_case_and_source_coverage() -> None:
    contract = _production_contract()
    case_ids = [
        json.loads(line)["golden_case_id"]
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert contract.case_count == 125
    assert list(contract.bindings) == case_ids
    assert set(KNOWN_COMPOSITE_CASE_ROLES) == {
        "GT-LIMIT-ST5-600518-20190603",
        "GT-LIMIT-ST5-600518-20191028",
        "GT-LIMIT-STAR20-688981-20200723",
        "GT-LIMIT-IPO44-601995",
        "GT-LIMIT-IPO44-605499",
    }
    for case_id, roles in KNOWN_COMPOSITE_CASE_ROLES.items():
        bindings = contract.for_case(case_id)
        assert tuple(binding.role for binding in bindings) == roles
        assert len(bindings) == 2
    for case_id in NEW_ST_CASES:
        bindings = contract.for_case(case_id)
        assert len(bindings) == 1
        assert urllib.parse.urlsplit(bindings[0].source_ref).hostname == "static.cninfo.com.cn"
        assert bindings[0].kind == "COMPANY_ANNOUNCEMENT"


def test_arbitrary_http_host_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "contract.jsonl"
    _write_contract(
        path,
        case_ids=["CASE-A"],
        source_map={
            "CASE-A": [{"source_ref": "https://official.example/a.pdf", "kind": "OTHER_OFFICIAL"}]
        },
    )
    with pytest.raises(EvidenceSourceContractError, match="official allowlist"):
        load_evidence_source_contract(
            path,
            expected_truth_version="test-v1",
            expected_dataset_file="golden_cases_test.jsonl",
            expected_dataset_hash="0" * 64,
            expected_case_ids=["CASE-A"],
            enforce_known_composites=False,
        )


@pytest.mark.parametrize(
    ("case_ids", "records", "match"),
    [
        (["CASE-A", "CASE-B"], ["CASE-A"], "exactly one record"),
        (["CASE-A", "CASE-B"], ["CASE-A", "CASE-A"], "does not match ACTIVE"),
        (["CASE-A", "CASE-B"], ["CASE-X", "CASE-B"], "does not match ACTIVE"),
    ],
)
def test_contract_case_coverage_is_exact(
    tmp_path: Path,
    case_ids: list[str],
    records: list[str],
    match: str,
) -> None:
    path = tmp_path / "contract.jsonl"
    source_map = {case_id: [_official_source(f"{case_id}.html")] for case_id in set(records)}
    path.write_text(
        json.dumps(
            {
                "record_type": "contract_header",
                "schema": 1,
                "format": "GT-H3B-CASE-EVIDENCE-CONTRACT/v1",
                "truth_version": "test-v1",
                "dataset_file": "golden_cases_test.jsonl",
                "dataset_sha256": "0" * 64,
                "case_count": len(case_ids),
            }
        )
        + "\n"
        + "".join(
            json.dumps(
                {
                    "record_type": "case",
                    "golden_case_id": case_id,
                    "sources": source_map[case_id],
                }
            )
            + "\n"
            for case_id in records
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceSourceContractError, match=match):
        load_evidence_source_contract(
            path,
            expected_truth_version="test-v1",
            expected_dataset_file="golden_cases_test.jsonl",
            expected_dataset_hash="0" * 64,
            expected_case_ids=case_ids,
            enforce_known_composites=False,
        )


def test_case_a_source_cannot_be_reused_for_case_b(tmp_path: Path) -> None:
    path = tmp_path / "contract.jsonl"
    source_map = {
        "CASE-A": [_official_source("case-a.html")],
        "CASE-B": [_official_source("case-b.html")],
    }
    _write_contract(path, case_ids=["CASE-A", "CASE-B"], source_map=source_map)
    contract = load_evidence_source_contract(
        path,
        expected_truth_version="test-v1",
        expected_dataset_file="golden_cases_test.jsonl",
        expected_dataset_hash="0" * 64,
        expected_case_ids=["CASE-A", "CASE-B"],
        enforce_known_composites=False,
    )
    with pytest.raises(EvidenceSourceContractError, match="does not match"):
        validate_review_source_bindings(
            contract,
            [
                {
                    "case": "CASE-B",
                    "kind": "OTHER_OFFICIAL",
                    "sources": source_map["CASE-A"],
                }
            ],
        )


def test_ordinary_review_entry_requires_sources(tmp_path: Path) -> None:
    module = _load_review_module()
    manifest = tmp_path / "ordinary-review-manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "case": "CASE-A",
                    "artifact": "artifact.html",
                    "kind": "OTHER_OFFICIAL",
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
        source_ref=None,
        source_kind=None,
    )
    with pytest.raises(module.ReviewError, match="sources requires"):
        module._load_review_requests(args)


@pytest.mark.parametrize("mutation", ["missing", "swapped", "extra"])
def test_composite_source_binding_is_exact(mutation: str) -> None:
    contract = _production_contract()
    case_id = "GT-LIMIT-ST5-600518-20190603"
    expected = [
        {"source_ref": binding.source_ref, "kind": binding.kind}
        for binding in contract.for_case(case_id)
    ]
    if mutation == "missing":
        declared = expected[:1]
    elif mutation == "swapped":
        declared = list(reversed(expected))
    else:
        declared = expected + [_official_source("extra.html")]
    with pytest.raises(EvidenceSourceContractError, match="does not match"):
        validate_review_source_bindings(
            contract,
            [{"case": case_id, "kind": "EVIDENCE_BUNDLE", "bundle_sources": declared}],
        )
