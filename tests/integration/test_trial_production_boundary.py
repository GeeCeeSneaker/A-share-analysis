"""R4-A3 A3-04: runtime truth / trial boundary tests (audit 20260826
section 7.2).

    CI/Fake = structure truth only
    Trial account = L1 connectivity only
    Production account = formal permission / endpoint / business truth

Any Trial/Fake success can NEVER mark a capability as PRODUCTION
APPROVED - enforced at BOTH approval entry points (the persisted
approval path and the spike-run-derived approval path).
"""

from __future__ import annotations

import pytest

# Access discipline (same as test_capability_governance.py): everything
# flows through the module attribute so importlib.reload() elsewhere in
# the suite cannot leave this file's by-value imports stale.
from ashare_state.providers.amazingdata import capability as capability_module


@pytest.fixture(autouse=True)
def _restore_capability_registry():
    """approve_capability mutates the GLOBAL registry - snapshot/restore
    so the A3-04 tests cannot leak APPROVED into other suites."""
    snapshot = dict(capability_module.CAPABILITY_REGISTRY)
    yield
    capability_module.CAPABILITY_REGISTRY.clear()
    capability_module.CAPABILITY_REGISTRY.update(snapshot)


def _full_evidence(account_profile_id: str):
    return capability_module.CapabilityEvidence(
        spike_report_ref="spike-run:x",
        provider_verification_ref="docs/provider_verification/amazingdata.md",
        golden_case_refs=("GT-1",),
        dry_run_ref="verdict:PASS",
        approved_by="human",
        approved_at="2026-08-26T00:00:00+00:00",
        account_profile_id=account_profile_id,
    )


class TestApprovalRefusesTrialAccounts:
    @pytest.mark.parametrize(
        "profile_id",
        [
            "TRIAL_SIMULATION_abc123",
            "TRIAL_abc123",
            "FAKE_session",
            "UNKNOWN",
            "",
        ],
    )
    def test_trial_fake_unknown_account_cannot_approve(self, profile_id):
        with pytest.raises(
            capability_module.CapabilityGovernanceError,
            match=r"not a production account|evidence incomplete",
        ):
            capability_module.approve_capability("daily_bar", _full_evidence(profile_id))

    def test_production_account_can_approve(self):
        cap = capability_module.approve_capability("daily_bar", _full_evidence("ACCOUNT_abc123"))
        assert cap.status.value == "APPROVED"
        assert cap.account_profile_id == "ACCOUNT_abc123"
        assert (
            capability_module.CAPABILITY_REGISTRY["daily_bar"].status
            is capability_module.CapabilityStatus.APPROVED
        )


class TestSpikeRunApprovalRefusesTrialAccounts:
    def test_production_run_with_trial_account_refused(self, tmp_path):
        """Defense in depth: even if a RunKind.PRODUCTION run exists under
        a TRIAL account profile (e.g. a tampered/persisted run created
        before the creation-time gate), the APPROVAL path still refuses -
        run kind alone is not production truth (audit A3-04)."""
        from ashare_state.providers.amazingdata.session import AccountProfile
        from ashare_state.spike import runner as runner_module
        from ashare_state.spike.golden_store import GoldenTruthStore
        from ashare_state.spike.model import RunKind
        from ashare_state.spike.runner import close_run, new_run

        trial_profile = AccountProfile(
            raw_profile={"PermissionCode": "1|2", "SubscribeLimitNum": 500},
            auth_ok=True,
            profile_parsed=True,
            account_profile_id="TRIAL_SIMULATION_abc123",
        )
        with pytest.MonkeyPatch.context() as mp:
            # relax the CREATION-time gate + formal gates: this test
            # isolates the APPROVAL-path refusal
            mp.setattr(runner_module, "verify_production_account", lambda profile: None)
            mp.setattr(GoldenTruthStore, "quantity_gate", lambda self, *a, **k: [])
            mp.setattr(GoldenTruthStore, "event_coverage_gate", lambda self, *a, **k: [])
            mp.setattr(GoldenTruthStore, "review_gate", lambda self, *a, **k: [])
            from ashare_state.spike import trading_rule as rule_module

            mp.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])
            run, store = new_run(
                run_kind=RunKind.PRODUCTION,
                spike_root=tmp_path / "spike",
                code_commit="a" * 40,
                environment_lock_hash="e" * 64,
                config_hash="c" * 64,
                sdk_version="1.1.9",
                runtime_version="V4.3.0",
                account_profile_id=trial_profile.account_profile_id,
                as_of_date="20260826",
                account_profile=trial_profile,
            )
            close_run(store, run)
        import duckdb

        conn = duckdb.connect(":memory:")
        conn.execute(
            "CREATE TABLE meta_provider_capability ("
            "provider VARCHAR, capability VARCHAR, status VARCHAR, "
            "spike_report_ref VARCHAR, provider_verification_ref VARCHAR, "
            "golden_case_refs VARCHAR, dry_run_ref VARCHAR, "
            "account_profile_id VARCHAR, approved_by VARCHAR, "
            "adapter_version VARCHAR, verified_at VARCHAR)"
        )
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="not a production account"
        ):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="human",
            )
