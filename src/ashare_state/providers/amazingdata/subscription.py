"""L1 subscription lifecycle controller (R4-A3.1 P1-01, audit 20260827).

R4-A3 delivered the subscription states (SUBSCRIBE_STARTED /
CALLBACK_ACTIVE / UNSUBSCRIBED) in the ``SdkLifecycle`` state machine,
but the real Trial L1 script still drove register/run/unregister/stop
through a private ``dict`` - a second lifecycle SoR the audit rejected.
This controller is the single subscription control-flow wrapper that
DRIVES the real state machine:

    SESSION_READY -> register ok -> SUBSCRIBE_STARTED
        -> first valid callback -> CALLBACK_ACTIVE
        -> unregister / stop complete -> UNSUBSCRIBED
        -> logout -> LOGGED_OUT (via lifecycle.close())

Contract (audit R4-A3.1 section 5.2):
- registration failure does NOT fake SUBSCRIBE_STARTED (state is only
  advanced when the SDK register call actually succeeded);
- unregister/stop are RETRY SAFE (repeat calls are no-ops once
  UNSUBSCRIBED; failures are recorded, never guessed away);
- a callback arriving after UNSUBSCRIBED does NOT silently reactivate
  the state (counted as a late callback instead);
- Trial L1 remains connectivity evidence ONLY - this controller never
  asserts production permission truth.
"""

from __future__ import annotations

from typing import Any

from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState

__all__ = ["SubscriptionController"]


class SubscriptionController:
    """Drives the REAL L1 subscription control flow through the SDK
    lifecycle state machine - the correctness SoR for register/run/
    unregister/stop (replaces ad-hoc lifecycle dicts in scripts)."""

    def __init__(self, lifecycle: SdkLifecycle, subscriber: Any) -> None:
        self.lifecycle = lifecycle
        self.subscriber = subscriber
        #: callbacks observed after UNSUBSCRIBED (never reactivate)
        self.late_callbacks = 0
        #: callbacks observed without an active subscription window
        self.orphan_callbacks = 0
        #: per-step error records (register/run/unregister/stop) - the
        #: diagnostic VIEW; the state machine is the correctness SoR
        self.step_errors: dict[str, str] = {}

    # ------------------------------------------------------------ register
    def register(
        self,
        *,
        code_list: list[str],
        period: Any,
        callback: Any,
    ) -> None:
        """Register the SDK subscription; SUBSCRIBE_STARTED only on the
        SDK's own success (a failure leaves the state untouched - never
        a faked SUBSCRIBE_STARTED)."""
        wrapped = self._wrap_callback(callback)
        self.subscriber.register(code_list=code_list, period=period, callback=wrapped)
        self.lifecycle.transition(
            SdkLifecycleState.SUBSCRIBE_STARTED,
            reason=f"registered {len(code_list)} symbols",
            evidence_ref="SubscribeData.register",
        )

    def run(self) -> None:
        """Start the SDK push loop if it exposes one (best-effort:
        some SDK versions start implicitly on register)."""
        run_fn = getattr(self.subscriber, "run", None) or getattr(self.subscriber, "start", None)
        if not callable(run_fn):
            return
        try:
            run_fn()
        except Exception as exc:  # noqa: BLE001 - diagnostic record
            self.step_errors["run"] = f"{type(exc).__name__}: {exc}"[:200]

    # ----------------------------------------------------------- callback
    def _wrap_callback(self, callback: Any) -> Any:
        """Wrap the user callback: the FIRST valid callback advances
        SUBSCRIBE_STARTED -> CALLBACK_ACTIVE; callbacks after
        UNSUBSCRIBED are counted late and NEVER reactivate the state."""

        def on_event(data: Any) -> None:
            self._note_callback()
            callback(data)

        return on_event

    def _note_callback(self) -> None:
        state = self.lifecycle.state
        if state is SdkLifecycleState.CALLBACK_ACTIVE:
            return  # already active - idempotent
        if state is SdkLifecycleState.SUBSCRIBE_STARTED:
            self.lifecycle.transition(
                SdkLifecycleState.CALLBACK_ACTIVE,
                reason="first valid callback",
                evidence_ref="SubscribeData.callback",
            )
            return
        if state is SdkLifecycleState.UNSUBSCRIBED:
            # late callback after unsubscribe: counted, never reactivated
            self.late_callbacks += 1
            return
        # callback without an active subscription window (e.g. before
        # register completed, or after logout) - an anomaly to record
        self.orphan_callbacks += 1

    # -------------------------------------------------- unregister / stop
    def unregister(self, *, code_list: list[str], period: Any) -> None:
        """Unregister the subscription. RETRY SAFE: once UNSUBSCRIBED a
        repeat call is a no-op; an SDK failure is recorded (diagnostic)
        without advancing the state on a guess."""
        if self.lifecycle.state is SdkLifecycleState.UNSUBSCRIBED:
            return  # retry-safe no-op
        try:
            self.subscriber.unregister(code_list=code_list, period=period)
        except Exception as exc:  # noqa: BLE001 - diagnostic record
            self.step_errors["unregister"] = f"{type(exc).__name__}: {exc}"[:200]
            return
        self.lifecycle.transition(
            SdkLifecycleState.UNSUBSCRIBED,
            reason="unregister complete",
            evidence_ref="SubscribeData.unregister",
        )

    def stop(self) -> None:
        """Stop the SDK push loop (retry safe; failures recorded)."""
        if self.lifecycle.state is SdkLifecycleState.UNSUBSCRIBED:
            # already unsubscribed: stop is optional cleanup
            stop_fn = getattr(self.subscriber, "stop", None)
            if callable(stop_fn):
                try:
                    stop_fn()
                except Exception as exc:  # noqa: BLE001 - diagnostic record
                    self.step_errors["stop"] = f"{type(exc).__name__}: {exc}"[:200]
            return
        stop_fn = getattr(self.subscriber, "stop", None)
        if callable(stop_fn):
            try:
                stop_fn()
            except Exception as exc:  # noqa: BLE001 - diagnostic record
                self.step_errors["stop"] = f"{type(exc).__name__}: {exc}"[:200]
                return
        if self.lifecycle.state in (
            SdkLifecycleState.SUBSCRIBE_STARTED,
            SdkLifecycleState.CALLBACK_ACTIVE,
        ):
            self.lifecycle.transition(
                SdkLifecycleState.UNSUBSCRIBED,
                reason="stop complete",
                evidence_ref="SubscribeData.stop",
            )

    # -------------------------------------------------------------- views
    def diagnostic(self) -> dict[str, object]:
        """The report VIEW (state machine remains the SoR)."""
        return {
            "state": self.lifecycle.state.value,
            "step_errors": dict(self.step_errors),
            "late_callbacks": self.late_callbacks,
            "orphan_callbacks": self.orphan_callbacks,
            "transitions": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "reason": t.reason,
                    "at": t.at,
                }
                for t in self.lifecycle.history
            ],
        }
