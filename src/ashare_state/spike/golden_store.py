"""Golden Truth Dataset store (R4-A1.1 + R4-A2 evidence closure).

Layout (append-only versions):
    golden_cases_v1.jsonl / truth_manifest_v1.json   (immutable snapshots)
    golden_cases_v2.jsonl / truth_manifest_v2.json   ...
    golden_cases_v3.jsonl / truth_manifest_v3.json   (review workflow target)
    truth_manifest.json                              (ACTIVE pointer only)
    evidence/                                        (external artifacts,
                                                     resolvable + hashable)

R4-A2 additions over R4-A1.1 (review sections 5-12):
- source evidence model: source_artifact_ref/kind/retrieved_at; the
  FORMAL review gate resolves artifact bytes and re-verifies SHA256 -
  hand-typed hashes can never pass (they must equal the artifact bytes).
- compiled_* / reviewed_* provenance separated.
- ST event semantics: ST_TRANSITION with subtypes (ST_ADD/ST_REMOVE/
  STAR_ST_ADD/STAR_ST_REMOVE); gate requires >=50 distinct events AND
  ADD>0 AND REMOVE>0.
- Delist gate: distinct structural (provider_symbol, event_effective_date)
  identities >= 20 AND distinct provider_symbol >= 20.
- SpikeRun field renamed golden_dataset_hash (review section 11, option A).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ashare_state.spike.validators import GoldenCase

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
ACTIVE_MANIFEST = "truth_manifest.json"
EVIDENCE_DIRNAME = "evidence"

#: per-type minimum ROW counts
REQUIRED_GOLDEN_COUNTS = {
    "golden_st_transition": 50,
    "golden_delisted": 20,
    "golden_limit_regime": 30,
    "golden_corporate_action": 20,
}
#: distinct-event minimums with semantic constraints (review sections 9-10)
REQUIRED_DISTINCT_EVENTS = {
    "golden_st_transition": ("ST_TRANSITION", 50),
    "golden_delisted": ("DELIST", 20),
}
ST_ADD_SUBTYPES = ("ST_ADD", "STAR_ST_ADD")
ST_REMOVE_SUBTYPES = ("ST_REMOVE", "STAR_ST_REMOVE")
VALID_ST_SUBTYPES = frozenset((*ST_ADD_SUBTYPES, *ST_REMOVE_SUBTYPES))


class StructuralEventError(ValueError):
    """A structural ST/DELIST identity is incomplete or malformed."""


def validate_event_effective_date(
    value: object,
    *,
    case_id: str,
    event_class: str,
) -> str:
    """Require an explicit, calendar-valid ``YYYYMMDD`` effective date.

    ``trade_date`` is deliberately not accepted as a substitute.  The
    historical v1-v3 files remain loadable for audit/replay, but their
    incomplete structural rows are rejected by the Formal event gate and by
    the new candidate/review workflows.
    """
    if not isinstance(value, str) or not value.strip():
        raise StructuralEventError(
            f"{case_id}: {event_class} requires a non-empty event_effective_date"
        )
    effective = value.strip()
    if effective != value or len(effective) != 8 or not effective.isdigit():
        raise StructuralEventError(
            f"{case_id}: {event_class} event_effective_date must be YYYYMMDD"
        )
    try:
        datetime.strptime(effective, "%Y%m%d")
    except ValueError as exc:
        raise StructuralEventError(
            f"{case_id}: {event_class} event_effective_date is not a valid calendar date"
        ) from exc
    return effective


def validate_structural_event_fields(
    *,
    case_id: str,
    event_class: str,
    provider_symbol: object,
    event_subtype: object,
    event_effective_date: object,
) -> None:
    """Validate the fields that define a structural event identity."""
    if not isinstance(event_class, str) or event_class not in {"ST_TRANSITION", "DELIST"}:
        return
    if (
        not isinstance(provider_symbol, str)
        or not provider_symbol.strip()
        or provider_symbol != provider_symbol.strip()
    ):
        raise StructuralEventError(f"{case_id}: {event_class} requires a non-empty provider_symbol")
    if event_class == "ST_TRANSITION" and (
        not isinstance(event_subtype, str) or event_subtype not in VALID_ST_SUBTYPES
    ):
        raise StructuralEventError(
            f"{case_id}: ST_TRANSITION requires event_subtype in {sorted(VALID_ST_SUBTYPES)}"
        )
    validate_event_effective_date(
        event_effective_date,
        case_id=case_id,
        event_class=event_class,
    )


def st_event_identity(case: GoldenCase) -> tuple[str, str, str]:
    """Structural ST event identity (audit section 14): the free-form
    event_id string can never inflate the count - identity is
    (provider_symbol, event_effective_date, event_subtype)."""
    if case.event_class != "ST_TRANSITION":
        raise StructuralEventError(
            f"{case.golden_case_id}: st_event_identity requires ST_TRANSITION"
        )
    effective = validate_event_effective_date(
        case.event_effective_date,
        case_id=case.golden_case_id,
        event_class=case.event_class,
    )
    validate_structural_event_fields(
        case_id=case.golden_case_id,
        event_class=case.event_class,
        provider_symbol=case.provider_symbol,
        event_subtype=case.event_subtype,
        event_effective_date=case.event_effective_date,
    )
    return (case.provider_symbol, effective, case.event_subtype)


def delist_event_identity(case: GoldenCase) -> tuple[str, str]:
    if case.event_class != "DELIST":
        raise StructuralEventError(f"{case.golden_case_id}: delist_event_identity requires DELIST")
    effective = validate_event_effective_date(
        case.event_effective_date,
        case_id=case.golden_case_id,
        event_class=case.event_class,
    )
    validate_structural_event_fields(
        case_id=case.golden_case_id,
        event_class=case.event_class,
        provider_symbol=case.provider_symbol,
        event_subtype=case.event_subtype,
        event_effective_date=case.event_effective_date,
    )
    return (case.provider_symbol, effective)


class GoldenTruthError(RuntimeError):
    """Golden dataset integrity violation."""


@dataclass(frozen=True)
class GoldenManifest:
    truth_version: str
    dataset_file: str
    dataset_hash: str
    case_count: int
    counts_by_type: dict[str, int]
    review_summary: dict[str, int]
    distinct_events: dict[str, int]
    distinct_securities: dict[str, int]
    manifest_schema: int = 1
    st_add_events: int = 0
    st_remove_events: int = 0
    distinct_delisted_securities: int = 0

    @property
    def quantities_complete(self) -> bool:
        return all(
            self.counts_by_type.get(case_type, 0) >= minimum
            for case_type, minimum in REQUIRED_GOLDEN_COUNTS.items()
        )

    @property
    def events_complete(self) -> bool:
        return all(
            self.distinct_events.get(event_class, 0) >= minimum
            for event_class, minimum in REQUIRED_DISTINCT_EVENTS.values()
        )

    @property
    def fully_reviewed(self) -> bool:
        total = sum(self.review_summary.values())
        return total > 0 and self.review_summary.get("REVIEWED", 0) == total


class GoldenTruthStore:
    """Loads + seals the versioned golden dataset (ACTIVE pointer)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else GOLDEN_ROOT
        self._manifest: GoldenManifest | None = None
        self._cases: list[GoldenCase] | None = None

    # ---------------------------------------------------------------- load
    def load(self) -> tuple[list[GoldenCase], GoldenManifest]:
        if self._cases is not None and self._manifest is not None:
            return self._cases, self._manifest
        active_path = self.root / ACTIVE_MANIFEST
        if not active_path.is_file():
            msg = f"no {ACTIVE_MANIFEST} under {self.root} (run scripts/golden/compile_v2.py)"
            raise GoldenTruthError(msg)
        active = json.loads(active_path.read_text(encoding="utf-8"))
        dataset_file = str(active.get("dataset_file", ""))
        if not dataset_file:
            msg = "active manifest has no dataset_file pointer"
            raise GoldenTruthError(msg)
        dataset_path = self.root / dataset_file
        if not dataset_path.is_file():
            msg = f"active manifest points to missing dataset {dataset_file}"
            raise GoldenTruthError(msg)

        dataset_bytes = dataset_path.read_bytes()
        dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
        if active.get("dataset_hash") != dataset_hash:
            msg = "golden dataset hash mismatch vs the ACTIVE manifest pointer"
            raise GoldenTruthError(msg)

        truth_version = str(active["truth_version"])
        cases = cases_from_dataset_bytes(dataset_bytes, truth_version)

        # P0-01: manifest statistics RECOMPUTED from cases (self-verification)
        stats = recompute_manifest_statistics(cases)
        actual_count = int(stats["case_count"])
        actual_counts = stats["counts_by_type"]
        actual_review = stats["review_summary"]
        actual_events = stats["distinct_events"]
        actual_securities = stats["distinct_securities"]
        if active.get("case_count") != actual_count:
            msg = f"manifest case_count {active.get('case_count')} != recomputed {actual_count}"
            raise GoldenTruthError(msg)
        if dict(active.get("counts_by_type", {})) != actual_counts:
            msg = "manifest counts_by_type != recomputed counts (P0-01 tamper)"
            raise GoldenTruthError(msg)
        if dict(active.get("review_summary", {})) != actual_review:
            msg = "manifest review_summary != recomputed summary (P0-01 tamper)"
            raise GoldenTruthError(msg)

        try:
            manifest_schema = int(active.get("manifest_schema", 1))
        except (TypeError, ValueError) as exc:
            raise GoldenTruthError("manifest_schema must be an integer") from exc
        if manifest_schema >= 2:
            _verify_structural_manifest_fields(active, stats)

        manifest = GoldenManifest(
            truth_version=truth_version,
            dataset_file=dataset_file,
            dataset_hash=dataset_hash,
            case_count=actual_count,
            counts_by_type=actual_counts,
            review_summary=actual_review,
            distinct_events=actual_events,
            distinct_securities=actual_securities,
            manifest_schema=manifest_schema,
            st_add_events=int(stats["st_add_events"]),
            st_remove_events=int(stats["st_remove_events"]),
            distinct_delisted_securities=int(stats["distinct_delisted_securities"]),
        )
        self._manifest, self._cases = manifest, cases
        return cases, manifest

    # ------------------------------------------------------------ bound load
    def load_bound(
        self,
        dataset_file: str,
        truth_version: str,
        dataset_hash: str,
    ) -> tuple[list[GoldenCase], GoldenManifest]:
        """R4A2-P0-02: load the RUN-BOUND immutable dataset directly.

        Never touches the ACTIVE pointer: formal runs, resumes, verdicts
        and replay resolve the exact dataset they were created against,
        even after the ACTIVE pointer advances to a newer version.
        """
        dataset_path = self.root / dataset_file
        if not dataset_path.is_file():
            msg = (
                f"bound golden dataset {dataset_file!r} does not exist under "
                f"{self.root} (immutable version must not be deleted)"
            )
            raise GoldenTruthError(msg)
        dataset_bytes = dataset_path.read_bytes()
        actual_hash = hashlib.sha256(dataset_bytes).hexdigest()
        if actual_hash != dataset_hash:
            msg = (
                f"bound golden dataset {dataset_file!r}: hash mismatch "
                f"(bound {dataset_hash[:12]}..., actual {actual_hash[:12]}...) - "
                "the immutable version file was modified"
            )
            raise GoldenTruthError(msg)

        cases = cases_from_dataset_bytes(dataset_bytes, truth_version)
        stats = recompute_manifest_statistics(cases)
        manifest = GoldenManifest(
            truth_version=truth_version,
            dataset_file=dataset_file,
            dataset_hash=actual_hash,
            case_count=int(stats["case_count"]),
            counts_by_type=stats["counts_by_type"],
            review_summary=stats["review_summary"],
            distinct_events=stats["distinct_events"],
            distinct_securities=stats["distinct_securities"],
            manifest_schema=2 if _truth_version_number(truth_version) >= 4 else 1,
            st_add_events=int(stats["st_add_events"]),
            st_remove_events=int(stats["st_remove_events"]),
            distinct_delisted_securities=int(stats["distinct_delisted_securities"]),
        )
        return cases, manifest

    def production_formal_gate(
        self,
        bound_cases: list[GoldenCase] | None = None,
        bound_manifest: GoldenManifest | None = None,
    ) -> list[str]:
        """R4A2-P0-04 + R4-A2.3 P0-05: the FORMAL production gate.

        Bound-aware contract (audit section 7): RUNNING/RESUME/CLOSE/
        VERDICT/REPLAY stages MUST pass bound (cases, manifest) - then
        quantity + event-coverage + review gates are ALL re-verified over
        the run-bound dataset itself. The ACTIVE dataset is only consulted
        when no bound data is supplied (new-run creation path), and an
        ACTIVE advance/tamper can never leak into a historical run's
        verdict.
        """
        cases, manifest = self._resolve_dataset(bound_cases, bound_manifest)
        return (
            self.quantity_gate(cases, manifest)
            + self.event_coverage_gate(cases, manifest)
            + self.review_gate(cases, manifest)
        )

    # ---------------------------------------------------------------- gates
    def _resolve_dataset(
        self,
        cases: list[GoldenCase] | None,
        manifest: GoldenManifest | None,
    ) -> tuple[list[GoldenCase], GoldenManifest]:
        """Bound-aware dataset resolution: explicit (cases, manifest) win
        (run-bound datasets); otherwise fall back to ACTIVE (only valid
        for new-run creation, never for verdict paths).

        R4-A2.3 P0-05: the old verify_binding() (comparing a run's binding
        against the ACTIVE pointer) was REMOVED - it violated the
        bound-run contract. Binding integrity is verified via load_bound()
        hash checking instead."""
        if cases is not None and manifest is not None:
            return cases, manifest
        return self.load()

    def quantity_gate(
        self,
        cases: list[GoldenCase] | None = None,
        manifest: GoldenManifest | None = None,
    ) -> list[str]:
        cases_, manifest_ = self._resolve_dataset(cases, manifest)
        _ = cases_
        return [
            f"{case_type}: {manifest_.counts_by_type.get(case_type, 0)} rows < {minimum}"
            for case_type, minimum in REQUIRED_GOLDEN_COUNTS.items()
            if manifest_.counts_by_type.get(case_type, 0) < minimum
        ]

    def event_coverage_gate(
        self,
        cases: list[GoldenCase] | None = None,
        manifest: GoldenManifest | None = None,
    ) -> list[str]:
        """Distinct-event semantics (audit sections 14-16): identity is
        STRUCTURAL - (symbol, effective_date, subtype) for ST and
        (symbol, effective_date) for delist. Free-form event_id strings
        can never inflate the count. Bound-aware (P0-05)."""
        cases_, manifest_ = self._resolve_dataset(cases, manifest)
        _ = manifest_
        problems: list[str] = []
        stats = recompute_manifest_statistics(cases_)
        invalid = stats["invalid_structural_cases"]
        invalid_by_class: dict[str, list[str]] = {"ST_TRANSITION": [], "DELIST": []}
        for event_class, case_id in invalid:
            invalid_by_class[event_class].append(case_id)
        if invalid_by_class["ST_TRANSITION"]:
            problems.append(
                "golden_st_transition: invalid structural event identity for "
                f"{len(invalid_by_class['ST_TRANSITION'])} cases; "
                "event_effective_date is required and trade_date fallback is forbidden "
                f"({', '.join(invalid_by_class['ST_TRANSITION'][:3])})"
            )
        if invalid_by_class["DELIST"]:
            problems.append(
                "golden_delisted: invalid structural event identity for "
                f"{len(invalid_by_class['DELIST'])} cases; "
                "event_effective_date is required and trade_date fallback is forbidden "
                f"({', '.join(invalid_by_class['DELIST'][:3])})"
            )
        # ST transitions: >= 50 distinct structural events, ADD>0, REMOVE>0
        st_count = int(stats["distinct_events"].get("ST_TRANSITION", 0))
        if st_count < REQUIRED_DISTINCT_EVENTS["golden_st_transition"][1]:
            problems.append(f"golden_st_transition: distinct ST_TRANSITION events {st_count} < 50")
        add_count = int(stats["st_add_events"])
        remove_count = int(stats["st_remove_events"])
        if add_count == 0:
            problems.append("golden_st_transition: no ST_ADD/STAR_ST_ADD subtype events")
        if remove_count == 0:
            problems.append("golden_st_transition: no ST_REMOVE/STAR_ST_REMOVE subtype events")
        # Delist: distinct (symbol, effective_date) >= 20 AND symbols >= 20
        delist_count = int(stats["distinct_events"].get("DELIST", 0))
        delist_symbols = int(stats["distinct_delisted_securities"])
        if delist_count < REQUIRED_DISTINCT_EVENTS["golden_delisted"][1]:
            problems.append(f"golden_delisted: distinct DELIST events {delist_count} < 20")
        if delist_symbols < 20:
            problems.append(f"golden_delisted: distinct delisted securities {delist_symbols} < 20")
        return problems

    def review_gate(
        self,
        cases: list[GoldenCase] | None = None,
        manifest: GoldenManifest | None = None,
    ) -> list[str]:
        """FORMAL review gate (review section 8): every case REVIEWED, and
        EVERY REVIEWED case's source artifact RESOLVES and hash-VERIFIES.

        R4A2-P0-01 fix: verifies ALL reviewed cases with complete error
        collection - never breaks on the first success.

        R4-A2.3 P0-05: bound-aware - with explicit (cases, manifest) the
        gate re-verifies the RUN-BOUND dataset (verdict/replay stages);
        artifacts live in the shared immutable evidence store, so bound
        case refs verify against the same content-addressed files.
        """
        cases_, manifest_ = self._resolve_dataset(cases, manifest)
        problems: list[str] = []
        if not manifest_.fully_reviewed:
            total = sum(manifest_.review_summary.values())
            problems.append(
                "golden truth not fully human-reviewed "
                f"(REVIEWED {manifest_.review_summary.get('REVIEWED', 0)}/{total}; "
                "audit section 39 requires every golden entry reviewed before P0-M-1B)"
            )
        for case in cases_:
            if case.review_status == "REVIEWED":
                problems.extend(self._verify_artifact(case))
        return problems

    def _verify_artifact(self, case: GoldenCase) -> list[str]:
        if not case.source_artifact_ref:
            return [
                f"{case.golden_case_id}: REVIEWED without source_artifact_ref "
                "(review section 8: a resolvable artifact is mandatory)"
            ]
        if not case.source_artifact_hash:
            return [f"{case.golden_case_id}: REVIEWED without source_artifact_hash"]
        # R4A2-P1-03 + R4-A2.9 (audit 20260825 #5 CI root cause #2): path
        # confinement must be PLATFORM-INDEPENDENT. On Linux,
        # ``evidence_dir / "C:/evil.txt"`` is a RELATIVE join (no escape
        # detected by the resolved check); on Windows the drive prefix
        # makes it absolute. Reject absolute-on-any-platform forms
        # LEXICALLY first (leading slash/backslash, drive prefix,
        # '..' traversal), then do the resolved confinement check.
        ref = str(case.source_artifact_ref).replace("\\", "/")
        lexical_violation = ""
        if ref.startswith("/"):
            lexical_violation = "absolute path"
        elif ":" in ref.split("/", 1)[0]:
            lexical_violation = "drive-letter path"
        elif any(part == ".." for part in ref.split("/")):
            lexical_violation = "'..' traversal"
        if lexical_violation:
            return [
                f"{case.golden_case_id}: source_artifact_ref "
                f"{case.source_artifact_ref!r} escapes the evidence store "
                f"(path confinement violation: {lexical_violation})"
            ]
        evidence_dir = (self.root / EVIDENCE_DIRNAME).resolve()
        artifact_path = (evidence_dir / case.source_artifact_ref).resolve()
        try:
            artifact_path.relative_to(evidence_dir)
        except ValueError:
            return [
                f"{case.golden_case_id}: source_artifact_ref "
                f"{case.source_artifact_ref!r} escapes the evidence store "
                "(path confinement violation)"
            ]
        if not artifact_path.is_file():
            return [
                f"{case.golden_case_id}: source artifact {case.source_artifact_ref!r} "
                "does not resolve under the evidence store"
            ]
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != case.source_artifact_hash:
            return [
                f"{case.golden_case_id}: source artifact hash mismatch - the "
                "sealed hash does not match the artifact bytes (REVIEW_INCOMPLETE)"
            ]
        return []


def cases_from_dataset_bytes(dataset_bytes: bytes, truth_version: str) -> list[GoldenCase]:
    """Parse and fully seal-check a dataset in memory.

    Candidate/review publishers call this before touching any versioned file;
    the loader uses the same path so preflight and runtime validation cannot
    drift apart.
    """
    try:
        text = dataset_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GoldenTruthError("golden dataset is not valid UTF-8") from exc
    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldenTruthError(f"golden dataset line {line_number}: invalid JSON") from exc
        if not isinstance(doc, dict):
            raise GoldenTruthError(f"golden dataset line {line_number}: case must be a JSON object")
        golden = _case_from_doc(doc, truth_version)
        if golden.case_semantic_hash != semantic_hash_of(golden):
            raise GoldenTruthError(
                f"golden case {golden.golden_case_id}: case_semantic_hash mismatch"
            )
        if golden.golden_case_id in seen_ids:
            raise GoldenTruthError(f"duplicate golden_case_id {golden.golden_case_id}")
        seen_ids.add(golden.golden_case_id)
        cases.append(golden)
    return cases


def recompute_structural_statistics(cases: Iterable[GoldenCase]) -> dict[str, Any]:
    """Recompute event statistics using the Formal structural identities.

    Invalid legacy structural rows are reported, not silently converted into
    trade-date identities.  That keeps v1-v3 readable while making every
    missing effective date visible to the Formal gate.
    """
    event_ids_by_class: dict[str, set[str]] = {}
    st_events: set[tuple[str, str, str]] = set()
    delist_events: set[tuple[str, str]] = set()
    delisted_symbols: set[str] = set()
    invalid_structural_cases: list[tuple[str, str]] = []
    securities: dict[str, int] = {}
    for case in cases:
        securities[case.provider_symbol] = securities.get(case.provider_symbol, 0) + 1
        if case.event_class == "ST_TRANSITION":
            try:
                identity = st_event_identity(case)
            except StructuralEventError:
                invalid_structural_cases.append((case.event_class, case.golden_case_id))
                continue
            st_events.add(identity)
        elif case.event_class == "DELIST":
            delisted_symbols.add(case.provider_symbol)
            try:
                delist_events.add(delist_event_identity(case))
            except StructuralEventError:
                invalid_structural_cases.append((case.event_class, case.golden_case_id))
        elif case.event_class:
            if case.event_id:
                event_ids_by_class.setdefault(case.event_class, set()).add(case.event_id)

    distinct_events = {
        event_class: len(event_ids) for event_class, event_ids in event_ids_by_class.items()
    }
    distinct_events["ST_TRANSITION"] = len(st_events)
    distinct_events["DELIST"] = len(delist_events)
    st_add_events = sum(1 for _, _, subtype in st_events if subtype in ST_ADD_SUBTYPES)
    st_remove_events = sum(1 for _, _, subtype in st_events if subtype in ST_REMOVE_SUBTYPES)
    return {
        "distinct_events": distinct_events,
        "distinct_securities": securities,
        "st_add_events": st_add_events,
        "st_remove_events": st_remove_events,
        "distinct_delisted_securities": len(delisted_symbols),
        "invalid_structural_cases": invalid_structural_cases,
    }


def recompute_manifest_statistics(cases: Iterable[GoldenCase]) -> dict[str, Any]:
    """Return all row/review/structural statistics used by schema v2."""
    case_list = list(cases)
    counts: dict[str, int] = {}
    review: dict[str, int] = {}
    for case in case_list:
        counts[case.case_type] = counts.get(case.case_type, 0) + 1
        review[case.review_status] = review.get(case.review_status, 0) + 1
    stats = recompute_structural_statistics(case_list)
    stats.update(
        {
            "case_count": len(case_list),
            "counts_by_type": counts,
            "review_summary": review,
        }
    )
    return stats


def review_readiness_gate(
    cases: Iterable[GoldenCase],
    manifest: GoldenManifest,
) -> list[str]:
    """Require a clean, compiled v4+ candidate before human review.

    A v1-v3 ACTIVE dataset may remain loadable for historical replay, but it
    is not a valid input lineage for producing a REVIEWED version because its
    legacy structural rows can make the subsequent clean rebuild impossible.
    """
    case_list = list(cases)
    problems: list[str] = []
    if _truth_version_number(manifest.truth_version) < 4:
        problems.append(
            "active golden candidate is not review-ready: a clean v4+ truth_version is required"
        )
    if manifest.manifest_schema < 2:
        problems.append(
            "active golden candidate is not review-ready: manifest_schema 2 is required"
        )

    stats = recompute_manifest_statistics(case_list)
    invalid = stats["invalid_structural_cases"]
    if invalid:
        examples = ", ".join(case_id for _, case_id in invalid[:3])
        problems.append(
            "active golden candidate is not review-ready: invalid structural cases "
            f"({len(invalid)}; {examples}); clean rebuild is required"
        )

    non_compiled = [case.golden_case_id for case in case_list if case.review_status != "COMPILED"]
    if non_compiled:
        examples = ", ".join(non_compiled[:3])
        problems.append(
            "active golden candidate is not review-ready: every case must remain COMPILED "
            f"before review ({examples})"
        )

    with_review_provenance = [
        case.golden_case_id
        for case in case_list
        if any(
            (
                case.reviewed_by,
                case.reviewed_at,
                case.review_note,
                case.source_artifact_ref,
                case.source_artifact_hash,
                case.source_artifact_kind,
                case.source_retrieved_at,
            )
        )
    ]
    if with_review_provenance:
        examples = ", ".join(with_review_provenance[:3])
        problems.append(
            "active golden candidate is not review-ready: compiled cases must not carry "
            f"review provenance ({examples})"
        )
    return problems


def _verify_structural_manifest_fields(active: Mapping[str, Any], stats: Mapping[str, Any]) -> None:
    """Verify the schema-v2 fields that must match row-level recomputation."""
    fields = (
        "distinct_events",
        "distinct_securities",
        "st_add_events",
        "st_remove_events",
        "distinct_delisted_securities",
    )
    for field in fields:
        if field not in active:
            raise GoldenTruthError(f"manifest_schema 2 requires {field}")
        if active[field] != stats[field]:
            raise GoldenTruthError(f"manifest {field} != recomputed structural statistics")


def _truth_version_number(value: object) -> int:
    prefix = str(value).split("-", 1)[0]
    if not prefix.startswith("v"):
        return 0
    digits = prefix[1:]
    return int(digits) if digits.isdigit() else 0


def _semantic_statement_for_doc(doc: Mapping[str, Any]) -> str:
    statement: dict[str, Any] = {
        "golden_case_id": doc["golden_case_id"],
        "case_type": doc["case_type"],
        "provider_symbol": doc["provider_symbol"],
        "trade_date": doc["trade_date"],
        "expected_fields": doc["expected_fields"],
        "truth_source": doc["truth_source"],
        "source_ref": doc["source_ref"],
        "source_artifact_hash": doc.get("source_artifact_hash", ""),
        "truth_version": doc["truth_version"],
    }
    # v1-v3 hashes are immutable legacy contracts.  v4+ seals the event
    # identity fields so a free-form alias/subtype/date edit cannot survive
    # by merely recomputing the dataset hash.
    if _truth_version_number(doc.get("truth_version")) >= 4:
        statement.update(
            {
                "event_id": doc.get("event_id", ""),
                "event_class": doc.get("event_class", ""),
                "event_subtype": doc.get("event_subtype", ""),
                "event_effective_date": doc.get("event_effective_date", ""),
            }
        )
    return json.dumps(statement, sort_keys=True, ensure_ascii=False)


def _semantic_statement(golden: GoldenCase) -> str:
    doc = {
        "golden_case_id": golden.golden_case_id,
        "case_type": golden.case_type,
        "provider_symbol": golden.provider_symbol,
        "trade_date": golden.trade_date,
        "expected_fields": golden.expected_fields,
        "truth_source": golden.truth_source,
        "source_ref": golden.source_ref,
        "source_artifact_hash": golden.source_artifact_hash,
        "truth_version": golden.truth_version,
        "event_id": golden.event_id,
        "event_class": golden.event_class,
        "event_subtype": golden.event_subtype,
        "event_effective_date": golden.event_effective_date,
    }
    return _semantic_statement_for_doc(doc)


def semantic_hash_for_doc(doc: Mapping[str, Any]) -> str:
    """Compute the version-aware semantic seal for a JSON document."""
    return hashlib.sha256(_semantic_statement_for_doc(doc).encode("utf-8")).hexdigest()


def review_identity_hash_for_doc(doc: Mapping[str, Any]) -> str:
    """Compute a version-neutral identity hash for review carry-forward.

    ``semantic_hash_for_doc`` deliberately includes ``truth_version`` because
    it seals one immutable dataset version.  A carry-forward ledger compares
    the same reviewed fact across two immutable versions, so it needs the
    same canonical statement with only the version label removed.  Source
    references, expected fields and structural event fields remain included;
    changing any of those therefore invalidates carry-forward eligibility.
    """
    statement = json.loads(_semantic_statement_for_doc(doc))
    statement.pop("truth_version", None)
    payload = json.dumps(statement, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def semantic_hash_of(golden: GoldenCase) -> str:
    """Recompute the case semantic hash (used by the review workflow)."""
    return hashlib.sha256(_semantic_statement(golden).encode("utf-8")).hexdigest()


#: R4A2-P1-02: artifact kinds shared by the review CLI and the loader
VALID_ARTIFACT_KINDS = {
    "SSE_ANNOUNCEMENT",
    "SZSE_ANNOUNCEMENT",
    "BSE_ANNOUNCEMENT",
    "CSRC_DOCUMENT",
    "EXCHANGE_RULEBOOK",
    "COMPANY_ANNOUNCEMENT",
    "INDEX_METHODOLOGY",
    "OTHER_OFFICIAL",
}


def _validate_review_provenance(doc: dict) -> None:
    """REVIEWED provenance completeness (R4A2-P1-02)."""
    case_id = str(doc.get("golden_case_id", "?"))
    problems = []
    if not str(doc.get("reviewed_by", "")):
        problems.append("reviewed_by is empty")
    reviewed_at = str(doc.get("reviewed_at", ""))
    if not _valid_iso_timestamp(reviewed_at):
        problems.append("reviewed_at is not a valid ISO timestamp")
    if not str(doc.get("source_artifact_ref", "")):
        problems.append("source_artifact_ref is empty")
    artifact_hash = str(doc.get("source_artifact_hash", ""))
    if len(artifact_hash) != 64 or not all(c in "0123456789abcdef" for c in artifact_hash):
        problems.append("source_artifact_hash is not 64-hex")
    if str(doc.get("source_artifact_kind", "")) not in VALID_ARTIFACT_KINDS:
        problems.append(
            f"source_artifact_kind {doc.get('source_artifact_kind')!r} not in allowlist"
        )
    retrieved_at = str(doc.get("source_retrieved_at", ""))
    if not _valid_iso_timestamp(retrieved_at):
        problems.append("source_retrieved_at is not a valid ISO timestamp")
    if problems:
        msg = f"golden case {case_id}: REVIEWED provenance incomplete: {'; '.join(problems)}"
        raise GoldenTruthError(msg)


def _valid_iso_timestamp(text: str) -> bool:
    if not text:
        return False
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


def _case_from_doc(doc: dict, dataset_truth_version: str) -> GoldenCase:
    missing = [
        field
        for field in (
            "case_semantic_hash",
            "truth_version",
            "review_status",
            "compiled_by",
            "compiled_at",
            "event_id",
            "event_class",
        )
        if field not in doc
    ]
    if missing:
        msg = f"golden case {doc.get('golden_case_id')}: missing seal fields {missing}"
        raise GoldenTruthError(msg)
    if doc["truth_version"] != dataset_truth_version:
        msg = (
            f"golden case {doc['golden_case_id']}: truth_version "
            f"{doc['truth_version']} != dataset {dataset_truth_version}"
        )
        raise GoldenTruthError(msg)
    # provenance discipline: COMPILED cases must NOT carry reviewer fields
    if doc["review_status"] == "COMPILED" and (doc.get("reviewed_by") or doc.get("reviewed_at")):
        msg = (
            f"golden case {doc['golden_case_id']}: COMPILED case carries "
            "reviewer provenance (compiled/reviewed must be separate)"
        )
        raise GoldenTruthError(msg)
    # R4A2-P1-02: REVIEWED cases must carry COMPLETE review provenance
    if doc["review_status"] == "REVIEWED":
        _validate_review_provenance(doc)
    return GoldenCase(
        golden_case_id=str(doc["golden_case_id"]),
        case_type=str(doc["case_type"]),
        provider_symbol=str(doc["provider_symbol"]),
        trade_date=str(doc["trade_date"]),
        truth_source=str(doc["truth_source"]),
        source_ref=str(doc["source_ref"]),
        expected_fields=dict(doc.get("expected_fields", {})),
        case_semantic_hash=str(doc["case_semantic_hash"]),
        source_artifact_hash=str(doc.get("source_artifact_hash", "")),
        source_artifact_ref=str(doc.get("source_artifact_ref", "")),
        source_artifact_kind=str(doc.get("source_artifact_kind", "")),
        source_retrieved_at=str(doc.get("source_retrieved_at", "")),
        truth_version=str(doc["truth_version"]),
        compiled_by=str(doc["compiled_by"]),
        compiled_at=str(doc["compiled_at"]),
        reviewed_by=str(doc.get("reviewed_by", "")),
        reviewed_at=str(doc.get("reviewed_at", "")),
        review_note=str(doc.get("review_note", "")),
        review_status=str(doc["review_status"]),
        event_id=str(doc["event_id"]),
        event_class=str(doc["event_class"]),
        event_subtype=str(doc.get("event_subtype", "")),
        event_effective_date=str(doc.get("event_effective_date", "")),
    )

