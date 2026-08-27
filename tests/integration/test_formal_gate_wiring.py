"""Formal runtime gate wiring tests (R4-A3.1 P0-01/P0-02, audit 20260827).

The audit finding: R4-A3 delivered the gate LIBRARY, but the formal
Spike/Provider execution path never consumed it - a component test
proves the library, not the formal path. These tests pin the wired
contract:

- the formal boundary (FormalRuntimeGateExecutor) executes the frozen
  RuntimeGatePipeline for every registered capability (probe_b1);
- every probe gate exchange - success AND failure - is persisted through
  the run's RawWriter and the gate result binds the persisted evidence
  identity (request_id + evidence_uri + evidence_hash - never a
  request_id alone);
- a blocking permission gate stops the chain: ZERO downstream provider
  calls and ZERO raw evidence;
- capability approval refuses runs without the gate proof (anti-bypass)
  and the approval source statically contains the check;
- persistence failure downgrades a passing probe to FAIL (fail closed).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.providers.runtime_gates import GateKind, GateStatus
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.formal_gates import (
    FORMAL_GATE_PROBE_KINDS,
    GATE_PLAN_SPECS,
    FormalRuntimeGateExecutor,
    gate_case_id,
    gate_report_case_id,
    probe_b1_formal_gates,
)
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget

_SHA = "a" * 40
REPO_ROOT = Path(__file__).resolve().parents[2]


class _CodeListDeniedTarget(FakeTarget):
    """The permission probe FAILS with a first-class error exchange."""

    def get_code_list_exchange(self, security_type=None):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="code_list",
            endpoint="BaseData.get_code_list",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


class _NoPersistContext(ProbeContext):
    """Persistence broken: the RawWriter fails for every exchange - a
    passing probe must NOT count as formal evidence PASS."""

    def evidence_from_exchange(self, exchange):
        raise RuntimeError("simulated persistence failure")


def _ctx(tmp_path: Path, target=None, context_cls=ProbeContext) -> ProbeContext:
    run, store = new_run(
        run_kind=RunKind.DRY_RUN,
        spike_root=tmp_path / "spike",
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TRIAL_SIMULATION_FAKE",
        as_of_date="20260814",
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    return context_cls(run, store, catalog, target or FakeTarget())


def _raw_files(ctx: ProbeContext) -> list[Path]:
    return sorted(ctx.store.raw_dir(ctx.run).rglob("*.meta.json"))


def _case_by_id(ctx: ProbeContext, case_id: str):
    for case in ctx.catalog.cases:
        if case.case_id == case_id:
            return case
    return None


@pytest.mark.integration
class TestFormalGateWiring:
    def test_every_registered_capability_has_a_gate_plan(self):
        from ashare_state.providers.amazingdata.capability import CAPABILITY_REGISTRY

        assert set(GATE_PLAN_SPECS) == set(CAPABILITY_REGISTRY)

    def test_all_gates_pass_business_fires_and_evidence_binds(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        assert bound.report.all_passed
        assert not bound.report.early_stopped
        # all six gates evaluated in order
        kinds = [r.kind for r in bound.report.results]
        assert kinds == [
            GateKind.AUTH_ACCOUNT,
            GateKind.PERMISSION,
            GateKind.ENDPOINT_AVAILABLE,
            GateKind.CACHE_METADATA,
            GateKind.FRESHNESS_ASOF,
            GateKind.BUSINESS_DATA,
        ]
        # every probe gate bound a persisted evidence identity
        for kind in FORMAL_GATE_PROBE_KINDS:
            binding = bound.bindings[kind]
            assert binding.request_id, kind
            assert binding.evidence_uri.endswith(".meta.json"), kind
            assert len(binding.evidence_hash) == 64, kind
            gate_result = next(r for r in bound.report.results if r.kind is kind)
            assert gate_result.status is GateStatus.PASS
            assert gate_result.request_id == binding.request_id
            assert gate_result.evidence_uri == binding.evidence_uri
            assert gate_result.evidence_hash == binding.evidence_hash
            assert gate_result.has_persisted_evidence
        # the bound URI is a REAL persisted file whose hash matches
        meta_path = ctx.store.spike_root / bound.bindings[GateKind.BUSINESS_DATA].evidence_uri
        assert meta_path.is_file()
        import hashlib

        assert (
            hashlib.sha256(meta_path.read_bytes()).hexdigest()
            == bound.bindings[GateKind.BUSINESS_DATA].evidence_hash
        )

    def test_permission_failure_blocks_with_zero_downstream_calls(self, tmp_path: Path):
        ctx = _ctx(tmp_path, target=_CodeListDeniedTarget())
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        assert not bound.report.all_passed
        assert bound.report.early_stopped
        assert bound.report.blocked_by is GateKind.PERMISSION
        # the permission gate FAILED but its failure exchange IS persisted
        # and bound (P0-02: failure evidence is still evidence)
        permission_result = next(r for r in bound.report.results if r.kind is GateKind.PERMISSION)
        assert permission_result.status is GateStatus.FAIL
        assert permission_result.has_persisted_evidence
        # downstream gates were skipped: ZERO provider calls, ZERO raw
        # evidence beyond the permission failure exchange itself
        probes_fired = sum(p.fired for k, p in bound.probes.items() if k is not GateKind.PERMISSION)
        assert probes_fired == 0
        # exactly one persisted evidence exists: the permission failure
        assert len(_raw_files(ctx)) == 1
        # business/endpoint gate cases are absent (nothing fabricated)
        assert _case_by_id(ctx, gate_case_id("trade_calendar", GateKind.BUSINESS_DATA)) is None
        assert _case_by_id(ctx, gate_case_id("trade_calendar", GateKind.ENDPOINT_AVAILABLE)) is None
        # the REPORT case records the block
        report_case = _case_by_id(ctx, gate_report_case_id("trade_calendar"))
        assert report_case is not None
        assert report_case.result is CaseResult.NOT_TESTABLE_PERMISSION

    def test_probe_b1_runs_the_boundary_for_all_capabilities(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        out = probe_b1_formal_gates(ctx)
        assert out["count"] == len(GATE_PLAN_SPECS)
        assert all(v == "PASS" for v in out["capabilities"].values())
        # every capability left its full proof: 3 probe cases + REPORT
        for capability in GATE_PLAN_SPECS:
            for kind in FORMAL_GATE_PROBE_KINDS:
                case = _case_by_id(ctx, gate_case_id(capability, kind))
                assert case is not None, (capability, kind)
                assert case.result is CaseResult.VALIDATED_PASS
                assert case.evidence_ref.endswith(".meta.json")
                assert len(case.evidence_hash) == 64
            report_case = _case_by_id(ctx, gate_report_case_id(capability))
            assert report_case is not None
            assert report_case.result is CaseResult.VALIDATED_PASS

    def test_gate_report_artifact_persisted_with_bindings(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        executor = FormalRuntimeGateExecutor(ctx)
        executor.execute(GATE_PLAN_SPECS["daily_bar"](ctx))

        report_path = (
            ctx.store.run_dir(ctx.run) / "gates" / "daily_bar.json"
        )
        assert report_path.is_file()
        doc = json.loads(report_path.read_text(encoding="utf-8"))
        assert doc["capability"] == "daily_bar"
        assert doc["all_passed"] is True
        by_kind = {g["kind"]: g for g in doc["gates"]}
        for kind in FORMAL_GATE_PROBE_KINDS:
            entry = by_kind[kind.value]
            assert entry["evidence_uri"].endswith(".meta.json")
            assert len(entry["evidence_hash"]) == 64
            assert entry["request_id"]
        # the REPORT case binds this artifact by hash
        report_case = _case_by_id(ctx, gate_report_case_id("daily_bar"))
        import hashlib

        assert report_case.evidence_hash == hashlib.sha256(report_path.read_bytes()).hexdigest()
        assert report_case.evidence_ref.endswith("gates/daily_bar.json")

    def test_dry_run_includes_b1_phase(self, tmp_path: Path):
        from ashare_state.spike.runner import run_dry_run

        outputs = run_dry_run(spike_root=tmp_path / "spike")
        assert "b1" in outputs["phases"]
        assert outputs["phases"]["b1"]["count"] == len(GATE_PLAN_SPECS)


@pytest.mark.integration
class TestGateEvidenceBindingAdversarial:
    def test_persistence_failure_downgrades_pass_to_fail(self, tmp_path: Path):
        """P0-02: a request id alone is NOT persisted evidence PASS. When
        the exchange fires but the bytes never land on disk, the gate
        must FAIL (fail closed), not pass on the request identity."""
        ctx = _ctx(tmp_path, context_cls=_NoPersistContext)
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        assert not bound.report.all_passed
        assert bound.report.blocked_by is GateKind.PERMISSION
        permission_result = next(
            r for r in bound.report.results if r.kind is GateKind.PERMISSION
        )
        assert permission_result.status is GateStatus.FAIL
        assert "persistence failed" in permission_result.reason
        assert not permission_result.has_persisted_evidence
        # no raw evidence was written
        assert _raw_files(ctx) == []

    def test_tampered_meta_blocks_verdict(self, tmp_path: Path):
        """P0-02: gate proof cases are subject to the same evidence
        closure as all formal evidence - tampering with the persisted
        meta file blocks the run's evidence closure."""
        from ashare_state.spike.runner import verify_evidence_closure

        ctx = _ctx(tmp_path)
        executor = FormalRuntimeGateExecutor(ctx)
        executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))
        ctx.catalog.flush(ctx.store.run_dir(ctx.run))
        permission_case = _case_by_id(
            ctx, gate_case_id("trade_calendar", GateKind.PERMISSION)
        )
        meta_path = ctx.store.spike_root / permission_case.evidence_ref
        # tamper with the persisted bytes
        original = meta_path.read_bytes()
        meta_path.write_bytes(original + b"\n# tampered")
        problems = verify_evidence_closure(ctx.store, ctx.run, ctx.catalog)
        assert problems, "tampered gate evidence must block closure"
        combined = " ".join(problems).lower()
        assert "evidence" in combined or "hash" in combined

    def test_gate_report_artifact_tamper_blocks_verdict(self, tmp_path: Path):
        from ashare_state.spike.runner import verify_evidence_closure

        ctx = _ctx(tmp_path)
        executor = FormalRuntimeGateExecutor(ctx)
        executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))
        ctx.catalog.flush(ctx.store.run_dir(ctx.run))
        report_path = ctx.store.run_dir(ctx.run) / "gates" / "trade_calendar.json"
        report_path.write_text('{"tampered": true}', encoding="utf-8")
        problems = verify_evidence_closure(ctx.store, ctx.run, ctx.catalog)
        assert problems, "tampered gate report must block closure"


@pytest.mark.integration
class TestNoBypassStaticGuards:
    """Control-flow guards (audit P0-01): the formal path cannot silently
    drop the gate boundary - enforced by AST on the consumed sources."""

    def _function_source(self, path: Path, name: str) -> str:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.dump(node)
        raise AssertionError(f"function {name} not found in {path}")

    def test_approval_calls_the_formal_gate_proof_check(self):
        """approve_from_spike_run statically consumes the boundary."""
        source_path = (
            REPO_ROOT / "src" / "ashare_state" / "providers" / "amazingdata" / "capability.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        approval = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "approve_from_spike_run"
        )
        called = {
            ast.unparse(node.func)
            for node in ast.walk(approval)
            if isinstance(node, ast.Call)
        }
        assert "_require_formal_gate_proof" in called

    def test_executor_builds_the_frozen_pipeline(self):
        source_path = REPO_ROOT / "src" / "ashare_state" / "spike" / "formal_gates.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        executor = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "FormalRuntimeGateExecutor"
        )
        execute = next(
            n for n in ast.walk(executor) if isinstance(n, ast.FunctionDef) and n.name == "execute"
        )
        called = {
            ast.unparse(node.func)
            for node in ast.walk(execute)
            if isinstance(node, ast.Call)
        }
        assert "RuntimeGatePipeline" in called, "the boundary must build the frozen pipeline"

    def test_probe_b1_uses_the_executor_not_a_private_pipeline(self):
        source_path = REPO_ROOT / "src" / "ashare_state" / "spike" / "formal_gates.py"
        dumped = self._function_source(source_path, "probe_b1_formal_gates")
        assert "FormalRuntimeGateExecutor" in dumped

    def test_dry_run_runner_consumes_probe_b1(self):
        source_path = REPO_ROOT / "src" / "ashare_state" / "spike" / "runner.py"
        dumped = self._function_source(source_path, "run_dry_run")
        assert "probe_b1_formal_gates" in dumped
