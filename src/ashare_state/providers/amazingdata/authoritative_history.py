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

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ashare_state.providers.amazingdata.month_completeness import evaluate_month_completeness
from ashare_state.providers.amazingdata.operations import (
    DAILY_BAR_KLINE,
    HIST_CODE_LIST,
    HISTORY_STOCK_STATUS,
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
    "InfoData.get_history_stock_status": HISTORY_STOCK_STATUS,
    "MarketData.query_kline": DAILY_BAR_KLINE,
}
_RESPONSE_SHAPES = {
    "BaseData.get_calendar": "list[int]",
    "BaseData.get_hist_code_list": "list[str]",
    "InfoData.get_history_stock_status": "dict[str,dataframe|None]",
    "MarketData.query_kline": "dict[str,dataframe|None]",
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
        """Return a receipt only after the semantic expected-bar set passes."""
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

        status_exchange, status_receipt = self._exchange(
            "InfoData.get_history_stock_status",
            lambda: self.provider.get_history_stock_status_exchange(begin, finish, symbols),
            expected_params={
                "begin_date": begin,
                "end_date": finish,
                "code_list": symbols,
                "is_local": False,
            },
        )

        exact_day_universes: dict[int, list[str]] = {}
        exact_day_exchanges: list[ProviderExchange] = []
        semantic_receipts: list[AmazingDataExchangeReceipt] = []
        for trading_day in trading_days:
            exact_day = _day_to_date(trading_day)
            exact_day_end = _yyyymmdd(exact_day + timedelta(days=1))
            exact_exchange, exact_receipt = self._exchange(
                "BaseData.get_hist_code_list",
                lambda start_day=trading_day, end_day=exact_day_end: (
                    self.provider.get_hist_code_list_exchange(_SECURITY_TYPE, start_day, end_day)
                ),
                expected_params={
                    "security_type": _SECURITY_TYPE,
                    "start_date": trading_day,
                    "end_date": exact_day_end,
                },
            )
            exact_day_universes[trading_day] = _validate_security_universe(exact_exchange.payload)
            exact_day_exchanges.append(exact_exchange)
            semantic_receipts.append(exact_receipt)

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
        evaluation = evaluate_month_completeness(
            monthly_symbols=symbols,
            trading_days=trading_days,
            exact_day_universes=exact_day_universes,
            status_payload=status_exchange.payload,
            daily_bar_payload=kline_exchange.payload,
        )
        try:
            evaluation.require_accepted()
        except ValueError as exc:
            raise AmazingDataAcquisitionError(
                "AmazingData month completeness is unresolved; authoritative acquisition is blocked"
            ) from exc
        returned_first_date = evaluation.returned_first_date
        returned_last_date = evaluation.returned_last_date
        returned_trading_day_count = evaluation.returned_trading_day_count
        returned_trading_days_hash = evaluation.returned_trading_days_hash
        returned_row_count = evaluation.returned_row_count
        if returned_first_date is None or returned_last_date is None:
            raise AmazingDataAcquisitionError(
                "AmazingData daily-bar response has no returned date range"
            )
        operations = (calendar_receipt, code_receipt, status_receipt, kline_receipt)
        retrieved_at = max(
            ensure_utc_timestamp(str(getattr(exchange.envelope, "received_at", "")))
            for exchange in (
                calendar_exchange,
                code_exchange,
                status_exchange,
                kline_exchange,
                *exact_day_exchanges,
            )
        )
        capture = _VerifiedAmazingDataCapture._from_provider(  # noqa: SLF001
            requested_scope_start=start,
            requested_scope_end=end,
            security_universe_count=len(symbols),
            security_universe_hash=_hash_values(symbols),
            calendar_trading_day_count=len(trading_days),
            calendar_trading_days_hash=_hash_values(trading_days),
            returned_first_date=returned_first_date,
            returned_last_date=returned_last_date,
            returned_trading_day_count=returned_trading_day_count,
            returned_trading_days_hash=returned_trading_days_hash,
            returned_row_count=returned_row_count,
            operations=operations,
            semantic_operations=tuple(semantic_receipts),
            completeness_evaluation=evaluation,
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


def _day_to_date(value: int) -> date:
    try:
        return date(value // 10000, (value // 100) % 100, value % 100)
    except ValueError as exc:
        raise AmazingDataAcquisitionError("daily-bar response contains an invalid date") from exc


def _yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _hash_values(values: list[Any]) -> str:
    return sha256_hex(canonical_json(values))
