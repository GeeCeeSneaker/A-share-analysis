"""Provider-normalized DTOs (task book section 7).

Provider DTOs FAITHFULLY express provider fields - no renaming into
system semantics, no dropping 'unneeded' fields. Canonical mappers route
them into fact domains later (task book section 1.3: one provider
interface may feed SEVERAL canonical domains, never merged).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# NOTE (verified against manual + live probes 2026-08-21):
# provider symbol format is SUFFIX style: "600000.SH" / "000001.SZ" / "830799.BJ"


@dataclass(frozen=True)
class TradeCalendarDTO:
    """get_calendar / get_calendar(market) - trading days."""

    market: str  # provider market literal, e.g. "SH"
    trading_days: list[date]


@dataclass(frozen=True)
class SecurityMasterDTO:
    """get_code_list / get_hist_code_list / get_stock_basic entries."""

    provider_symbol: str  # "600000.SH"
    security_code: str  # "600000"
    market_code: str  # provider market literal
    security_type: str  # provider security type literal
    # from get_stock_basic (None when the endpoint lacks the column)
    security_name: str | None = None
    list_date: date | None = None
    delist_date: date | None = None
    is_listed: int | None = None  # 1 listed / 3 terminated (provider coding)
    st_flag: int | None = None


@dataclass(frozen=True)
class DailyBarDTO:
    """query_kline daily rows - provider units preserved (unit map TBD B5)."""

    provider_symbol: str
    kline_type: str  # e.g. "DAY"
    kline_time: int  # yyyymmdd provider encoding
    open: float
    high: float
    low: float
    close: float
    pre_close: float | None
    volume: float  # provider unit (hand? share? - B5 evidence pending)
    amount: float  # provider unit (yuan? thousand? - B5 evidence pending)


@dataclass(frozen=True)
class SecurityStatusDTO:
    """get_history_stock_status - faithful full-field mirror.

    Feeds THREE canonical domains (routing happens in mapper, not here):
      Security Status : IS_ST_SEC, IS_SUSP_SEC, security identity
      Limit Price     : HIGH_LIMITED, LOW_LIMITED, PRECLOSE
      Corporate Action: IS_WD_SEC, IS_XR_SEC
    """

    market_code: str
    security_code: str  # provider may return bare code here (verified in B3)
    trade_date: date
    pre_close: float | None
    high_limited: float | None
    low_limited: float | None
    price_high_lmt_rate: float | None
    price_low_lmt_rate: float | None
    is_st_sec: int | None
    is_susp_sec: int | None
    is_wd_sec: int | None
    is_xr_sec: int | None


@dataclass(frozen=True)
class LimitPriceDTO:
    """Limit-price projection of get_history_stock_status (mapper output)."""

    provider_symbol: str
    trade_date: date
    pre_close: float | None
    up_limit: float | None  # HIGH_LIMITED
    down_limit: float | None  # LOW_LIMITED
    up_limit_rate: float | None  # PRICE_HIGH_LMT_RATE
    down_limit_rate: float | None  # PRICE_LOW_LMT_RATE


@dataclass(frozen=True)
class AdjFactorDTO:
    """get_adj_factor / get_backward_factor rows."""

    provider_symbol: str
    ex_date: date
    adj_factor: float  # single-event factor (get_adj_factor)
    backward_factor: float | None  # cumulative factor (get_backward_factor)
    factor_type: str  # "SINGLE" | "BACKWARD"


@dataclass(frozen=True)
class CorporateActionDTO:
    """get_dividend / get_right_issue / ex-dividend rows (B4 shape TBD)."""

    provider_symbol: str
    event_date: date | None
    ex_date: date | None
    event_type: str  # provider literal: DIVIDEND / RIGHT_ISSUE / ...
    is_ex_dividend: bool = False
    is_ex_rights: bool = False
    provider_fields: dict[str, float | str | None] | None = None  # faithful extras


@dataclass(frozen=True)
class EquityStructureDTO:
    """get_equity_structure rows - B6 free-float assessment input.

    Provider semantics preserved verbatim; equivalence verdict
    (EXACT/DERIVABLE/ALTERNATIVE/MISSING vs Tushare free_share) is a
    SEPARATE assessment result, never a DTO assumption.
    """

    provider_symbol: str
    report_date: date
    total_shares: float | None
    float_a_shares: float | None  # provider literal meaning recorded in B6
    provider_field_meanings: dict[str, str] | None = None


@dataclass(frozen=True)
class IndustryMemberDTO:
    """get_industry_constituent rows (taxonomy owner verified in B7)."""

    provider_symbol: str
    industry_code: str  # provider industry code (taxonomy owner TBD B7)
    industry_level: int | None  # 1/2/3
    in_date: date | None
    out_date: date | None
    current_sign: int | None
    taxonomy_owner: str = "UNVERIFIED"  # SW / GALAXY / GALAXY_UNVERIFIED


@dataclass(frozen=True)
class IndexDailyDTO:
    """get_index_daily / index kline rows - benchmark input."""

    index_code: str  # provider index code
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    pre_close: float | None
    volume: float | None  # provider unit (B5)
    amount: float | None  # provider unit (B5)
    return_type: str = "UNVERIFIED"  # PRICE / TOTAL_RETURN / UNVERIFIED
