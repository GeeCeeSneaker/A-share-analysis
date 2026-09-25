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
_SUFFIX_MARKET = {suffix: market for market, suffix in _MARKET_SUFFIX.items()}
_SECURITY_CODE_LENGTH = 6
_PROVIDER_INDEX_FIELDS = (
    "__index_level_0__",  # pandas unnamed Index preserved by RawWriter
    "index",
    "symbol",
)
_EXPLICIT_SECURITY_IDENTITY_FIELDS = (
    "SECURITY_CODE",
    "code",
    "security_code",
    "PROVIDER_SYMBOL",
    "provider_symbol",
)
_SECURITY_IDENTITY_FIELDS = (
    *_EXPLICIT_SECURITY_IDENTITY_FIELDS,
    *_PROVIDER_INDEX_FIELDS,
)


def normalize_provider_symbol(code: str, market_code: str | None = None) -> str:
    """ProviderSymbolNormalizer (audit R2-P1-05): the SINGLE rule producing
    canonical provider symbols `600000.SH` / `000001.SZ` / `830799.BJ`.

    - bare code + market code -> suffixed symbol
    - already-suffixed symbol -> validated and returned unchanged
    - unknown market -> MappingValidationError
    """
    text = str(code).strip()
    if "." in text:
        bare, _, suffix = text.partition(".")
        if f".{suffix}" not in _MARKET_SUFFIX.values():
            raise MappingValidationError(
                f"provider symbol {text!r}: unknown suffix {suffix!r} "
                f"(expected one of {sorted(_MARKET_SUFFIX.values())})"
            )
        if not bare.isdigit():
            raise MappingValidationError(f"provider symbol {text!r}: non-numeric code")
        return text
    market = str(market_code or "")
    market_suffix = _MARKET_SUFFIX.get(market)
    if market_suffix is None:
        raise MappingValidationError(
            f"cannot normalize bare code {text!r}: unknown/missing market "
            f"code {market!r} (expected one of {sorted(_MARKET_SUFFIX)})"
        )
    if not text.isdigit():
        raise MappingValidationError(f"provider symbol {text!r}: non-numeric code")
    return f"{text}{market_suffix}"


def _security_master_identity(row: Any, *, context: str) -> tuple[str, str, str]:
    """Resolve a security-master identity without request-order inference.

    AmazingData ``stock_basic`` can expose the provider symbol as the
    DataFrame index rather than a named column, or in the observed
    ``MARKET_CODE`` literal.  RawWriter preserves a non-default index; this
    helper accepts only an explicit provider code field, that verified
    suffixed ``MARKET_CODE`` carrier, or one of the preserved index names.
    A bare/default index value is not a valid identity unless it is a
    six-digit provider code and an explicit market is present.
    """
    explicit_code = first_present(row, *_EXPLICIT_SECURITY_IDENTITY_FIELDS)
    index_code = first_present(row, *_PROVIDER_INDEX_FIELDS)
    raw_market = first_present(row, "MARKET_CODE", "market")
    market_text = "" if raw_market is None else str(raw_market).strip()

    # The observed stock_basic response calls its full provider symbol
    # ``MARKET_CODE``.  Treat only a dotted, suffix-valid value in that
    # literal as an identity carrier; bare MARKET_CODE values remain market
    # enums (1/2/3) and still require a separate code/index.
    market_identity: tuple[str, str, str | None] | None = None
    if "." in market_text:
        market_identity = _parse_security_identity(market_text, context=context)
    if explicit_code is not None:
        raw_code = explicit_code
    elif market_identity is not None:
        # The observed stock_basic response uses MARKET_CODE for the full
        # provider symbol.  Prefer that verified carrier over the duplicate
        # integer index produced by the SDK's batch concat.
        raw_code = market_text
    else:
        raw_code = index_code

    if raw_code is None:
        _required(row, *_SECURITY_IDENTITY_FIELDS, context=context)
    provider_symbol, bare, inferred_market = _parse_security_identity(raw_code, context=context)

    if market_identity is not None:
        carrier_symbol, carrier_bare, carrier_market = market_identity
        if bare != carrier_bare:
            raise MappingValidationError(
                f"{context}: security identity {provider_symbol!r} conflicts with "
                f"MARKET_CODE carrier {carrier_symbol!r}"
            )
        if inferred_market is not None and inferred_market != carrier_market:
            raise MappingValidationError(
                f"{context}: provider symbol market {inferred_market!r} conflicts "
                f"with MARKET_CODE carrier {carrier_market!r}"
            )
        inferred_market = carrier_market
        if explicit_code is None and index_code is not None:
            # A valid provider index is additional identity evidence and
            # must agree.  Synthetic/non-provider indexes (e.g. the SDK's
            # repeated zero after batch concat) are retained in raw evidence
            # but are not treated as a security identity.
            try:
                _, index_bare, index_market = _parse_security_identity(index_code, context=context)
            except MappingValidationError:
                pass
            else:
                if index_bare != carrier_bare or (
                    index_market is not None and index_market != carrier_market
                ):
                    raise MappingValidationError(
                        f"{context}: provider index identity conflicts with "
                        f"MARKET_CODE carrier {carrier_symbol!r}"
                    )

    market = market_text if market_identity is None else ""
    if market:
        if market not in _MARKET_SUFFIX:
            raise MappingValidationError(
                f"{context}: unknown/missing MARKET_CODE {market!r}; "
                "provider symbol normalization requires a known market "
                f"(one of {sorted(_MARKET_SUFFIX)})"
            )
        if inferred_market is not None and market != inferred_market:
            raise MappingValidationError(
                f"{context}: provider symbol market {inferred_market!r} conflicts "
                f"with MARKET_CODE {market!r}"
            )
    elif inferred_market is not None:
        market = inferred_market
    else:
        raise MappingValidationError(
            f"{context}: unknown/missing MARKET_CODE; provider symbol normalization "
            f"requires a known market (one of {sorted(_MARKET_SUFFIX)})"
        )

    if not provider_symbol:
        provider_symbol = normalize_provider_symbol(bare, market)
    return provider_symbol, bare, market


def _parse_security_identity(value: Any, *, context: str) -> tuple[str, str, str | None]:
    """Parse one explicit bare or suffixed provider identity."""
    text = str(value).strip()
    if not text:
        raise MappingValidationError(f"{context}: security code is empty")
    if "." in text:
        bare, _, suffix = text.partition(".")
        provider_symbol = normalize_provider_symbol(text)
        inferred_market = _SUFFIX_MARKET.get(f".{suffix}")
        if inferred_market is None:
            # normalize_provider_symbol already rejects this; keep the
            # branch explicit for the tuple contract below.
            raise MappingValidationError(f"{context}: unknown provider market suffix")
        if len(bare) != _SECURITY_CODE_LENGTH or not bare.isdigit():
            raise MappingValidationError(
                f"{context}: security code {bare!r} is not a six-digit numeric code"
            )
        return provider_symbol, bare, inferred_market
    if len(text) != _SECURITY_CODE_LENGTH or not text.isdigit():
        raise MappingValidationError(
            f"{context}: security code {text!r} is not a six-digit numeric code"
        )
    return "", text, None


def validate_provider_symbol(value: Any, *, context: str) -> tuple[str, str, str]:
    """Validate and split one provider-owned suffixed symbol."""
    return _security_master_identity({"PROVIDER_SYMBOL": value}, context=context)


def _col(row: Any, name: str) -> Any:
    """DataFrame row / dict access with explicit None for absence."""
    try:
        if hasattr(row, "get"):
            return row.get(name)
        return row[name]
    except KeyError, IndexError, TypeError:
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
    except TypeError, ValueError:
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


def _to_kline_time(value: Any) -> int | None:
    """Convert the provider's daily-bar date/time field to YYYYMMDD.

    Date-like handling is deliberately local to ``KLINE_TIME``.  The generic
    integer mapper must not reinterpret date objects supplied to unrelated
    numeric fields as integers.
    """
    if isinstance(value, date):
        return int(value.strftime("%Y%m%d"))
    return _to_int(value)


# ------------------------------------------------------------- calendar


def map_trade_calendar(market: str, trading_days: list[Any]) -> TradeCalendarDTO:
    """Strict calendar (R2-P1-05): ONE unparsable date quarantines the WHOLE
    response - the calendar underpins PIT/rolling/prev-next logic and must
    never be silently filtered."""
    days: list[date] = []
    for value in trading_days:
        parsed = _to_date(value)
        if parsed is None:
            raise MappingValidationError(
                f"trade_calendar({market}): unparsable trading day {value!r}; "
                "whole payload quarantined (audit R2-P1-05)"
            )
        days.append(parsed)
    return TradeCalendarDTO(market=market, trading_days=days)


# -------------------------------------------------------- security master


def map_security_master_row(row: Any, *, source: str) -> SecurityMasterDTO:
    provider_symbol, symbol, market = _security_master_identity(row, context="security_master")
    return SecurityMasterDTO(
        provider_symbol=provider_symbol,
        security_code=symbol,
        market_code=market,
        security_type=str(first_present(row, "SECURITY_TYPE") or source),
        security_name=first_present(row, "SECURITY_NAME_ABBR", "SECURITY_NAME"),
        list_date=_to_date(first_present(row, "LISTING_DATE", "LISTDATE")),
        delist_date=_to_date(first_present(row, "DELISTING_DATE", "DELISTDATE")),
        is_listed=_to_int(first_present(row, "IS_LISTED")),
        st_flag=_to_int(first_present(row, "IS_ST")),
    )


def map_security_master_symbol(value: Any, *, source: str) -> SecurityMasterDTO:
    """Map the provider's scalar code-list member into one master row.

    The historical code-list endpoint returns suffixed provider symbols as
    ``list[str]``.  It proves membership only; no listing date is invented
    here, so PIT identity still depends on a separately verified
    ``stock_basic`` row.
    """
    return map_security_master_row(
        {"value": value, "PROVIDER_SYMBOL": value},
        source=source,
    )


# ------------------------------------------------------------------ bars


def map_daily_bar_row(row: Any, *, kline_type: str = "DAY") -> DailyBarDTO:
    ctx = "daily_bar"
    bare = str(_required(row, "SECURITY_CODE", "code", context=ctx))
    market = str(first_present(row, "MARKET_CODE", "market") or "")
    # R2-P1-05: daily bar symbols normalize through the SAME rule as
    # security master (600000 -> 600000.SH), never left bare
    symbol = normalize_provider_symbol(bare, market or None)
    kline_time = _to_kline_time(first_present(row, "KLINE_TIME", "kline_time"))
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


def map_daily_bar_member_row(row: Any, *, member_key_field: str) -> DailyBarDTO:
    """Map one row from AmazingData's ``symbol -> DataFrame`` response.

    The member key is the provider's explicit response identity.  It is
    accepted only after suffix validation and is cross-checked against any
    code already present in the row; request order and first-table selection
    are never used.
    """
    member_key = _required(row, member_key_field, context="daily_bar member map")
    member_symbol, member_code, member_market = validate_provider_symbol(
        member_key, context="daily_bar member map"
    )
    adapted = dict(row)
    if first_present(adapted, "MARKET_CODE", "market") is None:
        adapted["MARKET_CODE"] = member_market
    row_code = first_present(adapted, *_EXPLICIT_SECURITY_IDENTITY_FIELDS)
    row_index = first_present(adapted, *_PROVIDER_INDEX_FIELDS)
    row_market = first_present(adapted, "MARKET_CODE", "market")
    has_row_identity = row_code is not None or (
        row_market is not None and "." in str(row_market).strip()
    )
    if not has_row_identity and row_index is not None:
        try:
            _parse_security_identity(row_index, context="daily_bar member row")
        except MappingValidationError:
            pass
        else:
            has_row_identity = True
    if has_row_identity:
        row_symbol, row_bare, row_market_code = _security_master_identity(
            adapted, context="daily_bar member row"
        )
        if row_symbol != member_symbol:
            raise MappingValidationError(
                "daily_bar member map: row security identity conflicts with "
                f"member key {member_symbol!r}"
            )
        adapted["SECURITY_CODE"] = row_bare
        adapted["MARKET_CODE"] = row_market_code
    else:
        if str(row_market) != member_market:
            raise MappingValidationError(
                f"daily_bar member map: row market conflicts with member key {member_symbol!r}"
            )
        adapted["SECURITY_CODE"] = member_code
    return map_daily_bar_row(adapted)


# ------------------------------------------------- status -> THREE domains


_STATUS_IDENTITY_FIELDS = (
    "PROVIDER_SYMBOL",
    "provider_symbol",
    "SECURITY_CODE",
    "security_code",
    "code",
)
_STATUS_MARKET_FIELDS = ("MARKET_CODE", "market_code", "market")
_STATUS_MEMBER_KEY_FIELD = "_TABLE_KEY"
_STATUS_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "TRADE_DATE": ("TRADE_DATE", "trade_date"),
    "PRECLOSE": ("PRECLOSE", "pre_close"),
    "HIGH_LIMITED": ("HIGH_LIMITED", "high_limited"),
    "LOW_LIMITED": ("LOW_LIMITED", "low_limited"),
    "CLOSE_PRICE": ("CLOSE_PRICE", "CLOSE", "close_price", "close"),
    "PRICE_HIGH_LMT_RATE": ("PRICE_HIGH_LMT_RATE", "price_high_lmt_rate"),
    "PRICE_LOW_LMT_RATE": ("PRICE_LOW_LMT_RATE", "price_low_lmt_rate"),
    "IS_ST_SEC": ("IS_ST_SEC", "is_st_sec"),
    "IS_SUSP_SEC": ("IS_SUSP_SEC", "is_susp_sec"),
    "IS_WD_SEC": ("IS_WD_SEC", "is_wd_sec"),
    "IS_XR_SEC": ("IS_XR_SEC", "is_xr_sec"),
}
_STATUS_ROW_FIELDS = frozenset(
    field.casefold()
    for aliases in (*_STATUS_FIELD_ALIASES.values(), _STATUS_IDENTITY_FIELDS, _STATUS_MARKET_FIELDS)
    for field in aliases
)
_STATUS_MARKET_ALIASES = {"SH": "1", "SZ": "2", "BJ": "3"}


def _case_insensitive_values(row: dict[str, Any], names: tuple[str, ...]) -> list[Any]:
    accepted = {name.casefold() for name in names}
    return [
        value for key, value in row.items() if str(key).casefold() in accepted and value is not None
    ]


def _case_insensitive_first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        for key, value in row.items():
            if str(key).casefold() == name.casefold() and value is not None:
                return value
    return None


def _status_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    context = "security_status"
    market_codes: set[str] = set()
    market_symbols: set[str] = set()
    for raw_market in _case_insensitive_values(row, _STATUS_MARKET_FIELDS):
        text = str(raw_market).strip().upper()
        if "." in text:
            symbol, _code, _market = _parse_security_identity(text, context=context)
            market_symbols.add(symbol)
        else:
            market = _STATUS_MARKET_ALIASES.get(text, text)
            if market not in _MARKET_SUFFIX:
                raise MappingValidationError(
                    f"{context}: unsupported MARKET_CODE {text!r}; expected SH/SZ/BJ or 1/2/3"
                )
            market_codes.add(market)
    if len(market_codes) > 1:
        raise MappingValidationError(f"{context}: conflicting market-code fields")

    resolved_symbols: set[str] = set(market_symbols)
    for raw_identity in _case_insensitive_values(row, _STATUS_IDENTITY_FIELDS):
        symbol, code, inferred_market = _parse_security_identity(
            str(raw_identity).strip().upper(), context=context
        )
        market = inferred_market or next(iter(market_codes), None)
        if market is None:
            raise MappingValidationError(f"{context}: row identity has no exchange")
        if inferred_market is not None and market_codes and inferred_market not in market_codes:
            raise MappingValidationError(f"{context}: row identity conflicts with MARKET_CODE")
        resolved_symbols.add(symbol or normalize_provider_symbol(code, market))

    if len(resolved_symbols) != 1:
        raise MappingValidationError(
            f"{context}: missing or conflicting independently embedded security identity"
        )
    symbol = next(iter(resolved_symbols))
    code, suffix = symbol.rsplit(".", 1)
    market = _SUFFIX_MARKET[f".{suffix}"]
    if market_codes and market not in market_codes:
        raise MappingValidationError(f"{context}: row identity conflicts with MARKET_CODE")
    return symbol, code, market


def _status_table_member_rows(member: Any, *, context: str) -> list[dict[str, Any]]:
    if member is None:
        return []
    if isinstance(member, dict):
        return [dict(member)] if member else []
    if isinstance(member, list):
        if any(not isinstance(row, dict) for row in member):
            raise MappingValidationError(f"{context}: status table contains a non-mapping row")
        return [dict(row) for row in member]
    iter_rows = getattr(member, "iter_rows", None)
    if callable(iter_rows) and hasattr(member, "columns"):
        return [dict(row) for row in iter_rows(named=True)]
    rows = getattr(member, "rows", None)
    columns = getattr(member, "columns", None)
    if callable(rows) and columns is not None:
        return [dict(zip(columns, values, strict=True)) for values in rows()]
    to_dict = getattr(member, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict(orient="records")
        except TypeError:
            records = None
        if records is not None and all(isinstance(row, dict) for row in records):
            return [dict(row) for row in records]
    raise MappingValidationError(f"{context}: unsupported status table shape")


def _canonical_status_row(row: dict[str, Any], *, member_symbol: str | None) -> dict[str, Any]:
    symbol, code, market = _status_identity(row)
    if member_symbol is not None and symbol != member_symbol:
        raise MappingValidationError(
            "security_status: embedded identity conflicts with provider table key"
        )

    raw_dates = _case_insensitive_values(row, ("TRADE_DATE", "trade_date"))
    parsed_dates = [_to_date(value) for value in raw_dates]
    if not parsed_dates or any(value is None for value in parsed_dates):
        raise MappingValidationError("security_status: missing or invalid TRADE_DATE")
    if len(set(parsed_dates)) != 1:
        raise MappingValidationError("security_status: conflicting TRADE_DATE fields")
    trade_day = parsed_dates[0]
    assert trade_day is not None

    canonical = dict(row)
    canonical.update(
        {
            "SECURITY_CODE": code,
            "MARKET_CODE": market,
            "EXCHANGE_CODE": symbol.rsplit(".", 1)[1],
            "PROVIDER_SYMBOL": symbol,
            "TRADE_DATE": trade_day.strftime("%Y%m%d"),
        }
    )
    for field, aliases in _STATUS_FIELD_ALIASES.items():
        if field == "TRADE_DATE":
            continue
        value = _case_insensitive_first(row, aliases)
        if value is not None:
            canonical[field] = value
    return canonical


def normalize_status_payload(
    payload: Any, *, request_params: Any = None
) -> tuple[list[dict[str, Any]], list[tuple[str | None, int]], int]:
    """Normalize AmazingData status rows at the production mapper boundary.

    Keyed response tables are flattened without using their keys to invent a
    row identity. Every row must independently carry the same exchange-
    qualified identity as its member key. The returned locators retain table
    and row order for normalization provenance; empty members are counted but
    never converted into negative status facts.
    """
    params = request_params if isinstance(request_params, dict) else {}
    scope_keys = {"begin_date", "end_date", "code_list"}
    requested_symbols: set[str] | None = None
    begin: date | None = None
    end: date | None = None
    if scope_keys.intersection(params):
        if not scope_keys.issubset(params):
            raise MappingValidationError("security_status: incomplete request scope metadata")
        symbols = params["code_list"]
        if (
            not isinstance(symbols, list)
            or not symbols
            or any(not isinstance(value, str) or not value.strip() for value in symbols)
        ):
            raise MappingValidationError("security_status: invalid request symbol list")
        normalized_symbols = [
            validate_provider_symbol(value.strip().upper(), context="security_status request")[0]
            for value in symbols
        ]
        if len(normalized_symbols) != len(set(normalized_symbols)):
            raise MappingValidationError("security_status: duplicate request symbols")
        requested_symbols = set(normalized_symbols)
        begin = _to_date(params["begin_date"])
        end = _to_date(params["end_date"])
        if begin is None or end is None or begin > end:
            raise MappingValidationError("security_status: invalid request date window")

    raw_members: list[tuple[str | None, list[dict[str, Any]]]] = []
    empty_members = 0
    if payload is None:
        return [], [], 0
    if isinstance(payload, dict) and any(
        str(key).casefold() in _STATUS_ROW_FIELDS for key in payload
    ):
        raw_members.append((None, [dict(payload)]))
    elif isinstance(payload, dict):
        for raw_key, member in sorted(payload.items(), key=lambda item: str(item[0]).upper()):
            member_symbol = validate_provider_symbol(
                str(raw_key).strip().upper(), context="security_status table key"
            )[0]
            if requested_symbols is not None and member_symbol not in requested_symbols:
                raise MappingValidationError(
                    "security_status: provider table key is outside request scope"
                )
            member_rows = _status_table_member_rows(
                member, context=f"security_status table {member_symbol}"
            )
            if not member_rows:
                empty_members += 1
            raw_members.append((member_symbol, member_rows))
    else:
        raw_rows = _status_table_member_rows(payload, context="security_status payload")
        if not raw_rows:
            empty_members = 0
        raw_members.append((None, raw_rows))

    rows: list[dict[str, Any]] = []
    locators: list[tuple[str | None, int]] = []
    seen: set[tuple[str, date]] = set()
    for member_symbol, member_rows in raw_members:
        for ordinal, raw_row in enumerate(member_rows):
            canonical = _canonical_status_row(raw_row, member_symbol=member_symbol)
            symbol = canonical["PROVIDER_SYMBOL"]
            trade_day = _to_date(canonical["TRADE_DATE"])
            assert trade_day is not None
            if requested_symbols is not None and symbol not in requested_symbols:
                raise MappingValidationError(
                    "security_status: row identity is outside request scope"
                )
            if begin is not None and end is not None and not begin <= trade_day <= end:
                raise MappingValidationError("security_status: row date is outside request window")
            natural_key = (symbol, trade_day)
            if natural_key in seen:
                raise MappingValidationError("security_status: duplicate natural key")
            seen.add(natural_key)
            rows.append(canonical)
            locators.append((member_symbol, ordinal))
    return rows, locators, empty_members


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
