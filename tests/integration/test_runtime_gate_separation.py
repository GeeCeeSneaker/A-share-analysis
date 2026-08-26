"""R4-A3 A3-02: permission / cache / freshness gate separation tests
(audit 20260826 section 7.2).

Different failure natures are DIFFERENT gates with explicit status /
blocking reason / traceable evidence. Non-maskability rules:

- permission failure is never masked by a cache hit (PERMISSION evaluates
  first; CACHE_METADATA is skipped after the permission FAIL);
- a cached result never replaces the formal endpoint proof
  (ENDPOINT_AVAILABLE fires a REAL probe exchange);
- insufficient freshness never degrades into "data exists -> PASS"
  (FRESHNESS_ASOF FAIL blocks BUSINESS_DATA from firing).

Early-stop proof: after a blocking gate, downstream checks report
SKIPPED_BLOCKED with provider_calls_fired == 0 - proven by counters,
not by the final exception.
"""

from __future__ import annotations

from typing import Any

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState
from ashare_state.providers.runtime_gates import (
    AuthAccountGate,
    BusinessDataGate,
    CacheMetadataGate,
    EndpointAvailableGate,
    FreshnessAsOfGate,
    GateKind,
    GateStatus,
    PermissionGate,
    RuntimeGatePipeline,
)


class _CountingProbe:
    """A probe caller that fires REAL provider exchanges (success or
    first-class failure) and counts how many times it fired."""

    def __init__(self, *, fail_with: Exception | None = None, payload: Any = None) -> None:
        self.fired = 0
        self._fail_with = fail_with
        self._payload = payload if payload is not None else ["600519.SH"]

    def __call__(self) -> ProviderExchange:
        self.fired += 1
        if self._fail_with is not None:
            env = RawEnvelope(
                provider="amazingdata",
                provider_dataset="probe",
                endpoint="Fake.probe",
                request_id=f"req-fail-{self.fired}",
                status="ERROR",
                error_class=type(self._fail_with).__name__,
            )
            error = ProviderPermissionError(str(self._fail_with))
            error.exchange = ProviderExchange(envelope=env, payload=None)
            raise error
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="probe",
            endpoint="Fake.probe",
            request_id=f"req-ok-{self.fired}",
            status="OK",
            row_count=1,
        )
        return ProviderExchange(envelope=env, payload=self._payload)


def _ready_lifecycle() -> SdkLifecycle:
    lc = SdkLifecycle()
    lc.transition(SdkLifecycleState.SESSION_READY, reason="test login")
    return lc


class TestGateResults:
    def test_permission_pass_carries_exchange_evidence(self):
        probe = _CountingProbe()
        result = PermissionGate(probe).evaluate()
        assert result.status is GateStatus.PASS
        assert result.evidence_ref.startswith("req-ok-")
        assert result.provider_calls_fired == 1

    def test_permission_fail_carries_failure_exchange_evidence(self):
        probe = _CountingProbe(fail_with=ProviderPermissionError("entitlement denied"))
        result = PermissionGate(probe).evaluate()
        assert result.status is GateStatus.FAIL
        assert result.evidence_ref.startswith("req-fail-")
        assert result.provider_calls_fired == 1
        assert result.blocking

    def test_auth_account_pass(self):
        result = AuthAccountGate(
            lifecycle=_ready_lifecycle(), account_profile_id="ACCOUNT_x", profile_parsed=True
        ).evaluate()
        assert result.status is GateStatus.PASS

    def test_auth_account_unparsed_profile_not_testable(self):
        """Login ok but profile unparsed: the gate is NOT_TESTABLE
        (unprovable), which is BLOCKING - never a silent PASS."""
        result = AuthAccountGate(
            lifecycle=_ready_lifecycle(),
            account_profile_id="UNKNOWN",
            profile_parsed=False,
        ).evaluate()
        assert result.status is GateStatus.NOT_TESTABLE
        assert result.blocking

    def test_auth_account_terminal_lifecycle_fails(self):
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.AUTH_REJECTED, reason="bad credentials")
        result = AuthAccountGate(lifecycle=lc).evaluate()
        assert result.status is GateStatus.FAIL
        assert "AUTH_REJECTED" in result.reason
        assert "bad credentials" in result.reason

    def test_freshness_stale_fails(self):
        result = FreshnessAsOfGate(
            data_as_of="20260820", required_as_of="20260825", evidence_ref="meta.json"
        ).evaluate()
        assert result.status is GateStatus.FAIL
        assert "stale" in result.reason

    def test_freshness_unknown_as_of_not_testable(self):
        result = FreshnessAsOfGate(data_as_of="", required_as_of="20260825").evaluate()
        assert result.status is GateStatus.NOT_TESTABLE

    def test_freshness_current_passes(self):
        result = FreshnessAsOfGate(data_as_of="20260825", required_as_of="20260825").evaluate()
        assert result.status is GateStatus.PASS

    def test_cache_metadata_fail_is_local(self):
        gate = CacheMetadataGate(lambda: (False, "security master missing"), evidence_ref="db")
        result = gate.evaluate()
        assert result.status is GateStatus.FAIL
        assert result.provider_calls_fired == 0


class TestPipelineEarlyStop:
    def _full_pipeline(
        self,
        *,
        permission_probe: _CountingProbe,
        endpoint_probe: _CountingProbe,
        business_probe: _CountingProbe,
        cache_ok: bool = True,
        data_as_of: str = "20260825",
    ) -> RuntimeGatePipeline:
        return RuntimeGatePipeline(
            [
                AuthAccountGate(
                    lifecycle=_ready_lifecycle(),
                    account_profile_id="ACCOUNT_x",
                    profile_parsed=True,
                ),
                PermissionGate(permission_probe),
                EndpointAvailableGate(endpoint_probe),
                CacheMetadataGate(
                    lambda: (cache_ok, "security master ok" if cache_ok else "missing"),
                    evidence_ref="db",
                ),
                FreshnessAsOfGate(data_as_of=data_as_of, required_as_of="20260825"),
                BusinessDataGate(business_probe),
            ]
        )

    def test_all_pass_business_fires_once(self):
        permission = _CountingProbe()
        endpoint = _CountingProbe()
        business = _CountingProbe()
        report = self._full_pipeline(
            permission_probe=permission, endpoint_probe=endpoint, business_probe=business
        ).evaluate()
        assert report.all_passed
        assert not report.early_stopped
        assert report.total_provider_calls_fired() == 3
        assert permission.fired == 1
        assert endpoint.fired == 1
        assert business.fired == 1

    def test_permission_fail_blocks_dependent_business_fetch(self):
        """The audit's core scenario: permission denied -> the dependent
        business fetch MUST NOT fire (probe counter == 0), and the
        endpoint/permission gates are the ONLY provider calls made."""
        permission = _CountingProbe(fail_with=ProviderPermissionError("denied"))
        endpoint = _CountingProbe()
        business = _CountingProbe()
        report = self._full_pipeline(
            permission_probe=permission, endpoint_probe=endpoint, business_probe=business
        ).evaluate()
        assert report.early_stopped
        assert report.blocked_by is GateKind.PERMISSION
        assert report.status_of(GateKind.PERMISSION) is GateStatus.FAIL
        assert report.status_of(GateKind.ENDPOINT_AVAILABLE) is GateStatus.SKIPPED_BLOCKED
        assert report.status_of(GateKind.BUSINESS_DATA) is GateStatus.SKIPPED_BLOCKED
        # counter proof: only the permission probe fired
        assert permission.fired == 1
        assert endpoint.fired == 0
        assert business.fired == 0
        assert report.total_provider_calls_fired() == 1

    def test_cache_hit_cannot_mask_permission_failure(self):
        """Non-maskability: the cache is HEALTHY, but permission FAILED -
        the overall result is still blocked at PERMISSION (the cache gate
        never even evaluates)."""
        permission = _CountingProbe(fail_with=ProviderPermissionError("denied"))
        report = self._full_pipeline(
            permission_probe=permission,
            endpoint_probe=_CountingProbe(),
            business_probe=_CountingProbe(),
            cache_ok=True,  # healthy cache must NOT mask the denial
        ).evaluate()
        assert report.blocked_by is GateKind.PERMISSION
        assert report.status_of(GateKind.CACHE_METADATA) is GateStatus.SKIPPED_BLOCKED
        assert not report.all_passed

    def test_freshness_fail_blocks_business_pass(self):
        """Stale data NEVER degrades into 'data exists -> PASS': the
        freshness FAIL blocks the business gate from firing."""
        business = _CountingProbe()
        report = self._full_pipeline(
            permission_probe=_CountingProbe(),
            endpoint_probe=_CountingProbe(),
            business_probe=business,
            data_as_of="20260801",  # stale
        ).evaluate()
        assert report.blocked_by is GateKind.FRESHNESS_ASOF
        assert report.status_of(GateKind.BUSINESS_DATA) is GateStatus.SKIPPED_BLOCKED
        assert business.fired == 0  # business fetch never fired

    def test_cache_metadata_fail_blocks_dependent_probe(self):
        """Required local metadata invalid -> dependent probes do not fire."""
        endpoint = _CountingProbe()
        business = _CountingProbe()
        report = self._full_pipeline(
            permission_probe=_CountingProbe(),
            endpoint_probe=endpoint,
            business_probe=business,
            cache_ok=False,
        ).evaluate()
        assert report.blocked_by is GateKind.CACHE_METADATA
        assert endpoint.fired == 1  # endpoint probe already fired (ordering)
        assert business.fired == 0
        assert report.status_of(GateKind.BUSINESS_DATA) is GateStatus.SKIPPED_BLOCKED

    def test_endpoint_failure_blocks_business(self):
        endpoint = _CountingProbe(fail_with=ProviderPermissionError("endpoint dead"))
        business = _CountingProbe()
        report = self._full_pipeline(
            permission_probe=_CountingProbe(),
            endpoint_probe=endpoint,
            business_probe=business,
        ).evaluate()
        assert report.blocked_by is GateKind.ENDPOINT_AVAILABLE
        assert business.fired == 0

    def test_not_testable_auth_blocks_everything(self):
        """Unprovable auth (profile unparsed) is BLOCKING: NO provider
        call fires at all."""
        permission = _CountingProbe()
        report = RuntimeGatePipeline(
            [
                AuthAccountGate(
                    lifecycle=_ready_lifecycle(),
                    account_profile_id="UNKNOWN",
                    profile_parsed=False,
                ),
                PermissionGate(permission),
                BusinessDataGate(_CountingProbe()),
            ]
        ).evaluate()
        assert report.blocked_by is GateKind.AUTH_ACCOUNT
        assert report.status_of(GateKind.AUTH_ACCOUNT) is GateStatus.NOT_TESTABLE
        assert permission.fired == 0
        assert report.total_provider_calls_fired() == 0

    def test_every_gate_result_carries_reason_and_evidence(self):
        """Each result is auditable: explicit status + blocking reason +
        traceable evidence ref (never a bare boolean)."""
        report = self._full_pipeline(
            permission_probe=_CountingProbe(fail_with=ProviderPermissionError("denied")),
            endpoint_probe=_CountingProbe(),
            business_probe=_CountingProbe(),
        ).evaluate()
        for result in report.results:
            assert result.status
            if result.status is GateStatus.FAIL:
                assert result.reason
                assert result.evidence_ref
            if result.status is GateStatus.SKIPPED_BLOCKED:
                assert "early stop" in result.reason
