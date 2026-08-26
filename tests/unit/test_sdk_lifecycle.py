"""R4-A3 A3-01: SDK lifecycle state machine tests (audit 20260826
section 7.2).

The runtime process phase is an EXPLICIT state machine:
- terminal auth/load failures early-stop the runtime;
- no later provider business call fires after a terminal failure
  (require_ready raises BEFORE the endpoint function is invoked);
- cleanup/close is idempotent (closing a closed or FAILED runtime is
  legal, never a state guess);
- illegal jumps raise (programming errors surface loudly).
"""

from __future__ import annotations

import pytest

from ashare_state.providers.errors import ProviderError
from ashare_state.providers.lifecycle import (
    TERMINAL_LIFECYCLE_STATES,
    LifecycleTransitionError,
    ProviderLifecycleTerminalError,
    SdkLifecycle,
    SdkLifecycleState,
)


class TestStateMachine:
    def test_happy_path_init_to_session_ready(self):
        lc = SdkLifecycle()
        assert lc.state is SdkLifecycleState.INIT
        assert not lc.session_alive
        lc.transition(SdkLifecycleState.SESSION_READY, reason="login ok")
        assert lc.state is SdkLifecycleState.SESSION_READY
        assert lc.session_alive
        assert not lc.is_terminal

    def test_subscription_lifecycle_states(self):
        """SUBSCRIBE_STARTED -> CALLBACK_ACTIVE -> UNSUBSCRIBED -> (re)SUBSCRIBE."""
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.SESSION_READY)
        lc.transition(SdkLifecycleState.SUBSCRIBE_STARTED)
        assert lc.session_alive
        lc.transition(SdkLifecycleState.CALLBACK_ACTIVE)
        lc.transition(SdkLifecycleState.UNSUBSCRIBED)
        assert lc.session_alive
        lc.transition(SdkLifecycleState.SUBSCRIBE_STARTED)  # re-subscribe
        assert lc.state is SdkLifecycleState.SUBSCRIBE_STARTED

    @pytest.mark.parametrize(
        "terminal",
        [
            SdkLifecycleState.SDK_UNAVAILABLE,
            SdkLifecycleState.LOAD_FAILED,
            SdkLifecycleState.LOGIN_FAILED,
            SdkLifecycleState.AUTH_REJECTED,
        ],
    )
    def test_failure_states_are_terminal(self, terminal):
        lc = SdkLifecycle()
        lc.transition(terminal, reason="boom", evidence_ref="login")
        assert lc.state in TERMINAL_LIFECYCLE_STATES
        assert lc.is_terminal
        assert not lc.session_alive
        assert lc.terminal_reason == "boom"
        assert lc.terminal_evidence_ref == "login"

    def test_illegal_jump_raises(self):
        """INIT -> SESSION_READY -> SDK_UNAVAILABLE is not a legal forward
        transition (a load failure can only happen from INIT) - it must
        raise instead of silently teleporting the state."""
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.SESSION_READY)
        with pytest.raises(LifecycleTransitionError, match="illegal lifecycle transition"):
            lc.transition(SdkLifecycleState.SDK_UNAVAILABLE)

    def test_logged_out_only_via_close(self):
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.SESSION_READY)
        with pytest.raises(LifecycleTransitionError, match="close"):
            lc.transition(SdkLifecycleState.LOGGED_OUT)

    def test_close_is_idempotent(self):
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.SESSION_READY)
        lc.close(reason="logout")
        assert lc.state is SdkLifecycleState.LOGGED_OUT
        lc.close(reason="logout again")  # no-op, not an error
        assert lc.state is SdkLifecycleState.LOGGED_OUT
        assert len([t for t in lc.history if t.to_state is SdkLifecycleState.LOGGED_OUT]) == 1

    def test_close_from_failed_state_is_legal_cleanup(self):
        """Closing a FAILED runtime is cleanup, not a state guess."""
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.AUTH_REJECTED, reason="bad credentials")
        lc.close(reason="cleanup after failure")
        assert lc.state is SdkLifecycleState.LOGGED_OUT

    def test_history_records_transitions_with_reason_and_evidence(self):
        lc = SdkLifecycle()
        lc.transition(
            SdkLifecycleState.SESSION_READY, reason="login ok", evidence_ref="ACCOUNT_abc"
        )
        lc.close(reason="logout")
        assert [(t.from_state, t.to_state) for t in lc.history] == [
            (SdkLifecycleState.INIT, SdkLifecycleState.SESSION_READY),
            (SdkLifecycleState.SESSION_READY, SdkLifecycleState.LOGGED_OUT),
        ]
        assert lc.history[0].evidence_ref == "ACCOUNT_abc"
        assert lc.history[0].reason == "login ok"
        assert lc.history[0].at  # ISO timestamp


class TestRequireReady:
    def test_terminal_state_refuses_business_call(self):
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.AUTH_REJECTED, reason="bad credentials")
        with pytest.raises(ProviderLifecycleTerminalError) as exc_info:
            lc.require_ready("BaseData.get_code_list")
        ctx = exc_info.value.context
        assert ctx["lifecycle_state"] == "AUTH_REJECTED"
        assert ctx["terminal_reason"] == "bad credentials"
        assert ctx["refused_action"] == "BaseData.get_code_list"
        assert ctx["early_stop"] is True

    @pytest.mark.parametrize(
        "terminal",
        [
            SdkLifecycleState.SDK_UNAVAILABLE,
            SdkLifecycleState.LOAD_FAILED,
            SdkLifecycleState.LOGIN_FAILED,
            SdkLifecycleState.AUTH_REJECTED,
            SdkLifecycleState.LOGGED_OUT,
        ],
    )
    def test_every_terminal_state_refuses(self, terminal):
        lc = SdkLifecycle()
        if terminal is SdkLifecycleState.LOGGED_OUT:
            lc.transition(SdkLifecycleState.SESSION_READY)
            lc.close()
        else:
            lc.transition(terminal, reason="r")
        with pytest.raises(ProviderLifecycleTerminalError, match="TERMINAL"):
            lc.require_ready("any.endpoint")

    def test_init_state_refuses_not_yet_ready(self):
        lc = SdkLifecycle()
        with pytest.raises(ProviderLifecycleTerminalError, match="not session-ready"):
            lc.require_ready("any.endpoint")

    def test_session_ready_allows(self):
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.SESSION_READY)
        lc.require_ready("BaseData.get_code_list")  # no raise

    def test_terminal_error_is_a_provider_error(self):
        """The early-stop error participates in the ONE provider exception
        hierarchy (audit P1-10)."""
        lc = SdkLifecycle()
        lc.transition(SdkLifecycleState.SDK_UNAVAILABLE, reason="absent")
        with pytest.raises(ProviderError):
            lc.require_ready("x")
