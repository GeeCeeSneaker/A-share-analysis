"""Single TGW credential path backed by the current Windows user's vault."""

from __future__ import annotations

import getpass
import importlib
import os
from collections.abc import Callable, Mapping
from pathlib import Path

TGW_PASSWORD_ENV = "TGW_PASSWORD"
TGW_VAULT_SERVICE = "ashare-state/tgw"
_ENV_FILE_KEYS = frozenset({"TGW_USERNAME", "TGW_SERVER_VIP", "TGW_SERVER_PORT", "TGW_MODULE"})
STORE_CREDENTIAL_COMMAND = (
    "uv run python scripts/spike/production_account_bootstrap.py --store-credential"
)


class TgwCredentialsError(RuntimeError):
    """Safe, actionable credential/setup error without provider values."""


def load_tgw_environment(
    path: Path = Path(".env"), *, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Load process TGW settings and non-secret TGW_* values from an optional .env.

    A password in .env is deliberately ignored. Process environment values,
    including the explicit TGW_PASSWORD override, take precedence.
    """

    source = os.environ if environ is None else environ
    values = {key: value for key, value in source.items() if key.startswith("TGW_")}
    if not path.is_file():
        return values

    with path.open(encoding="utf-8") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key not in _ENV_FILE_KEYS or key in values:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key] = value
    return values


def _windows_credential_store():
    if os.name != "nt":
        raise TgwCredentialsError(
            "TGW credentials require the current Windows user's Credential Manager. "
            f"Run {STORE_CREDENTIAL_COMMAND} on the controlled Windows runtime."
        )
    try:
        backend_module = importlib.import_module("keyring.backends.Windows")
        return backend_module.WinVaultKeyring()
    except Exception:  # noqa: BLE001 - do not expose backend details
        raise TgwCredentialsError(
            "Windows Credential Manager is unavailable. "
            f"Run {STORE_CREDENTIAL_COMMAND} to configure or rotate the credential."
        ) from None


def resolve_tgw_password(username: str, *, override: str | None = None) -> str:
    """Use an explicit process override or the Windows Credential Manager."""

    if override:
        return override
    if not username:
        raise TgwCredentialsError(
            "Set TGW_USERNAME in the local non-secret configuration, then run "
            f"{STORE_CREDENTIAL_COMMAND}."
        )
    try:
        password = _windows_credential_store().get_password(TGW_VAULT_SERVICE, username)
    except TgwCredentialsError:
        raise
    except Exception:  # noqa: BLE001 - vault errors may contain sensitive context
        raise TgwCredentialsError(
            f"TGW credential is unavailable. Run {STORE_CREDENTIAL_COMMAND} to set or rotate it."
        ) from None
    if not password:
        raise TgwCredentialsError(
            f"TGW credential is unavailable. Run {STORE_CREDENTIAL_COMMAND} to set or rotate it."
        )
    return password


def resolve_tgw_credentials(settings: Mapping[str, str]) -> tuple[str, str, str, int]:
    """Build provider credentials from non-secret settings and one secret source."""

    missing = [
        key
        for key in ("TGW_USERNAME", "TGW_SERVER_VIP", "TGW_SERVER_PORT")
        if not settings.get(key)
    ]
    if missing:
        raise TgwCredentialsError(
            f"Set {', '.join(missing)} in the local non-secret configuration; then run "
            f"{STORE_CREDENTIAL_COMMAND}."
        )
    try:
        port = int(settings["TGW_SERVER_PORT"])
    except (TypeError, ValueError):
        raise TgwCredentialsError(
            "TGW_SERVER_PORT must be an integer in the local non-secret configuration."
        ) from None
    username = settings["TGW_USERNAME"]
    password = resolve_tgw_password(username, override=settings.get(TGW_PASSWORD_ENV))
    return username, password, settings["TGW_SERVER_VIP"], port


def store_tgw_password(username: str, *, prompt: Callable[[str], str] | None = None) -> None:
    """Prompt once without echo and replace the current user's saved TGW password."""

    if not username:
        raise TgwCredentialsError(
            "Set TGW_USERNAME in the local non-secret configuration before storing the credential."
        )
    store = _windows_credential_store()
    try:
        password = (prompt or getpass.getpass)("TGW password (input hidden): ")
    except Exception:  # noqa: BLE001 - never expose prompt implementation details
        raise TgwCredentialsError("Password entry failed; no credential was stored.") from None
    if not password:
        raise TgwCredentialsError("An empty TGW password was not stored; run the command again.")
    try:
        store.set_password(TGW_VAULT_SERVICE, username, password)
    except Exception:  # noqa: BLE001 - backend messages must not reach output
        raise TgwCredentialsError(
            "Windows Credential Manager could not store the TGW credential. "
            f"Verify the current Windows user and rerun {STORE_CREDENTIAL_COMMAND}."
        ) from None


def credential_rotation_hint() -> str:
    """Return the same safe next step for a provider-rejected credential."""

    return (
        "TGW rejected the saved credential. Verify the non-secret account settings, "
        f"then run {STORE_CREDENTIAL_COMMAND} to replace the password."
    )
