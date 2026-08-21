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
    classify_sdk_error,
)
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStdout,
    parse_logon_profile,
    sdk_stdout_into,
)


@dataclass
class AccountProfile:
    """Scrubbed logon entitlements + derived stable profile id."""

    raw_profile: dict[str, Any] = field(default_factory=dict)
    login_ok: bool = False
    account_profile_id: str = "UNKNOWN"

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
    def from_scrubbed(cls, profile: dict[str, Any] | None) -> AccountProfile:
        if not profile:
            return cls(login_ok=False)
        digest = hashlib.sha256(
            f"{profile.get('PermissionCode', '')}|"
            f"{profile.get('SubscribeLimitNum', '')}|"
            f"{profile.get('TotalWeekFlow', '')}".encode()
        ).hexdigest()[:12]
        # classify trial vs production by entitlement shape; refined when a
        # real production account is observed (task book section 18).
        kind = "TRIAL_SIMULATION" if profile.get("TotalWeekFlow") == 10 else "ACCOUNT"
        return cls(
            raw_profile=profile,
            login_ok=True,
            account_profile_id=f"{kind}_{digest}",
        )


class AmazingDataSession:
    """Owns login/logout; all data classes are created after login."""

    def __init__(self, username: str, password: str, host: str, port: int) -> None:
        self._credentials = (username, password, host, port)
        self._sdk: Any = None
        self.profile = AccountProfile()

    # -------------------------------------------------------------- login
    def login(self) -> AccountProfile:
        """Login with SDK stdout captured; parse + scrub the logon json."""
        if self.profile.login_ok:
            return self.profile
        self._sdk = sdk_loader.load_sdk()
        username, password, host, port = self._credentials
        holder = CapturedStdout()
        try:
            with sdk_stdout_into(holder):
                self._sdk.login(username=username, password=password, host=host, port=int(port))
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - classification boundary
            raised = classify_sdk_error(exc, endpoint="login")
            if isinstance(raised, ProviderNetworkError | ProviderSdkInternalError):
                # login-specific refinement: auth vs network
                lowered = str(exc).lower()
                if any(h in lowered for h in ("password", "user", "auth", "logon")):
                    raised = ProviderAuthError(f"login failed: {exc}")
            raise raised from exc
        # login success prints "login success" + logon json into the capture
        profile = parse_logon_profile(holder.text)
        if profile is None:
            # SDK version drift: no logon json captured - record raw shape
            profile = {"NOTE": "logon json pattern not captured", "captured_len": len(holder.text)}
        self.profile = AccountProfile.from_scrubbed(profile)
        return self.profile

    # ------------------------------------------------------------- logout
    def logout(self) -> None:
        if self._sdk is None:
            return
        try:
            with sdk_stdout_into(CapturedStdout()):
                self._sdk.logout()
        except Exception:  # noqa: BLE001, S110 - logout is best-effort
            pass
        finally:
            self._sdk = None
            self.profile = AccountProfile()

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
