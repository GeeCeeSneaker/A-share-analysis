"""Source Policy governance state machine (task book section 10).

States: CANDIDATE -> APPROVED -> RETIRED (no skipping, no demotion to
CANDIDATE; a broken APPROVED goes RETIRED and a replacement starts fresh).

Approval requires (designer ruling, task book 10):
    real account -> spike -> golden -> provider verification ->
    source-policy dry-run -> APPROVED

Unverified AmazingData capabilities can only ever be CANDIDATE - enforced
by requiring the evidence bundle at transition time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ashare_state.domain.types import SourcePolicyStatus


class PolicyTransitionError(RuntimeError):
    """Illegal state transition attempt."""


@dataclass(frozen=True)
class ApprovalEvidence:
    """Required bundle for CANDIDATE -> APPROVED."""

    spike_report_ref: str  # e.g. docs/spike_report_p0m1.md
    provider_verification_ref: str  # e.g. docs/provider_verification/amazingdata.md
    golden_case_refs: tuple[str, ...]  # case ids from spike_case_catalog
    dry_run_ref: str  # dry-run run id / report
    approved_by: str
    approved_at: str


_VALID = {
    (SourcePolicyStatus.CANDIDATE, SourcePolicyStatus.APPROVED),
    (SourcePolicyStatus.APPROVED, SourcePolicyStatus.RETIRED),
    (SourcePolicyStatus.CANDIDATE, SourcePolicyStatus.RETIRED),
}


def validate_transition(current: SourcePolicyStatus, target: SourcePolicyStatus) -> None:
    if current is target:
        return
    if (current, target) not in _VALID:
        msg = f"illegal source-policy transition {current} -> {target}"
        raise PolicyTransitionError(msg)


def approve_candidate(
    current: SourcePolicyStatus, evidence: ApprovalEvidence
) -> SourcePolicyStatus:
    """CANDIDATE -> APPROVED with full evidence bundle; else BLOCK."""
    validate_transition(current, SourcePolicyStatus.APPROVED)
    missing = [
        field
        for field, value in (
            ("spike_report_ref", evidence.spike_report_ref),
            ("provider_verification_ref", evidence.provider_verification_ref),
            ("golden_case_refs", evidence.golden_case_refs),
            ("dry_run_ref", evidence.dry_run_ref),
            ("approved_by", evidence.approved_by),
            ("approved_at", evidence.approved_at),
        )
        if not value
    ]
    if missing:
        msg = (
            f"approval evidence incomplete; missing: {missing} "
            "(task book 10: real spike + golden + verification + dry-run required)"
        )
        raise PolicyTransitionError(msg)
    return SourcePolicyStatus.APPROVED


def retire(current: SourcePolicyStatus, *, reason: str) -> SourcePolicyStatus:
    if not reason:
        msg = "retirement requires an auditable reason"
        raise PolicyTransitionError(msg)
    validate_transition(current, SourcePolicyStatus.RETIRED)
    return SourcePolicyStatus.RETIRED
