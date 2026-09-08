"""Machine-bound evidence-source contract for the GT-H3B review seal.

This module deliberately contains no network access.  It validates the
versioned contract, official-host policy, and case-to-source declarations
before review.py reads or stages any evidence bytes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ashare_state.spike.golden_store import VALID_ARTIFACT_KINDS

CONTRACT_FORMAT = "GT-H3B-CASE-EVIDENCE-CONTRACT/v1"
CONTRACT_RELATIVE_PATH = Path("docs/golden/gt_h3/gt_h3b/v6_case_evidence_source_contract.jsonl")
PRODUCTION_CONTRACT_SHA256 = "3c235e35d1a09f0171322a7f0c610edb3cbe3d5ad8c6afc701f7b90afa77d3bb"

# These are the exact hosts used by the reviewed GT-H3 / GT-H3R / GT-H3R2
# source metadata.  Aliases are explicit; broad suffix or wildcard matching
# is intentionally not used.
OFFICIAL_SOURCE_HOSTS = frozenset(
    {
        "www.sse.com.cn",
        "static.sse.com.cn",
        "star.sse.com.cn",
        "www.szse.cn",
        "disc.static.szse.cn",
        "www.bse.cn",
        "static.cninfo.com.cn",
    }
)

KNOWN_COMPOSITE_CASE_ROLES: dict[str, tuple[str, ...]] = {
    "GT-LIMIT-ST5-600518-20190603": ("RULE", "APPLICABILITY"),
    "GT-LIMIT-ST5-600518-20191028": ("RULE", "APPLICABILITY"),
    "GT-LIMIT-STAR20-688981-20200723": ("RULE", "APPLICABILITY"),
    "GT-LIMIT-IPO44-601995": ("RULE", "APPLICABILITY"),
    "GT-LIMIT-IPO44-605499": ("RULE", "APPLICABILITY"),
}


class EvidenceSourceContractError(ValueError):
    """A case-to-official-source contract or declaration is invalid."""


@dataclass(frozen=True)
class SourceBinding:
    """One ordered source locator and its review artifact classification."""

    source_ref: str
    kind: str
    role: str | None = None

    def pair(self) -> tuple[str, str]:
        return self.source_ref, self.kind


@dataclass(frozen=True)
class EvidenceSourceContract:
    """The frozen source bindings for one exact dataset."""

    truth_version: str
    dataset_file: str
    dataset_sha256: str
    case_count: int
    bindings: dict[str, tuple[SourceBinding, ...]]

    def for_case(self, case_id: str) -> tuple[SourceBinding, ...]:
        try:
            return self.bindings[case_id]
        except KeyError as exc:
            raise EvidenceSourceContractError(
                f"case {case_id!r} is absent from the evidence-source contract"
            ) from exc


def validate_official_source_ref(value: object) -> str:
    """Validate a direct locator against the explicit official-host policy."""
    if not isinstance(value, str) or not value:
        raise EvidenceSourceContractError("source_ref must be a non-empty string")
    if value != value.strip() or any(character.isspace() for character in value):
        raise EvidenceSourceContractError("source_ref must not contain whitespace")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise EvidenceSourceContractError(f"source_ref is not a valid URL: {value!r}") from exc
    if parsed.scheme.lower() not in {"http", "https"} or hostname is None:
        raise EvidenceSourceContractError(f"source_ref must use an HTTP(S) URL: {value!r}")
    if (
        parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise EvidenceSourceContractError(
            f"source_ref must not contain credentials, a port, or a fragment: {value!r}"
        )
    if not parsed.path or parsed.path == "/":
        raise EvidenceSourceContractError(
            f"source_ref must identify a concrete official resource: {value!r}"
        )
    normalized_host = hostname.lower()
    if normalized_host not in OFFICIAL_SOURCE_HOSTS:
        raise EvidenceSourceContractError(
            f"source_ref host {normalized_host!r} is not in the explicit official allowlist"
        )
    return value


def _parse_source(raw: object, *, context: str) -> SourceBinding:
    if not isinstance(raw, Mapping):
        raise EvidenceSourceContractError(f"{context} must be an object")
    unknown = set(raw) - {"source_ref", "kind", "role"}
    if unknown:
        raise EvidenceSourceContractError(
            f"{context} contains unsupported fields: {sorted(unknown)}"
        )
    source_ref = validate_official_source_ref(raw.get("source_ref"))
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in VALID_ARTIFACT_KINDS:
        raise EvidenceSourceContractError(
            f"{context} kind {kind!r} is not in the artifact allowlist"
        )
    if kind == "EVIDENCE_BUNDLE":
        raise EvidenceSourceContractError(f"{context} cannot be an EVIDENCE_BUNDLE")
    role = raw.get("role")
    if role is not None and (not isinstance(role, str) or not role):
        raise EvidenceSourceContractError(f"{context} role must be a non-empty string")
    return SourceBinding(source_ref=source_ref, kind=kind, role=role)


def _read_records(path: Path) -> tuple[bytes, list[dict]]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceSourceContractError(
            f"cannot read evidence-source contract {path}: {exc}"
        ) from exc
    records: list[dict] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceSourceContractError(
                f"contract line {line_number} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(record, dict):
            raise EvidenceSourceContractError(f"contract line {line_number} must be a JSON object")
        records.append(record)
    return raw, records


def load_evidence_source_contract(
    path: Path,
    *,
    expected_truth_version: str,
    expected_dataset_file: str,
    expected_dataset_hash: str,
    expected_case_ids: Sequence[str],
    expected_sha256: str | None = None,
    enforce_known_composites: bool = True,
) -> EvidenceSourceContract:
    """Load and validate a contract against the active dataset identity."""
    raw, records = _read_records(path)
    if expected_sha256 is not None:
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256:
            raise EvidenceSourceContractError(
                "evidence-source contract bytes do not match the pinned production hash"
            )
    if not records or records[0].get("record_type") != "contract_header":
        raise EvidenceSourceContractError("contract must begin with one contract_header")
    header = records[0]
    if header.get("schema") != 1 or header.get("format") != CONTRACT_FORMAT:
        raise EvidenceSourceContractError("unsupported evidence-source contract format")
    if header.get("truth_version") != expected_truth_version:
        raise EvidenceSourceContractError(
            "evidence-source contract truth_version does not match ACTIVE"
        )
    if header.get("dataset_file") != expected_dataset_file:
        raise EvidenceSourceContractError(
            "evidence-source contract dataset_file does not match ACTIVE"
        )
    if header.get("dataset_sha256") != expected_dataset_hash:
        raise EvidenceSourceContractError(
            "evidence-source contract dataset_sha256 does not match ACTIVE"
        )
    case_ids = list(expected_case_ids)
    if (
        not case_ids
        or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
        or len(set(case_ids)) != len(case_ids)
    ):
        raise EvidenceSourceContractError("active dataset case IDs must be non-empty and unique")
    if header.get("case_count") != len(case_ids):
        raise EvidenceSourceContractError(
            "evidence-source contract case_count does not match ACTIVE"
        )
    case_records = records[1:]
    if len(case_records) != len(case_ids):
        raise EvidenceSourceContractError(
            "evidence-source contract must have exactly one record per ACTIVE case"
        )

    bindings: dict[str, tuple[SourceBinding, ...]] = {}
    for position, (record, expected_case_id) in enumerate(
        zip(case_records, case_ids, strict=True), start=1
    ):
        if record.get("record_type") != "case":
            raise EvidenceSourceContractError(
                f"contract record {position} must have record_type='case'"
            )
        case_id = record.get("golden_case_id")
        if case_id != expected_case_id:
            raise EvidenceSourceContractError(
                f"contract record {position} case ID {case_id!r} does not match "
                f"ACTIVE case {expected_case_id!r}"
            )
        if case_id in bindings:
            raise EvidenceSourceContractError(f"contract contains duplicate case {case_id!r}")
        raw_sources = record.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise EvidenceSourceContractError(
                f"contract case {case_id!r} must declare at least one source"
            )
        parsed_sources = tuple(
            _parse_source(source, context=f"contract case {case_id!r} source {index}")
            for index, source in enumerate(raw_sources, start=1)
        )
        if len({source.pair() for source in parsed_sources}) != len(parsed_sources):
            raise EvidenceSourceContractError(
                f"contract case {case_id!r} contains duplicate source bindings"
            )
        known_roles = KNOWN_COMPOSITE_CASE_ROLES.get(case_id)
        if enforce_known_composites:
            if known_roles is not None:
                actual_roles = tuple(source.role for source in parsed_sources)
                if actual_roles != known_roles:
                    raise EvidenceSourceContractError(
                        f"contract composite case {case_id!r} must preserve roles {known_roles!r}"
                    )
            elif len(parsed_sources) != 1:
                raise EvidenceSourceContractError(
                    f"ordinary contract case {case_id!r} must declare exactly one source"
                )
        bindings[case_id] = parsed_sources
    return EvidenceSourceContract(
        truth_version=expected_truth_version,
        dataset_file=expected_dataset_file,
        dataset_sha256=expected_dataset_hash,
        case_count=len(case_ids),
        bindings=bindings,
    )


def validate_review_source_bindings(
    contract: EvidenceSourceContract,
    requests: Iterable[Mapping[str, object]],
) -> None:
    """Require every review request to match its case's frozen source pairs."""
    for position, request in enumerate(requests, start=1):
        request_kind = request.get("kind")
        if not isinstance(request_kind, str) or request_kind not in VALID_ARTIFACT_KINDS:
            raise EvidenceSourceContractError(
                f"review request {position} artifact kind {request_kind!r} not in allowlist"
            )
        case_id = request.get("case")
        if not isinstance(case_id, str) or not case_id:
            raise EvidenceSourceContractError(f"review request {position} has an invalid case ID")
        declared_field = "bundle_sources" if request.get("kind") == "EVIDENCE_BUNDLE" else "sources"
        raw_sources = request.get(declared_field)
        if not isinstance(raw_sources, list) or not raw_sources:
            raise EvidenceSourceContractError(
                f"review request {position} case {case_id!r} must declare {declared_field}"
            )
        declared = tuple(
            _parse_source(
                source,
                context=f"review request {position} {declared_field} {index}",
            )
            for index, source in enumerate(raw_sources, start=1)
        )
        if request_kind != "EVIDENCE_BUNDLE":
            source_kind = declared[0].kind if len(declared) == 1 else None
            if request_kind != source_kind:
                raise EvidenceSourceContractError(
                    f"ordinary review request {position} case {case_id!r} artifact kind "
                    f"{request_kind!r} does not match source kind {source_kind!r}"
                )
        expected = contract.for_case(case_id)
        actual_pairs = tuple(source.pair() for source in declared)
        expected_pairs = tuple(source.pair() for source in expected)
        if actual_pairs != expected_pairs:
            raise EvidenceSourceContractError(
                f"review request {position} case {case_id!r} source binding does not "
                "match the frozen contract"
            )
