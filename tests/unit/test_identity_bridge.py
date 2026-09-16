from datetime import date

import pytest

from ashare_state.canonical.identity import (
    IdentityBridge,
    IdentityResolutionError,
    approved_provider_identity_events,
)
from ashare_state.identity import resolve_security_identity
from ashare_state.research.models import IdentityView

EVENT = approved_provider_identity_events()[0]
MASTER_HASH = "master-input-set"


def _bridge() -> IdentityBridge:
    # The real current stock_basic shape carries the new code and the
    # original listing date.  The static event supplies the old interval.
    return IdentityBridge(
        [{"provider_symbol": EVENT.new_provider_symbol, "list_date": "20100827"}],
        master_input_set_hash=MASTER_HASH,
    )


def test_approved_code_change_keeps_one_id_and_pit_intervals() -> None:
    bridge = _bridge()
    stable_id = EVENT.security_id

    assert stable_id == str(
        resolve_security_identity(
            "SZSE", "STOCK", "300114", first_list_date=date(2010, 8, 27)
        ).security_id
    )
    assert bridge.resolve(EVENT.old_provider_symbol, date(2024, 1, 2)) == stable_id
    assert bridge.resolve(EVENT.new_provider_symbol, date(2025, 2, 17)) == stable_id
    assert bridge.resolve(EVENT.old_provider_symbol, date(2025, 2, 17)) is None
    assert bridge.resolve(EVENT.new_provider_symbol, date(2025, 2, 16)) is None


def test_current_lookup_returns_new_code_for_old_or_current_input() -> None:
    bridge = _bridge()

    assert bridge.current_provider_symbol(EVENT.security_id) == "302132.SZ"
    assert bridge.current_symbol_for("300114.SZ") == "302132.SZ"
    assert bridge.current_symbol_for("302132.SZ") == "302132.SZ"


def test_event_list_date_conflict_fails_closed() -> None:
    with pytest.raises(IdentityResolutionError, match="expected 2010-08-27"):
        IdentityBridge(
            [{"provider_symbol": "302132.SZ", "list_date": "20100828"}],
            master_input_set_hash=MASTER_HASH,
        )


def test_identity_view_separates_current_and_explicit_pit_lookup() -> None:
    view = IdentityView.from_rows(
        [
            {
                "security_id": EVENT.security_id,
                "symbol": "300114",
                "exchange": "SZSE",
                "valid_from": "2010-08-27",
                "valid_to": "2025-02-17",
            },
            {
                "security_id": EVENT.security_id,
                "symbol": "302132",
                "exchange": "SZSE",
                "valid_from": "2025-02-17",
            },
        ],
        version="identity-event-fixture-v1",
    )

    assert view.current_symbol(EVENT.security_id) == "302132.SZ"
    assert view.resolve_provider_symbol("300114.SZ", date(2024, 1, 2)).provider_symbol == (
        "300114.SZ"
    )
    assert view.resolve_provider_symbol("300114.SZ", date(2025, 2, 17)) is None
