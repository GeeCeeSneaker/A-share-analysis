"""In-memory adapters for provider row identity and date fields.

The AmazingData spike payloads are provider-faithful and are not required to
use the canonical mapper's field names.  In particular, status payloads may
carry a full ``MARKET_CODE`` such as ``600518.SH`` without a separate
``SECURITY_CODE``, historical code lists may be a one-column ``value`` list,
and daily bars may use lower-case field names.  The spike validators consume
these helpers without changing or reserializing the raw evidence.

This module deliberately does not infer missing semantic fields.  A scalar
``value`` is used as an identity only when it is the sole row field and is a
fully suffixed provider symbol; malformed or ambiguous rows return an empty
identity so the caller remains fail-closed.
"""

from __future__ import annotations

from typing import Any

from ashare_state.providers.amazingdata.mapper import normalize_provider_symbol
from ashare_state.providers.errors import MappingValidationError

__all__ = [
    "date_key",
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
    return date_key(first_present(row, *fields))


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
    code_raw = first_present(row, "SECURITY_CODE", "security_code", "code")
    market_raw = first_present(row, "MARKET_CODE", "market_code", "market")
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
    if set(row) == {"value"}:
        return _full_symbol(row.get("value"))
    return ""
