"""Golden Candidate Augmentation Workflow (audit R4A2-P0-03, sections 9-12).

Golden lifecycle (audit section 11):
    Candidate Compilation (compile_vN.py)
        -> Candidate AUGMENTATION (this tool: add-case / validate / build)
        -> Human Review (review.py)
        -> Reviewed Version
        -> Formal Run Binding

Responsibilities (audit section 12):
- candidate workflow ADDS/MODIFIES COMPILED candidates
- review workflow VERIFIES candidates and binds external artifacts
- review never creates truth events; candidate never marks REVIEWED

Usage:
    python scripts/golden/candidate.py add-case --input new_events.jsonl
    python scripts/golden/candidate.py validate
    python scripts/golden/candidate.py build-version
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


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
    "BJ_CODE_MIGRATION",
    "NEGATIVE_SAMPLE",
}
VALID_ST_SUBTYPES = {"ST_ADD", "ST_REMOVE", "STAR_ST_ADD", "STAR_ST_REMOVE"}


class CandidateError(RuntimeError):
    """Candidate augmentation contract violation."""


def _semantic_hash(doc: dict) -> str:
    statement = json.dumps(
        {
            "golden_case_id": doc["golden_case_id"],
            "case_type": doc["case_type"],
            "provider_symbol": doc["provider_symbol"],
            "trade_date": doc["trade_date"],
            "expected_fields": doc["expected_fields"],
            "truth_source": doc["truth_source"],
            "source_ref": doc["source_ref"],
            "source_artifact_hash": doc.get("source_artifact_hash", ""),
            "truth_version": doc["truth_version"],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _validate_candidate(doc: dict, known_ids: set[str]) -> None:
    missing = [f for f in REQUIRED_FIELDS if not doc.get(f)]
    if missing:
        msg = f"candidate {doc.get('golden_case_id', '?')}: missing fields {missing}"
        raise CandidateError(msg)
    if doc["golden_case_id"] in known_ids:
        msg = f"candidate {doc['golden_case_id']}: duplicate golden_case_id"
        raise CandidateError(msg)
    if doc["event_class"] not in VALID_EVENT_CLASSES:
        msg = f"candidate {doc['golden_case_id']}: unknown event_class {doc['event_class']!r}"
        raise CandidateError(msg)
    subtype = str(doc.get("event_subtype", ""))
    if doc["event_class"] == "ST_TRANSITION" and subtype not in VALID_ST_SUBTYPES:
        msg = (
            f"candidate {doc['golden_case_id']}: ST_TRANSITION requires "
            f"event_subtype in {sorted(VALID_ST_SUBTYPES)}"
        )
        raise CandidateError(msg)
    if doc["event_class"] == "ST_TRANSITION" and not doc.get("event_effective_date"):
        msg = (
            f"candidate {doc['golden_case_id']}: ST_TRANSITION requires "
            "event_effective_date (structural event identity)"
        )
        raise CandidateError(msg)
    if doc.get("review_status") not in (None, "COMPILED"):
        msg = (
            f"candidate {doc['golden_case_id']}: augmentation may only add "
            "COMPILED candidates (review is the review workflow's job)"
        )
        raise CandidateError(msg)


def _load_active_cases() -> tuple[dict, list[dict]]:
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    active = json.loads(active_path.read_text(encoding="utf-8"))
    dataset = GOLDEN_ROOT / str(active["dataset_file"])
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != active["dataset_hash"]:
        msg = "active dataset hash mismatch"
        raise CandidateError(msg)
    lines = [json.loads(x) for x in dataset.read_text(encoding="utf-8").splitlines() if x.strip()]
    return active, lines


def _create_only_write(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() == data:
            return
        msg = f"versioned file {path.name} already exists with different bytes"
        raise CandidateError(msg)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    Path(tmp).replace(Path(path))


def _write_new_version(lines: list[dict], old_active: dict) -> str:
    old_version = str(old_active["truth_version"])
    num = "".join(ch for ch in old_version.split("-")[0][1:] if ch.isdigit()) or "1"
    truth_version = f"v{int(num) + 1}-candidate-{datetime.now(UTC).strftime('%Y%m%d')}"
    for doc in lines:
        doc["truth_version"] = truth_version
        doc["case_semantic_hash"] = _semantic_hash(doc)
    dataset_file = f"golden_cases_{truth_version.split('-')[0]}.jsonl"
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in lines)
    dataset_path = GOLDEN_ROOT / dataset_file
    _create_only_write(dataset_path, payload.encode("utf-8"))
    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

    counts: dict[str, int] = {}
    review: dict[str, int] = {}
    events: dict[str, set[str]] = {}
    for c in lines:
        counts[c["case_type"]] = counts.get(c["case_type"], 0) + 1
        review[c["review_status"]] = review.get(c["review_status"], 0) + 1
        events.setdefault(c["event_class"], set()).add(c["event_id"])
    manifest = {
        "truth_version": truth_version,
        "dataset_file": dataset_file,
        "dataset_hash": dataset_hash,
        "case_count": len(lines),
        "counts_by_type": counts,
        "review_summary": review,
        "distinct_events": {k: len(v) for k, v in events.items()},
    }
    _create_only_write(
        GOLDEN_ROOT / f"truth_manifest_{truth_version.split('-')[0]}.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    staging = GOLDEN_ROOT / "truth_manifest.json.tmp"
    staging.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    staging.replace(GOLDEN_ROOT / "truth_manifest.json")
    return truth_version


def cmd_add_case(input_path: Path) -> None:
    """Stage new COMPILED candidates into candidate_staging.jsonl."""
    active, lines = _load_active_cases()
    known = {doc["golden_case_id"] for doc in lines}
    if CANDIDATE_STAGING.exists():
        staged = [
            json.loads(x)
            for x in CANDIDATE_STAGING.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        known.update(doc["golden_case_id"] for doc in staged)
    else:
        staged = []
    new_entries = [
        json.loads(x)
        for x in Path(input_path).read_text(encoding="utf-8").splitlines()
        if x.strip()
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
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in staged)
    CANDIDATE_STAGING.write_text(payload, encoding="utf-8", newline="\n")
    print(f"staged: {len(new_entries)} new candidates (total staged: {len(staged)})")


def cmd_validate() -> None:
    """Validate the staged candidates against the active dataset."""
    active, lines = _load_active_cases()
    known = {doc["golden_case_id"] for doc in lines}
    if not CANDIDATE_STAGING.exists():
        print("no staged candidates")
        return
    staged = [
        json.loads(x)
        for x in CANDIDATE_STAGING.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    for doc in staged:
        _validate_candidate(doc, known)
        known.add(doc["golden_case_id"])
    # structural event-identity sanity: distinct ST identities among staged
    st_ids = {
        (d["provider_symbol"], d.get("event_effective_date", ""), d.get("event_subtype", ""))
        for d in staged
        if d["event_class"] == "ST_TRANSITION"
    }
    print(f"staged candidates valid: {len(staged)}; distinct ST identities: {len(st_ids)}")


def cmd_build_version() -> None:
    """Merge staged candidates into a NEW append-only dataset version."""
    active, lines = _load_active_cases()
    staged = (
        [
            json.loads(x)
            for x in CANDIDATE_STAGING.read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        if CANDIDATE_STAGING.exists()
        else []
    )
    known = {doc["golden_case_id"] for doc in lines}
    for doc in staged:
        _validate_candidate(doc, known)
        known.add(doc["golden_case_id"])
        lines.append(doc)
    version = _write_new_version(lines, active)
    CANDIDATE_STAGING.unlink(missing_ok=True)
    print(f"built dataset version: {version} ({len(lines)} cases)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden candidate augmentation")
    parser.add_argument("--root", type=Path, help="golden root override (tests)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("build-version")
    add = sub.add_parser("add-case")
    add.add_argument("--input", type=Path, required=True)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
