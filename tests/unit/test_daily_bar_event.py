from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from ashare_state.canonical.daily_bar_event import (
    DAILY_BAR_EVENT_ELIGIBILITY_VERSION,
    DAILY_BAR_SESSION_CALENDAR_VERSION,
    DailyBarEventContractError,
    daily_bar_event_eligibility_binding,
    daily_bar_event_eligible_at,
    daily_bar_session_close_at,
    validate_daily_bar_event_eligibility_binding,
)


@pytest.mark.parametrize(
    ("trade_date", "market"),
    [(date(2020, 1, 2), "SH"), (date(2020, 1, 2), "SZ"), (date(2021, 11, 15), "BJ")],
)
def test_session_calendar_resolves_exchange_local_close(trade_date: date, market: str) -> None:
    close = daily_bar_session_close_at(trade_date, market)

    assert close.isoformat() == f"{trade_date.isoformat()}T15:00:00+08:00"


def test_daily_bar_is_eligible_at_close_boundary_not_before() -> None:
    assert not daily_bar_event_eligible_at(
        "2024-01-02",
        datetime(2024, 1, 2, 6, 59, 59, tzinfo=UTC),
        market="SH",
    )
    assert daily_bar_event_eligible_at(
        "2024-01-02",
        datetime(2024, 1, 2, 7, 0, tzinfo=UTC),
        market="SH",
    )
    assert daily_bar_event_eligible_at(
        date(2024, 1, 2),
        datetime(2024, 1, 2, 7, 0, 1, tzinfo=UTC),
        market="SH",
    )


def test_daily_bar_event_contract_has_explicit_versioned_binding() -> None:
    binding = daily_bar_event_eligibility_binding()

    assert binding["policy_version"] == DAILY_BAR_EVENT_ELIGIBILITY_VERSION
    assert binding["session_calendar_version"] == DAILY_BAR_SESSION_CALENDAR_VERSION
    assert len(binding["policy_hash"]) == 64
    assert len(binding["session_calendar_hash"]) == 64
    validate_daily_bar_event_eligibility_binding(binding)
    with pytest.raises(DailyBarEventContractError, match="binding differs"):
        validate_daily_bar_event_eligibility_binding({**binding, "session_calendar_hash": "0" * 64})


def test_event_clock_does_not_accept_retrieval_time_as_a_substitute() -> None:
    with pytest.raises(DailyBarEventContractError, match="timezone-aware"):
        daily_bar_event_eligible_at("2024-01-02", datetime(2024, 1, 2, 15, 0), market="SH")


def test_unknown_market_and_pre_bse_session_fail_closed() -> None:
    with pytest.raises(DailyBarEventContractError, match="unsupported A-share market"):
        daily_bar_session_close_at(date(2024, 1, 2), "UNKNOWN")
    with pytest.raises(DailyBarEventContractError, match="outside the versioned calendar scope"):
        daily_bar_session_close_at(date(2021, 11, 12), "BJ")
