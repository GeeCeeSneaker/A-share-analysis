"""Inspect the GT-H3R2 ST transition audit ledger.

The default command reports the complete inventory and its blockers.  Passing
--require-clean turns the independent semantic gate into a non-zero check.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.golden_store import cases_from_dataset_bytes  # noqa: E402
from ashare_state.spike.st_transition_audit import (  # noqa: E402
    transition_audit_publication_gate,
    validate_transition_audit,
)

DEFAULT_ROOT = Path("data/golden/provider/amazingdata")
DEFAULT_AUDIT = (
    Path(__file__).resolve().parents[2]
    / "docs/golden/gt_h3/remediation/GT_H3R2_ST_TRANSITION_AUDIT.jsonl"
)


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"cannot read {path}: {exc}") from exc
    result: list[dict] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}:{line_number}: expected a JSON object")
        result.append(value)
    return result


def _active_dataset(root: Path) -> tuple[dict, list[dict]]:
    manifest_path = root / "truth_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dataset_path = root / str(manifest["dataset_file"])
        dataset_bytes = dataset_path.read_bytes()
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load active golden dataset: {exc}") from exc
    cases_from_dataset_bytes(dataset_bytes, str(manifest["truth_version"]))
    rows = [
        json.loads(line)
        for line in dataset_bytes.decode("utf-8").splitlines()
        if line.strip()
    ]
    return manifest, rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    manifest, candidate_rows = _active_dataset(args.root)
    audit_rows = _jsonl(args.audit)
    structural = validate_transition_audit(audit_rows, candidate_rows)
    publication = transition_audit_publication_gate(audit_rows, candidate_rows)
    status_counts = Counter(
        str(row.get("audit_status", "MISSING")) for row in audit_rows
    )
    summary = {
        "truth_version": manifest.get("truth_version"),
        "candidate_st_transition_count": sum(
            row.get("event_class") == "ST_TRANSITION" for row in candidate_rows
        ),
        "audit_row_count": len(audit_rows),
        "audit_status_counts": dict(sorted(status_counts.items())),
        "structural_problems": structural,
        "publication_ready": not publication,
        "publication_problems": publication[:20],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if structural or (args.require_clean and publication):
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"GT-H3R2 audit error: {exc}", file=sys.stderr)
        sys.exit(2)
