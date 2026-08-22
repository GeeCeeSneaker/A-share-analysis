"""Capability governance persistence tests (audit P1-03).

Access pattern note: all state flows through `capability_module.X` (never
`from ... import X`) so that importlib.reload() between tests gives a
consistent fresh-process view without stale-boundary pollution.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import duckdb
import pytest

from ashare_state.providers.amazingdata import capability as capability_module
from ashare_state.storage import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

EVIDENCE_KWARGS = {
    "spike_report_ref": "docs/spike_report_p0m1.md",
    "provider_verification_ref": "docs/provider_verification/amazingdata.md",
    "golden_case_refs": ("B2-SECMASTER-0001", "B3-STATUS-0001"),
    "dry_run_ref": "dryrun-2026-09-01",
    "approved_by": "designer",
    "approved_at": "2026-09-01T00:00:00+00:00",
    "account_profile_id": "ACCOUNT_abc123",
}


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


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
            assert cap.status is capability_module.CapabilityStatus.CANDIDATE, name

    def test_approval_requires_full_evidence(self):
        broken = capability_module.CapabilityEvidence("", "pv", ("c",), "dr", "by", "at", "acct")
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="evidence incomplete"
        ):
            capability_module.approve_capability("daily_bar", broken)

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

    def test_persist_and_reload_survives_process_restart(self, conn):
        """The core P1-03 scenario: approval survives a 'process restart'
        (fresh in-memory registry) because the DB is authoritative."""
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        capability_module.approve_capability("daily_bar", evidence)
        capability_module.persist_approval(conn, "daily_bar", evidence)
        # simulate restart: fresh module state
        importlib.reload(capability_module)
        assert (
            capability_module.capability_status("daily_bar")
            is capability_module.CapabilityStatus.CANDIDATE
        )
        # sync from db -> approval restored
        loaded = capability_module.load_approvals(conn)
        assert loaded.get("daily_bar") is capability_module.CapabilityStatus.APPROVED
        assert (
            capability_module.capability_status("daily_bar")
            is capability_module.CapabilityStatus.APPROVED
        )

    def test_persist_writes_evidence_columns(self, conn):
        evidence = capability_module.CapabilityEvidence(**EVIDENCE_KWARGS)
        capability_module.approve_capability("security_master", evidence)
        capability_module.persist_approval(conn, "security_master", evidence)
        row = conn.execute(
            "SELECT status, spike_report_ref, golden_case_refs, approved_by, "
            "account_profile_id FROM meta_provider_capability "
            "WHERE provider='amazingdata' AND capability='security_master'"
        ).fetchone()
        assert row[0] == "APPROVED"
        assert row[1] == evidence.spike_report_ref
        assert "B2-SECMASTER-0001" in row[2]
        assert row[3] == "designer"
        assert row[4] == evidence.account_profile_id

    def test_unknown_db_status_fails_safe_to_candidate(self, conn):
        conn.execute(
            "INSERT INTO meta_provider_capability (provider, capability, status) "
            "VALUES ('amazingdata', 'daily_bar', 'WEIRD_STATUS')"
        )
        loaded = capability_module.load_approvals(conn)
        assert loaded.get("daily_bar") is capability_module.CapabilityStatus.CANDIDATE
        assert (
            capability_module.capability_status("daily_bar")
            is capability_module.CapabilityStatus.CANDIDATE
        )
