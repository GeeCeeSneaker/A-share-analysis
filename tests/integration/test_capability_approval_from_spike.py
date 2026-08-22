"""Capability approval self-verification tests (R3-P0-17, section 57)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ashare_state.providers.amazingdata import capability as capability_module
from ashare_state.spike import (
    CaseCatalog,
    CaseResult,
    RunKind,
    close_run,
    new_run,
)
from ashare_state.spike.model import SpikeCase
from ashare_state.storage import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _event_gate_relaxed(monkeypatch):
    """R4-A1.1: PRODUCTION runs now require the reviewed golden dataset
    (distinct-event coverage). These tests exercise OTHER gates, so the
    event/review gates are relaxed here; dedicated tests live in
    test_golden_truth_gates.py."""
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "event_coverage_gate", lambda self: [])
    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self: [])


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def fresh_registry():
    import importlib

    importlib.reload(capability_module)
    yield
    importlib.reload(capability_module)


def _make_closed_production_run(spike_root: Path, *, cases: list[tuple[str, str, CaseResult]]):
    """A CLOSED production run with the given (case_id, case_type, result)
    cases; each case gets real evidence."""
    from ashare_state.providers.amazingdata.session import AccountProfile

    profile = AccountProfile.from_scrubbed(
        {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
        host="h",
        username="u",
    )
    run, store = new_run(
        run_kind=RunKind.PRODUCTION,
        spike_root=spike_root,
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="1.1.9",
        runtime_version="V4.3.0",
        account_profile_id=profile.account_profile_id,
        account_profile=profile,
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    for case_id, case_type, result in cases:
        meta = store.write_evidence(
            run,
            f"req-{case_id}",
            endpoint="ep",
            provider_dataset="ds",
            params={},
            payload={"case": case_id},
        )
        catalog.add(
            SpikeCase(
                case_id=case_id,
                spike_run_id=run.spike_run_id,
                case_type=case_type,
                security="X",
                provider_symbol="X",
                trade_date="20260814",
                expected_value="e",
                actual_value="a",
                evidence_type="RAW_JSON",
                evidence_ref=str(meta["evidence_ref"]),
                result=result,
                evidence_hash=str(meta["content_hash"]),
            )
        )
    catalog.flush(store.run_dir(run))
    close_run(store, run)
    return run


def _daily_bar_passing_cases(count: int = 1):
    return [(f"DB{i}", "daily_bar_units", CaseResult.VALIDATED_PASS) for i in range(count)]


@pytest.mark.integration
class TestApprovalFromSpikeRun:
    def test_approval_requires_closed_run(self, conn, tmp_path: Path):
        from ashare_state.providers.amazingdata.session import AccountProfile

        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500}
        )
        run, store = new_run(
            run_kind=RunKind.PRODUCTION,
            spike_root=tmp_path / "spike",
            code_commit=_SHA,
            environment_lock_hash="e" * 64,
            config_hash="c" * 64,
            sdk_version="1.1.9",
            runtime_version="V4.3.0",
            account_profile_id=profile.account_profile_id,
            account_profile=profile,
        )
        with pytest.raises(capability_module.CapabilityGovernanceError, match="not CLOSED"):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
            )

    def test_approval_requires_capability_pass(self, conn, tmp_path: Path):
        cases = [(f"DB{i}", "daily_bar_units", CaseResult.VALIDATED_FAIL) for i in range(1)]
        run = _make_closed_production_run(tmp_path / "spike", cases=cases)
        with pytest.raises(capability_module.CapabilityGovernanceError, match="FAILED"):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
            )

    def test_approval_rejects_missing_case_refs(self, conn, tmp_path: Path):
        cases = _daily_bar_passing_cases()
        run = _make_closed_production_run(tmp_path / "spike", cases=cases)
        with pytest.raises(capability_module.CapabilityGovernanceError, match="not in run"):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
                capability_case_refs=("NONEXISTENT-CASE",),
            )

    def test_approval_rejects_failing_case_refs(self, conn, tmp_path: Path):
        cases = [(f"DB{i}", "daily_bar_units", CaseResult.VALIDATED_FAIL) for i in range(1)]
        run = _make_closed_production_run(tmp_path / "spike", cases=cases)
        with pytest.raises(capability_module.CapabilityGovernanceError, match="FAILED"):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
                capability_case_refs=("DB0",),
            )

    def test_successful_approval_from_verified_run(self, conn, tmp_path: Path):
        cases = _daily_bar_passing_cases()
        run = _make_closed_production_run(tmp_path / "spike", cases=cases)
        approved = capability_module.approve_from_spike_run(
            conn,
            "daily_bar",
            spike_root=tmp_path / "spike",
            spike_run_id=run.spike_run_id,
            approved_by="designer",
            capability_case_refs=("DB0",),
        )
        assert approved.status == capability_module.CapabilityStatus.APPROVED
        # persisted with run-derived evidence
        row = conn.execute(
            "SELECT spike_report_ref, status FROM meta_provider_capability "
            "WHERE capability='daily_bar'"
        ).fetchone()
        assert row[0] == f"spike-run:{run.spike_run_id}"
        assert row[1] == "APPROVED"
