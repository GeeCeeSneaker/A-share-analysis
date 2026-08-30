"""Formal runtime gate execution boundary (R4-A3.1 P0-01/P0-02, audit
20260827; R4-A3.2 P0-01, audit 20260828; R4-B1 B1-02, audit 20260828).

R4-A3 delivered the gate library (``providers.runtime_gates``) as a
reusable component - but a component test proves the LIBRARY, not the
FORMAL PATH. This module is the ONE formal gate execution boundary:

    FormalRuntimeGateExecutor(CapabilityProbePlan)
      -> AUTH_ACCOUNT        (session lifecycle + account profile)
      -> PERMISSION          (REAL probe exchange, persisted)
      -> ENDPOINT_AVAILABLE  (REAL probe exchange PER REQUIREMENT,
                              persisted, exact endpoint identity)
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
- persistence failure (exchange exists, bytes not on disk) converts
  the gate to a blocking FAIL IMMEDIATELY, DURING gate evaluation
  (R4-A3.2 P0-01: fire + persist + verdict is one atomic evaluation -
  the frozen pipeline then early-stops so downstream probes fire ZERO
  provider calls; a post-hoc rewrite after the pipeline finished is
  FORBIDDEN - it would report an early stop that never happened);
- after a blocking gate, downstream probes fire ZERO provider calls and
  persist ZERO raw evidence (provable by counters and by the raw dir).

Exact endpoint identity (R4-B1 B1-02, audit 20260828):
- the ENDPOINT_AVAILABLE gate consumes the Endpoint Requirement
  Contract (``providers.amazingdata.endpoint_requirements``): ONE
  exact probe PER declared requirement;
- the probe exchange's ``envelope.endpoint`` (and provider_dataset)
  must MATCH the declared requirement - a stand-in endpoint (e.g.
  ``get_stock_basic`` proving ``industry_taxonomy``, or a calendar
  probe proving ``daily_bar``) is a blocking FAIL, never a PASS;
- an endpoint that cannot be verified as the declared one is
  FAIL-CLOSED (NOT_TESTABLE/FAIL) - no fallback to an unrelated
  endpoint; official alternatives are declared EXPLICITLY as an
  ALTERNATIVE_GROUP in the contract;
- one proof case PER requirement, and the REPORT artifact carries the
  full structured endpoint identity (requirement_id / expected /
  actual endpoint / evidence binding) hash-anchored for approval's
  tamper re-verification (B1-04).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from ashare_state.providers.amazingdata.capability import FORMAL_GATE_CASE_TYPE
from ashare_state.providers.amazingdata.endpoint_requirements import (
    EndpointRequirement,
    endpoint_requirement_case_id,
    endpoint_requirements_for,
)
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.providers.runtime_gates import (
    AuthAccountGate,
    BusinessDataGate,
    CacheMetadataGate,
    FreshnessAsOfGate,
    GateCheck,
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
    "ENDPOINT_PROBE_SPECS",
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
    the executor assembles the full pipeline in the fixed order.

    R4-B1: ``endpoint_requirements`` comes from the Endpoint Requirement
    Contract - the ENDPOINT gate fires one EXACT probe per requirement
    (no caller-chosen stand-in endpoint)."""

    capability: str
    permission_probe: ProbeCaller
    endpoint_requirements: tuple[EndpointRequirement, ...]
    cache_validator: Callable[[], tuple[bool, str]]
    data_as_of: str
    required_as_of: str
    business_fetch: ProbeCaller
    cache_evidence_ref: str = ""
    freshness_evidence_ref: str = ""


class _PersistedProbe:
    """Wraps a ProbeCaller so EVERY fired exchange - success or
    first-class failure - is persisted through the run's RawWriter
    BEFORE the gate verdict is finalized, and the binding is recorded.

    R4-A3.2 P0-01: the recorded binding/persist outcome is consumed
    INSIDE the gate evaluation (see :class:`_PersistedPermissionGate`
    and siblings) - never post hoc after the pipeline finished."""

    def __init__(self, ctx: ProbeContext, probe: ProbeCaller, label: str) -> None:
        self.ctx = ctx
        self.probe = probe
        self.label = label
        self.fired = 0
        self.binding: GateEvidenceIdentity | None = None
        self.persist_error: str = ""
        #: request identity of the last fired exchange (a request id is
        #: NOT persisted evidence - P0-02 - but a downgraded result may
        #: still record it for traceability)
        self.last_request_id: str = ""

    def __call__(self) -> ProviderExchange:
        self.fired += 1
        try:
            exchange = self.probe()
        except ProviderError as exc:
            failure = getattr(exc, "exchange", None)
            if failure is not None:
                self.last_request_id = str(failure.envelope.request_id)
                self._persist(failure)
            raise
        self.last_request_id = str(exchange.envelope.request_id)
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


def _finalize_persisted(result: GateResult, probe: _PersistedProbe) -> GateResult:
    """Fold the persistence outcome INTO the gate evaluation itself
    (R4-A3.2 P0-01 - no post-hoc rewrite after the pipeline finished):

    - exchange persisted -> the result is BOUND to the persisted
      evidence identity (request_id + evidence_uri + evidence_hash);
    - exchange fired but nothing persisted -> an otherwise-PASS gate is
      IMMEDIATELY downgraded to a blocking FAIL right here, so the
      frozen pipeline early-stops and downstream probes never fire
      (structural fail-closed, audit 20260828 P0-01). The request id
      may still be recorded - it is a request identity - but URI/hash
      stay empty: a request id alone is never formal evidence PASS;
    - an already-failing gate keeps its (more specific) reason, with
      the persistence failure appended for auditability.
    """
    binding = probe.binding
    if binding is not None:
        return replace(
            result,
            request_id=binding.request_id,
            evidence_uri=binding.evidence_uri,
            evidence_hash=binding.evidence_hash,
            evidence_ref=binding.evidence_uri,
        )
    if result.status is GateStatus.PASS:
        return replace(
            result,
            status=GateStatus.FAIL,
            reason=(
                "probe exchange succeeded but evidence persistence failed - "
                f"{probe.persist_error or 'no persisted evidence'}; "
                "formal evidence PASS refused (audit R4-A3.2 P0-01)"
            ),
            request_id=probe.last_request_id,
        )
    if probe.persist_error:
        return replace(
            result,
            reason=f"{result.reason} | evidence persistence failed: {probe.persist_error}",
        )
    return result


@dataclass(frozen=True)
class _PersistedPermissionGate(GateCheck):
    """PERMISSION through the formal boundary: fire + persist + verdict
    form ONE atomic gate evaluation (R4-A3.2 P0-01)."""

    probe: _PersistedProbe
    kind = GateKind.PERMISSION

    def evaluate(self) -> GateResult:
        inner = PermissionGate(self.probe).evaluate()
        return _finalize_persisted(inner, self.probe)


@dataclass
class _EndpointProbeOutcome:
    """B1-02/B1-04: the evaluated outcome of ONE endpoint requirement -
    the structured exact-endpoint identity the proof case and the
    REPORT artifact carry (hash-anchored for approval re-verification)."""

    requirement: EndpointRequirement
    status: GateStatus = GateStatus.SKIPPED_BLOCKED
    reason: str = ""
    actual_endpoint: str = ""
    actual_dataset: str = ""
    request_id: str = ""
    binding: GateEvidenceIdentity | None = None


class _ExactEndpointRequirementsGate(GateCheck):
    """ENDPOINT_AVAILABLE through the formal boundary (R4-B1 B1-02).

    One EXACT probe per declared requirement. Each probe evaluation is
    atomic (fire + persist + verdict, R4-A3.2 P0-01 semantics):
    - the exchange's endpoint AND provider_dataset must MATCH the
      declared requirement - a stand-in is a blocking FAIL;
    - persistence failure downgrades to FAIL immediately;
    - a ProviderError (first-class failure exchange) is FAIL.

    Verdict: every REQUIRED requirement PASS and every ALTERNATIVE_GROUP
    satisfied by at least one passing member -> PASS; otherwise FAIL
    (blocking - the frozen pipeline early-stops downstream)."""

    kind = GateKind.ENDPOINT_AVAILABLE

    def __init__(
        self,
        ctx: ProbeContext,
        capability: str,
        requirements: tuple[EndpointRequirement, ...],
        probes: dict[str, _PersistedProbe],
        outcomes: dict[str, _EndpointProbeOutcome],
    ) -> None:
        self.ctx = ctx
        self.capability = capability
        self.requirements = requirements
        self.probes = probes
        self.outcomes = outcomes

    def evaluate(self) -> GateResult:
        fired = 0
        reasons: list[str] = []
        group_members: dict[str, list[bool]] = {}
        first_binding: GateEvidenceIdentity | None = None
        first_request_id = ""

        for req in self.requirements:
            probe = self.probes[req.requirement_id]
            outcome = self._evaluate_one(req, probe)
            self.outcomes[req.requirement_id] = outcome
            fired += probe.fired
            if outcome.binding is not None and first_binding is None:
                first_binding = outcome.binding
                first_request_id = outcome.request_id
            if req.group_id:
                group_members.setdefault(req.group_id, []).append(outcome.status is GateStatus.PASS)
            elif outcome.status is not GateStatus.PASS:
                reasons.append(f"{req.requirement_id}: {outcome.reason}")

        failed_groups = [gid for gid, members in group_members.items() if not any(members)]
        for gid in failed_groups:
            reasons.append(f"alternative group {gid!r} unsatisfied: no member endpoint passed")

        ok = not reasons
        if ok:
            status = GateStatus.PASS
            reason = "; ".join(f"{r.requirement_id}: PASS" for r in self.requirements)
        else:
            status = GateStatus.FAIL
            reason = "; ".join(reasons)[:600]
        return GateResult(
            kind=GateKind.ENDPOINT_AVAILABLE,
            status=status,
            reason=reason,
            request_id=first_request_id,
            evidence_uri=first_binding.evidence_uri if first_binding else "",
            evidence_hash=first_binding.evidence_hash if first_binding else "",
            evidence_ref=first_binding.evidence_uri if first_binding else "",
            provider_calls_fired=fired,
        )

    def _evaluate_one(
        self, req: EndpointRequirement, probe: _PersistedProbe
    ) -> _EndpointProbeOutcome:
        outcome = _EndpointProbeOutcome(requirement=req)
        try:
            exchange = probe()
        except ProviderError as exc:
            failure = getattr(exc, "exchange", None)
            if failure is None:
                outcome.status = GateStatus.FAIL
                outcome.reason = f"probe refused without a first-class exchange: {exc}"[:300]
                outcome.request_id = probe.last_request_id
                outcome.binding = probe.binding
                return outcome
            env = failure.envelope
            outcome.actual_endpoint = str(env.endpoint)
            outcome.actual_dataset = str(env.provider_dataset)
            outcome.request_id = probe.last_request_id
            outcome.binding = probe.binding
            if env.endpoint != req.endpoint or env.provider_dataset != req.provider_dataset:
                outcome.status = GateStatus.FAIL
                outcome.reason = (
                    f"failure exchange endpoint mismatch: expected {req.endpoint} "
                    f"(dataset {req.provider_dataset}), got {env.endpoint} "
                    f"(dataset {env.provider_dataset}) - stand-in endpoints can "
                    "never satisfy a requirement (audit R4-B1 B1-02)"
                )
                return outcome
            outcome.status = GateStatus.FAIL
            outcome.reason = (
                f"{env.endpoint} failed: {env.error_class or 'ERROR'} - "
                "endpoint requirement not proven available"
            )
            return outcome
        env = exchange.envelope
        outcome.actual_endpoint = str(env.endpoint)
        outcome.actual_dataset = str(env.provider_dataset)
        outcome.request_id = probe.last_request_id
        outcome.binding = probe.binding
        if env.endpoint != req.endpoint or env.provider_dataset != req.provider_dataset:
            outcome.status = GateStatus.FAIL
            outcome.reason = (
                f"endpoint mismatch: expected {req.endpoint} "
                f"(dataset {req.provider_dataset}), got {env.endpoint} "
                f"(dataset {env.provider_dataset}) - stand-in endpoints can "
                "never satisfy a requirement (audit R4-B1 B1-02)"
            )
            return outcome
        if probe.binding is None:
            # R4-A3.2 P0-01 (atomic persistence) + B1-02: a request id
            # alone is never formal evidence PASS.
            outcome.status = GateStatus.FAIL
            outcome.reason = (
                "probe exchange succeeded but evidence persistence failed - "
                f"{probe.persist_error or 'no persisted evidence'}; "
                "formal evidence PASS refused (audit R4-A3.2 P0-01)"
            )
            return outcome
        outcome.status = GateStatus.PASS
        outcome.reason = f"{env.endpoint} returned {env.row_count} rows"
        return outcome


@dataclass(frozen=True)
class _PersistedBusinessGate(GateCheck):
    """BUSINESS_DATA through the formal boundary: fire + persist +
    verdict form ONE atomic gate evaluation (R4-A3.2 P0-01)."""

    probe: _PersistedProbe
    kind = GateKind.BUSINESS_DATA

    def evaluate(self) -> GateResult:
        inner = BusinessDataGate(self.probe).evaluate()
        return _finalize_persisted(inner, self.probe)


@dataclass
class _BoundReport:
    """GateReport + per-gate persisted bindings + probe counters +
    per-requirement endpoint outcomes (R4-B1 B1-02/B1-04)."""

    report: GateReport
    bindings: dict[GateKind, GateEvidenceIdentity] = field(default_factory=dict)
    probes: dict[GateKind, _PersistedProbe] = field(default_factory=dict)
    endpoint_outcomes: dict[str, _EndpointProbeOutcome] = field(default_factory=dict)
    endpoint_probes: dict[str, _PersistedProbe] = field(default_factory=dict)


class FormalRuntimeGateExecutor:
    """The ONE formal gate execution boundary (audit R4-A3.1 P0-01).

    Executes a :class:`CapabilityProbePlan` through the frozen
    ``RuntimeGatePipeline`` component; persists every probe exchange via
    the run's RawWriter; binds persisted evidence identities onto the
    gate results; emits the gate-proof SpikeCases (PERMISSION/ENDPOINT/
    BUSINESS + REPORT) consumed by capability approval.

    R4-A3.2 P0-01: fire + persist + verdict is ONE atomic gate
    evaluation per probe gate - a persistence failure blocks DURING
    evaluation, the pipeline early-stops structurally, and downstream
    probes fire ZERO provider calls. The report is NEVER rewritten
    after the pipeline has finished."""

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
        business_probe = _PersistedProbe(self.ctx, plan.business_fetch, "BUSINESS")

        # R4-B1 B1-02: one EXACT persisted probe per declared endpoint
        # requirement - the probe factories come from the static
        # ENDPOINT_PROBE_SPECS table keyed by requirement_id, so the
        # gate can never be handed a caller-chosen stand-in endpoint.
        requirements = plan.endpoint_requirements
        endpoint_probes: dict[str, _PersistedProbe] = {}
        endpoint_outcomes: dict[str, _EndpointProbeOutcome] = {}
        for req in requirements:
            factory = ENDPOINT_PROBE_SPECS.get(req.requirement_id)
            if factory is None:
                msg = (
                    f"formal gate boundary: no exact probe declared for "
                    f"requirement {req.requirement_id!r} - every declared "
                    "endpoint requirement MUST have a probe factory "
                    "(audit R4-B1 B1-02/B1-05)"
                )
                raise FormalGateProofError(msg)

            def _bound_probe(
                f: Callable[[ProbeContext], ProviderExchange] = factory,
            ) -> ProviderExchange:
                return f(self.ctx)

            endpoint_probes[req.requirement_id] = _PersistedProbe(
                self.ctx,
                _bound_probe,
                f"ENDPOINT:{req.requirement_id}",
            )

        # R4-A3.2 P0-01: the probe gates are the ATOMIC persisted gates -
        # a persistence failure becomes a blocking FAIL DURING gate
        # evaluation, so the frozen pipeline early-stops and downstream
        # probes fire ZERO provider calls. There is NO post-hoc rewrite
        # after the pipeline has finished (that would report an early
        # stop that never structurally happened).
        pipeline = RuntimeGatePipeline(
            [
                AuthAccountGate(
                    lifecycle=lifecycle,
                    account_profile_id=account_profile_id,
                    profile_parsed=profile_parsed,
                    require_production_identity=require_production,
                    frozen_production_id=frozen_id,
                ),
                _PersistedPermissionGate(permission_probe),
                _ExactEndpointRequirementsGate(
                    self.ctx,
                    plan.capability,
                    requirements,
                    endpoint_probes,
                    endpoint_outcomes,
                ),
                CacheMetadataGate(plan.cache_validator, evidence_ref=plan.cache_evidence_ref),
                FreshnessAsOfGate(
                    data_as_of=plan.data_as_of,
                    required_as_of=plan.required_as_of,
                    evidence_ref=plan.freshness_evidence_ref,
                ),
                _PersistedBusinessGate(business_probe),
            ]
        )
        report = pipeline.evaluate()

        probes = {
            GateKind.PERMISSION: permission_probe,
            GateKind.BUSINESS_DATA: business_probe,
        }
        bindings: dict[GateKind, GateEvidenceIdentity] = {}
        for result in report.results:
            if result.kind is GateKind.ENDPOINT_AVAILABLE:
                continue
            probe = probes.get(result.kind)
            if probe is None:
                continue
            if probe.binding is not None:
                bindings[result.kind] = probe.binding
            elif result.status is GateStatus.PASS:
                # Defensive fail-closed (should be unreachable): the
                # persisted-gate subclass MUST have downgraded this
                # DURING evaluation. Refuse loudly instead of rewriting
                # the report post hoc (audit R4-A3.2 P0-01).
                raise FormalGateProofError(
                    f"{result.kind.value} PASSED without persisted evidence - "
                    "the persisted-gate evaluation contract was violated"
                )
        endpoint_result = next(
            (r for r in report.results if r.kind is GateKind.ENDPOINT_AVAILABLE), None
        )
        if endpoint_result is not None and endpoint_result.status is GateStatus.PASS:
            # the exact-requirements gate guarantees: PASS means every
            # REQUIRED outcome bound persisted evidence (mismatch /
            # persistence failure are FAILs during evaluation)
            unbound = [
                req.requirement_id
                for req in requirements
                if req.mode.value == "REQUIRED"
                and (
                    endpoint_outcomes.get(req.requirement_id) is None
                    or endpoint_outcomes[req.requirement_id].binding is None
                )
            ]
            if unbound:
                raise FormalGateProofError(
                    f"ENDPOINT_AVAILABLE PASSED with unbound requirements {unbound} - "
                    "the exact-endpoint evaluation contract was violated"
                )
        bound_report = _BoundReport(
            report=report,
            bindings=bindings,
            probes=probes,
            endpoint_outcomes=endpoint_outcomes,
            endpoint_probes=endpoint_probes,
        )
        self._emit_cases(plan, bound_report)
        return bound_report

    # -------------------------------------------------------------- cases
    def _emit_cases(self, plan: CapabilityProbePlan, bound: _BoundReport) -> None:
        as_of = str(self.ctx.as_of_date)
        for kind in (GateKind.PERMISSION, GateKind.BUSINESS_DATA):
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
        # R4-B1: one proof case PER endpoint requirement (B1-04) - the
        # case carries the exact endpoint identity (expected/actual
        # endpoint + persisted evidence binding); SKIPPED requirements
        # (pipeline early stop) emit no case, which blocks approval.
        for req in plan.endpoint_requirements:
            outcome = bound.endpoint_outcomes.get(req.requirement_id)
            if outcome is None or outcome.status is GateStatus.SKIPPED_BLOCKED:
                continue
            binding = outcome.binding
            meta = (
                {
                    "evidence_ref": binding.evidence_uri,
                    "content_hash": binding.evidence_hash,
                }
                if binding is not None
                else {}
            )
            self.ctx.case(
                case_id=endpoint_requirement_case_id(req),
                case_type=FORMAL_GATE_CASE_TYPE,
                security="GATE",
                provider_symbol="GATE",
                trade_date=as_of,
                expected=(
                    f"endpoint {req.endpoint} (dataset {req.provider_dataset}) "
                    f"available for {req.capability}"
                    + (f" [group {req.group_id}]" if req.group_id else "")
                ),
                actual=(
                    f"{outcome.status.value}: {outcome.reason} | "
                    f"expected_endpoint={req.endpoint} "
                    f"actual_endpoint={outcome.actual_endpoint} "
                    + (
                        f"request_id={binding.request_id} "
                        f"evidence_uri={binding.evidence_uri} "
                        f"evidence_hash={binding.evidence_hash[:16]}"
                        if binding is not None
                        else "no persisted evidence binding"
                    )
                )[:400],
                result=_gate_status_to_case_result(outcome.status),
                evidence_meta=meta,
                reason_code=f"GATE_ENDPOINT_{outcome.status.value}",
                validator_id="formal_endpoint_requirement_v1",
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
            # R4-B1 B1-04: the structured exact-endpoint identity of every
            # declared requirement - hash-anchored by the REPORT case's
            # evidence_hash, consumed by capability approval for the
            # mismatch/tamper re-verification (fail closed).
            "endpoint_requirements": [
                {
                    "requirement_id": req.requirement_id,
                    "capability": req.capability,
                    "expected_endpoint": req.endpoint,
                    "actual_endpoint": outcome.actual_endpoint,
                    "provider_dataset": req.provider_dataset,
                    "actual_dataset": outcome.actual_dataset,
                    "mode": req.mode.value,
                    "group_id": req.group_id,
                    "status": outcome.status.value,
                    "reason": outcome.reason,
                    "request_id": outcome.request_id,
                    "evidence_uri": outcome.binding.evidence_uri if outcome.binding else "",
                    "evidence_hash": outcome.binding.evidence_hash if outcome.binding else "",
                }
                for req in plan.endpoint_requirements
                for outcome in (bound.endpoint_outcomes.get(req.requirement_id),)
                if outcome is not None
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
    business_fetch: Callable[[], ProviderExchange],
    cache_validator: Callable[[], tuple[bool, str]] | None = None,
) -> CapabilityProbePlan:
    """Assemble a complete plan - every gate is mandatory (no opt-out).

    R4-B1: the endpoint requirements come from the CONTRACT
    (``endpoint_requirements_for``) - never from caller choice."""
    as_of = str(ctx.as_of_date)
    return CapabilityProbePlan(
        capability=capability,
        permission_probe=lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
        endpoint_requirements=endpoint_requirements_for(capability),
        cache_validator=cache_validator or _ok_validator,
        data_as_of=as_of,
        required_as_of=as_of,
        business_fetch=business_fetch,
        cache_evidence_ref="run-bound rule book" if cache_validator else "local prerequisites",
        freshness_evidence_ref=f"run as-of {as_of}",
    )


def _factory(
    capability: str,
    business_fetch: Callable[[ProbeContext], ProviderExchange],
    rule_bound: bool = False,
) -> Callable[[ProbeContext], CapabilityProbePlan]:
    def build(ctx: ProbeContext) -> CapabilityProbePlan:
        return _plan(
            capability,
            ctx,
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


def _probe_bj_code_mapping(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_bj_code_mapping_exchange(["430047.BJ"])


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


def _probe_right_issue(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_right_issue_exchange(["600519.SH"])


def _probe_equity_structure(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_equity_structure_exchange(["600519.SH"])


def _probe_industry_base_info(ctx: ProbeContext) -> ProviderExchange:
    return ctx.target.get_industry_base_info_exchange(["600519.SH"])


#: R4-B1 B1-02: the EXACT probe factory for every declared endpoint
#: requirement (keyed by requirement_id - the same contract the
#: ENDPOINT gate and capability approval consume). A probe whose
#: exchange envelope does not match the declared endpoint/dataset is a
#: blocking FAIL at evaluation time; there is deliberately NO way to
#: hand the gate a stand-in endpoint.
#: R4-B1.1: security_master:BaseData.get_code_list removed - the
#: current-snapshot listing is a NON-APPROVAL surface (survivorship is
#: proven by the HISTORICAL endpoint, audit 20260830 P0-01).
ENDPOINT_PROBE_SPECS: dict[str, Callable[[ProbeContext], ProviderExchange]] = {
    "trade_calendar:BaseData.get_calendar": _probe_calendar,
    "security_master:BaseData.get_hist_code_list": _probe_hist_code_list,
    "code_mapping_bj:InfoData.get_bj_code_mapping": _probe_bj_code_mapping,
    "daily_bar:MarketData.query_kline": _probe_kline_600519,
    "security_status_history:InfoData.get_history_stock_status": _probe_status_history,
    "adj_factor:BaseData.get_adj_factor": _probe_adj_factor,
    "corporate_action:InfoData.get_dividend": _probe_dividend,
    "corporate_action:InfoData.get_right_issue": _probe_right_issue,
    "equity_structure:InfoData.get_equity_structure": _probe_equity_structure,
    "industry_taxonomy:InfoData.get_industry_base_info": _probe_industry_base_info,
    "index_daily:MarketData.query_kline": _probe_kline_index,
}


#: per-capability formal gate plans (R4-A3.1 P0-01 + R4-B1 B1-02). The
#: endpoint requirements are consumed from the contract - NOT chosen
#: here; the business fetch remains the capability's own business
#: exchange (semantic validation is the B2-B7 probes' job; this
#: boundary proves the GATE CHAIN + exact endpoint identities).
GATE_PLAN_SPECS: dict[str, Callable[[ProbeContext], CapabilityProbePlan]] = {
    "trade_calendar": _factory("trade_calendar", _probe_calendar),
    "security_master": _factory("security_master", _probe_hist_code_list),
    "code_mapping_bj": _factory("code_mapping_bj", _probe_bj_code_mapping),
    "daily_bar": _factory("daily_bar", _probe_kline_600519),
    "security_status_history": _factory(
        "security_status_history",
        _probe_status_history,
        rule_bound=True,
    ),
    "adj_factor": _factory("adj_factor", _probe_adj_factor),
    "corporate_action": _factory("corporate_action", _probe_dividend),
    "equity_structure": _factory("equity_structure", _probe_equity_structure),
    "industry_taxonomy": _factory("industry_taxonomy", _probe_industry_base_info),
    "index_daily": _factory("index_daily", _probe_kline_index),
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
