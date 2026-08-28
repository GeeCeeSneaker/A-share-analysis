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

from ashare_state.providers.amazingdata.endpoint_requirements import (
    endpoint_requirement_case_id,
    endpoint_requirements_for,
)
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


class _SelectiveNoPersistContext(ProbeContext):
    """Persistence fails only on the Nth (0-based) persisted exchange -
    lets a single gate position (permission=0, endpoint=1, business=2)
    hit the persistence failure while the upstream ones bind normally."""

    def __init__(self, run, store, catalog, target, fail_on: set[int]) -> None:
        super().__init__(run, store, catalog, target)
        self._fail_on = fail_on
        self._persist_calls = 0

    @classmethod
    def fail_on_factory(cls, fail_on: set[int]):
        def make(run, store, catalog, target):
            return cls(run, store, catalog, target, fail_on=fail_on)

        return make

    def evidence_from_exchange(self, exchange):
        index = self._persist_calls
        self._persist_calls += 1
        if index in self._fail_on:
            raise RuntimeError(f"simulated persistence failure #{index}")
        return super().evidence_from_exchange(exchange)


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
        # every single-probe gate bound a persisted evidence identity
        for kind in (GateKind.PERMISSION, GateKind.BUSINESS_DATA):
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
        # R4-B1: EVERY endpoint requirement fired its exact probe and
        # bound persisted evidence (one outcome per requirement)
        requirements = endpoint_requirements_for("trade_calendar")
        assert requirements
        for req in requirements:
            outcome = bound.endpoint_outcomes[req.requirement_id]
            assert outcome.status is GateStatus.PASS
            assert outcome.actual_endpoint == req.endpoint
            assert outcome.actual_dataset == req.provider_dataset
            assert outcome.binding is not None
            assert outcome.binding.evidence_uri.endswith(".meta.json")
            assert len(outcome.binding.evidence_hash) == 64
            assert bound.endpoint_probes[req.requirement_id].fired == 1
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
        probes_fired += sum(p.fired for p in bound.endpoint_probes.values())
        assert probes_fired == 0
        # exactly one persisted evidence exists: the permission failure
        assert len(_raw_files(ctx)) == 1
        # business/endpoint gate cases are absent (nothing fabricated)
        assert _case_by_id(ctx, gate_case_id("trade_calendar", GateKind.BUSINESS_DATA)) is None
        for req in endpoint_requirements_for("trade_calendar"):
            assert _case_by_id(ctx, endpoint_requirement_case_id(req)) is None
        # the REPORT case records the block
        report_case = _case_by_id(ctx, gate_report_case_id("trade_calendar"))
        assert report_case is not None
        assert report_case.result is CaseResult.NOT_TESTABLE_PERMISSION

    def test_probe_b1_runs_the_boundary_for_all_capabilities(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        out = probe_b1_formal_gates(ctx)
        assert out["count"] == len(GATE_PLAN_SPECS)
        assert all(v == "PASS" for v in out["capabilities"].values())
        # every capability left its full proof: PERMISSION/BUSINESS cases
        # + one case PER endpoint requirement + REPORT (R4-B1 B1-04)
        for capability in GATE_PLAN_SPECS:
            for kind in (GateKind.PERMISSION, GateKind.BUSINESS_DATA):
                case = _case_by_id(ctx, gate_case_id(capability, kind))
                assert case is not None, (capability, kind)
                assert case.result is CaseResult.VALIDATED_PASS
                assert case.evidence_ref.endswith(".meta.json")
                assert len(case.evidence_hash) == 64
            for req in endpoint_requirements_for(capability):
                case = _case_by_id(ctx, endpoint_requirement_case_id(req))
                assert case is not None, (capability, req.requirement_id)
                assert case.result is CaseResult.VALIDATED_PASS
                assert case.evidence_ref.endswith(".meta.json")
                assert len(case.evidence_hash) == 64
                assert req.endpoint in case.expected_value
            report_case = _case_by_id(ctx, gate_report_case_id(capability))
            assert report_case is not None
            assert report_case.result is CaseResult.VALIDATED_PASS

    def test_gate_report_artifact_persisted_with_bindings(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        executor = FormalRuntimeGateExecutor(ctx)
        executor.execute(GATE_PLAN_SPECS["daily_bar"](ctx))

        report_path = ctx.store.run_dir(ctx.run) / "gates" / "daily_bar.json"
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
    """R4-A3.2 P0-01 (audit 20260828): persistence failure is a blocking
    FAIL DURING gate evaluation - the pipeline early-stops structurally
    so downstream probes fire ZERO provider calls. A post-hoc rewrite
    after the pipeline finished (the shipped bug) would report an early
    stop that never happened; these tests pin the structural truth via
    the per-probe ``fired`` counters, not just the final blocked_by."""

    def test_permission_persistence_fail_blocks_immediately(self, tmp_path: Path):
        """PERMISSION exchange succeeds, its persist fails -> PERMISSION
        FAILs during evaluation; ENDPOINT/BUSINESS probes never fire;
        zero downstream Raw evidence."""
        ctx = _ctx(tmp_path, context_cls=_NoPersistContext)
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        assert not bound.report.all_passed
        assert bound.report.early_stopped
        assert bound.report.blocked_by is GateKind.PERMISSION
        permission_result = next(r for r in bound.report.results if r.kind is GateKind.PERMISSION)
        assert permission_result.status is GateStatus.FAIL
        assert "persistence failed" in permission_result.reason
        # the request identity may be recorded, but URI/hash are absent:
        # a request id alone is never formal evidence PASS (P0-02)
        assert not permission_result.has_persisted_evidence
        assert not permission_result.evidence_uri
        assert not permission_result.evidence_hash
        # STRUCTURAL early stop: downstream probes never fired
        assert all(p.fired == 0 for p in bound.endpoint_probes.values())
        assert bound.probes[GateKind.BUSINESS_DATA].fired == 0
        # downstream gates are SKIPPED_BLOCKED, not evaluated
        endpoint_result = next(
            r for r in bound.report.results if r.kind is GateKind.ENDPOINT_AVAILABLE
        )
        business_result = next(r for r in bound.report.results if r.kind is GateKind.BUSINESS_DATA)
        assert endpoint_result.status is GateStatus.SKIPPED_BLOCKED
        assert business_result.status is GateStatus.SKIPPED_BLOCKED
        assert endpoint_result.provider_calls_fired == 0
        assert business_result.provider_calls_fired == 0
        # zero downstream Raw evidence (nothing landed on disk at all)
        assert _raw_files(ctx) == []

    def test_endpoint_persistence_fail_blocks_business(self, tmp_path: Path):
        """ENDPOINT exchange succeeds, its persist fails -> ENDPOINT
        FAILs during evaluation; the BUSINESS probe never fires."""
        ctx = _ctx(tmp_path, context_cls=_SelectiveNoPersistContext.fail_on_factory({1}))
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        assert not bound.report.all_passed
        assert bound.report.early_stopped
        assert bound.report.blocked_by is GateKind.ENDPOINT_AVAILABLE
        # permission persisted fine (binding present), endpoint did not
        permission_result = next(r for r in bound.report.results if r.kind is GateKind.PERMISSION)
        endpoint_result = next(
            r for r in bound.report.results if r.kind is GateKind.ENDPOINT_AVAILABLE
        )
        assert permission_result.status is GateStatus.PASS
        assert permission_result.has_persisted_evidence
        assert endpoint_result.status is GateStatus.FAIL
        assert "persistence failed" in endpoint_result.reason
        assert not endpoint_result.has_persisted_evidence
        # STRUCTURAL early stop: the business probe never fired
        assert bound.probes[GateKind.BUSINESS_DATA].fired == 0
        business_result = next(r for r in bound.report.results if r.kind is GateKind.BUSINESS_DATA)
        assert business_result.status is GateStatus.SKIPPED_BLOCKED
        assert business_result.provider_calls_fired == 0
        # exactly one Raw evidence landed: the permission exchange
        assert len(_raw_files(ctx)) == 1

    def test_business_persistence_fail_refuses_all_passed(self, tmp_path: Path):
        """BUSINESS exchange succeeds, its persist fails -> BUSINESS
        FAILs during evaluation; the report can never claim all_passed."""
        ctx = _ctx(tmp_path, context_cls=_SelectiveNoPersistContext.fail_on_factory({2}))
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        assert not bound.report.all_passed
        assert bound.report.blocked_by is GateKind.BUSINESS_DATA
        business_result = next(r for r in bound.report.results if r.kind is GateKind.BUSINESS_DATA)
        assert business_result.status is GateStatus.FAIL
        assert "persistence failed" in business_result.reason
        assert not business_result.has_persisted_evidence
        # the business probe DID fire (upstream gates passed) - only its
        # persistence failed; the two upstream exchanges persisted
        assert bound.probes[GateKind.BUSINESS_DATA].fired == 1
        assert len(_raw_files(ctx)) == 2

    def test_request_id_alone_is_never_formal_evidence_pass(self, tmp_path: Path):
        """P0-02 via P0-01 lens: a downgraded result may carry the
        request identity, but with URI/hash absent it can never be read
        as formal evidence PASS."""
        ctx = _ctx(tmp_path, context_cls=_NoPersistContext)
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))

        permission_result = next(r for r in bound.report.results if r.kind is GateKind.PERMISSION)
        assert permission_result.status is GateStatus.FAIL
        # request_id may exist; has_persisted_evidence must be False
        assert not (permission_result.request_id and permission_result.has_persisted_evidence)
        assert not permission_result.has_persisted_evidence
        # and the proof case for a failing gate is a FAIL case, never PASS
        permission_case = _case_by_id(ctx, gate_case_id("trade_calendar", GateKind.PERMISSION))
        assert permission_case is not None
        assert permission_case.result is CaseResult.VALIDATED_FAIL

    def test_tampered_meta_blocks_verdict(self, tmp_path: Path):
        """P0-02: gate proof cases are subject to the same evidence
        closure as all formal evidence - tampering with the persisted
        meta file blocks the run's evidence closure."""
        from ashare_state.spike.runner import verify_evidence_closure

        ctx = _ctx(tmp_path)
        executor = FormalRuntimeGateExecutor(ctx)
        executor.execute(GATE_PLAN_SPECS["trade_calendar"](ctx))
        ctx.catalog.flush(ctx.store.run_dir(ctx.run))
        permission_case = _case_by_id(ctx, gate_case_id("trade_calendar", GateKind.PERMISSION))
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
            ast.unparse(node.func) for node in ast.walk(approval) if isinstance(node, ast.Call)
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
            ast.unparse(node.func) for node in ast.walk(execute) if isinstance(node, ast.Call)
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
