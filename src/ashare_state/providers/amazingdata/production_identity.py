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

from dataclasses import dataclass
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
]

#: repo root (src/ashare_state/providers/amazingdata/production_identity.py)
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: the frozen identity config (scrubbed identity - no credentials)
PRODUCTION_ACCOUNT_CONFIG = _REPO_ROOT / "configs" / "production_account.yaml"


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


def load_frozen_production_identity(
    config_path: Path | None = None,
) -> FrozenProductionIdentity | None:
    """Load the frozen production identity, or None (fail closed).

    None is returned when the config is missing, unreadable, or the
    identity has not been confirmed yet (empty value) - in that state NO
    production truth may be granted anywhere in the system.
    """
    path = config_path or PRODUCTION_ACCOUNT_CONFIG
    if not path.is_file():
        return None
    import yaml

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(doc, dict):
        return None
    profile_id = str(doc.get("production_account_profile_id", "") or "").strip()
    if not profile_id:
        # not yet confirmed - the correct production state today
        return None
    return FrozenProductionIdentity(
        account_profile_id=profile_id,
        confirmed_at=str(doc.get("confirmed_at", "") or ""),
        confirmed_by=str(doc.get("confirmed_by", "") or ""),
    )


def production_account_status(profile: AccountProfile) -> tuple[AccountKind, str]:
    """Positive classification of a parsed profile against the frozen
    production identity.

    Returns ``(kind, reason)``; PRODUCTION requires an EXACT match with
    the frozen identity plus a fully parsed, entitlement-verified
    profile. Everything else - including "not a known trial" - is
    UNKNOWN (never an implicit production upgrade).
    """
    frozen = load_frozen_production_identity()
    if frozen is None:
        return (
            AccountKind.UNKNOWN,
            "no frozen production identity configured - production truth "
            "unprovable (fail closed, audit R4-A3.1 P0-03)",
        )
    if not profile.profile_parsed:
        return (AccountKind.UNKNOWN, "logon profile not parsed")
    if not profile.entitlement_verified:
        return (AccountKind.UNKNOWN, "entitlement not verified (PermissionCode missing)")
    if profile.account_profile_id == frozen.account_profile_id:
        return (
            AccountKind.PRODUCTION,
            "exact match with the frozen production identity"
            + (f" (confirmed {frozen.confirmed_at})" if frozen.confirmed_at else ""),
        )
    return (
        AccountKind.UNKNOWN,
        "not the frozen production identity - a non-trial account is NOT "
        "automatically production (audit R4-A3.1 P0-03)",
    )
