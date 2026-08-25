"""Trading-rule dataset review workflow (R4-A2.4 P0-04 + R4-A2.5 P0-02/03).

Rule dataset lifecycle (mirrors golden truth):

    versions/<v-compiled>/rules.yaml   COMPILED candidate (immutable)
    -- reviewer supplies an OFFICIAL source artifact -->
    versions/<v-reviewed>/rules.yaml   REVIEWED copy (immutable, NEW version)
    rule_manifest.json                 ACTIVE selector -> the reviewed version
    evidence/<ref>                     sealed source artifact bytes

R4-A2.9 / CR-1.2.5 (audit 20260825 #5) - EXACT-BYTE SEAL + OUTPUT
CONFINEMENT + STAGED OUTPUT:

Phase 1 - pure validation / snapshot (ZERO output mutation):
    ACTIVE integrity (load_active_rules), from-version lineage,
    single-file support, input == ACTIVE file, ACTIVE COMPILED,
    version-id confinement (lexical single-component grammar +
    resolved confinement + non-existence), ONE-TIME snapshot capture
    whose hash is computed FROM THE SNAPSHOT BYTES (never a second
    filesystem read), artifact read + hash, reviewed copy built IN
    MEMORY from the exact snapshot bytes.

Phase 2 - staged output:
    stage the evidence artifact (content-addressed), stage the reviewed
    version under versions/.staging-<id>/ and run the FULL review gate
    against the staged layout; any failure removes every staged byte.

Phase 3 - publish (ACTIVE manifest LAST):
    atomically move the staging dir into versions/<id>/, then atomically
    replace the ACTIVE manifest.

The invariant enforced throughout:

    hash-checked ACTIVE bytes == bytes transformed == bytes sealed

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
import re
import shutil
import sys
import uuid
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

#: R4-A2.9 P0-02 (audit 20260825 #5 section 3.2): a version id is ONE
#: single path component - starts alphanumeric, then alnum/./_/- only.
#: Rejects traversal, separators, drive prefixes, '.', '..' and any
#: multi-component input BEFORE any output mutation.
_VERSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _hash_snapshot(snapshot: list[tuple[str, bytes]]) -> str:
    """R4-A2.9 P0-01: the manifest dataset-hash algorithm computed over an
    IN-MEMORY snapshot [(rel_path, bytes)] - never a second file read.

    This is the exact algorithm load_rule_manifest/load_active_rules use
    over on-disk files, so a snapshot hash equal to the manifest hash
    proves the captured bytes ARE the ACTIVE dataset bytes."""
    digest = hashlib.sha256()
    for rel, blob in sorted(snapshot):
        digest.update(rel.replace("\\", "/").encode("utf-8"))
        digest.update(blob)
    return digest.hexdigest()


def _rel_under_root(path: Path, root: Path) -> str:
    """Relative path of ``path`` under ``root`` ("" when outside)."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return ""


def _validate_version_id(version: str, rules_root: Path) -> Path:
    """R4-A2.9 P0-02: validate ``--version`` as a single safe path
    component confined to versions/, BEFORE any mutation.

    Step A (lexical, zero fs): single component per _VERSION_ID_RE,
    explicitly not '.'/'..' (no separators can pass the regex anyway).
    Step B (resolved confinement): the candidate must resolve INSIDE
    versions/ (covers symlinked parents).
    Returns the resolved version directory path or raises SystemExit-ish
    ValueError with the rejection reason."""
    if version in (".", ".."):
        msg = f"invalid --version {version!r}: '.'/'..' are not version ids"
        raise ValueError(msg)
    if not _VERSION_ID_RE.match(version):
        msg = (
            f"invalid --version {version!r}: a version id is ONE path "
            "component matching [A-Za-z0-9][A-Za-z0-9._-]* (no '/' or '\\', "
            "no traversal, no drive prefixes)"
        )
        raise ValueError(msg)
    versions_root = (rules_root / "versions").resolve()
    candidate = (versions_root / version).resolve()
    try:
        candidate.relative_to(versions_root)
    except ValueError as exc:
        msg = f"invalid --version {version!r}: escapes the versions root"
        raise ValueError(msg) from exc
    return candidate


def _build_reviewed_text(
    snapshot_bytes: bytes,
    *,
    reviewer: str,
    now: str,
    artifact_ref: str,
    artifact_hash: str,
    kind: str,
) -> str:
    """Build the REVIEWED yaml text IN MEMORY from the EXACT snapshot
    bytes (R4-A2.9 P0-01: hash-checked bytes == bytes transformed)."""
    lines = snapshot_bytes.decode("utf-8").splitlines(keepends=True)
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
                    f"reviewed_by: {reviewer}\n",
                    f"reviewed_at: {now}\n",
                    f"source_artifact_ref: {artifact_ref}\n",
                    f"source_artifact_hash: {artifact_hash}\n",
                    f"source_artifact_kind: {kind}\n",
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
        msg = "review_status line not found in the rule yaml"
        raise ValueError(msg)
    return "".join(reviewed)


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


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

    # ================= Phase 1: pure validation / snapshot =================
    # (audit 20260825 #5 section 4 / section 3.2 Step C: EVERY
    #  deterministic validation completes BEFORE any output mutation)
    if not rules_path.is_file():
        return _fail(f"rules file not found: {rules_path}")
    if not artifact.is_file():
        return _fail(f"source artifact not found: {artifact}")

    # R4-A2.8 P0-03: the preflight runs the FULL integrity gate -
    # load_active_rules re-verifies the ACTIVE dataset hash AND
    # manifest<->dataset coherence. A tampered/incoherent ACTIVE can
    # NEVER be re-sealed into a fresh REVIEWED version through this
    # tool: a human review approves a VERIFIED candidate, it does not
    # re-seal an integrity-broken one.
    try:
        active_book, active = load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - clear operator error
        return _fail(f"ACTIVE dataset failed the integrity preflight (load_active_rules): {exc}")
    expected_active = args.from_version or active.rule_version
    if active.rule_version != expected_active:
        return _fail(
            f"ACTIVE manifest is {active.rule_version!r}, expected "
            f"{expected_active!r} - the selector moved; re-check the lineage "
            "before reviewing"
        )
    # R4-A2.7 P1-01: this tool reviews exactly ONE dataset file.
    if len(active.dataset_files) != 1:
        return _fail(
            f"ACTIVE dataset {active.rule_version!r} declares "
            f"{len(active.dataset_files)} files ({list(active.dataset_files)}) - "
            "this tool reviews single-file datasets only; a multi-file review "
            "must seal the COMPLETE file list (never silently review just the first)"
        )
    active_rel = active.dataset_files[0]
    input_rel = _rel_under_root(rules_path, rules_root)
    if not input_rel or input_rel.replace("\\", "/") != active_rel.replace("\\", "/"):
        return _fail(
            f"--rules {input_rel or rules_path} is not the ACTIVE dataset "
            f"({active_rel}) - review the current ACTIVE version or pass an "
            "explicit lineage transition"
        )
    if active_book.review_status != "COMPILED":
        return _fail(
            f"the verified ACTIVE dataset is not a COMPILED candidate "
            f"(review_status={active_book.review_status!r}) - only a COMPILED "
            "candidate can be sealed into REVIEWED"
        )

    # R4-A2.9 P0-02: version-id confinement BEFORE any mutation (lexical
    # grammar + resolved confinement + non-existence).
    try:
        version_dir = _validate_version_id(args.version, rules_root)
    except ValueError as exc:
        return _fail(str(exc))
    if version_dir.exists():
        return _fail(
            f"version directory already exists: {version_dir} "
            "(versions are immutable - pick a NEW version name)"
        )

    # R4-A2.9 P0-01: EXACT-BYTE SEAL - capture the ACTIVE bytes ONCE and
    # compute the verification hash FROM THE SNAPSHOT. There is no second
    # filesystem read of the ACTIVE file anywhere past this point: the
    # bytes hashed are the bytes transformed into the REVIEWED copy.
    active_path = rules_root / active_rel
    active_bytes = active_path.read_bytes()
    snapshot_hash = _hash_snapshot([(active_rel, active_bytes)])
    if snapshot_hash != active.dataset_hash:
        return _fail(
            "ACTIVE dataset snapshot hash mismatch (declared "
            f"{active.dataset_hash[:16]}..., snapshot {snapshot_hash[:16]}...) - "
            "the file changed during the review; aborting, no output written"
        )

    artifact_bytes = artifact.read_bytes()
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    now = datetime.now(UTC).isoformat()
    # seal the artifact bytes under the evidence root (the gate's confined
    # resolution root); ref is RELATIVE to evidence/
    artifact_ref = f"{artifact_hash[:16]}-{artifact.name}"
    evidence_dir = rules_root / RULE_EVIDENCE_SUBDIR
    artifact_copy = evidence_dir / artifact_ref
    if artifact_copy.exists() and artifact_copy.read_bytes() != artifact_bytes:
        return _fail(f"evidence collision with different bytes: {artifact_ref}")

    # build the REVIEWED copy IN MEMORY from the exact snapshot bytes
    try:
        reviewed_text = _build_reviewed_text(
            active_bytes,
            reviewer=args.reviewer,
            now=now,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            kind=args.kind,
        )
    except ValueError as exc:
        return _fail(str(exc))

    # structural validation of the reviewed copy BEFORE any output: the
    # text must parse as a TradingRuleBook (system temp sandbox - zero
    # rule-store mutation).
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rule-review-") as sandbox:
        sandbox_yaml = Path(sandbox) / "rules.yaml"
        sandbox_yaml.write_text(reviewed_text, encoding="utf-8")
        try:
            TradingRuleBook.load(sandbox_yaml)
        except Exception as exc:  # noqa: BLE001 - parse failure blocks
            return _fail(f"reviewed copy does not parse as a rule dataset: {exc}")

    # ================= Phase 2: staged output =================
    # stage the evidence artifact (content-addressed, idempotent) and the
    # reviewed version under versions/.staging-<id>/, then run the FULL
    # review gate against the staged layout. Any failure here removes
    # every staged byte (no finalized version, no orphan evidence).
    created_evidence = False
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if not artifact_copy.exists():
        artifact_copy.write_bytes(artifact_bytes)
        created_evidence = True
    staging_dir = rules_root / "versions" / f".staging-{args.version}-{uuid.uuid4().hex[:8]}"
    try:
        staging_dir.mkdir(parents=True)
        staged_yaml = staging_dir / "rules.yaml"
        staged_yaml.write_text(reviewed_text, encoding="utf-8")
        # full gate against the staged layout: the evidence artifact is in
        # place so the gate's confined artifact resolution works
        reviewed_book = TradingRuleBook.load(staged_yaml)
        problems = trading_rule_review_gate(reviewed_book, rules_root=rules_root)
        if problems:
            # a `return` inside `try` does NOT trigger the except-cleanup -
            # remove every staged byte explicitly (no finalized version,
            # no orphan evidence) before failing
            shutil.rmtree(staging_dir, ignore_errors=True)
            if created_evidence:
                artifact_copy.unlink(missing_ok=True)
            return _fail(f"reviewed copy fails the review gate: {problems}")
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if created_evidence:
            artifact_copy.unlink(missing_ok=True)
        raise

    # ================= Phase 3: publish (ACTIVE manifest LAST) ============
    try:
        # publish the immutable version (atomic dir rename; the target's
        # non-existence was validated in Phase 1 - a concurrent creation
        # surfaces as a loud failure, never a silent overwrite)
        version_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir.replace(version_dir)
        # flip the ACTIVE manifest - ATOMIC REPLACEMENT / READER-SAFE: a
        # temp manifest then Path.replace; concurrent readers always see
        # either the complete old manifest or the complete new one. (NOT a
        # power-loss durability guarantee - no fsync is performed.)
        dataset_files = [f"versions/{args.version}/rules.yaml"]
        published_bytes = (version_dir / "rules.yaml").read_bytes()
        manifest = {
            "rule_version": args.version,
            "review_status": "REVIEWED",
            "dataset_files": dataset_files,
            "dataset_hash": _hash_snapshot([(dataset_files[0], published_bytes)]),
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
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    loaded_manifest = load_rule_manifest(rules_root)
    if loaded_manifest.rule_version != args.version:
        return _fail("ACTIVE manifest did not flip to the reviewed version")
    # coherence self-check: load_active_rules must accept the flipped state
    try:
        load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - coherence failure must surface
        return _fail(f"flipped ACTIVE fails coherence load: {exc}")
    print(
        f"REVIEWED version written: {version_dir / 'rules.yaml'}\n"
        f"  version={args.version} rules={len(reviewed_book.rules)}\n"
        f"  sealed from ACTIVE snapshot sha256={snapshot_hash[:16]}...\n"
        f"  evidence {RULE_EVIDENCE_SUBDIR}/{artifact_ref} sha256={artifact_hash[:16]}...\n"
        f"  ACTIVE manifest -> {args.version}; review gate: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
