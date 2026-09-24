"""Versioned event-time eligibility for completed A-share daily bars.

This policy is deliberately separate from provider receipt/ingestion time.
It supplies a market-session boundary for logical PIT decisions without
persisting a synthetic per-row availability timestamp in the daily fact set.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

DAILY_BAR_EVENT_ELIGIBILITY_VERSION = "DAILY_BAR_EVENT_ELIGIBILITY_V1"
DAILY_BAR_SESSION_CALENDAR_VERSION = "CN_A_SHARE_SESSION_CALENDAR_V1"
_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


class DailyBarEventContractError(ValueError):
    """The daily-bar event-eligibility input or manifest contract is invalid."""


# These are official exchange-owned references. The cited pages/rules define
# the closing auction through 15:00 local time for the supported venues.
# This is a session-close contract, not a holiday/trading-date list.
_SESSION_CALENDAR: dict[str, Any] = {
    "version": DAILY_BAR_SESSION_CALENDAR_VERSION,
    "timezone": "Asia/Shanghai",
    "archive_scope": {"start": "2020-01-01", "end": "2026-06-30"},
    "markets": {
        "SH": {
            "exchange": "SSE",
            "close_local": "15:00:00",
            "evidence_url": "https://edu.sse.com.cn/best/article/gsxlsc/c/4725367.shtml",
            "evidence_published": "2019-02-24",
        },
        "SZ": {
            "exchange": "SZSE",
            "close_local": "15:00:00",
            "evidence_url": "https://www.szse.cn/www/investor/warning/t20190513_567105.html",
            "evidence_published": "2019-05-13",
        },
        "BJ": {
            "exchange": "BSE",
            "first_session": "2021-11-15",
            "close_local": "15:00:00",
            "evidence_url": "https://www.bse.cn/jygl_list/200010919.html",
            "evidence_note_url": "https://www.bse.cn/uploads/6/file/public/202111/20211119182131_imqohh30d0.pdf",
        },
    },
}

_EVENT_POLICY: dict[str, Any] = {
    "version": DAILY_BAR_EVENT_ELIGIBILITY_VERSION,
    "eligible_when": "market_as_of >= session_close_at(trade_date, market)",
    "event_clock_source": "trade_date plus the bound session-calendar contract",
    "retrieved_at_is_event_clock": False,
    "row_level_market_available_at_persisted": False,
    "same_close_execution_default": False,
    "default_execution_timing": "NEXT_TRADABLE_EVENT_AFTER_SIGNAL_ELIGIBILITY",
    "archive_semantics": "event eligibility only; not historical vendor publication time",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_contract(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def daily_bar_event_eligibility_binding() -> dict[str, str]:
    """Return the exact compact policy/session binding stored in manifests."""
    return {
        "policy_version": DAILY_BAR_EVENT_ELIGIBILITY_VERSION,
        "policy_hash": _hash_contract(_EVENT_POLICY),
        "session_calendar_version": DAILY_BAR_SESSION_CALENDAR_VERSION,
        "session_calendar_hash": _hash_contract(_SESSION_CALENDAR),
    }


def validate_daily_bar_event_eligibility_binding(value: Any) -> None:
    """Fail closed unless a stored binding names this exact policy and calendar."""
    if value != daily_bar_event_eligibility_binding():
        raise DailyBarEventContractError(
            "daily-bar event-eligibility policy/session-calendar binding differs"
        )


def daily_bar_session_close_at(trade_date: date | str, market: str) -> datetime:
    """Resolve one supported venue's local session-close boundary.

    The caller supplies the market from the PIT identity dimension; a stable
    security UUID is intentionally not treated as an exchange identifier.
    """
    if isinstance(trade_date, datetime):
        raise DailyBarEventContractError("trade_date must be a date, not a datetime")
    if isinstance(trade_date, str):
        try:
            trade_date = date.fromisoformat(trade_date)
        except ValueError as exc:
            raise DailyBarEventContractError("trade_date must be an ISO calendar date") from exc
    if not isinstance(trade_date, date):
        raise DailyBarEventContractError("trade_date must be a date")

    market_code = str(market).strip().upper()
    session = _SESSION_CALENDAR["markets"].get(market_code)
    if session is None:
        raise DailyBarEventContractError(f"unsupported A-share market {market!r}")
    if market_code == "BJ" and trade_date < date.fromisoformat(session["first_session"]):
        raise DailyBarEventContractError("BSE session is outside the versioned calendar scope")

    close_time = time.fromisoformat(session["close_local"])
    return datetime.combine(trade_date, close_time, tzinfo=_MARKET_TIMEZONE)


def daily_bar_latest_session_close_at(trade_date: date | str) -> datetime:
    """Resolve the common close boundary when a fact partition has mixed venues.

    The fixed16 fact schema intentionally has no exchange column. The current
    session contract gives every supported active venue the same close; if a
    later contract makes them differ, this aggregate resolver fails closed and
    the fact/lineage contract must be revisited instead of guessing a venue.
    """
    if isinstance(trade_date, datetime):
        raise DailyBarEventContractError("trade_date must be a date, not a datetime")
    if isinstance(trade_date, str):
        try:
            trade_date = date.fromisoformat(trade_date)
        except ValueError as exc:
            raise DailyBarEventContractError("trade_date must be an ISO calendar date") from exc
    if not isinstance(trade_date, date):
        raise DailyBarEventContractError("trade_date must be a date")
    archive_start = date.fromisoformat(_SESSION_CALENDAR["archive_scope"]["start"])
    if trade_date < archive_start:
        raise DailyBarEventContractError("trade_date is outside the versioned archive scope")

    active_closes = {
        time.fromisoformat(session["close_local"])
        for session in _SESSION_CALENDAR["markets"].values()
        if not session.get("first_session")
        or trade_date >= date.fromisoformat(session["first_session"])
    }
    if len(active_closes) != 1:
        raise DailyBarEventContractError(
            "active exchange session closes differ; a venue-specific boundary is required"
        )
    return datetime.combine(trade_date, next(iter(active_closes)), tzinfo=_MARKET_TIMEZONE)


def daily_bar_event_eligible_at(
    trade_date: date | str,
    market_as_of: datetime,
    *,
    market: str,
) -> bool:
    """Whether the completed bar's event boundary has passed at ``market_as_of``.

    Equality is eligible: the bar becomes eligible at the exact session-close
    boundary. This does not establish when the provider actually published it.
    """
    if market_as_of.tzinfo is None or market_as_of.utcoffset() is None:
        raise DailyBarEventContractError("market_as_of must be timezone-aware")
    boundary = daily_bar_session_close_at(trade_date, market)
    return market_as_of >= boundary
