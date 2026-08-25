"""CR-1.2.2 Probe Exchange Enforcement tests (audit 20260825 #2, P0-01).

Every real provider exchange on the formal probe path is persisted -
success AND failure - through the approved execution boundary
(ProbeExecutor.call / the golden-router domain collector). "Calling
ctx.target.*_exchange directly and remembering to persist afterwards" is
no longer a correctness contract anyone may rely on.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import (
    ProbeContext,
    probe_b2_security_master,
    probe_b3_core_facts,
    probe_b4_golden,
    probe_b5_units_pit_freshness,
    probe_b6_replacement,
    probe_b7_capacity,
)
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget

_SHA = "e" * 40


class _CodeListDeniedTarget(FakeTarget):
    """get_code_list FAILS with a first-class error exchange (the exact
    P0-01 scenario: the exception escapes BEFORE any manual persist)."""

    def get_code_list_exchange(self, security_type=None):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="code_list",
            endpoint="BaseData.get_code_list",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("code list entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


def _counting_target() -> tuple[FakeTarget, dict[str, int]]:
    """Wrap FakeTarget so every *_exchange CALL is counted."""
    counter: dict[str, int] = {"calls": 0}
    inner = FakeTarget()

    class _Counting(FakeTarget):
        def __init__(self) -> None:
            super().__init__()
            self.__dict__["_inner"] = inner

        def __getattribute__(self, name: str):
            if name.endswith("_exchange") and name != "exchange_calls":

                def counted(*args, **kwargs):
                    counter["calls"] += 1
                    return getattr(inner, name)(*args, **kwargs)

                return counted
            return getattr(inner, name)

    return _Counting(), counter


def _ctx(tmp_path: Path, target=None) -> ProbeContext:
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
    return ProbeContext(run, store, catalog, target or FakeTarget())


def _metas(ctx: ProbeContext) -> list[dict]:
    raw_root = ctx.store.raw_dir(ctx.run)
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(raw_root.glob("provider=*/dataset=*/*.meta.json"))
    ]


def _failure_metas(ctx: ProbeContext, endpoint: str) -> list[dict]:
    return [m for m in _metas(ctx) if m["endpoint"] == endpoint and m["status"] == "ERROR"]


class TestB5CodeListBoundary:
    def test_success_persists_exactly_one_raw_meta(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        metrics = probe_b5_units_pit_freshness(ctx, 20220601)
        assert metrics["symbols"] > 0
        code_list_metas = [m for m in _metas(ctx) if m["endpoint"] == "BaseData.get_code_list"]
        assert len(code_list_metas) == 1
        assert code_list_metas[0]["status"] == "OK"

    def test_failure_persists_failure_meta_and_structured_case(self, tmp_path: Path):
        """The P0-01 scenario: the exception escapes BEFORE the old manual
        persist - the boundary must catch it and persist the failure
        exchange as raw evidence + a structured case."""
        ctx = _ctx(tmp_path, target=_CodeListDeniedTarget())
        metrics = probe_b5_units_pit_freshness(ctx, 20220601)  # must not raise
        assert metrics["symbols"] == 0
        failures = _failure_metas(ctx, "BaseData.get_code_list")
        assert len(failures) == 1
        assert failures[0]["error_class"] == "ProviderPermissionError"
        cases = [c for c in ctx.catalog.cases if c.case_type == "symbol_mapping_unambiguous"]
        assert cases
        assert all(c.result is CaseResult.NOT_TESTABLE_PERMISSION for c in cases)


class TestB6CodeListBoundary:
    def test_success_persists_raw_meta(self, tmp_path: Path):
        """B6 previously consumed the code-list exchange WITHOUT persisting
        it at all - the boundary now persists it."""
        ctx = _ctx(tmp_path)
        probe_b6_replacement(ctx, 20220601)
        code_list_metas = [m for m in _metas(ctx) if m["endpoint"] == "BaseData.get_code_list"]
        assert len(code_list_metas) == 1
        assert code_list_metas[0]["status"] == "OK"

    def test_failure_persists_meta_and_structured_case(self, tmp_path: Path):
        ctx = _ctx(tmp_path, target=_CodeListDeniedTarget())
        probe_b6_replacement(ctx, 20220601)  # must not raise
        failures = _failure_metas(ctx, "BaseData.get_code_list")
        assert len(failures) == 1
        cases = [c for c in ctx.catalog.cases if c.case_type == "free_float_equivalence"]
        assert cases
        # the dependent stock_basic call was NOT fired
        assert not [m for m in _metas(ctx) if m["endpoint"] == "InfoData.get_stock_basic"]


class TestExchangeCountClosure:
    """Instrumented Spy: formal B2-B7 real-call count == persisted exchange
    count (every exchange that FIRED left exactly one raw meta)."""

    @pytest.mark.parametrize(
        ("probe", "sample"),
        [
            (probe_b3_core_facts, 20220601),
            (probe_b5_units_pit_freshness, 20220601),
            (probe_b6_replacement, 20220601),
            (probe_b7_capacity, 20220601),
        ],
    )
    def test_probe_real_calls_equal_persisted_exchanges(self, tmp_path, probe, sample):
        target, counter = _counting_target()
        ctx = _ctx(tmp_path, target=target)
        probe(ctx, sample)
        metas = _metas(ctx)
        assert counter["calls"] == len(metas), (
            f"{probe.__name__}: {counter['calls']} real exchange calls but "
            f"{len(metas)} persisted raw metas - an exchange escaped the "
            "evidence boundary (CR-1.2.2 P0-01)"
        )

    def test_b2_security_master_calls_equal_persisted(self, tmp_path):
        target, counter = _counting_target()
        ctx = _ctx(tmp_path, target=target)
        probe_b2_security_master(ctx)
        metas = _metas(ctx)
        assert counter["calls"] == len(metas)

    def test_b4_golden_calls_equal_persisted(self, tmp_path: Path):
        target, counter = _counting_target()
        ctx = _ctx(tmp_path, target=target)
        out = probe_b4_golden(ctx, 20260814)
        assert out["golden_cases"] > 0
        metas = _metas(ctx)
        assert counter["calls"] == len(metas)


class TestStaticBoundaryGuard:
    """AST guard: in the formal runtime modules, a direct
    ``ctx.target.*_exchange(...)`` CALL must sit inside an approved
    execution boundary - i.e. within a lambda handed to the executor, or
    (golden_router) inside the domain collector's persist path. Direct
    calls at probe-body level (the old B5/B6 pattern) are rejected."""

    @staticmethod
    def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
        parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        return parents

    @classmethod
    def _inside_lambda(cls, node: ast.AST, parents: dict[int, ast.AST]) -> bool:
        current = node
        while True:
            parent = parents.get(id(current))
            if parent is None:
                return False
            if isinstance(parent, ast.Lambda):
                return True
            current = parent

    @classmethod
    def _inside_persist_call(cls, node: ast.AST, parents: dict[int, ast.AST]) -> bool:
        """`collector.persist(ctx.target.X_exchange(...))` - the call is an
        argument of a persist() invocation (call-and-persist boundary)."""
        parent = parents.get(id(node))
        if parent is None or not isinstance(parent, ast.Call):
            return False
        func = parent.func
        return isinstance(func, ast.Attribute) and func.attr == "persist"

    @classmethod
    def _inside_atomic_call_boundary(cls, node: ast.AST, parents: dict[int, ast.AST]) -> bool:
        """R4-A2.8 P0-01: the exchange call sits inside a Lambda that is an
        argument of ``collector.call(...)`` - the ATOMIC call+persist
        boundary (the evidence is persisted before the boundary returns)."""
        current = node
        while True:
            parent = parents.get(id(current))
            if parent is None:
                return False
            if isinstance(parent, ast.Lambda):
                # the lambda must be an argument of collector.call(...)
                grand = parents.get(id(parent))
                return bool(
                    grand is not None
                    and isinstance(grand, ast.Call)
                    and isinstance(grand.func, ast.Attribute)
                    and grand.func.attr == "call"
                )
            current = parent

    def test_probes_direct_exchange_calls_must_be_in_lambda(self):
        """probes.py: every ctx.target.X_exchange(...) call node must be
        inside a Lambda (the executor.call boundary)."""
        source_path = Path("src/ashare_state/spike/probes.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        parents = self._parent_map(tree)
        offenders: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr.endswith("_exchange")
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "target"
            ) and not self._inside_lambda(node, parents):
                offenders.append(node.lineno)
        assert not offenders, (
            f"probes.py calls ctx.target.*_exchange directly at lines {offenders} "
            "- formal exchanges must go through ProbeExecutor.call (lambda) "
            "so success AND failure both persist (CR-1.2.2 P0-01)"
        )

    def test_golden_router_direct_exchange_calls_confined(self):
        """R4-A2.8 P0-01 (audit 20260825 #4 section 2.3): golden_router.py
        target exchange calls must sit inside the ATOMIC
        ``collector.call(lambda: ...)`` boundary - name-presence
        assign-then-persist patterns are NO LONGER accepted (a later
        provider-call failure could orphan a prior success exchange)."""
        source_path = Path("src/ashare_state/spike/golden_router.py")
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents = self._parent_map(tree)
        offenders: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr.endswith("_exchange")
                and isinstance(func.value, ast.Attribute)
                and func.value.attr in ("target", "ctx_target")
            ) and not self._inside_atomic_call_boundary(node, parents):
                offenders.append(node.lineno)
        assert not offenders, (
            f"golden_router.py calls target.*_exchange outside the atomic "
            f"collector.call(lambda: ...) boundary at lines {offenders} - "
            "assign-then-persist patterns are forbidden: every real provider "
            "exchange must be persisted BEFORE the next provider call fires "
            "(R4-A2.8 P0-01)"
        )
        # the atomic boundary really exists in the runtime
        assert "collector.call(" in source

    def test_golden_router_forbids_assign_then_persist_pattern(self):
        """Negative check of the guard itself: the OLD assign-then-persist
        source (the R4-A2.7 CA lineage pattern the audit rejected) MUST be
        flagged by the boundary rule (proves the guard is control-flow
        safe, not name-presence based)."""
        old_pattern = """
def fetch(ctx, collector):
    dividend_exchange = ctx.target.get_dividend_exchange(symbols)
    right_issue_exchange = ctx.target.get_right_issue_exchange(symbols)
    dividend = collector.persist(dividend_exchange)
    right_issue = collector.persist(right_issue_exchange)
    return dividend, right_issue
"""
        tree = ast.parse(old_pattern)
        parents = self._parent_map(tree)
        flagged = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.endswith("_exchange")
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr in ("target", "ctx_target")
            and not self._inside_atomic_call_boundary(node, parents)
        ]
        assert flagged, "the assign-then-persist pattern must be flagged"
