"""Session lifecycle: login/logout with stdout isolation + profile capture.

The logon profile (scrubbed: no Token) identifies the account's
entitlements and becomes the account_profile_id used in Raw envelopes
(task book section 6: TRIAL_SIMULATION vs PRODUCTION must never mix).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ashare_state.providers.amazingdata import sdk_loader
from ashare_state.providers.amazingdata.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderSdkInternalError,
    ProviderUnavailableError,
    classify_sdk_error,
)
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStdout,
    parse_logon_profile,
    sdk_stdout_into,
)
from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState


@dataclass
class AccountProfile:
    """Scrubbed logon entitlements + derived stable profile id.

    Audit P1-08: auth success and profile parsing are SEPARATE facts:
      auth_ok            - login call returned without error
      profile_parsed     - the logon json was captured and parsed
      entitlement_verified - PermissionCode was present and non-empty
    Production source-policy approval requires all three.

    Audit P1-07: account_profile_id mixes provider/env/host/username-hash
    with the entitlement hash so two accounts with identical entitlements
    still get distinct ids.
    """

    raw_profile: dict[str, Any] = field(default_factory=dict)
    auth_ok: bool = False
    profile_parsed: bool = False
    account_profile_id: str = "UNKNOWN"

    @property
    def login_ok(self) -> bool:
        """Legacy view: auth succeeded (profile may still be unparsed)."""
        return self.auth_ok

    @property
    def entitlement_verified(self) -> bool:
        return self.profile_parsed and bool(self.permission_codes)

    @property
    def permission_codes(self) -> str:
        return str(self.raw_profile.get("PermissionCode", ""))

    @property
    def subscribe_limit(self) -> int | None:
        v = self.raw_profile.get("SubscribeLimitNum")
        return int(v) if isinstance(v, (int, float)) else None

    @property
    def weekly_flow_limit(self) -> int | None:
        v = self.raw_profile.get("TotalWeekFlow")
        return int(v) if isinstance(v, (int, float)) else None

    @property
    def used_week_flow(self) -> float | None:
        v = self.raw_profile.get("UsedWeekFlow")
        return float(v) if isinstance(v, (int, float)) else None

    @classmethod
    def from_scrubbed(
        cls,
        profile: dict[str, Any] | None,
        *,
        provider: str = "amazingdata",
        environment: str = "UNKNOWN",
        host: str = "",
        username: str = "",
    ) -> AccountProfile:
        """Build the profile; unparsable logon output keeps auth_ok=True
        but profile_parsed=False (audit P1-08)."""
        if not profile:
            return cls(auth_ok=True, profile_parsed=False)
        username_hash = hashlib.sha256(username.encode()).hexdigest()[:8] if username else "anon"
        entitlement = (
            f"{profile.get('PermissionCode', '')}|"
            f"{profile.get('SubscribeLimitNum', '')}|"
            f"{profile.get('TotalWeekFlow', '')}"
        )
        digest = hashlib.sha256(
            f"{provider}|{environment}|{host}|{username_hash}|{entitlement}".encode()
        ).hexdigest()[:12]
        # classify trial vs production by entitlement shape; refined when a
        # real production account is observed (task book section 18).
        kind = "TRIAL_SIMULATION" if profile.get("TotalWeekFlow") == 10 else "ACCOUNT"
        return cls(
            raw_profile=profile,
            auth_ok=True,
            profile_parsed=True,
            account_profile_id=f"{kind}_{digest}",
        )


class AmazingDataSession:
    """Owns login/logout; all data classes are created after login.

    R4-A3 A3-01: the session drives the EXPLICIT SDK lifecycle state
    machine (``self.lifecycle``) - SDK load failure / login failure /
    auth rejection become terminal states, and the provider refuses
    business calls after a terminal failure (early stop)."""

    def __init__(self, username: str, password: str, host: str, port: int) -> None:
        self._credentials = (username, password, host, port)
        self._sdk: Any = None
        self.profile = AccountProfile()
        self.lifecycle = SdkLifecycle()

    # -------------------------------------------------------------- login
    def login(self) -> AccountProfile:
        """Login with SDK stdout captured; parse + scrub the logon json.

        Every failure class lands in an EXPLICIT terminal lifecycle state
        (R4-A3 A3-01) - the process phase is never inferred from
        exception strings downstream."""
        if self.profile.login_ok:
            return self.profile
        try:
            self._sdk = sdk_loader.load_sdk()
        except ProviderUnavailableError as exc:
            self.lifecycle.transition(
                SdkLifecycleState.SDK_UNAVAILABLE,
                reason=str(exc),
                evidence_ref="sdk_loader.load_sdk",
            )
            raise
        except Exception as exc:  # noqa: BLE001 - classification boundary
            self.lifecycle.transition(
                SdkLifecycleState.LOAD_FAILED,
                reason=f"{type(exc).__name__}: {exc}",
                evidence_ref="sdk_loader.load_sdk",
            )
            raise
        username, password, host, port = self._credentials
        holder = CapturedStdout()
        try:
            with sdk_stdout_into(holder):
                self._sdk.login(username=username, password=password, host=host, port=int(port))
        except ProviderError as raised:
            if isinstance(raised, ProviderAuthError):
                self.lifecycle.transition(
                    SdkLifecycleState.AUTH_REJECTED,
                    reason=str(raised),
                    evidence_ref="login",
                )
            else:
                self.lifecycle.transition(
                    SdkLifecycleState.LOGIN_FAILED,
                    reason=f"{type(raised).__name__}: {raised}",
                    evidence_ref="login",
                )
            raise
        except Exception as exc:  # noqa: BLE001 - classification boundary
            typed = classify_sdk_error(exc, endpoint="login")
            if isinstance(typed, ProviderNetworkError | ProviderSdkInternalError):
                # login-specific refinement: auth vs network
                lowered = str(exc).lower()
                if any(h in lowered for h in ("password", "user", "auth", "logon")):
                    typed = ProviderAuthError(f"login failed: {exc}")
            if isinstance(typed, ProviderAuthError):
                self.lifecycle.transition(
                    SdkLifecycleState.AUTH_REJECTED,
                    reason=str(typed),
                    evidence_ref="login",
                )
            else:
                self.lifecycle.transition(
                    SdkLifecycleState.LOGIN_FAILED,
                    reason=f"{type(typed).__name__}: {typed}",
                    evidence_ref="login",
                )
            raise typed from exc
        # login success prints "login success" + logon json into the capture
        profile = parse_logon_profile(holder.text)
        if profile is None:
            # SDK version drift: no logon json captured - keep auth_ok=True
            # but profile_parsed=False (audit P1-08: separate the two facts)
            self.profile = AccountProfile(auth_ok=True, profile_parsed=False)
            self.lifecycle.transition(
                SdkLifecycleState.SESSION_READY,
                reason="login ok; logon profile not parsed (audit P1-08)",
                evidence_ref="UNKNOWN",
            )
            return self.profile
        self.profile = AccountProfile.from_scrubbed(
            profile,
            provider="amazingdata",
            host=host,
            username=username,
        )
        self.lifecycle.transition(
            SdkLifecycleState.SESSION_READY,
            reason="login ok",
            evidence_ref=self.profile.account_profile_id,
        )
        return self.profile

    # ------------------------------------------------------------- logout
    def logout(self) -> None:
        """Best-effort clean close - IDEMPOTENT (R4-A3 A3-01): closing a
        closed session is a no-op; closing a FAILED session is legal
        cleanup, not a state guess."""
        if self._sdk is None:
            self.lifecycle.close(reason="logout (no sdk handle)")
            return
        try:
            with sdk_stdout_into(CapturedStdout()):
                self._sdk.logout()
        except Exception:  # noqa: BLE001, S110 - logout is best-effort
            pass
        finally:
            self._sdk = None
            self.profile = AccountProfile()
            self.lifecycle.close(reason="logout")

    # ------------------------------------------------------------ helpers
    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            msg = "session not logged in"
            raise ProviderSdkInternalError(msg)
        return self._sdk

    def __enter__(self) -> AmazingDataSession:
        self.login()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.logout()
