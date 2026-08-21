"""Source Policy state machine tests (task book section 10)."""

from __future__ import annotations

import pytest

from ashare_state.domain.types import SourcePolicyStatus
from ashare_state.storage.source_policy import (
    ApprovalEvidence,
    PolicyTransitionError,
    approve_candidate,
    retire,
    validate_transition,
)

EVIDENCE = ApprovalEvidence(
    spike_report_ref="docs/spike_report_p0m1.md",
    provider_verification_ref="docs/provider_verification/amazingdata.md",
    golden_case_refs=("B2-SECMASTER-0001",),
    dry_run_ref="dryrun-2026-09-01",
    approved_by="designer",
    approved_at="2026-09-01T00:00:00+00:00",
)


class TestStateMachine:
    def test_candidate_to_approved_with_evidence(self):
        assert (
            approve_candidate(SourcePolicyStatus.CANDIDATE, EVIDENCE) is SourcePolicyStatus.APPROVED
        )

    def test_approved_requires_full_evidence(self):
        for broken in (
            ApprovalEvidence("", "pv", ("c",), "dr", "by", "at"),
            ApprovalEvidence("sr", "pv", (), "dr", "by", "at"),
            ApprovalEvidence("sr", "pv", ("c",), "", "by", "at"),
        ):
            with pytest.raises(PolicyTransitionError, match="evidence incomplete"):
                approve_candidate(SourcePolicyStatus.CANDIDATE, broken)

    def test_retire_paths(self):
        assert retire(SourcePolicyStatus.APPROVED, reason="replaced") is SourcePolicyStatus.RETIRED
        assert (
            retire(SourcePolicyStatus.CANDIDATE, reason="withdrawn") is SourcePolicyStatus.RETIRED
        )

    def test_retire_requires_reason(self):
        with pytest.raises(PolicyTransitionError, match="auditable reason"):
            retire(SourcePolicyStatus.APPROVED, reason="")

    def test_no_demotion_to_candidate(self):
        with pytest.raises(PolicyTransitionError, match="illegal"):
            validate_transition(SourcePolicyStatus.APPROVED, SourcePolicyStatus.CANDIDATE)

    def test_no_resurrection(self):
        with pytest.raises(PolicyTransitionError, match="illegal"):
            validate_transition(SourcePolicyStatus.RETIRED, SourcePolicyStatus.APPROVED)

    def test_self_transition_allowed(self):
        validate_transition(SourcePolicyStatus.CANDIDATE, SourcePolicyStatus.CANDIDATE)
