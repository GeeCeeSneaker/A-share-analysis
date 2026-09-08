"""Golden candidate compilation and append-only rebuild workflow.

The legacy ``add-case``/``validate`` commands only stage candidate facts.
The old implicit ``build-version`` append path is intentionally disabled:
the v4+ publisher requires an explicit plan containing KEEP, REPLACE, DROP
and ADD for every source case.  This is what allows the v3 structural errors
to be removed without mutating the immutable v3 files.

Usage::

    python scripts/golden/candidate.py add-case --input new_events.jsonl
    python scripts/golden/candidate.py validate
    python scripts/golden/candidate.py rebuild --plan rebuild_v4.json
    python scripts/golden/candidate.py promote-existing --truth-version v6-candidate-20260908 \
        --plan v5_to_v6_rebuild_plan.json \
        --carry-forward v5_to_v6_human_review_carry_forward.jsonl \
        --transition-audit GT_H3R2_ST_TRANSITION_AUDIT.jsonl

The rebuild plan binds to the exact active ``truth_version`` and dataset
SHA256.  Every output row is COMPILED, and structural ST/DELIST identities
must be explicit; multiple observation rows may share one identity and are
deduplicated only for qualification.  Human review remains the separate
``scripts/golden/review.py`` workflow.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.golden_store import (  # noqa: E402
    GoldenTruthError,
    GoldenTruthStore,
    StructuralEventError,
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    review_identity_hash_for_doc,
    semantic_hash_for_doc,
    validate_structural_event_fields,
)
from ashare_state.spike.st_transition_audit import (  # noqa: E402
    transition_audit_publication_gate,
)

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
CANDIDATE_STAGING = GOLDEN_ROOT / "candidate_staging.jsonl"

DEFAULT_TRANSITION_AUDIT = (
    Path(__file__).resolve().parents[2]
    / "docs/golden/gt_h3/remediation/GT_H3R2_ST_TRANSITION_AUDIT.jsonl"
)


# GT-H3B-P0: fixed, reviewer-authorized promotion contract.  These hashes
# identify the already-staged bytes; they are deliberately not CLI inputs.
GT_H3B_V4_VERSION = "v4-candidate-20260906"
GT_H3B_V4_DATASET = "golden_cases_v4.jsonl"
GT_H3B_V4_DATASET_HASH = (
    "8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b"
)
GT_H3B_V4_MANIFEST = "truth_manifest_v4.json"
GT_H3B_V4_MANIFEST_SHA256 = (
    "ad69052c29e13f412f8608b7f4c11af4bb920430f0fa70ddf42af5dc5f756960"
)
GT_H3B_V5_VERSION = "v5-candidate-20260907"
GT_H3B_V5_DATASET = "golden_cases_v5.jsonl"
GT_H3B_V5_DATASET_HASH = (
    "5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c"
)
GT_H3B_V5_MANIFEST = "truth_manifest_v5.json"
GT_H3B_V5_MANIFEST_SHA256 = (
    "0019e22d947614a884f7573468e44d20b1bbbfcacebe94f583372fb8686569dc"
)
GT_H3B_V6_VERSION = "v6-candidate-20260908"
GT_H3B_V6_DATASET = "golden_cases_v6.jsonl"
GT_H3B_V6_DATASET_HASH = (
    "0b3952f9f82ee4f6a55a7f060c47af3cc781b0054ed1f83b5868246c0642a343"
)
GT_H3B_V6_MANIFEST = "truth_manifest_v6.json"
GT_H3B_V6_MANIFEST_SHA256 = (
    "f6cd5aa41a95ab3e640155c3050ec50ab69073b03e7d17b3f4ca68cadb250c06"
)
GT_H3B_REQUIRED_STATS = {
    "case_count": 125,
    "counts_by_type": {
        "golden_limit_regime": 30,
        "golden_corporate_action": 25,
        "golden_st_transition": 50,
        "golden_delisted": 20,
    },
    "review_summary": {"COMPILED": 125},
    "distinct_events": {
        "LIMIT_REGIME": 6,
        "NO_LIMIT_IPO": 3,
        "DIVIDEND_EX_DATE": 20,
        "RIGHT_ISSUE_EX_DATE": 5,
        "ST_TRANSITION": 50,
        "DELIST": 20,
    },
    "st_add_events": 38,
    "st_remove_events": 12,
    "distinct_delisted_securities": 20,
}
GT_H3B_PLAN_SUMMARY = {"KEEP": 110, "REPLACE": 0, "DROP": 15, "ADD": 15}
REVIEW_PROVENANCE_FIELDS = (
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "source_artifact_ref",
    "source_artifact_hash",
    "source_artifact_kind",
    "source_retrieved_at",
)

REQUIRED_FIELDS = (
    "golden_case_id",
    "case_type",
    "provider_symbol",
    "trade_date",
    "truth_source",
    "source_ref",
    "expected_fields",
    "event_id",
    "event_class",
)
VALID_EVENT_CLASSES = {
    "ST_TRANSITION",
    "DELIST",
    "LIMIT_REGIME",
    "NO_LIMIT_IPO",
    "DIVIDEND_EX_DATE",
    "RIGHT_ISSUE_EX_DATE",
    "BJ_CODE_MIGRATION",
    "NEGATIVE_SAMPLE",
}
REVIEW_PROVENANCE_FIELDS = (
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "source_artifact_ref",
    "source_artifact_hash",
    "source_artifact_kind",
    "source_retrieved_at",
)


class CandidateError(RuntimeError):
    """Candidate augmentation or rebuild contract violation."""


def _semantic_hash(doc: dict) -> str:
    """Use the shared legacy-compatible/version-aware semantic seal."""
    return semantic_hash_for_doc(doc)


def _validate_candidate(doc: dict, known_ids: set[str]) -> None:
    if not isinstance(doc, dict):
        raise CandidateError("candidate must be a JSON object")
    case_id = doc.get("golden_case_id", "?")
    missing = [f for f in REQUIRED_FIELDS if not doc.get(f)]
    if missing:
        raise CandidateError(f"candidate {case_id}: missing fields {missing}")
    if not isinstance(case_id, str):
        raise CandidateError(f"candidate {case_id!r}: golden_case_id must be text")
    if case_id in known_ids:
        raise CandidateError(f"candidate {case_id}: duplicate golden_case_id")
    event_class = doc["event_class"]
    if not isinstance(event_class, str) or event_class not in VALID_EVENT_CLASSES:
        raise CandidateError(f"candidate {case_id}: unknown event_class {event_class!r}")
    if doc.get("review_status") not in (None, "COMPILED"):
        raise CandidateError(
            f"candidate {case_id}: augmentation may only add COMPILED candidates "
            "(review is the review workflow's job)"
        )
    if any(str(doc.get(field, "")) for field in REVIEW_PROVENANCE_FIELDS):
        raise CandidateError(
            f"candidate {case_id}: candidate input contains review provenance; "
            "only review.py may bind artifacts or mark REVIEWED"
        )
    try:
        validate_structural_event_fields(
            case_id=case_id,
            event_class=event_class,
            provider_symbol=doc.get("provider_symbol"),
            event_subtype=doc.get("event_subtype", ""),
            event_effective_date=doc.get("event_effective_date", ""),
        )
    except StructuralEventError as exc:
        raise CandidateError(str(exc)) from exc


def _load_active_cases() -> tuple[dict, list[dict]]:
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    if not active_path.is_file():
        raise CandidateError(f"no active truth manifest under {GOLDEN_ROOT}")
    active = json.loads(active_path.read_text(encoding="utf-8"))
    dataset_file = str(active.get("dataset_file", ""))
    if not dataset_file:
        raise CandidateError("active manifest has no dataset_file")
    dataset = GOLDEN_ROOT / dataset_file
    if not dataset.is_file():
        raise CandidateError(f"active dataset does not exist: {dataset_file}")
    dataset_bytes = dataset.read_bytes()
    if hashlib.sha256(dataset_bytes).hexdigest() != active.get("dataset_hash"):
        raise CandidateError("active dataset hash mismatch")
    try:
        cases_from_dataset_bytes(dataset_bytes, str(active["truth_version"]))
    except GoldenTruthError as exc:
        raise CandidateError(f"active dataset is not loadable: {exc}") from exc
    lines = [
        json.loads(line) for line in dataset_bytes.decode("utf-8").splitlines() if line.strip()
    ]
    return active, lines




def _read_json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateError(f"{label} {path} must contain a JSON object")
    return value


def _read_jsonl_objects(path: Path, label: str) -> list[dict]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CandidateError(f"cannot read {label} {path}: {exc}") from exc
    rows: list[dict] = []
    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CandidateError(f"invalid JSONL {label} {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise CandidateError(f"JSONL {label} {path}:{line_number} must be an object")
        rows.append(value)
    return rows



def _jsonl_objects_from_bytes(payload: bytes, label: str) -> list[dict]:
    try:
        raw_lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CandidateError(f"{label} is not valid UTF-8: {exc}") from exc
    rows: list[dict] = []
    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CandidateError(f"invalid JSONL {label}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise CandidateError(f"JSONL {label}:{line_number} must be an object")
        rows.append(value)
    return rows

def _assert_file_hash(path: Path, expected_hash: str, label: str) -> bytes:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise CandidateError(f"cannot read {label} {path}: {exc}") from exc
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash:
        raise CandidateError(
            f"{label} {path.name}: SHA256 mismatch "
            f"(expected {expected_hash[:12]}..., actual {actual_hash[:12]}...)"
        )
    return payload


def _validate_promotion_stats(manifest: dict, cases: list, label: str) -> dict:
    stats = recompute_manifest_statistics(cases)
    for field, expected in GT_H3B_REQUIRED_STATS.items():
        if manifest.get(field) != expected:
            raise CandidateError(f"{label} manifest {field} != required value")
        if stats.get(field) != expected:
            raise CandidateError(f"{label} recomputation {field} != required value")
    if manifest.get("distinct_securities") != stats.get("distinct_securities"):
        raise CandidateError(f"{label} manifest distinct_securities != recomputed values")
    return stats


def _validate_promotion_compiled_docs(
    docs: list[dict], truth_version: str, label: str
) -> list:
    try:
        cases = _validate_output_documents(docs, truth_version)
    except CandidateError as exc:
        raise CandidateError(f"{label} candidate validation failed: {exc}") from exc
    return cases


def _validate_promotion_plan(
    plan: dict,
    active: dict,
    v5_lines: list[dict],
    v6_payload: bytes,
    v6_manifest: dict,
    v6_cases: list,
) -> dict[str, str]:
    if plan.get("plan_schema") != 1:
        raise CandidateError("promotion plan schema must be 1")
    if plan.get("source_truth_version") != GT_H3B_V5_VERSION:
        raise CandidateError("promotion plan source truth_version mismatch")
    if plan.get("source_dataset_file") != GT_H3B_V5_DATASET:
        raise CandidateError("promotion plan source dataset mismatch")
    if plan.get("source_dataset_hash") != GT_H3B_V5_DATASET_HASH:
        raise CandidateError("promotion plan source dataset hash mismatch")
    if plan.get("target_truth_version") != GT_H3B_V6_VERSION:
        raise CandidateError("promotion plan target truth_version mismatch")
    if plan.get("operation_summary") != GT_H3B_PLAN_SUMMARY:
        raise CandidateError("promotion plan operation_summary mismatch")

    operations = plan.get("operations")
    if not isinstance(operations, list):
        raise CandidateError("promotion plan operations must be a list")
    if Counter(str(op.get("op")) for op in operations if isinstance(op, dict)) != Counter(
        {"KEEP": 110, "DROP": 15, "ADD": 15}
    ):
        raise CandidateError("promotion plan operation set/count mismatch")
    if any(not isinstance(op, dict) for op in operations):
        raise CandidateError("promotion plan contains a non-object operation")
    if any(op.get("op") == "REPLACE" for op in operations):
        raise CandidateError("promotion plan must not contain REPLACE operations")

    try:
        rebuilt_lines = _build_rebuild_lines(active, v5_lines, plan, GT_H3B_V6_VERSION)
        rebuilt_cases = _validate_promotion_compiled_docs(
            rebuilt_lines, GT_H3B_V6_VERSION, "rebuilt v6"
        )
    except CandidateError as exc:
        raise CandidateError(f"promotion plan rebuild failed: {exc}") from exc
    rebuilt_payload = _jsonl_bytes(rebuilt_lines)
    if rebuilt_payload != v6_payload:
        raise CandidateError(
            "promotion plan does not reproduce the existing v6 dataset bytes; "
            "DROP/ADD set or case content drifted"
        )
    rebuilt_manifest = _manifest_for_cases(
        GT_H3B_V6_VERSION,
        GT_H3B_V6_DATASET,
        GT_H3B_V6_DATASET_HASH,
        rebuilt_cases,
    )
    if rebuilt_manifest != v6_manifest:
        raise CandidateError("promotion plan rebuild statistics do not match v6 manifest")
    add_source_by_new_id: dict[str, str] = {}
    for op in operations:
        if op.get("op") != "ADD":
            continue
        case = op.get("case")
        if not isinstance(case, dict):
            raise CandidateError("promotion plan ADD operation is missing its case object")
        new_id = str(op.get("golden_case_id", ""))
        lineage = case.get("lineage")
        if not isinstance(lineage, dict) or not str(lineage.get("source_case_id", "")):
            raise CandidateError(f"promotion plan ADD {new_id}: source lineage is missing")
        source_id = str(lineage["source_case_id"])
        if new_id in add_source_by_new_id:
            raise CandidateError(f"promotion plan contains duplicate ADD case {new_id}")
        add_source_by_new_id[new_id] = source_id
    return add_source_by_new_id


def _validate_promotion_carry_forward(
    rows: list[dict],
    v5_lines: list[dict],
    v6_lines: list[dict],
    add_source_by_new_id: dict[str, str],
) -> tuple[int, int]:
    if len(rows) != 125:
        raise CandidateError("promotion carry-forward ledger must contain 125 rows")
    v5_by_id = {str(doc["golden_case_id"]): doc for doc in v5_lines}
    v6_by_id = {str(doc["golden_case_id"]): doc for doc in v6_lines}
    if len(v5_by_id) != len(v5_lines) or len(v6_by_id) != len(v6_lines):
        raise CandidateError("promotion carry-forward inputs contain duplicate case IDs")
    by_old: dict[str, dict] = {}
    for row in rows:
        old_id = str(row.get("old_case_id", ""))
        if not old_id or old_id in by_old:
            raise CandidateError(f"promotion carry-forward duplicate old ID {old_id}")
        by_old[old_id] = row
    if set(by_old) != set(v5_by_id):
        raise CandidateError("promotion carry-forward old ID coverage mismatch")

    added_by_source: dict[str, str] = {}
    for new_id, source_id in add_source_by_new_id.items():
        if source_id in added_by_source:
            raise CandidateError(f"promotion plan maps one source to multiple ADD cases: {source_id}")
        added_by_source[source_id] = new_id
    expected_map: dict[str, str] = {}
    for old_id in v5_by_id:
        if old_id in v6_by_id:
            expected_map[old_id] = old_id
        elif old_id in added_by_source:
            expected_map[old_id] = added_by_source[old_id]
        else:
            raise CandidateError(f"promotion carry-forward has no replacement mapping for {old_id}")
    if set(expected_map.values()) != set(v6_by_id):
        raise CandidateError("promotion carry-forward new ID coverage mismatch")

    eligible_count = 0
    ineligible_count = 0
    for old_id, old_doc in v5_by_id.items():
        row = by_old[old_id]
        new_id = expected_map[old_id]
        if row.get("ledger_schema") != 2 or row.get("transition") != "v5_to_v6":
            raise CandidateError(f"promotion carry-forward {old_id}: schema/transition mismatch")
        if row.get("new_case_id") != new_id:
            raise CandidateError(f"promotion carry-forward {old_id}: new case ID mismatch")
        if row.get("prior_decision") != "APPROVE":
            raise CandidateError(f"promotion carry-forward {old_id}: prior decision mismatch")
        new_doc = v6_by_id[new_id]
        old_identity = review_identity_hash_for_doc(old_doc)
        new_identity = review_identity_hash_for_doc(new_doc)
        if row.get("old_review_identity_hash") != old_identity:
            raise CandidateError(f"promotion carry-forward {old_id}: old identity hash mismatch")
        if row.get("new_review_identity_hash") != new_identity:
            raise CandidateError(f"promotion carry-forward {old_id}: new identity hash mismatch")
        if row.get("old_dataset_case_semantic_hash") != old_doc.get("case_semantic_hash"):
            raise CandidateError(f"promotion carry-forward {old_id}: old dataset hash mismatch")
        if row.get("new_dataset_case_semantic_hash") != new_doc.get("case_semantic_hash"):
            raise CandidateError(f"promotion carry-forward {old_id}: new dataset hash mismatch")
        eligible = old_id == new_id and old_identity == new_identity
        if row.get("carry_forward_eligible") is not eligible:
            raise CandidateError(f"promotion carry-forward {old_id}: eligibility was not recomputed")
        if row.get("new_review_required") is not (not eligible):
            raise CandidateError(f"promotion carry-forward {old_id}: review-required mismatch")
        if eligible:
            eligible_count += 1
        else:
            ineligible_count += 1
    if (eligible_count, ineligible_count) != (110, 15):
        raise CandidateError(
            "promotion carry-forward counts must be recomputed as 110 eligible / 15 ineligible"
        )
    return eligible_count, ineligible_count


def _validate_promotion_audit(rows: list[dict], v6_lines: list[dict]) -> dict[str, int]:
    if len(rows) != 50:
        raise CandidateError("GT-H3R2 transition audit must contain 50 rows")
    st_ids = {
        str(doc["golden_case_id"]) for doc in v6_lines if doc.get("event_class") == "ST_TRANSITION"
    }
    audit_ids = {str(row.get("golden_case_id")) for row in rows}
    if audit_ids != st_ids:
        raise CandidateError("GT-H3R2 audit ID set does not match v6 ST set")
    problems = transition_audit_publication_gate(rows, v6_lines)
    if problems:
        detail = "; ".join(problems[:5])
        raise CandidateError(f"GT-H3R2 transition audit failed closed: {detail}")
    if Counter(str(row.get("audit_status")) for row in rows) != Counter({"PASS": 50}):
        raise CandidateError("GT-H3R2 audit status must be PASS=50")
    if not all(row.get("transition_valid") is True for row in rows):
        raise CandidateError("GT-H3R2 audit contains an invalid transition")
    if not all(
        row.get(field, {}).get("status") == "OFFICIAL_SOURCE_REVIEWED"
        for row in rows
        for field in ("pre_state_official_evidence", "effective_state_official_evidence")
    ):
        raise CandidateError("GT-H3R2 audit evidence is not fully official-source-reviewed")
    return {"PASS": 50}


def cmd_promote_existing(
    requested_truth_version: str,
    plan_path: Path,
    carry_forward_path: Path,
    transition_audit_path: Path | None = None,
) -> None:
    """Promote only the exact, already-staged v6 candidate; never rebuild it."""
    if requested_truth_version != GT_H3B_V6_VERSION:
        raise CandidateError(
            f"promote-existing only accepts the authorized target {GT_H3B_V6_VERSION}"
        )

    v4_manifest_path = GOLDEN_ROOT / GT_H3B_V4_MANIFEST
    v5_manifest_path = GOLDEN_ROOT / GT_H3B_V5_MANIFEST
    v6_manifest_path = GOLDEN_ROOT / GT_H3B_V6_MANIFEST
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    v4_dataset_path = GOLDEN_ROOT / GT_H3B_V4_DATASET
    v5_dataset_path = GOLDEN_ROOT / GT_H3B_V5_DATASET
    v6_dataset_path = GOLDEN_ROOT / GT_H3B_V6_DATASET

    v4_manifest_bytes = _assert_file_hash(
        v4_manifest_path, GT_H3B_V4_MANIFEST_SHA256, "v4 manifest"
    )
    _ = v4_manifest_bytes
    _assert_file_hash(v4_dataset_path, GT_H3B_V4_DATASET_HASH, "v4 dataset")
    v5_manifest_bytes = _assert_file_hash(
        v5_manifest_path, GT_H3B_V5_MANIFEST_SHA256, "v5 manifest"
    )
    v5_payload = _assert_file_hash(v5_dataset_path, GT_H3B_V5_DATASET_HASH, "v5 dataset")
    v6_manifest_bytes = _assert_file_hash(
        v6_manifest_path, GT_H3B_V6_MANIFEST_SHA256, "v6 manifest"
    )
    v6_payload = _assert_file_hash(v6_dataset_path, GT_H3B_V6_DATASET_HASH, "v6 dataset")
    try:
        active_bytes = active_path.read_bytes()
    except OSError as exc:
        raise CandidateError(f"cannot read ACTIVE pointer {active_path}: {exc}") from exc
    if active_bytes == v5_manifest_bytes:
        active_state = "v5"
    elif active_bytes == v6_manifest_bytes:
        active_state = "v6"
    else:
        raise CandidateError(
            "ACTIVE pointer is neither the exact authorized v5 manifest nor the exact v6 manifest"
        )

    v4_manifest = _read_json_object(v4_manifest_path, "v4 manifest")
    if (
        v4_manifest.get("truth_version") != GT_H3B_V4_VERSION
        or v4_manifest.get("dataset_file") != GT_H3B_V4_DATASET
        or v4_manifest.get("dataset_hash") != GT_H3B_V4_DATASET_HASH
    ):
        raise CandidateError("v4 manifest metadata does not match the immutable baseline")

    v5_manifest = _read_json_object(v5_manifest_path, "v5 manifest")
    if (
        v5_manifest.get("truth_version") != GT_H3B_V5_VERSION
        or v5_manifest.get("dataset_file") != GT_H3B_V5_DATASET
        or v5_manifest.get("dataset_hash") != GT_H3B_V5_DATASET_HASH
    ):
        raise CandidateError("v5 manifest metadata does not match the immutable baseline")
    if active_state == "v5" and active_bytes != v5_manifest_bytes:
        raise CandidateError("ACTIVE v5 pointer is not byte-equivalent to truth_manifest_v5.json")
    if active_state == "v6" and active_bytes != v6_manifest_bytes:
        raise CandidateError("ACTIVE v6 pointer is not byte-equivalent to truth_manifest_v6.json")

    v5_lines = _jsonl_objects_from_bytes(v5_payload, "v5 dataset")
    v5_cases = _validate_promotion_compiled_docs(v5_lines, GT_H3B_V5_VERSION, "v5")
    _validate_promotion_stats(v5_manifest, v5_cases, "v5")
    try:
        bound_v5_cases, bound_v5_manifest = GoldenTruthStore(GOLDEN_ROOT).load_bound(
            GT_H3B_V5_DATASET,
            GT_H3B_V5_VERSION,
            GT_H3B_V5_DATASET_HASH,
        )
    except (GoldenTruthError, OSError, ValueError) as exc:
        raise CandidateError(f"v5 Golden loader rejected immutable baseline: {exc}") from exc
    if len(bound_v5_cases) != len(v5_cases) or bound_v5_manifest.case_count != 125:
        raise CandidateError("v5 Golden loader statistics do not match the immutable baseline")

    v6_manifest = _read_json_object(v6_manifest_path, "v6 manifest")
    if (
        v6_manifest.get("truth_version") != GT_H3B_V6_VERSION
        or v6_manifest.get("dataset_file") != GT_H3B_V6_DATASET
        or v6_manifest.get("dataset_hash") != GT_H3B_V6_DATASET_HASH
    ):
        raise CandidateError("v6 manifest metadata does not match the authorized baseline")
    try:
        bound_v6_cases, bound_v6_manifest = GoldenTruthStore(GOLDEN_ROOT).load_bound(
            GT_H3B_V6_DATASET,
            GT_H3B_V6_VERSION,
            GT_H3B_V6_DATASET_HASH,
        )
    except (GoldenTruthError, OSError, ValueError) as exc:
        raise CandidateError(f"v6 Golden loader rejected existing candidate: {exc}") from exc
    v6_lines = _jsonl_objects_from_bytes(v6_payload, "v6 dataset")
    v6_cases = _validate_promotion_compiled_docs(v6_lines, GT_H3B_V6_VERSION, "v6")
    if len(bound_v6_cases) != len(v6_cases):
        raise CandidateError("v6 JSONL and Golden loader row counts differ")
    for doc, case in zip(v6_lines, bound_v6_cases, strict=True):
        if doc.get("golden_case_id") != case.golden_case_id:
            raise CandidateError("v6 JSONL and Golden loader case order differs")
    _validate_promotion_stats(v6_manifest, v6_cases, "v6")
    for field in (
        "case_count",
        "counts_by_type",
        "review_summary",
        "distinct_events",
        "distinct_securities",
        "st_add_events",
        "st_remove_events",
        "distinct_delisted_securities",
    ):
        if getattr(bound_v6_manifest, field) != v6_manifest.get(field):
            raise CandidateError(f"v6 manifest {field} differs from Golden loader recomputation")
    pointer_bytes = json.dumps(v6_manifest, ensure_ascii=False, indent=2).encode("utf-8")
    if pointer_bytes != v6_manifest_bytes:
        raise CandidateError("v6 manifest bytes are not valid atomic ACTIVE pointer bytes")

    plan = _read_json_object(plan_path, "promotion plan")
    add_source_by_new_id = _validate_promotion_plan(
        plan,
        v5_manifest,
        v5_lines,
        v6_payload,
        v6_manifest,
        v6_cases,
    )
    carry_rows = _read_jsonl_objects(carry_forward_path, "carry-forward ledger")
    _validate_promotion_carry_forward(
        carry_rows,
        v5_lines,
        v6_lines,
        add_source_by_new_id,
    )
    audit_path = transition_audit_path or DEFAULT_TRANSITION_AUDIT
    audit_rows = _read_jsonl_objects(audit_path, "GT-H3R2 transition audit")
    _validate_promotion_audit(audit_rows, v6_lines)

    if active_state == "v6":
        print(f"ACTIVE already points to {GT_H3B_V6_VERSION}; promotion no-op")
        return

    try:
        _atomic_active_pointer(v6_manifest)
    except (OSError, ValueError) as exc:
        raise CandidateError(f"ACTIVE pointer promotion failed atomically: {exc}") from exc
    try:
        published_bytes = active_path.read_bytes()
    except OSError as exc:
        raise CandidateError(f"cannot verify promoted ACTIVE pointer: {exc}") from exc
    if published_bytes != v6_manifest_bytes:
        raise CandidateError("promoted ACTIVE pointer is not byte-equivalent to v6 manifest")
    print(f"promoted existing candidate to ACTIVE: {GT_H3B_V6_VERSION}")

def _preflight_create_only(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() != data:
        raise CandidateError(f"versioned file {path.name} already exists with different bytes")


def _create_only_write(path: Path, data: bytes) -> None:
    """Create a versioned file without ever overwriting different bytes."""
    _preflight_create_only(path, data)
    if path.exists():
        return
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_active_pointer(manifest: dict) -> None:
    """Publish ACTIVE only after all immutable outputs are validated."""
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    tmp = active_path.with_name(f".{active_path.name}.{uuid4().hex}.tmp")
    data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        tmp.write_bytes(data)
        tmp.replace(active_path)
    finally:
        tmp.unlink(missing_ok=True)


def _version_number(version: object) -> int:
    prefix = str(version).split("-", 1)[0]
    if not prefix.startswith("v") or not prefix[1:].isdigit():
        raise CandidateError(f"invalid truth_version {version!r}")
    return int(prefix[1:])


def _next_truth_version(old_version: str) -> str:
    return f"v{_version_number(old_version) + 1}-candidate-{datetime.now(UTC).strftime('%Y%m%d')}"


def _compiled_at_for_version(truth_version: str) -> str:
    date_text = truth_version.split("-")[-1]
    if len(date_text) == 8 and date_text.isdigit():
        return f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}T00:00:00+00:00"
    return datetime.now(UTC).isoformat()


def _prepare_compiled_doc(doc: dict, truth_version: str) -> dict:
    normalized = copy.deepcopy(doc)
    normalized.setdefault("event_subtype", "")
    normalized.setdefault("event_effective_date", "")
    normalized.setdefault("compiled_by", "candidate-rebuild")
    normalized.setdefault("compiled_at", _compiled_at_for_version(truth_version))
    normalized["review_status"] = "COMPILED"
    for field in REVIEW_PROVENANCE_FIELDS:
        normalized[field] = ""
    normalized["truth_version"] = truth_version
    normalized["case_semantic_hash"] = _semantic_hash(normalized)
    return normalized


def _validate_output_documents(lines: list[dict], truth_version: str) -> list:
    """Validate every output row; structural identities are not row keys."""
    known_ids: set[str] = set()
    for doc in lines:
        _validate_candidate(doc, known_ids)
        case_id = str(doc["golden_case_id"])
        if doc.get("truth_version") != truth_version:
            raise CandidateError(f"candidate {case_id}: wrong output truth_version")
        if doc.get("review_status") != "COMPILED":
            raise CandidateError(f"candidate {case_id}: rebuild output must be COMPILED")
        if any(str(doc.get(field, "")) for field in REVIEW_PROVENANCE_FIELDS):
            raise CandidateError(f"candidate {case_id}: rebuild output contains review provenance")
        if not doc.get("compiled_by") or not doc.get("compiled_at"):
            raise CandidateError(f"candidate {case_id}: compiled provenance is incomplete")
        if doc.get("case_semantic_hash") != _semantic_hash(doc):
            raise CandidateError(f"candidate {case_id}: case_semantic_hash mismatch")
        known_ids.add(case_id)

    payload = _jsonl_bytes(lines)
    try:
        cases = cases_from_dataset_bytes(payload, truth_version)
    except GoldenTruthError as exc:
        raise CandidateError(f"rebuilt dataset failed loader self-validation: {exc}") from exc

    return cases


def _validate_transition_audit_for_publication(
    lines: list[dict],
    truth_version: str,
    audit_path: Path | None,
) -> None:
    """Fail closed on ST semantics for v6+ candidates; v5 remains immutable."""
    if _version_number(truth_version) < 6:
        return
    st_lines = [line for line in lines if line.get("event_class") == "ST_TRANSITION"]
    if not st_lines:
        return
    resolved_audit_path = audit_path or DEFAULT_TRANSITION_AUDIT
    if not resolved_audit_path.is_file():
        raise CandidateError(
            "GT-H3R2 ST transition audit is required before publishing v6+: "
            f"missing {resolved_audit_path}"
        )
    try:
        audit_rows = [
            json.loads(line)
            for line in resolved_audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError(
            f"cannot read GT-H3R2 ST transition audit {resolved_audit_path}: {exc}"
        ) from exc
    problems = transition_audit_publication_gate(audit_rows, lines)
    if problems:
        detail = "; ".join(problems[:8])
        more = " ..." if len(problems) > 8 else ""
        raise CandidateError("GT-H3R2 ST transition audit failed closed: " + detail + more)


def _jsonl_bytes(lines: list[dict]) -> bytes:
    payload = "".join(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n" for doc in lines)
    return payload.encode("utf-8")


def _manifest_for_cases(
    truth_version: str,
    dataset_file: str,
    dataset_hash: str,
    cases: list,
) -> dict:
    stats = recompute_manifest_statistics(cases)
    return {
        "manifest_schema": 2,
        "truth_version": truth_version,
        "dataset_file": dataset_file,
        "dataset_hash": dataset_hash,
        "case_count": stats["case_count"],
        "counts_by_type": stats["counts_by_type"],
        "review_summary": stats["review_summary"],
        "distinct_events": stats["distinct_events"],
        "distinct_securities": stats["distinct_securities"],
        "st_add_events": stats["st_add_events"],
        "st_remove_events": stats["st_remove_events"],
        "distinct_delisted_securities": stats["distinct_delisted_securities"],
    }


def _load_rebuild_plan(plan_path: Path) -> dict:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError(f"cannot read rebuild plan {plan_path}: {exc}") from exc
    if not isinstance(plan, dict):
        raise CandidateError("rebuild plan must be a JSON object")
    if not isinstance(plan.get("operations"), list) or not plan["operations"]:
        raise CandidateError("rebuild plan requires a non-empty operations list")
    return plan


def _build_rebuild_lines(
    active: dict,
    source_lines: list[dict],
    plan: dict,
    truth_version: str,
) -> list[dict]:
    source_version = str(active["truth_version"])
    expected_version = plan.get("source_truth_version")
    expected_hash = plan.get("source_dataset_hash")
    if expected_version != source_version:
        raise CandidateError(
            "rebuild source_truth_version "
            f"{expected_version!r} does not match active {source_version!r}"
        )
    if expected_hash != active.get("dataset_hash"):
        raise CandidateError("rebuild source_dataset_hash does not match the active dataset")
    if plan.get("source_dataset_file") not in (None, active.get("dataset_file")):
        raise CandidateError("rebuild source_dataset_file does not match the active dataset")

    source_by_id = {str(doc["golden_case_id"]): doc for doc in source_lines}
    if len(source_by_id) != len(source_lines):
        raise CandidateError("active dataset contains duplicate golden_case_id")
    source_ids = set(source_by_id)
    for doc in source_lines:
        if doc.get("review_status") != "COMPILED":
            raise CandidateError("rebuild source must contain only COMPILED cases")
        if any(str(doc.get(field, "")) for field in REVIEW_PROVENANCE_FIELDS):
            raise CandidateError("rebuild source contains reviewer provenance")

    output: list[dict] = []
    output_ids: set[str] = set()
    seen_source_ids: set[str] = set()
    for index, raw in enumerate(plan["operations"], start=1):
        if not isinstance(raw, dict):
            raise CandidateError(f"rebuild operation {index} must be an object")
        op = str(raw.get("op", "")).upper()
        if op == "ADD":
            case = raw.get("case")
            if not isinstance(case, dict):
                raise CandidateError(f"rebuild operation {index}: ADD requires case object")
            case_id = case.get("golden_case_id")
            if raw.get("golden_case_id") not in (None, case_id):
                raise CandidateError(f"rebuild operation {index}: ADD case ID mismatch")
            if not isinstance(case_id, str) or not case_id:
                raise CandidateError(f"rebuild operation {index}: ADD requires case.golden_case_id")
            _validate_candidate(case, source_ids | output_ids)
            normalized = _prepare_compiled_doc(case, truth_version)
            output.append(normalized)
            output_ids.add(case_id)
            continue

        case_id = raw.get("golden_case_id")
        if not isinstance(case_id, str) or not case_id:
            raise CandidateError(f"rebuild operation {index}: {op} requires golden_case_id")
        if op not in {"KEEP", "REPLACE", "DROP"}:
            raise CandidateError(f"rebuild operation {index}: unknown op {op!r}")
        if case_id not in source_by_id:
            raise CandidateError(f"rebuild operation {index}: unknown source case {case_id}")
        if case_id in seen_source_ids:
            raise CandidateError(f"rebuild source case {case_id}: duplicate operation")
        seen_source_ids.add(case_id)

        if op == "DROP":
            continue
        if op == "KEEP":
            normalized = _prepare_compiled_doc(source_by_id[case_id], truth_version)
        else:
            replacement = raw.get("case")
            if not isinstance(replacement, dict):
                raise CandidateError(f"rebuild operation {index}: REPLACE requires case object")
            replacement_id = replacement.get("golden_case_id")
            if replacement_id != case_id and raw.get("allow_rekey") is not True:
                raise CandidateError(
                    f"rebuild operation {index}: REPLACE case ID mismatch; "
                    "set allow_rekey=true only for an explicit "
                    "source-to-replacement identity change"
                )
            _validate_candidate(replacement, (source_ids - {case_id}) | output_ids)
            normalized = _prepare_compiled_doc(replacement, truth_version)
        output_id = str(normalized["golden_case_id"])
        if output_id in output_ids:
            raise CandidateError(f"rebuild output duplicate golden_case_id {output_id}")
        output.append(normalized)
        output_ids.add(output_id)

    missing = sorted(source_ids - seen_source_ids)
    if missing:
        raise CandidateError(
            "rebuild plan must specify exactly one KEEP/REPLACE/DROP operation "
            f"for every source case; missing {missing[:5]}"
        )
    return output


def cmd_rebuild(
    plan_path: Path,
    requested_truth_version: str | None,
    transition_audit_path: Path | None = None,
) -> None:
    """Build and publish one fully prevalidated candidate version."""
    active, source_lines = _load_active_cases()
    plan = _load_rebuild_plan(plan_path)
    plan_truth_version = plan.get("target_truth_version")
    if plan_truth_version is not None and requested_truth_version not in (None, plan_truth_version):
        raise CandidateError("CLI --truth-version conflicts with plan target_truth_version")
    truth_version = str(
        requested_truth_version
        or plan_truth_version
        or _next_truth_version(active["truth_version"])
    )
    if "/" in truth_version or "\\" in truth_version:
        raise CandidateError("target truth_version may not contain a path separator")
    if _version_number(truth_version) <= _version_number(str(active["truth_version"])):
        raise CandidateError("target truth_version must be newer than the active version")

    lines = _build_rebuild_lines(active, source_lines, plan, truth_version)
    cases = _validate_output_documents(lines, truth_version)
    _validate_transition_audit_for_publication(lines, truth_version, transition_audit_path)
    dataset_file = f"golden_cases_{truth_version.split('-', 1)[0]}.jsonl"
    manifest_file = f"truth_manifest_{truth_version.split('-', 1)[0]}.json"
    payload = _jsonl_bytes(lines)
    dataset_hash = hashlib.sha256(payload).hexdigest()
    manifest = _manifest_for_cases(truth_version, dataset_file, dataset_hash, cases)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    # All conflict checks happen before creating either immutable output or
    # touching ACTIVE.  The case loader above is the in-memory bound
    # self-validation used again by production load_bound().
    dataset_path = GOLDEN_ROOT / dataset_file
    manifest_path = GOLDEN_ROOT / manifest_file
    _preflight_create_only(dataset_path, payload)
    _preflight_create_only(manifest_path, manifest_bytes)
    _create_only_write(dataset_path, payload)
    _create_only_write(manifest_path, manifest_bytes)
    _atomic_active_pointer(manifest)
    print(f"rebuilt dataset version: {truth_version} ({len(cases)} cases)")


def cmd_add_case(input_path: Path) -> None:
    """Stage new COMPILED candidates into candidate_staging.jsonl."""
    _, lines = _load_active_cases()
    known = {doc["golden_case_id"] for doc in lines}
    if CANDIDATE_STAGING.exists():
        staged = [
            json.loads(line)
            for line in CANDIDATE_STAGING.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        known.update(doc["golden_case_id"] for doc in staged)
    else:
        staged = []
    new_entries = [
        json.loads(line)
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for doc in new_entries:
        _validate_candidate(doc, known)
        known.add(doc["golden_case_id"])
        doc.setdefault("source_artifact_ref", "")
        doc.setdefault("source_artifact_kind", "")
        doc.setdefault("source_retrieved_at", "")
        doc.setdefault("source_artifact_hash", "")
        doc.setdefault("reviewed_by", "")
        doc.setdefault("reviewed_at", "")
        doc.setdefault("review_note", "")
        doc["review_status"] = "COMPILED"
        doc.setdefault("event_subtype", "")
        doc.setdefault("event_effective_date", "")
        doc["compiled_by"] = "candidate-augmentation"
        doc["compiled_at"] = datetime.now(UTC).isoformat()
        doc["truth_version"] = "staged"
        doc["case_semantic_hash"] = _semantic_hash(doc)
        staged.append(doc)
    payload = "".join(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n" for doc in staged)
    CANDIDATE_STAGING.write_text(payload, encoding="utf-8", newline="\n")
    print(f"staged: {len(new_entries)} new candidates (total staged: {len(staged)})")


def cmd_validate() -> None:
    """Validate staged candidates against the active dataset."""
    _, lines = _load_active_cases()
    known = {doc["golden_case_id"] for doc in lines}
    if not CANDIDATE_STAGING.exists():
        print("no staged candidates")
        return
    staged = [
        json.loads(line)
        for line in CANDIDATE_STAGING.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for doc in staged:
        _validate_candidate(doc, known)
        known.add(doc["golden_case_id"])
        if doc.get("case_semantic_hash") != _semantic_hash(doc):
            raise CandidateError(
                f"candidate {doc['golden_case_id']}: staged semantic hash mismatch"
            )
    st_ids = {
        (d["provider_symbol"], d.get("event_effective_date", ""), d.get("event_subtype", ""))
        for d in staged
        if d["event_class"] == "ST_TRANSITION"
    }
    print(f"staged candidates valid: {len(staged)}; distinct ST identities: {len(st_ids)}")


def cmd_build_version() -> None:
    """Reject the pre-GT-H1 implicit append bypass."""
    raise CandidateError(
        "build-version is disabled because implicit append cannot repair legacy "
        "structural truth; use rebuild --plan with explicit KEEP/REPLACE/DROP/ADD"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden candidate compilation and rebuild")
    parser.add_argument("--root", type=Path, help="golden root override (tests)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("build-version")
    add = sub.add_parser("add-case")
    add.add_argument("--input", type=Path, required=True)
    rebuild = sub.add_parser("rebuild")
    rebuild.add_argument("--plan", type=Path, required=True)
    rebuild.add_argument("--truth-version")
    rebuild.add_argument("--transition-audit", type=Path)
    promote = sub.add_parser("promote-existing")
    promote.add_argument("--truth-version", required=True)
    promote.add_argument("--plan", type=Path, required=True)
    promote.add_argument("--carry-forward", type=Path, required=True)
    promote.add_argument("--transition-audit", type=Path)
    args = parser.parse_args()

    global GOLDEN_ROOT, CANDIDATE_STAGING
    if args.root:
        GOLDEN_ROOT = Path(args.root)
        CANDIDATE_STAGING = GOLDEN_ROOT / "candidate_staging.jsonl"

    if args.command == "add-case":
        cmd_add_case(args.input)
    elif args.command == "validate":
        cmd_validate()
    elif args.command == "build-version":
        cmd_build_version()
    elif args.command == "rebuild":
        cmd_rebuild(args.plan, args.truth_version, args.transition_audit)
    elif args.command == "promote-existing":
        cmd_promote_existing(
            args.truth_version,
            args.plan,
            args.carry_forward,
            args.transition_audit,
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CandidateError, GoldenTruthError) as exc:
        print(f"candidate error: {exc}", file=sys.stderr)
        sys.exit(2)
