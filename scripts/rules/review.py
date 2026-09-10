"""Trading-rule dataset review workflow (R4-A2.4 P0-04 + R4-A2.5 P0-02/03).

Rule dataset lifecycle (mirrors golden truth):

    versions/<v-compiled>/rules.yaml   COMPILED candidate (immutable)
    -- reviewer supplies an OFFICIAL source artifact -->
    versions/<v-reviewed>/rules.yaml   REVIEWED copy (immutable, NEW version)
    rule_manifest.json                 ACTIVE selector -> the reviewed version
    evidence/<ref>                     sealed bundle + raw source bytes

R4-A2.9 / CR-1.2.5 (audit 20260825 #5) - EXACT-BYTE SEAL + OUTPUT
CONFINEMENT + STAGED OUTPUT:

Phase 1 - pure validation / snapshot (ZERO output mutation):
    ACTIVE integrity (load_active_rules), from-version lineage,
    single-file support, input == ACTIVE file, ACTIVE COMPILED,
    version-id confinement (lexical single-component grammar +
    resolved confinement + non-existence), ONE-TIME source snapshot capture
    whose hash is computed FROM THE SNAPSHOT BYTES, artifact read + hash,
    reviewed copy built IN MEMORY from the exact snapshot bytes. Candidate
    read-backs, when used, are verification-only and never replace the
    source snapshot.

Phase 2 - staged output:
    stage the evidence bundle and all raw artifacts (content-addressed), stage the reviewed
    version under versions/.staging-<id>/ and run the FULL review gate
    against the staged layout; any failure removes every staged byte.

Phase 3 - publish (ACTIVE manifest LAST):
    atomically move the staging dir into versions/<id>/, then atomically
    replace the ACTIVE manifest.

The invariant enforced throughout:

    hash-checked ACTIVE bytes == bytes transformed == bytes sealed

The tool computes every source and bundle SHA-256 itself, writes the reviewed
copy under a NEW immutable version directory (the COMPILED original is never
modified), stores the bundle and raw sources under the evidence root, and
flips the ACTIVE manifest. The provenance is verifiable forever after via
``ashare_state.spike.trading_rule.trading_rule_review_gate`` - the gate
resolves the bundle and every raw source RELATIVE TO THE EVIDENCE ROOT (path
confined) and re-hashes the bytes. Production requires the bundle form.

Usage:
    uv run python scripts/rules/review.py \
        --rules configs/trading_rules/versions/v20260824-compiled/rules.yaml \
        --evidence-bundle docs/provider_verification/trading_rule_h1_evidence_input.json \
        --reviewer "human-name" \
        --version v20260825-reviewed \
        --from-version v20260824-compiled

The H1 production candidate path is explicit and does not require making the
candidate ACTIVE first:

    uv run python scripts/rules/review.py \
        --candidate configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml \
        --candidate-version v20260909-h1-compiled \
        --expected-candidate-hash <manifest-style-sha256> \
        --evidence-bundle <prepared-bundle.json> \
        --reviewer owner-authorized-ai-reviewer \
        --version v20260909-h1-reviewed \
        --from-version v20260824-compiled

The candidate path requires the explicit expected ACTIVE parent, candidate
directory identity, and candidate dataset hash. It keeps the candidate
non-ACTIVE until the final atomic manifest replacement.

The legacy ``--artifact`` mode remains available for compatibility tests and
non-production tooling; it cannot satisfy the strict production review gate.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.rule_evidence import (  # noqa: E402
    RULE_EVIDENCE_BUNDLE_HASH,
    RULE_EVIDENCE_BUNDLE_KIND,
    RULE_EVIDENCE_BUNDLE_REF,
    RULE_EVIDENCE_BUNDLE_SCHEMA,
    PreparedRuleEvidenceBundle,
    RawRuleEvidence,
    prepare_rule_evidence_bundle,
    source_urls_from_ref,
)
from ashare_state.spike.trading_rule import (  # noqa: E402
    RULE_EVIDENCE_SUBDIR,
    RULE_MANIFEST_FILE,
    TradingRuleBook,
    load_active_rules,
    load_rule_manifest,
    trading_rule_review_gate,
)

_KINDS = (
    "OTHER_OFFICIAL",
    "EXCHANGE_NOTICE",
    "REGULATOR_DOC",
    "DATASET_DOC",
    RULE_EVIDENCE_BUNDLE_KIND,
)

# Candidate sealing records the actor's truthful provenance.  The
# owner-authorized AI marker is intentionally explicit: it is not a claim
# that the project owner personally performed the evidence review.
_CANDIDATE_REVIEWER_MARKERS = frozenset({"project-owner", "owner-authorized-ai-reviewer"})

#: R4-A2.9 P0-02 (audit 20260825 #5 section 3.2): a version id is ONE
#: single path component - starts alphanumeric, then alnum/./_/- only.
#: Rejects traversal, separators, drive prefixes, '.', '..' and any
#: multi-component input BEFORE any output mutation.
_VERSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class _ReviewEvidence:
    __slots__ = (
        "artifact_ref",
        "artifact_hash",
        "artifact_kind",
        "artifact_bytes",
        "raw_artifacts",
        "evidence_contract",
    )

    def __init__(
        self,
        *,
        artifact_ref: str,
        artifact_hash: str,
        artifact_kind: str,
        artifact_bytes: bytes,
        raw_artifacts: tuple[RawRuleEvidence, ...] = (),
        evidence_contract: str = "",
    ) -> None:
        self.artifact_ref = artifact_ref
        self.artifact_hash = artifact_hash
        self.artifact_kind = artifact_kind
        self.artifact_bytes = artifact_bytes
        self.raw_artifacts = raw_artifacts
        self.evidence_contract = evidence_contract


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


def _validate_candidate_path(
    candidate: Path,
    *,
    candidate_version: str,
    rules_root: Path,
) -> tuple[Path, str]:
    """Validate the H1 candidate path before reading any candidate bytes.

    The candidate is intentionally narrower than the legacy ``--rules``
    input: it must be exactly ``versions/<candidate-version>/rules.yaml``.
    This prevents a caller from supplying an arbitrary external file, a
    traversal spelling, or a staging/symlink path while still claiming to
    seal the named version.
    """
    if candidate_version.startswith(".staging-"):
        raise ValueError("candidate version must not be a staging version")
    version_dir = _validate_version_id(candidate_version, rules_root)
    versions_root_raw = rules_root / "versions"
    versions_root = versions_root_raw.resolve()
    if versions_root_raw.is_symlink():
        raise ValueError("candidate versions root must not be a symlink")
    raw_version_dir = versions_root_raw / candidate_version
    if raw_version_dir.is_symlink():
        raise ValueError("candidate version directory must not be a symlink")
    if not version_dir.is_dir():
        raise ValueError(f"candidate version directory not found: {raw_version_dir}")

    candidate_text = str(candidate).replace("\\", "/")
    if any(part in (".", "..") for part in candidate_text.split("/")):
        raise ValueError("candidate path must not contain '.' or '..' components")
    root_abs = rules_root.absolute()
    candidate_abs = candidate if candidate.is_absolute() else Path.cwd() / candidate
    expected_abs = root_abs / "versions" / candidate_version / "rules.yaml"
    normalized_candidate = os.path.normcase(os.path.normpath(str(candidate_abs)))
    normalized_expected = os.path.normcase(os.path.normpath(str(expected_abs)))
    if normalized_candidate != normalized_expected:
        raise ValueError(
            "candidate path must be exactly "
            f"versions/{candidate_version}/rules.yaml under the rules root"
        )
    if candidate_abs.is_symlink():
        raise ValueError("candidate rules file must not be a symlink")
    if not candidate_abs.is_file():
        raise ValueError(f"candidate rules file not found: {candidate_abs}")
    resolved = candidate_abs.resolve()
    try:
        resolved.relative_to(versions_root)
    except ValueError as exc:
        raise ValueError("candidate path escapes the versions root") from exc
    if resolved != (version_dir / "rules.yaml").resolve():
        raise ValueError("candidate path resolves to a different version file")
    return candidate_abs, f"versions/{candidate_version}/rules.yaml"


def _candidate_file_identity(path: Path) -> tuple[int, int] | None:
    """Return a portable replacement-detection identity when available."""

    stat = path.stat()
    if not stat.st_ino:
        return None
    return stat.st_dev, stat.st_ino


def _verify_candidate_snapshot(
    *,
    candidate_file: Path,
    candidate_version: str,
    rules_root: Path,
    candidate_rel: str,
    snapshot_bytes: bytes,
    snapshot_hash: str,
    snapshot_file_identity: tuple[int, int] | None,
) -> str:
    """Verify the candidate still matches its captured identity.

    The read in this function is deliberately a read-back only. Its bytes
    are compared with the original snapshot and its derived hash is compared
    with ``snapshot_hash``; neither is ever used to build or rebind the
    reviewed output. This closes the gap between the one-time source read
    and the final ACTIVE manifest commit while keeping the source of truth
    bound to the original in-memory snapshot.
    """

    try:
        verified_file, verified_rel = _validate_candidate_path(
            candidate_file,
            candidate_version=candidate_version,
            rules_root=rules_root,
        )
        verified_identity = _candidate_file_identity(verified_file)
        verification_bytes = verified_file.read_bytes()
    except (OSError, ValueError) as exc:
        return f"candidate identity verification failed: {exc}"
    if verified_rel != candidate_rel:
        return (
            "candidate identity verification failed: candidate relative path "
            f"changed from {candidate_rel!r} to {verified_rel!r}"
        )
    if snapshot_file_identity is not None and verified_identity != snapshot_file_identity:
        return "candidate file identity changed after the source snapshot"
    if verification_bytes != snapshot_bytes:
        return "candidate bytes changed after the source snapshot"
    verification_hash = _hash_snapshot([(verified_rel, verification_bytes)])
    if verification_hash != snapshot_hash:
        return "candidate snapshot verification hash changed after the source snapshot"
    return ""


def _load_snapshot_book(snapshot_bytes: bytes) -> TradingRuleBook:
    """Parse a version book from already captured bytes.

    The temporary file is deliberately separate from the mutable rule store:
    the candidate file is read once by the caller, and all later parsing uses
    this immutable in-memory byte object.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rule-candidate-") as sandbox:
        sandbox_yaml = Path(sandbox) / "rules.yaml"
        sandbox_yaml.write_bytes(snapshot_bytes)
        return TradingRuleBook.load(sandbox_yaml)


def _build_reviewed_text(
    snapshot_bytes: bytes,
    *,
    reviewer: str,
    now: str,
    artifact_ref: str,
    artifact_hash: str,
    kind: str,
    evidence_contract: str = "",
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
        RULE_EVIDENCE_BUNDLE_REF + ":",
        RULE_EVIDENCE_BUNDLE_HASH + ":",
        "evidence_contract:",
    )
    reviewed: list[str] = []
    inserted = False
    skipping_review_note = False
    final_review_note_inserted = False
    for line in lines:
        # A COMPILED candidate may carry a multiline review_note explaining
        # that it is not yet reviewed.  That note is stale in the REVIEWED
        # copy, so consume the complete YAML scalar instead of leaking its
        # candidate-only provenance into the sealed artifact.
        if skipping_review_note:
            if not line.strip() or line[:1].isspace():
                continue
            skipping_review_note = False
        if line.startswith("review_note:"):
            if reviewer == "owner-authorized-ai-reviewer" and not final_review_note_inserted:
                reviewed.extend(
                    [
                        "review_note: >\n",
                        (
                            "  Evidence was sealed under the owner-authorized AI reviewer "
                            "provenance marker.\n"
                        ),
                    ]
                )
                final_review_note_inserted = True
            skipping_review_note = True
            continue
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
            if evidence_contract:
                reviewed.extend(
                    [
                        f"evidence_contract: {evidence_contract}\n",
                        f"{RULE_EVIDENCE_BUNDLE_REF}: {artifact_ref}\n",
                        f"{RULE_EVIDENCE_BUNDLE_HASH}: {artifact_hash}\n",
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


def _prepare_review_evidence(
    *,
    artifact: Path | None,
    bundle_manifest: Path | None,
    expected_rule_ids: list[str],
    expected_dataset_version: str,
    expected_source_urls_by_rule: dict[str, tuple[str, ...]],
    kind: str,
) -> _ReviewEvidence:
    if bundle_manifest is not None:
        prepared: PreparedRuleEvidenceBundle = prepare_rule_evidence_bundle(
            bundle_manifest,
            expected_rule_ids=expected_rule_ids,
            expected_dataset_version=expected_dataset_version,
            expected_source_urls_by_rule=expected_source_urls_by_rule,
        )
        bundle_hash = hashlib.sha256(prepared.content).hexdigest()
        return _ReviewEvidence(
            artifact_ref=f"sha256/{bundle_hash}",
            artifact_hash=bundle_hash,
            artifact_kind=RULE_EVIDENCE_BUNDLE_KIND,
            artifact_bytes=prepared.content,
            raw_artifacts=prepared.raw_artifacts,
            evidence_contract=RULE_EVIDENCE_BUNDLE_SCHEMA,
        )
    if artifact is None:
        raise ValueError("one of --artifact or --evidence-bundle is required")
    artifact_bytes = artifact.read_bytes()
    artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
    return _ReviewEvidence(
        artifact_ref=f"{artifact_hash[:16]}-{artifact.name}",
        artifact_hash=artifact_hash,
        artifact_kind=kind,
        artifact_bytes=artifact_bytes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    rules_input = parser.add_mutually_exclusive_group(required=True)
    rules_input.add_argument(
        "--rules",
        help="COMPILED ACTIVE rule yaml to review (legacy compatibility path)",
    )
    rules_input.add_argument(
        "--candidate",
        help=(
            "explicit non-ACTIVE COMPILED candidate yaml for the H1 seal path; "
            "must be under versions/<candidate-version>/rules.yaml"
        ),
    )
    evidence_input = parser.add_mutually_exclusive_group(required=True)
    evidence_input.add_argument(
        "--artifact",
        help="one official source artifact file (legacy single-artifact mode)",
    )
    evidence_input.add_argument(
        "--evidence-bundle",
        dest="evidence_bundle",
        help=(
            "input RULE_EVIDENCE_BUNDLE.v1 JSON; each source must provide "
            "artifact_path, official source_url, kind, and role"
        ),
    )
    parser.add_argument(
        "--kind",
        choices=_KINDS[:-1],
        help="artifact kind for legacy --artifact mode",
    )
    parser.add_argument(
        "--reviewer",
        required=True,
        help=(
            "reviewer identity or truthful provenance marker; --candidate "
            "allows 'project-owner' or 'owner-authorized-ai-reviewer'"
        ),
    )
    parser.add_argument(
        "--version",
        required=True,
        help="new immutable version name (e.g. v20260825-reviewed)",
    )
    parser.add_argument(
        "--candidate-version",
        default="",
        help=(
            "candidate directory identity for --candidate; required for the "
            "explicit H1 candidate path"
        ),
    )
    parser.add_argument(
        "--expected-candidate-hash",
        "--candidate-dataset-hash",
        dest="expected_candidate_hash",
        default="",
        help=(
            "frozen manifest-style SHA-256 over "
            "versions/<candidate-version>/rules.yaml + bytes; required for --candidate"
        ),
    )
    parser.add_argument(
        "--rules-root",
        default="configs/trading_rules",
        help="rules root holding versions/ + evidence/ + rule_manifest.json",
    )
    parser.add_argument(
        "--from-version",
        "--expected-active-version",
        dest="from_version",
        default="",
        help=(
            "expected CURRENT ACTIVE parent version (lineage check; required "
            "for --candidate and optional for legacy --rules)"
        ),
    )
    args = parser.parse_args()
    if args.artifact and not args.kind:
        parser.error("--kind is required with --artifact")
    if args.evidence_bundle and args.kind:
        parser.error("--kind is only valid with --artifact")
    if args.candidate and args.artifact:
        parser.error("--candidate requires --evidence-bundle, not legacy --artifact")
    if args.candidate and args.reviewer not in _CANDIDATE_REVIEWER_MARKERS:
        parser.error(
            "--candidate requires reviewer marker one of: "
            "'project-owner', 'owner-authorized-ai-reviewer'"
        )
    if args.candidate and not args.from_version:
        parser.error("--candidate requires --from-version/--expected-active-version")
    if args.candidate and not args.candidate_version:
        parser.error("--candidate requires --candidate-version")
    if args.candidate and not args.expected_candidate_hash:
        parser.error("--candidate requires --expected-candidate-hash")

    rules_path = Path(args.rules) if args.rules else None
    candidate_path = Path(args.candidate) if args.candidate else None
    artifact = Path(args.artifact) if args.artifact else None
    bundle_manifest = Path(args.evidence_bundle) if args.evidence_bundle else None
    rules_root = Path(args.rules_root)

    # ================= Phase 0: lock acquisition =================
    # R4-A2.11 P0-01 (audit 20260825 #7 section 3.1, Option A): the
    # single-writer lock MUST be acquired BEFORE every ACTIVE-dependent /
    # mutable-version-store read. The previous placement (lock after the
    # snapshot/sandbox) serialized only Phase 2/3 - two reviewers could
    # both complete Phase 1 against the SAME parent, then commit in turn:
    # the second would overwrite the first's ACTIVE advance with a
    # stale-parent seal. Lock-before-preflight makes PARENT SELECTION
    # itself serialized; "Phase 2/3 serial" != "review parent lineage
    # serial".
    #
    # Allowed BEFORE the lock: CLI parse + pure lexical argument checks +
    # basic rules_root existence - none of these read the ACTIVE selector
    # or the mutable version store.
    if rules_path is not None and not rules_path.is_file():
        return _fail(f"rules file not found: {rules_path}")
    if artifact is not None and not artifact.is_file():
        return _fail(f"source artifact not found: {artifact}")
    if bundle_manifest is not None and not bundle_manifest.is_file():
        return _fail(f"evidence bundle manifest not found: {bundle_manifest}")

    import os as os_mod

    lock_path = rules_root / ".review.lock"
    try:
        lock_fd = os_mod.open(lock_path, os_mod.O_CREAT | os_mod.O_EXCL | os_mod.O_WRONLY)
    except FileExistsError:
        return _fail(
            "another review appears to be in progress (.review.lock exists) - "
            "if no review is actually running, remove the stale lock file "
            f"manually: {lock_path}"
        )
    try:
        os_mod.write(
            lock_fd,
            f"pid={os_mod.getpid()} started={datetime.now(UTC).isoformat()}".encode(),
        )
        os_mod.close(lock_fd)
        if candidate_path is not None:
            return _candidate_review_workflow_locked(
                rules_root=rules_root,
                candidate_path=candidate_path,
                candidate_version=args.candidate_version,
                expected_candidate_hash=args.expected_candidate_hash,
                bundle_manifest=bundle_manifest,
                expected_active_version=args.from_version,
                version=args.version,
                reviewer=args.reviewer,
            )
        assert rules_path is not None
        return _review_workflow_locked(
            rules_root=rules_root,
            rules_path=rules_path,
            artifact=artifact,
            bundle_manifest=bundle_manifest,
            from_version=args.from_version,
            version=args.version,
            reviewer=args.reviewer,
            kind=args.kind or RULE_EVIDENCE_BUNDLE_KIND,
        )
    finally:
        lock_path.unlink(missing_ok=True)


def _candidate_review_workflow_locked(
    *,
    rules_root: Path,
    candidate_path: Path,
    candidate_version: str,
    expected_candidate_hash: str,
    bundle_manifest: Path | None,
    expected_active_version: str,
    version: str,
    reviewer: str,
) -> int:
    """Seal one explicit non-ACTIVE COMPILED candidate under the lock.

    This is the H1 production path. The current ACTIVE dataset is only the
    expected parent; the candidate is read once into ``candidate_bytes`` and
    all evidence contracts, parsing, transformation, and dataset identity
    checks use that snapshot. ACTIVE is not changed until the shared staged
    workflow has passed every gate.
    """
    if reviewer not in _CANDIDATE_REVIEWER_MARKERS:
        return _fail(
            "H1 candidate seal requires reviewer marker one of: "
            "'project-owner', 'owner-authorized-ai-reviewer'"
        )
    if not expected_active_version:
        return _fail("H1 candidate seal requires an explicit expected ACTIVE parent")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_candidate_hash):
        return _fail("expected candidate hash must be 64 lower-hex characters")

    try:
        active_book, active = load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - clear operator error
        return _fail(f"ACTIVE parent failed the integrity preflight: {exc}")
    if active.rule_version != expected_active_version:
        return _fail(
            f"ACTIVE parent is {active.rule_version!r}, expected "
            f"{expected_active_version!r} - the selector moved"
        )
    if active.review_status != "COMPILED":
        return _fail(f"expected ACTIVE parent must be COMPILED, got {active.review_status!r}")
    if len(active.dataset_files) != 1:
        return _fail(
            "H1 candidate seal requires a single-file ACTIVE parent; "
            f"got {list(active.dataset_files)!r}"
        )

    try:
        candidate_file, candidate_rel = _validate_candidate_path(
            candidate_path,
            candidate_version=candidate_version,
            rules_root=rules_root,
        )
    except ValueError as exc:
        return _fail(str(exc))
    active_rel = active.dataset_files[0].replace("\\", "/")
    if candidate_rel == active_rel or candidate_version == active.rule_version:
        return _fail("H1 candidate must be non-ACTIVE and distinct from the expected parent")

    # Candidate source bytes are read exactly once from the mutable version
    # store. The returned object is the only source used by the transform and
    # the frozen candidate hash. Any later candidate read is verification-only
    # and cannot substitute new bytes.
    try:
        candidate_file_identity = _candidate_file_identity(candidate_file)
        candidate_bytes = candidate_file.read_bytes()
    except OSError as exc:
        return _fail(f"candidate file could not be read or identified: {exc}")
    candidate_hash = _hash_snapshot([(candidate_rel, candidate_bytes)])
    if candidate_hash != expected_candidate_hash:
        return _fail(
            "candidate dataset hash mismatch: expected "
            f"{expected_candidate_hash[:16]}..., snapshot {candidate_hash[:16]}..."
        )
    try:
        candidate_book = _load_snapshot_book(candidate_bytes)
    except (OSError, UnicodeError, ValueError) as exc:
        return _fail(f"candidate snapshot does not parse as a rule dataset: {exc}")
    if candidate_book.review_status != "COMPILED":
        return _fail(f"candidate snapshot must be COMPILED, got {candidate_book.review_status!r}")
    if candidate_book.evidence_contract != RULE_EVIDENCE_BUNDLE_SCHEMA:
        return _fail(
            f"H1 candidate snapshot must declare evidence_contract={RULE_EVIDENCE_BUNDLE_SCHEMA!r}"
        )
    if not candidate_book.version:
        return _fail("candidate snapshot must declare a non-empty dataset version")
    try:
        reviewed_version_dir = _validate_version_id(version, rules_root)
    except ValueError as exc:
        return _fail(str(exc))
    if reviewed_version_dir.exists():
        return _fail(
            f"version directory already exists: {reviewed_version_dir} "
            "(versions are immutable - pick a NEW version name)"
        )

    now = datetime.now(UTC).isoformat()
    try:
        review_evidence = _prepare_review_evidence(
            artifact=None,
            bundle_manifest=bundle_manifest,
            expected_rule_ids=[rule.rule_id for rule in candidate_book.rules],
            expected_dataset_version=candidate_book.version,
            expected_source_urls_by_rule={
                rule.rule_id: source_urls_from_ref(rule.source_ref) for rule in candidate_book.rules
            },
            kind=RULE_EVIDENCE_BUNDLE_KIND,
        )
    except (OSError, ValueError) as exc:
        return _fail(f"review evidence preparation failed: {exc}")
    artifact_bytes = review_evidence.artifact_bytes
    artifact_hash = review_evidence.artifact_hash
    artifact_ref = review_evidence.artifact_ref
    try:
        reviewed_text = _build_reviewed_text(
            candidate_bytes,
            reviewer=reviewer,
            now=now,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            kind=review_evidence.artifact_kind,
            evidence_contract=review_evidence.evidence_contract,
        )
    except (UnicodeError, ValueError) as exc:
        return _fail(f"candidate snapshot could not be transformed: {exc}")
    reviewed_bytes = reviewed_text.encode("utf-8")
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rule-review-") as sandbox:
        sandbox_yaml = Path(sandbox) / "rules.yaml"
        sandbox_yaml.write_bytes(reviewed_bytes)
        try:
            TradingRuleBook.load(sandbox_yaml)
        except Exception as exc:  # noqa: BLE001 - parse failure blocks
            return _fail(f"reviewed candidate copy does not parse: {exc}")

    return _review_locked_workflow(
        rules_root=rules_root,
        snapshot_hash=candidate_hash,
        version=version,
        version_dir=reviewed_version_dir,
        reviewed_bytes=reviewed_bytes,
        artifact_bytes=artifact_bytes,
        artifact_hash=artifact_hash,
        artifact_ref=artifact_ref,
        artifact_copy=rules_root / RULE_EVIDENCE_SUBDIR / artifact_ref,
        raw_artifacts=review_evidence.raw_artifacts,
        reviewer=reviewer,
        now=now,
        kind=review_evidence.artifact_kind,
        evidence_contract=review_evidence.evidence_contract,
        expected_parent_version=active.rule_version,
        expected_parent_dataset_hash=active.dataset_hash,
        expected_parent_dataset_files=active.dataset_files,
        source_rule_identity=candidate_book.rules,
        candidate_file=candidate_file,
        candidate_version=candidate_version,
        candidate_rel=candidate_rel,
        candidate_snapshot_bytes=candidate_bytes,
        candidate_snapshot_file_identity=candidate_file_identity,
    )


def _expected_parent_problem(
    *,
    rules_root: Path,
    expected_version: str,
    expected_dataset_hash: str,
    expected_dataset_files: tuple[str, ...],
) -> str:
    """Return a stale/tampered ACTIVE-parent error without mutating output."""
    try:
        _book, current = load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - parent must remain loadable
        return f"ACTIVE parent changed or became invalid during seal: {exc}"
    if current.rule_version != expected_version:
        return (
            f"ACTIVE parent moved during seal: current {current.rule_version!r}, "
            f"expected {expected_version!r}"
        )
    if current.dataset_hash != expected_dataset_hash:
        return "ACTIVE parent dataset hash changed during seal"
    if current.dataset_files != expected_dataset_files:
        return "ACTIVE parent dataset file list changed during seal"
    return ""


def _verify_parent_snapshot(
    *,
    rules_root: Path,
    expected_dataset_hash: str,
    expected_dataset_files: tuple[str, ...],
) -> str:
    """Verify the old parent bytes after the ACTIVE commit."""

    if len(expected_dataset_files) != 1:
        return "expected ACTIVE parent no longer has a single dataset file"
    expected_rel = expected_dataset_files[0].replace("\\", "/")
    parent_path = rules_root / expected_rel
    try:
        parent_path.resolve().relative_to(rules_root.resolve())
        parent_bytes = parent_path.read_bytes()
    except (OSError, ValueError) as exc:
        return f"old ACTIVE parent snapshot verification failed: {exc}"
    actual_hash = _hash_snapshot([(expected_rel, parent_bytes)])
    if actual_hash != expected_dataset_hash:
        return "old ACTIVE parent bytes changed after ACTIVE manifest commit"
    return ""


def _review_workflow_locked(
    *,
    rules_root: Path,
    rules_path: Path,
    artifact: Path | None,
    bundle_manifest: Path | None,
    from_version: str,
    version: str,
    reviewer: str,
    kind: str,
) -> int:
    """The ENTIRE review workflow, executed under the single-writer lock
    (R4-A2.11 P0-01, Option A): ACTIVE integrity + parent identity
    (load_active_rules / lineage / COMPILED / version confinement +
    non-existence) -> ACTIVE snapshot -> review transform -> sandbox parse
    -> staged review gate -> publish -> ACTIVE manifest commit ->
    post-commit verification - ALL inside the serialization boundary.
    The lock is advisory + process-scoped (a stale lock after a crash must
    be removed manually) - this is NOT an OS-level CAS, and the ADR
    records that limitation honestly."""
    # ================= Phase 1: pure validation / snapshot =================
    # (audit 20260825 #5 section 4 / section 3.2 Step C: EVERY
    #  deterministic validation completes BEFORE any output mutation)

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
    expected_active = from_version or active.rule_version
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
        version_dir = _validate_version_id(version, rules_root)
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

    now = datetime.now(UTC).isoformat()
    try:
        review_evidence = _prepare_review_evidence(
            artifact=artifact,
            bundle_manifest=bundle_manifest,
            expected_rule_ids=[rule.rule_id for rule in active_book.rules],
            expected_dataset_version=active_book.version,
            expected_source_urls_by_rule={
                rule.rule_id: source_urls_from_ref(rule.source_ref) for rule in active_book.rules
            },
            kind=kind,
        )
    except (OSError, ValueError) as exc:
        return _fail(f"review evidence preparation failed: {exc}")
    artifact_bytes = review_evidence.artifact_bytes
    artifact_hash = review_evidence.artifact_hash
    artifact_ref = review_evidence.artifact_ref
    evidence_dir = rules_root / RULE_EVIDENCE_SUBDIR
    artifact_copy = evidence_dir / artifact_ref
    if artifact_copy.exists() and artifact_copy.read_bytes() != artifact_bytes:
        return _fail(f"evidence collision with different bytes: {artifact_ref}")
    for raw in review_evidence.raw_artifacts:
        raw_copy = evidence_dir / raw.artifact_ref
        if raw_copy.exists() and raw_copy.read_bytes() != raw.content:
            return _fail(f"evidence collision with different bytes: {raw.artifact_ref}")

    # build the REVIEWED copy IN MEMORY from the exact snapshot bytes.
    # R4-A2.10 P0-01 (audit 20260825 #6 section 2): the transformed
    # identity is an immutable BYTES object. Path.write_text() would let
    # the OS text-mode newline translation rewrite LF to CRLF on Windows,
    # making persisted bytes != exact transformed bytes. Every formal
    # dataset write below uses write_bytes(reviewed_bytes) ONLY.
    try:
        reviewed_text = _build_reviewed_text(
            active_bytes,
            reviewer=reviewer,
            now=now,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            kind=review_evidence.artifact_kind,
            evidence_contract=review_evidence.evidence_contract,
        )
    except ValueError as exc:
        return _fail(str(exc))
    reviewed_bytes = reviewed_text.encode("utf-8")

    # structural validation of the reviewed copy BEFORE any output: the
    # bytes must parse as a TradingRuleBook (system temp sandbox - zero
    # rule-store mutation, byte-identical write).
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rule-review-") as sandbox:
        sandbox_yaml = Path(sandbox) / "rules.yaml"
        sandbox_yaml.write_bytes(reviewed_bytes)
        try:
            TradingRuleBook.load(sandbox_yaml)
        except Exception as exc:  # noqa: BLE001 - parse failure blocks
            return _fail(f"reviewed copy does not parse as a rule dataset: {exc}")

    # R4-A2.11 P0-01 (Option A): the staged publish workflow runs inside
    # the SAME lock scope - parent selection, snapshot, staged gate,
    # publish, manifest commit and post-commit verification are ALL
    # within the single-writer serialization boundary.
    return _review_locked_workflow(
        rules_root=rules_root,
        snapshot_hash=snapshot_hash,
        version=version,
        version_dir=version_dir,
        reviewed_bytes=reviewed_bytes,
        artifact_bytes=artifact_bytes,
        artifact_hash=artifact_hash,
        artifact_ref=artifact_ref,
        artifact_copy=artifact_copy,
        raw_artifacts=review_evidence.raw_artifacts,
        reviewer=reviewer,
        now=now,
        kind=review_evidence.artifact_kind,
        evidence_contract=review_evidence.evidence_contract,
    )


def _review_locked_workflow(
    *,
    rules_root: Path,
    snapshot_hash: str,
    version: str,
    version_dir: Path,
    reviewed_bytes: bytes,
    artifact_bytes: bytes,
    artifact_hash: str,
    artifact_ref: str,
    artifact_copy: Path,
    raw_artifacts: tuple[RawRuleEvidence, ...],
    reviewer: str,
    now: str,
    kind: str,
    evidence_contract: str,
    expected_parent_version: str = "",
    expected_parent_dataset_hash: str = "",
    expected_parent_dataset_files: tuple[str, ...] = (),
    source_rule_identity: tuple[object, ...] | None = None,
    candidate_file: Path | None = None,
    candidate_version: str = "",
    candidate_rel: str = "",
    candidate_snapshot_bytes: bytes | None = None,
    candidate_snapshot_file_identity: tuple[int, int] | None = None,
) -> int:
    """The staged review workflow, executed under the single-writer lock.

    Commit boundary (R4-A2.10 P1-01, audit 20260825 #6 section 4):
      - BEFORE the ACTIVE manifest atomic replace succeeds, every failure
        is UNCOMMITTED: the newly published version dir, the evidence
        artifact created by THIS run, and the tmp manifest are removed;
        ACTIVE stays on the old selector; a same-version retry works.
      - AFTER the manifest replace succeeds the operation is COMMITTED:
        a post-commit verification failure is an explicit
        REVIEW_COMMIT_INCONSISTENT hard failure (exit code 3) - never
        disguised as an ordinary retryable failure.

    Manifest identity (R4-A2.10 P0-02, audit section 3): the dataset hash
    is DERIVED from the gate-validated in-memory reviewed_bytes - the
    post-rename filesystem read-back is VERIFICATION ONLY (actual bytes
    must equal reviewed_bytes; a tampered final file can never have its
    bytes re-hashed into the manifest)."""
    evidence_dir = rules_root / RULE_EVIDENCE_SUBDIR
    evidence_dir_preexisting = evidence_dir.exists()
    created_evidence_refs: set[str] = set()
    published_version = False
    manifest_committed = False
    staging_dir = rules_root / "versions" / f".staging-{version}-{uuid.uuid4().hex[:8]}"
    tmp_manifest = rules_root / f".{RULE_MANIFEST_FILE}.tmp-{version}"

    # H1 candidate path: re-check the expected old ACTIVE parent immediately
    # before any evidence/version mutation. Legacy ACTIVE->REVIEWED callers
    # leave these arguments empty and retain their existing behavior.
    if expected_parent_version:
        parent_problem = _expected_parent_problem(
            rules_root=rules_root,
            expected_version=expected_parent_version,
            expected_dataset_hash=expected_parent_dataset_hash,
            expected_dataset_files=expected_parent_dataset_files,
        )
        if parent_problem:
            return _fail(parent_problem)

    def _cleanup_uncommitted() -> None:
        # remove every byte THIS run created (staged/published/evidence/tmp)
        shutil.rmtree(staging_dir, ignore_errors=True)
        if published_version and version_dir.is_dir():
            shutil.rmtree(version_dir, ignore_errors=True)
        for ref in created_evidence_refs:
            (evidence_dir / ref).unlink(missing_ok=True)
        tmp_manifest.unlink(missing_ok=True)
        if not evidence_dir_preexisting and evidence_dir.is_dir():
            # Bundle refs create evidence/sha256/. Remove only empty
            # directories created by this attempt; never remove a preexisting
            # evidence tree or an unexpected file.
            for directory in sorted(
                (path for path in evidence_dir.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                with contextlib.suppress(OSError):
                    directory.rmdir()
            with contextlib.suppress(OSError):
                evidence_dir.rmdir()

    try:
        # ================= Phase 2: staged output =================
        # stage the evidence artifact (content-addressed, idempotent) and
        # the reviewed version under versions/.staging-<id>/, then run the
        # FULL review gate against the staged layout.
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for raw in raw_artifacts:
            raw_copy = evidence_dir / raw.artifact_ref
            if not raw_copy.exists():
                raw_copy.parent.mkdir(parents=True, exist_ok=True)
                raw_copy.write_bytes(raw.content)
                created_evidence_refs.add(raw.artifact_ref)
        if not artifact_copy.exists():
            artifact_copy.parent.mkdir(parents=True, exist_ok=True)
            artifact_copy.write_bytes(artifact_bytes)
            created_evidence_refs.add(artifact_ref)
        staging_dir.mkdir(parents=True)
        staged_yaml = staging_dir / "rules.yaml"
        staged_yaml.write_bytes(reviewed_bytes)  # byte identity preserved
        # full gate against the staged layout: the evidence artifact is in
        # place so the gate's confined artifact resolution works
        reviewed_book = TradingRuleBook.load(staged_yaml)
        problems = trading_rule_review_gate(
            reviewed_book,
            rules_root=rules_root,
            require_evidence_bundle=bool(evidence_contract),
        )
        if source_rule_identity is not None and tuple(reviewed_book.rules) != source_rule_identity:
            problems.append(
                "reviewed candidate rule identity differs from the captured candidate snapshot"
            )
        if problems:
            _cleanup_uncommitted()
            return _fail(f"reviewed copy fails the review gate: {problems}")

        # ================= Phase 3: publish (ACTIVE manifest LAST) ======
        # manifest identity DERIVED FROM the gate-validated reviewed_bytes
        final_rel = f"versions/{version}/rules.yaml"
        expected_dataset_hash = _hash_snapshot([(final_rel, reviewed_bytes)])
        # publish the immutable version (atomic dir rename; the target's
        # non-existence was validated in Phase 1 - a concurrent creation
        # surfaces as a loud failure, never a silent overwrite)
        version_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir.replace(version_dir)
        published_version = True
        # READ-BACK VERIFICATION ONLY (audit 20260825 #6 section 3.2): the
        # persisted bytes must EQUAL the reviewed_bytes identity; a tampered
        # final file blocks + rolls back - it can never define the seal.
        actual_final_bytes = (version_dir / "rules.yaml").read_bytes()
        if actual_final_bytes != reviewed_bytes:
            published_version = True  # keep cleanup semantics accurate
            _cleanup_uncommitted()
            return _fail(
                "published REVIEWED bytes differ from the gate-validated "
                "reviewed_bytes identity - rolled back; ACTIVE unchanged "
                "(read-back is verification-only, never a hash source)"
            )
        if expected_parent_version:
            parent_problem = _expected_parent_problem(
                rules_root=rules_root,
                expected_version=expected_parent_version,
                expected_dataset_hash=expected_parent_dataset_hash,
                expected_dataset_files=expected_parent_dataset_files,
            )
            if parent_problem:
                _cleanup_uncommitted()
                return _fail(parent_problem)
        manifest = {
            "rule_version": version,
            "review_status": "REVIEWED",
            "dataset_files": [final_rel],
            "dataset_hash": expected_dataset_hash,
            "source_version": reviewed_book.source_version,
            "dataset_version": reviewed_book.version,
            "review_provenance": {
                "reviewed_by": reviewer,
                "reviewed_at": now,
                "source_artifact_ref": artifact_ref,
                "source_artifact_hash": artifact_hash,
                "source_artifact_kind": kind,
                "source_retrieved_at": now,
            },
        }
        if evidence_contract:
            manifest["evidence_contract"] = evidence_contract
            manifest["review_provenance"][RULE_EVIDENCE_BUNDLE_REF] = artifact_ref
            manifest["review_provenance"][RULE_EVIDENCE_BUNDLE_HASH] = artifact_hash
        manifest_path = rules_root / RULE_MANIFEST_FILE
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        tmp_manifest.write_bytes(manifest_bytes + b"\n")
        if candidate_file is not None:
            assert candidate_snapshot_bytes is not None
            candidate_problem = _verify_candidate_snapshot(
                candidate_file=candidate_file,
                candidate_version=candidate_version,
                rules_root=rules_root,
                candidate_rel=candidate_rel,
                snapshot_bytes=candidate_snapshot_bytes,
                snapshot_hash=snapshot_hash,
                snapshot_file_identity=candidate_snapshot_file_identity,
            )
            if candidate_problem:
                _cleanup_uncommitted()
                return _fail(
                    f"candidate changed before ACTIVE manifest commit: {candidate_problem}"
                )
        # ATOMIC REPLACEMENT / READER-SAFE: concurrent readers see either
        # the complete old manifest or the complete new one. (NOT a
        # power-loss durability guarantee - no fsync is performed.)
        tmp_manifest.replace(manifest_path)
        manifest_committed = True
    except BaseException:
        if not manifest_committed:
            _cleanup_uncommitted()
        raise

    # ================= post-commit verification =================
    # the ACTIVE manifest has advanced: a failure here is a COMMITTED-state
    # inconsistency (explicit hard failure, exit 3) - NOT a normal retry.
    loaded_manifest = load_rule_manifest(rules_root)
    if loaded_manifest.rule_version != version or (
        loaded_manifest.dataset_hash != expected_dataset_hash
    ):
        print(
            f"REVIEW_COMMIT_INCONSISTENT: ACTIVE manifest ("
            f"{loaded_manifest.rule_version}) does not reflect the committed "
            f"review ({version}) - manual intervention required",
            file=sys.stderr,
        )
        return 3
    try:
        committed_book, _committed_manifest = load_active_rules(rules_root)
    except Exception as exc:  # noqa: BLE001 - coherence failure must surface
        print(
            f"REVIEW_COMMIT_INCONSISTENT: the committed ACTIVE state fails "
            f"coherence load: {exc} - manual intervention required",
            file=sys.stderr,
        )
        return 3
    post_problems = trading_rule_review_gate(
        committed_book,
        rules_root=rules_root,
        require_evidence_bundle=bool(evidence_contract),
    )
    if post_problems:
        print(
            "REVIEW_COMMIT_INCONSISTENT: committed ACTIVE fails the post-commit "
            f"review/evidence gate: {post_problems} - manual intervention required",
            file=sys.stderr,
        )
        return 3
    if expected_parent_version:
        parent_problem = _verify_parent_snapshot(
            rules_root=rules_root,
            expected_dataset_hash=expected_parent_dataset_hash,
            expected_dataset_files=expected_parent_dataset_files,
        )
        if parent_problem:
            print(
                "REVIEW_COMMIT_INCONSISTENT: old ACTIVE parent changed after "
                f"manifest commit: {parent_problem} - manual intervention required",
                file=sys.stderr,
            )
            return 3
    if candidate_file is not None:
        assert candidate_snapshot_bytes is not None
        candidate_problem = _verify_candidate_snapshot(
            candidate_file=candidate_file,
            candidate_version=candidate_version,
            rules_root=rules_root,
            candidate_rel=candidate_rel,
            snapshot_bytes=candidate_snapshot_bytes,
            snapshot_hash=snapshot_hash,
            snapshot_file_identity=candidate_snapshot_file_identity,
        )
        if candidate_problem:
            print(
                "REVIEW_COMMIT_INCONSISTENT: candidate changed after ACTIVE "
                f"manifest commit: {candidate_problem} - manual intervention required",
                file=sys.stderr,
            )
            return 3
    print(
        f"REVIEWED version written: {version_dir / 'rules.yaml'}\n"
        f"  version={version} rules={len(reviewed_book.rules)}\n"
        f"  sealed from ACTIVE snapshot sha256={snapshot_hash[:16]}...\n"
        f"  evidence {RULE_EVIDENCE_SUBDIR}/{artifact_ref} sha256={artifact_hash[:16]}...\n"
        f"  ACTIVE manifest -> {version}; review gate: PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
