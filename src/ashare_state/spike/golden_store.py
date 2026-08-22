"""Golden Truth Dataset store (audit R4-P0-01/02/12).

The golden dataset is a VERSIONED EVIDENCE SET on disk:
    data/golden/provider/amazingdata/golden_cases_v1.jsonl
    data/golden/provider/amazingdata/truth_manifest.json

Integrity chain (R4-P0-02):
    External Truth Artifact (per case)
    -> source_hash  (SHA-256 of the canonical truth statement)
    -> manifest_hash (SHA-256 of the whole jsonl)
    -> SpikeRun.golden_truth_version + golden_manifest_hash (set at run
       creation; resume AND verdict re-verify)

Review gate (R4-P0-01 + audit section 39):
    production verdicts require every golden entry to be human-reviewed
    (review_status=REVIEWED). v1 ships COMPILED entries; the review step
    corrects/removes entries and bumps the truth version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ashare_state.spike.validators import GoldenCase

GOLDEN_ROOT = Path("data/golden/provider/amazingdata")

#: core-gate minimum counts per golden case type (audit R4-P0-01/04)
REQUIRED_GOLDEN_COUNTS = {
    "golden_st_transition": 50,
    "golden_delisted": 20,
    "golden_limit_regime": 30,
    "golden_corporate_action": 20,
}


class GoldenTruthError(RuntimeError):
    """Golden dataset integrity violation."""


@dataclass(frozen=True)
class GoldenManifest:
    truth_version: str
    manifest_hash: str
    case_count: int
    counts_by_type: dict[str, int]
    review_summary: dict[str, int]

    @property
    def quantities_complete(self) -> bool:
        return all(
            self.counts_by_type.get(case_type, 0) >= minimum
            for case_type, minimum in REQUIRED_GOLDEN_COUNTS.items()
        )

    @property
    def fully_reviewed(self) -> bool:
        total = sum(self.review_summary.values())
        return total > 0 and self.review_summary.get("REVIEWED", 0) == total


class GoldenTruthStore:
    """Loads + seals the versioned golden dataset."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else GOLDEN_ROOT
        self._jsonl: Path | None = None
        self._manifest: GoldenManifest | None = None
        self._cases: list[GoldenCase] | None = None

    # -------------------------------------------------------------- paths
    def _discover(self) -> Path:
        """Newest golden_cases_*.jsonl under the root."""
        candidates = sorted(self.root.glob("golden_cases_*.jsonl"))
        if not candidates:
            msg = f"no golden_cases_*.jsonl under {self.root} (run scripts/golden/compile_v1.py)"
            raise GoldenTruthError(msg)
        return candidates[-1]

    def _manifest_path(self) -> Path:
        return self.root / "truth_manifest.json"

    # --------------------------------------------------------------- load
    def load(self) -> tuple[list[GoldenCase], GoldenManifest]:
        """Load + FULLY VERIFY the dataset (source hashes, manifest hash)."""
        if self._cases is not None and self._manifest is not None:
            return self._cases, self._manifest
        jsonl = self._discover()
        raw_bytes = jsonl.read_bytes()
        manifest_hash = hashlib.sha256(raw_bytes).hexdigest()

        manifest_doc = json.loads(self._manifest_path().read_text(encoding="utf-8"))
        if manifest_doc["manifest_hash"] != manifest_hash:
            msg = (
                "golden manifest hash mismatch: dataset file was modified "
                "after sealing (expected "
                f"{str(manifest_doc['manifest_hash'])[:12]}..., got {manifest_hash[:12]}...)"
            )
            raise GoldenTruthError(msg)

        cases: list[GoldenCase] = []
        seen_ids: set[str] = set()
        for line in raw_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue
            doc = json.loads(line)
            golden = _case_from_doc(doc, manifest_doc["truth_version"])
            # R4-P0-02: source_hash is REQUIRED and re-verified per entry
            canonical = _truth_statement(golden)
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if golden.source_hash != expected:
                msg = (
                    f"golden case {golden.golden_case_id}: source_hash mismatch "
                    "(entry edited without re-sealing)"
                )
                raise GoldenTruthError(msg)
            if golden.golden_case_id in seen_ids:
                msg = f"duplicate golden_case_id {golden.golden_case_id}"
                raise GoldenTruthError(msg)
            seen_ids.add(golden.golden_case_id)
            cases.append(golden)

        manifest = GoldenManifest(
            truth_version=str(manifest_doc["truth_version"]),
            manifest_hash=manifest_hash,
            case_count=int(manifest_doc["case_count"]),
            counts_by_type=dict(manifest_doc["counts_by_type"]),
            review_summary=dict(manifest_doc.get("review_summary", {})),
        )
        if manifest.case_count != len(cases):
            msg = f"manifest case_count {manifest.case_count} != jsonl rows {len(cases)}"
            raise GoldenTruthError(msg)
        self._jsonl, self._manifest, self._cases = jsonl, manifest, cases
        return cases, manifest

    # -------------------------------------------------------------- gates
    def verify_binding(self, *, truth_version: str, manifest_hash: str) -> None:
        """R4-P0-02: resume/verdict re-verify the run's golden binding."""
        _, manifest = self.load()
        if truth_version != manifest.truth_version:
            msg = (
                f"golden truth_version drifted: run bound {truth_version!r}, "
                f"dataset now {manifest.truth_version!r}"
            )
            raise GoldenTruthError(msg)
        if manifest_hash != manifest.manifest_hash:
            msg = "golden manifest_hash drifted since the run was created"
            raise GoldenTruthError(msg)

    def quantity_gate(self) -> list[str]:
        """R4-P0-01: required minimum counts per golden type."""
        _, manifest = self.load()
        return [
            f"{case_type}: {manifest.counts_by_type.get(case_type, 0)} < {minimum}"
            for case_type, minimum in REQUIRED_GOLDEN_COUNTS.items()
            if manifest.counts_by_type.get(case_type, 0) < minimum
        ]

    def review_gate(self) -> list[str]:
        """Audit section 39: production verdicts need fully-reviewed truth."""
        _, manifest = self.load()
        if manifest.fully_reviewed:
            return []
        total = sum(manifest.review_summary.values())
        return [
            "golden truth not fully human-reviewed "
            f"(REVIEWED {manifest.review_summary.get('REVIEWED', 0)}/{total}; "
            "audit section 39 requires every golden entry reviewed before P0-M-1B)"
        ]


def _truth_statement(golden: GoldenCase) -> str:
    doc = {
        "golden_case_id": golden.golden_case_id,
        "provider_symbol": golden.provider_symbol,
        "trade_date": golden.trade_date,
        "expected_fields": golden.expected_fields,
        "truth_source": golden.truth_source,
        "source_ref": golden.source_ref,
    }
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


def _case_from_doc(doc: dict, dataset_truth_version: str) -> GoldenCase:
    """Materialize a GoldenCase; missing seal fields are integrity errors."""
    missing = [
        field
        for field in ("source_hash", "truth_version", "reviewed_by", "reviewed_at", "review_status")
        if not doc.get(field)
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
        source_hash=str(doc["source_hash"]),
        truth_version=str(doc["truth_version"]),
        reviewed_by=str(doc["reviewed_by"]),
        reviewed_at=str(doc["reviewed_at"]),
        review_status=str(doc["review_status"]),
    )
