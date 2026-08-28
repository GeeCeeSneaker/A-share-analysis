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


@pytest.fixture(autouse=True)
def _rule_review_gate_relaxed(monkeypatch):
    """R4-A2.4: the trading-rule review gate has dedicated tests in
    test_trading_rule_binding.py."""
    from ashare_state.spike import trading_rule as rule_module

    monkeypatch.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])


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


@pytest.fixture(autouse=True)
def _frozen_production_identity(monkeypatch):
    """R4-A3.1 P0-03: freeze the positive production identity matching the
    profile _make_closed_production_run builds (host=h/username=u) - the
    real repo stays fail closed."""
    from ashare_state.providers.amazingdata import production_identity as pi
    from ashare_state.providers.amazingdata.session import AccountProfile

    profile = AccountProfile.from_scrubbed(
        {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
        host="h",
        username="u",
    )
    frozen = pi.FrozenProductionIdentity(
        account_profile_id=profile.account_profile_id,
        confirmed_at="2026-08-27T00:00:00+00:00",
        confirmed_by="r4-a3.1-test",
    )
    monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)


def _add_formal_gate_proof(store, run, catalog, capability: str) -> None:
    """Attach the formal gate proof cases a CLOSED run needs for
    approval (R4-A3.1 P0-01 + R4-B1 B1-04): PERMISSION/BUSINESS
    (persisted probe evidence), one ENDPOINT case PER declared
    requirement (exact endpoint identity), and REPORT (the six-gate
    report artifact carrying the structured endpoint identities) -
    all PASS."""
    import hashlib
    import json

    from ashare_state.providers.amazingdata.capability import FORMAL_GATE_CASE_TYPE
    from ashare_state.providers.amazingdata.endpoint_requirements import (
        endpoint_requirement_case_id,
        endpoint_requirements_for,
    )

    def _gate_case(case_id: str, meta) -> None:
        catalog.add(
            SpikeCase(
                case_id=case_id,
                spike_run_id=run.spike_run_id,
                case_type=FORMAL_GATE_CASE_TYPE,
                security="GATE",
                provider_symbol="GATE",
                trade_date="20260814",
                expected_value="e",
                actual_value="a",
                evidence_type="RAW_JSON",
                evidence_ref=str(meta["evidence_ref"]),
                result=CaseResult.VALIDATED_PASS,
                evidence_hash=str(meta["content_hash"]),
            )
        )

    for suffix in ("PERMISSION", "BUSINESS"):
        case_id = f"GATE-{capability}-{suffix}"
        meta = store.write_evidence(
            run,
            f"req-{case_id}",
            endpoint="ep",
            provider_dataset="ds",
            params={},
            payload={"gate": suffix},
        )
        _gate_case(case_id, meta)

    # R4-B1: one proof case per declared endpoint requirement
    endpoint_entries = []
    for req in endpoint_requirements_for(capability):
        case_id = endpoint_requirement_case_id(req)
        meta = store.write_evidence(
            run,
            f"req-{case_id}",
            endpoint=req.endpoint,
            provider_dataset=req.provider_dataset,
            params={},
            payload={"endpoint_proof": req.requirement_id},
        )
        _gate_case(case_id, meta)
        endpoint_entries.append(
            {
                "requirement_id": req.requirement_id,
                "capability": req.capability,
                "expected_endpoint": req.endpoint,
                "actual_endpoint": req.endpoint,
                "provider_dataset": req.provider_dataset,
                "actual_dataset": req.provider_dataset,
                "mode": req.mode.value,
                "group_id": req.group_id,
                "status": "PASS",
                "reason": "fixture proof",
                "request_id": f"req-{case_id}",
                "evidence_uri": str(meta["evidence_ref"]),
                "evidence_hash": str(meta["content_hash"]),
            }
        )

    report_doc = {
        "capability": capability,
        "run_id": run.spike_run_id,
        "all_passed": True,
        "early_stopped": False,
        "blocked_by": None,
        "gates": [],
        "endpoint_requirements": endpoint_entries,
    }
    gates_dir = store.run_dir(run) / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    report_path = gates_dir / f"{capability}.json"
    report_path.write_text(json.dumps(report_doc, indent=2, sort_keys=True), encoding="utf-8")
    rel = f"{run.run_kind.value.lower()}/{run.spike_run_id}/gates/{capability}.json"
    catalog.add(
        SpikeCase(
            case_id=f"GATE-{capability}-REPORT",
            spike_run_id=run.spike_run_id,
            case_type=FORMAL_GATE_CASE_TYPE,
            security="GATE",
            provider_symbol="GATE",
            trade_date="20260814",
            expected_value="e",
            actual_value="a",
            evidence_type="RAW_JSON",
            evidence_ref=rel,
            result=CaseResult.VALIDATED_PASS,
            evidence_hash=hashlib.sha256(report_path.read_bytes()).hexdigest(),
        )
    )


def _make_closed_production_run(
    spike_root: Path,
    *,
    cases: list[tuple[str, str, CaseResult]],
    gate_proof: bool = True,
):
    """A CLOSED production run with the given (case_id, case_type, result)
    cases; each case gets real evidence. With gate_proof=True the formal
    runtime gate proof cases are attached (R4-A3.1 P0-01 - required for
    approval); pass gate_proof=False to build bypass scenarios."""
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
    if gate_proof:
        _add_formal_gate_proof(store, run, catalog, "daily_bar")
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

    def test_approval_refuses_run_without_formal_gate_proof(self, conn, tmp_path: Path):
        """R4-A3.1 P0-01: a CLOSED, capability-PASSING production run whose
        proof never executed the formal gate boundary cannot approve - the
        boundary is mandatory and cannot be bypassed."""
        cases = _daily_bar_passing_cases()
        run = _make_closed_production_run(tmp_path / "spike", cases=cases, gate_proof=False)
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="formal runtime gate proof"
        ):
            capability_module.approve_from_spike_run(
                conn,
                "daily_bar",
                spike_root=tmp_path / "spike",
                spike_run_id=run.spike_run_id,
                approved_by="designer",
                capability_case_refs=("DB0",),
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
