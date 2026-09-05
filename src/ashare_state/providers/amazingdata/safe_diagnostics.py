"""Allowlisted public diagnostics; raw SDK reports are not public evidence."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from ashare_state.providers import errors
from ashare_state.providers.amazingdata.production_identity import (
    is_generated_scrubbed_profile_id,
)

_ERROR_TYPES = (
    errors.ProviderCapabilityNotApprovedError,
    errors.ProviderUnavailableError,
    errors.ProviderAuthError,
    errors.ProviderNetworkError,
    errors.ProviderPermissionError,
    errors.ProviderTimeoutError,
    errors.ProviderRateLimitError,
    errors.ProviderSchemaError,
    errors.ProviderEmptyResultError,
    errors.ProviderSdkInternalError,
    errors.ProviderGovernanceError,
    errors.ProviderError,
)
_ERROR_CODES = frozenset(cls.__name__ for cls in _ERROR_TYPES) | {"UNEXPECTED_ERROR"}
_RUNTIME_VERDICTS = frozenset(
    {
        "RUNTIME_ACTUAL_LOAD_VERIFIED",
        "RUNTIME_PACKAGE_VERIFIED",
        "RUNTIME_VERSION_MISMATCH",
        "RUNTIME_PATH_AMBIGUOUS",
        "NOT_VERIFIED",
    }
)


def safe_error_code(exc: BaseException) -> str:
    """Return a fixed taxonomy label, never SDK text or an arbitrary class name."""
    for cls in _ERROR_TYPES:
        if isinstance(exc, cls):
            return cls.__name__
    return "UNEXPECTED_ERROR"


def safe_session_error(exc: BaseException) -> errors.ProviderError:
    """Copy only the known error class; discard raw message, context and cause."""
    for cls in _ERROR_TYPES:
        if isinstance(exc, cls):
            return cls(cls.__name__)
    return errors.ProviderSdkInternalError("UNEXPECTED_ERROR")


def parse_permission_codes(value: Any) -> tuple[str, ...]:
    """Parse ASCII decimal tokens deterministically; reject the entire invalid input.

    Ordering and leading zeroes are preserved: these are provider codes, not
    quantities. Parsing must not change the existing account identity digest.
    """
    if not isinstance(value, str) or not value or len(value) > 200:
        return ()
    if any(char not in "0123456789|,;" and not char.isspace() for char in value):
        return ()
    return tuple(token for token in re.split(r"[|,;\s]+", value) if token)


def safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _choice(value: Any, choices: frozenset[str], fallback: str) -> str:
    return value if isinstance(value, str) and value in choices else fallback


def _version(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(
        r"[vV]?[0-9]+(?:\.[0-9]+){1,5}(?:-rc[0-9]+(?:\.[0-9]+)*(?:-YHZQ)?)?", value
    ):
        return value
    return None


def _status(value: Any) -> str:
    if value in ("YES", "NO", "NOT_TESTED"):
        return str(value)
    # Older internal reports attached a type label. Do not preserve that text.
    return "NO" if isinstance(value, str) and value.startswith("NO (") else "NOT_TESTED"


def safe_diagnostic_projection(raw: dict[str, Any], *, offline: bool = False) -> dict[str, Any]:
    """One value-validated projection shared by doctor, CLI and bootstrap.

    Paths, free text, raw profiles and arbitrary extra fields never cross this
    boundary. A numeric permission token is not a capability approval.
    """
    checked_at = None
    candidate = raw.get("checked_at")
    if isinstance(candidate, str):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                checked_at = parsed.isoformat()
        except ValueError:
            pass
    abi = raw.get("SDK_ABI")
    safe: dict[str, Any] = {
        "checked_at": checked_at,
        "platform": _choice(
            raw.get("platform"), frozenset({"win32", "linux", "darwin"}), "UNKNOWN"
        ),
        "PYTHON_VERSION": _version(raw.get("PYTHON_VERSION")),
        "SDK_ABI": (
            abi
            if isinstance(abi, str)
            and re.fullmatch(r"(?:cpython|pypy)[0-9]+/(?:win32|linux|darwin)-x64", abi)
            else None
        ),
        "sdk_state": _choice(
            raw.get("sdk_state"),
            frozenset({"SDK_INSTALLED", "SDK_NOT_INSTALLED", "NOT_TESTED", "ERROR"}),
            "ERROR",
        ),
        "verdict": _choice(raw.get("verdict"), _RUNTIME_VERDICTS, "NOT_VERIFIED"),
    }
    for key in (
        "AMAZINGDATA_PACKAGE_VERSION",
        "PYTHON_TGW_PACKAGE_VERSION",
        "TGW_RUNTIME_REPORTED_VERSION",
        "TGW_LOADED_DLL_VERSION",
    ):
        safe[key] = _version(raw.get(key))
    if offline:
        return safe
    network = raw.get("NETWORK_REACHABLE")
    safe["NETWORK_REACHABLE"] = _choice(
        network, frozenset({"REACHABLE", "UNREACHABLE", "NOT_TESTED"}), "NOT_TESTED"
    )
    if isinstance(network, str) and network.startswith("UNREACHABLE ("):
        safe["NETWORK_REACHABLE"] = "UNREACHABLE"
    safe["AUTHENTICATED"] = _status(raw.get("AUTHENTICATED"))
    safe["QUERY_READY"] = _status(raw.get("QUERY_READY"))
    if "auth_error" in raw:
        safe["auth_error"] = _choice(raw["auth_error"], _ERROR_CODES, "UNEXPECTED_ERROR")
    if "error_code" in raw:
        safe["error_code"] = _choice(raw["error_code"], _ERROR_CODES, "UNEXPECTED_ERROR")
    profile = raw.get("ACCOUNT_PROFILE")
    profile = profile if isinstance(profile, dict) else {}
    profile_id = profile.get("account_profile_id")
    safe["ACCOUNT_PROFILE"] = {
        "account_profile_id": (
            profile_id
            if isinstance(profile_id, str) and is_generated_scrubbed_profile_id(profile_id)
            else "UNAVAILABLE"
        ),
        "permission_codes": "|".join(parse_permission_codes(profile.get("permission_codes"))),
        "subscribe_limit": safe_number(profile.get("subscribe_limit")),
        "weekly_flow_limit": safe_number(profile.get("weekly_flow_limit")),
        "used_week_flow": safe_number(profile.get("used_week_flow")),
    }
    return safe
