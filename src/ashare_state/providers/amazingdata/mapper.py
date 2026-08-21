"""Provider DataFrame -> DTO mappers (task book sections 1.3 / 7).

Mappers are DEFENSIVE by design: SDK response shapes are verified during
Spike B2-B7 on the real account; until then every column access tolerates
absence (None) and records what was seen. Column names follow the manual;
any drift fails loudly in tests once real fixtures are captured.

Task book 1.3 routing rule lives here: get_history_stock_status maps to
THREE domain DTOs (SecurityStatusDTO projection + LimitPriceDTO
projection + corporate-action flags) - never a single merged DTO.
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


def _col(row: Any, name: str) -> Any:
    """DataFrame row / dict access with explicit None for absence."""
    try:
        if hasattr(row, "get"):
            return row.get(name)
        return row[name]
    except (KeyError, IndexError, TypeError):
        return None


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


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


# ------------------------------------------------------------- calendar


def map_trade_calendar(market: str, trading_days: list[Any]) -> TradeCalendarDTO:
    days = [d for d in (_to_date(v) for v in trading_days) if d is not None]
    return TradeCalendarDTO(market=market, trading_days=days)


# -------------------------------------------------------- security master


def map_security_master_row(row: Any, *, source: str) -> SecurityMasterDTO:
    symbol = str(_col(row, "SECURITY_CODE") or _col(row, "code") or "")
    market = str(_col(row, "MARKET_CODE") or _col(row, "market") or "")
    suffix = {"1": ".SH", "2": ".SZ", "3": ".BJ"}.get(market, "")
    return SecurityMasterDTO(
        provider_symbol=f"{symbol}{suffix}" if suffix else symbol,
        security_code=symbol,
        market_code=market,
        security_type=str(_col(row, "SECURITY_TYPE") or source),
        security_name=_col(row, "SECURITY_NAME_ABBR") or _col(row, "SECURITY_NAME"),
        list_date=_to_date(_col(row, "LISTING_DATE")),
        delist_date=_to_date(_col(row, "DELISTING_DATE")),
        is_listed=_to_int(_col(row, "IS_LISTED")),
        st_flag=_to_int(_col(row, "IS_ST")),
    )


# ------------------------------------------------------------------ bars


def map_daily_bar_row(row: Any, *, kline_type: str = "DAY") -> DailyBarDTO:
    symbol = str(_col(row, "SECURITY_CODE") or _col(row, "code") or "")
    return DailyBarDTO(
        provider_symbol=symbol,
        kline_type=str(_col(row, "KLINE_TYPE") or kline_type),
        kline_time=_to_int(_col(row, "KLINE_TIME") or _col(row, "kline_time")) or 0,
        open=_to_float(_col(row, "OPEN_PRICE") or _col(row, "open")) or 0.0,
        high=_to_float(_col(row, "HIGH_PRICE") or _col(row, "high")) or 0.0,
        low=_to_float(_col(row, "LOW_PRICE") or _col(row, "low")) or 0.0,
        close=_to_float(_col(row, "CLOSE_PRICE") or _col(row, "close")) or 0.0,
        pre_close=_to_float(_col(row, "PRE_CLOSE_PRICE")),
        volume=_to_float(_col(row, "VOLUME") or _col(row, "volume")) or 0.0,
        amount=_to_float(_col(row, "AMOUNT") or _col(row, "amount")) or 0.0,
    )


# ------------------------------------------------- status -> THREE domains


def map_security_status_row(row: Any) -> SecurityStatusDTO:
    return SecurityStatusDTO(
        market_code=str(_col(row, "MARKET_CODE") or ""),
        security_code=str(_col(row, "SECURITY_CODE") or ""),
        trade_date=_to_date(_col(row, "TRADE_DATE")) or date(1970, 1, 1),
        pre_close=_to_float(_col(row, "PRECLOSE")),
        high_limited=_to_float(_col(row, "HIGH_LIMITED")),
        low_limited=_to_float(_col(row, "LOW_LIMITED")),
        price_high_lmt_rate=_to_float(_col(row, "PRICE_HIGH_LMT_RATE")),
        price_low_lmt_rate=_to_float(_col(row, "PRICE_LOW_LMT_RATE")),
        is_st_sec=_to_int(_col(row, "IS_ST_SEC")),
        is_susp_sec=_to_int(_col(row, "IS_SUSP_SEC")),
        is_wd_sec=_to_int(_col(row, "IS_WD_SEC")),
        is_xr_sec=_to_int(_col(row, "IS_XR_SEC")),
    )


def project_limit_price(status: SecurityStatusDTO) -> LimitPriceDTO:
    """Limit-price domain projection (task book 1.3: separate fact owner)."""
    suffix = {"1": ".SH", "2": ".SZ", "3": ".BJ"}.get(status.market_code, "")
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
    suffix = {"1": ".SH", "2": ".SZ", "3": ".BJ"}.get(status.market_code, "")
    symbol = f"{status.security_code}{suffix}"
    is_xr = bool(status.is_xr_sec) if status.is_xr_sec is not None else False
    is_wd = bool(status.is_wd_sec) if status.is_wd_sec is not None else False
    return symbol, status.trade_date, is_wd, is_xr


# ---------------------------------------------------------------- factors


def map_adj_factor_row(row: Any, *, factor_type: str) -> AdjFactorDTO:
    return AdjFactorDTO(
        provider_symbol=str(_col(row, "SECURITY_CODE") or ""),
        ex_date=_to_date(_col(row, "EX_DATE")) or date(1970, 1, 1),
        adj_factor=_to_float(_col(row, "EX_FACTOR")) or 0.0,
        backward_factor=_to_float(_col(row, "CUM_FACTOR")),
        factor_type=factor_type,
    )


# --------------------------------------------------------------- industry


def map_industry_member_row(row: Any) -> IndustryMemberDTO:
    in_date = _to_date(_col(row, "INDUSTRY_IN_DATE") or _col(row, "IN_DATE"))
    return IndustryMemberDTO(
        provider_symbol=str(_col(row, "SECURITY_CODE") or ""),
        industry_code=str(_col(row, "INDUSTRY_CODE") or ""),
        industry_level=_to_int(_col(row, "INDUSTRY_LEVEL")),
        in_date=in_date,
        out_date=_to_date(_col(row, "INDUSTRY_OUT_DATE") or _col(row, "OUT_DATE")),
        current_sign=_to_int(_col(row, "CURRENT_SIGN")),
        taxonomy_owner="GALAXY_UNVERIFIED",  # task book B6: until proven SW
    )


# ------------------------------------------------------------------ index


def map_index_daily_row(row: Any) -> IndexDailyDTO:
    return IndexDailyDTO(
        index_code=str(_col(row, "INDEX_CODE") or _col(row, "SECURITY_CODE") or ""),
        trade_date=_to_date(_col(row, "TRADE_DATE") or _col(row, "KLINE_TIME")) or date(1970, 1, 1),
        open=_to_float(_col(row, "OPEN_PRICE")),
        high=_to_float(_col(row, "HIGH_PRICE")),
        low=_to_float(_col(row, "LOW_PRICE")),
        close=_to_float(_col(row, "CLOSE_PRICE")),
        pre_close=_to_float(_col(row, "PRE_CLOSE_PRICE")),
        volume=_to_float(_col(row, "VOLUME")),
        amount=_to_float(_col(row, "AMOUNT")),
        return_type="UNVERIFIED",  # price vs total-return verified in B6
    )


# -------------------------------------------------------- equity structure


def map_equity_structure_row(row: Any) -> EquityStructureDTO:
    return EquityStructureDTO(
        provider_symbol=str(_col(row, "SECURITY_CODE") or ""),
        report_date=_to_date(_col(row, "REPORT_DATE") or _col(row, "TRADE_DATE"))
        or date(1970, 1, 1),
        total_shares=_to_float(_col(row, "TOTAL_SHARE")),
        float_a_shares=_to_float(_col(row, "FLOAT_A_SHARE")),
        # B6 assessment records the ACTUAL provider semantics for each field
        provider_field_meanings=None,
    )
