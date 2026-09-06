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
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.golden_store import (  # noqa: E402
    GoldenTruthError,
    StructuralEventError,
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    semantic_hash_for_doc,
    validate_structural_event_fields,
)

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
CANDIDATE_STAGING = GOLDEN_ROOT / "candidate_staging.jsonl"

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


def cmd_rebuild(plan_path: Path, requested_truth_version: str | None) -> None:
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
        cmd_rebuild(args.plan, args.truth_version)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CandidateError, GoldenTruthError) as exc:
        print(f"candidate error: {exc}", file=sys.stderr)
        sys.exit(2)
