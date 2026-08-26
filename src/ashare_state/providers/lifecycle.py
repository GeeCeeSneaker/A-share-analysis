"""SDK runtime lifecycle state machine (R4-A3 A3-01, audit 20260826).

The provider runtime's process phase is an EXPLICIT state machine - flow
position is never guessed from exception strings:

    INIT
      -> SDK_UNAVAILABLE   (SDK import impossible - terminal)
      -> LOAD_FAILED       (SDK import raised - terminal)
      -> LOGIN_FAILED      (login network/internal failure - terminal)
      -> AUTH_REJECTED     (credentials rejected - terminal)
      -> SESSION_READY     (logged in; business calls allowed)
    SESSION_READY / UNSUBSCRIBED
      -> SUBSCRIBE_STARTED -> CALLBACK_ACTIVE -> UNSUBSCRIBED ...
    any state
      -> LOGGED_OUT        (clean close - terminal, idempotent)

Terminal semantics (audit section 7.2 A3-01):
- terminal auth/load failures EARLY-STOP the runtime;
- NO later provider business call fires after a terminal failure
  (``require_ready`` raises a typed ProviderLifecycleTerminalError
  BEFORE the endpoint function is invoked);
- cleanup/close is IDEMPOTENT (closing a closed runtime is a no-op;
  closing a failed runtime is legal cleanup, not a state guess).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from ashare_state.providers.errors import ProviderError

__all__ = [
    "LifecycleTransitionError",
    "ProviderLifecycleTerminalError",
    "SdkLifecycle",
    "SdkLifecycleState",
    "TERMINAL_LIFECYCLE_STATES",
]


class SdkLifecycleState(StrEnum):
    """Explicit runtime states (audit 20260826 section 7.2 A3-01)."""

    INIT = "INIT"
    SDK_UNAVAILABLE = "SDK_UNAVAILABLE"  # SDK not importable (terminal)
    LOAD_FAILED = "LOAD_FAILED"  # SDK import raised (terminal)
    LOGIN_FAILED = "LOGIN_FAILED"  # login network/internal failure (terminal)
    AUTH_REJECTED = "AUTH_REJECTED"  # credentials rejected (terminal)
    SESSION_READY = "SESSION_READY"  # logged in; business calls allowed
    SUBSCRIBE_STARTED = "SUBSCRIBE_STARTED"
    CALLBACK_ACTIVE = "CALLBACK_ACTIVE"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    LOGGED_OUT = "LOGGED_OUT"  # clean close (terminal)


#: states from which the runtime can never proceed to business activity
TERMINAL_LIFECYCLE_STATES = frozenset(
    {
        SdkLifecycleState.SDK_UNAVAILABLE,
        SdkLifecycleState.LOAD_FAILED,
        SdkLifecycleState.LOGIN_FAILED,
        SdkLifecycleState.AUTH_REJECTED,
        SdkLifecycleState.LOGGED_OUT,
    }
)

#: states in which provider business calls are allowed
SESSION_ALIVE_STATES = frozenset(
    {
        SdkLifecycleState.SESSION_READY,
        SdkLifecycleState.SUBSCRIBE_STARTED,
        SdkLifecycleState.CALLBACK_ACTIVE,
        SdkLifecycleState.UNSUBSCRIBED,
    }
)

#: legal forward transitions (LOGGED_OUT via close() is legal from ANY
#: state - idempotent cleanup - and is not listed here)
_LEGAL_TRANSITIONS: dict[SdkLifecycleState, frozenset[SdkLifecycleState]] = {
    SdkLifecycleState.INIT: frozenset(
        {
            SdkLifecycleState.SDK_UNAVAILABLE,
            SdkLifecycleState.LOAD_FAILED,
            SdkLifecycleState.LOGIN_FAILED,
            SdkLifecycleState.AUTH_REJECTED,
            SdkLifecycleState.SESSION_READY,
        }
    ),
    SdkLifecycleState.SESSION_READY: frozenset({SdkLifecycleState.SUBSCRIBE_STARTED}),
    SdkLifecycleState.SUBSCRIBE_STARTED: frozenset(
        {SdkLifecycleState.CALLBACK_ACTIVE, SdkLifecycleState.UNSUBSCRIBED}
    ),
    SdkLifecycleState.CALLBACK_ACTIVE: frozenset({SdkLifecycleState.UNSUBSCRIBED}),
    SdkLifecycleState.UNSUBSCRIBED: frozenset({SdkLifecycleState.SUBSCRIBE_STARTED}),
}


class LifecycleTransitionError(RuntimeError):
    """An illegal lifecycle transition was requested (programming error -
    the runtime control flow must only issue legal transitions)."""


class ProviderLifecycleTerminalError(ProviderError):
    """Early-stop enforcement: a provider business call was attempted
    after (or before reaching) a live session state.

    The context carries the terminal state, its reason and evidence ref so
    the failure is auditable WITHOUT guessing from exception strings."""

    def __init__(self, message: str, *, context: dict | None = None) -> None:
        super().__init__(message, context=context or {})


@dataclass(frozen=True)
class LifecycleTransition:
    """One recorded state change - the audit trail of the runtime phase."""

    from_state: SdkLifecycleState
    to_state: SdkLifecycleState
    reason: str
    evidence_ref: str
    at: str


@dataclass
class SdkLifecycle:
    """The provider runtime's lifecycle state machine.

    Terminal states early-stop the runtime: ``require_ready`` raises a
    typed error BEFORE any endpoint function is invoked, so no later
    provider business call can fire after a terminal failure.
    """

    state: SdkLifecycleState = SdkLifecycleState.INIT
    terminal_reason: str = ""
    terminal_evidence_ref: str = ""
    history: list[LifecycleTransition] = field(default_factory=list)

    # ------------------------------------------------------------ queries
    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_LIFECYCLE_STATES

    @property
    def session_alive(self) -> bool:
        return self.state in SESSION_ALIVE_STATES

    def require_ready(self, action: str) -> None:
        """Early-stop enforcement: business calls are legal only while a
        session is alive. Raises ProviderLifecycleTerminalError (terminal)
        or ProviderLifecycleTerminalError (not yet ready) otherwise - the
        endpoint function is NEVER invoked in either case."""
        if self.state in TERMINAL_LIFECYCLE_STATES:
            msg = (
                f"provider runtime is TERMINAL ({self.state.value}) - "
                f"'{action}' refused; terminal reason: {self.terminal_reason or 'n/a'}"
            )
            raise ProviderLifecycleTerminalError(
                msg,
                context={
                    "lifecycle_state": self.state.value,
                    "terminal_reason": self.terminal_reason,
                    "terminal_evidence_ref": self.terminal_evidence_ref,
                    "refused_action": action,
                    "early_stop": True,
                },
            )
        if not self.session_alive:
            msg = (
                f"provider runtime is not session-ready ({self.state.value}) - "
                f"'{action}' refused; complete login first"
            )
            raise ProviderLifecycleTerminalError(
                msg,
                context={
                    "lifecycle_state": self.state.value,
                    "refused_action": action,
                    "early_stop": True,
                },
            )

    # -------------------------------------------------------- transitions
    def transition(
        self,
        new_state: SdkLifecycleState,
        *,
        reason: str = "",
        evidence_ref: str = "",
    ) -> None:
        """Move to ``new_state``; illegal jumps raise (programming error).

        LOGGED_OUT is reachable from ANY state via :meth:`close` only."""
        if new_state is SdkLifecycleState.LOGGED_OUT:
            msg = (
                "LOGGED_OUT must be reached through close() (idempotent "
                "cleanup), not a plain transition"
            )
            raise LifecycleTransitionError(msg)
        legal = _LEGAL_TRANSITIONS.get(self.state, frozenset())
        if new_state not in legal:
            msg = (
                f"illegal lifecycle transition {self.state.value} -> "
                f"{new_state.value} (legal: {sorted(s.value for s in legal)})"
            )
            raise LifecycleTransitionError(msg)
        self._record(new_state, reason=reason, evidence_ref=evidence_ref)

    def close(self, *, reason: str = "", evidence_ref: str = "") -> None:
        """Idempotent clean close: legal from ANY state (closing a failed
        runtime is cleanup, not a state guess); a no-op when already
        closed."""
        if self.state is SdkLifecycleState.LOGGED_OUT:
            return
        self._record(SdkLifecycleState.LOGGED_OUT, reason=reason, evidence_ref=evidence_ref)

    def _record(self, new_state: SdkLifecycleState, *, reason: str, evidence_ref: str) -> None:
        self.history.append(
            LifecycleTransition(
                from_state=self.state,
                to_state=new_state,
                reason=reason,
                evidence_ref=evidence_ref,
                at=datetime.now(UTC).isoformat(),
            )
        )
        self.state = new_state
        if new_state in TERMINAL_LIFECYCLE_STATES and new_state is not SdkLifecycleState.LOGGED_OUT:
            self.terminal_reason = reason
            self.terminal_evidence_ref = evidence_ref
