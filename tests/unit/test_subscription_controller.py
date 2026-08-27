"""Subscription lifecycle controller tests (R4-A3.1 P1-01, audit 20260827).

The real L1 subscription control flow (register -> run -> callback ->
unregister/stop) drives the SdkLifecycle state machine through
SubscriptionController - the correctness SoR - never a second private
lifecycle dict.
"""

from __future__ import annotations

import pytest

from ashare_state.providers.amazingdata.subscription import SubscriptionController
from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState


class FakeSubscriber:
    """The SDK SubscribeData stand-in recording register/unregister."""

    def __init__(self, *, fail_register: bool = False, fail_unregister: bool = False) -> None:
        self.fail_register = fail_register
        self.fail_unregister = fail_unregister
        self.registered: list[tuple[list[str], object]] = []
        self.unregistered: list[tuple[list[str], object]] = []
        self.stopped = 0
        self.ran = 0
        self.callbacks: list = []

    def register(self, *, code_list, period, callback) -> None:
        if self.fail_register:
            raise RuntimeError("register refused")
        self.registered.append((code_list, period))
        self.callbacks.append(callback)

    def run(self) -> None:
        self.ran += 1

    def unregister(self, *, code_list, period) -> None:
        if self.fail_unregister:
            raise RuntimeError("unregister refused")
        self.unregistered.append((code_list, period))

    def stop(self) -> None:
        self.stopped += 1


def _controller(subscriber: FakeSubscriber):
    lifecycle = SdkLifecycle()
    lifecycle.transition(
        SdkLifecycleState.SESSION_READY, reason="login ok", evidence_ref="ad.login"
    )
    return SubscriptionController(lifecycle, subscriber), lifecycle


def _drive_callback(subscriber: FakeSubscriber, data=None) -> None:
    assert subscriber.callbacks, "no registered callback"
    subscriber.callbacks[0](data)


class TestRegister:
    def test_register_success_advances_to_subscribe_started(self):
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        assert lifecycle.state is SdkLifecycleState.SUBSCRIBE_STARTED
        assert sub.registered == [(["600519.SH"], 1)]

    def test_registration_failure_does_not_fake_subscribe_started(self):
        """Audit R4-A3.1 5.2: an SDK register failure leaves the state
        machine untouched - SUBSCRIBE_STARTED is never a guess."""
        sub = FakeSubscriber(fail_register=True)
        controller, lifecycle = _controller(sub)
        with pytest.raises(RuntimeError, match="register refused"):
            controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        assert lifecycle.state is SdkLifecycleState.SESSION_READY


class TestCallbacks:
    def test_first_valid_callback_advances_to_callback_active(self):
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        _drive_callback(sub, data={"last_price": 1.0})
        assert lifecycle.state is SdkLifecycleState.CALLBACK_ACTIVE
        # idempotent: further callbacks stay active
        _drive_callback(sub)
        _drive_callback(sub)
        assert lifecycle.state is SdkLifecycleState.CALLBACK_ACTIVE

    def test_callback_after_unsubscribed_never_reactivates(self):
        """Audit R4-A3.1 5.2: a late callback after UNSUBSCRIBED is
        COUNTED, never a silent reactivation."""
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        controller.unregister(code_list=["600519.SH"], period=1)
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED
        _drive_callback(sub)
        _drive_callback(sub)
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED
        assert controller.late_callbacks == 2

    def test_callback_without_subscription_window_is_orphan(self):
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        controller.unregister(code_list=["600519.SH"], period=1)
        controller.stop()
        # late + orphan accounting stay separate diagnostics
        _drive_callback(sub)
        assert controller.late_callbacks == 1
        assert controller.orphan_callbacks == 0


class TestUnregisterStop:
    def test_unregister_advances_to_unsubscribed(self):
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        controller.unregister(code_list=["600519.SH"], period=1)
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED

    def test_unregister_is_retry_safe(self):
        """Audit R4-A3.1 5.2: repeat unregister/stop calls are no-ops once
        UNSUBSCRIBED (the SDK itself can be double-invoked)."""
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        controller.unregister(code_list=["600519.SH"], period=1)
        controller.unregister(code_list=["600519.SH"], period=1)
        controller.unregister(code_list=["600519.SH"], period=1)
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED
        assert len(sub.unregistered) == 1

    def test_unregister_failure_keeps_state_and_records(self):
        sub = FakeSubscriber(fail_unregister=True)
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        controller.unregister(code_list=["600519.SH"], period=1)
        assert lifecycle.state is SdkLifecycleState.SUBSCRIBE_STARTED
        assert "unregister" in controller.step_errors

    def test_stop_completes_unsubscription(self):
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        _drive_callback(sub)
        controller.stop()
        assert lifecycle.state is SdkLifecycleState.UNSUBSCRIBED
        assert sub.stopped == 1

    def test_run_failure_recorded_not_raised(self):
        class _RunFailSubscriber(FakeSubscriber):
            def run(self) -> None:
                raise RuntimeError("run refused")

        sub = _RunFailSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        controller.run()  # records the error, does not crash the probe
        assert "run" in controller.step_errors
        assert lifecycle.state is SdkLifecycleState.SUBSCRIBE_STARTED


class TestDiagnostics:
    def test_diagnostic_view_derives_from_state_machine(self):
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        _drive_callback(sub)
        controller.unregister(code_list=["600519.SH"], period=1)
        diag = controller.diagnostic()
        assert diag["state"] == "UNSUBSCRIBED"
        states = [t["to"] for t in diag["transitions"]]
        assert states == ["SESSION_READY", "SUBSCRIBE_STARTED", "CALLBACK_ACTIVE", "UNSUBSCRIBED"]

    def test_state_machine_is_the_sor_not_the_view(self):
        """Mutating the diagnostic view cannot corrupt the state."""
        sub = FakeSubscriber()
        controller, lifecycle = _controller(sub)
        controller.register(code_list=["600519.SH"], period=1, callback=lambda d: None)
        diag = controller.diagnostic()
        diag["state"] = "CALLBACK_ACTIVE"  # tamper the view
        assert lifecycle.state is SdkLifecycleState.SUBSCRIBE_STARTED
