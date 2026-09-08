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
- A publishing invocation must cover every ACTIVE case exactly once.  A
  single-case invocation is valid only when the ACTIVE dataset itself has
  one case; review packets may be prepared incrementally, but ACTIVE
  publication is an atomic full-corpus seal (GT-H1.2).
- Versioned dataset/manifest files are create-only: same bytes are an
  idempotent no-op, different bytes BLOCK (R4A2-P1-04).
- The ACTIVE pointer moves via staging + atomic replace.
- COMPILED provenance is preserved untouched.

    python scripts/golden/review.py --manifest review-batch.json \
        --reviewer alice

  ``review-batch.json`` must contain one entry for every case in the clean
  ACTIVE candidate, with each ``case`` ID appearing exactly once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.evidence_bundle import (  # noqa: E402
    EvidenceBundleError,
    read_evidence_bundle,
)
from ashare_state.spike.evidence_contract import (  # noqa: E402
    CONTRACT_RELATIVE_PATH,
    PRODUCTION_CONTRACT_SHA256,
    EvidenceSourceContractError,
    load_evidence_source_contract,
    validate_review_source_bindings,
)
from ashare_state.spike.golden_store import (  # noqa: E402
    VALID_ARTIFACT_KINDS,
    GoldenTruthError,
    GoldenTruthStore,
    StructuralEventError,
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    review_readiness_gate,
    semantic_hash_for_doc,
    validate_structural_event_fields,
)

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
PRODUCTION_GOLDEN_ROOT = (Path(__file__).resolve().parents[2] / GOLDEN_ROOT).resolve()
EVIDENCE_DIR = GOLDEN_ROOT / "evidence"
EVIDENCE_SOURCE_CONTRACT_PATH = Path(__file__).resolve().parents[2] / CONTRACT_RELATIVE_PATH


class ReviewError(RuntimeError):
    """Review workflow contract violation."""


# ------------------------------------------------------------- validation


def _validate_artifact_kind(kind: str) -> None:
    """R4A2-P1-01: single + batch share the allowlist check."""
    if kind not in VALID_ARTIFACT_KINDS:
        msg = f"artifact kind {kind!r} not in allowlist {sorted(VALID_ARTIFACT_KINDS)}"
        raise ReviewError(msg)


def _parse_source_declarations(
    raw_sources: object,
    *,
    entry_index: int,
    field_name: str,
    minimum: int,
) -> list[dict]:
    if not isinstance(raw_sources, list) or len(raw_sources) < minimum:
        raise ReviewError(
            f"review manifest entry {entry_index} {field_name} requires "
            f"at least {minimum} source declaration(s)"
        )
    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source_index, source in enumerate(raw_sources, start=1):
        if not isinstance(source, dict):
            raise ReviewError(
                f"review manifest entry {entry_index} {field_name} source "
                f"{source_index} must be an object"
            )
        source_ref = source.get("source_ref")
        source_kind = source.get("kind")
        if not isinstance(source_ref, str) or not source_ref:
            raise ReviewError(
                f"review manifest entry {entry_index} {field_name} source "
                f"{source_index} has an invalid source_ref"
            )
        if not isinstance(source_kind, str) or not source_kind:
            raise ReviewError(
                f"review manifest entry {entry_index} {field_name} source "
                f"{source_index} has an invalid kind"
            )
        _validate_artifact_kind(source_kind)
        if source_kind == "EVIDENCE_BUNDLE":
            raise ReviewError(
                f"review manifest entry {entry_index} {field_name} source "
                f"{source_index} cannot itself be an EVIDENCE_BUNDLE"
            )
        key = (source_ref, source_kind)
        if key in seen:
            raise ReviewError(
                f"review manifest entry {entry_index} contains duplicate "
                f"{field_name} source {source_index}"
            )
        seen.add(key)
        sources.append({"source_ref": source_ref, "kind": source_kind})
    return sources


def _validate_review_coverage(lines: list[dict], submitted_case_ids: list[str]) -> None:
    """Require one publishing entry for every ACTIVE case (GT-H1.2)."""
    active_case_ids = [str(doc.get("golden_case_id", "")) for doc in lines]
    if not active_case_ids:
        raise ReviewError("active dataset has no cases to review")
    if any(not case_id for case_id in active_case_ids):
        raise ReviewError("active dataset contains a case with an empty golden_case_id")

    def duplicates(values: list[str]) -> list[str]:
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return sorted(value for value, count in counts.items() if count > 1)

    active_duplicates = duplicates(active_case_ids)
    if active_duplicates:
        raise ReviewError(
            "active dataset contains duplicate golden_case_id values: "
            + ", ".join(active_duplicates[:5])
        )

    submitted_duplicates = duplicates(submitted_case_ids)
    if submitted_duplicates:
        raise ReviewError(
            "review batch contains duplicate case IDs: "
            + ", ".join(submitted_duplicates[:5])
            + "; each ACTIVE golden_case_id must appear exactly once"
        )

    active_set = set(active_case_ids)
    submitted_set = set(submitted_case_ids)
    foreign = sorted(submitted_set - active_set)
    if foreign:
        raise ReviewError("review batch contains foreign case IDs: " + ", ".join(foreign[:5]))

    missing = sorted(active_set - submitted_set)
    if missing or len(submitted_case_ids) != len(active_case_ids):
        suffix = ", ".join(missing[:5]) if missing else "case-count mismatch"
        raise ReviewError(
            "review batch must cover every active case exactly once; missing: " + suffix
        )


def _load_review_requests(args: argparse.Namespace) -> list[dict]:
    """Parse review inputs without reading or writing evidence."""
    if args.manifest and any(
        (
            args.case,
            args.artifact,
            args.kind,
            args.expect_fields,
            getattr(args, "source_ref", None),
            getattr(args, "source_kind", None),
        )
    ):
        raise ReviewError(
            "--manifest cannot be combined with --case/--artifact/--kind/source-ref/source-kind"
        )

    if args.manifest:
        try:
            raw_entries = json.loads(args.manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewError(f"cannot read review manifest: {exc}") from exc
        if not isinstance(raw_entries, list):
            raise ReviewError("review manifest must be a JSON list")

        requests: list[dict] = []
        for index, entry in enumerate(raw_entries, start=1):
            if not isinstance(entry, dict):
                raise ReviewError(f"review manifest entry {index} must be a JSON object")
            missing = [field for field in ("case", "artifact", "kind") if field not in entry]
            if missing:
                raise ReviewError(
                    f"review manifest entry {index} is missing required fields: {missing}"
                )
            case_id = entry["case"]
            artifact = entry["artifact"]
            kind = entry["kind"]
            if not isinstance(case_id, str) or not case_id:
                raise ReviewError(f"review manifest entry {index} has an invalid case ID")
            if not isinstance(artifact, str) or not artifact:
                raise ReviewError(f"review manifest entry {index} has an invalid artifact path")
            if not isinstance(kind, str) or not kind:
                raise ReviewError(f"review manifest entry {index} has an invalid artifact kind")
            if "expect_fields" in entry:
                raise ReviewError(
                    "GT-H3B batch review manifest must not contain expect_fields; "
                    "correct the candidate before review"
                )
            expect_fields = entry.get("expect_fields")
            if expect_fields is not None and not isinstance(expect_fields, dict):
                raise ReviewError(f"review manifest entry {index} expect_fields must be an object")

            sources: list[dict] | None = None
            bundle_sources: list[dict] | None = None
            if kind == "EVIDENCE_BUNDLE":
                if "sources" in entry:
                    raise ReviewError(
                        f"review manifest entry {index} sources is only valid "
                        "for ordinary artifacts"
                    )
                bundle_sources = _parse_source_declarations(
                    entry.get("bundle_sources"),
                    entry_index=index,
                    field_name="bundle_sources",
                    minimum=2,
                )
            else:
                if "bundle_sources" in entry:
                    raise ReviewError(
                        f"review manifest entry {index} bundle_sources is only valid "
                        "for EVIDENCE_BUNDLE"
                    )
                sources = _parse_source_declarations(
                    entry.get("sources"),
                    entry_index=index,
                    field_name="sources",
                    minimum=1,
                )
            requests.append(
                {
                    "case": case_id,
                    "artifact": Path(artifact),
                    "kind": kind,
                    "note": entry.get("note", ""),
                    "expect_fields": expect_fields,
                    "sources": sources,
                    "bundle_sources": bundle_sources,
                }
            )
        return requests

    missing = [
        name
        for name, value in (
            ("--case", args.case),
            ("--artifact", args.artifact),
            ("--kind", args.kind),
            ("--source-ref", getattr(args, "source_ref", None)),
            ("--source-kind", getattr(args, "source_kind", None)),
        )
        if value is None
    ]
    if missing:
        raise ReviewError(f"missing arguments: {missing} (or use --manifest)")
    expect_fields = None
    if args.expect_fields:
        try:
            expect_fields = json.loads(args.expect_fields)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"--expect-fields must be valid JSON: {exc}") from exc
        if not isinstance(expect_fields, dict):
            raise ReviewError("--expect-fields must be a JSON object")
    return [
        {
            "case": args.case,
            "artifact": args.artifact,
            "kind": args.kind,
            "note": args.note,
            "expect_fields": expect_fields,
            "sources": [
                {
                    "source_ref": args.source_ref,
                    "kind": args.source_kind,
                }
            ],
            "bundle_sources": None,
        }
    ]


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
    try:
        cases, manifest = GoldenTruthStore(GOLDEN_ROOT).load()
    except (GoldenTruthError, KeyError, OSError, ValueError) as exc:
        raise ReviewError(f"active dataset cannot be used for review: {exc}") from exc
    readiness_problems = review_readiness_gate(cases, manifest)
    if readiness_problems:
        raise ReviewError("; ".join(readiness_problems))
    lines = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return dataset, active, lines


def _load_evidence_source_contract(
    args: argparse.Namespace,
    dataset: Path,
    active: dict,
    lines: list[dict],
):
    contract_path = args.contract or EVIDENCE_SOURCE_CONTRACT_PATH
    if args.contract is not None:
        if args.root is None:
            raise ReviewError("--contract is a test override and requires --root")
        try:
            requested_root = Path(args.root).resolve()
            production_root = PRODUCTION_GOLDEN_ROOT.resolve()
        except (OSError, RuntimeError) as exc:
            raise ReviewError(
                "cannot resolve --root for test contract boundary validation"
            ) from exc
        if requested_root == production_root:
            raise ReviewError(
                "--contract test override cannot target the production Golden root"
            )
    try:
        return load_evidence_source_contract(
            contract_path,
            expected_truth_version=str(active["truth_version"]),
            expected_dataset_file=dataset.name,
            expected_dataset_hash=str(active["dataset_hash"]),
            expected_case_ids=[str(doc["golden_case_id"]) for doc in lines],
            expected_sha256=None if args.contract is not None else PRODUCTION_CONTRACT_SHA256,
            enforce_known_composites=args.contract is None,
        )
    except (EvidenceSourceContractError, OSError, ValueError) as exc:
        raise ReviewError(f"cannot load evidence-source contract: {exc}") from exc


def _semantic_hash(doc: dict) -> str:
    return semantic_hash_for_doc(doc)


# ---------------------------------------------------------------- staging


def _stage_artifact(
    artifact: Path, kind: str, bundle_sources: list[dict] | None = None
) -> tuple[str, str, str]:
    """Stage ONE artifact: validate kind, hash the real bytes, return
    (content-addressed ref, sha256, retrieved_at). Nothing is written yet
    (R4A2-P1-05: stage-all-then-commit)."""
    _validate_artifact_kind(kind)
    if kind == "EVIDENCE_BUNDLE":
        if bundle_sources is None:
            raise ReviewError("EVIDENCE_BUNDLE requires declared bundle_sources")
        try:
            read_evidence_bundle(artifact, expected_sources=bundle_sources)
        except EvidenceBundleError as exc:
            raise ReviewError(f"invalid EVIDENCE_BUNDLE {artifact}: {exc}") from exc
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


def _commit_evidence(
    staged: list[tuple[Path, str, str]],
    created: list[tuple[Path, bytes]] | None = None,
) -> list[tuple[Path, bytes]]:
    """Copy staged artifacts into the evidence store (create-only).

    The returned/received list records only files created by this invocation.
    It lets the caller remove unreferenced outputs if the final ACTIVE pointer
    commit fails.
    """
    created_files = created if created is not None else []
    for source, ref, expected_hash in staged:
        target = EVIDENCE_DIR / ref
        data = source.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            raise ReviewError(
                f"artifact changed after staging: {source} no longer matches {expected_hash}"
            )
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
                msg = f"evidence {ref} already exists with different bytes"
                raise ReviewError(msg)
            continue  # idempotent
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        created_files.append((target, data))
    return created_files


def _create_only_write(path: Path, data: bytes) -> bool:
    """R4A2-P1-04: versioned files are create-only.

    absent -> create; exists + same bytes -> idempotent no-op;
    exists + different bytes -> BLOCK.
    """
    if path.exists():
        if path.read_bytes() == data:
            return False
        msg = f"versioned file {path.name} already exists with different bytes"
        raise ReviewError(msg)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    Path(tmp).replace(Path(path))
    return True


def _rollback_created_files(created: list[tuple[Path, bytes]]) -> list[str]:
    """Remove only unchanged files created before a failed publication."""
    failures: list[str] = []
    for path, expected in reversed(created):
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            failures.append(str(path))
            continue
        try:
            actual = path.read_bytes()
        except OSError as exc:
            failures.append(f"{path}: {exc}")
            continue
        if actual != expected:
            failures.append(f"{path}: bytes changed after creation")
            continue
        try:
            path.unlink()
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    return failures


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


@dataclass(frozen=True)
class _PreparedReview:
    truth_version: str
    dataset_path: Path
    dataset_bytes: bytes
    manifest_path: Path
    manifest_bytes: bytes
    manifest: dict


def _prepare_new_version(
    lines: list[dict], old_active: dict, staged_hashes: dict[str, str] | None = None
) -> _PreparedReview:
    """Build and fully validate the reviewed version without writing it."""
    if not lines:
        raise ReviewError("cannot publish a reviewed dataset with no cases")

    old_version = str(old_active["truth_version"])
    num = "".join(ch for ch in old_version.split("-")[0][1:] if ch.isdigit()) or "1"
    truth_version = f"v{int(num) + 1}-reviewed-{datetime.now(UTC).strftime('%Y%m%d')}"
    final_lines: list[dict] = []
    for original in lines:
        doc = dict(original)
        doc["truth_version"] = truth_version
        doc["case_semantic_hash"] = _semantic_hash(doc)
        final_lines.append(doc)

    if staged_hashes is not None:
        for doc in final_lines:
            ref = str(doc.get("source_artifact_ref", ""))
            digest = str(doc.get("source_artifact_hash", ""))
            if staged_hashes.get(ref) != digest:
                raise ReviewError(
                    f"{doc.get('golden_case_id')}: reviewed artifact binding was not staged"
                )

    dataset_file = f"golden_cases_{truth_version.split('-')[0]}.jsonl"
    payload = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in final_lines)
    try:
        cases = cases_from_dataset_bytes(payload.encode("utf-8"), truth_version)
    except GoldenTruthError as exc:
        raise ReviewError(f"reviewed dataset failed loader self-validation: {exc}") from exc
    stats = recompute_manifest_statistics(cases)
    expected_review_summary = {"REVIEWED": len(cases)}
    if stats["review_summary"] != expected_review_summary:
        raise ReviewError(
            "reviewed output must be a complete REVIEWED seal: "
            f"expected {expected_review_summary}, got {stats['review_summary']}"
        )
    dataset_bytes = payload.encode("utf-8")
    dataset_path = GOLDEN_ROOT / dataset_file
    dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
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
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    return _PreparedReview(
        truth_version=truth_version,
        dataset_path=dataset_path,
        dataset_bytes=dataset_bytes,
        manifest_path=manifest_file,
        manifest_bytes=manifest_bytes,
        manifest=manifest,
    )


def _preflight_create_only(path: Path, data: bytes) -> None:
    """Check immutable version collisions before any evidence is committed."""
    if path.exists() and path.read_bytes() != data:
        raise ReviewError(f"versioned file {path.name} already exists with different bytes")


def _preflight_evidence(staged: list[tuple[Path, str, str]]) -> None:
    """Validate every source and existing content-addressed target pre-commit."""
    for source, ref, expected_hash in staged:
        data = source.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            raise ReviewError(
                f"artifact changed after staging: {source} no longer matches {expected_hash}"
            )
        target = EVIDENCE_DIR / ref
        if target.exists() and target.read_bytes() != data:
            raise ReviewError(f"evidence {ref} already exists with different bytes")


def _publish_new_version(
    prepared: _PreparedReview,
    created: list[tuple[Path, bytes]] | None = None,
) -> str:
    """Publish a prevalidated version and move ACTIVE last."""
    created_files = created if created is not None else []
    if _create_only_write(prepared.dataset_path, prepared.dataset_bytes):
        created_files.append((prepared.dataset_path, prepared.dataset_bytes))
    if _create_only_write(prepared.manifest_path, prepared.manifest_bytes):
        created_files.append((prepared.manifest_path, prepared.manifest_bytes))
    _atomic_active_pointer(prepared.manifest)
    return prepared.truth_version


def _write_new_version(lines: list[dict], old_active: dict) -> str:
    """Write the next dataset version (create-only) + move ACTIVE."""
    return _publish_new_version(_prepare_new_version(lines, old_active))


# ------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden review workflow")
    parser.add_argument("--case", help="golden_case_id to review")
    parser.add_argument("--artifact", type=Path, help="path to the external evidence artifact")
    parser.add_argument("--kind", help="artifact kind (see allowlist)")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--expect-fields", help="JSON: corrected expected_fields (optional)")
    parser.add_argument("--source-ref", help="single-case source locator")
    parser.add_argument("--source-kind", help="single-case source artifact kind")
    parser.add_argument("--manifest", type=Path, help="batch review manifest (JSON list)")
    parser.add_argument(
        "--contract",
        type=Path,
        help="test-only source contract override; requires a non-production --root",
    )
    parser.add_argument("--root", type=Path, help="golden root override (tests)")
    args = parser.parse_args()

    global GOLDEN_ROOT, EVIDENCE_DIR
    if args.root:
        GOLDEN_ROOT = Path(args.root)
        EVIDENCE_DIR = GOLDEN_ROOT / "evidence"

    dataset, active, lines = _load_active()
    _ = dataset

    requests = _load_review_requests(args)
    _validate_review_coverage(lines, [request["case"] for request in requests])
    contract = _load_evidence_source_contract(args, dataset, active, lines)
    try:
        validate_review_source_bindings(contract, requests)
    except EvidenceSourceContractError as exc:
        raise ReviewError(f"review source binding failed: {exc}") from exc

    # -------- stage ALL entries first (P1-05: no orphan evidence) --------
    staged_artifacts: list[tuple[Path, str, str]] = []
    entries: list[dict] = []
    for request in requests:
        ref, digest, retrieved = _stage_artifact(
            request["artifact"], request["kind"], request["bundle_sources"]
        )
        staged_artifacts.append((request["artifact"], ref, digest))
        entries.append(
            {
                "case": request["case"],
                "ref": ref,
                "digest": digest,
                "retrieved": retrieved,
                "kind": request["kind"],
                "note": request["note"],
                "expect_fields": request["expect_fields"],
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

    # -------- preflight the complete output before any durable publication --
    prepared = _prepare_new_version(
        lines,
        active,
        staged_hashes={ref: digest for _, ref, digest in staged_artifacts},
    )
    _preflight_create_only(prepared.dataset_path, prepared.dataset_bytes)
    _preflight_create_only(prepared.manifest_path, prepared.manifest_bytes)
    _preflight_evidence(staged_artifacts)

    # -------- commit: evidence -> version -> ACTIVE pointer ---------------
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    try:
        active_before = active_path.read_bytes()
    except OSError as exc:
        raise ReviewError(f"cannot snapshot ACTIVE pointer before commit: {exc}") from exc

    created_files: list[tuple[Path, bytes]] = []
    try:
        _commit_evidence(staged_artifacts, created_files)
        version = _publish_new_version(prepared, created_files)
    except Exception as exc:
        try:
            active_after = active_path.read_bytes()
        except OSError as pointer_exc:
            raise ReviewError(
                "review publication failed and ACTIVE could not be verified; "
                "durable outputs were retained for recovery"
            ) from pointer_exc
        if active_after != active_before:
            raise ReviewError(
                "review publication failed after ACTIVE pointer changed; "
                "durable outputs were retained for recovery"
            ) from exc
        rollback_errors = _rollback_created_files(created_files)
        if rollback_errors:
            detail = "; ".join(rollback_errors[:5])
            raise ReviewError(
                "review publication failed before ACTIVE pointer commit; "
                f"rollback incomplete: {detail}"
            ) from exc
        if isinstance(exc, ReviewError):
            raise
        raise ReviewError(f"review publication failed before ACTIVE pointer commit: {exc}") from exc
    reviewed = sum(1 for c in lines if c["review_status"] == "REVIEWED")
    print(f"reviewed dataset version: {version}")
    print(f"cases: {reviewed} REVIEWED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
