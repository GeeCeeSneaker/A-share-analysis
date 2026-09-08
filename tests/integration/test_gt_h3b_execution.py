"""Offline tests for the GT-H3B controlled execution boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/golden/gt_h3b_execute.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gt_h3b_execute", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        url: str | None = None,
        content_type: str = "application/pdf",
    ):
        self.status = status
        self._body = body
        self._url = url
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url or "https://www.sse.com.cn/example.pdf"

    def read(self, size: int = -1):
        if not self._body:
            return b""
        body, self._body = self._body, b""
        return body


def test_fetch_source_accepts_http_200_pdf_and_hashes_raw_bytes(tmp_path, monkeypatch):
    module = _load_module()
    body = b"%PDF-1.7\nraw official bytes\n"
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda request, timeout: _FakeResponse(body),
    )

    result = module._fetch_source(
        "https://www.sse.com.cn/example.pdf",
        "EXCHANGE_RULEBOOK",
        tmp_path / "sources",
        1,
        5,
    )

    assert result.path.suffix == ".pdf"
    assert result.size == len(body)
    assert result.sha256 == module._sha256(body)
    assert result.path.read_bytes() == body


def test_fetch_source_retries_transient_network_failure(tmp_path, monkeypatch):
    module = _load_module()
    body = b"%PDF-1.7\nretryable raw bytes\n"
    attempts = 0

    def flaky_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise module.URLError("connection reset")
        return _FakeResponse(body)

    monkeypatch.setattr(module, "urlopen", flaky_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    result = module._fetch_source(
        "https://www.sse.com.cn/example.pdf",
        "EXCHANGE_RULEBOOK",
        tmp_path / "sources",
        1,
        5,
    )

    assert attempts == 2
    assert result.path.read_bytes() == body


def test_fetch_source_upgrades_legacy_http_locator_to_https(tmp_path, monkeypatch):
    module = _load_module()
    body = b"<html>official historical source</html>"
    requested_urls = []

    def capture_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return _FakeResponse(
            body,
            url="https://www.sse.com.cn/legacy.shtml",
            content_type="text/html",
        )

    monkeypatch.setattr(module, "urlopen", capture_urlopen)
    result = module._fetch_source(
        "http://www.sse.com.cn/legacy.shtml",
        "SSE_ANNOUNCEMENT",
        tmp_path / "sources",
        1,
        5,
    )

    assert requested_urls == ["https://www.sse.com.cn/legacy.shtml"]
    assert result.source_ref == "http://www.sse.com.cn/legacy.shtml"
    assert result.final_url == "https://www.sse.com.cn/legacy.shtml"
    assert result.path.read_bytes() == body


def test_fetch_source_uses_browser_for_http_403(tmp_path, monkeypatch):
    module = _load_module()
    body = b"<html>browser-resolved official source</html>"
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            module.HTTPError(request.full_url, 403, "forbidden", {}, None)
        ),
    )
    browser_calls = []

    def browser_fetch(source_ref, timeout, *, require_pdf):
        browser_calls.append((source_ref, require_pdf))
        return body, "text/html", source_ref

    monkeypatch.setattr(module, "_fetch_source_with_browser", browser_fetch)
    result = module._fetch_source(
        "https://www.sse.com.cn/blocked.shtml",
        "SSE_ANNOUNCEMENT",
        tmp_path / "sources",
        1,
        5,
    )

    assert browser_calls == [("https://www.sse.com.cn/blocked.shtml", False)]
    assert result.path.read_bytes() == body


def test_fetch_source_rejects_pdf_challenge_body(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda request, timeout: _FakeResponse(b"<html>challenge</html>"),
    )

    with pytest.raises(module.ExecutionError, match="anti-bot"):
        module._fetch_source(
            "https://www.sse.com.cn/example.pdf",
            "EXCHANGE_RULEBOOK",
            tmp_path / "sources",
            1,
            5,
        )


def test_fetch_source_uses_browser_for_pdf_challenge(tmp_path, monkeypatch):
    module = _load_module()
    body = b"%PDF-1.7\nbrowser-resolved raw bytes\n"
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda request, timeout: _FakeResponse(b"<html>challenge</html>"),
    )
    monkeypatch.setattr(
        module,
        "_fetch_pdf_with_browser",
        lambda source_ref, timeout: (body, "application/pdf", source_ref),
    )

    result = module._fetch_source(
        "https://www.sse.com.cn/example.pdf",
        "EXCHANGE_RULEBOOK",
        tmp_path / "sources",
        1,
        5,
    )

    assert result.path.read_bytes() == body
    assert result.content_type == "application/pdf"


def test_fetch_source_rejects_non_official_redirect(tmp_path, monkeypatch):
    module = _load_module()
    body = b"<html>official page</html>"

    monkeypatch.setattr(
        module,
        "urlopen",
        lambda request, timeout: _FakeResponse(
            body,
            url="https://example.invalid/not-official",
        ),
    )

    with pytest.raises(module.ExecutionError, match="allowlist"):
        module._fetch_source(
            "https://www.sse.com.cn/example.shtml",
            "SSE_ANNOUNCEMENT",
            tmp_path / "sources",
            1,
            5,
        )


def test_build_review_manifest_preserves_composite_source_order(tmp_path):
    module = _load_module()
    composite = "GT-LIMIT-ST5-600518-20190603"
    ordinary = "CASE-A"
    rule = module.SourceBinding(
        "https://www.sse.com.cn/rule.pdf",
        "EXCHANGE_RULEBOOK",
        "RULE",
    )
    applicability = module.SourceBinding(
        "https://www.sse.com.cn/app.shtml",
        "SSE_ANNOUNCEMENT",
        "APPLICABILITY",
    )
    ordinary_binding = module.SourceBinding(
        "https://www.sse.com.cn/case.shtml",
        "SSE_ANNOUNCEMENT",
    )
    contract = module.EvidenceSourceContract(
        truth_version="test-v6",
        dataset_file="golden_cases_test.jsonl",
        dataset_sha256="0" * 64,
        case_count=2,
        bindings={
            composite: (rule, applicability),
            ordinary: (ordinary_binding,),
        },
    )
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    rule_path = source_dir / "rule.pdf"
    applicability_path = source_dir / "app.shtml"
    ordinary_path = source_dir / "case.shtml"
    rule_path.write_bytes(b"%PDF-1.7\nrule")
    applicability_path.write_bytes(b"<html>app</html>")
    ordinary_path.write_bytes(b"<html>case</html>")
    sources = {
        rule.pair(): module.RetrievedSource(
            rule.source_ref,
            rule.kind,
            rule_path,
            module._sha256(rule_path.read_bytes()),
            rule_path.stat().st_size,
            "application/pdf",
            rule.source_ref,
        ),
        applicability.pair(): module.RetrievedSource(
            applicability.source_ref,
            applicability.kind,
            applicability_path,
            module._sha256(applicability_path.read_bytes()),
            applicability_path.stat().st_size,
            "text/html",
            applicability.source_ref,
        ),
        ordinary_binding.pair(): module.RetrievedSource(
            ordinary_binding.source_ref,
            ordinary_binding.kind,
            ordinary_path,
            module._sha256(ordinary_path.read_bytes()),
            ordinary_path.stat().st_size,
            "text/html",
            ordinary_binding.source_ref,
        ),
    }

    manifest_path, digest, stats = module._build_review_manifest(
        contract,
        [composite, ordinary],
        sources,
        tmp_path,
    )
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert digest == module._sha256(manifest_path.read_bytes())
    assert stats == {
        "case_count": 2,
        "ordinary_cases": 1,
        "composite_cases": 1,
        "bundle_count": 1,
    }
    assert entries[0]["kind"] == "EVIDENCE_BUNDLE"
    assert [entry["kind"] for entry in entries[0]["bundle_sources"]] == [
        "EXCHANGE_RULEBOOK",
        "SSE_ANNOUNCEMENT",
    ]
    assert "expect_fields" not in entries[0]


def test_append_once_does_not_duplicate_governance_entry(tmp_path):
    module = _load_module()
    path = tmp_path / "DEVLOG.md"
    path.write_text("base\n", encoding="utf-8")
    entry = "## unique marker\n\nrecord"
    module._append_once(path, "## unique marker", entry)
    module._append_once(path, "## unique marker", entry)
    assert path.read_text(encoding="utf-8").count("## unique marker") == 1


def test_existing_seal_uses_strong_reviewed_verifier(monkeypatch, tmp_path):
    module = _load_module()
    receipt = {
        "format": "GT-H3B-CONTROLLED-EXECUTION-RECEIPT/v1",
        "phase_b": {"review_manifest_sha256": "manifest-hash"},
        "phase_c": {
            "reviewer": "project-owner",
            "reviewed_version": "v7-reviewed-20260908",
            "dataset_hash": "dataset-hash",
            "case_count": 125,
            "review_summary": {"REVIEWED": 125},
            "evidence_ref_count": 1,
            "evidence_bytes": 10,
            "gates": {
                "review": [],
                "quantity": [],
                "event_coverage": [],
                "production_formal": [],
            },
        },
        "immutable_v1_v6": {"golden_cases_v1.jsonl": "immutable-hash"},
    }
    active = {"truth_version": "v7-reviewed-20260908", "dataset_hash": "dataset-hash"}
    case_ids = [f"CASE-{index:03d}" for index in range(125)]
    monkeypatch.setattr(module, "_read_json", lambda path: active)
    monkeypatch.setattr(
        module,
        "_load_active_case_documents",
        lambda *args: [{"golden_case_id": case_id} for case_id in case_ids],
    )
    frozen_contract = object()
    captured = {}

    def load_contract(repo_root, case_ids):
        captured["contract"] = (repo_root, case_ids)
        return frozen_contract

    def strong_verifier(
        repo_root,
        contract,
        case_ids,
        immutable_before,
        reviewer,
        manifest_sha256,
    ):
        captured["strong"] = (
            repo_root,
            contract,
            case_ids,
            immutable_before,
            reviewer,
            manifest_sha256,
        )
        return {
            "reviewed_version": "v7-reviewed-20260908",
            "dataset_hash": "dataset-hash",
            "case_count": 125,
            "review_summary": {"REVIEWED": 125},
            "evidence_ref_count": 1,
            "evidence_bytes": 10,
            "gates": {
                "review": [],
                "quantity": [],
                "event_coverage": [],
                "production_formal": [],
            },
        }

    monkeypatch.setattr(module, "_load_frozen_v6_contract", load_contract)
    monkeypatch.setattr(module, "_verify_reviewed_output", strong_verifier)
    module._verify_existing_seal(tmp_path, receipt)

    assert captured["contract"] == (tmp_path, case_ids)
    assert captured["strong"] == (
        tmp_path,
        frozen_contract,
        case_ids,
        receipt["immutable_v1_v6"],
        "project-owner",
        "manifest-hash",
    )


def test_existing_seal_verifies_real_v7_corpus():
    """Exercise the idempotent path against the committed sealed v7 corpus."""
    module = _load_module()
    repo_root = SCRIPT.parents[2]
    receipt_path = repo_root / module.RECEIPT_RELATIVE

    assert receipt_path.is_file()
    receipt = module._read_json(receipt_path)
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["format"] in {
        "GT-H3B-CONTROLLED-EXECUTION-RECEIPT/v1",
        "GT-H3B-CONTROLLED-EXECUTION-RECEIPT/v2",
    }
    assert receipt["phase_c"]["reviewed_version"] == "v7-reviewed-20260908"

    module._verify_existing_seal(repo_root, receipt)
