"""Prepare the GT-H3 human-review bundle without sealing any case.

GT-H3A is deliberately read-only with respect to Golden truth.  It derives
artifact groups and a case-level decision template from the adjudicated v5
candidate and its GT-H2 packet.  It does not retrieve evidence, write
``REVIEWED`` fields, or invoke ``review.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN_ROOT = REPO_ROOT / "data/golden/provider/amazingdata"
DEFAULT_PACKET = REPO_ROOT / "docs/golden/gt_h2/review_packet_index.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs/golden/gt_h3"

EXPECTED_TRUTH_VERSION = "v5-candidate-20260907"
EXPECTED_CASE_COUNT = 125
REVIEWER_CLOSURE_ID = "5125393678"
GT_H3A_ADJUDICATION_ID = "5128750265"
MAIN_BASELINE = "669759adf34bece4c9e41c7be2ce2e9f858e5277"

_EMPTY_REVIEW_FIELDS = (
    "reviewed_by",
    "reviewed_at",
    "review_note",
    "source_artifact_hash",
    "source_artifact_kind",
    "source_artifact_ref",
    "source_retrieved_at",
)
_SEAL_ENTRY_FIELDS = frozenset({"case", "artifact", "kind", "note"})


class PreparationError(RuntimeError):
    """GT-H3A input or output contract violation."""


def _guard_output_dir(output_dir: Path) -> None:
    """Keep the versioned v4 GT-H3A snapshot from being overwritten."""
    if output_dir.resolve() != DEFAULT_OUTPUT_DIR.resolve():
        return
    snapshot = output_dir / "GT_H3_REVIEW_BUNDLE.md"
    if snapshot.is_file():
        raise PreparationError(
            "refusing to overwrite the version-scoped GT-H3A snapshot; "
            "pass --output-dir docs/golden/gt_h3/remediation for v5 remediation outputs"
        )


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreparationError(f"JSON file {path} must contain an object")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise PreparationError(f"cannot read JSONL file {path}: {exc}") from exc
    rows: list[dict] = []
    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PreparationError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise PreparationError(f"JSONL row {path}:{line_number} must be an object")
        rows.append(row)
    return rows


def _case_ids(rows: list[dict], label: str) -> list[str]:
    ids = [str(row.get("golden_case_id", "")) for row in rows]
    if any(not case_id for case_id in ids):
        raise PreparationError(f"{label} contains an empty golden_case_id")
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise PreparationError(f"{label} contains duplicate case IDs: {duplicates[:5]}")
    return ids


def _load_candidate(golden_root: Path) -> tuple[dict, list[dict]]:
    manifest = _read_json(golden_root / "truth_manifest.json")
    if manifest.get("truth_version") != EXPECTED_TRUTH_VERSION:
        raise PreparationError(
            "GT-H3A must start from the adjudicated v5 candidate: "
            f"got {manifest.get('truth_version')!r}"
        )
    dataset_path = golden_root / str(manifest.get("dataset_file", ""))
    if not dataset_path.is_file():
        raise PreparationError(f"active dataset does not exist: {dataset_path}")
    dataset_bytes = dataset_path.read_bytes()
    dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
    if dataset_hash != manifest.get("dataset_hash"):
        raise PreparationError("active dataset hash does not match truth_manifest.json")
    rows = _read_jsonl(dataset_path)
    ids = _case_ids(rows, "active dataset")
    if len(rows) != EXPECTED_CASE_COUNT or manifest.get("case_count") != EXPECTED_CASE_COUNT:
        raise PreparationError(
            f"GT-H3A requires exactly {EXPECTED_CASE_COUNT} active cases; "
            f"dataset={len(rows)}, manifest={manifest.get('case_count')}"
        )
    for row in rows:
        case_id = str(row["golden_case_id"])
        if row.get("review_status") != "COMPILED":
            raise PreparationError(f"{case_id}: GT-H3A input must remain COMPILED")
        for field in _EMPTY_REVIEW_FIELDS:
            if row.get(field, "") not in ("", None):
                raise PreparationError(
                    f"{case_id}: review provenance is already populated: {field}"
                )
    if manifest.get("review_summary") != {"COMPILED": EXPECTED_CASE_COUNT}:
        raise PreparationError("GT-H3A requires review_summary == {'COMPILED': 125}")
    if len(ids) != EXPECTED_CASE_COUNT:
        raise PreparationError("active dataset case count is inconsistent")
    return manifest, rows


def _validate_packet(packet_rows: list[dict], candidate_rows: list[dict]) -> dict[str, dict]:
    candidate_by_id = {str(row["golden_case_id"]): row for row in candidate_rows}
    packet_ids = _case_ids(packet_rows, "GT-H2 review packet")
    candidate_ids = set(candidate_by_id)
    packet_set = set(packet_ids)
    if len(packet_rows) != EXPECTED_CASE_COUNT or packet_set != candidate_ids:
        missing = sorted(candidate_ids - packet_set)
        foreign = sorted(packet_set - candidate_ids)
        raise PreparationError(
            "GT-H2 review packet must cover ACTIVE exactly once; "
            f"missing={missing[:5]}, foreign={foreign[:5]}, rows={len(packet_rows)}"
        )
    by_id: dict[str, dict] = {}
    for packet in packet_rows:
        case_id = str(packet["golden_case_id"])
        required = ("official_source_name", "official_source_ref", "artifact_kind_candidate")
        missing = [field for field in required if not str(packet.get(field, ""))]
        if missing:
            raise PreparationError(f"{case_id}: packet is missing {missing}")
        if packet.get("source_evidence_scope") != "CASE_SPECIFIC_OFFICIAL_ARTIFACT":
            raise PreparationError(f"{case_id}: packet source scope is not case-specific official")
        if packet.get("fact_proved") is not True:
            raise PreparationError(
                f"{case_id}: packet fact_proved must be true before Human Review"
            )
        by_id[case_id] = packet
    return by_id


def _artifact_suffix(source_ref: str) -> str:
    path = urlparse(source_ref).path.lower()
    return ".pdf" if path.endswith(".pdf") else ".html"


def _semantic_summary(case: dict) -> dict:
    return {
        "case": case["golden_case_id"],
        "provider_symbol": case.get("provider_symbol", ""),
        "trade_date": case.get("trade_date", ""),
        "event_class": case.get("event_class", ""),
        "event_subtype": case.get("event_subtype", ""),
        "event_effective_date": case.get("event_effective_date", ""),
        "expected_fields": case.get("expected_fields", {}),
        "truth_source": case.get("truth_source", ""),
    }


def _build_groups(
    candidate_rows: list[dict], packet_by_id: dict[str, dict]
) -> tuple[list[dict], dict[str, str]]:
    grouped: defaultdict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for case in candidate_rows:
        case_id = str(case["golden_case_id"])
        packet = packet_by_id[case_id]
        key = (
            str(packet["official_source_name"]),
            str(packet["official_source_ref"]),
            str(packet["artifact_kind_candidate"]),
        )
        grouped[key].append(case)

    groups: list[dict] = []
    case_to_group: dict[str, str] = {}
    for index, key in enumerate(sorted(grouped), start=1):
        source_name, source_ref, artifact_kind = key
        group_id = f"AG-{index:03d}"
        cases = grouped[key]
        case_ids = [str(case["golden_case_id"]) for case in cases]
        for case_id in case_ids:
            case_to_group[case_id] = group_id
        artifact_filename = f"artifact-{index:03d}{_artifact_suffix(source_ref)}"
        groups.append(
            {
                "artifact_group_id": group_id,
                "official_source_name": source_name,
                "official_source_ref": source_ref,
                "artifact_kind_candidate": artifact_kind,
                "case_ids": case_ids,
                "case_count": len(cases),
                "claim_summary": sorted({str(case.get("truth_source", "")) for case in cases}),
                "case_specific_expected_semantics": [_semantic_summary(case) for case in cases],
                "retrieval_status": "PENDING_HUMAN_REVIEW",
                "retrieval_final_url": "",
                "proposed_local_artifact_filename": artifact_filename,
                "preflight_sha256": None,
            }
        )
    return groups, case_to_group


def validate_seal_manifest_entries(entries: list[dict], active_case_ids: list[str]) -> None:
    """Reject an executable GT-H3 manifest that could mutate Golden truth.

    The existing review CLI accepts the legacy ``expect_fields`` option for
    candidate correction.  GT-H3 must never use that option: its manifest is
    limited to case, artifact, kind and human review note.
    """
    if not isinstance(entries, list):
        raise PreparationError("GT-H3 seal manifest must be a JSON list")
    submitted: list[str] = []
    active = set(active_case_ids)
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise PreparationError(f"GT-H3 seal entry {index} must be an object")
        unknown = set(entry) - _SEAL_ENTRY_FIELDS
        if unknown:
            raise PreparationError(
                f"GT-H3 seal entry {index} has forbidden fields: {sorted(unknown)}"
            )
        if not isinstance(entry.get("case"), str) or not entry["case"]:
            raise PreparationError(f"GT-H3 seal entry {index} has an invalid case")
        if not isinstance(entry.get("artifact"), str) or not entry["artifact"]:
            raise PreparationError(f"GT-H3 seal entry {index} has an invalid artifact")
        if not isinstance(entry.get("kind"), str) or not entry["kind"]:
            raise PreparationError(f"GT-H3 seal entry {index} has an invalid kind")
        if not isinstance(entry.get("note", ""), str):
            raise PreparationError(f"GT-H3 seal entry {index} note must be a string")
        submitted.append(entry["case"])
    if len(submitted) != len(set(submitted)):
        raise PreparationError("GT-H3 seal manifest contains duplicate cases")
    submitted_set = set(submitted)
    foreign = sorted(submitted_set - active)
    missing = sorted(active - submitted_set)
    if foreign or missing or len(submitted) != len(active):
        raise PreparationError(
            "GT-H3 seal manifest must cover ACTIVE exactly once; "
            f"missing={missing[:5]}, foreign={foreign[:5]}"
        )


def _build_template(candidate_rows: list[dict], case_to_group: dict[str, str]) -> list[dict]:
    return [
        {
            "case": str(case["golden_case_id"]),
            "artifact_group_id": case_to_group[str(case["golden_case_id"])],
            "decision": "",
            "review_note": "",
            "reviewed_by": "",
            "reviewed_at": "",
            "expected_semantics": _semantic_summary(case),
        }
        for case in candidate_rows
    ]


def _jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def _bundle_markdown(manifest: dict, groups: list[dict], case_count: int) -> str:
    lines = [
        "# GT-H3 Human Review Bundle",
        "",
        "> Status: **GT-H3A PREPARED / NOT SEALED**",
        ">",
        "> This bundle is a review aid. It contains no retrieved official evidence bytes "
        "> and does not mark any case REVIEWED.",
        "",
        "## Candidate and authority",
        "",
        f"- ACTIVE truth version: `{manifest['truth_version']}`",
        f"- ACTIVE dataset: `{manifest['dataset_file']}`",
        f"- ACTIVE dataset SHA256: `{manifest['dataset_hash']}`",
        f"- ACTIVE case count: `{case_count}` (`COMPILED {case_count}/125`, `REVIEWED 0/125`)",
        f"- Main baseline used for this preparation: `{MAIN_BASELINE}`",
        f"- GT-H2 Reviewer closure: `{REVIEWER_CLOSURE_ID}`",
        f"- GT-H3A adjudication review: `{GT_H3A_ADJUDICATION_ID}`",
        "- Required boundary: Human Reviewer must explicitly approve or reject every case "
        "before any GT-H3 seal manifest is constructed.",
        "",
        "## Review boundary",
        "",
        "1. Review the exact official artifact for each group and verify issuer, "
        "document/rule version, scope, date, symbol and expected semantics.",
        "2. A source mismatch, an unresolvable artifact, or a fact that the artifact "
        "does not prove is `REJECT`; do not repair the Golden row in this workflow.",
        "3. Fill one case-level decision row for every case in "
        "`review_decision_template.jsonl`; permitted decisions are `APPROVE` and `REJECT`.",
        "4. A complete human statement must authorize the full 125-case set and identify "
        "the human marker to write as `reviewed_by`.",
        "5. Only after that statement may a separate executable manifest be built with "
        "exactly `case`, `artifact`, `kind` and `note` per row.",
        "",
        "The GT-H3 seal manifest must not contain `expect_fields`. Human Review cannot "
        "change `expected_fields`; any correction returns to candidate governance.",
        "",
        "## Artifact-group index",
        "",
        f"The bundle contains `{len(groups)}` deterministic artifact groups covering "
        f"`{case_count}` cases. Every group is currently `PENDING_HUMAN_REVIEW`; "
        "`preflight_sha256` is intentionally empty until the exact bytes are retrieved.",
        "",
        "| Group | Cases | Kind | Proposed local artifact | Official source |",
        "|---|---:|---|---|---|",
    ]
    for group in groups:
        source = group["official_source_ref"]
        lines.append(
            f"| `{group['artifact_group_id']}` | {group['case_count']} | "
            f"`{group['artifact_kind_candidate']}` | "
            f"`{group['proposed_local_artifact_filename']}` | "
            f"[{group['official_source_name']}]({source}) |"
        )
    lines.extend(
        [
            "",
            "## Tracked outputs",
            "",
            "- `review_bundle_index.jsonl`: one row per unique official artifact group, "
            "including all case-specific semantics and retrieval placeholders.",
            "- `review_decision_template.jsonl`: exactly one blank human decision row "
            "per ACTIVE case.",
            "- This document: review instructions, authority and checkpoint state.",
            "",
            "## Explicitly not done",
            "",
            "- No official HTML/PDF bytes were retrieved or committed in Checkpoint A.",
            "- No `REVIEWED` field, evidence hash, ACTIVE pointer advance or reviewed "
            "dataset was created.",
            "- No `review.py` seal, GT-H3B, Formal Production B1-B7, Data Sufficiency, "
            "Provider capability approval, backfill, strategy, backtest or trading run "
            "was executed.",
        ]
    )
    return "\n".join(lines) + "\n"


def prepare_bundle(
    golden_root: Path = DEFAULT_GOLDEN_ROOT,
    packet_path: Path = DEFAULT_PACKET,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    """Build GT-H3A outputs and return a compact summary."""
    _guard_output_dir(output_dir)
    manifest, candidate_rows = _load_candidate(golden_root)
    packet_rows = _read_jsonl(packet_path)
    packet_by_id = _validate_packet(packet_rows, candidate_rows)
    groups, case_to_group = _build_groups(candidate_rows, packet_by_id)
    template = _build_template(candidate_rows, case_to_group)
    validate_seal_manifest_entries(
        [
            {"case": row["case"], "artifact": "PENDING", "kind": "PENDING", "note": ""}
            for row in template
        ],
        [str(case["golden_case_id"]) for case in candidate_rows],
    )
    outputs = {
        "GT_H3_REVIEW_BUNDLE.md": _bundle_markdown(manifest, groups, len(candidate_rows)),
        "review_bundle_index.jsonl": _jsonl(groups),
        "review_decision_template.jsonl": _jsonl(template),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (output_dir / name).write_text(content, encoding="utf-8", newline="\n")
    return {
        "truth_version": manifest["truth_version"],
        "dataset_hash": manifest["dataset_hash"],
        "case_count": len(candidate_rows),
        "artifact_group_count": len(groups),
        "retrieval_status": "PENDING_HUMAN_REVIEW",
        "output_dir": str(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the GT-H3A human-review bundle")
    parser.add_argument("--root", type=Path, default=DEFAULT_GOLDEN_ROOT)
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        summary = prepare_bundle(args.root, args.packet, args.output_dir)
    except PreparationError as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
