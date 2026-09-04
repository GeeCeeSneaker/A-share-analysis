"""Scrubbed production-account bootstrap (P0-M-1B.0 / P0-AD-01).

This command is the controlled entry point for a real-account identity
check. Credentials are read only from TGW_* environment variables or the
local .env file; they are never printed, persisted, or passed as CLI
arguments. The command emits only a scrubbed profile and runtime facts.

It deliberately does not write configs/production_account.yaml. A human
must confirm that the returned scrubbed identity belongs to this project
before the production allowlist is changed in a separate governed commit.

Usage:
    uv run python scripts/spike/production_account_bootstrap.py
    uv run python scripts/spike/production_account_bootstrap.py --offline
    uv run python scripts/spike/production_account_bootstrap.py \
        --output data/spike/results/production_account_bootstrap.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ashare_state.providers.amazingdata.doctor import run_doctor
from ashare_state.providers.amazingdata.production_identity import (
    is_freezable_production_candidate_id,
    is_generated_scrubbed_profile_id,
    load_frozen_production_identity,
)
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStderr,
    sdk_stderr_into,
)

_ENV_KEYS = (
    "TGW_USERNAME",
    "TGW_PASSWORD",
    "TGW_SERVER_VIP",
    "TGW_SERVER_PORT",
)
_RUNTIME_VERDICTS = {
    "RUNTIME_ACTUAL_LOAD_VERIFIED",
    "RUNTIME_PACKAGE_VERIFIED",
}


def load_env(path: Path = Path(".env")) -> dict[str, str]:
    """Load only TGW_* values; process env takes precedence over .env."""

    values = {key: value for key, value in os.environ.items() if key.startswith("TGW_")}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key not in _ENV_KEYS:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values.setdefault(key, value)
    return values


def _credentials_from_env(env: dict[str, str]) -> tuple[str, str, str, int] | None:
    if not all(env.get(key) for key in _ENV_KEYS):
        return None
    try:
        port = int(env["TGW_SERVER_PORT"])
    except (TypeError, ValueError):
        return None
    return (
        env["TGW_USERNAME"],
        env["TGW_PASSWORD"],
        env["TGW_SERVER_VIP"],
        port,
    )


def _safe_permission_codes(value: Any) -> str:
    """Keep only numeric entitlement codes and their public separators."""

    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or len(candidate) > 200:
        return ""
    return candidate if all(char.isdigit() or char in "|,; " for char in candidate) else ""


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(float(value)) else None


def _profile_kind(profile_id: str) -> str:
    if profile_id.startswith("TRIAL_SIMULATION_"):
        return "TRIAL"
    if profile_id.startswith("UNKNOWN_"):
        return "UNKNOWN"
    return "UNAVAILABLE" if not profile_id or profile_id == "UNKNOWN" else "UNKNOWN"


def _normalized_runtime_verdict(raw: dict[str, Any]) -> str:
    verdict = str(raw.get("verdict") or "NOT_VERIFIED")
    return verdict if verdict in _RUNTIME_VERDICTS else "NOT_VERIFIED"


def _offline_safe_report(raw: dict[str, Any]) -> dict[str, Any]:
    """Return runtime-only facts; never inspect account/profile state."""

    sdk_state = str(raw.get("sdk_state") or "NOT_TESTED")
    return {
        "schema": "production_account_bootstrap.v1",
        "checked_at": raw.get("checked_at") or datetime.now(UTC).isoformat(),
        "platform": raw.get("platform") or sys.platform,
        "PYTHON_VERSION": raw.get("PYTHON_VERSION"),
        "SDK_ABI": raw.get("SDK_ABI"),
        "sdk_state": sdk_state,
        "AMAZINGDATA_PACKAGE_VERSION": raw.get("AMAZINGDATA_PACKAGE_VERSION"),
        "PYTHON_TGW_PACKAGE_VERSION": raw.get("PYTHON_TGW_PACKAGE_VERSION"),
        "TGW_RUNTIME_REPORTED_VERSION": raw.get("TGW_RUNTIME_REPORTED_VERSION"),
        "runtime_verdict": _normalized_runtime_verdict(raw),
        "offline": True,
        "bootstrap_status": (
            "OFFLINE_RUNTIME_VERIFIED" if sdk_state == "SDK_INSTALLED" else "NOT_TESTABLE_SDK"
        ),
    }


def _safe_report(
    raw: dict[str, Any], *, offline: bool, credentials_available: bool = True
) -> dict[str, Any]:
    """Project the doctor report onto fields safe for stdout/evidence."""

    if offline:
        return _offline_safe_report(raw)

    profile = raw.get("ACCOUNT_PROFILE")
    profile = profile if isinstance(profile, dict) else {}
    profile_id_candidate = str(profile.get("account_profile_id") or "").strip()
    profile_id = profile_id_candidate if is_generated_scrubbed_profile_id(profile_id_candidate) else ""
    permission_codes = _safe_permission_codes(profile.get("permission_codes"))
    profile_parsed = bool(profile_id)
    profile_kind = _profile_kind(profile_id)
    profile_is_freezable = is_freezable_production_candidate_id(profile_id)
    entitlement_verified = profile_parsed and bool(permission_codes)
    authenticated = raw.get("AUTHENTICATED") == "YES"
    query_ready = raw.get("QUERY_READY") == "YES"

    frozen = load_frozen_production_identity()
    if frozen is None:
        production_status = "NOT_FROZEN"
    elif (
        authenticated
        and profile_parsed
        and entitlement_verified
        and profile_is_freezable
        and profile_id == frozen.account_profile_id
    ):
        production_status = "PRODUCTION"
    else:
        production_status = "UNKNOWN"

    sdk_state = str(raw.get("sdk_state") or "NOT_TESTED")
    runtime_verdict = _normalized_runtime_verdict(raw)

    if not credentials_available:
        bootstrap_status = "NOT_TESTABLE_ACCOUNT"
    elif sdk_state != "SDK_INSTALLED":
        bootstrap_status = "NOT_TESTABLE_SDK"
    elif not authenticated:
        bootstrap_status = "NOT_TESTABLE_ACCOUNT"
    elif not profile_parsed:
        bootstrap_status = "NOT_TESTABLE_PROFILE"
    elif not entitlement_verified:
        bootstrap_status = "NOT_TESTABLE_ENTITLEMENT"
    elif not query_ready:
        bootstrap_status = "NOT_QUERY_READY"
    elif profile_kind == "TRIAL":
        bootstrap_status = "TRIAL_ACCOUNT_NOT_FREEZABLE"
    elif not profile_is_freezable:
        bootstrap_status = "NOT_TESTABLE_PROFILE"
    elif production_status == "PRODUCTION":
        bootstrap_status = "FROZEN_IDENTITY_MATCH_REQUIRES_REVIEW"
    else:
        bootstrap_status = "IDENTITY_CANDIDATE"

    safe_profile: dict[str, Any] = {
        "account_profile_id": profile_id if profile_id else "UNAVAILABLE",
        "profile_kind": profile_kind,
        "profile_parsed": profile_parsed,
        "entitlement_verified": entitlement_verified,
        "permission_codes": permission_codes,
        "subscribe_limit": _safe_number(profile.get("subscribe_limit")),
        "weekly_flow_limit": _safe_number(profile.get("weekly_flow_limit")),
        "used_week_flow": _safe_number(profile.get("used_week_flow")),
    }
    return {
        "schema": "production_account_bootstrap.v1",
        "checked_at": raw.get("checked_at") or datetime.now(UTC).isoformat(),
        "platform": raw.get("platform") or sys.platform,
        "PYTHON_VERSION": raw.get("PYTHON_VERSION"),
        "SDK_ABI": raw.get("SDK_ABI"),
        "sdk_state": sdk_state,
        "AMAZINGDATA_PACKAGE_VERSION": raw.get("AMAZINGDATA_PACKAGE_VERSION"),
        "PYTHON_TGW_PACKAGE_VERSION": raw.get("PYTHON_TGW_PACKAGE_VERSION"),
        "TGW_RUNTIME_REPORTED_VERSION": raw.get("TGW_RUNTIME_REPORTED_VERSION"),
        "runtime_verdict": runtime_verdict,
        "NETWORK_REACHABLE": raw.get("NETWORK_REACHABLE", "NOT_TESTED"),
        "AUTHENTICATED": "YES" if authenticated else str(raw.get("AUTHENTICATED") or "NOT_TESTED"),
        "QUERY_READY": "YES" if query_ready else str(raw.get("QUERY_READY") or "NOT_TESTED"),
        "ACCOUNT_PROFILE": safe_profile,
        "production_identity_status": production_status,
        "bootstrap_status": bootstrap_status,
        "config_written": False,
        "human_confirmation_required": True,
    }


def _not_tested_report() -> dict[str, Any]:
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "sdk_state": "NOT_TESTED",
        "AUTHENTICATED": "NOT_TESTED",
        "QUERY_READY": "NOT_TESTED",
    }


def _error_report() -> dict[str, Any]:
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "sdk_state": "ERROR",
        "AUTHENTICATED": "NOT_TESTED",
        "QUERY_READY": "NOT_TESTED",
    }


def _run_doctor_with_stderr_containment(
    *,
    credentials: tuple[str, str, str, int] | None,
    offline: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """Run doctor without allowing raw stderr to escape the process."""

    holder = CapturedStderr()
    raw: dict[str, Any] | None = None
    try:
        with sdk_stderr_into(holder):
            raw = run_doctor(credentials=credentials, offline=offline)
    except Exception:  # noqa: BLE001 - raw error text must not escape
        pass
    stderr_observed = bool(holder.text)
    holder.text = ""
    return raw, stderr_observed


def _write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="emit a scrubbed AmazingData production-account identity candidate"
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="verify the packaged SDK/runtime without reading or using account credentials",
    )
    args = parser.parse_args()

    if args.offline:
        raw, stderr_observed = _run_doctor_with_stderr_containment(credentials=None, offline=True)
        safe = _safe_report(_error_report() if raw is None else raw, offline=True)
        safe["sdk_stderr_observed"] = stderr_observed
        if raw is None:
            safe["bootstrap_status"] = "ERROR"
            exit_code = 3
        else:
            exit_code = 0 if safe["bootstrap_status"] == "OFFLINE_RUNTIME_VERIFIED" else 2
    else:
        env = load_env(args.env_file)
        credentials = _credentials_from_env(env)
        if credentials is None:
            safe = _safe_report(_not_tested_report(), offline=False, credentials_available=False)
            safe["sdk_stderr_observed"] = False
            exit_code = 2
        else:
            raw, stderr_observed = _run_doctor_with_stderr_containment(
                credentials=credentials, offline=False
            )
            safe = _safe_report(_error_report() if raw is None else raw, offline=False)
            safe["sdk_stderr_observed"] = stderr_observed
            if raw is None:
                safe["bootstrap_status"] = "ERROR"
                exit_code = 3
            else:
                exit_code = (
                    0
                    if safe["bootstrap_status"]
                    in {
                        "IDENTITY_CANDIDATE",
                        "FROZEN_IDENTITY_MATCH_REQUIRES_REVIEW",
                    }
                    else 1
                )

    if args.output:
        try:
            _write_report(safe, args.output)
        except OSError:
            exit_code = 3
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
