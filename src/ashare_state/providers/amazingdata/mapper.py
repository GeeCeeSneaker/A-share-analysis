"""Provider DataFrame -> DTO mappers (task book sections 1.3 / 7, audit P0-04).

Audit P0-04 discipline:
- REQUIRED fields (security_code, trade_date, OHLC, adj-factor keys)
  missing or unparsable -> MappingValidationError (row quarantined by the
  caller); NEVER sentinel values like 1970-01-01 / 0.0.
- OPTIONAL fields stay None and downstream null_policy handles them.
- Field presence is decided by `first_present` (identity-aware), never by
  `or` (which conflates legal 0 / 0.0 / "" with missing).
- Task book 1.3 routing lives here: get_history_stock_status maps to
  THREE domain DTOs - never a single merged DTO.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ashare_state.providers.amazingdata.dto import (
    AdjFactorDTO,
    DailyBarDTO,
    EquityStructureDTO,
    IndexDailyDTO,
    IndustryMemberDTO,
    LimitPriceDTO,
    SecurityMasterDTO,
    SecurityStatusDTO,
    TradeCalendarDTO,
)
from ashare_state.providers.errors import MappingValidationError

_MARKET_SUFFIX = {"1": ".SH", "2": ".SZ", "3": ".BJ"}


def _col(row: Any, name: str) -> Any:
    """DataFrame row / dict access with explicit None for absence."""
    try:
        if hasattr(row, "get"):
            return row.get(name)
        return row[name]
    except (KeyError, IndexError, TypeError):
        return None


def first_present(row: Any, *names: str) -> Any:
    """First column that is PRESENT (not None); None when all absent.

    Audit P0-04: replaces `a or b` chains - a legal 0 in column `a` must
    not cause a silent fallback to column `b`.
    """
    for name in names:
        value = _col(row, name)
        if value is not None:
            return value
    return None


def _required(row: Any, *names: str, context: str) -> Any:
    value = first_present(row, *names)
    if value is None or value == "":
        raise MappingValidationError(
            f"{context}: required field {'/'.join(names)} is missing",
            context={"fields": names},
        )
    return value


def _to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        try:
            return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    return None


def _required_date(row: Any, *names: str, context: str) -> date:
    value = _required(row, *names, context=context)
    parsed = _to_date(value)
    if parsed is None:
        raise MappingValidationError(
            f"{context}: date field {'/'.join(names)} unparsable: {value!r}",
            context={"fields": names, "raw": str(value)},
        )
    return parsed


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_float(row: Any, *names: str, context: str) -> float:
    value = _required(row, *names, context=context)
    parsed = _to_float(value)
    if parsed is None:
        raise MappingValidationError(
            f"{context}: numeric field {'/'.join(names)} unparsable: {value!r}",
            context={"fields": names, "raw": str(value)},
        )
    return parsed


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


# ------------------------------------------------------------- calendar


def map_trade_calendar(market: str, trading_days: list[Any]) -> TradeCalendarDTO:
    days = [d for d in (_to_date(v) for v in trading_days) if d is not None]
    return TradeCalendarDTO(market=market, trading_days=days)


# -------------------------------------------------------- security master


def map_security_master_row(row: Any, *, source: str) -> SecurityMasterDTO:
    symbol = str(_required(row, "SECURITY_CODE", "code", context="security_master"))
    market = str(first_present(row, "MARKET_CODE", "market") or "")
    suffix = _MARKET_SUFFIX.get(market, "")
    return SecurityMasterDTO(
        provider_symbol=f"{symbol}{suffix}" if suffix else symbol,
        security_code=symbol,
        market_code=market,
        security_type=str(first_present(row, "SECURITY_TYPE") or source),
        security_name=first_present(row, "SECURITY_NAME_ABBR", "SECURITY_NAME"),
        list_date=_to_date(first_present(row, "LISTING_DATE")),
        delist_date=_to_date(first_present(row, "DELISTING_DATE")),
        is_listed=_to_int(first_present(row, "IS_LISTED")),
        st_flag=_to_int(first_present(row, "IS_ST")),
    )


# ------------------------------------------------------------------ bars


def map_daily_bar_row(row: Any, *, kline_type: str = "DAY") -> DailyBarDTO:
    ctx = "daily_bar"
    symbol = str(_required(row, "SECURITY_CODE", "code", context=ctx))
    kline_time = _to_int(first_present(row, "KLINE_TIME", "kline_time"))
    if kline_time is None:
        raise MappingValidationError(f"{ctx}: required KLINE_TIME missing/unparsable")
    return DailyBarDTO(
        provider_symbol=symbol,
        kline_type=str(first_present(row, "KLINE_TYPE") or kline_type),
        kline_time=kline_time,
        open=_required_float(row, "OPEN_PRICE", "open", context=ctx),
        high=_required_float(row, "HIGH_PRICE", "high", context=ctx),
        low=_required_float(row, "LOW_PRICE", "low", context=ctx),
        close=_required_float(row, "CLOSE_PRICE", "close", context=ctx),
        pre_close=_to_float(first_present(row, "PRE_CLOSE_PRICE")),
        volume=_required_float(row, "VOLUME", "volume", context=ctx),
        amount=_required_float(row, "AMOUNT", "amount", context=ctx),
    )


# ------------------------------------------------- status -> THREE domains


def map_security_status_row(row: Any) -> SecurityStatusDTO:
    ctx = "security_status"
    market_code = str(first_present(row, "MARKET_CODE") or "")
    security_code = str(_required(row, "SECURITY_CODE", context=ctx))
    trade_date = _required_date(row, "TRADE_DATE", context=ctx)
    return SecurityStatusDTO(
        market_code=market_code,
        security_code=security_code,
        trade_date=trade_date,
        pre_close=_to_float(first_present(row, "PRECLOSE")),
        high_limited=_to_float(first_present(row, "HIGH_LIMITED")),
        low_limited=_to_float(first_present(row, "LOW_LIMITED")),
        price_high_lmt_rate=_to_float(first_present(row, "PRICE_HIGH_LMT_RATE")),
        price_low_lmt_rate=_to_float(first_present(row, "PRICE_LOW_LMT_RATE")),
        is_st_sec=_to_int(first_present(row, "IS_ST_SEC")),
        is_susp_sec=_to_int(first_present(row, "IS_SUSP_SEC")),
        is_wd_sec=_to_int(first_present(row, "IS_WD_SEC")),
        is_xr_sec=_to_int(first_present(row, "IS_XR_SEC")),
    )


def project_limit_price(status: SecurityStatusDTO) -> LimitPriceDTO:
    """Limit-price domain projection (task book 1.3: separate fact owner)."""
    suffix = _MARKET_SUFFIX.get(status.market_code, "")
    return LimitPriceDTO(
        provider_symbol=f"{status.security_code}{suffix}",
        trade_date=status.trade_date,
        pre_close=status.pre_close,
        up_limit=status.high_limited,
        down_limit=status.low_limited,
        up_limit_rate=status.price_high_lmt_rate,
        down_limit_rate=status.price_low_lmt_rate,
    )


def corporate_action_flags(status: SecurityStatusDTO) -> tuple[str, date, bool, bool]:
    """Corporate-action domain projection: (symbol, ex_date, ex_div, ex_rights)."""
    suffix = _MARKET_SUFFIX.get(status.market_code, "")
    symbol = f"{status.security_code}{suffix}"
    is_xr = bool(status.is_xr_sec) if status.is_xr_sec is not None else False
    is_wd = bool(status.is_wd_sec) if status.is_wd_sec is not None else False
    return symbol, status.trade_date, is_wd, is_xr


# ---------------------------------------------------------------- factors


def map_adj_factor_row(row: Any, *, factor_type: str) -> AdjFactorDTO:
    ctx = "adj_factor"
    return AdjFactorDTO(
        provider_symbol=str(_required(row, "SECURITY_CODE", context=ctx)),
        ex_date=_required_date(row, "EX_DATE", context=ctx),
        adj_factor=_required_float(row, "EX_FACTOR", context=ctx),
        backward_factor=_to_float(first_present(row, "CUM_FACTOR")),
        factor_type=factor_type,
    )


# --------------------------------------------------------------- industry


def map_industry_member_row(row: Any) -> IndustryMemberDTO:
    ctx = "industry_member"
    return IndustryMemberDTO(
        provider_symbol=str(_required(row, "SECURITY_CODE", context=ctx)),
        industry_code=str(_required(row, "INDUSTRY_CODE", context=ctx)),
        industry_level=_to_int(first_present(row, "INDUSTRY_LEVEL")),
        in_date=_to_date(first_present(row, "INDUSTRY_IN_DATE", "IN_DATE")),
        out_date=_to_date(first_present(row, "INDUSTRY_OUT_DATE", "OUT_DATE")),
        current_sign=_to_int(first_present(row, "CURRENT_SIGN")),
        taxonomy_owner="GALAXY_UNVERIFIED",  # task book B6: until proven SW
    )


# ------------------------------------------------------------------ index


def map_index_daily_row(row: Any) -> IndexDailyDTO:
    ctx = "index_daily"
    return IndexDailyDTO(
        index_code=str(_required(row, "INDEX_CODE", "SECURITY_CODE", context=ctx)),
        trade_date=_required_date(row, "TRADE_DATE", "KLINE_TIME", context=ctx),
        open=_to_float(first_present(row, "OPEN_PRICE")),
        high=_to_float(first_present(row, "HIGH_PRICE")),
        low=_to_float(first_present(row, "LOW_PRICE")),
        close=_to_float(first_present(row, "CLOSE_PRICE")),
        pre_close=_to_float(first_present(row, "PRE_CLOSE_PRICE")),
        volume=_to_float(first_present(row, "VOLUME")),
        amount=_to_float(first_present(row, "AMOUNT")),
        return_type="UNVERIFIED",  # price vs total-return verified in B6
    )


# -------------------------------------------------------- equity structure


def map_equity_structure_row(row: Any) -> EquityStructureDTO:
    ctx = "equity_structure"
    return EquityStructureDTO(
        provider_symbol=str(_required(row, "SECURITY_CODE", context=ctx)),
        report_date=_required_date(row, "REPORT_DATE", "TRADE_DATE", context=ctx),
        total_shares=_to_float(first_present(row, "TOTAL_SHARE")),
        float_a_shares=_to_float(first_present(row, "FLOAT_A_SHARE")),
        # B6 assessment records the ACTUAL provider semantics for each field
        provider_field_meanings=None,
    )
