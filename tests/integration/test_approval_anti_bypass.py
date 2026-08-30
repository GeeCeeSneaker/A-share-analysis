"""Approval Anti-Bypass + Persisted Identity Cross-Binding tests
(R4-B1.1 P0-02/P0-03 + R4-B1.2 P0-01, audits 20260830).

R4-B1.2 P0-01 (Option A): the production module contains NO callable
that writes APPROVED without the formal-run verification chain - the
persistence transaction lives INSIDE ``approve_from_spike_run``:

    approve_from_spike_run
      -> closed production run + provenance + frozen identity
      -> verdict + formal gate proof + four-layer cross-binding
      -> (inline) single DB transaction + cache rebuild

The R4-B1.1-era "verified object" (``VerifiedCapabilityApproval``) and
the src test-only helpers are GONE from src/ - Python's ``_name`` is a
naming convention, not access control. Test-side approval mechanics
live in ``tests/integration/_capability_test_persistence.py``.

The bypass tests below make REAL bypass attempts (construct fabricated
objects, call whatever remains importable) and assert the DB never
reaches APPROVED - not just that names disappeared.

P0-03 cross-binding tamper tests: contract <-> REPORT entry <->
proof case <-> persisted Raw meta - every tamper fails CLOSED,
including attacks that re-bind the REPORT case hash after tampering.
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
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunKind, SpikeCase
from ashare_state.spike.runner import new_run

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


def _make_frozen_identity(profile):
    from ashare_state.providers.amazingdata import production_identity as pi

    return pi.FrozenProductionIdentity(
        account_profile_id=profile.account_profile_id,
        confirmed_at="2026-08-30T00:00:00+00:00",
        confirmed_by="r4-b1.1-test",
    )


def _catalog_path(store, run) -> Path:
    return store.run_dir(run) / "cases" / "spike_case_catalog.jsonl"


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


def _make_closed_production_run(tmp_path: Path, monkeypatch, *, capability: str = "daily_bar"):
    """A CLOSED production run with the full formal gate proof chain
    (per-requirement endpoint cases + REPORT artifact)."""
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
    """R4-B1.2 P0-01 (Option A): REAL bypass attempts - the caller tries
    every remaining importable route to APPROVED and the DB never gets
    there without the formal-run verification chain."""

    def _db_status(self, conn, name: str):
        row = conn.execute(
            "SELECT status FROM meta_provider_capability "
            f"WHERE provider = 'amazingdata' AND capability = '{name}'"
        ).fetchone()
        return row[0] if row else None

    def test_src_approval_bypass_callables_are_gone(self):
        """The R4-B1.1-era src test-only helpers, the 'verified' proof
        object, and the old public names no longer exist - there is
        nothing left to import for a caller-built evidence bypass."""
        for attr in (
            "approve_and_persist_capability",
            "approve_capability",
            "_approve_and_persist_capability_testonly",
            "_approve_capability_in_memory_testonly",
            "_persist_verified_capability",
            "VerifiedCapabilityApproval",
        ):
            assert not hasattr(capability_module, attr), attr

    def test_fabricated_verified_object_cannot_be_constructed(self, conn):
        """The attacker tries to construct the R4-B1.1 'verified'
        dataclass with fake nonempty fields - the class no longer
        exists in the production module, so the object (and the proof
        it would carry) cannot be fabricated at all."""
        with pytest.raises(AttributeError):
            capability_module.VerifiedCapabilityApproval(
                name="daily_bar",
                evidence=None,
                verified_from_run="fake-run",
                endpoint_requirements_proven=("fake-proof",),
            )
        assert self._db_status(conn, "daily_bar") is None

    def test_only_approve_from_spike_run_writes_approved(self):
        """Structural guard (AST): in the production module the ONLY
        function whose body (excluding its docstring) references the
        APPROVED status - as a literal, an SQL string, or a
        CapabilityStatus attribute - is ``approve_from_spike_run``,
        whose signature takes (conn, name, spike_root, spike_run_id,
        ...), NEVER a CapabilityEvidence or a caller-constructible
        'verified' object. ``load_approvals`` mirrors the DB into the
        cache and cannot mint a new APPROVED."""

        def _body_without_docstring(fn: ast.FunctionDef) -> list[ast.stmt]:
            body = list(fn.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                return body[1:]
            return body

        tree = ast.parse(CAPABILITY_SOURCE.read_text(encoding="utf-8"))
        writers: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for stmt in _body_without_docstring(node):
                for sub in ast.walk(stmt):
                    writes_approved = (
                        isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and "APPROVED" in sub.value
                    ) or (
                        isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "CapabilityStatus"
                        and sub.attr == "APPROVED"
                    )
                    if writes_approved:
                        writers.add(node.name)
        assert writers == {"approve_from_spike_run"}, (
            f"APPROVED reachable from unexpected functions: {sorted(writers)}"
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "approve_from_spike_run"
        )
        arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        assert "evidence" not in arg_names
        assert not any("verified" in a for a in arg_names)

    def test_caller_built_evidence_with_frozen_id_still_cannot_approve(
        self, conn, tmp_path, monkeypatch
    ):
        """Even WITH a legitimately frozen production identity patched
        in, a caller-built CapabilityEvidence has no importable route
        to an APPROVED row: every former approval-shaped callable is
        gone from the production module."""
        from ashare_state.providers.amazingdata.capability import CapabilityEvidence
        from ashare_state.providers.amazingdata.session import AccountProfile

        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            host="h",
            username="u",
        )
        from ashare_state.providers.amazingdata import production_identity as pi

        frozen = _make_frozen_identity(profile)
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)
        # a caller-built evidence bundle with the FROZEN account id -
        # the strongest fabricated input an attacker can assemble
        CapabilityEvidence(
            spike_report_ref="fabricated",
            provider_verification_ref="fabricated",
            golden_case_refs=("fabricated",),
            dry_run_ref="fabricated",
            approved_by="attacker",
            approved_at="2026-08-30T00:00:00",
            account_profile_id=profile.account_profile_id,  # the FROZEN id
        )
        # attempt every approval-shaped call that used to exist
        for attr in (
            "approve_and_persist_capability",
            "approve_capability",
            "_approve_and_persist_capability_testonly",
            "_approve_capability_in_memory_testonly",
            "_persist_verified_capability",
        ):
            assert not hasattr(capability_module, attr), (
                f"{attr} still exists - a caller-built evidence bypass route"
            )
        assert self._db_status(conn, "daily_bar") is None

    def test_failed_endpoint_requirement_has_no_bypass(self, conn, tmp_path, monkeypatch):
        """A run whose REQUIRED endpoint failed cannot be approved by
        ANY path - and after the refusal the DB and the in-memory cache
        stay consistent (CANDIDATE, not APPROVED)."""
        run, store, _, _ = _make_closed_production_run(
            tmp_path, monkeypatch, capability="security_master"
        )
        req = endpoint_requirements_for("security_master")[0]
        report_path = store.run_dir(run) / "gates" / "security_master.json"
        _mutate_report_entry(report_path, req.requirement_id, status="FAIL")
        _rebind_report_case_hash(store, run, "security_master", report_path)
        with pytest.raises(capability_module.CapabilityGovernanceError):
            _approve(conn, tmp_path, run, capability="security_master")
        statuses = capability_module.load_approvals(conn)
        assert statuses.get("security_master") is not capability_module.CapabilityStatus.APPROVED
        assert self._db_status(conn, "security_master") != "APPROVED"

    def test_only_the_formal_run_path_persists_approved(self, conn, tmp_path, monkeypatch):
        """The happy chain: a closed production run with the FULL
        cross-bound proof approves via approve_from_spike_run - the one
        and only reachable APPROVED transition."""
        run, store, report_path, _ = _make_closed_production_run(tmp_path, monkeypatch)
        approved = _approve(conn, tmp_path, run)
        assert approved.status is capability_module.CapabilityStatus.APPROVED
        row = conn.execute(
            "SELECT spike_report_ref FROM meta_provider_capability "
            "WHERE provider = 'amazingdata' AND capability = 'daily_bar'"
        ).fetchone()
        assert row[0] == f"spike-run:{run.spike_run_id}"

    def test_production_src_never_imports_test_modules(self):
        """The test-side approval mechanics live in tests/ - production
        src must not import any test module (AST scan of every src
        file's import statements)."""
        src_root = REPO_ROOT / "src"
        for path in src_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: set[str] = set()
                if isinstance(node, ast.Import):
                    names.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module)
                for name in names:
                    assert "tests" not in name.split("."), (
                        f"production code imports a test module: {path} -> {name}"
                    )


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
