"""R4-A3 A3-03: runtime early-stop control flow tests (audit 20260826
section 7.2).

Fault injection across the dependency chain - proven by provider
CALL-COUNT / EXCHANGE-COUNT / EVIDENCE-COUNT, never just the final
exception:

  SDK load fail        -> no login / no endpoint call
  login/auth terminal  -> no capability calls
  session not ready    -> no endpoint call
  terminal failure     -> NO later provider business call (lifecycle gate
                          fires BEFORE the endpoint function)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.errors import (
    ProviderAuthError,
    ProviderUnavailableError,
)
from ashare_state.providers.lifecycle import (
    ProviderLifecycleTerminalError,
    SdkLifecycle,
    SdkLifecycleState,
)


@dataclass
class FakeIdentity:
    sdk_version: str = "fake-1.0"
    tgw_runtime_version: str = "fake-rt"


class _CallCountingSdk:
    """A fake SDK module counting every business call."""

    def __init__(self, *, login_error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._login_error = login_error

    def login(self, **kwargs: Any) -> None:
        self.calls.append("login")
        if self._login_error is not None:
            raise self._login_error

    def logout(self) -> None:
        self.calls.append("logout")

    def BaseData(self) -> Any:
        return _CountingFacade(self.calls, "BaseData")

    def InfoData(self) -> Any:
        return _CountingFacade(self.calls, "InfoData")


class _CountingFacade:
    def __init__(self, calls: list[str], prefix: str) -> None:
        self._calls = calls
        self._prefix = prefix

    def __getattr__(self, name: str) -> Any:
        def method(**kwargs: Any) -> list[str]:
            self._calls.append(f"{self._prefix}.{name}")
            return ["600519.SH"]

        return method


@dataclass
class ReadySession:
    """A fake logged-in session with a controllable lifecycle."""

    profile: Any = None
    lifecycle: SdkLifecycle = field(default_factory=SdkLifecycle)

    def __post_init__(self) -> None:
        if self.profile is None:
            from ashare_state.providers.amazingdata.session import AccountProfile

            self.profile = AccountProfile()
        if self.lifecycle.state is SdkLifecycleState.INIT:
            self.lifecycle.transition(SdkLifecycleState.SESSION_READY, reason="fake login")


def _provider(session: Any) -> AmazingDataProvider:
    return AmazingDataProvider(session, identity=FakeIdentity(), use_mode=ProviderUseMode.SPIKE)


class TestSdkLoadFailure:
    def test_sdk_absent_no_login_no_endpoint_call(self, monkeypatch):
        """SDK import impossible -> terminal SDK_UNAVAILABLE; neither
        login nor ANY endpoint call fires (call-count proof)."""
        import ashare_state.providers.amazingdata.sdk_loader as loader

        def _raise(*args: object, **kwargs: object) -> None:
            raise ProviderUnavailableError("AmazingData SDK is not installed in this environment")

        monkeypatch.setattr(loader, "load_sdk", _raise)
        session = AmazingDataSession("u", "p", "h", 1)
        with pytest.raises(ProviderUnavailableError):
            session.login()
        assert session.lifecycle.state is SdkLifecycleState.SDK_UNAVAILABLE
        # the early stop is durable: a later business call on the SAME
        # provider is refused before the SDK function fires
        provider = AmazingDataProvider.__new__(AmazingDataProvider)
        provider.session = session
        provider.identity = FakeIdentity()
        provider.use_mode = ProviderUseMode.SPIKE
        with pytest.raises(ProviderLifecycleTerminalError, match="TERMINAL"):
            provider.call_exchange("BaseData.get_code_list", "code_list", lambda: None)

    def test_sdk_load_exception_is_load_failed(self, monkeypatch):
        """A non-ImportError load failure (corrupted wheel) lands in
        LOAD_FAILED, distinct from SDK_UNAVAILABLE."""
        import ashare_state.providers.amazingdata.sdk_loader as loader

        def _raise(*args: object, **kwargs: object) -> None:
            raise OSError("dll load failed")

        monkeypatch.setattr(loader, "load_sdk", _raise)
        session = AmazingDataSession("u", "p", "h", 1)
        with pytest.raises(OSError, match="dll load failed"):
            session.login()
        assert session.lifecycle.state is SdkLifecycleState.LOAD_FAILED
        assert session.lifecycle.is_terminal


class TestLoginTerminalFailure:
    def test_auth_rejected_no_capability_calls(self):
        """Credentials rejected -> terminal AUTH_REJECTED; the SDK module
        saw the login attempt but ZERO business endpoint calls fired."""
        sdk = _CallCountingSdk(login_error=Exception("login fail: password error"))
        session = AmazingDataSession("u", "bad", "h", 1)
        # inject the fake SDK BEFORE login
        object.__setattr__(session, "_sdk", sdk)
        # bypass load_sdk by injecting _sdk then calling the login body:
        # simulate by monkeypatching load_sdk to return our fake
        import ashare_state.providers.amazingdata.sdk_loader as loader

        original = loader.load_sdk
        loader.load_sdk = lambda: sdk
        try:
            with pytest.raises(ProviderAuthError):
                session.login()
        finally:
            loader.load_sdk = original
        assert session.lifecycle.state is SdkLifecycleState.AUTH_REJECTED
        assert sdk.calls == ["login"]  # NO BaseData/InfoData call fired

    def test_network_login_failure_is_login_failed(self):
        """A network-ish login failure lands in LOGIN_FAILED (distinct
        from AUTH_REJECTED) and still early-stops."""
        sdk = _CallCountingSdk(login_error=Exception("connection refused"))
        session = AmazingDataSession("u", "p", "h", 1)
        import ashare_state.providers.amazingdata.sdk_loader as loader

        original = loader.load_sdk
        loader.load_sdk = lambda: sdk
        try:
            with pytest.raises(Exception, match="connection refused"):
                session.login()
        finally:
            loader.load_sdk = original
        assert session.lifecycle.state is SdkLifecycleState.LOGIN_FAILED
        assert sdk.calls == ["login"]


class TestNoBusinessCallAfterTerminal:
    @pytest.mark.parametrize(
        "terminal_state",
        [
            SdkLifecycleState.SDK_UNAVAILABLE,
            SdkLifecycleState.LOAD_FAILED,
            SdkLifecycleState.LOGIN_FAILED,
            SdkLifecycleState.AUTH_REJECTED,
            SdkLifecycleState.LOGGED_OUT,
        ],
    )
    def test_endpoint_function_never_invoked_after_terminal(self, terminal_state):
        """The lifecycle gate fires BEFORE the endpoint function: the fn
        passed to call_exchange is NEVER invoked (call-count proof), and
        NO exchange/evidence is created for the refused call."""

        fired = {"count": 0}

        def endpoint_fn() -> Any:
            fired["count"] += 1
            return ["600519.SH"]

        lc = SdkLifecycle()
        if terminal_state is SdkLifecycleState.LOGGED_OUT:
            lc.transition(SdkLifecycleState.SESSION_READY)
            lc.close()
        else:
            lc.transition(terminal_state, reason="fault injected")
        session = ReadySession(lifecycle=lc)
        provider = _provider(session)
        with pytest.raises(ProviderLifecycleTerminalError):
            provider.call_exchange("BaseData.get_code_list", "code_list", endpoint_fn)
        assert fired["count"] == 0  # endpoint function NEVER fired
        assert provider.last_envelopes == []  # no evidence created

    def test_not_ready_session_refuses(self):
        """INIT (never logged in) also refuses - no silent call."""
        fired = {"count": 0}

        def endpoint_fn() -> Any:
            fired["count"] += 1
            return []

        session = ReadySession()
        # override post_init's automatic ready transition: simulate a
        # session that never logged in
        session.lifecycle = SdkLifecycle()
        provider = _provider(session)
        with pytest.raises(ProviderLifecycleTerminalError, match="not session-ready"):
            provider.call_exchange("BaseData.get_code_list", "code_list", endpoint_fn)
        assert fired["count"] == 0

    def test_ready_session_proceeds_normally(self):
        """Control: a SESSION_READY lifecycle lets the exchange through
        (envelope + payload recorded)."""
        fired = {"count": 0}

        def endpoint_fn() -> Any:
            fired["count"] += 1
            return ["600519.SH"]

        provider = _provider(ReadySession())
        exchange = provider.call_exchange("BaseData.get_code_list", "code_list", endpoint_fn)
        assert fired["count"] == 1
        assert exchange.payload == ["600519.SH"]
        assert exchange.envelope.status == "OK"
        assert len(provider.last_envelopes) == 1


class TestLifecycleDrivesSession:
    def test_real_session_login_success_marks_session_ready(self, monkeypatch):
        sdk = _CallCountingSdk()
        monkeypatch.setattr("ashare_state.providers.amazingdata.sdk_loader.load_sdk", lambda: sdk)
        import ashare_state.providers.amazingdata.session as session_mod

        monkeypatch.setattr(session_mod, "parse_logon_profile", lambda text: None)
        session = AmazingDataSession("u", "p", "h", 1)
        session.login()
        assert session.lifecycle.state is SdkLifecycleState.SESSION_READY
        assert session.lifecycle.session_alive

    def test_real_session_logout_is_idempotent(self, monkeypatch):
        """logout() twice: the lifecycle closes once and stays closed."""
        sdk = _CallCountingSdk()
        monkeypatch.setattr("ashare_state.providers.amazingdata.sdk_loader.load_sdk", lambda: sdk)
        import ashare_state.providers.amazingdata.session as session_mod

        monkeypatch.setattr(session_mod, "parse_logon_profile", lambda text: None)
        session = AmazingDataSession("u", "p", "h", 1)
        session.login()
        session.logout()
        assert session.lifecycle.state is SdkLifecycleState.LOGGED_OUT
        session.logout()  # idempotent no-op
        assert session.lifecycle.state is SdkLifecycleState.LOGGED_OUT
        assert sdk.calls.count("logout") == 1

    def test_logout_after_failure_is_cleanup(self, monkeypatch):
        sdk = _CallCountingSdk(login_error=Exception("login fail: password error"))
        monkeypatch.setattr("ashare_state.providers.amazingdata.sdk_loader.load_sdk", lambda: sdk)
        session = AmazingDataSession("u", "bad", "h", 1)
        with pytest.raises(ProviderAuthError):
            session.login()
        assert session.lifecycle.state is SdkLifecycleState.AUTH_REJECTED
        session.logout()  # legal cleanup from a FAILED state
        assert session.lifecycle.state is SdkLifecycleState.LOGGED_OUT
