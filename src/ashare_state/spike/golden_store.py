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
- Delist gate: distinct event_id >= 20 AND distinct provider_symbol >= 20.
- SpikeRun field renamed golden_dataset_hash (review section 11, option A).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


def st_event_identity(case: GoldenCase) -> tuple[str, str, str]:
    """Structural ST event identity (audit section 14): the free-form
    event_id string can never inflate the count - identity is
    (provider_symbol, event_effective_date, event_subtype)."""
    return (case.provider_symbol, case.event_effective_date or case.trade_date, case.event_subtype)


def delist_event_identity(case: GoldenCase) -> tuple[str, str]:
    return (case.provider_symbol, case.event_effective_date or case.trade_date)


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

        cases: list[GoldenCase] = []
        seen_ids: set[str] = set()
        truth_version = str(active["truth_version"])
        for line in dataset_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue
            doc = json.loads(line)
            golden = _case_from_doc(doc, truth_version)
            expected = hashlib.sha256(_semantic_statement(golden).encode("utf-8")).hexdigest()
            if golden.case_semantic_hash != expected:
                msg = (
                    f"golden case {golden.golden_case_id}: case_semantic_hash "
                    "mismatch (entry edited without re-sealing)"
                )
                raise GoldenTruthError(msg)
            if golden.golden_case_id in seen_ids:
                msg = f"duplicate golden_case_id {golden.golden_case_id}"
                raise GoldenTruthError(msg)
            seen_ids.add(golden.golden_case_id)
            cases.append(golden)

        # P0-01: manifest statistics RECOMPUTED from cases (self-verification)
        actual_count = len(cases)
        actual_counts: dict[str, int] = {}
        actual_review: dict[str, int] = {}
        event_ids_by_class: dict[str, set[str]] = {}
        actual_securities: dict[str, int] = {}
        for case in cases:
            actual_counts[case.case_type] = actual_counts.get(case.case_type, 0) + 1
            actual_review[case.review_status] = actual_review.get(case.review_status, 0) + 1
            if case.event_class and case.event_id:
                event_ids_by_class.setdefault(case.event_class, set()).add(case.event_id)
            actual_securities[case.provider_symbol] = (
                actual_securities.get(case.provider_symbol, 0) + 1
            )
        actual_events = {k: len(v) for k, v in event_ids_by_class.items()}
        if active.get("case_count") != actual_count:
            msg = f"manifest case_count {active.get('case_count')} != recomputed {actual_count}"
            raise GoldenTruthError(msg)
        if dict(active.get("counts_by_type", {})) != actual_counts:
            msg = "manifest counts_by_type != recomputed counts (P0-01 tamper)"
            raise GoldenTruthError(msg)
        if dict(active.get("review_summary", {})) != actual_review:
            msg = "manifest review_summary != recomputed summary (P0-01 tamper)"
            raise GoldenTruthError(msg)

        manifest = GoldenManifest(
            truth_version=truth_version,
            dataset_file=dataset_file,
            dataset_hash=dataset_hash,
            case_count=actual_count,
            counts_by_type=actual_counts,
            review_summary=actual_review,
            distinct_events=actual_events,
            distinct_securities=actual_securities,
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

        cases: list[GoldenCase] = []
        for line in dataset_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue
            doc = json.loads(line)
            golden = _case_from_doc(doc, truth_version)
            expected = hashlib.sha256(_semantic_statement(golden).encode("utf-8")).hexdigest()
            if golden.case_semantic_hash != expected:
                msg = (
                    f"golden case {golden.golden_case_id}: case_semantic_hash "
                    "mismatch in bound dataset"
                )
                raise GoldenTruthError(msg)
            cases.append(golden)

        counts: dict[str, int] = {}
        review: dict[str, int] = {}
        event_ids: dict[str, set[str]] = {}
        securities: dict[str, int] = {}
        for case in cases:
            counts[case.case_type] = counts.get(case.case_type, 0) + 1
            review[case.review_status] = review.get(case.review_status, 0) + 1
            if case.event_class and case.event_id:
                event_ids.setdefault(case.event_class, set()).add(case.event_id)
            securities[case.provider_symbol] = securities.get(case.provider_symbol, 0) + 1
        manifest = GoldenManifest(
            truth_version=truth_version,
            dataset_file=dataset_file,
            dataset_hash=actual_hash,
            case_count=len(cases),
            counts_by_type=counts,
            review_summary=review,
            distinct_events={k: len(v) for k, v in event_ids.items()},
            distinct_securities=securities,
        )
        return cases, manifest

    def production_formal_gate(self, bound_manifest: GoldenManifest) -> list[str]:
        """R4A2-P0-04 formal gate evaluated over the BOUND dataset:
        the review gate (artifact verification) + full-review requirement
        of the bound dataset itself."""
        problems = self.review_gate()
        if not bound_manifest.fully_reviewed:
            problems = list(problems) + [
                "bound golden dataset is not fully REVIEWED "
                f"(REVIEWED {bound_manifest.review_summary.get('REVIEWED', 0)}/"
                f"{bound_manifest.case_count})"
            ]
        return problems

    # ---------------------------------------------------------------- gates
    def verify_binding(self, *, truth_version: str, dataset_hash: str) -> None:
        _, manifest = self.load()
        if truth_version != manifest.truth_version:
            msg = (
                f"golden truth_version drifted: run bound {truth_version!r}, "
                f"dataset now {manifest.truth_version!r}"
            )
            raise GoldenTruthError(msg)
        if dataset_hash != manifest.dataset_hash:
            msg = "golden dataset hash drifted since the run was created"
            raise GoldenTruthError(msg)

    def quantity_gate(self) -> list[str]:
        _, manifest = self.load()
        return [
            f"{case_type}: {manifest.counts_by_type.get(case_type, 0)} rows < {minimum}"
            for case_type, minimum in REQUIRED_GOLDEN_COUNTS.items()
            if manifest.counts_by_type.get(case_type, 0) < minimum
        ]

    def event_coverage_gate(self) -> list[str]:
        """Distinct-event semantics (audit sections 14-16): identity is
        STRUCTURAL - (symbol, effective_date, subtype) for ST and
        (symbol, effective_date) for delist. Free-form event_id strings
        can never inflate the count."""
        cases, manifest = self.load()
        problems: list[str] = []
        # ST transitions: >= 50 distinct structural events, ADD>0, REMOVE>0
        st_events: dict[tuple[str, str, str], str] = {}
        for case in cases:
            if case.event_class == "ST_TRANSITION":
                st_events[st_event_identity(case)] = case.event_subtype
        st_count = len(st_events)
        if st_count < REQUIRED_DISTINCT_EVENTS["golden_st_transition"][1]:
            problems.append(f"golden_st_transition: distinct ST_TRANSITION events {st_count} < 50")
        add_count = sum(1 for s in st_events.values() if s in ST_ADD_SUBTYPES)
        remove_count = sum(1 for s in st_events.values() if s in ST_REMOVE_SUBTYPES)
        if add_count == 0:
            problems.append("golden_st_transition: no ST_ADD/STAR_ST_ADD subtype events")
        if remove_count == 0:
            problems.append("golden_st_transition: no ST_REMOVE/STAR_ST_REMOVE subtype events")
        # Delist: distinct (symbol, effective_date) >= 20 AND symbols >= 20
        delist_identities = {delist_event_identity(c) for c in cases if c.event_class == "DELIST"}
        delist_symbols = {c.provider_symbol for c in cases if c.event_class == "DELIST"}
        if len(delist_identities) < REQUIRED_DISTINCT_EVENTS["golden_delisted"][1]:
            problems.append(
                f"golden_delisted: distinct DELIST events {len(delist_identities)} < 20"
            )
        if len(delist_symbols) < 20:
            problems.append(
                f"golden_delisted: distinct delisted securities {len(delist_symbols)} < 20"
            )
        return problems

    def review_gate(self) -> list[str]:
        """FORMAL review gate (review section 8): every case REVIEWED, and
        EVERY REVIEWED case's source artifact RESOLVES and hash-VERIFIES.

        R4A2-P0-01 fix: verifies ALL reviewed cases with complete error
        collection - never breaks on the first success.
        """
        cases, manifest = self.load()
        problems: list[str] = []
        if not manifest.fully_reviewed:
            total = sum(manifest.review_summary.values())
            problems.append(
                "golden truth not fully human-reviewed "
                f"(REVIEWED {manifest.review_summary.get('REVIEWED', 0)}/{total}; "
                "audit section 39 requires every golden entry reviewed before P0-M-1B)"
            )
        for case in cases:
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
        # R4A2-P1-03: path confinement - must resolve INSIDE <root>/evidence
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
    }
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


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
