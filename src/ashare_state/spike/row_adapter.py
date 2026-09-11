"""In-memory adapters for provider row identity, dates, and field views.

The AmazingData spike payloads are provider-faithful and are not required to
use the canonical mapper's field names.  In particular, status payloads may
carry a full ``MARKET_CODE`` such as ``600518.SH`` without a separate
``SECURITY_CODE``, historical code lists may be a one-column ``value`` list,
and daily bars may use lower-case field names.  The spike validators consume
these helpers without changing or reserializing the raw evidence.

The canonical views in this module are ephemeral clones.  They never modify
the provider payload that is persisted as evidence and deliberately do not
infer missing semantic fields.  A scalar ``value`` is used as an identity
only when it is the sole row field and is a fully suffixed provider symbol;
malformed or ambiguous rows return an empty identity or raise the explicit
shape error documented below so the caller remains fail-closed.
"""

from __future__ import annotations

from typing import Any

from ashare_state.providers.amazingdata.mapper import normalize_provider_symbol
from ashare_state.providers.errors import MappingValidationError

__all__ = [
    "ProviderRowShapeError",
    "canonical_daily_bar_view",
    "canonical_status_view",
    "date_key",
    "first_case_insensitive",
    "first_present",
    "provider_symbol",
    "row_date",
]


_MARKET_SUFFIX = {
    "1": ".SH",
    "2": ".SZ",
    "3": ".BJ",
    "SH": ".SH",
    "SZ": ".SZ",
    "BJ": ".BJ",
}

_SUFFIX_MARKET = {"SH": "1", "SZ": "2", "BJ": "3"}


class ProviderRowShapeError(ValueError):
    """A provider row cannot enter a semantic canonical view safely.

    This is intentionally separate from a provider transport/schema error:
    the exchange may have succeeded, but the returned row identity is
    ambiguous or incomplete for the semantic consumer.  Callers must record
    the successful raw exchange and turn this into a structured fail-closed
    outcome; they must not guess a symbol or silently drop the row.
    """


def first_present(row: dict[str, Any], *names: str) -> Any:
    """Return the first named field whose value is not ``None``.

    Empty strings and numeric zero are preserved as present values.  This is
    the same presence rule used by the strict provider mappers and prevents a
    legal zero from being accidentally replaced by a fallback field.
    """
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def first_case_insensitive(row: dict[str, Any], *names: str) -> Any:
    """Return the first present field using canonical-name priority.

    The provider has emitted both upper- and lower-case variants of daily
    bar/status fields.  Matching is case-insensitive, while aliases with
    different spellings (for example ``PRECLOSE``/``pre_close``) are listed
    explicitly by each canonical view.
    """
    for name in names:
        value = first_present(row, name)
        if value is not None:
            return value
        folded = name.casefold()
        for key, candidate in row.items():
            if str(key).casefold() == folded and candidate is not None:
                return candidate
    return None


def date_key(value: Any) -> str:
    """Return a canonical ``YYYYMMDD`` key from a provider date value.

    Daily-bar providers can return a timestamp in ``KLINE_TIME`` while the
    Golden case and trading-calendar contracts use an eight-digit date.  A
    value with fewer than eight digits is rejected rather than padded or
    replaced by a sentinel.
    """
    if value is None or value == "":
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def row_date(row: dict[str, Any], *names: str) -> str:
    """Extract a canonical date from one of the supplied row fields."""
    fields = names or ("TRADE_DATE", "trade_date", "KLINE_TIME", "kline_time")
    return date_key(first_case_insensitive(row, *fields))


def _full_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." not in text:
        return ""
    try:
        return normalize_provider_symbol(text)
    except MappingValidationError:
        return ""


def provider_symbol(row: dict[str, Any]) -> str:
    """Resolve a provider symbol from native or canonical row identity.

    Accepted identity forms are:

    * ``SECURITY_CODE``/``code`` plus numeric or textual market code;
    * a full suffixed symbol in ``SECURITY_CODE`` or ``MARKET_CODE``; and
    * a sole ``value`` field containing a full suffixed symbol, which is the
      explicit scalar-list shape of ``get_hist_code_list``.

    If both code and full-symbol fields are present but disagree, the result
    is empty so a caller cannot validate against the wrong security.
    """
    code_fields = _present_values(row, "SECURITY_CODE", "security_code", "code")
    market_fields = _present_values(row, "MARKET_CODE", "market_code", "market")
    if _identity_fields_conflict(code_fields, kind="code") or _identity_fields_conflict(
        market_fields, kind="market"
    ):
        return ""
    code_raw = code_fields[0] if code_fields else None
    market_raw = market_fields[0] if market_fields else None
    code_text = str(code_raw or "").strip()
    market_text = str(market_raw or "").strip().upper()

    code_full = _full_symbol(code_text)
    market_full = _full_symbol(market_text)
    if code_full and market_full and code_full != market_full:
        return ""
    if code_full:
        if market_text and not market_full:
            market_suffix = _MARKET_SUFFIX.get(market_text)
            if market_suffix is None or not code_full.endswith(market_suffix):
                return ""
        return code_full
    if market_full:
        if code_text and code_text != market_full.split(".", 1)[0]:
            return ""
        return market_full

    # Some documented event payloads expose only MARKET_CODE, but the value
    # is the bare security code (for example ``600519``); the numeric market
    # discriminator is only one digit in the status contract.  Preserve this
    # explicit single-field code without inventing an exchange suffix.
    if not code_text and market_text.isdigit() and len(market_text) > 1:
        return market_text

    if code_text:
        suffix = _MARKET_SUFFIX.get(market_text)
        if suffix:
            if not code_text.isdigit():
                return ""
            return f"{code_text}{suffix}"
        if market_text:
            return ""
        # Keep a bare numeric identity available for validators that
        # intentionally accept rows without market information.  A malformed
        # non-numeric value must not become a security identity.
        return code_text if code_text.isdigit() else ""

    # Only the documented scalar-list row shape may use ``value``.  Never
    # select an arbitrary first field from a multi-column provider row.
    if len(row) == 1 and str(next(iter(row))).casefold() == "value":
        return _full_symbol(next(iter(row.values())))
    return ""


def _present_values(row: dict[str, Any], *names: str) -> list[Any]:
    """Collect non-null values for a case-insensitive alias group."""
    wanted = {name.casefold() for name in names}
    return [
        value for key, value in row.items() if str(key).casefold() in wanted and value is not None
    ]


def _identity_fields_conflict(values: list[Any], *, kind: str) -> bool:
    """Detect contradictory duplicate identity fields without normalizing away
    a legitimate bare-code/full-symbol pair in the security-code group."""
    if len(values) < 2:
        return False
    first = str(values[0]).strip().upper()
    for raw in values[1:]:
        current = str(raw).strip().upper()
        if kind == "code":
            first_full = _full_symbol(first)
            current_full = _full_symbol(current)
            if first_full and current_full:
                if first_full != current_full:
                    return True
                continue
            if first_full:
                if current != first_full.split(".", 1)[0]:
                    return True
                continue
            if current_full:
                if first != current_full.split(".", 1)[0]:
                    return True
                continue
        if kind == "market":
            first_full = _full_symbol(first)
            current_full = _full_symbol(current)
            if first_full or current_full:
                # A full security symbol and a separate market discriminator
                # are two different identity shapes, not interchangeable
                # aliases.  Two equal full symbols are safe.
                return first_full != current_full
            first_market = _MARKET_SUFFIX.get(first, first)
            current_market = _MARKET_SUFFIX.get(current, current)
            if current_market != first_market:
                return True
            continue
        if current != first:
            return True
    return False


_STATUS_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "TRADE_DATE": ("TRADE_DATE", "trade_date"),
    "PRECLOSE": ("PRECLOSE", "pre_close"),
    "HIGH_LIMITED": ("HIGH_LIMITED",),
    "LOW_LIMITED": ("LOW_LIMITED",),
    "CLOSE_PRICE": ("CLOSE_PRICE", "CLOSE"),
    "IS_ST_SEC": ("IS_ST_SEC",),
    "IS_SUSP_SEC": ("IS_SUSP_SEC",),
    "IS_WD_SEC": ("IS_WD_SEC",),
}


def canonical_status_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create the one canonical status view consumed by semantic validators.

    Native status payloads may put an exchange-qualified symbol in
    ``MARKET_CODE`` and omit ``SECURITY_CODE``.  Each accepted row is cloned
    and receives a bare ``SECURITY_CODE``, numeric ``MARKET_CODE`` (1=SH,
    2=SZ, 3=BJ), ``EXCHANGE_CODE`` and ``PROVIDER_SYMBOL``.  The view also
    canonicalizes status dates/known fields.  An empty response remains an
    empty response; an identity/date that cannot be proven is a loud shape
    error rather than a guessed mapping.
    """
    view: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProviderRowShapeError(f"status row {index} is not a mapping")
        symbol = provider_symbol(row)
        if "." not in symbol:
            raise ProviderRowShapeError(
                f"status row {index} has ambiguous or missing exchange-qualified identity"
            )
        code, suffix = symbol.rsplit(".", 1)
        trade_date = row_date(row, "TRADE_DATE", "trade_date")
        if not trade_date:
            raise ProviderRowShapeError(f"status row {index} has missing or invalid TRADE_DATE")
        canonical = dict(row)
        canonical["SECURITY_CODE"] = code
        canonical["MARKET_CODE"] = _SUFFIX_MARKET[suffix]
        canonical["EXCHANGE_CODE"] = suffix
        canonical["PROVIDER_SYMBOL"] = symbol
        for field_name, aliases in _STATUS_FIELD_ALIASES.items():
            value = first_case_insensitive(row, *aliases)
            if value is not None:
                canonical[field_name] = value
        canonical["TRADE_DATE"] = trade_date
        view.append(canonical)
    return view


_DAILY_BAR_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "CLOSE_PRICE": ("CLOSE_PRICE", "CLOSE"),
    "VOLUME": ("VOLUME",),
    "AMOUNT": ("AMOUNT",),
    "KLINE_TIME": ("KLINE_TIME", "TRADE_DATE", "DATE"),
}


def canonical_daily_bar_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clone daily-bar rows with a case-insensitive canonical field contract.

    The adapter exposes ``CLOSE_PRICE``, ``VOLUME``, ``AMOUNT`` and a
    normalized ``TRADE_DATE`` to observation code while retaining every raw
    field in the clone.  Missing fields are not invented and ambiguous bar
    identity is left empty for the caller to classify.
    """
    view: list[dict[str, Any]] = []
    for row in rows:
        canonical = dict(row)
        for field_name, aliases in _DAILY_BAR_FIELD_ALIASES.items():
            value = first_case_insensitive(row, *aliases)
            if value is not None:
                canonical[field_name] = value
        day = date_key(canonical.get("KLINE_TIME"))
        if day:
            canonical["TRADE_DATE"] = day
        symbol = provider_symbol(row)
        if symbol:
            canonical["PROVIDER_SYMBOL"] = symbol
        view.append(canonical)
    return view
