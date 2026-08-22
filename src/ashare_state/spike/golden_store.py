"""Golden Truth Dataset store (R4-A1.1: Truth Integrity Hotfix).

Layout (append-only versions, audit R4A1-P1-01/02):
    golden_cases_v1.jsonl / truth_manifest_v1.json   (immutable snapshots)
    golden_cases_v2.jsonl / truth_manifest_v2.json   ...
    truth_manifest.json                              (ACTIVE pointer only)

Fixes over R4-A1 (audit sections 2-11):
- P0-01 manifest self-verification: case_count / counts_by_type /
  review_summary are RECOMPUTED from parsed cases and must equal the
  manifest - editing only the manifest cannot bypass any gate.
- P0-02/03 hash model split: case_semantic_hash covers golden_case_id,
  case_type, symbol, date, expected_fields, truth_source, source_ref,
  source_artifact_hash, truth_version; source_artifact_hash comes from a
  REAL external artifact (empty while COMPILED; required for REVIEWED).
- P0-04 event coverage: event_id/event_class on every case; the
  distinct-event gate enforces frozen semantics (>= 50 distinct positive
  ST transitions, >= 20 distinct delisted securities) - repeated dates of
  one event or negative samples never count.
- P0-06 review evidence: REVIEWED requires review command output
  (reviewer/at/note + source_artifact_hash), not a hand-edited flag.
- P1-02 the ACTIVE pointer selects the dataset file explicitly; no
  lexicographic "latest" guessing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ashare_state.spike.validators import GoldenCase

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")
ACTIVE_MANIFEST = "truth_manifest.json"

#: per-type minimum ROW counts (kept from R4-A1)
REQUIRED_GOLDEN_COUNTS = {
    "golden_st_transition": 50,
    "golden_delisted": 20,
    "golden_limit_regime": 30,
    "golden_corporate_action": 20,
}
#: distinct EVENT minimums (audit R4A1-P0-04): negative samples and
#: repeated dates of the same event never count toward these.
REQUIRED_DISTINCT_EVENTS = {
    "golden_st_transition": ("ST_CAP", 50),  # distinct positive ST/*ST caps
    "golden_delisted": ("DELIST", 20),  # distinct delisted securities
}


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
            # P0-02/03: case_semantic_hash re-verified per entry
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
        # P0-04: DISTINCT event ids per class (repeated dates never count)
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

    # ---------------------------------------------------------------- gates
    def verify_binding(self, *, truth_version: str, manifest_hash: str) -> None:
        _, manifest = self.load()
        if truth_version != manifest.truth_version:
            msg = f"golden truth_version drifted: run bound {truth_version!r}, dataset now {manifest.truth_version!r}"
            raise GoldenTruthError(msg)
        if manifest_hash != manifest.dataset_hash:
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
        """P0-04: distinct-event semantics (negative samples / repeated
        dates never count)."""
        _, manifest = self.load()
        problems: list[str] = []
        for case_type, (event_class, minimum) in REQUIRED_DISTINCT_EVENTS.items():
            actual = manifest.distinct_events.get(event_class, 0)
            if actual < minimum:
                problems.append(
                    f"{case_type}: distinct {event_class} events {actual} < {minimum} "
                    "(repeated dates of one event / negative samples do not count; "
                    "the reviewed dataset must add real distinct events)"
                )
        return problems

    def review_gate(self) -> list[str]:
        """REVIEWED entries must carry source_artifact_hash + review
        evidence (P0-06); production verdicts need full review."""
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
            if case.review_status == "REVIEWED" and not case.source_artifact_hash:
                problems.append(
                    f"{case.golden_case_id}: REVIEWED without source_artifact_hash "
                    "(P0-06: review must seal the real external artifact)"
                )
                break
        return problems


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


def _case_from_doc(doc: dict, dataset_truth_version: str) -> GoldenCase:
    missing = [
        field
        for field in (
            "case_semantic_hash",
            "truth_version",
            "reviewed_by",
            "reviewed_at",
            "review_status",
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
        truth_version=str(doc["truth_version"]),
        reviewed_by=str(doc["reviewed_by"]),
        reviewed_at=str(doc["reviewed_at"]),
        review_status=str(doc["review_status"]),
        event_id=str(doc["event_id"]),
        event_class=str(doc["event_class"]),
    )
