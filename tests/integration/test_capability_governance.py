"""Capability governance persistence tests (audit P1-03 + R2-P1-01, section 33).

Access pattern note: all state flows through `capability_module.X` (never
`from ... import X`) so importlib.reload() between tests gives a consistent
fresh-process view without stale-boundary pollution.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import duckdb
import pytest

from ashare_state.providers.amazingdata import capability as capability_module
from ashare_state.storage import apply_migrations


@pytest.fixture(autouse=True)
def _event_gate_relaxed(monkeypatch):
    """R4-A1.1: PRODUCTION runs now require the reviewed golden dataset
    (distinct-event coverage). These tests exercise OTHER gates, so the
    event/review gates are relaxed here; dedicated tests live in
    test_golden_truth_gates.py."""
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "event_coverage_gate", lambda self: [])
    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self: [])


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

EVIDENCE_KWARGS = {
    "spike_report_ref": "docs/spike_report_p0m1.md",
    "provider_verification_ref": "docs/provider_verification/amazingdata.md",
    "golden_case_refs": ("B2-SECMASTER-0001", "B3-STATUS-0001"),
    "dry_run_ref": "dryrun-2026-09-01",
    "approved_by": "designer",
    "approved_at": "2026-09-01T00:00:00+00:00",
    # R4-A3.1 P0-03: approval requires a POSITIVE frozen identity - the
    # scrubbed profile id frozen below (an arbitrary ACCOUNT_* string is
    # no longer enough)
    "account_profile_id": "ACCOUNT_frozenprod01",
}


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _frozen_production_identity(monkeypatch):
    """R4-A3.1 P0-03: freeze the positive production identity matching
    EVIDENCE_KWARGS - approval tests exercise the exact-match allowlist
    path (the repo default stays fail closed)."""
    from ashare_state.providers.amazingdata import production_identity as pi

    frozen = pi.FrozenProductionIdentity(
        account_profile_id=EVIDENCE_KWARGS["account_profile_id"],
        confirmed_at="2026-08-27T00:00:00+00:00",
        confirmed_by="r4-a3.1-test",
    )
    monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Fresh-process registry view per test (audit P1-03 restart semantics)."""
    importlib.reload(capability_module)
    yield
    importlib.reload(capability_module)


@pytest.mark.integration
class TestCapabilityGovernance:
    def test_all_start_candidate(self):
        for name, cap in capability_module.CAPABILITY_REGISTRY.items():
            assert cap.status == capability_module.CapabilityStatus.CANDIDATE, name

    def test_approval_requires_full_evidence(self):
        broken = capability_module.CapabilityEvidence("", "pv", ("c",), "dr", "by", "at", "acct")
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="evidence incomplete"
        ):
            capability_module.approve_and_persist_capability(
                duckdb.connect(":memory:"), "daily_bar", broken
            )

    def test_retired_refuses_approval(self):
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        registry = capability_module.CAPABILITY_REGISTRY
        registry["daily_bar"] = registry["daily_bar"].__class__(
            name="daily_bar",
            sdk_methods=registry["daily_bar"].sdk_methods,
            canonical_domains=registry["daily_bar"].canonical_domains,
            status=capability_module.CapabilityStatus.RETIRED,
        )
        with pytest.raises(capability_module.CapabilityGovernanceError, match="RETIRED"):
            capability_module.approve_capability("daily_bar", evidence)

    def test_persist_cannot_bypass_evidence(self, conn):
        """R2-P1-01 12.1: the only public path validates evidence first -
        broken evidence never reaches the DB."""
        broken = capability_module.CapabilityEvidence("spike", "pv", ("c",), "dr", "by", "at", "")
        with pytest.raises(capability_module.CapabilityGovernanceError):
            capability_module.approve_and_persist_capability(conn, "daily_bar", broken)
        row = conn.execute(
            "SELECT count(*) FROM meta_provider_capability WHERE capability='daily_bar'"
        ).fetchone()
        assert row[0] == 0

    def test_approval_survives_process_restart(self, conn):
        """The core P1-03 scenario: DB authoritative across restarts."""
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        capability_module.approve_and_persist_capability(conn, "daily_bar", evidence)
        # simulate restart: fresh module state
        importlib.reload(capability_module)
        assert (
            capability_module.capability_status("daily_bar")
            == capability_module.CapabilityStatus.CANDIDATE
        )
        loaded = capability_module.load_approvals(conn)
        assert loaded.get("daily_bar") == capability_module.CapabilityStatus.APPROVED
        assert (
            capability_module.capability_status("daily_bar")
            == capability_module.CapabilityStatus.APPROVED
        )

    def test_approval_preserves_existing_metadata(self, conn):
        """R2-P1-01 12.3: an UPDATE path must not erase existing columns."""
        conn.execute(
            "INSERT INTO meta_provider_capability "
            "(provider, capability, status, asset_class, frequency, transport, "
            "permission_note) VALUES ('amazingdata', 'daily_bar', 'CANDIDATE', "
            "'EQUITY', 'DAILY', 'SDK', 'galaxy trial')"
        )
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        capability_module.approve_and_persist_capability(conn, "daily_bar", evidence)
        row = conn.execute(
            "SELECT asset_class, frequency, transport, permission_note, status "
            "FROM meta_provider_capability WHERE capability='daily_bar'"
        ).fetchone()
        assert row[0] == "EQUITY"
        assert row[1] == "DAILY"
        assert row[2] == "SDK"
        assert row[3] == "galaxy trial"
        assert row[4] == "APPROVED"

    def test_db_candidate_demotes_cached_approved(self, conn):
        """R2-P1-01 12.4: DB CANDIDATE actively overrides a stale cache."""
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        capability_module.approve_and_persist_capability(conn, "daily_bar", evidence)
        assert (
            capability_module.capability_status("daily_bar")
            == capability_module.CapabilityStatus.APPROVED
        )
        # DB is rolled back to CANDIDATE out-of-band (e.g. governance reversal)
        conn.execute(
            "UPDATE meta_provider_capability SET status='CANDIDATE' WHERE capability='daily_bar'"
        )
        capability_module.load_approvals(conn)
        assert (
            capability_module.capability_status("daily_bar")
            == capability_module.CapabilityStatus.CANDIDATE
        )

    def test_load_restores_account_profile_and_verified_at(self, conn):
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        capability_module.approve_and_persist_capability(conn, "daily_bar", evidence)
        importlib.reload(capability_module)
        capability_module.load_approvals(conn)
        cap = capability_module.CAPABILITY_REGISTRY["daily_bar"]
        assert cap.account_profile_id == EVIDENCE_KWARGS["account_profile_id"]
        # DuckDB normalizes the timestamptz to the session zone; compare dates
        assert cap.verified_at and cap.verified_at.startswith("2026-09-01")

    def test_unknown_db_status_fails_safe_to_candidate(self, conn):
        conn.execute(
            "INSERT INTO meta_provider_capability (provider, capability, status) "
            "VALUES ('amazingdata', 'daily_bar', 'WEIRD_STATUS')"
        )
        loaded = capability_module.load_approvals(conn)
        assert loaded.get("daily_bar") == capability_module.CapabilityStatus.CANDIDATE
        assert (
            capability_module.capability_status("daily_bar")
            == capability_module.CapabilityStatus.CANDIDATE
        )
