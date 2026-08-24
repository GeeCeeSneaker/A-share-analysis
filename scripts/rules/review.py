"""Trading-rule dataset review workflow (R4-A2.4 P0-04).

Mirrors the golden-truth review discipline for the rule data layer:

    COMPILED (candidate) -> REVIEWED (human-reviewed)

The reviewer supplies an OFFICIAL source artifact (exchange notice /
regulator doc / official dataset doc); the tool computes its SHA-256 and
writes the review provenance INTO a new reviewed copy of the yaml. The
original COMPILED file is never modified in place - the reviewed version
is a new file (``--out``), which the operator then points the ACTIVE
rules at (single-file convention: configs/trading_rules/).

The provenance is verifiable forever after via
``ashare_state.spike.trading_rule.trading_rule_review_gate`` - the gate
resolves ``source_artifact_ref`` under the rules root (or its evidence/
subdir) and re-hashes the bytes.

Usage:
    uv run python scripts/rules/review.py \
        --rules configs/trading_rules/a_share_limit_v1.yaml \
        --artifact docs/evidence/rules/a_share_limit_v1_source.pdf \
        --kind EXCHANGE_NOTICE \
        --reviewer "human-name" \
        --out configs/trading_rules/a_share_limit_v1_reviewed.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.trading_rule import (  # noqa: E402
    TradingRuleBook,
    trading_rule_review_gate,
)

_KINDS = ("OTHER_OFFICIAL", "EXCHANGE_NOTICE", "REGULATOR_DOC", "DATASET_DOC")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", required=True, help="COMPILED rule yaml to review")
    parser.add_argument("--artifact", required=True, help="official source artifact file")
    parser.add_argument("--kind", required=True, choices=_KINDS)
    parser.add_argument("--reviewer", required=True, help="human reviewer identity")
    parser.add_argument("--out", required=True, help="output REVIEWED yaml path")
    args = parser.parse_args()

    rules_path = Path(args.rules)
    artifact = Path(args.artifact)
    out_path = Path(args.out)
    if not rules_path.is_file():
        print(f"ERROR: rules file not found: {rules_path}", file=sys.stderr)
        return 2
    if not artifact.is_file():
        print(f"ERROR: source artifact not found: {artifact}", file=sys.stderr)
        return 2

    book = TradingRuleBook.load(rules_path)
    if book.review_status == "REVIEWED":
        print(f"ERROR: {rules_path} is already REVIEWED - review once, seal forever")
        return 2

    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    now = datetime.now(UTC).isoformat()
    # the artifact must remain resolvable by the review gate: copy it next
    # to the rules (evidence/ convention) unless it already lives there
    rules_dir = rules_path.parent
    evidence_dir = rules_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifact_copy = evidence_dir / artifact.name
    if artifact.resolve() != artifact_copy.resolve():
        shutil.copy2(artifact, artifact_copy)

    lines = rules_path.read_text(encoding="utf-8").splitlines(keepends=True)
    provenance_keys = (
        "reviewed_by:",
        "reviewed_at:",
        "source_artifact_ref:",
        "source_artifact_hash:",
        "source_artifact_kind:",
        "source_retrieved_at:",
    )
    reviewed = []
    inserted = False
    for line in lines:
        if line.startswith("review_status:") and not inserted:
            reviewed.append("review_status: REVIEWED\n")
            reviewed.extend(
                [
                    f"reviewed_by: {args.reviewer}\n",
                    f"reviewed_at: {now}\n",
                    f"source_artifact_ref: evidence/{artifact.name}\n",
                    f"source_artifact_hash: {artifact_hash}\n",
                    f"source_artifact_kind: {args.kind}\n",
                    f"source_retrieved_at: {now}\n",
                ]
            )
            inserted = True
        elif line.startswith(provenance_keys):
            # drop the COMPILED placeholder provenance (empty values) -
            # keeping them would create DUPLICATE yaml keys whose last
            # (empty) value silently overrides the review seal
            continue
        else:
            reviewed.append(line)
    if not inserted:
        print("ERROR: review_status line not found in the rule yaml", file=sys.stderr)
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(reviewed), encoding="utf-8")

    # self-verify: the written file must PASS the review gate
    reviewed_book = TradingRuleBook.load(out_path)
    problems = trading_rule_review_gate(reviewed_book, rules_root=out_path.parent)
    if problems:
        print(f"ERROR: reviewed copy fails the review gate: {problems}", file=sys.stderr)
        return 2
    print(
        f"REVIEWED dataset written: {out_path}\n"
        f"  version={reviewed_book.version} rules={len(reviewed_book.rules)}\n"
        f"  source artifact evidence/{artifact.name} sha256={artifact_hash[:16]}...\n"
        f"  review gate: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
