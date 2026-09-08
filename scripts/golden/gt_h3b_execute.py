"""Run the authorized GT-H3B promotion, evidence materialization, and seal.

This is an explicit, network-using orchestration layer around the already
reviewed candidate.py and review.py workflows. It never receives provider
credentials, never changes Golden truth, and stops before seal on any source,
contract, or publication mismatch.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.evidence_bundle import (  # noqa: E402
    EvidenceBundleError,
    read_evidence_bundle,
    write_evidence_bundle,
)
from ashare_state.spike.evidence_contract import (  # noqa: E402
    CONTRACT_RELATIVE_PATH,
    KNOWN_COMPOSITE_CASE_ROLES,
    OFFICIAL_SOURCE_HOSTS,
    PRODUCTION_CONTRACT_SHA256,
    EvidenceSourceContract,
    SourceBinding,
    load_evidence_source_contract,
    validate_official_source_ref,
)
from ashare_state.spike.golden_store import (  # noqa: E402
    GoldenTruthError,
    GoldenTruthStore,
    review_readiness_gate,
)

GOLDEN_RELATIVE = Path("data/golden/provider/amazingdata")
REMEDIATION_RELATIVE = Path("docs/golden/gt_h3/remediation")
RECEIPT_RELATIVE = Path("docs/golden/gt_h3/gt_h3b/GT_H3B_EXECUTION_RECEIPT.json")
V5_VERSION = "v5-candidate-20260907"
V6_VERSION = "v6-candidate-20260908"
V6_DATASET_HASH = "0b3952f9f82ee4f6a55a7f060c47af3cc781b0054ed1f83b5868246c0642a343"
MAX_SOURCE_BYTES = 50 * 1024 * 1024
# v1 is a legacy dataset snapshot; its versioned manifest starts at v2.
IMMUTABLE_VERSION_FILES = tuple(
    [f"golden_cases_v{number}.jsonl" for number in range(1, 7)]
    + [f"truth_manifest_v{number}.json" for number in range(2, 7)]
)


class ExecutionError(RuntimeError):
    """A controlled GT-H3B execution precondition or verification failure."""


@dataclass(frozen=True)
class RetrievedSource:
    source_ref: str
    kind: str
    path: Path
    sha256: str
    size: int
    content_type: str
    final_url: str


Fetcher = Callable[[str, str, Path, int, float], RetrievedSource]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path_hash(path: Path) -> str:
    return _sha256(path.read_bytes())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExecutionError(f"JSON file {path} must contain an object")
    return value


def _active_summary(active: dict) -> dict:
    return {
        "truth_version": active.get("truth_version"),
        "dataset_file": active.get("dataset_file"),
        "dataset_hash": active.get("dataset_hash"),
        "case_count": active.get("case_count"),
        "review_summary": active.get("review_summary"),
    }


def _run_checked(command: list[str], *, cwd: Path, label: str) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        output = "\n".join((completed.stdout + "\n" + completed.stderr).splitlines()[-40:]).strip()
        raise ExecutionError(f"{label} failed with exit code {completed.returncode}:\n{output}")
    return completed.stdout


def _snapshot_immutable(repo_root: Path) -> dict[str, str]:
    golden = repo_root / GOLDEN_RELATIVE
    snapshot: dict[str, str] = {}
    for name in IMMUTABLE_VERSION_FILES:
        path = golden / name
        if not path.is_file():
            raise ExecutionError(f"required immutable version file is missing: {path}")
        snapshot[name] = _path_hash(path)
    return snapshot


def _assert_immutable(repo_root: Path, expected: dict[str, str]) -> None:
    actual = _snapshot_immutable(repo_root)
    if actual != expected:
        changed = sorted(
            name for name in set(actual) | set(expected) if actual.get(name) != expected.get(name)
        )
        raise ExecutionError(
            "v1-v6 versioned Golden files changed during execution: " + ", ".join(changed)
        )


def _load_active_case_documents(repo_root: Path, active: dict) -> list[dict]:
    dataset_path = repo_root / GOLDEN_RELATIVE / str(active.get("dataset_file", ""))
    if not dataset_path.is_file():
        raise ExecutionError(f"ACTIVE dataset is missing: {dataset_path}")
    try:
        documents = [
            json.loads(line)
            for line in dataset_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"cannot parse ACTIVE dataset {dataset_path}: {exc}") from exc
    if not all(isinstance(document, dict) for document in documents):
        raise ExecutionError("ACTIVE dataset contains a non-object JSONL row")
    return documents


def _load_v6_contract(
    repo_root: Path,
    active: dict,
    documents: list[dict],
) -> EvidenceSourceContract:
    contract_path = repo_root / CONTRACT_RELATIVE_PATH
    try:
        return load_evidence_source_contract(
            contract_path,
            expected_truth_version=str(active["truth_version"]),
            expected_dataset_file=str(active["dataset_file"]),
            expected_dataset_hash=str(active["dataset_hash"]),
            expected_case_ids=[str(document["golden_case_id"]) for document in documents],
            expected_sha256=PRODUCTION_CONTRACT_SHA256,
            enforce_known_composites=True,
        )
    except (OSError, UnicodeDecodeError, ValueError, KeyError) as exc:
        raise ExecutionError(f"frozen evidence-source contract rejected: {exc}") from exc


def _run_promotion(repo_root: Path) -> tuple[dict, str]:
    golden = repo_root / GOLDEN_RELATIVE
    active = _read_json(golden / "truth_manifest.json")
    if active.get("truth_version") not in {V5_VERSION, V6_VERSION}:
        truth_version = repr(active.get("truth_version"))
        raise ExecutionError("Phase A requires ACTIVE v5 or v6; found " + truth_version)
    command = [
        sys.executable,
        str(repo_root / "scripts/golden/candidate.py"),
        "promote-existing",
        "--truth-version",
        V6_VERSION,
        "--transition-audit",
        str(repo_root / REMEDIATION_RELATIVE / "GT_H3R2_ST_TRANSITION_AUDIT.jsonl"),
        "--carry-forward",
        str(repo_root / REMEDIATION_RELATIVE / "v5_to_v6_human_review_carry_forward.jsonl"),
        "--plan",
        str(repo_root / REMEDIATION_RELATIVE / "v5_to_v6_rebuild_plan.json"),
    ]
    output = _run_checked(command, cwd=repo_root, label="GT-H3B Phase A promotion")
    promoted = _read_json(golden / "truth_manifest.json")
    if promoted.get("truth_version") != V6_VERSION:
        raise ExecutionError("Phase A completed without ACTIVE v6")
    if promoted.get("dataset_hash") != V6_DATASET_HASH:
        raise ExecutionError("Phase A ACTIVE v6 dataset hash is not the frozen hash")
    if promoted.get("review_summary") != {"COMPILED": 125}:
        raise ExecutionError("Phase A must leave v6 at COMPILED 125/125")
    return promoted, output


def _read_bounded(response: object) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(1024 * 1024)  # type: ignore[attr-defined]
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_SOURCE_BYTES:
            raise ExecutionError(
                f"official source exceeded the {MAX_SOURCE_BYTES} byte safety limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_pdf_with_browser(
    source_ref: str,
    timeout: float,
) -> tuple[bytes, str, str]:
    """Resolve a JavaScript anti-bot challenge through a browser network response."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ExecutionError("browser fallback unavailable for PDF anti-bot challenge") from exc

    responses: list[object] = []
    downloads: list[object] = []
    observed: list[str] = []
    with sync_playwright() as playwright:
        headless = not bool(os.environ.get("DISPLAY"))
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                accept_downloads=True,
                user_agent="A-share-analysis-GT-H3B-materializer/1.0",
            )
            try:
                page = context.new_page()

                def record_response(response: object) -> None:
                    status = getattr(response, "status", None)
                    response_url = str(getattr(response, "url", ""))
                    response_parts = urlsplit(response_url)
                    headers = getattr(response, "headers", {})
                    raw_content_type = str(headers.get("content-type", ""))
                    content_type = raw_content_type.split(";", 1)[0].strip().lower()
                    observed.append(
                        f"{status}:{(response_parts.hostname or '').lower()}:"
                        f"{response_parts.path}:{content_type}"
                    )
                    responses.append(response)

                def record_download(download: object) -> None:
                    downloads.append(download)

                page.on("response", record_response)
                page.on("download", record_download)
                cdp_session = context.new_cdp_session(page)
                cdp_session.send("Network.enable")
                cdp_session.send(
                    "Fetch.enable",
                    {
                        "patterns": [
                            {
                                "urlPattern": f"*{Path(urlsplit(source_ref).path).name}*",
                                "requestStage": "Response",
                            }
                        ]
                    },
                )
                cdp_responses: dict[str, tuple[str, dict]] = {}
                finished_request_ids: list[str] = []
                fetch_bodies: list[tuple[bytes, str, str]] = []
                fetch_errors: list[ExecutionError] = []

                def record_cdp_response(event: dict) -> None:
                    response = event.get("response", {})
                    request_id = str(event.get("requestId", ""))
                    if request_id and response.get("status") == 200:
                        cdp_responses[request_id] = (
                            str(response.get("url", "")),
                            response.get("headers") or {},
                        )

                def record_cdp_finished(event: dict) -> None:
                    request_id = str(event.get("requestId", ""))
                    if request_id in cdp_responses:
                        finished_request_ids.append(request_id)

                def record_fetch_paused(event: dict) -> None:
                    request_id = str(event.get("requestId", ""))
                    request = event.get("request") or {}
                    response_url = str(request.get("url", ""))
                    response_parts = urlsplit(response_url)
                    response_headers = {
                        str(header.get("name", "")).lower(): str(header.get("value", ""))
                        for header in event.get("responseHeaders") or []
                        if isinstance(header, dict)
                    }
                    content_type = response_headers.get("content-type", "")
                    content_type = content_type.split(";", 1)[0].strip().lower()
                    if (
                        event.get("responseStatusCode") == 200
                        and response_parts.scheme.lower() == "https"
                        and (response_parts.hostname or "").lower() in OFFICIAL_SOURCE_HOSTS
                        and content_type == "application/pdf"
                    ):
                        with suppress(PlaywrightError, binascii.Error, UnicodeError, ValueError):
                            body_result = cdp_session.send(
                                "Fetch.getResponseBody",
                                {"requestId": request_id},
                            )
                            encoded_body = body_result.get("body")
                            if isinstance(encoded_body, str):
                                body = (
                                    base64.b64decode(encoded_body)
                                    if body_result.get("base64Encoded")
                                    else encoded_body.encode("utf-8")
                                )
                                if len(body) > MAX_SOURCE_BYTES:
                                    fetch_errors.append(
                                        ExecutionError(
                                            f"CDP Fetch PDF response exceeded {MAX_SOURCE_BYTES} bytes"
                                        )
                                    )
                                elif body.startswith(b"%PDF-"):
                                    fetch_bodies.append(
                                        (body, content_type, response_url)
                                    )
                    try:
                        cdp_session.send(
                            "Fetch.continueResponse",
                            {"requestId": request_id},
                        )
                    except PlaywrightError:
                        with suppress(PlaywrightError):
                            cdp_session.send(
                                "Fetch.continueRequest",
                                {"requestId": request_id},
                            )

                cdp_session.on("Network.responseReceived", record_cdp_response)
                cdp_session.on("Network.loadingFinished", record_cdp_finished)
                cdp_session.on("Fetch.requestPaused", record_fetch_paused)
                # PDF downloads can abort page.goto; inspect captured responses below.
                with suppress(PlaywrightError, PlaywrightTimeoutError):
                    page.goto(
                        source_ref,
                        wait_until="commit",
                        timeout=max(1000, int(timeout * 1000)),
                    )
                page.wait_for_timeout(min(10000, max(2000, int(timeout * 1000))))
                if fetch_errors:
                    raise fetch_errors[0]
                for body, content_type, response_url in reversed(fetch_bodies):
                    return body, content_type, response_url
                for request_id in reversed(finished_request_ids):
                    response_info = cdp_responses.get(request_id)
                    if response_info is None:
                        continue
                    response_url, headers = response_info
                    final = urlsplit(response_url)
                    if (
                        final.scheme.lower() != "https"
                        or (final.hostname or "").lower() not in OFFICIAL_SOURCE_HOSTS
                    ):
                        continue
                    try:
                        body_result = cdp_session.send(
                            "Network.getResponseBody",
                            {"requestId": request_id},
                        )
                    except PlaywrightError:
                        continue
                    encoded_body = body_result.get("body")
                    if not isinstance(encoded_body, str):
                        continue
                    try:
                        body = (
                            base64.b64decode(encoded_body)
                            if body_result.get("base64Encoded")
                            else encoded_body.encode("utf-8")
                        )
                    except (ValueError, UnicodeError):
                        continue
                    if len(body) > MAX_SOURCE_BYTES:
                        raise ExecutionError(
                            f"CDP PDF response exceeded the {MAX_SOURCE_BYTES} "
                            "byte safety limit"
                        )
                    if body.startswith(b"%PDF-"):
                        raw_content_type = str(headers.get("content-type", ""))
                        content_type = raw_content_type.split(";", 1)[0].strip().lower()
                        return body, content_type or "application/pdf", response_url
                successful_response_paths = {
                    (urlsplit(str(getattr(response, "url", ""))).hostname or "").lower()
                    + urlsplit(str(getattr(response, "url", ""))).path
                    for response in responses
                    if getattr(response, "status", None) == 200
                }
                for download in reversed(downloads):
                    download_url = str(getattr(download, "url", ""))
                    download_parts = urlsplit(download_url)
                    download_key = (download_parts.hostname or "").lower() + download_parts.path
                    if (
                        download_parts.scheme.lower() != "https"
                        or download_parts.hostname is None
                        or download_parts.hostname.lower() not in OFFICIAL_SOURCE_HOSTS
                        or download_key not in successful_response_paths
                    ):
                        continue
                    try:
                        download_path = download.path()
                        if download_path is None:
                            continue
                        download_file = Path(download_path)
                        if download_file.stat().st_size > MAX_SOURCE_BYTES:
                            raise ExecutionError(
                                f"browser PDF download exceeded the {MAX_SOURCE_BYTES} "
                                "byte safety limit"
                            )
                        body = download_file.read_bytes()
                    except PlaywrightError:
                        continue
                    except OSError as exc:
                        raise ExecutionError(
                            f"browser PDF download could not be read: {exc}"
                        ) from exc
                    if body.startswith(b"%PDF-"):
                        return body, "application/pdf", download_url
                for response in reversed(responses):
                    if getattr(response, "status", None) != 200:
                        continue
                    response_url = str(getattr(response, "url", ""))
                    final = urlsplit(response_url)
                    if (
                        final.scheme.lower() != "https"
                        or (final.hostname or "").lower() not in OFFICIAL_SOURCE_HOSTS
                    ):
                        continue
                    headers = getattr(response, "headers", {})
                    content_length = headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > MAX_SOURCE_BYTES:
                                raise ExecutionError(
                                    f"browser PDF response exceeded the {MAX_SOURCE_BYTES} "
                                    "byte safety limit"
                                )
                        except ValueError:
                            pass
                    try:
                        body = response.body()
                    except PlaywrightError:
                        continue
                    if len(body) > MAX_SOURCE_BYTES:
                        raise ExecutionError(
                            f"browser PDF response exceeded the {MAX_SOURCE_BYTES} "
                            "byte safety limit"
                        )
                    if body.startswith(b"%PDF-"):
                        raw_content_type = str(headers.get("content-type", ""))
                        content_type = raw_content_type.split(";", 1)[0].strip().lower()
                        return body, content_type or "application/pdf", response_url
            finally:
                context.close()
        finally:
            browser.close()
    summary = ", ".join(observed[-12:]) or "none"
    raise ExecutionError(
        f"browser fallback did not obtain an HTTP 200 PDF response for {source_ref}; "
        f"observed {len(observed)} responses and {len(downloads)} downloads: {summary}"
    )


def _fetch_source(
    source_ref: str,
    kind: str,
    source_dir: Path,
    ordinal: int,
    timeout: float,
) -> RetrievedSource:
    try:
        validate_official_source_ref(source_ref)
        parsed = urlsplit(source_ref)
    except ValueError as exc:
        raise ExecutionError(f"invalid official source {source_ref!r}: {exc}") from exc
    if parsed.scheme.lower() != "https":
        raise ExecutionError(f"official source must use HTTPS: {source_ref}")
    request = Request(
        source_ref,
        headers={
            "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.1",
            "User-Agent": "A-share-analysis-GT-H3B-materializer/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            if status != 200:
                raise ExecutionError(
                    f"official source {source_ref} returned HTTP {status}, not 200"
                )
            final_url = str(response.geturl())
            final = urlsplit(final_url)
            final_host = (final.hostname or "").lower()
            if final.scheme.lower() != "https" or final_host not in OFFICIAL_SOURCE_HOSTS:
                raise ExecutionError(
                    f"official source {source_ref} redirected outside the official HTTPS "
                    f"allowlist: {final_url}"
                )
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            data = _read_bounded(response)
    except HTTPError as exc:
        raise ExecutionError(f"official source {source_ref} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ExecutionError(f"official source {source_ref} could not be retrieved: {exc}") from exc

    is_pdf_url = parsed.path.lower().endswith(".pdf")
    if is_pdf_url and (not data or not data.startswith(b"%PDF-")):
        try:
            data, content_type, final_url = _fetch_pdf_with_browser(source_ref, timeout)
        except ExecutionError as exc:
            raise ExecutionError(
                f"official PDF source {source_ref} did not return a PDF body; "
                f"browser fallback failed: {exc}"
            ) from exc
    if not data:
        raise ExecutionError(f"official source {source_ref} returned an empty body")
    is_pdf = data.startswith(b"%PDF-") or content_type == "application/pdf"
    suffix = ".pdf" if is_pdf else ".html"
    output = source_dir / f"source-{ordinal:04d}{suffix}"
    temporary = source_dir / f".source-{ordinal:04d}.tmp"
    source_dir.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(data)
    temporary.replace(output)
    return RetrievedSource(
        source_ref=source_ref,
        kind=kind,
        path=output,
        sha256=_sha256(data),
        size=len(data),
        content_type=content_type,
        final_url=final_url,
    )


def _download_sources(
    contract: EvidenceSourceContract,
    case_ids: list[str],
    work_dir: Path,
    timeout: float,
    fetcher: Fetcher = _fetch_source,
) -> dict[tuple[str, str], RetrievedSource]:
    cache: dict[tuple[str, str], RetrievedSource] = {}
    source_dir = work_dir / "sources"
    ordinal = 0
    for case_id in case_ids:
        for binding in contract.for_case(case_id):
            key = binding.pair()
            if key in cache:
                continue
            ordinal += 1
            cache[key] = fetcher(
                binding.source_ref,
                binding.kind,
                source_dir,
                ordinal,
                timeout,
            )
    return cache


def _binding_declaration(binding: SourceBinding) -> dict[str, str]:
    return {"source_ref": binding.source_ref, "kind": binding.kind}


def _build_review_manifest(
    contract: EvidenceSourceContract,
    case_ids: list[str],
    sources: dict[tuple[str, str], RetrievedSource],
    work_dir: Path,
) -> tuple[Path, str, dict[str, int]]:
    entries: list[dict[str, object]] = []
    composite_count = 0
    bundle_dir = work_dir / "bundles"
    for position, case_id in enumerate(case_ids, start=1):
        bindings = contract.for_case(case_id)
        if not bindings:
            raise ExecutionError(f"contract case {case_id} has no source bindings")
        if len(bindings) == 1:
            binding = bindings[0]
            source = sources[binding.pair()]
            entries.append(
                {
                    "artifact": str(source.path),
                    "case": case_id,
                    "kind": binding.kind,
                    "note": "GT-H3B frozen official raw bytes",
                    "sources": [_binding_declaration(binding)],
                }
            )
            continue

        if case_id not in KNOWN_COMPOSITE_CASE_ROLES:
            raise ExecutionError(
                f"unexpected multi-source case {case_id}; composite roles are frozen"
            )
        if len(bindings) != len(KNOWN_COMPOSITE_CASE_ROLES[case_id]):
            raise ExecutionError(f"composite case {case_id} has the wrong source count")
        bundle_sources = [
            {
                "path": str(sources[binding.pair()].path),
                "source_ref": binding.source_ref,
                "kind": binding.kind,
            }
            for binding in bindings
        ]
        bundle_path = bundle_dir / f"bundle-{position:03d}.zip"
        try:
            write_evidence_bundle(bundle_path, bundle_sources)
        except (EvidenceBundleError, OSError) as exc:
            raise ExecutionError(f"cannot create bundle for {case_id}: {exc}") from exc
        entries.append(
            {
                "artifact": str(bundle_path),
                "case": case_id,
                "kind": "EVIDENCE_BUNDLE",
                "note": "GT-H3B frozen RULE/APPLICABILITY raw bytes",
                "bundle_sources": [_binding_declaration(binding) for binding in bindings],
            }
        )
        composite_count += 1

    manifest_path = work_dir / "gt_h3b_125_review_manifest.json"
    manifest_bytes = _json_bytes(entries)
    manifest_path.write_bytes(manifest_bytes)
    return (
        manifest_path,
        _sha256(manifest_bytes),
        {
            "case_count": len(entries),
            "ordinary_cases": len(entries) - composite_count,
            "composite_cases": composite_count,
            "bundle_count": composite_count,
        },
    )


def _verify_reviewed_output(
    repo_root: Path,
    contract: EvidenceSourceContract | None,
    case_ids: list[str],
    immutable_before: dict[str, str],
    reviewer: str,
    manifest_sha256: str | None,
) -> dict:
    golden = repo_root / GOLDEN_RELATIVE
    active = _read_json(golden / "truth_manifest.json")
    truth_version = str(active.get("truth_version", ""))
    if not truth_version.startswith("v7-reviewed-"):
        raise ExecutionError(f"seal did not produce a v7 reviewed ACTIVE: {truth_version}")
    dataset_path = golden / str(active.get("dataset_file", ""))
    if not dataset_path.is_file():
        raise ExecutionError("reviewed ACTIVE dataset is missing")
    if _path_hash(dataset_path) != active.get("dataset_hash"):
        raise ExecutionError("reviewed ACTIVE dataset hash mismatch")
    documents = _load_active_case_documents(repo_root, active)
    if [str(document.get("golden_case_id")) for document in documents] != case_ids:
        raise ExecutionError("reviewed dataset case order/coverage changed")
    if len(documents) != 125:
        raise ExecutionError("reviewed dataset does not contain exactly 125 cases")
    for document in documents:
        if document.get("review_status") != "REVIEWED":
            raise ExecutionError(f"case {document.get('golden_case_id')} is not REVIEWED")
        if document.get("reviewed_by") != reviewer:
            raise ExecutionError(f"case {document.get('golden_case_id')} reviewer mismatch")
        ref = document.get("source_artifact_ref")
        digest = document.get("source_artifact_hash")
        if not isinstance(ref, str) or not ref.startswith("sha256/"):
            raise ExecutionError(
                f"case {document.get('golden_case_id')} has no content-addressed ref"
            )
        relative_ref = Path(ref)
        if relative_ref.is_absolute() or ".." in relative_ref.parts:
            raise ExecutionError(
                f"case {document.get('golden_case_id')} has an unsafe evidence ref"
            )
        evidence_path = golden / "evidence" / relative_ref
        if not evidence_path.is_file():
            raise ExecutionError(f"missing evidence bytes for {document.get('golden_case_id')}")
        if not isinstance(digest, str) or _path_hash(evidence_path) != digest:
            raise ExecutionError(f"evidence hash mismatch for {document.get('golden_case_id')}")
        if (
            contract is not None
            and str(document.get("golden_case_id")) in KNOWN_COMPOSITE_CASE_ROLES
        ):
            expected = [
                _binding_declaration(binding)
                for binding in contract.for_case(str(document["golden_case_id"]))
            ]
            try:
                read_evidence_bundle(evidence_path, expected_sources=expected)
            except EvidenceBundleError as exc:
                raise ExecutionError(
                    f"composite evidence verification failed for "
                    f"{document['golden_case_id']}: {exc}"
                ) from exc

    try:
        store = GoldenTruthStore(golden)
        cases, manifest = store.load()
    except (GoldenTruthError, OSError, ValueError) as exc:
        raise ExecutionError(f"reviewed ACTIVE failed Golden loader verification: {exc}") from exc
    gates = {
        "review_readiness": review_readiness_gate(cases, manifest),
        "quantity": store.quantity_gate(cases, manifest),
        "event_coverage": store.event_coverage_gate(cases, manifest),
        "production_formal": store.production_formal_gate(cases, manifest),
    }
    if any(gates.values()):
        raise ExecutionError(f"reviewed Golden gates are not empty: {gates}")
    if manifest.case_count != 125 or manifest.review_summary != {"REVIEWED": 125}:
        raise ExecutionError("reviewed manifest is not REVIEWED 125/125")
    if manifest_sha256 is not None and not manifest_sha256:
        raise ExecutionError("review manifest SHA256 is unexpectedly empty")
    _assert_immutable(repo_root, immutable_before)
    evidence_refs = {
        str(document["source_artifact_ref"])
        for document in documents
        if document.get("source_artifact_ref")
    }
    evidence_bytes = sum(
        (golden / "evidence" / Path(reference)).stat().st_size for reference in evidence_refs
    )
    return {
        "active": _active_summary(active),
        "reviewed_version": truth_version,
        "dataset_hash": active["dataset_hash"],
        "case_count": len(documents),
        "review_summary": manifest.review_summary,
        "evidence_ref_count": len(evidence_refs),
        "evidence_bytes": evidence_bytes,
        "gates": gates,
    }


def _verify_existing_seal(repo_root: Path, receipt: dict) -> None:
    golden = repo_root / GOLDEN_RELATIVE
    active = _read_json(golden / "truth_manifest.json")
    expected_version = receipt.get("phase_c", {}).get("reviewed_version")
    if active.get("truth_version") != expected_version:
        raise ExecutionError("existing receipt does not match the current ACTIVE pointer")
    if not str(active.get("truth_version", "")).startswith("v7-reviewed-"):
        raise ExecutionError("existing receipt does not point to a v7 reviewed version")
    try:
        store = GoldenTruthStore(golden)
        cases, manifest = store.load()
    except (GoldenTruthError, OSError, ValueError) as exc:
        raise ExecutionError(f"existing reviewed ACTIVE failed verification: {exc}") from exc
    if len(cases) != 125 or manifest.review_summary != {"REVIEWED": 125}:
        raise ExecutionError("existing reviewed ACTIVE is not a 125/125 seal")
    if any(document.reviewed_by != "project-owner" for document in cases):
        raise ExecutionError("existing reviewed ACTIVE reviewer provenance changed")
    _assert_immutable(repo_root, receipt.get("immutable_v1_v6", {}))


def _append_once(path: Path, marker: str, entry: str) -> None:
    try:
        existing = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExecutionError(f"cannot read governance document {path}: {exc}") from exc
    if marker in existing:
        return
    payload = existing.rstrip() + "\n\n" + entry.strip() + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")


def _write_receipt_and_governance(repo_root: Path, receipt: dict) -> None:
    receipt_path = repo_root / RECEIPT_RELATIVE
    payload = _json_bytes(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if receipt_path.exists():
        if receipt_path.read_bytes() != payload:
            raise ExecutionError("execution receipt already exists with different bytes")
    else:
        receipt_path.write_bytes(payload)

    executed_at = str(receipt["executed_at"])
    date = executed_at[:10]
    run_id = str(receipt.get("workflow_run_id") or "local")
    source_sha = str(receipt.get("source_head_sha") or receipt.get("source_main_sha") or "unknown")
    phase_b = receipt["phase_b"]
    phase_c = receipt["phase_c"]
    devlog_entry = (
        "\n".join(
            [
                f"## {date} · GT-H3B controlled execution succeeded",
                "",
                "> 状态：**GT-H3B PHASE A/B/C SUCCEEDED / REVIEWED 125/125 / "
                "FORMAL PRODUCTION NOT RUN**",
                "",
                f"- source execution SHA：{source_sha}；workflow run：{run_id}。",
                "- Phase A 通过已治理的 candidate.py promote-existing，ACTIVE 从 v5 推进到 v6；",
                "  v1-v6 versioned files 经执行前后 hash 对比保持不变。",
                f"- Phase B 按冻结合同 {phase_b['contract_sha256']} 获取 "
                f"{phase_b['case_count']} 个 case 的官方原始 bytes；",
                f"  普通 {phase_b['ordinary_cases']}、复合 {phase_b['composite_cases']}、"
                f"deterministic bundle {phase_b['bundle_count']}。",
                f"- 125-entry review manifest SHA256：{phase_b['review_manifest_sha256']}；",
                "  未使用 expect_fields。",
                f"- Phase C 通过 review.py --reviewer project-owner 一次性生成 "
                f"{phase_c['reviewed_version']}，REVIEWED 125/125；",
                f"  evidence refs {phase_c['evidence_ref_count']}，hash consistency 已复核。",
                "- Formal Production B1-B7：**NOT RUN**；未提交任何账号、密码、Token、",
                "  IP、Cookie 或 Provider 凭据。",
            ]
        )
        + "\n"
    )
    management_entry = (
        "\n".join(
            [
                f"## DM-CR-{date.replace('-', '')}-121 · GT-H3B受控真实执行闭环",
                "",
                "**Type**：C1 — controlled GT-H3B execution",
                f"**Date**：{date}",
                "**Status**：SUCCEEDED / REVIEWED 125/125 / FORMAL PRODUCTION NOT RUN",
                f"**Evidence**：{RECEIPT_RELATIVE.as_posix()}；workflow run {run_id}；",
                f"reviewed version {phase_c['reviewed_version']}；",
                f"dataset SHA256 {phase_c['dataset_hash']}。",
                "",
                "- Phase A 使用已审阅的 promote-existing，没有重写 v1-v6 versioned bytes。",
                "- Phase B 只使用冻结 source contract，125 case exactly once，含 5 个",
                "  RULE → APPLICABILITY deterministic bundles；证据 bytes/hash 由 review.py 复核。",
                "- Phase C 是一次性 REVIEWED 125/125，reviewer marker 为 project-owner；",
                "  quantity/event/review/production formal gates 均为空。",
                "- Formal Production B1-B7、Provider capability verdict、Data Sufficiency",
                "  和 2020+ backfill 均未执行。",
            ]
        )
        + "\n"
    )
    _append_once(
        repo_root / "docs/DEVLOG.md",
        f"## {date} · GT-H3B controlled execution succeeded",
        devlog_entry,
    )
    _append_once(
        repo_root / "docs/project/DEVELOPMENT_MANAGEMENT.md",
        f"DM-CR-{date.replace('-', '')}-121 · GT-H3B受控真实执行闭环",
        management_entry,
    )


def execute(repo_root: Path, *, reviewer: str, timeout: float) -> dict:
    receipt_path = repo_root / RECEIPT_RELATIVE
    if receipt_path.exists():
        receipt = _read_json(receipt_path)
        if receipt.get("status") != "SUCCEEDED":
            raise ExecutionError("existing execution receipt is not successful")
        _verify_existing_seal(repo_root, receipt)
        print("GT-H3B controlled execution already completed; idempotent verification passed")
        return receipt

    immutable_before = _snapshot_immutable(repo_root)
    golden = repo_root / GOLDEN_RELATIVE
    active_before = _read_json(golden / "truth_manifest.json")
    promoted, promotion_output = _run_promotion(repo_root)
    documents = _load_active_case_documents(repo_root, promoted)
    case_ids = [str(document.get("golden_case_id", "")) for document in documents]
    if len(case_ids) != 125 or any(not case_id for case_id in case_ids):
        raise ExecutionError("Phase A ACTIVE v6 case set is not exactly 125 valid IDs")
    contract = _load_v6_contract(repo_root, promoted, documents)

    with tempfile.TemporaryDirectory(prefix="gt-h3b-") as temporary:
        work_dir = Path(temporary)
        sources = _download_sources(contract, case_ids, work_dir, timeout)
        manifest_path, manifest_sha256, manifest_stats = _build_review_manifest(
            contract, case_ids, sources, work_dir
        )
        review_command = [
            sys.executable,
            str(repo_root / "scripts/golden/review.py"),
            "--manifest",
            str(manifest_path),
            "--reviewer",
            reviewer,
        ]
        _run_checked(review_command, cwd=repo_root, label="GT-H3B Phase C review seal")
        final = _verify_reviewed_output(
            repo_root,
            contract,
            case_ids,
            immutable_before,
            reviewer,
            manifest_sha256,
        )
        source_binding_occurrences = sum(len(contract.for_case(case_id)) for case_id in case_ids)
        receipt = {
            "format": "GT-H3B-CONTROLLED-EXECUTION-RECEIPT/v1",
            "status": "SUCCEEDED",
            "executed_at": datetime.now(UTC).isoformat(),
            "source_main_sha": os.environ.get("GITHUB_SHA"),
            "source_head_sha": os.environ.get("GITHUB_HEAD_SHA"),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "phase_a": {
                "command": [
                    "uv",
                    "run",
                    "python",
                    "scripts/golden/candidate.py",
                    "promote-existing",
                    "--truth-version",
                    V6_VERSION,
                ],
                "active_before": _active_summary(active_before),
                "active_after": _active_summary(promoted),
                "result": "SUCCEEDED",
                "stdout_tail": promotion_output.splitlines()[-1:] or [],
            },
            "phase_b": {
                "contract_sha256": PRODUCTION_CONTRACT_SHA256,
                "case_count": manifest_stats["case_count"],
                "ordinary_cases": manifest_stats["ordinary_cases"],
                "composite_cases": manifest_stats["composite_cases"],
                "bundle_count": manifest_stats["bundle_count"],
                "unique_source_bindings": len(sources),
                "source_binding_occurrences": source_binding_occurrences,
                "redirected_sources": sum(
                    source.final_url != source.source_ref for source in sources.values()
                ),
                "official_http_200": len(sources),
                "review_manifest_sha256": manifest_sha256,
            },
            "phase_c": {
                "command": [
                    "uv",
                    "run",
                    "python",
                    "scripts/golden/review.py",
                    "--manifest",
                    "<generated-125-entry-manifest>",
                    "--reviewer",
                    reviewer,
                ],
                "reviewer": reviewer,
                "reviewed_version": final["reviewed_version"],
                "dataset_hash": final["dataset_hash"],
                "case_count": final["case_count"],
                "review_summary": final["review_summary"],
                "evidence_ref_count": final["evidence_ref_count"],
                "evidence_bytes": final["evidence_bytes"],
                "gates": final["gates"],
            },
            "immutable_v1_v6": immutable_before,
            "formal_production_b1_b7": "NOT_RUN",
            "credentials_committed": False,
        }
    _write_receipt_and_governance(repo_root, receipt)
    print(json.dumps(receipt["phase_c"], ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="GT-H3B controlled execution")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--reviewer", default="project-owner")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    try:
        execute(args.repo_root.resolve(), reviewer=args.reviewer, timeout=args.timeout)
    except (ExecutionError, OSError, ValueError) as exc:
        print(f"GT-H3B execution blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
