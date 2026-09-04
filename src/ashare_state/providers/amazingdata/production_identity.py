"""Positive production account identity (R4-A3.1 P0-03, audit 20260827).

The previous "not Trial == Production" blacklist was FAIL-OPEN: any
unknown / educational / other-vendor-tier account whose profile did not
happen to match the ``TotalWeekFlow == 10`` trial heuristic was stamped
``ACCOUNT_*`` and became approval-eligible. That conflicts with the
project's truth ladder:

    CI/Fake      = structure truth only
    Trial        = connectivity only
    Production   = formal truth only

Production truth therefore requires a POSITIVE, explicitly frozen
production account identity - an exact-match allowlist of ONE scrubbed
stable profile id. Until the real production account is human-confirmed
and frozen, the correct behavior is NOT_TESTABLE / BLOCKED (fail closed),
never "unknown account auto-upgrades to production".

Governance rules encoded here:
- the frozen value is the SCRUBBED stable profile identity
  (``<kind>_<digest>``) - NEVER username / password / token;
- a missing / empty / unconfirmed config file means NO production
  identity exists -> every production gate blocks;
- ``RunKind.PRODUCTION`` never substitutes for account identity - the
  run kind and the account identity are independent facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ashare_state.providers.amazingdata.session import AccountProfile

__all__ = [
    "AccountKind",
    "FrozenProductionIdentity",
    "load_frozen_production_identity",
    "production_account_status",
    "is_scrubbed_profile_id",
]

#: repo root (src/ashare_state/providers/amazingdata/production_identity.py)
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: the frozen identity config (scrubbed identity - no credentials)
PRODUCTION_ACCOUNT_CONFIG = _REPO_ROOT / "configs" / "production_account.yaml"

# A generated AccountProfile id is a kind label plus a hexadecimal digest.
# Keeping this shape strict prevents raw usernames, hosts, tokens, or other
# provider output from becoming a governance identity by accident.
_PROFILE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}_[0-9a-f]{6,64}$")
_ALLOWED_CONFIG_KEYS = frozenset({"production_account_profile_id", "confirmed_at", "confirmed_by"})
_FORBIDDEN_CONFIRMATION_MARKER_RE = re.compile(
    r"(?i)\b(?:password|passwd|token|secret|credential|username|host|port)\b"
)


class AccountKind(StrEnum):
    """The account truth ladder (R4-A3.1 P0-03).

    ``UNKNOWN`` is the default for every parsed profile that is neither
    the known trial shape NOR the frozen production identity - it is
    NOT an approval-eligible state (fail closed).
    """

    UNKNOWN = "UNKNOWN"
    TRIAL = "TRIAL"
    PRODUCTION = "PRODUCTION"


@dataclass(frozen=True)
class FrozenProductionIdentity:
    """The human-confirmed production account identity.

    ``account_profile_id`` is the scrubbed stable profile identity
    (provider/env/host/username-hash/entitlement digest) - carrying real
    credentials here would be a governance violation, not a config.
    """

    account_profile_id: str
    confirmed_at: str = ""
    confirmed_by: str = ""


def is_scrubbed_profile_id(value: object) -> bool:
    """Return True only for the public, digest-shaped profile identity."""

    if not isinstance(value, str) or value != value.strip():
        return False
    return bool(_PROFILE_ID_RE.fullmatch(value))


def _valid_confirmation_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_confirmed_by(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > 128:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        return False
    return _FORBIDDEN_CONFIRMATION_MARKER_RE.search(candidate) is None


def _valid_frozen_identity(identity: FrozenProductionIdentity) -> bool:
    profile_id = identity.account_profile_id
    if not is_scrubbed_profile_id(profile_id):
        return False
    if profile_id.startswith(("TRIAL_", "TRIAL_SIMULATION_", "FAKE_")):
        return False
    return _valid_confirmation_timestamp(identity.confirmed_at) and _valid_confirmed_by(
        identity.confirmed_by
    )


def load_frozen_production_identity(
    config_path: Path | None = None,
) -> FrozenProductionIdentity | None:
    """Load a fully confirmed, scrubbed production identity or return None.

    Missing, empty, malformed, trial-shaped, or unconfirmed config is
    deliberately indistinguishable from no identity. This keeps every
    production gate fail closed.
    """
    path = config_path or PRODUCTION_ACCOUNT_CONFIG
    if not path.is_file():
        return None
    import yaml

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(doc, dict) or set(doc) - _ALLOWED_CONFIG_KEYS:
        return None

    profile_id = doc.get("production_account_profile_id")
    confirmed_at = doc.get("confirmed_at")
    confirmed_by = doc.get("confirmed_by")
    if not isinstance(profile_id, str) or not profile_id.strip():
        return None
    identity = FrozenProductionIdentity(
        account_profile_id=profile_id.strip(),
        confirmed_at=confirmed_at.strip() if isinstance(confirmed_at, str) else "",
        confirmed_by=confirmed_by.strip() if isinstance(confirmed_by, str) else "",
    )
    return identity if _valid_frozen_identity(identity) else None


def production_account_status(profile: AccountProfile) -> tuple[AccountKind, str]:
    """Classify a parsed profile against the confirmed positive allowlist."""

    frozen = load_frozen_production_identity()
    if frozen is None:
        return (
            AccountKind.UNKNOWN,
            "no frozen production identity configured or confirmed - production truth "
            "unprovable (fail closed, audit R4-A3.1 P0-03)",
        )
    if not _valid_frozen_identity(frozen):
        return (AccountKind.UNKNOWN, "frozen production identity is invalid or unconfirmed")
    if not profile.auth_ok:
        return (AccountKind.UNKNOWN, "authentication not confirmed")
    if not profile.profile_parsed:
        return (AccountKind.UNKNOWN, "logon profile not parsed")
    if profile.kind is AccountKind.TRIAL:
        return (
            AccountKind.UNKNOWN,
            "trial profile is never production (use --trial for trial evidence)",
        )
    if not profile.entitlement_verified:
        return (AccountKind.UNKNOWN, "entitlement not verified (PermissionCode missing)")
    if not is_scrubbed_profile_id(profile.account_profile_id):
        return (AccountKind.UNKNOWN, "account profile identity is not scrubbed")
    if profile.account_profile_id == frozen.account_profile_id:
        return (
            AccountKind.PRODUCTION,
            "exact match with the frozen production identity"
            + (f" (confirmed {frozen.confirmed_at})" if frozen.confirmed_at else ""),
        )
    return (
        AccountKind.UNKNOWN,
        "not the frozen production identity - a non-trial account is NOT automatically production "
        "(audit R4-A3.1 P0-03)",
    )
