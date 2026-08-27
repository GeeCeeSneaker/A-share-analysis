"""Formal runtime gate execution boundary (R4-A3.1 P0-01/P0-02, audit
20260827).

R4-A3 delivered the gate library (``providers.runtime_gates``) as a
reusable component - but a component test proves the LIBRARY, not the
FORMAL PATH. This module is the ONE formal gate execution boundary:

    FormalRuntimeGateExecutor(CapabilityProbePlan)
      -> AUTH_ACCOUNT        (session lifecycle + account profile)
      -> PERMISSION          (REAL probe exchange, persisted)
      -> ENDPOINT_AVAILABLE  (REAL probe exchange, persisted)
      -> CACHE_METADATA      (local prerequisite validity, no call)
      -> FRESHNESS_ASOF      (data as-of vs required, no call)
      -> BUSINESS_DATA       (REAL business exchange, persisted)

Non-bypassability (audit P0-01):
- the plan must define EVERY gate - a caller cannot opt out of
  permission/freshness and jump straight to the business fetch;
- the pipeline ordering + early stop is the frozen component semantics;
- ``capability.approve_from_spike_run`` REFUSES runs without the gate
  proof cases this executor emits (``_require_formal_gate_proof``), so
  the capability-approval path cannot bypass the boundary either.

Persisted evidence closure (audit P0-02):
- every probe gate exchange - success AND failure - is persisted
  through the SAME RawWriter boundary as all formal evidence
  (``ProbeContext.evidence_from_exchange``), never a private writer;
- each gate result binds the persisted evidence identity EXPLICITLY:
  request_id + evidence_uri (the .meta.json anchor) + evidence_hash;
  a request id alone is never accepted as formal evidence;
- persistence failure (exchange exists, bytes not on disk) DOWNGRADES
  the gate to FAIL - fail closed;
- after a blocking gate, downstream probes fire ZERO provider calls and
  persist ZERO raw evidence (provable by counters and by the raw dir).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from ashare_state.providers.amazingdata.capability import FORMAL_GATE_CASE_TYPE
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.providers.runtime_gates import (
    AuthAccountGate,
    BusinessDataGate,
    CacheMetadataGate,
    EndpointAvailableGate,
    FreshnessAsOfGate,
    GateKind,
    GateReport,
    GateResult,
    GateStatus,
    PermissionGate,
    ProbeCaller,
    RuntimeGatePipeline,
)
from ashare_state.spike.model import CaseResult, RunKind

if TYPE_CHECKING:
    from ashare_state.spike.probes import ProbeContext

__all__ = [
    "FORMAL_GATE_PROBE_KINDS",
    "CapabilityProbePlan",
    "FormalGateProofError",
    "FormalRuntimeGateExecutor",
    "GATE_PLAN_SPECS",
    "GateEvidenceIdentity",
    "gate_report_case_id",
    "probe_b1_formal_gates",
]

#: the probe gates whose exchanges MUST be persisted (P0-02)
FORMAL_GATE_PROBE_KINDS = (
    GateKind.PERMISSION,
    GateKind.ENDPOINT_AVAILABLE,
    GateKind.BUSINESS_DATA,
)


#: gate proof case id helper (mirrors capability._require_formal_gate_proof)
def gate_case_id(capability: str, kind: GateKind) -> str:
    return f"GATE-{capability}-{kind.value}"


def gate_report_case_id(capability: str) -> str:
    return f"GATE-{capability}-REPORT"


@dataclass(frozen=True)
class GateEvidenceIdentity:
    """P0-02: the typed persisted-evidence identity of one fired probe."""

    request_id: str
    evidence_uri: str
    evidence_hash: str


class FormalGateProofError(RuntimeError):
    """The formal gate boundary contract was violated."""


@dataclass(frozen=True)
class CapabilityProbePlan:
    """A complete formal gate plan for one capability.

    A caller CANNOT skip a gate: every probe/validator is mandatory and
    the executor assembles the full pipeline in the fixed order."""

    capability: str
    permission_probe: ProbeCaller
    endpoint_probe: ProbeCaller
    cache_validator: Callable[[], tuple[bool, str]]
    data_as_of: str
    required_as_of: str
    business_fetch: ProbeCaller
    cache_evidence_ref: str = ""
    freshness_evidence_ref: str = ""


class _PersistedProbe:
    """Wraps a ProbeCaller so EVERY fired exchange - success or
    first-class failure - is persisted through the run's RawWriter
    BEFORE the gate sees it, and the binding is recorded.

    A probe PASS without a persisted binding is impossible from here:
    persistence failure downgrades to a recorded error which the
    executor turns into a gate FAIL (fail closed, audit P0-02)."""

    def __init__(self, ctx: ProbeContext, probe: ProbeCaller, label: str) -> None:
        self.ctx = ctx
        self.probe = probe
        self.label = label
        self.fired = 0
        self.binding: GateEvidenceIdentity | None = None
        self.persist_error: str = ""

    def __call__(self) -> ProviderExchange:
        self.fired += 1
        try:
            exchange = self.probe()
        except ProviderError as exc:
            failure = getattr(exc, "exchange", None)
            if failure is not None:
                self._persist(failure)
            raise
        self._persist(exchange)
        return exchange

    def _persist(self, exchange: ProviderExchange) -> None:
        try:
            meta = self.ctx.evidence_from_exchange(exchange)
        except Exception as exc:  # noqa: BLE001 - persistence failure is a gate failure
            self.persist_error = f"{type(exc).__name__}: {exc}"
            return
        self.binding = GateEvidenceIdentity(
            request_id=str(meta.get("request_id", "")),
            evidence_uri=str(meta.get("evidence_ref", "")),
            evidence_hash=str(meta.get("content_hash", "")),
        )


@dataclass
class _BoundReport:
    """GateReport + per-gate persisted bindings + probe counters."""

    report: GateReport
    bindings: dict[GateKind, GateEvidenceIdentity] = field(default_factory=dict)
    probes: dict[GateKind, _PersistedProbe] = field(default_factory=dict)


class FormalRuntimeGateExecutor:
    """The ONE formal gate execution boundary (audit R4-A3.1 P0-01).

    Executes a :class:`CapabilityProbePlan` through the frozen
    ``RuntimeGatePipeline`` component; persists every probe exchange via
    the run's RawWriter; binds persisted evidence identities onto the
    gate results; emits the gate-proof SpikeCases (PERMISSION/ENDPOINT/
    BUSINESS + REPORT) consumed by capability approval."""

    def __init__(self, ctx: ProbeContext) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------- execute
    def execute(self, plan: CapabilityProbePlan) -> _BoundReport:
        identity = self.ctx.target.identity()
        lifecycle = self._target_lifecycle()
        account_profile_id = str(identity.get("account_profile_id", "UNKNOWN"))
        profile_parsed = bool(identity.get("profile_parsed", False))

        # P0-03: production proof input requires the POSITIVE frozen
        # identity; trial/dry-run runs keep the connectivity semantics.
        require_production = self.ctx.run.run_kind is RunKind.PRODUCTION
        frozen_id = ""
        if require_production:
            from ashare_state.providers.amazingdata import production_identity

            frozen = production_identity.load_frozen_production_identity()
            frozen_id = frozen.account_profile_id if frozen else ""

        permission_probe = _PersistedProbe(self.ctx, plan.permission_probe, "PERMISSION")
        endpoint_probe = _PersistedProbe(self.ctx, plan.endpoint_probe, "ENDPOINT")
        business_probe = _PersistedProbe(self.ctx, plan.business_fetch, "BUSINESS")

        pipeline = RuntimeGatePipeline(
            [
                AuthAccountGate(
                    lifecycle=lifecycle,
                    account_profile_id=account_profile_id,
                    profile_parsed=profile_parsed,
                    require_production_identity=require_production,
                    frozen_production_id=frozen_id,
                ),
                PermissionGate(permission_probe),
                EndpointAvailableGate(endpoint_probe),
                CacheMetadataGate(plan.cache_validator, evidence_ref=plan.cache_evidence_ref),
                FreshnessAsOfGate(
                    data_as_of=plan.data_as_of,
                    required_as_of=plan.required_as_of,
                    evidence_ref=plan.freshness_evidence_ref,
                ),
                BusinessDataGate(business_probe),
            ]
        )
        report = pipeline.evaluate()

        probes = {
            GateKind.PERMISSION: permission_probe,
            GateKind.ENDPOINT_AVAILABLE: endpoint_probe,
            GateKind.BUSINESS_DATA: business_probe,
        }
        bindings: dict[GateKind, GateEvidenceIdentity] = {}
        bound_results: list[GateResult] = []
        downgraded: GateKind | None = None
        for result in report.results:
            probe = probes.get(result.kind)
            if probe is None:
                bound_results.append(result)
                continue
            if probe.binding is not None:
                bindings[result.kind] = probe.binding
                bound = replace(
                    result,
                    request_id=probe.binding.request_id,
                    evidence_uri=probe.binding.evidence_uri,
                    evidence_hash=probe.binding.evidence_hash,
                    evidence_ref=probe.binding.evidence_uri,
                )
            elif result.status is GateStatus.PASS:
                # P0-02 fail-closed: the exchange fired but the evidence
                # bytes are NOT on disk - a request id is not formal
                # evidence PASS.
                bound = replace(
                    result,
                    status=GateStatus.FAIL,
                    reason=(
                        f"probe PASSED but evidence persistence failed - "
                        f"{probe.persist_error or 'no persisted evidence'}; "
                        "formal evidence PASS refused (audit R4-A3.1 P0-02)"
                    ),
                )
                if downgraded is None:
                    downgraded = result.kind
            else:
                bound = result
            bound_results.append(bound)
        bound_report = _BoundReport(
            report=replace(
                report,
                results=tuple(bound_results),
                early_stopped=True if downgraded is not None else report.early_stopped,
                blocked_by=downgraded or report.blocked_by,
            ),
            bindings=bindings,
            probes=probes,
        )
        self._emit_cases(plan, bound_report)
        return bound_report

    # -------------------------------------------------------------- cases
    def _emit_cases(self, plan: CapabilityProbePlan, bound: _BoundReport) -> None:
        as_of = str(self.ctx.as_of_date)
        for kind in FORMAL_GATE_PROBE_KINDS:
            result = None
            for candidate in bound.report.results:
                if candidate.kind is kind:
                    result = candidate
                    break
            if result is None or result.status is GateStatus.SKIPPED_BLOCKED:
                # early stop: the probe never fired - no case (a missing
                # proof case blocks approval; nothing is fabricated)
                continue
            binding = bound.bindings.get(kind)
            meta = (
                {
                    "evidence_ref": binding.evidence_uri,
                    "content_hash": binding.evidence_hash,
                }
                if binding is not None
                else {}
            )
            case_result = _gate_status_to_case_result(result.status)
            self.ctx.case(
                case_id=gate_case_id(plan.capability, kind),
                case_type=FORMAL_GATE_CASE_TYPE,
                security="GATE",
                provider_symbol="GATE",
                trade_date=as_of,
                expected=f"runtime gate {kind.value} PASS with persisted evidence",
                actual=(
                    f"{result.status.value}: {result.reason}"
                    + (
                        f" | request_id={binding.request_id} "
                        f"evidence_uri={binding.evidence_uri} "
                        f"evidence_hash={binding.evidence_hash[:16]}"
                        if binding is not None
                        else " | no persisted evidence binding"
                    )
                )[:400],
                result=case_result,
                evidence_meta=meta,
                reason_code=f"GATE_{result.status.value}",
                validator_id="formal_runtime_gate_v1",
                validator_version="1.0.0",
            )
        self._emit_report_case(plan, bound, as_of)

    def _emit_report_case(self, plan: CapabilityProbePlan, bound: _BoundReport, as_of: str) -> None:
        """Persist the FULL six-gate report as a run artifact and bind a
        REPORT case to it - the auditable record that the formal boundary
        actually executed (and what each gate concluded) for this
        capability."""
        import hashlib
        import json

        report_doc = {
            "capability": plan.capability,
            "run_id": self.ctx.run.spike_run_id,
            "all_passed": bound.report.all_passed,
            "early_stopped": bound.report.early_stopped,
            "blocked_by": bound.report.blocked_by.value if bound.report.blocked_by else None,
            "gates": [
                {
                    "kind": r.kind.value,
                    "status": r.status.value,
                    "reason": r.reason,
                    "provider_calls_fired": r.provider_calls_fired,
                    "request_id": r.request_id,
                    "evidence_uri": r.evidence_uri,
                    "evidence_hash": r.evidence_hash,
                }
                for r in bound.report.results
            ],
        }
        run_dir = self.ctx.store.run_dir(self.ctx.run)
        gates_dir = run_dir / "gates"
        gates_dir.mkdir(parents=True, exist_ok=True)
        report_path = gates_dir / f"{plan.capability}.json"
        payload = json.dumps(report_doc, indent=2, ensure_ascii=False, sort_keys=True)
        report_path.write_text(payload, encoding="utf-8")
        report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        run_prefix = f"{self.ctx.run.run_kind.value.lower()}/{self.ctx.run.spike_run_id}/"
        meta = {
            "evidence_ref": f"{run_prefix}gates/{plan.capability}.json",
            "content_hash": report_hash,
        }
        self.ctx.case(
            case_id=gate_report_case_id(plan.capability),
            case_type=FORMAL_GATE_CASE_TYPE,
            security="GATE",
            provider_symbol="GATE",
            trade_date=as_of,
            expected="all six runtime gates PASS through the formal boundary",
            actual=(
                "all_passed"
                if bound.report.all_passed
                else (
                    "blocked_by="
                    f"{bound.report.blocked_by.value if bound.report.blocked_by else 'n/a'}"
                )
            ),
            result=(
                CaseResult.VALIDATED_PASS
                if bound.report.all_passed
                else CaseResult.NOT_TESTABLE_PERMISSION
            ),
            evidence_meta=meta,
            reason_code=("GATE_ALL_PASS" if bound.report.all_passed else "GATE_CHAIN_BLOCKED"),
            validator_id="formal_runtime_gate_v1",
            validator_version="1.0.0",
        )

    # ------------------------------------------------------------ helpers
    def _target_lifecycle(self):
        lifecycle = getattr(self.ctx.target, "lifecycle", None)
        if lifecycle is None:
            msg = (
                "formal gate boundary: target does not expose the SDK "
                "lifecycle - the AUTH gate must consume the REAL control-flow "
                "state machine (audit R4-A3.1 P0-01)"
            )
            raise FormalGateProofError(msg)
        return lifecycle


def _gate_status_to_case_result(status: GateStatus) -> CaseResult:
    if status is GateStatus.PASS:
        return CaseResult.VALIDATED_PASS
    if status is GateStatus.FAIL:
        return CaseResult.VALIDATED_FAIL
    return CaseResult.NOT_TESTABLE_PERMISSION


# ------------------------------------------------------------------ plans


def _rule_book_validator_factory(ctx: ProbeContext) -> Callable[[], tuple[bool, str]]:
    """CACHE_METADATA for limit/rule-dependent capabilities: the run-bound
    trading-rule book must be loadable (local prerequisite, no call)."""

    def validator() -> tuple[bool, str]:
        try:
            _book = ctx.rule_book  # noqa: F841 - loadability IS the check
        except Exception as exc:  # noqa: BLE001 - local metadata failure blocks
            return False, f"run-bound rule book unavailable: {exc}"
        return True, "run-bound trading-rule book loadable"

    return validator


def _ok_validator(detail: str = "local prerequisites present") -> tuple[bool, str]:
    return True, detail


def _plan(
    capability: str,
    ctx: ProbeContext,
    *,
    endpoint_probe: Callable[[], ProviderExchange],
    business_fetch: Callable[[], ProviderExchange],
    cache_validator: Callable[[], tuple[bool, str]] | None = None,
) -> CapabilityProbePlan:
    """Assemble a complete plan - every gate is mandatory (no opt-out)."""
    as_of = str(ctx.as_of_date)
    return CapabilityProbePlan(
        capability=capability,
        permission_probe=lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
        endpoint_probe=endpoint_probe,
        cache_validator=cache_validator or _ok_validator,
        data_as_of=as_of,
        required_as_of=as_of,
        business_fetch=business_fetch,
        cache_evidence_ref="run-bound rule book" if cache_validator else "local prerequisites",
        freshness_evidence_ref=f"run as-of {as_of}",
    )


def _factory(
    capability: str,
    endpoint_probe: Callable[[ProbeContext], ProviderExchange],
    business_fetch: Callable[[ProbeContext], ProviderExchange],
    rule_bound: bool = False,
) -> Callable[[ProbeContext], CapabilityProbePlan]:
    def build(ctx: ProbeContext) -> CapabilityProbePlan:
        return _plan(
            capability,
            ctx,
            endpoint_probe=lambda: endpoint_probe(ctx),
            business_fetch=lambda: business_fetch(ctx),
            cache_validator=_rule_book_validator_factory(ctx) if rule_bound else None,
        )

    return build


# ------------------------------------------------------- named gate probes
# (explicit annotations: the gate plans are static declarations, and the
# endpoint/business fetch signatures must be checkable - no anonymous
# nested lambdas whose types mypy cannot determine)


def _probe_calendar(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_calendar_exchange()


def _probe_hist_code_list(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_hist_code_list_exchange("EXTRA_STOCK_A_SH_SZ", 19900101, ctx.as_of_date)


def _probe_code_list_bj(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_code_list_exchange("EXTRA_STOCK_BJ")


def _probe_kline_600519(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.query_kline_exchange(
        ["600519.SH"],
        begin_date=ctx.as_of_date,
        end_date=ctx.as_of_date,
        kline_type="DAY",
        trading_days=[ctx.as_of_date],
    )


def _probe_kline_index(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.query_kline_exchange(
        ["000300.SH"],
        begin_date=ctx.as_of_date,
        end_date=ctx.as_of_date,
        kline_type="DAY",
        trading_days=[ctx.as_of_date],
    )


def _probe_status_history(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_history_stock_status_exchange(
        ctx.as_of_date, ctx.as_of_date, ["600519.SH"]
    )


def _probe_adj_factor(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_adj_factor_exchange(["600519.SH"])


def _probe_dividend(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_dividend_exchange(["600519.SH"])


def _probe_stock_basic(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_stock_basic_exchange(["600519.SH"])


#: per-capability formal gate plans (R4-A3.1 P0-01). The endpoint /
#: business fetches use the SpikeTarget's explicit exchange surface; for
#: capabilities whose dedicated endpoints are not yet on the target
#: surface (industry_taxonomy / equity_structure), the entitlement
#: surface stands in as the GATE probe - semantic endpoint validation
#: remains the job of the B2-B7 probes (this boundary proves the GATE
#: CHAIN, not business semantics).
GATE_PLAN_SPECS: dict[str, Callable[[ProbeContext], CapabilityProbePlan]] = {
    "trade_calendar": _factory("trade_calendar", _probe_calendar, _probe_calendar),
    "security_master": _factory("security_master", _probe_hist_code_list, _probe_hist_code_list),
    "code_mapping_bj": _factory("code_mapping_bj", _probe_code_list_bj, _probe_code_list_bj),
    "daily_bar": _factory("daily_bar", _probe_calendar, _probe_kline_600519),
    "security_status_history": _factory(
        "security_status_history",
        _probe_status_history,
        _probe_status_history,
        rule_bound=True,
    ),
    "adj_factor": _factory("adj_factor", _probe_adj_factor, _probe_adj_factor),
    "corporate_action": _factory("corporate_action", _probe_dividend, _probe_dividend),
    "equity_structure": _factory("equity_structure", _probe_stock_basic, _probe_stock_basic),
    "industry_taxonomy": _factory("industry_taxonomy", _probe_stock_basic, _probe_stock_basic),
    "index_daily": _factory("index_daily", _probe_calendar, _probe_kline_index),
}


def probe_b1_formal_gates(ctx: ProbeContext) -> dict[str, Any]:
    """B1: execute the formal gate boundary for EVERY registered
    capability - the mandatory first phase of formal runs (audit
    R4-A3.1 P0-01). Capability approval consumes these proofs; a run
    without them cannot approve anything."""
    executor = FormalRuntimeGateExecutor(ctx)
    results: dict[str, str] = {}
    for capability, build_plan in GATE_PLAN_SPECS.items():
        plan = build_plan(ctx)
        bound = executor.execute(plan)
        results[capability] = (
            "PASS" if bound.report.all_passed else f"BLOCKED_BY_{bound.report.blocked_by}"
        )
    return {"capabilities": results, "count": len(results)}
