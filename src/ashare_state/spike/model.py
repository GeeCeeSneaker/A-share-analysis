"""Spike framework core models (Round-2 audit sections 5/7/24).

R2-P0-04: every case binds to a SpikeRun; verdicts aggregate ONE closed
run only. Dry-run / trial / production evidence are physically isolated.

R2-P0-03: case results form a strict state machine - only VALIDATED_PASS
satisfies the Core Gate; DIFF_EXPLAINED alone never does (the validator
decides equivalence and records it explicitly).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class RunKind(StrEnum):
    DRY_RUN = "DRY_RUN"
    TRIAL = "TRIAL"
    PRODUCTION = "PRODUCTION"


class RunStatus(StrEnum):
    """R3-P0-01: formal runs ALWAYS reach a terminal state."""

    RUNNING = "RUNNING"
    CLOSED = "CLOSED"  # all phases executed (success or partial semantic fails)
    FAILED = "FAILED"  # aborted by auth/account/fatal error
    ABORTED = "ABORTED"  # operator-interrupted


TERMINAL_RUN_STATUSES = (RunStatus.CLOSED, RunStatus.FAILED, RunStatus.ABORTED)


class RunFailureReason(StrEnum):
    """Why a run FAILED (terminal detail)."""

    FAILED_ACCOUNT = "FAILED_ACCOUNT"  # ProviderAuthError: run cannot continue
    FRAMEWORK_ERROR = "FRAMEWORK_ERROR"


class CaseResult(StrEnum):
    """Audit R2 section 4: eight states, semantic verdicts only."""

    OBSERVED = "OBSERVED"  # data seen, validator not yet run
    VALIDATED_PASS = "VALIDATED_PASS"  # semantic validation passed
    VALIDATED_FAIL = "VALIDATED_FAIL"  # semantic validation failed
    DIFF_EXPLAINED = "DIFF_EXPLAINED"  # difference attributed; equivalence decided by validator
    NOT_TESTABLE_PERMISSION = "NOT_TESTABLE_PERMISSION"  # entitlement denied
    NOT_TESTABLE_ACCOUNT = "NOT_TESTABLE_ACCOUNT"  # account-level block (flow etc.)
    NOT_TESTABLE_TIME = "NOT_TESTABLE_TIME"  # outside session / data not yet available
    MISSING = "MISSING"  # capability produced nothing


#: results that can never satisfy a core gate (see core_gate_satisfied)


def core_gate_satisfied(result: CaseResult, *, equivalent_pass: bool = False) -> bool:
    """Only VALIDATED_PASS (or DIFF_EXPLAINED with explicit validator
    equivalence) can satisfy the Core Gate (audit R2 section 4)."""
    if result is CaseResult.VALIDATED_PASS:
        return True
    return result is CaseResult.DIFF_EXPLAINED and equivalent_pass


@dataclass(frozen=True)
class SpikeRun:
    """Run-scope identity: every case and evidence file binds to this."""

    spike_run_id: str
    run_kind: RunKind
    provider: str = "amazingdata"
    account_profile_id: str = "UNKNOWN"
    sdk_version: str | None = None
    runtime_version: str | None = None
    code_commit: str = "unknown"
    environment_lock_hash: str = ""
    config_hash: str = ""
    as_of_date: str = ""  # R3-P1-09: the single run-wide as-of reference
    # R4-P0-02/12: golden binding + catalog seal (set at creation / close)
    golden_truth_version: str = ""
    golden_dataset_file: str = ""
    golden_dataset_hash: str = ""
    case_catalog_hash: str = ""
    #: R4-A2.4 P0-03 + R4-A2.5 P0-02: the run BINDS the trading-rule
    #: dataset it was created with. The binding captures the FULL dataset
    #: file list + the combined hash over (rel path + bytes) of every file
    #: (the ACTIVE-manifest algorithm) - tampering ANY bound file blocks
    #: the replay. verdict/resume never read the working tree's ACTIVE.
    trading_rule_version: str = ""
    #: R4-A2.6 P0-04: the run binds BOTH identities explicitly -
    #: trading_rule_version = the manifest SELECTOR id (v20260824-compiled)
    #: trading_rule_dataset_version = the dataset CONTENT version (yaml)
    trading_rule_dataset_version: str = ""
    trading_rule_dataset_files: list[str] = field(default_factory=list)
    trading_rule_dataset_hash: str = ""
    trading_rule_review_status: str = ""  # COMPILED | REVIEWED at binding time
    trading_rule_source_version: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    ended_at: str | None = None
    status: str = "RUNNING"
    failure_reason: str | None = None  # RunFailureReason when FAILED

    def to_json(self) -> dict[str, Any]:
        return {
            "spike_run_id": self.spike_run_id,
            "run_kind": str(self.run_kind),
            "provider": self.provider,
            "account_profile_id": self.account_profile_id,
            "sdk_version": self.sdk_version,
            "runtime_version": self.runtime_version,
            "code_commit": self.code_commit,
            "environment_lock_hash": self.environment_lock_hash,
            "config_hash": self.config_hash,
            "as_of_date": self.as_of_date,
            "golden_truth_version": self.golden_truth_version,
            "golden_dataset_file": self.golden_dataset_file,
            "golden_dataset_hash": self.golden_dataset_hash,
            "case_catalog_hash": self.case_catalog_hash,
            "trading_rule_version": self.trading_rule_version,
            "trading_rule_dataset_version": self.trading_rule_dataset_version,
            "trading_rule_dataset_files": list(self.trading_rule_dataset_files),
            "trading_rule_dataset_hash": self.trading_rule_dataset_hash,
            "trading_rule_review_status": self.trading_rule_review_status,
            "trading_rule_source_version": self.trading_rule_source_version,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "failure_reason": self.failure_reason,
        }

    def provenance_complete(self) -> bool:
        """R3-P0-15: formal verdict requires full provenance.

        R4-P0-02: golden binding (truth_version + manifest_hash) is part
        of provenance for formal runs.

        R4-A2.6 P1-01: the trading-rule binding (selector version +
        dataset files/hash + review status) is part of formal provenance
        too - ADR-013 made the rule dataset a formal semantic SoR, and
        downstream consumers (Capability Approval, Replay, Publish) reuse
        this API: it must never claim completeness with the semantic SoR
        unbound.
        """
        required = (
            self.code_commit,
            self.environment_lock_hash,
            self.config_hash,
            self.sdk_version or "",
            self.runtime_version or "",
            self.account_profile_id,
        )
        if not all(value and value != "unknown" for value in required):
            return False
        if self.run_kind != RunKind.PRODUCTION:
            return True
        golden_bound = bool(self.golden_truth_version and self.golden_dataset_hash)
        # R4-A2.7 P0-03: the semantic SoR binding is complete only with the
        # selector version + the dataset content version + the source
        # lineage + the file identity + the review status
        rules_bound = bool(
            self.trading_rule_version
            and self.trading_rule_dataset_version
            and self.trading_rule_source_version
            and self.trading_rule_dataset_files
            and self.trading_rule_dataset_hash
            and self.trading_rule_review_status
        )
        return golden_bound and rules_bound


@dataclass(frozen=True)
class SpikeCase:
    """One auditable case (audit R2 sections 4/7/24.3).

    Uniqueness: (spike_run_id, case_id); the catalog rejects duplicates.
    Case ids encode semantics (e.g. B3-ST-600000.SH-20260814), never just
    method+date.
    """

    case_id: str
    spike_run_id: str
    case_type: str
    security: str
    provider_symbol: str
    trade_date: str
    expected_value: str
    actual_value: str
    evidence_type: str  # RAW_JSON / PARQUET / DOC / EXCHANGE_NOTICE
    evidence_ref: str
    result: CaseResult
    reason_code: str = ""  # required for DIFF_EXPLAINED
    validator_id: str = ""
    validator_version: str = ""
    evidence_hash: str = ""
    equivalent_pass: bool = False  # validator-decided equivalence for DIFF_EXPLAINED
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def validate(self) -> None:
        if self.result is CaseResult.DIFF_EXPLAINED and not self.reason_code:
            msg = f"case {self.case_id}: DIFF_EXPLAINED requires a reason_code"
            raise ValueError(msg)
        if self.result is CaseResult.DIFF_EXPLAINED and not self.validator_id:
            msg = (
                f"case {self.case_id}: DIFF_EXPLAINED requires the validator "
                "that decided equivalence"
            )
            raise ValueError(msg)
