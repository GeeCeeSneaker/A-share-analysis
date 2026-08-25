"""Trading-rule dataset review workflow (R4-A2.4 P0-04 + R4-A2.5 P0-02/03).

Rule dataset lifecycle (mirrors golden truth):

    versions/<v-compiled>/rules.yaml   COMPILED candidate (immutable)
    -- reviewer supplies an OFFICIAL source artifact -->
    versions/<v-reviewed>/rules.yaml   REVIEWED copy (immutable, NEW version)
    rule_manifest.json                 ACTIVE selector -> the reviewed version
    evidence/<ref>                     sealed source artifact bytes

The tool computes the artifact's SHA-256 itself, writes the reviewed copy
under a NEW immutable version directory (the COMPILED original is never
modified), stores the artifact under the evidence root, and flips the
ACTIVE manifest. The provenance is verifiable forever after via
``ashare_state.spike.trading_rule.trading_rule_review_gate`` - the gate
resolves ``source_artifact_ref`` RELATIVE TO THE EVIDENCE ROOT (path
confined) and re-hashes the bytes.

Usage:
    uv run python scripts/rules/review.py \
        --rules configs/trading_rules/versions/v20260824-compiled/rules.yaml \
        --artifact docs/evidence/a_share_limit_source.pdf \
        --kind EXCHANGE_NOTICE \
        --reviewer "human-name" \
        --version v20260825-reviewed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.trading_rule import (  # noqa: E402
    RULE_EVIDENCE_SUBDIR,
    RULE_MANIFEST_FILE,
    TradingRuleBook,
    load_active_rules,
    load_rule_manifest,
    trading_rule_review_gate,
)

_KINDS = ("OTHER_OFFICIAL", "EXCHANGE_NOTICE", "REGULATOR_DOC", "DATASET_DOC")


def _dataset_files_hash(root: Path, rel_files: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(rel_files):
        digest.update(rel.replace("\\", "/").encode("utf-8"))
        digest.update((root / rel).read_bytes())
    return digest.hexdigest()


def _rel_under_root(path: Path, root: Path) -> str:
    """Relative path of ``path`` under ``root`` ("" when outside)."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", required=True, help="COMPILED rule yaml to review")
    parser.add_argument("--artifact", required=True, help="official source artifact file")
    parser.add_argument("--kind", required=True, choices=_KINDS)
    parser.add_argument("--reviewer", required=True, help="human reviewer identity")
    parser.add_argument(
        "--version",
        required=True,
        help="new immutable version name (e.g. v20260825-reviewed)",
    )
    parser.add_argument(
        "--rules-root",
        default="configs/trading_rules",
        help="rules root holding versions/ + evidence/ + rule_manifest.json",
    )
    parser.add_argument(
        "--from-version",
        default="",
        help=(
            "expected CURRENT ACTIVE version (lineage check: refuse when the "
            "ACTIVE selector moved elsewhere - avoids reviewing an arbitrary "
            "old/external compiled yaml and silently flipping ACTIVE)"
        ),
    )
    args = parser.parse_args()

    rules_path = Path(args.rules)
    artifact = Path(args.artifact)
    rules_root = Path(args.rules_root)
    if not rules_path.is_file():
        print(f"ERROR: rules file not found: {rules_path}", file=sys.stderr)
        return 2
    if not artifact.is_file():
        print(f"ERROR: source artifact not found: {artifact}", file=sys.stderr)
        return 2

    # R4-A2.6 P1-02: lineage check - the input must be the CURRENT ACTIVE
    # COMPILED version (explicit --from-version, or the manifest itself)
    #
    # R4-A2.8 P0-03 (audit 20260825 #4 section 4.3): the preflight runs the
    # FULL integrity gate FIRST - load_active_rules re-verifies the ACTIVE
    # dataset hash AND manifest<->dataset coherence. A tampered/incoherent
    # ACTIVE can NEVER be re-sealed into a fresh REVIEWED version through
    # this tool: a human review approves a VERIFIED candidate, it does not
    # re-seal an integrity-broken one.
    try:
        active_book, active = load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - clear operator error
        print(
            f"ERROR: ACTIVE dataset failed the integrity preflight (load_active_rules): {exc}",
            file=sys.stderr,
        )
        return 2
    expected_active = args.from_version or active.rule_version
    if active.rule_version != expected_active:
        print(
            f"ERROR: ACTIVE manifest is {active.rule_version!r}, expected "
            f"{expected_active!r} - the selector moved; re-check the lineage "
            "before reviewing",
            file=sys.stderr,
        )
        return 2
    # R4-A2.7 P1-01 (audit 20260825 #3 section 6, Option A): this tool
    # reviews exactly ONE dataset file. A multi-file ACTIVE version is
    # refused EXPLICITLY (fail loud) instead of silently reviewing only
    # the first file.
    if len(active.dataset_files) != 1:
        print(
            f"ERROR: ACTIVE dataset {active.rule_version!r} declares "
            f"{len(active.dataset_files)} files "
            f"({list(active.dataset_files)}) - this tool reviews single-file "
            "datasets only; a multi-file review must seal the COMPLETE file "
            "list (never silently review just the first)",
            file=sys.stderr,
        )
        return 2
    active_rel = active.dataset_files[0] if active.dataset_files else ""
    input_rel = _rel_under_root(rules_path, rules_root)
    if not input_rel or input_rel.replace("\\", "/") != active_rel.replace("\\", "/"):
        print(
            f"ERROR: --rules {input_rel or rules_path} is not the ACTIVE dataset "
            f"({active_rel}) - review the current ACTIVE version or pass an "
            "explicit lineage transition",
            file=sys.stderr,
        )
        return 2
    if active_book.review_status != "COMPILED":
        print(
            "ERROR: the verified ACTIVE dataset is not a COMPILED candidate "
            f"(review_status={active_book.review_status!r}) - only a COMPILED "
            "candidate can be sealed into REVIEWED",
            file=sys.stderr,
        )
        return 2

    # the reviewed copy is generated from the VERIFIED ACTIVE bytes (the
    # load_active_rules preflight above already re-hashed them) - never
    # from a second, unverified read of an arbitrary path
    book = active_book
    if book.review_status == "REVIEWED":
        print(f"ERROR: {rules_path} is already REVIEWED - review once, seal forever")
        return 2

    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    now = datetime.now(UTC).isoformat()
    # seal the artifact bytes under the evidence root (the gate's confined
    # resolution root); ref is RELATIVE to evidence/
    evidence_dir = rules_root / RULE_EVIDENCE_SUBDIR
    evidence_dir.mkdir(parents=True, exist_ok=True)
    artifact_ref = f"{artifact_hash[:16]}-{artifact.name}"
    artifact_copy = evidence_dir / artifact_ref
    if artifact_copy.exists() and artifact_copy.read_bytes() != artifact.read_bytes():
        print(f"ERROR: evidence collision with different bytes: {artifact_ref}", file=sys.stderr)
        return 2
    if not artifact_copy.exists():
        shutil.copy2(artifact, artifact_copy)

    # build the REVIEWED copy under a NEW immutable version directory
    version_dir = rules_root / "versions" / args.version
    if version_dir.exists():
        print(
            f"ERROR: version directory already exists: {version_dir} "
            "(versions are immutable - pick a NEW version name)",
            file=sys.stderr,
        )
        return 2
    # R4-A2.8 P0-03: generate the reviewed copy from the VERIFIED ACTIVE
    # BYTES - read the canonical ACTIVE path and re-verify its hash
    # against the manifest (no TOCTOU window between preflight and read)
    active_path = rules_root / active_rel
    active_bytes = active_path.read_bytes()
    if _dataset_files_hash(rules_root, [active_rel]) != active.dataset_hash:
        print(
            "ERROR: ACTIVE dataset bytes changed during the review "
            "(hash re-verification failed) - aborting, no output written",
            file=sys.stderr,
        )
        return 2
    version_dir.mkdir(parents=True)
    lines = active_bytes.decode("utf-8").splitlines(keepends=True)
    provenance_keys = (
        "reviewed_by:",
        "reviewed_at:",
        "source_artifact_ref:",
        "source_artifact_hash:",
        "source_artifact_kind:",
        "source_retrieved_at:",
    )
    reviewed: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith("review_status:") and not inserted:
            reviewed.append("review_status: REVIEWED\n")
            reviewed.extend(
                [
                    f"reviewed_by: {args.reviewer}\n",
                    f"reviewed_at: {now}\n",
                    f"source_artifact_ref: {artifact_ref}\n",
                    f"source_artifact_hash: {artifact_hash}\n",
                    f"source_artifact_kind: {args.kind}\n",
                    f"source_retrieved_at: {now}\n",
                ]
            )
            inserted = True
        elif line.startswith(provenance_keys):
            # drop COMPILED placeholder provenance (empty values) - keeping
            # them would create DUPLICATE yaml keys whose last (empty)
            # value silently overrides the review seal
            continue
        else:
            reviewed.append(line)
    if not inserted:
        print("ERROR: review_status line not found in the rule yaml", file=sys.stderr)
        return 2
    reviewed_path = version_dir / "rules.yaml"
    reviewed_path.write_text("".join(reviewed), encoding="utf-8")

    # self-verify: the reviewed copy must load and PASS the review gate
    reviewed_book = TradingRuleBook.load(reviewed_path)
    problems = trading_rule_review_gate(reviewed_book, rules_root=rules_root)
    if problems:
        print(f"ERROR: reviewed copy fails the review gate: {problems}", file=sys.stderr)
        return 2

    # flip the ACTIVE manifest to the reviewed version - ATOMIC
    # REPLACEMENT / READER-SAFE (R4-A2.6 P1-02 + R4-A2.7 P1-02): write a
    # temp manifest, then Path.replace - concurrent readers always see
    # either the complete old manifest or the complete new one, never a
    # half-written file. (This is NOT a power-loss durability guarantee -
    # no file/dir fsync is performed; a torn old-or-new state survives an
    # OS crash only as one of the two complete files.)
    dataset_files = [f"versions/{args.version}/rules.yaml"]
    manifest = {
        "rule_version": args.version,
        "review_status": "REVIEWED",
        "dataset_files": dataset_files,
        "dataset_hash": _dataset_files_hash(rules_root, dataset_files),
        "source_version": reviewed_book.source_version,
        "dataset_version": reviewed_book.version,
        "review_provenance": {
            "reviewed_by": args.reviewer,
            "reviewed_at": now,
            "source_artifact_ref": artifact_ref,
            "source_artifact_hash": artifact_hash,
            "source_artifact_kind": args.kind,
            "source_retrieved_at": now,
        },
    }
    manifest_path = rules_root / RULE_MANIFEST_FILE
    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    tmp_manifest = rules_root / f".{RULE_MANIFEST_FILE}.tmp-{args.version}"
    tmp_manifest.write_bytes(manifest_bytes + b"\n")
    tmp_manifest.replace(manifest_path)  # atomic replacement (reader-safe)
    loaded_manifest = load_rule_manifest(rules_root)
    if loaded_manifest.rule_version != args.version:
        print("ERROR: ACTIVE manifest did not flip to the reviewed version", file=sys.stderr)
        return 2
    # coherence self-check: load_active_rules must accept the flipped state
    # (module-level import - a function-local import would shadow the
    # preflight use above)
    try:
        load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - coherence failure must surface
        print(f"ERROR: flipped ACTIVE fails coherence load: {exc}", file=sys.stderr)
        return 2
    print(
        f"REVIEWED version written: {reviewed_path}\n"
        f"  version={args.version} rules={len(reviewed_book.rules)}\n"
        f"  evidence {RULE_EVIDENCE_SUBDIR}/{artifact_ref} sha256={artifact_hash[:16]}...\n"
        f"  ACTIVE manifest -> {args.version}; review gate: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
