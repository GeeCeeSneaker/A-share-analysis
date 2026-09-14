"""Reviewed AmazingData acquisition path for CR-7 authoritative history.

This module is the only issuer of a new ``AmazingDataAcquisitionReceipt``.
It performs one complete calendar-month request against the typed provider
facade, validates the response shape/range against the same request, and
persists each exchange through ``RawWriter`` before issuing the receipt.

The module never writes credentials or raw payloads to Git-tracked locations.
The caller must provide a previously verified research snapshot; no free-form
snapshot id/hash/timestamp or completeness label is accepted here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ashare_state.providers.amazingdata.operations import (
    DAILY_BAR_KLINE,
    HIST_CODE_LIST,
    TRADE_CALENDAR,
)
from ashare_state.providers.amazingdata.provider import AmazingDataProvider, RawEnvelope
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.research.historical import (
    AMAZINGDATA_CALENDAR_MARKET,
    AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
    AmazingDataAcquisitionReceipt,
    AmazingDataExchangeReceipt,
    CoverageBasisError,
    PartitionKey,
    VerifiedSourceSnapshot,
    _issue_amazingdata_acquisition_receipt,
    _VerifiedAmazingDataCapture,
)
from ashare_state.research.models import canonical_json, ensure_utc_timestamp, sha256_hex
from ashare_state.storage.atomic_files import write_file_atomic
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter
from ashare_state.storage.raw_writer import RawWriteResult

__all__ = ["AmazingDataHistoryAcquisition", "AmazingDataAcquisitionError"]


class AmazingDataAcquisitionError(CoverageBasisError):
    """A complete-month AmazingData acquisition cannot be accepted."""


_SECURITY_TYPE = AMAZINGDATA_SECURITY_UNIVERSE_SELECTION
_PERIOD_DAY = 10008
_METHOD_SPECS = {
    "BaseData.get_calendar": TRADE_CALENDAR,
    "BaseData.get_hist_code_list": HIST_CODE_LIST,
    "MarketData.query_kline": DAILY_BAR_KLINE,
}
_RESPONSE_SHAPES = {
    "BaseData.get_calendar": "list[int]",
    "BaseData.get_hist_code_list": "list[str]",
    "MarketData.query_kline": "dict[str,dataframe]",
}
_DAILY_BAR_COLUMN_ALIASES = {
    "symbol": ("code", "CODE"),
    "date": ("KLINE_TIME", "kline_time", "TRADE_DATE", "trade_date"),
    "open": ("OPEN_PRICE", "open"),
    "high": ("HIGH_PRICE", "high"),
    "low": ("LOW_PRICE", "low"),
    "close": ("CLOSE_PRICE", "close"),
    "volume": ("VOLUME", "volume"),
    "amount": ("AMOUNT", "amount"),
}


@dataclass(frozen=True)
class AmazingDataHistoryAcquisition:
    """Acquire and validate one complete logical month from AmazingData."""

    provider: AmazingDataProvider
    raw_writer: AnchoredRawEvidenceWriter
    source_snapshot: VerifiedSourceSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.provider, AmazingDataProvider):
            raise AmazingDataAcquisitionError("acquisition requires the typed AmazingData provider")
        if not isinstance(self.raw_writer, AnchoredRawEvidenceWriter):
            raise AmazingDataAcquisitionError(
                "acquisition requires the anchored raw evidence writer"
            )
        if not isinstance(self.source_snapshot, VerifiedSourceSnapshot):
            raise AmazingDataAcquisitionError("acquisition requires a verified source snapshot")

    def acquire_month(self, partition: PartitionKey) -> AmazingDataAcquisitionReceipt:
        """Return a receipt only after all three complete-scope checks pass."""
        if not isinstance(partition, PartitionKey):
            raise AmazingDataAcquisitionError("acquisition requires a typed historical partition")
        start = partition.scope_start
        end = partition.scope_end
        begin = _yyyymmdd(start)
        finish = _yyyymmdd(end)

        calendar_exchange, calendar_receipt = self._exchange(
            "BaseData.get_calendar",
            lambda: self.provider.get_calendar_exchange(AMAZINGDATA_CALENDAR_MARKET),
            expected_params={"market": AMAZINGDATA_CALENDAR_MARKET},
        )
        trading_days = _validate_calendar(calendar_exchange.payload, start=start, end=end)

        code_exchange, code_receipt = self._exchange(
            "BaseData.get_hist_code_list",
            lambda: self.provider.get_hist_code_list_exchange(_SECURITY_TYPE, begin, finish),
            expected_params={
                "security_type": _SECURITY_TYPE,
                "start_date": begin,
                "end_date": finish,
            },
        )
        symbols = _validate_security_universe(code_exchange.payload)

        kline_exchange, kline_receipt = self._exchange(
            "MarketData.query_kline",
            lambda: self.provider.query_kline_exchange(
                symbols,
                begin_date=begin,
                end_date=finish,
                kline_type="DAY",
                trading_days=trading_days,
            ),
            expected_params={
                "code_list": symbols,
                "begin_date": begin,
                "end_date": finish,
                "kline_type": "DAY",
                "period": _PERIOD_DAY,
                "trading_days": trading_days,
            },
        )
        returned = _validate_daily_bars(
            kline_exchange.payload,
            symbols=symbols,
            trading_days=trading_days,
            start=start,
            end=end,
        )
        operations = (calendar_receipt, code_receipt, kline_receipt)
        retrieved_at = max(
            ensure_utc_timestamp(str(getattr(exchange.envelope, "received_at", "")))
            for exchange in (calendar_exchange, code_exchange, kline_exchange)
        )
        capture = _VerifiedAmazingDataCapture._from_provider(  # noqa: SLF001
            requested_scope_start=start,
            requested_scope_end=end,
            security_universe_count=len(symbols),
            security_universe_hash=_hash_values(symbols),
            calendar_trading_day_count=len(trading_days),
            calendar_trading_days_hash=_hash_values(trading_days),
            returned_first_date=returned["first_date"],
            returned_last_date=returned["last_date"],
            returned_trading_day_count=returned["trading_day_count"],
            returned_trading_days_hash=returned["trading_days_hash"],
            returned_row_count=returned["row_count"],
            operations=operations,
            retrieved_at_utc=retrieved_at,
        )
        receipt = _issue_amazingdata_acquisition_receipt(
            source_snapshot=self.source_snapshot,
            capture=capture,
        )
        _persist_capture_catalog(self.raw_writer, receipt)
        try:
            receipt.verify_retained_capture(self.raw_writer.root)
        except CoverageBasisError as exc:
            raise AmazingDataAcquisitionError(
                "AmazingData acquisition proof chain could not be replayed"
            ) from exc
        return receipt

    def _exchange(
        self,
        method: str,
        fn: Any,
        *,
        expected_params: dict[str, Any],
    ) -> tuple[ProviderExchange, AmazingDataExchangeReceipt]:
        try:
            exchange = fn()
        except Exception as exc:  # noqa: BLE001 - provider facade owns raw classification
            raise AmazingDataAcquisitionError(
                f"AmazingData {method} exchange failed; authoritative acquisition is blocked"
            ) from exc
        if not isinstance(exchange, ProviderExchange):
            raise AmazingDataAcquisitionError(
                f"AmazingData {method} did not return ProviderExchange"
            )
        _verify_envelope(exchange, method, expected_params)
        try:
            persisted = self.raw_writer.write_exchange(exchange)
        except Exception as exc:  # noqa: BLE001 - persistence is part of the proof chain
            raise AmazingDataAcquisitionError(
                f"AmazingData {method} raw evidence could not be retained"
            ) from exc
        return exchange, _receipt_for_exchange(method, exchange.envelope, persisted)


def _verify_envelope(
    exchange: ProviderExchange, method: str, expected_params: dict[str, Any]
) -> None:
    envelope = exchange.envelope
    spec = _METHOD_SPECS[method]
    if getattr(envelope, "status", "") != "OK":
        raise AmazingDataAcquisitionError(f"AmazingData {method} returned a non-OK envelope")
    if (
        getattr(envelope, "provider", "") != "amazingdata"
        or getattr(envelope, "endpoint", "") != spec.endpoint
        or getattr(envelope, "provider_dataset", "") != spec.provider_dataset
        or getattr(envelope, "normalization_surface", "") != spec.normalization_surface
        or getattr(envelope, "operation_id", "") != spec.operation_id
    ):
        raise AmazingDataAcquisitionError(f"AmazingData {method} envelope identity changed")
    actual_params = getattr(envelope, "request_params", None)
    if actual_params != expected_params:
        raise AmazingDataAcquisitionError(f"AmazingData {method} request scope changed")
    if getattr(envelope, "request_params_hash", "") != RawEnvelope.params_hash(expected_params):
        raise AmazingDataAcquisitionError(f"AmazingData {method} request hash changed")
    if not getattr(envelope, "received_at", ""):
        raise AmazingDataAcquisitionError(f"AmazingData {method} has no retrieval timestamp")


def _receipt_for_exchange(
    method: str,
    envelope: Any,
    persisted: RawWriteResult,
) -> AmazingDataExchangeReceipt:
    if not persisted.evidence_uri or not persisted.evidence_hash:
        raise AmazingDataAcquisitionError(f"AmazingData {method} lacks retained raw evidence")
    schema_parts = sorted((str(table.name), table.schema_hash) for table in persisted.tables)
    schema_hash = sha256_hex(canonical_json(schema_parts))
    return AmazingDataExchangeReceipt(
        method=method,
        operation_id=str(envelope.operation_id),
        request_params_hash=str(envelope.request_params_hash),
        response_shape=_RESPONSE_SHAPES[method],
        response_schema_hash=schema_hash,
        response_content_hash=persisted.content_hash,
        row_count=int(persisted.row_count),
        captured_evidence_uri=persisted.evidence_uri,
        captured_evidence_hash=persisted.evidence_hash,
    )


def _persist_capture_catalog(
    writer: AnchoredRawEvidenceWriter,
    receipt: AmazingDataAcquisitionReceipt,
) -> None:
    """Persist the catalog before the receipt leaves the acquisition path."""
    catalog_bytes = canonical_json(receipt.capture_catalog()).encode("utf-8")
    if sha256_hex(catalog_bytes) != receipt.source_capture_hash:
        raise AmazingDataAcquisitionError("AmazingData capture catalog hash changed before persist")
    target = writer.root.joinpath(*receipt.source_capture_uri.split("/"))
    try:
        write_file_atomic(
            target,
            catalog_bytes,
            expected_sha256=receipt.source_capture_hash,
            allow_existing_identical=True,
        )
    except Exception as exc:  # noqa: BLE001 - immutable persistence boundary
        raise AmazingDataAcquisitionError(
            "AmazingData capture catalog could not be retained immutably"
        ) from exc
    if not target.is_file() or target.read_bytes() != catalog_bytes:
        raise AmazingDataAcquisitionError("AmazingData capture catalog persistence did not verify")


def _validate_security_universe(payload: Any) -> list[str]:
    if not isinstance(payload, list) or not payload:
        raise AmazingDataAcquisitionError("historical code-list response is not a non-empty list")
    symbols: list[str] = []
    for value in payload:
        if not isinstance(value, str) or not value.strip():
            raise AmazingDataAcquisitionError(
                "historical code-list response contains an invalid code"
            )
        symbol = value.strip()
        if re.fullmatch(r"\d{6}\.(?:SH|SZ)", symbol) is None:
            raise AmazingDataAcquisitionError(
                "historical code-list contains an out-of-scope market"
            )
        symbols.append(symbol)
    if len(symbols) != len(set(symbols)):
        raise AmazingDataAcquisitionError("historical code-list contains duplicate securities")
    return sorted(symbols)


def _validate_calendar(payload: Any, *, start: date, end: date) -> list[int]:
    if not isinstance(payload, list) or not payload:
        raise AmazingDataAcquisitionError("calendar response is not a non-empty list")
    values: list[int] = []
    for value in payload:
        if isinstance(value, bool) or not isinstance(value, int) or len(str(value)) != 8:
            raise AmazingDataAcquisitionError("calendar response contains an invalid date")
        try:
            parsed = date(int(str(value)[:4]), int(str(value)[4:6]), int(str(value)[6:]))
        except ValueError as exc:
            raise AmazingDataAcquisitionError("calendar response contains an invalid date") from exc
        if parsed < start or parsed > end:
            continue
        values.append(value)
    if len(values) != len(set(values)):
        raise AmazingDataAcquisitionError("calendar response contains duplicate dates")
    values.sort()
    if not values:
        raise AmazingDataAcquisitionError("calendar response has no requested-month trading days")
    return values


def _validate_daily_bars(
    payload: Any,
    *,
    symbols: list[str],
    trading_days: list[int],
    start: date,
    end: date,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != set(symbols):
        raise AmazingDataAcquisitionError(
            "daily-bar response security keys do not exactly match the requested universe"
        )
    returned_days: set[int] = set()
    row_count = 0
    for symbol in symbols:
        frame = payload[symbol]
        if frame is None or not hasattr(frame, "columns"):
            raise AmazingDataAcquisitionError(
                "daily-bar response is partial or has an unexpected table shape"
            )
        columns = {str(column) for column in frame.columns}
        selected_columns = {
            name: next((candidate for candidate in aliases if candidate in columns), None)
            for name, aliases in _DAILY_BAR_COLUMN_ALIASES.items()
        }
        if any(value is None for value in selected_columns.values()):
            raise AmazingDataAcquisitionError(
                "daily-bar response is missing a required symbol or OHLCV column"
            )
        symbol_column = selected_columns["symbol"]
        if symbol_column is None:
            raise AmazingDataAcquisitionError("daily-bar response has no validated symbol column")
        symbol_values = _frame_column(frame, symbol_column)
        if not symbol_values or any(str(value).strip() != symbol for value in symbol_values):
            raise AmazingDataAcquisitionError(
                "daily-bar response security identity does not match its response key"
            )
        date_column = selected_columns["date"]
        if date_column is None:
            raise AmazingDataAcquisitionError("daily-bar response has no validated date column")
        values = _frame_column(frame, date_column)
        if not values:
            raise AmazingDataAcquisitionError("daily-bar response contains an empty security table")
        numeric_columns = {
            name: selected_columns[name]
            for name in ("open", "high", "low", "close", "volume", "amount")
        }
        for name, column in numeric_columns.items():
            if column is None:
                raise AmazingDataAcquisitionError(
                    f"daily-bar response is missing the {name} column"
                )
            numeric_values = _frame_column(frame, column)
            if len(numeric_values) != len(values) or any(
                not _is_finite_number(value) for value in numeric_values
            ):
                raise AmazingDataAcquisitionError(
                    f"daily-bar response contains invalid {name} values"
                )
        normalized: list[int] = []
        for value in values:
            day = _normalize_day(value)
            if day is None:
                raise AmazingDataAcquisitionError("daily-bar response contains an invalid date")
            try:
                parsed = date(day // 10000, (day // 100) % 100, day % 100)
            except ValueError as exc:
                raise AmazingDataAcquisitionError(
                    "daily-bar response contains an invalid date"
                ) from exc
            if parsed < start or parsed > end:
                raise AmazingDataAcquisitionError(
                    "daily-bar response returned a date outside scope"
                )
            normalized.append(day)
        if len(normalized) != len(set(normalized)):
            raise AmazingDataAcquisitionError(
                "daily-bar response contains duplicate security dates"
            )
        if set(normalized) != set(trading_days):
            raise AmazingDataAcquisitionError(
                "daily-bar response is partial for one or more securities"
            )
        returned_days.update(normalized)
        row_count += len(normalized)
    expected_days = set(trading_days)
    if returned_days != expected_days:
        raise AmazingDataAcquisitionError(
            "daily-bar response date range is partial or differs from the calendar"
        )
    return {
        "first_date": _day_to_date(min(returned_days)),
        "last_date": _day_to_date(max(returned_days)),
        "trading_day_count": len(returned_days),
        "trading_days_hash": _hash_values(sorted(returned_days)),
        "row_count": row_count,
    }


def _frame_column(frame: Any, name: str) -> list[Any]:
    try:
        column = frame.get_column(name) if hasattr(frame, "get_column") else frame[name]
        values = column.to_list() if hasattr(column, "to_list") else column.tolist()
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise AmazingDataAcquisitionError("daily-bar response date column is unreadable") from exc
    return list(values)


def _normalize_day(value: Any) -> int | None:
    if isinstance(value, datetime):
        return _yyyymmdd(value.date())
    if isinstance(value, date):
        return _yyyymmdd(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and len(str(value)) == 8:
        return value
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit())
        if len(digits) >= 8:
            return int(digits[:8])
    return None


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _day_to_date(value: int) -> date:
    try:
        return date(value // 10000, (value // 100) % 100, value % 100)
    except ValueError as exc:
        raise AmazingDataAcquisitionError("daily-bar response contains an invalid date") from exc


def _yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _hash_values(values: list[Any]) -> str:
    return sha256_hex(canonical_json(values))
