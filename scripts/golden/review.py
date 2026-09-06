"""Golden Review Workflow (R4-A2.1 hardening).

The ONLY path from COMPILED to REVIEWED. Reviewers provide the external
evidence ARTIFACT; the workflow hashes the real bytes itself.

Hard rules:
- NO --hash parameter: source_artifact_hash is computed from artifact
  bytes by this workflow, never typed by a human.
- Evidence is content-addressed: evidence/sha256/<full_hash>.<ext>
  (R4A2-P1-06 option A).
- Batch mode validates ALL entries (kind allowlist included) BEFORE
  writing anything; a failure leaves no orphan evidence (R4A2-P1-05).
- Versioned dataset/manifest files are create-only: same bytes are an
  idempotent no-op, different bytes BLOCK (R4A2-P1-04).
- The ACTIVE pointer moves via staging + atomic replace.
- COMPILED provenance is preserved untouched.

    python scripts/golden/review.py --case GT-ST-600518-20190506 \
        --artifact evidence-src/kangmei.txt \
        --kind SSE_ANNOUNCEMENT --reviewer alice --note "verified"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.golden_store import (  # noqa: E402
    VALID_ARTIFACT_KINDS,
    GoldenTruthError,
    StructuralEventError,
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    semantic_hash_for_doc,
    validate_structural_event_fields,
)

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
EVIDENCE_DIR = GOLDEN_ROOT / "evidence"


class ReviewError(RuntimeError):
    """Review workflow contract violation."""


# ------------------------------------------------------------- validation


def _validate_artifact_kind(kind: str) -> None:
    """R4A2-P1-01: single + batch share the allowlist check."""
    if kind not in VALID_ARTIFACT_KINDS:
        msg = f"artifact kind {kind!r} not in allowlist {sorted(VALID_ARTIFACT_KINDS)}"
        raise ReviewError(msg)


# ---------------------------------------------------------------- loading


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
    return semantic_hash_for_doc(doc)


# ---------------------------------------------------------------- staging


def _stage_artifact(artifact: Path, kind: str) -> tuple[str, str, str]:
    """Stage ONE artifact: validate kind, hash the real bytes, return
    (content-addressed ref, sha256, retrieved_at). Nothing is written yet
    (R4A2-P1-05: stage-all-then-commit)."""
    _validate_artifact_kind(kind)
    if not artifact.is_file():
        msg = f"artifact file does not exist: {artifact}"
        raise ReviewError(msg)
    data = artifact.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    # R4A2-P1-06 option A: content-addressed evidence
    suffix = artifact.suffix or ".bin"
    ref = f"sha256/{digest}{suffix}"
    retrieved_at = datetime.now(UTC).isoformat()
    return ref, digest, retrieved_at


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
) -> None:
    """Mutate the target case into REVIEWED (in-memory)."""
    now = datetime.now(UTC).isoformat()
    for doc in lines:
        if doc["golden_case_id"] != case_id:
            continue
        if doc["review_status"] != "COMPILED":
            msg = f"case {case_id} is already {doc['review_status']}"
            raise ReviewError(msg)
        try:
            validate_structural_event_fields(
                case_id=case_id,
                event_class=doc.get("event_class", ""),
                provider_symbol=doc.get("provider_symbol"),
                event_subtype=doc.get("event_subtype", ""),
                event_effective_date=doc.get("event_effective_date", ""),
            )
        except StructuralEventError as exc:
            raise ReviewError(
                f"case {case_id}: incomplete structural event; review cannot promote it: {exc}"
            ) from exc
        if expect_fields is not None:
            doc["expected_fields"] = expect_fields
        doc["source_artifact_ref"] = artifact_ref
        doc["source_artifact_kind"] = artifact_kind
        doc["source_retrieved_at"] = retrieved_at
        doc["source_artifact_hash"] = artifact_hash
        doc["reviewed_by"] = reviewer
        doc["reviewed_at"] = now
        doc["review_note"] = note
        doc["review_status"] = "REVIEWED"
        doc["case_semantic_hash"] = _semantic_hash(doc)
        return
    msg = f"case {case_id} not found in the active dataset"
    raise ReviewError(msg)


# ----------------------------------------------------------------- commit


def _commit_evidence(staged: list[tuple[Path, str]]) -> None:
    """Copy staged artifacts into the evidence store (create-only)."""
    for source, ref in staged:
        target = EVIDENCE_DIR / ref
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
                msg = f"evidence {ref} already exists with different bytes"
                raise ReviewError(msg)
            continue  # idempotent
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)


def _create_only_write(path: Path, data: bytes) -> None:
    """R4A2-P1-04: versioned files are create-only.

    absent -> create; exists + same bytes -> idempotent no-op;
    exists + different bytes -> BLOCK.
    """
    if path.exists():
        if path.read_bytes() == data:
            return
        msg = f"versioned file {path.name} already exists with different bytes"
        raise ReviewError(msg)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    Path(tmp).replace(Path(path))


def _atomic_active_pointer(manifest: dict) -> None:
    """Move the ACTIVE pointer via staging + atomic replace."""
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    staging = active_path.with_name(f".{active_path.name}.{uuid4().hex}.tmp")
    try:
        staging.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
        staging.replace(active_path)
    finally:
        staging.unlink(missing_ok=True)


def _write_new_version(lines: list[dict], old_active: dict) -> str:
    """Write the next dataset version (create-only) + move ACTIVE."""
    old_version = str(old_active["truth_version"])
    num = "".join(ch for ch in old_version.split("-")[0][1:] if ch.isdigit()) or "1"
    truth_version = f"v{int(num) + 1}-reviewed-{datetime.now(UTC).strftime('%Y%m%d')}"
    for doc in lines:
        doc["truth_version"] = truth_version
        doc["case_semantic_hash"] = _semantic_hash(doc)
    dataset_file = f"golden_cases_{truth_version.split('-')[0]}.jsonl"
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in lines)
    try:
        cases = cases_from_dataset_bytes(payload.encode("utf-8"), truth_version)
    except GoldenTruthError as exc:
        raise ReviewError(f"reviewed dataset failed loader self-validation: {exc}") from exc
    dataset_path = GOLDEN_ROOT / dataset_file
    _create_only_write(dataset_path, payload.encode("utf-8"))
    dataset_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    stats = recompute_manifest_statistics(cases)
    manifest = {
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
    manifest_file = GOLDEN_ROOT / f"truth_manifest_{truth_version.split('-')[0]}.json"
    _create_only_write(
        manifest_file,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    _atomic_active_pointer(manifest)
    return truth_version


# ------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden review workflow")
    parser.add_argument("--case", help="golden_case_id to review")
    parser.add_argument("--artifact", type=Path, help="path to the external evidence artifact")
    parser.add_argument("--kind", help="artifact kind (see allowlist)")
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
    _ = dataset

    # -------- stage ALL entries first (P1-05: no orphan evidence) --------
    staged_artifacts: list[tuple[Path, str]] = []
    entries: list[dict] = []
    if args.manifest:
        raw_entries = json.loads(args.manifest.read_text(encoding="utf-8"))
        for entry in raw_entries:
            ref, digest, retrieved = _stage_artifact(Path(entry["artifact"]), entry["kind"])
            staged_artifacts.append((Path(entry["artifact"]), ref))
            entries.append(
                {
                    "case": entry["case"],
                    "ref": ref,
                    "digest": digest,
                    "retrieved": retrieved,
                    "kind": entry["kind"],
                    "note": entry.get("note", ""),
                    "expect_fields": entry.get("expect_fields"),
                }
            )
    else:
        missing = [f for f in (args.case, args.artifact, args.kind) if not f]
        if missing:
            parser.error(f"missing arguments: {missing} (or use --manifest)")
        ref, digest, retrieved = _stage_artifact(args.artifact, args.kind)
        staged_artifacts.append((args.artifact, ref))
        entries.append(
            {
                "case": args.case,
                "ref": ref,
                "digest": digest,
                "retrieved": retrieved,
                "kind": args.kind,
                "note": args.note,
                "expect_fields": json.loads(args.expect_fields) if args.expect_fields else None,
            }
        )

    # -------- apply ALL reviews in memory (validates every case) ---------
    for entry in entries:
        _apply_review(
            lines,
            entry["case"],
            artifact_ref=entry["ref"],
            artifact_hash=entry["digest"],
            artifact_kind=entry["kind"],
            retrieved_at=entry["retrieved"],
            reviewer=args.reviewer,
            note=entry["note"],
            expect_fields=entry["expect_fields"],
        )

    # -------- commit: evidence -> version -> ACTIVE pointer ---------------
    _commit_evidence(staged_artifacts)
    version = _write_new_version(lines, active)
    reviewed = sum(1 for c in lines if c["review_status"] == "REVIEWED")
    print(f"reviewed dataset version: {version}")
    print(f"cases: {reviewed} REVIEWED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
