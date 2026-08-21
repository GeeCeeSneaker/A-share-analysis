"""Spike case catalog (design ruling 11).

Every Spike observation must land as an auditable case record - never as a
stray stdout line. Field layout follows the ruling exactly:

    case_id, case_type, security/provider_symbol, trade_date,
    expected_value, actual_value, evidence_type, evidence_ref,
    result, reason_code, checked_at

Difference attribution reason codes (keep in sync with
src/ashare_state/domain/types.py::DifferenceReasonCode - this script tree
is deliberately independent of the production package):

    CORPORATE_ACTION / PRICE_TICK_ROUNDING / AFTER_HOURS_INCLUDED /
    SESSION_BOUNDARY / SYMBOL_MAPPING / SOURCE_REVISION / PROVIDER_TIMING /
    DOCUMENTED_UNIT_DIFFERENCE

A difference without a reason code is a FAIL ("differences must be
explainable, not excusable").

Verdict levels (design ruling 3.1 / 4):
    per-capability: EXACT_EQUIVALENT / DERIVABLE_EQUIVALENT /
                    ALTERNATIVE_SEMANTICS / MISSING
    overall:         GO_CORE / GO_DEGRADED / NO_GO
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

REASON_CODES = {
    "CORPORATE_ACTION",
    "PRICE_TICK_ROUNDING",
    "AFTER_HOURS_INCLUDED",
    "SESSION_BOUNDARY",
    "SYMBOL_MAPPING",
    "SOURCE_REVISION",
    "PROVIDER_TIMING",
    "DOCUMENTED_UNIT_DIFFERENCE",
}

EQUIVALENCE_VERDICTS = {
    "EXACT_EQUIVALENT",
    "DERIVABLE_EQUIVALENT",
    "ALTERNATIVE_SEMANTICS",
    "MISSING",
}
SPIKE_VERDICTS = {"GO_CORE", "GO_DEGRADED", "NO_GO"}

# Overall verdict inputs (design ruling 16): core facts must ALL pass for
# GO_CORE; free-float / SW taxonomy / real dual-source reconciliation may be
# missing -> GO_DEGRADED (blocks P0b / parts of P0-M2); core failure -> NO_GO.
CORE_FACT_CAPABILITIES = [
    "security_master_with_delisted",
    "daily_bar_units",
    "historical_st_suspend",
    "limit_price_and_no_limit_days",
    "adj_factor_corporate_action_continuity",
    "history_start_2018_plus_warmup",
    "symbol_mapping_unambiguous",
    "sdk_permission_cache_freshness",
]
DEGRADED_OK_MISSING = [
    "free_float_equivalence",
    "sw_taxonomy",
    "dual_source_reconciliation",
]


@dataclass
class SpikeCase:
    case_id: str
    case_type: str
    security: str
    provider_symbol: str
    trade_date: str
    expected_value: str
    actual_value: str
    evidence_type: str  # RAW_JSON / PARQUET / SCREENSHOT / DOC / EXCHANGE_NOTICE
    evidence_ref: str
    result: str  # PASS / FAIL / DIFF_EXPLAINED
    reason_code: str  # "" for clean pass; one of REASON_CODES for DIFF_EXPLAINED
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def validate(self) -> None:
        if self.result == "DIFF_EXPLAINED" and self.reason_code not in REASON_CODES:
            msg = f"case {self.case_id}: DIFF_EXPLAINED requires a valid reason_code"
            raise ValueError(msg)
        if self.result == "FAIL" and self.reason_code:
            msg = (
                f"case {self.case_id}: FAIL must carry an unexplained cause "
                "investigation, not a reason_code waiver"
            )
            raise ValueError(msg)


class CaseCatalog:
    """Append-only JSONL catalog + CSV export for the report."""

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = results_dir
        self.jsonl_path = results_dir / "spike_case_catalog.jsonl"
        self.csv_path = results_dir / "spike_case_catalog.csv"
        self._cases: list[SpikeCase] = []
        self._persisted_count = 0  # cases already on disk (loaded or flushed)

    def add(self, case: SpikeCase) -> None:
        case.validate()
        self._cases.append(case)

    def load_existing(self) -> None:
        if self.jsonl_path.exists():
            for line in self.jsonl_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._cases.append(SpikeCase(**json.loads(line)))
        self._persisted_count = len(self._cases)

    def flush(self) -> Path:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        # JSONL: append ONLY the cases added in this session (loaded cases are
        # already on disk - appending them again would duplicate evidence).
        new_cases = self._cases[self._persisted_count :]
        if new_cases:
            with self.jsonl_path.open("a", encoding="utf-8") as fh:
                for case in new_cases:
                    fh.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")
            self._persisted_count = len(self._cases)
        with self.csv_path.open("w", encoding="utf-8", newline="") as fh:
            fieldnames = [f.name for f in fields(SpikeCase)]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for case in self._cases:
                writer.writerow(asdict(case))
        return self.jsonl_path

    def by_type(self, case_type: str) -> list[SpikeCase]:
        return [c for c in self._cases if c.case_type == case_type]

    def stats(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for c in self._cases:
            bucket = out.setdefault(c.case_type, {"PASS": 0, "DIFF_EXPLAINED": 0, "FAIL": 0})
            bucket[c.result] += 1
        return out


def compute_overall_verdict(capability_verdicts: dict[str, str]) -> str:
    """Map per-capability verdicts to GO_CORE / GO_DEGRADED / NO_GO.

    capability_verdicts: capability -> one of PASS / MISSING / FAIL.
    """
    core_fail = [
        cap for cap in CORE_FACT_CAPABILITIES if capability_verdicts.get(cap, "MISSING") == "FAIL"
    ]
    if core_fail:
        return "NO_GO"
    core_missing = [
        cap
        for cap in CORE_FACT_CAPABILITIES
        if capability_verdicts.get(cap, "MISSING") not in ("PASS",)
    ]
    if core_missing:
        return "NO_GO"  # core facts unverified = cannot grant P0a either
    degraded = [
        cap for cap in DEGRADED_OK_MISSING if capability_verdicts.get(cap, "MISSING") == "MISSING"
    ]
    return "GO_DEGRADED" if degraded else "GO_CORE"
