"""Shared integration-test fixtures.

R4-A3.1 P0-03 (audit 20260827): the production account gate and the
capability-approval entry points now require a POSITIVE exact match
with a frozen production identity (allowlist; fail closed when nothing
is frozen). Tests that legitimately open PRODUCTION runs / approve
capabilities freeze an identity matching THEIR production profile via
``freeze_production_identity`` - the real repo stays fail-closed until
the formal production account is human-confirmed (P0-M-1B).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def freeze_production_identity(monkeypatch):
    """Freeze the production identity for the given AccountProfile.

    Returns the frozen account_profile_id. While frozen, the production
    gates treat exactly this profile as PRODUCTION; every other account
    (including unknown non-trial ones) stays refused."""

    def _freeze(profile) -> str:
        from ashare_state.providers.amazingdata import production_identity as pi

        frozen = pi.FrozenProductionIdentity(
            account_profile_id=profile.account_profile_id,
            confirmed_at="2026-08-27T00:00:00+00:00",
            confirmed_by="r4-a3.1-test",
        )
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)
        return frozen.account_profile_id

    return _freeze
