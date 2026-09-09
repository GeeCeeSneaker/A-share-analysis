"""Deterministic per-rule evidence contract for trading-rule review.

The trading-rule dataset spans several venues and historical regimes. A
single top-level official artifact cannot prove every rule fact, so a
reviewed dataset may bind a RULE_EVIDENCE_BUNDLE.v1 manifest. The bundle
lists exactly one entry per rule_id and one or more first-party source
artifacts for that rule. The validator re-checks the manifest, source host,
role, path confinement, byte size, and raw-byte SHA-256.

The module deliberately has no dependency on the rule loader. It can be
used by the review CLI before the reviewed YAML is published and by the
runtime review gate after publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

RULE_EVIDENCE_BUNDLE_SCHEMA = "RULE_EVIDENCE_BUNDLE.v1"
RULE_EVIDENCE_BUNDLE_REF = "rule_evidence_bundle_ref"
RULE_EVIDENCE_BUNDLE_HASH = "rule_evidence_bundle_hash"
RULE_EVIDENCE_BUNDLE_KIND = "EVIDENCE_BUNDLE"

RULE_EVIDENCE_ARTIFACT_KINDS = (
    "EXCHANGE_RULEBOOK",
    "EXCHANGE_NOTICE",
    "REGULATOR_DOC",
    "DATASET_DOC",
    "OTHER_OFFICIAL",
)
RULE_EVIDENCE_ROLES = ("RULE", "APPLICABILITY", "TRANSITION")
OFFICIAL_SOURCE_HOST_SUFFIXES = (
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "neeq.com.cn",
    "csrc.gov.cn",
)

_HEX64 = set("0123456789abcdef")
_SOURCE_URL_RE = re.compile(r"https://[^\s|]+")


@dataclass(frozen=True)
class RawRuleEvidence:
    """One raw source artifact prepared for content-addressed staging."""

    artifact_ref: str
    content: bytes


@dataclass(frozen=True)
class PreparedRuleEvidenceBundle:
    """Canonical bundle bytes plus the raw artifacts it references."""

    content: bytes
    raw_artifacts: tuple[RawRuleEvidence, ...]


def _is_hex64(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and set(text) <= _HEX64


def source_urls_from_ref(source_ref: object) -> tuple[str, ...]:
    """Return the exact HTTPS locators declared in a rule ``source_ref``.

    Rule YAML keeps the human-readable source description for backwards
    compatibility.  The evidence bundle still has to bind to one of the
    locators declared there; otherwise any official-looking URL could be
    substituted for the rule's stated source.
    """

    values = [match.rstrip(".,;)") for match in _SOURCE_URL_RE.findall(str(source_ref or ""))]
    return tuple(dict.fromkeys(values))


def _source_url_contract_problem(
    rule_id: str,
    source_url: str,
    expected_source_urls_by_rule: Mapping[str, Sequence[str]] | None,
) -> str:
    if expected_source_urls_by_rule is None:
        return ""
    declared = expected_source_urls_by_rule.get(rule_id)
    if declared is None:
        return f"no declared source URL contract for rule_id {rule_id!r}"
    if isinstance(declared, str):
        allowed = {declared}
    else:
        allowed = {str(value) for value in declared}
    if source_url not in allowed:
        return (
            f"source_url {source_url!r} is not declared by rule_id {rule_id!r}; "
            f"expected one of {sorted(allowed)!r}"
        )
    return ""


def _source_url_contract_shape_problems(
    expected_rule_ids: Sequence[str],
    expected_source_urls_by_rule: Mapping[str, Sequence[str]] | None,
) -> list[str]:
    if expected_source_urls_by_rule is None:
        return []
    expected = set(expected_rule_ids)
    supplied = set(expected_source_urls_by_rule)
    problems: list[str] = []
    missing = sorted(expected - supplied)
    extra = sorted(supplied - expected)
    if missing:
        problems.append(f"source URL contract missing rule_id entries: {missing}")
    if extra:
        problems.append(f"source URL contract has extra rule_id entries: {extra}")
    for rule_id in sorted(expected & supplied):
        declared = expected_source_urls_by_rule[rule_id]
        values = (declared,) if isinstance(declared, str) else tuple(declared)
        if not {str(value) for value in values}:
            problems.append(f"source URL contract for {rule_id!r} is empty")
    return problems


def _safe_relative_ref(ref: object) -> tuple[bool, str]:
    """Validate a relative evidence-root path without filesystem access."""

    text = str(ref or "")
    normalized = text.replace("\\", "/")
    if not normalized:
        return False, "empty reference"
    if normalized.startswith(("/", "\\")):
        return False, "absolute reference"
    if ":" in normalized.split("/")[0]:
        return False, "drive-letter reference"
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False, "reference contains an empty, '.', or '..' component"
    return True, normalized


def _confined_evidence_path(evidence_root: Path, ref: object) -> tuple[Path | None, str]:
    """Resolve a validated relative ref and enforce resolved confinement."""

    ok, normalized = _safe_relative_ref(ref)
    if not ok:
        return None, normalized
    candidate = (evidence_root / normalized).resolve()
    try:
        candidate.relative_to(evidence_root.resolve())
    except ValueError:
        return None, "resolved path escapes evidence root"
    return candidate, ""


def _official_url_problem(value: object) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        return "source_url must be an https URL"
    host = parsed.hostname.lower().rstrip(".")
    if not any(
        host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_SOURCE_HOST_SUFFIXES
    ):
        return f"source_url host is not an allowed first-party host: {host!r}"
    return ""


def _validate_rule_ids(entries: object, expected_rule_ids: Sequence[str]) -> list[str]:
    problems: list[str] = []
    if not isinstance(entries, list):
        return ["entries must be a list"]
    expected = set(expected_rule_ids)
    seen: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            problems.append(f"entries[{index}] must be an object")
            continue
        rule_id = str(entry.get("rule_id", "") or "")
        if not rule_id:
            problems.append(f"entries[{index}].rule_id is empty")
        seen.append(rule_id)
    duplicates = sorted({rule_id for rule_id in seen if seen.count(rule_id) > 1})
    if duplicates:
        problems.append(f"duplicate rule_id entries: {duplicates}")
    missing = sorted(expected - set(seen))
    extra = sorted(set(seen) - expected)
    if missing:
        problems.append(f"missing rule_id entries: {missing}")
    if extra:
        problems.append(f"extra rule_id entries: {extra}")
    return problems


def _read_manifest(path: Path) -> tuple[dict[str, object] | None, list[str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"bundle manifest unreadable: {exc}"]
    if not isinstance(document, dict):
        return None, ["bundle manifest must be a JSON object"]
    return document, []


def prepare_rule_evidence_bundle(
    manifest_path: Path | str,
    *,
    expected_rule_ids: Sequence[str],
    expected_dataset_version: str,
    expected_source_urls_by_rule: Mapping[str, Sequence[str]] | None = None,
) -> PreparedRuleEvidenceBundle:
    """Validate a reviewer-supplied input manifest and canonicalize it.

    Input sources use artifact_path relative to the input manifest (or an
    absolute path). The published bundle never contains that local path:
    it contains only content-addressed artifact_ref, SHA-256, size, role,
    kind, and first-party URL.
    """

    path = Path(manifest_path)
    if not path.is_file():
        raise ValueError(f"bundle manifest not found: {path}")
    document, problems = _read_manifest(path)
    if problems or document is None:
        raise ValueError("; ".join(problems))
    if document.get("schema_version") != RULE_EVIDENCE_BUNDLE_SCHEMA:
        problems.append(
            f"schema_version must be {RULE_EVIDENCE_BUNDLE_SCHEMA!r}, "
            f"got {document.get('schema_version')!r}"
        )
    if str(document.get("dataset_version", "") or "") != expected_dataset_version:
        problems.append(
            "dataset_version does not match the candidate: "
            f"{document.get('dataset_version')!r} != {expected_dataset_version!r}"
        )
    entries = document.get("entries")
    problems.extend(_validate_rule_ids(entries, expected_rule_ids))
    problems.extend(
        _source_url_contract_shape_problems(expected_rule_ids, expected_source_urls_by_rule)
    )
    if problems:
        raise ValueError("; ".join(problems))

    canonical_entries: list[dict[str, object]] = []
    raw_artifacts: dict[str, bytes] = {}
    assert isinstance(entries, list)
    for entry in entries:
        assert isinstance(entry, Mapping)
        rule_id = str(entry["rule_id"])
        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            problems.append(f"{rule_id}.sources must be a non-empty list")
            continue
        canonical_sources: list[dict[str, object]] = []
        source_refs: set[str] = set()
        for source_index, source in enumerate(sources):
            if not isinstance(source, Mapping):
                problems.append(f"{rule_id}.sources[{source_index}] must be an object")
                continue
            kind = str(source.get("artifact_kind", "") or "")
            role = str(source.get("role", "") or "")
            source_url = str(source.get("source_url", "") or "")
            artifact_path_raw = str(source.get("artifact_path", "") or "")
            if kind not in RULE_EVIDENCE_ARTIFACT_KINDS:
                problems.append(
                    f"{rule_id}.sources[{source_index}].artifact_kind {kind!r} "
                    f"not in {RULE_EVIDENCE_ARTIFACT_KINDS}"
                )
            if role not in RULE_EVIDENCE_ROLES:
                problems.append(
                    f"{rule_id}.sources[{source_index}].role {role!r} not in {RULE_EVIDENCE_ROLES}"
                )
            url_problem = _official_url_problem(source_url)
            if url_problem:
                problems.append(f"{rule_id}.sources[{source_index}]: {url_problem}")
            source_contract_problem = _source_url_contract_problem(
                rule_id, source_url, expected_source_urls_by_rule
            )
            if source_contract_problem:
                problems.append(f"{rule_id}.sources[{source_index}]: {source_contract_problem}")
            if not artifact_path_raw:
                problems.append(f"{rule_id}.sources[{source_index}].artifact_path is empty")
                continue
            artifact_path = Path(artifact_path_raw)
            if not artifact_path.is_absolute():
                artifact_path = path.parent / artifact_path
            if not artifact_path.is_file():
                problems.append(
                    f"{rule_id}.sources[{source_index}].artifact_path not found: {artifact_path}"
                )
                continue
            content = artifact_path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            artifact_ref = f"sha256/{digest}"
            if artifact_ref in source_refs:
                problems.append(
                    f"{rule_id}.sources[{source_index}] duplicates artifact_ref {artifact_ref}"
                )
            source_refs.add(artifact_ref)
            existing = raw_artifacts.get(artifact_ref)
            if existing is not None and existing != content:
                problems.append(f"artifact collision for {artifact_ref}")
            raw_artifacts[artifact_ref] = content
            canonical_sources.append(
                {
                    "artifact_kind": kind,
                    "artifact_ref": artifact_ref,
                    "byte_size": len(content),
                    "role": role,
                    "sha256": digest,
                    "source_url": source_url,
                }
            )
        canonical_entries.append(
            {
                "rule_id": rule_id,
                "sources": sorted(
                    canonical_sources,
                    key=lambda item: (
                        str(item["role"]),
                        str(item["source_url"]),
                        str(item["artifact_ref"]),
                    ),
                ),
            }
        )
    if problems:
        raise ValueError("; ".join(problems))
    canonical = {
        "dataset_version": expected_dataset_version,
        "entries": sorted(canonical_entries, key=lambda item: str(item["rule_id"])),
        "schema_version": RULE_EVIDENCE_BUNDLE_SCHEMA,
    }
    return PreparedRuleEvidenceBundle(
        content=(json.dumps(canonical, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        raw_artifacts=tuple(
            RawRuleEvidence(artifact_ref=ref, content=content)
            for ref, content in sorted(raw_artifacts.items())
        ),
    )


def validate_rule_evidence_bundle(
    *,
    bundle_ref: str,
    bundle_hash: str,
    expected_rule_ids: Sequence[str],
    expected_dataset_version: str,
    rules_root: Path | str,
    expected_source_urls_by_rule: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Validate a published bundle and every raw source it names."""

    problems: list[str] = []
    problems.extend(
        _source_url_contract_shape_problems(expected_rule_ids, expected_source_urls_by_rule)
    )
    evidence_root = Path(rules_root) / "evidence"
    bundle_path, reason = _confined_evidence_path(evidence_root, bundle_ref)
    if bundle_path is None:
        return [f"rule evidence bundle ref rejected: {reason}"]
    if not _is_hex64(bundle_hash):
        problems.append(f"rule evidence bundle hash must be 64 lower-hex chars: {bundle_hash!r}")
        return problems
    if bundle_ref != f"sha256/{bundle_hash}":
        problems.append(
            "rule evidence bundle ref must be content-addressed as sha256/<bundle_hash>: "
            f"{bundle_ref!r}"
        )
        return problems
    if not bundle_path.is_file():
        return [f"rule evidence bundle not found under evidence root: {bundle_ref}"]
    bundle_bytes = bundle_path.read_bytes()
    actual_bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()
    if actual_bundle_hash != bundle_hash:
        problems.append(
            f"rule evidence bundle hash mismatch: expected {bundle_hash}, "
            f"actual {actual_bundle_hash}"
        )
        return problems
    try:
        document = json.loads(bundle_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"rule evidence bundle is not valid UTF-8 JSON: {exc}"]
    if not isinstance(document, dict):
        return ["rule evidence bundle must be a JSON object"]
    if document.get("schema_version") != RULE_EVIDENCE_BUNDLE_SCHEMA:
        problems.append(
            f"rule evidence bundle schema_version must be {RULE_EVIDENCE_BUNDLE_SCHEMA!r}"
        )
    if str(document.get("dataset_version", "") or "") != expected_dataset_version:
        problems.append(
            "rule evidence bundle dataset_version does not match the rule dataset: "
            f"{document.get('dataset_version')!r} != {expected_dataset_version!r}"
        )
    entries = document.get("entries")
    problems.extend(_validate_rule_ids(entries, expected_rule_ids))
    if not isinstance(entries, list):
        return problems

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        rule_id = str(entry.get("rule_id", "") or "")
        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            problems.append(f"{rule_id}.sources must be a non-empty list")
            continue
        seen_refs: set[str] = set()
        for source_index, source in enumerate(sources):
            prefix = f"{rule_id}.sources[{source_index}]"
            if not isinstance(source, Mapping):
                continue
            kind = str(source.get("artifact_kind", "") or "")
            role = str(source.get("role", "") or "")
            source_url = str(source.get("source_url", "") or "")
            ref = str(source.get("artifact_ref", "") or "")
            declared_hash = str(source.get("sha256", "") or "")
            declared_size = source.get("byte_size")
            if kind not in RULE_EVIDENCE_ARTIFACT_KINDS:
                problems.append(f"{prefix}.artifact_kind {kind!r} not allowed")
            if role not in RULE_EVIDENCE_ROLES:
                problems.append(f"{prefix}.role {role!r} not allowed")
            url_problem = _official_url_problem(source_url)
            if url_problem:
                problems.append(f"{prefix}: {url_problem}")
            source_contract_problem = _source_url_contract_problem(
                rule_id, source_url, expected_source_urls_by_rule
            )
            if source_contract_problem:
                problems.append(f"{prefix}: {source_contract_problem}")
            if ref in seen_refs:
                problems.append(f"{prefix} duplicates artifact_ref {ref!r} for the same rule")
            seen_refs.add(ref)
            if not _is_hex64(declared_hash):
                problems.append(f"{prefix}.sha256 must be 64 lower-hex chars")
                continue
            if ref != f"sha256/{declared_hash}":
                problems.append(
                    f"{prefix}.artifact_ref must be content-addressed as "
                    f"sha256/<sha256>, got {ref!r}"
                )
            if isinstance(declared_size, bool) or not isinstance(declared_size, int):
                problems.append(f"{prefix}.byte_size must be a non-negative integer")
                continue
            if declared_size < 0:
                problems.append(f"{prefix}.byte_size must be a non-negative integer")
                continue
            artifact_path, reason = _confined_evidence_path(evidence_root, ref)
            if artifact_path is None:
                problems.append(f"{prefix}.artifact_ref rejected: {reason}")
                continue
            if not artifact_path.is_file():
                problems.append(f"{prefix}.artifact_ref not found: {ref}")
                continue
            content = artifact_path.read_bytes()
            actual_hash = hashlib.sha256(content).hexdigest()
            if len(content) != declared_size:
                problems.append(
                    f"{prefix}.byte_size mismatch: declared {declared_size}, actual {len(content)}"
                )
            if actual_hash != declared_hash:
                problems.append(
                    f"{prefix}.sha256 mismatch: declared {declared_hash}, actual {actual_hash}"
                )
    return problems


__all__ = [
    "OFFICIAL_SOURCE_HOST_SUFFIXES",
    "PreparedRuleEvidenceBundle",
    "RULE_EVIDENCE_ARTIFACT_KINDS",
    "RULE_EVIDENCE_BUNDLE_HASH",
    "RULE_EVIDENCE_BUNDLE_KIND",
    "RULE_EVIDENCE_BUNDLE_REF",
    "RULE_EVIDENCE_BUNDLE_SCHEMA",
    "RULE_EVIDENCE_ROLES",
    "RawRuleEvidence",
    "prepare_rule_evidence_bundle",
    "source_urls_from_ref",
    "validate_rule_evidence_bundle",
]
