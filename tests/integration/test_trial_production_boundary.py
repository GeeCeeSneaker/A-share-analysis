"""Trial / Production truth boundary tests.

R4-A3 A3-04: Fake/Trial success never grants PRODUCTION capability truth.
R4-A3.1 P0-03 (audit 20260827): the boundary is now a POSITIVE allowlist -
an EXACT match with the frozen production identity (configs/
production_account.yaml). The previous "not Trial == Production"
blacklist was FAIL-OPEN (any unknown/educational/other-vendor-tier
account was stamped ACCOUNT_* and became approval-eligible); these
tests pin the corrected semantics:

- an arbitrary ACCOUNT_* id can NOT approve (no positive match);
- an unknown NON-TRIAL profile is NOT automatically production;
- only the exact frozen identity is eligible;
- a mismatching identity BLOCKS;
- a missing frozen identity BLOCKS (fail closed - the repo truth today);
- RunKind.PRODUCTION never substitutes for account identity.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.integration._capability_test_persistence import (
    approve_and_persist_testonly,
)

from ashare_state.providers.amazingdata import capability as capability_module
from ashare_state.providers.amazingdata import production_identity as pi
from ashare_state.providers.amazingdata.capability import CapabilityEvidence
from ashare_state.providers.amazingdata.session import AccountProfile
from ashare_state.spike import CaseCatalog, CaseResult, RunKind, close_run, new_run
from ashare_state.spike.model import SpikeCase
from ashare_state.spike.runner import verify_production_account

_SHA = "a" * 40


def _profile(**kwargs) -> AccountProfile:
    base = {
        "PermissionCode": "1|2",
        "SubscribeLimitNum": 5000,
        "TotalWeekFlow": 500,
    }
    return AccountProfile.from_scrubbed(base, **kwargs)


def _freeze(monkeypatch, profile: AccountProfile) -> None:
    frozen = pi.FrozenProductionIdentity(
        account_profile_id=profile.account_profile_id,
        confirmed_at="2026-08-27T00:00:00+00:00",
        confirmed_by="r4-a3.1-test",
    )
    monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)


@pytest.fixture(autouse=True)
def _golden_and_rule_gates_relaxed(monkeypatch):
    """These tests exercise the ACCOUNT boundary, not the golden/rule
    review lifecycles (dedicated tests: test_golden_truth_gates.py,
    test_trading_rule_binding.py)."""
    from ashare_state.spike import trading_rule as rule_module
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "event_coverage_gate", lambda self, *a, **k: [])
    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self, *a, **k: [])
    monkeypatch.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])


@pytest.fixture
def conn():
    import duckdb

    from ashare_state.storage import apply_migrations

    connection = duckdb.connect(":memory:")
    apply_migrations(connection, Path(__file__).resolve().parents[2] / "migrations")
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def fresh_registry():
    import importlib

    importlib.reload(capability_module)
    yield
    importlib.reload(capability_module)


def _evidence(account_profile_id: str) -> CapabilityEvidence:
    return CapabilityEvidence(
        spike_report_ref="docs/spike_report_p0m1.md",
        provider_verification_ref="docs/provider_verification/amazingdata.md",
        golden_case_refs=("B2-SECMASTER-0001",),
        dry_run_ref="dryrun-2026-09-01",
        approved_by="designer",
        approved_at="2026-09-01T00:00:00+00:00",
        account_profile_id=account_profile_id,
    )


@pytest.mark.integration
class TestApprovalRefusesTrialAccounts:
    """A3-04: trial/fake/unknown accounts can never approve."""

    @pytest.mark.parametrize(
        "account_profile_id",
        ["TRIAL_abc123", "TRIAL_SIMULATION_x", "FAKE_session", "UNKNOWN", "UNKNOWN_deadbeef"],
    )
    def test_trial_fake_unknown_account_cannot_approve(self, conn, monkeypatch, account_profile_id):
        # even with a frozen identity configured, non-matching ids refuse
        _freeze(monkeypatch, _profile(host="h", username="u"))
        with pytest.raises(capability_module.CapabilityGovernanceError):
            approve_and_persist_testonly(conn, "daily_bar", _evidence(account_profile_id))

    def test_arbitrary_account_id_cannot_approve_without_positive_match(self, conn, monkeypatch):
        """R4-A3.1 P0-03 core fix: the fail-open hole - an arbitrary
        'ACCOUNT_abc123' (the old test's production stand-in!) is NOT
        production truth. Only the exact frozen identity may approve."""
        real_production = _profile(host="h", username="u")
        _freeze(monkeypatch, real_production)
        impostor = "ACCOUNT_abc123"  # non-trial, but NOT the frozen identity
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="frozen production identity"
        ):
            approve_and_persist_testonly(conn, "daily_bar", _evidence(impostor))

    def test_no_frozen_identity_blocks_all_approval(self, conn, monkeypatch):
        """Fail closed: with nothing frozen (the repo truth today - the
        formal production account is not opened/confirmed), NO account
        can approve, not even a well-formed non-trial one."""
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: None)
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="no frozen production"
        ):
            approve_and_persist_testonly(conn, "daily_bar", _evidence("ACCOUNT_whatever123"))

    def test_exact_frozen_identity_can_approve(self, conn, monkeypatch):
        """The positive allowlist path: an EXACT match with the frozen
        identity (complete, entitlement-verified profile) approves."""
        production = _profile(host="h", username="u")
        _freeze(monkeypatch, production)
        approved = approve_and_persist_testonly(
            conn, "daily_bar", _evidence(production.account_profile_id)
        )
        assert approved.status == capability_module.CapabilityStatus.APPROVED

    def test_unknown_non_trial_profile_is_not_production_kind(self):
        """A parsed non-trial profile is UNKNOWN, never an implicit
        PRODUCTION upgrade (production is a governance fact, not a
        parsing outcome)."""
        profile = _profile(host="h", username="u")
        assert profile.kind is pi.AccountKind.UNKNOWN
        assert profile.account_profile_id.startswith("UNKNOWN_")

    def test_production_account_status_positive_match(self, monkeypatch):
        profile = _profile(host="h", username="u")
        _freeze(monkeypatch, profile)
        kind, reason = pi.production_account_status(profile)
        assert kind is pi.AccountKind.PRODUCTION
        assert "exact match" in reason

    def test_production_account_status_mismatch_is_unknown(self, monkeypatch):
        _freeze(monkeypatch, _profile(host="h", username="u"))
        other = _profile(host="10.0.0.9", username="other-user")
        kind, _ = pi.production_account_status(other)
        assert kind is pi.AccountKind.UNKNOWN

    def test_production_account_status_unfrozen_fails_closed(self, monkeypatch):
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: None)
        kind, reason = pi.production_account_status(_profile(host="h", username="u"))
        assert kind is pi.AccountKind.UNKNOWN
        assert "fail closed" in reason


@pytest.mark.integration
class TestVerifyProductionAccount:
    def test_unfrozen_identity_refuses_production_run(self, monkeypatch):
        """Fail closed: without a frozen identity NO production run opens
        (this is the current repo truth until P0-M-1B)."""
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: None)
        with pytest.raises(Exception, match="positive production identity not confirmed"):
            verify_production_account(_profile(host="h", username="u"))

    def test_mismatched_identity_refuses_production_run(self, monkeypatch):
        _freeze(monkeypatch, _profile(host="h", username="u"))
        other = _profile(host="10.0.0.9", username="other-user")
        with pytest.raises(Exception, match="not the frozen production identity"):
            verify_production_account(other)

    def test_frozen_identity_passes_production_run(self, monkeypatch):
        profile = _profile(host="h", username="u")
        _freeze(monkeypatch, profile)
        verify_production_account(profile)  # no raise

    def test_trial_profile_refused_even_with_frozen_identity(self, monkeypatch):
        _freeze(monkeypatch, _profile(host="h", username="u"))
        trial = AccountProfile.from_scrubbed(
            {"PermissionCode": "3|4|32|33", "SubscribeLimitNum": 100, "TotalWeekFlow": 10},
            host="h",
            username="u",
        )
        with pytest.raises(Exception, match="TRIAL_SIMULATION"):
            verify_production_account(trial)


@pytest.mark.integration
class TestSpikeRunApprovalRefusesTrialAccounts:
    """Run-kind PRODUCTION never substitutes for account identity."""

    def _closed_run(self, tmp_path: Path, account_profile_id: str):
        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            host="h",
            username="u",
        )
        run, store = new_run(
            run_kind=RunKind.PRODUCTION,
            spike_root=tmp_path / "spike",
            code_commit=_SHA,
            environment_lock_hash="e" * 64,
            config_hash="c" * 64,
            sdk_version="1.1.9",
            runtime_version="V4.3.0",
            account_profile_id=account_profile_id,
            account_profile=profile,
        )
        catalog = CaseCatalog(store, run.spike_run_id)
        meta = store.write_evidence(
            run,
            "req-trial-refusal",
            endpoint="ep",
            provider_dataset="ds",
            params={},
            payload={"case": "refusal"},
        )
        catalog.add(
            SpikeCase(
                case_id="DB0",
                spike_run_id=run.spike_run_id,
                case_type="daily_bar_units",
                security="X",
                provider_symbol="X",
                trade_date="20260814",
                expected_value="e",
                actual_value="a",
                evidence_type="RAW_JSON",
                evidence_ref=str(meta["evidence_ref"]),
                result=CaseResult.VALIDATED_PASS,
                evidence_hash=str(meta["content_hash"]),
            )
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        return run

    def test_production_run_with_mismatched_account_refused(self, conn, tmp_path, monkeypatch):
        """R4-A3.1 P0-03: a PRODUCTION-kind run whose account is not the
        frozen identity cannot approve - run kind is not account truth."""
        real = _profile(host="h", username="u")
        _freeze(monkeypatch, real)
        run = self._closed_run(tmp_path, account_profile_id="ACCOUNT_somethingelse")
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="frozen production identity"
        ):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
            )

    def test_production_run_without_frozen_identity_refused(self, conn, tmp_path, monkeypatch):
        """RunKind.PRODUCTION does not substitute for the account identity:
        with nothing frozen the approval fails closed. (The run itself
        opens under a temporarily-frozen identity - unfreezing afterwards
        models 'the confirmation was never made'.)"""
        profile = _profile(host="h", username="u")
        _freeze(monkeypatch, profile)
        run = self._closed_run(tmp_path, account_profile_id=profile.account_profile_id)
        # unfreeze: no production identity exists anymore
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: None)
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="no frozen production"
        ):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
            )
