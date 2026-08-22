"""PIT Trading Rules (audit R4-A2.2b, section 39).

Versioned effective_from/effective_to rule rows; limit prices use
Decimal ROUND_HALF_UP (never Python float round).

Rule facts (publicly documented exchange rules):
- Main board (SH/SZ A): +/-10% from 1996-12-16; ST/risk-warning 5%
- Main-board IPO first day (2014-01 to 2023-registration): +44%/-36%
- ChiNext (300xxx): +/-10% until 2020-08-24; +/-20% after (first 5
  listing days no limit under the registration regime)
- STAR (688xxx, from 2019-07-22): +/-20% after the first 5 listing days
  (no limit within them)
- BSE (8xxxxx/43xxxx/92xxxx, from 2021-11-15): +/-30%
- Delisting-period main-board: +/-10%
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_MIN_DATE = "19000101"
_MAX_DATE = "20991231"


@dataclass(frozen=True)
class TradingRule:
    exchange: str  # SH / SZ / BJ
    board: str  # MAIN / CHINEXT / STAR / BSE / BSE_OLD
    effective_from: str  # yyyymmdd inclusive
    effective_to: str  # yyyymmdd inclusive
    st_state: bool
    listing_age_rule: str  # e.g. "FIRST_5_DAYS_NO_LIMIT" | "NONE"
    up_rate: float
    down_rate: float
    tick_size: Decimal = Decimal("0.01")
    rounding_mode: str = "ROUND_HALF_UP"

    def limit_prices(self, pre_close: Decimal) -> tuple[Decimal, Decimal]:
        """Decimal ROUND_HALF_UP limit prices (audit section 39)."""
        up = (pre_close * (Decimal(1) + Decimal(str(self.up_rate)))).quantize(
            self.tick_size, rounding=ROUND_HALF_UP
        )
        down = (pre_close * (Decimal(1) - Decimal(str(self.down_rate)))).quantize(
            self.tick_size, rounding=ROUND_HALF_UP
        )
        return up, down


def _yyyymmdd(value: str | date) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[:8]


def resolve_trading_rule(
    *,
    exchange: str,
    code: str,
    trade_date: str | date,
    is_st: bool = False,
    listing_date: str | date | None = None,
) -> TradingRule | None:
    """Resolve the PIT-effective trading rule for one security on one day.

    Returns None when the board cannot be determined from the code.
    """
    day = _yyyymmdd(trade_date)
    bare = code.split(".")[0]
    exch = exchange.upper()
    if exch in ("SH", "SSE", "1"):
        exch = "SH"
    elif exch in ("SZ", "SZSE", "2"):
        exch = "SZ"
    elif exch in ("BJ", "BSE", "3"):
        exch = "BJ"

    first_5 = _in_first_days(day, listing_date, 5)

    if exch == "BJ" or bare.startswith(("83", "87", "43", "92")):
        if day >= "20211115":
            return TradingRule(
                exchange="BJ",
                board="BSE",
                effective_from="20211115",
                effective_to=_MAX_DATE,
                st_state=is_st,
                listing_age_rule="NONE",
                up_rate=0.30,
                down_rate=0.30,
            )
        return TradingRule(
            exchange="BJ",
            board="BSE_OLD",
            effective_from=_MIN_DATE,
            effective_to="20211114",
            st_state=is_st,
            listing_age_rule="NONE",
            up_rate=0.30,
            down_rate=0.30,
        )
    if bare.startswith("688"):
        if first_5:
            return TradingRule(
                exchange="SH",
                board="STAR",
                effective_from="20190722",
                effective_to=_MAX_DATE,
                st_state=is_st,
                listing_age_rule="FIRST_5_DAYS_NO_LIMIT",
                up_rate=0.0,
                down_rate=0.0,
            )
        return TradingRule(
            exchange="SH",
            board="STAR",
            effective_from="20190722",
            effective_to=_MAX_DATE,
            st_state=is_st,
            listing_age_rule="NONE",
            up_rate=0.20,
            down_rate=0.20,
        )
    if bare.startswith("300") or bare.startswith("301"):
        if day < "20200824":
            return TradingRule(
                exchange="SZ",
                board="CHINEXT",
                effective_from="20121030",
                effective_to="20200823",
                st_state=is_st,
                listing_age_rule="NONE",
                up_rate=0.10,
                down_rate=0.10,
            )
        if first_5:
            return TradingRule(
                exchange="SZ",
                board="CHINEXT",
                effective_from="20200824",
                effective_to=_MAX_DATE,
                st_state=is_st,
                listing_age_rule="FIRST_5_DAYS_NO_LIMIT",
                up_rate=0.0,
                down_rate=0.0,
            )
        return TradingRule(
            exchange="SZ",
            board="CHINEXT",
            effective_from="20200824",
            effective_to=_MAX_DATE,
            st_state=is_st,
            listing_age_rule="NONE",
            up_rate=0.20,
            down_rate=0.20,
        )
    # main board
    if is_st:
        return TradingRule(
            exchange=exch or "SH",
            board="MAIN",
            effective_from="19961216",
            effective_to=_MAX_DATE,
            st_state=True,
            listing_age_rule="NONE",
            up_rate=0.05,
            down_rate=0.05,
        )
    if (
        listing_date is not None
        and _yyyymmdd(listing_date) == day
        and "20140101" <= day < "20230201"
    ):
        return TradingRule(
            exchange=exch or "SH",
            board="MAIN",
            effective_from="20140101",
            effective_to="20230131",
            st_state=False,
            listing_age_rule="IPO_DAY_44_36",
            up_rate=0.44,
            down_rate=0.36,
        )
    return TradingRule(
        exchange=exch or "SH",
        board="MAIN",
        effective_from="19961216",
        effective_to=_MAX_DATE,
        st_state=False,
        listing_age_rule="NONE",
        up_rate=0.10,
        down_rate=0.10,
    )


def _in_first_days(day: str, listing_date: str | date | None, days: int) -> bool:
    if listing_date is None:
        return False
    listed = _yyyymmdd(listing_date)
    if day < listed:
        return False
    from datetime import datetime, timedelta

    start = datetime.strptime(listed, "%Y%m%d")
    end = start + timedelta(days=days * 2)  # calendar window covering N trading days
    return day <= end.strftime("%Y%m%d")
