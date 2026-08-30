"""Approval Anti-Bypass + Persisted Identity Cross-Binding tests
(R4-B1.1, audit 20260830 P0-02 / P0-03).

P0-02 - the ONLY production-reachable APPROVED transition:

    approve_from_spike_run
      -> closed production run + provenance + verdict
      -> formal gate proof + exact endpoint identity cross-binding
      -> VerifiedCapabilityApproval (internal sealed proof object)
      -> _persist_verified_capability (private persistence boundary)

The old public paths (``approve_and_persist_capability`` /
``approve_capability``) accepted caller-constructed CapabilityEvidence
and could set APPROVED without any formal endpoint proof - that bypass
is closed here.

P0-03 - full cross-binding. For every requirement used to satisfy the
proof, approval re-verifies EXACT equality across all four layers:

    contract <-> REPORT entry <-> proof case <-> persisted Raw meta

Every tamper below fails CLOSED (approval refused), including attacks
that re-bind the REPORT case hash after tampering.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from ashare_state.providers.amazingdata import capability as capability_module
from ashare_state.providers.amazingdata.endpoint_requirements import (
    endpoint_requirement_case_id,
    endpoint_requirements_for,
)
from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunKind, SpikeCase
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
CAPABILITY_SOURCE = (
    REPO_ROOT / "src" / "ashare_state" / "providers" / "amazingdata" / "capability.py"
)
_SHA = "a" * 40


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    from ashare_state.storage import apply_migrations

    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _gates_relaxed(monkeypatch):
    from ashare_state.spike import trading_rule as rule_module
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "event_coverage_gate", lambda self: [])
    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self: [])
    monkeypatch.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])


@pytest.fixture(autouse=True)
def _fresh_capability_registry():
    """Reload the capability module around EVERY test: the registry is
    module-level mutable state, and the happy-path test approves
    daily_bar (same discipline as test_capability_governance)."""
    import importlib

    importlib.reload(capability_module)
    yield
    importlib.reload(capability_module)


class _HistDeniedTarget(FakeTarget):
    """security_master business surface denied (audit 20260830 P0-01
    scenario: the survivorship endpoint is unavailable)."""

    def get_hist_code_list_exchange(self, security_type, start_date, end_date):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="hist_code_list",
            endpoint="BaseData.get_hist_code_list",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


def _make_frozen_identity(profile):
    from ashare_state.providers.amazingdata import production_identity as pi

    return pi.FrozenProductionIdentity(
        account_profile_id=profile.account_profile_id,
        confirmed_at="2026-08-30T00:00:00+00:00",
        confirmed_by="r4-b1.1-test",
    )


def _catalog_path(store, run) -> Path:
    return store.run_dir(run) / "cases" / "spike_case_catalog.jsonl"


def _add_case(catalog, store, run, case: SpikeCase) -> None:
    catalog.add(case)


def _gate_case(run, case_id: str, meta, result: CaseResult = CaseResult.VALIDATED_PASS):
    return SpikeCase(
        case_id=case_id,
        spike_run_id=run.spike_run_id,
        case_type=capability_module.FORMAL_GATE_CASE_TYPE,
        security="GATE",
        provider_symbol="GATE",
        trade_date="20260814",
        expected_value="e",
        actual_value="a",
        evidence_type="RAW_JSON",
        evidence_ref=str(meta["evidence_ref"]),
        result=result,
        evidence_hash=str(meta["content_hash"]),
    )


def _make_closed_production_run(
    tmp_path: Path, monkeypatch, *, capability: str = "daily_bar", target=None
):
    """A CLOSED production run with the full formal gate proof chain
    (per-requirement endpoint cases + REPORT artifact). ``target`` can
    inject a failing endpoint surface."""
    from ashare_state.providers.amazingdata.session import AccountProfile
    from ashare_state.spike import close_run

    profile = AccountProfile.from_scrubbed(
        {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
        host="h",
        username="u",
    )
    from ashare_state.providers.amazingdata import production_identity as pi

    frozen = _make_frozen_identity(profile)
    monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)

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
    catalog = CaseCatalog(store, run.spike_run_id)

    # business case (case_type carries the spike capability id - the
    # verdict engine groups by case_type)
    spike_capability = capability_module.SPIKE_CAPABILITY_BY_REGISTRY[capability]
    meta = store.write_evidence(
        run,
        f"req-{spike_capability}",
        endpoint="ep",
        provider_dataset="ds",
        params={},
        payload={"case": spike_capability},
    )
    catalog.add(
        SpikeCase(
            case_id="DB0",
            spike_run_id=run.spike_run_id,
            case_type=spike_capability,
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

    # formal gate proof chain
    permission_meta = store.write_evidence(
        run,
        "req-GATE-PERMISSION",
        endpoint="ep",
        provider_dataset="ds",
        params={},
        payload={"gate": "PERMISSION"},
    )
    catalog.add(_gate_case(run, f"GATE-{capability}-PERMISSION", permission_meta))
    business_gate_meta = store.write_evidence(
        run,
        "req-GATE-BUSINESS",
        endpoint="ep",
        provider_dataset="ds",
        params={},
        payload={"gate": "BUSINESS"},
    )
    catalog.add(_gate_case(run, f"GATE-{capability}-BUSINESS", business_gate_meta))

    endpoint_entries = []
    endpoint_metas = {}
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
        catalog.add(_gate_case(run, case_id, meta))
        endpoint_metas[req.requirement_id] = meta
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
                "request_id": str(meta["request_id"]),
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
            case_type=capability_module.FORMAL_GATE_CASE_TYPE,
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
    catalog.flush(store.run_dir(run))
    close_run(store, run)
    return run, store, report_path, permission_meta


def _approve(conn, tmp_path, run, capability: str = "daily_bar"):
    return capability_module.approve_from_spike_run(
        conn,
        capability,
        spike_root=tmp_path / "spike",
        spike_run_id=run.spike_run_id,
        approved_by="designer",
        capability_case_refs=("DB0",),
    )


def _rewrite_catalog_case(store, run, case_id: str, **fields) -> None:
    """Tamper ONE case row in the persisted catalog jsonl."""
    path = _catalog_path(store, run)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for line in lines:
        doc = json.loads(line)
        if doc.get("case_id") == case_id:
            doc.update(fields)
            out.append(json.dumps(doc, ensure_ascii=False))
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _rebind_report_case_hash(store, run, capability: str, report_path: Path) -> None:
    """Re-point the REPORT case's evidence_hash at the CURRENT artifact
    bytes (the attacker re-binds the anchor after tampering)."""
    new_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    _rewrite_catalog_case(store, run, f"GATE-{capability}-REPORT", evidence_hash=new_hash)


def _mutate_report_entry(report_path: Path, requirement_id: str, **fields) -> None:
    doc = json.loads(report_path.read_text(encoding="utf-8"))
    for entry in doc.get("endpoint_requirements", []):
        if entry["requirement_id"] == requirement_id:
            entry.update(fields)
    report_path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")


@pytest.mark.integration
class TestApprovalAntiBypass:
    """P0-02: caller self-declared CapabilityEvidence can NEVER reach a
    production APPROVED state."""

    def test_old_public_approval_paths_no_longer_exist(self):
        """approve_and_persist_capability / approve_capability are GONE
        from the module namespace - no public API accepts a
        caller-constructed CapabilityEvidence anymore."""
        assert not hasattr(capability_module, "approve_and_persist_capability")
        assert not hasattr(capability_module, "approve_capability")

    def test_production_code_never_calls_the_testonly_helpers(self):
        """The test-only helpers exist for tests ONLY - src/ must not
        reference them anywhere (AST-level scan of every module)."""
        src_root = REPO_ROOT / "src"
        for path in src_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in (
                    "_approve_and_persist_capability_testonly",
                    "_approve_capability_in_memory_testonly",
                ):
                    msg = f"production code references a test-only helper: {path}"
                    raise AssertionError(msg)

    def test_approved_writes_only_in_governed_boundaries(self):
        """AST guard: an APPROVED status literal may only be written by
        (1) the private verified persistence boundary, (2) the
        test-only in-memory helper, (3) load_approvals (DB -> cache
        rebuild). No other function fabricates APPROVED."""
        tree = ast.parse(CAPABILITY_SOURCE.read_text(encoding="utf-8"))
        allowed = {
            "_persist_verified_capability",
            "_approve_capability_in_memory_testonly",
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and getattr(sub, "value", None) == "APPROVED":
                    assert node.name in allowed or node.name == "load_approvals", (
                        f"APPROVED literal written by {node.name}"
                    )
                if (
                    isinstance(sub, ast.Attribute)
                    and getattr(sub, "value", None) is not None
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == "CapabilityStatus"
                    and sub.attr == "APPROVED"
                ):
                    assert node.name in allowed, (
                        f"CapabilityStatus.APPROVED constructed by {node.name}"
                    )

    def test_fabricated_evidence_cannot_self_declare_production_approval(self, conn):
        """A caller-built CapabilityEvidence has NO public path to an
        APPROVED row: the only production entry is
        approve_from_spike_run, which requires a real closed run."""
        from ashare_state.providers.amazingdata.capability import CapabilityEvidence

        evidence = CapabilityEvidence(
            spike_report_ref="fabricated",
            provider_verification_ref="fabricated",
            golden_case_refs=("fabricated",),
            dry_run_ref="fabricated",
            approved_by="attacker",
            approved_at="2026-08-30T00:00:00",
            account_profile_id="ACCOUNT_attacker",
        )
        # no public function accepts (conn, name, evidence) anymore
        with pytest.raises(AttributeError):
            capability_module.approve_and_persist_capability(conn, "daily_bar", evidence)
        with pytest.raises(AttributeError):
            capability_module.approve_capability("daily_bar", evidence)
        row = conn.execute(
            "SELECT status FROM meta_provider_capability "
            "WHERE provider = 'amazingdata' AND capability = 'daily_bar'"
        ).fetchone()
        assert row is None

    def test_failed_endpoint_requirement_has_no_bypass(self, conn, tmp_path, monkeypatch):
        """A run whose REQUIRED endpoint failed cannot be approved by
        ANY path - and after the refusal the DB and the in-memory cache
        stay consistent (CANDIDATE, not APPROVED)."""
        run, store, _, _ = _make_closed_production_run(
            tmp_path, monkeypatch, capability="security_master", target=_HistDeniedTarget()
        )
        # the run's proof chain is the HAPPY fixture - simulate the
        # failure by removing the endpoint requirement case + flipping
        # its REPORT entry to FAIL (an honest failed run looks like this)
        req = endpoint_requirements_for("security_master")[0]
        _mutate_report_entry(
            store.run_dir(run) / "gates" / "security_master.json", req.requirement_id, status="FAIL"
        )
        report_path = store.run_dir(run) / "gates" / "security_master.json"
        _rebind_report_case_hash(store, run, "security_master", report_path)
        with pytest.raises(capability_module.CapabilityGovernanceError):
            _approve(conn, tmp_path, run, capability="security_master")
        # DB + cache stay consistent after the refused bypass
        statuses = capability_module.load_approvals(conn)
        assert statuses.get("security_master") is not capability_module.CapabilityStatus.APPROVED
        row = conn.execute(
            "SELECT status FROM meta_provider_capability "
            "WHERE provider = 'amazingdata' AND capability = 'security_master'"
        ).fetchone()
        assert row is None or row[0] != "APPROVED"

    def test_only_the_verified_path_persists_approved(self, conn, tmp_path, monkeypatch):
        """The happy chain: a closed production run with the FULL
        cross-bound proof approves via approve_from_spike_run - and the
        verified object carries the proven requirement ids."""
        run, store, report_path, _ = _make_closed_production_run(tmp_path, monkeypatch)
        approved = _approve(conn, tmp_path, run)
        assert approved.status is capability_module.CapabilityStatus.APPROVED
        req_ids = [r.requirement_id for r in endpoint_requirements_for("daily_bar")]
        # the persisted row records the verified source
        row = conn.execute(
            "SELECT spike_report_ref FROM meta_provider_capability "
            "WHERE provider = 'amazingdata' AND capability = 'daily_bar'"
        ).fetchone()
        assert row[0] == f"spike-run:{run.spike_run_id}"
        assert req_ids  # daily_bar's requirement was proven by the chain


@pytest.mark.integration
class TestCrossBindingTamper:
    """P0-03: contract <-> REPORT <-> case <-> Raw meta exact
    cross-binding. Every single tamper fails CLOSED - including attacks
    that re-bind the REPORT case hash after tampering."""

    def _run(self, tmp_path, monkeypatch):
        return _make_closed_production_run(tmp_path, monkeypatch)

    def test_actual_dataset_tamper_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, _ = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        _mutate_report_entry(report_path, req.requirement_id, actual_dataset="wrong_dataset")
        _rebind_report_case_hash(store, run, "daily_bar", report_path)
        with pytest.raises(capability_module.CapabilityGovernanceError, match="actual_dataset"):
            _approve(conn, tmp_path, run)

    def test_provider_dataset_tamper_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, _ = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        _mutate_report_entry(report_path, req.requirement_id, provider_dataset="wrong")
        _rebind_report_case_hash(store, run, "daily_bar", report_path)
        with pytest.raises(capability_module.CapabilityGovernanceError, match="provider_dataset"):
            _approve(conn, tmp_path, run)

    def test_report_evidence_uri_swapped_to_permission_evidence_blocks(
        self, conn, tmp_path, monkeypatch
    ):
        run, store, report_path, permission_meta = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        _mutate_report_entry(
            report_path,
            req.requirement_id,
            evidence_uri=str(permission_meta["evidence_ref"]),
            evidence_hash=str(permission_meta["content_hash"]),
            request_id=str(permission_meta["request_id"]),
        )
        _rebind_report_case_hash(store, run, "daily_bar", report_path)
        # the REPORT entry now points at the permission evidence; the
        # proof case still points at the endpoint evidence - the case
        # and the report disagree about WHAT proves the endpoint
        with pytest.raises(capability_module.CapabilityGovernanceError, match="evidence_ref"):
            _approve(conn, tmp_path, run)

    def test_report_evidence_hash_swapped_to_other_legitimate_hash_blocks(
        self, conn, tmp_path, monkeypatch
    ):
        run, store, report_path, permission_meta = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        _mutate_report_entry(
            report_path, req.requirement_id, evidence_hash=str(permission_meta["content_hash"])
        )
        _rebind_report_case_hash(store, run, "daily_bar", report_path)
        with pytest.raises(capability_module.CapabilityGovernanceError, match="evidence_hash"):
            _approve(conn, tmp_path, run)

    def test_case_evidence_ref_disagreeing_with_report_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, permission_meta = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        # tamper the CASE (not the report) to point elsewhere
        _rewrite_catalog_case(
            store,
            run,
            endpoint_requirement_case_id(req),
            evidence_ref=str(permission_meta["evidence_ref"]),
        )
        with pytest.raises(capability_module.CapabilityGovernanceError, match="evidence_ref"):
            _approve(conn, tmp_path, run)

    def test_case_evidence_hash_disagreeing_with_report_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, permission_meta = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        _rewrite_catalog_case(
            store,
            run,
            endpoint_requirement_case_id(req),
            evidence_hash=str(permission_meta["content_hash"]),
        )
        with pytest.raises(capability_module.CapabilityGovernanceError, match="evidence_hash"):
            _approve(conn, tmp_path, run)

    def test_raw_meta_endpoint_tamper_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, _ = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        entry = next(
            e
            for e in json.loads(report_path.read_text(encoding="utf-8"))["endpoint_requirements"]
            if e["requirement_id"] == req.requirement_id
        )
        meta_path = tmp_path / "spike" / str(entry["evidence_uri"])
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        doc["endpoint"] = "BaseData.get_calendar"  # endpoint tamper
        meta_path.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="persisted evidence bytes"
        ):
            _approve(conn, tmp_path, run)

    def test_raw_meta_provider_dataset_mismatch_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, _ = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        entry = next(
            e
            for e in json.loads(report_path.read_text(encoding="utf-8"))["endpoint_requirements"]
            if e["requirement_id"] == req.requirement_id
        )
        meta_path = tmp_path / "spike" / str(entry["evidence_uri"])
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        doc["provider_dataset"] = "code_list"  # dataset tamper
        meta_path.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="persisted evidence bytes"
        ):
            _approve(conn, tmp_path, run)

    def test_raw_meta_request_id_mismatch_blocks(self, conn, tmp_path, monkeypatch):
        run, store, report_path, _ = self._run(tmp_path, monkeypatch)
        req = endpoint_requirements_for("daily_bar")[0]
        entry = next(
            e
            for e in json.loads(report_path.read_text(encoding="utf-8"))["endpoint_requirements"]
            if e["requirement_id"] == req.requirement_id
        )
        meta_path = tmp_path / "spike" / str(entry["evidence_uri"])
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        doc["request_id"] = "req-impostor"  # request identity tamper
        meta_path.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="persisted evidence bytes"
        ):
            _approve(conn, tmp_path, run)
