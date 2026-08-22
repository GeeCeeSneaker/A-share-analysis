"""Golden Review Workflow (audit R4-A2 sections 6-8).

The ONLY path from COMPILED to REVIEWED. Reviewers provide the external
evidence ARTIFACT; the workflow hashes the real bytes itself.

    python scripts/golden/review.py \\
        --case GT-ST-600518-20190506 \\
        --artifact data/golden/provider/amazingdata/evidence/kangmei-st-notice.txt \\
        --kind SSE_ANNOUNCEMENT \\
        --reviewer alice \\
        --note "verified against SSE disclosure page 2026-08-22"

Hard rules (review section 6):
- NO --hash parameter exists: source_artifact_hash is computed from the
  artifact bytes by this workflow, never typed by a human.
- The artifact is copied into the evidence store (content-addressed by
  its own sha256) and source_artifact_ref points at the stored copy.
- The output is a NEW dataset version (append-only); the ACTIVE pointer
  is updated only after re-sealing every touched case's semantic hash.
- COMPILED provenance is preserved untouched.

Batch mode: --manifest review_batch.json applies many entries; each
entry must still resolve a real artifact file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
EVIDENCE_DIR = GOLDEN_ROOT / "evidence"

VALID_KINDS = {
    "SSE_ANNOUNCEMENT",
    "SZSE_ANNOUNCEMENT",
    "BSE_ANNOUNCEMENT",
    "CSRC_DOCUMENT",
    "EXCHANGE_RULEBOOK",
    "COMPANY_ANNOUNCEMENT",
    "INDEX_METHODLOGY",
    "OTHER_OFFICIAL",
}


class ReviewError(RuntimeError):
    """Review workflow contract violation."""


def _load_active() -> tuple[Path, dict, list[dict]]:
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    if not active_path.is_file():
        msg = "no active truth manifest"
        raise ReviewError(msg)
    active = json.loads(active_path.read_text(encoding="utf-8"))
    dataset = GOLDEN_ROOT / str(active["dataset_file"])
    if hashlib.sha256(dataset.read_bytes()).hexdigest() != active["dataset_hash"]:
        msg = "active dataset hash mismatch - dataset file modified"
        raise ReviewError(msg)
    lines = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return dataset, active, lines


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


def _store_artifact(artifact: Path, case_id: str, kind: str) -> tuple[str, str, str]:
    """Copy the artifact into the evidence store (content-addressed).

    Returns (source_artifact_ref, sha256, retrieved_at).
    """
    if not artifact.is_file():
        msg = f"artifact file does not exist: {artifact}"
        raise ReviewError(msg)
    data = artifact.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = artifact.suffix or ".bin"
    stored = EVIDENCE_DIR / f"{case_id}{suffix}"
    if stored.exists() and hashlib.sha256(stored.read_bytes()).hexdigest() != digest:
        stored = EVIDENCE_DIR / f"{case_id}-{digest[:12]}{suffix}"
    shutil.copy2(artifact, stored)
    retrieved_at = datetime.now(UTC).isoformat()
    return stored.name, digest, retrieved_at


def _apply_review(
    lines: list[dict],
    case_id: str,
    *,
    artifact_ref: str,
    artifact_hash: str,
    artifact_kind: str,
    retrieved_at: str,
    reviewer: str,
    note: str,
    expect_fields: dict | None = None,
) -> list[dict]:
    """Mutate the target case into REVIEWED (in-memory)."""
    now = datetime.now(UTC).isoformat()
    for doc in lines:
        if doc["golden_case_id"] != case_id:
            continue
        if doc["review_status"] != "COMPILED":
            msg = f"case {case_id} is already {doc['review_status']}"
            raise ReviewError(msg)
        if expect_fields is not None:
            doc["expected_fields"] = expect_fields
        doc["source_artifact_ref"] = artifact_ref
        doc["source_artifact_kind"] = artifact_kind
        doc["source_retrieved_at"] = retrieved_at
        doc["source_artifact_hash"] = artifact_hash  # computed from real bytes
        doc["reviewed_by"] = reviewer
        doc["reviewed_at"] = now
        doc["review_note"] = note
        doc["review_status"] = "REVIEWED"
        doc["case_semantic_hash"] = _semantic_hash(doc)  # re-seal
        return lines
    msg = f"case {case_id} not found in the active dataset"
    raise ReviewError(msg)


def _write_new_version(lines: list[dict], old_active: dict) -> str:
    """Write the next dataset version + update the ACTIVE pointer."""
    old_version = str(old_active["truth_version"])
    # bump the version suffix: vN-candidate -> v(N+1)-reviewed-partial
    num = "".join(ch for ch in old_version.split("-")[0][1:] if ch.isdigit()) or "1"
    truth_version = f"v{int(num) + 1}-reviewed-{datetime.now(UTC).strftime('%Y%m%d')}"
    for doc in lines:
        doc["truth_version"] = truth_version
        doc["case_semantic_hash"] = _semantic_hash(doc)
    dataset_file = f"golden_cases_{truth_version.split('-')[0]}.jsonl"
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in lines)
    (GOLDEN_ROOT / dataset_file).write_text(payload, encoding="utf-8", newline="\n")
    dataset_hash = hashlib.sha256((GOLDEN_ROOT / dataset_file).read_bytes()).hexdigest()

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
    (GOLDEN_ROOT / f"truth_manifest_{truth_version.split('-')[0]}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    (GOLDEN_ROOT / "truth_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return truth_version


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden review workflow")
    parser.add_argument("--case", help="golden_case_id to review")
    parser.add_argument("--artifact", type=Path, help="path to the external evidence artifact")
    parser.add_argument("--kind", choices=sorted(VALID_KINDS))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--expect-fields", help="JSON: corrected expected_fields (optional)")
    parser.add_argument("--manifest", type=Path, help="batch review manifest (JSON list)")
    parser.add_argument("--root", type=Path, help="golden root override (tests)")
    args = parser.parse_args()

    global GOLDEN_ROOT, EVIDENCE_DIR
    if args.root:
        GOLDEN_ROOT = Path(args.root)
        EVIDENCE_DIR = GOLDEN_ROOT / "evidence"

    dataset, active, lines = _load_active()

    if args.manifest:
        entries = json.loads(args.manifest.read_text(encoding="utf-8"))
        for entry in entries:
            ref, digest, retrieved = _store_artifact(
                Path(entry["artifact"]), entry["case"], entry["kind"]
            )
            _apply_review(
                lines,
                entry["case"],
                artifact_ref=ref,
                artifact_hash=digest,
                artifact_kind=entry["kind"],
                retrieved_at=retrieved,
                reviewer=args.reviewer,
                note=entry.get("note", ""),
                expect_fields=entry.get("expect_fields"),
            )
    else:
        missing = [f for f in (args.case, args.artifact, args.kind) if not f]
        if missing:
            parser.error(f"missing arguments: {missing} (or use --manifest)")
        expect = json.loads(args.expect_fields) if args.expect_fields else None
        ref, digest, retrieved = _store_artifact(args.artifact, args.case, args.kind)
        _apply_review(
            lines,
            args.case,
            artifact_ref=ref,
            artifact_hash=digest,
            artifact_kind=args.kind,
            retrieved_at=retrieved,
            reviewer=args.reviewer,
            note=args.note,
            expect_fields=expect,
        )

    version = _write_new_version(lines, active)
    print(f"reviewed dataset version: {version}")
    print(f"cases: {sum(1 for c in lines if c['review_status'] == 'REVIEWED')} REVIEWED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
