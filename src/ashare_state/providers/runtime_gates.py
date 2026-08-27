"""Provider runtime gate separation + early-stop pipeline (R4-A3
A3-02/A3-03, audit 20260826 section 7.2).

Different failure NATURES are DIFFERENT gates - never folded into one
"provider unavailable":

    AUTH_ACCOUNT        login/session state + account profile validity
    PERMISSION          broker-side entitlement (real probe exchange)
    ENDPOINT_AVAILABLE  the endpoint answers (real probe exchange)
    CACHE_METADATA      required local metadata/cache validity (NO call)
    FRESHNESS_ASOF      data as-of vs required as-of (NO call)
    BUSINESS_DATA       the business fetch itself (real exchange)

Every gate result carries an explicit status, an explicit blocking
reason and a traceable evidence ref. The pipeline is FAIL-CLOSED and
early-stops: once a gate FAILs (or is NOT_TESTABLE - unprovable is
blocking), later dependent gates are marked SKIPPED_BLOCKED and their
provider functions are NEVER invoked - proven by the per-gate
``provider_calls_fired`` counter, not by eyeballing the final exception.

Non-maskability rules encoded by the ordering + early-stop:
- a cache hit can never mask a permission failure (PERMISSION evaluates
  first; CACHE_METADATA after it is skipped when permission failed);
- a cached result can never replace the formal endpoint proof
  (ENDPOINT_AVAILABLE fires a REAL probe exchange);
- insufficient freshness can never degrade into "data exists -> PASS"
  (FRESHNESS_ASOF FAIL blocks BUSINESS_DATA from even firing).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState

__all__ = [
    "AuthAccountGate",
    "BusinessDataGate",
    "CacheMetadataGate",
    "EndpointAvailableGate",
    "FreshnessAsOfGate",
    "GateCheck",
    "GateKind",
    "GateReport",
    "GateResult",
    "GateStatus",
    "PermissionGate",
    "RuntimeGatePipeline",
]


class GateKind(StrEnum):
    AUTH_ACCOUNT = "AUTH_ACCOUNT"
    PERMISSION = "PERMISSION"
    ENDPOINT_AVAILABLE = "ENDPOINT_AVAILABLE"
    CACHE_METADATA = "CACHE_METADATA"  # CACHE / LOCAL_METADATA
    FRESHNESS_ASOF = "FRESHNESS_ASOF"  # FRESHNESS / ASOF
    BUSINESS_DATA = "BUSINESS_DATA"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    #: unprovable is BLOCKING (fail-closed): a NOT_TESTABLE prerequisite
    #: still prevents downstream dependent gates from firing
    NOT_TESTABLE = "NOT_TESTABLE"
    #: the gate never evaluated - an upstream prerequisite failed and the
    #: early-stop pipeline skipped it (provider function NOT invoked)
    SKIPPED_BLOCKED = "SKIPPED_BLOCKED"


@dataclass(frozen=True)
class GateResult:
    """One gate's verdict: explicit status + reason + traceable evidence.

    ``provider_calls_fired`` counts the REAL provider exchanges this gate
    executed (0 for pure-local gates, 1+ for probe/business gates) - the
    early-stop proof uses these counters, not the final exception.

    R4-A3.1 P0-02 (audit 20260827): persisted-evidence identity is
    EXPLICIT and split - a request id is a request identity, never a
    persisted-evidence identity. Probe gates that executed through the
    formal boundary additionally carry the RawWriter persisted evidence
    URI (the .meta.json anchor) and its content hash; a PASS without
    them is not formal evidence PASS."""

    kind: GateKind
    status: GateStatus
    reason: str = ""
    evidence_ref: str = ""
    provider_calls_fired: int = 0
    #: provider exchange request identity (request_id of the fired exchange)
    request_id: str = ""
    #: RawWriter persisted evidence URI (.meta.json anchor) - NOT a
    #: request id; empty for local gates that fire no exchange
    evidence_uri: str = ""
    #: sha256 of the persisted evidence bytes (the meta anchor)
    evidence_hash: str = ""

    @property
    def blocking(self) -> bool:
        return self.status in (GateStatus.FAIL, GateStatus.NOT_TESTABLE)

    @property
    def has_persisted_evidence(self) -> bool:
        """True when this result is bound to immutable persisted evidence
        (P0-02: request_id alone is NOT persisted evidence)."""
        return bool(self.evidence_uri and self.evidence_hash)


@dataclass(frozen=True)
class GateReport:
    """The pipeline's outcome over an ordered gate sequence."""

    results: tuple[GateResult, ...]
    early_stopped: bool = False
    blocked_by: GateKind | None = None

    @property
    def all_passed(self) -> bool:
        return all(r.status is GateStatus.PASS for r in self.results)

    def status_of(self, kind: GateKind) -> GateStatus:
        for result in self.results:
            if result.kind is kind:
                return result.status
        raise KeyError(kind)

    def total_provider_calls_fired(self) -> int:
        return sum(r.provider_calls_fired for r in self.results)


#: a probe caller fires ONE real provider exchange and either returns it
#: (success) or raises a ProviderError carrying ``.exchange`` (failure) -
#: the CR-1.1 first-class failure contract.
ProbeCaller = Callable[[], ProviderExchange]


class GateCheck:
    """Base: a single gate. Subclasses implement :meth:`evaluate`."""

    kind: GateKind = GateKind.BUSINESS_DATA  # overridden by subclasses

    def evaluate(self) -> GateResult:  # pragma: no cover - interface
        raise NotImplementedError


def _exchange_outcome(exchange: ProviderExchange) -> tuple[GateStatus, str, str]:
    """Map a persisted exchange to (status, reason, evidence_ref)."""
    env = exchange.envelope
    if env.status == "OK":
        return (
            GateStatus.PASS,
            f"{env.endpoint} returned {env.row_count} rows",
            str(env.request_id),
        )
    return (
        GateStatus.FAIL,
        f"{env.endpoint} failed: {env.error_class or 'ERROR'}",
        str(env.request_id),
    )


def _fire_probe(kind: GateKind, probe: ProbeCaller) -> GateResult:
    """Fire ONE real provider exchange through the explicit boundary and
    fold it into a gate result (success or first-class failure)."""
    try:
        exchange = probe()
    except ProviderError as exc:
        failure = getattr(exc, "exchange", None)
        if failure is not None:
            status, reason, ref = _exchange_outcome(failure)
            return GateResult(
                kind=kind,
                status=status,
                reason=reason,
                evidence_ref=ref,
                provider_calls_fired=1,
            )
        return GateResult(
            kind=kind,
            status=GateStatus.FAIL,
            reason=f"probe failed before an exchange was created: {exc}",
            evidence_ref="",
            provider_calls_fired=0,
        )
    status, reason, ref = _exchange_outcome(exchange)
    return GateResult(
        kind=kind,
        status=status,
        reason=reason,
        evidence_ref=ref,
        provider_calls_fired=1,
    )


@dataclass(frozen=True)
class AuthAccountGate(GateCheck):
    """AUTH/ACCOUNT: the session is alive and the account profile is
    usable. Pure state inspection - fires NO provider call.

    R4-A3.1 P0-03 (audit 20260827): when ``require_production_identity``
    is set (production proof input), the account must POSITIVELY match
    the frozen production identity - an allowlist, not a blacklist.
    With no frozen identity configured the gate is NOT_TESTABLE (the
    production truth is unprovable - fail closed); a mismatch FAILs."""

    lifecycle: SdkLifecycle
    account_profile_id: str = "UNKNOWN"
    profile_parsed: bool = False
    kind = GateKind.AUTH_ACCOUNT
    #: positive production identity requirement (production proof input)
    require_production_identity: bool = False
    #: the frozen production profile id to exact-match against
    frozen_production_id: str = ""

    def evaluate(self) -> GateResult:
        state = self.lifecycle.state
        if state is SdkLifecycleState.SESSION_READY or self.lifecycle.session_alive:
            if not self.profile_parsed:
                return GateResult(
                    kind=self.kind,
                    status=GateStatus.NOT_TESTABLE,
                    reason=(
                        "login succeeded but the logon profile was not parsed - "
                        "account identity unprovable (audit P1-08)"
                    ),
                    evidence_ref=self.account_profile_id,
                )
            if self.require_production_identity:
                # P0-03: positive identity - "not Trial" is NOT "Production"
                if not self.frozen_production_id:
                    return GateResult(
                        kind=self.kind,
                        status=GateStatus.NOT_TESTABLE,
                        reason=(
                            "no frozen production identity configured - "
                            "production account truth unprovable (fail closed, "
                            "audit R4-A3.1 P0-03)"
                        ),
                        evidence_ref=self.account_profile_id,
                    )
                if self.account_profile_id != self.frozen_production_id:
                    return GateResult(
                        kind=self.kind,
                        status=GateStatus.FAIL,
                        reason=(
                            f"account {self.account_profile_id!r} is not the frozen "
                            f"production identity {self.frozen_production_id!r} - "
                            "positive exact match required (audit R4-A3.1 P0-03)"
                        ),
                        evidence_ref=self.account_profile_id,
                    )
            return GateResult(
                kind=self.kind,
                status=GateStatus.PASS,
                reason=f"session {state.value}; account {self.account_profile_id}",
                evidence_ref=self.account_profile_id,
            )
        return GateResult(
            kind=self.kind,
            status=GateStatus.FAIL,
            reason=(
                f"lifecycle state {state.value}"
                + (f" ({self.lifecycle.terminal_reason})" if self.lifecycle.terminal_reason else "")
            ),
            evidence_ref=self.lifecycle.terminal_evidence_ref,
        )


@dataclass(frozen=True)
class PermissionGate(GateCheck):
    """PERMISSION: broker-side entitlement, proven by a REAL probe
    exchange (a cached entitlement can never substitute the formal
    proof). Fires exactly one provider call."""

    probe: ProbeCaller
    kind = GateKind.PERMISSION

    def evaluate(self) -> GateResult:
        result = _fire_probe(self.kind, self.probe)
        if result.status is GateStatus.PASS and "entitlement denial" in result.reason:
            # defensive: an OK envelope cannot carry a denial signature
            return GateResult(kind=self.kind, status=GateStatus.FAIL, reason=result.reason)
        return result


@dataclass(frozen=True)
class EndpointAvailableGate(GateCheck):
    """ENDPOINT_AVAILABLE: the endpoint answers - proven by a REAL probe
    exchange (a cache hit is never a substitute)."""

    probe: ProbeCaller
    kind = GateKind.ENDPOINT_AVAILABLE

    def evaluate(self) -> GateResult:
        return _fire_probe(self.kind, self.probe)


@dataclass(frozen=True)
class CacheMetadataGate(GateCheck):
    """CACHE/LOCAL_METADATA: required local metadata validity. Pure local
    validation - fires NO provider call, and can never mask an upstream
    permission failure (pipeline ordering + early stop)."""

    validator: Callable[[], tuple[bool, str]]
    evidence_ref: str = ""
    kind = GateKind.CACHE_METADATA

    def evaluate(self) -> GateResult:
        ok, detail = self.validator()
        return GateResult(
            kind=self.kind,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            reason=detail,
            evidence_ref=self.evidence_ref,
        )


@dataclass(frozen=True)
class FreshnessAsOfGate(GateCheck):
    """FRESHNESS/ASOF: data as-of vs required as-of. Staleness FAILS -
    never degrades into 'data exists -> PASS'. Pure comparison - fires
    NO provider call."""

    data_as_of: str
    required_as_of: str
    evidence_ref: str = ""
    kind = GateKind.FRESHNESS_ASOF

    def evaluate(self) -> GateResult:
        if not self.data_as_of:
            return GateResult(
                kind=self.kind,
                status=GateStatus.NOT_TESTABLE,
                reason="data as-of unknown - freshness unprovable",
                evidence_ref=self.evidence_ref,
            )
        if self.data_as_of < self.required_as_of:
            return GateResult(
                kind=self.kind,
                status=GateStatus.FAIL,
                reason=(
                    f"stale: data as-of {self.data_as_of} < required "
                    f"{self.required_as_of} - business-truth PASS is refused"
                ),
                evidence_ref=self.evidence_ref,
            )
        return GateResult(
            kind=self.kind,
            status=GateStatus.PASS,
            reason=f"data as-of {self.data_as_of} satisfies required {self.required_as_of}",
            evidence_ref=self.evidence_ref,
        )


@dataclass(frozen=True)
class BusinessDataGate(GateCheck):
    """BUSINESS_DATA: the business fetch itself - only reachable when
    every upstream gate passed (the pipeline guarantees it)."""

    fetch: ProbeCaller
    kind = GateKind.BUSINESS_DATA

    def evaluate(self) -> GateResult:
        return _fire_probe(self.kind, self.fetch)


class RuntimeGatePipeline:
    """Sequential fail-closed evaluation with EARLY STOP.

    On the first blocking gate (FAIL or NOT_TESTABLE) every later check
    is marked SKIPPED_BLOCKED and its ``evaluate`` is NEVER called - the
    provider functions of dependent gates cannot fire. The proof is
    structural: results of skipped gates carry provider_calls_fired=0
    and the caller can additionally assert their probe counters."""

    def __init__(self, checks: Sequence[GateCheck]) -> None:
        self.checks: tuple[GateCheck, ...] = tuple(checks)

    def evaluate(self) -> GateReport:
        results: list[GateResult] = []
        blocked_by: GateKind | None = None
        for check in self.checks:
            if blocked_by is not None:
                results.append(
                    GateResult(
                        kind=check.kind,
                        status=GateStatus.SKIPPED_BLOCKED,
                        reason=f"early stop: blocked by {blocked_by.value}",
                    )
                )
                continue
            result = check.evaluate()
            results.append(result)
            if result.blocking:
                blocked_by = result.kind
        return GateReport(
            results=tuple(results),
            early_stopped=blocked_by is not None,
            blocked_by=blocked_by,
        )
