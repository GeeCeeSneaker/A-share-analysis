"""Reviewed AmazingData acquisition path for CR-7 authoritative history.

This module is the only issuer of a new ``AmazingDataAcquisitionReceipt``.
It retains and evaluates a bounded calendar-month capture first; a later
verified source projection is then bound to that capture without another
provider request.

The module never writes credentials or raw payloads to Git-tracked locations.
No free-form snapshot id/hash/timestamp or completeness label is accepted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ashare_state.providers.amazingdata.month_completeness import (
    MonthCompletenessEvaluation,
    PositiveTradeFallback,
    _positive_trade_fallback_candidates,
    _snapshot_trade_observation,
    evaluate_month_completeness,
)
from ashare_state.providers.amazingdata.operations import (
    DAILY_BAR_KLINE,
    HIST_CODE_LIST,
    HISTORY_STOCK_STATUS,
    TRADE_ACTIVITY_SNAPSHOT,
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
    PositiveTradeFallbackOperation,
    _issue_amazingdata_acquisition_receipt,
)
from ashare_state.research.models import (
    VERIFIED_SECURITY_MASTER_SOURCE,
    canonical_json,
    ensure_utc_timestamp,
    sha256_hex,
)
from ashare_state.research.panel import VerifiedResearchProjection
from ashare_state.storage.atomic_files import write_file_atomic
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter
from ashare_state.storage.raw_writer import RawWriteResult

__all__ = [
    "AmazingDataHistoryAcquisition",
    "AmazingDataHistoryCapture",
    "AmazingDataAcquisitionError",
]


class AmazingDataAcquisitionError(CoverageBasisError):
    """A complete-month AmazingData acquisition cannot be accepted."""


_SECURITY_TYPE = AMAZINGDATA_SECURITY_UNIVERSE_SELECTION
_PERIOD_DAY = 10008
_METHOD_SPECS = {
    "BaseData.get_calendar": TRADE_CALENDAR,
    "BaseData.get_hist_code_list": HIST_CODE_LIST,
    "InfoData.get_history_stock_status": HISTORY_STOCK_STATUS,
    "MarketData.query_kline": DAILY_BAR_KLINE,
    "MarketData.query_snapshot": TRADE_ACTIVITY_SNAPSHOT,
}
_RESPONSE_SHAPES = {
    "BaseData.get_calendar": "list[int]",
    "BaseData.get_hist_code_list": "list[str]",
    "InfoData.get_history_stock_status": "dict[str,dataframe|None]",
    "MarketData.query_kline": "dict[str,dataframe|None]",
    "MarketData.query_snapshot": "dict[str,dataframe|None]",
}


@dataclass(frozen=True)
class AmazingDataHistoryCapture:
    """Immutable in-memory handoff for one retained provider month capture.

    Raw exchanges have already been anchored when this value is returned. The
    source projection is deliberately absent: callers build or refresh it
    after capture, then finalize this exact handoff without another request.
    """

    partition: PartitionKey
    operations: tuple[AmazingDataExchangeReceipt, ...]
    semantic_operations: tuple[AmazingDataExchangeReceipt, ...]
    positive_trade_operations: tuple[PositiveTradeFallbackOperation, ...]
    completeness_evaluation: MonthCompletenessEvaluation
    retrieved_at_utc: datetime
    raw_root: Path = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.partition, PartitionKey):
            raise AmazingDataAcquisitionError("month capture partition is malformed")
        if not isinstance(self.completeness_evaluation, MonthCompletenessEvaluation):
            raise AmazingDataAcquisitionError("month capture completeness evaluation is malformed")
        object.__setattr__(self, "operations", tuple(self.operations))
        object.__setattr__(self, "semantic_operations", tuple(self.semantic_operations))
        object.__setattr__(self, "positive_trade_operations", tuple(self.positive_trade_operations))
        object.__setattr__(self, "retrieved_at_utc", ensure_utc_timestamp(self.retrieved_at_utc))
        object.__setattr__(self, "raw_root", Path(self.raw_root))


@dataclass(frozen=True)
class AmazingDataHistoryAcquisition:
    """Capture and finalize one bounded AmazingData month acquisition."""

    provider: AmazingDataProvider
    raw_writer: AnchoredRawEvidenceWriter

    def __post_init__(self) -> None:
        if not isinstance(self.provider, AmazingDataProvider):
            raise AmazingDataAcquisitionError("acquisition requires the typed AmazingData provider")
        if not isinstance(self.raw_writer, AnchoredRawEvidenceWriter):
            raise AmazingDataAcquisitionError(
                "acquisition requires the anchored raw evidence writer"
            )

    def capture_month(
        self,
        partition: PartitionKey,
        *,
        list_dates_by_symbol: Mapping[str, Any] | None = None,
        delist_dates_by_symbol: Mapping[str, Any] | None = None,
    ) -> AmazingDataHistoryCapture:
        """Retain one bounded month capture and evaluate completeness.

        A fail-closed completeness result is returned as capture evidence so
        callers can diagnose the exact blocker. It cannot be converted to a
        receipt unless :meth:`finalize_capture` accepts the evaluation.
        """
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
            exact_exchange, exact_receipt = self._exchange(
                "BaseData.get_hist_code_list",
                lambda day=trading_day: self.provider.get_hist_code_list_exchange(
                    _SECURITY_TYPE, day, day
                ),
                expected_params={
                    "security_type": _SECURITY_TYPE,
                    "start_date": trading_day,
                    "end_date": trading_day,
                },
            )
            exact_day_universes[trading_day] = _validate_security_universe(exact_exchange.payload)
            exact_day_exchanges.append(exact_exchange)
            semantic_receipts.append(exact_receipt)

        fallback_candidates = _positive_trade_fallback_candidates(
            monthly_symbols=symbols,
            trading_days=trading_days,
            exact_day_universes=exact_day_universes,
            status_payload=status_exchange.payload,
            list_dates_by_symbol=list_dates_by_symbol,
            delist_dates_by_symbol=delist_dates_by_symbol,
        )
        snapshot_exchanges: list[ProviderExchange] = []
        snapshot_receipts: dict[tuple[str, int], AmazingDataExchangeReceipt] = {}
        positive_trade_pairs: list[tuple[str, int]] = []
        snapshot_request_hashes: dict[tuple[str, int], str] = {}
        for symbol, trading_day in sorted(fallback_candidates, key=lambda item: (item[1], item[0])):
            snapshot_exchange, snapshot_receipt = self._exchange(
                "MarketData.query_snapshot",
                lambda symbol=symbol, day=trading_day: self.provider.query_snapshot_exchange(
                    [symbol],
                    begin_date=day,
                    end_date=day,
                ),
                expected_params={
                    "code_list": [symbol],
                    "begin_date": trading_day,
                    "end_date": trading_day,
                    "begin_time": 93000000,
                    "end_time": 150000000,
                },
            )
            positive, snapshot_errors = _snapshot_trade_observation(
                snapshot_exchange.payload,
                symbol=symbol,
                trading_day=trading_day,
            )
            if snapshot_errors:
                raise AmazingDataAcquisitionError(
                    "AmazingData positive-trade snapshot identity is malformed"
                )
            snapshot_exchanges.append(snapshot_exchange)
            snapshot_request_hashes[(symbol, trading_day)] = snapshot_receipt.request_params_hash
            if positive:
                pair = (symbol, trading_day)
                positive_trade_pairs.append(pair)
                snapshot_receipts[pair] = snapshot_receipt

        positive_trade_fallback = None
        if fallback_candidates:
            positive_trade_fallback = PositiveTradeFallback(
                queried_pairs=fallback_candidates,
                positive_pairs=positive_trade_pairs,
                request_params_by_pair=snapshot_request_hashes,
            )

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
            positive_trade_fallback=positive_trade_fallback,
            list_dates_by_symbol=list_dates_by_symbol,
            delist_dates_by_symbol=delist_dates_by_symbol,
        )
        positive_trade_operations = tuple(
            PositiveTradeFallbackOperation(
                security=symbol,
                trading_day=trading_day,
                exchange=snapshot_receipts[(symbol, trading_day)],
            )
            for symbol, trading_day in sorted(
                positive_trade_pairs, key=lambda item: (item[1], item[0])
            )
        )
        retrieved_at = max(
            ensure_utc_timestamp(str(getattr(exchange.envelope, "received_at", "")))
            for exchange in (
                calendar_exchange,
                code_exchange,
                status_exchange,
                kline_exchange,
                *exact_day_exchanges,
                *snapshot_exchanges,
            )
        )
        return AmazingDataHistoryCapture(
            partition=partition,
            operations=(calendar_receipt, code_receipt, status_receipt, kline_receipt),
            semantic_operations=tuple(semantic_receipts),
            positive_trade_operations=positive_trade_operations,
            completeness_evaluation=evaluation,
            retrieved_at_utc=retrieved_at,
            raw_root=self.raw_writer.root,
        )

    def finalize_capture(
        self,
        capture: AmazingDataHistoryCapture,
        *,
        source_snapshot: VerifiedResearchProjection,
    ) -> AmazingDataAcquisitionReceipt:
        """Issue and replay a receipt from a retained capture, without I/O to provider."""
        if not isinstance(capture, AmazingDataHistoryCapture):
            raise AmazingDataAcquisitionError("receipt finalization requires a typed month capture")
        if not isinstance(source_snapshot, VerifiedResearchProjection):
            raise AmazingDataAcquisitionError(
                "receipt finalization requires a verified source snapshot"
            )
        if capture.raw_root.resolve() != self.raw_writer.root.resolve():
            raise AmazingDataAcquisitionError(
                "month capture must be finalized against its original retained raw root"
            )
        try:
            capture.completeness_evaluation.require_accepted()
        except ValueError as exc:
            raise AmazingDataAcquisitionError(
                "AmazingData month completeness is unresolved; authoritative acquisition is blocked"
            ) from exc
        evaluation = capture.completeness_evaluation
        if len(source_snapshot.rows) != evaluation.returned_row_count:
            raise AmazingDataAcquisitionError(
                "verified projection daily-row cardinality does not match the retained capture"
            )
        for row in source_snapshot.rows:
            if not isinstance(row, Mapping):
                raise AmazingDataAcquisitionError("verified projection row is malformed")
            raw_trade_date = row.get("trade_date")
            if not isinstance(raw_trade_date, date) or isinstance(raw_trade_date, datetime):
                raise AmazingDataAcquisitionError(
                    "verified projection trade date is missing or malformed"
                )
            if not capture.partition.scope_start <= raw_trade_date <= capture.partition.scope_end:
                raise AmazingDataAcquisitionError(
                    "verified projection rows do not match the bounded capture scope"
                )
            if row.get("research_split") != capture.partition.research_split.value:
                raise AmazingDataAcquisitionError(
                    "verified projection research split does not match the bounded capture"
                )
        if evaluation.prelisting_list_dates or evaluation.postdelisting_delist_dates:
            identity_view = source_snapshot.identity_view
            if (
                identity_view.source_kind != VERIFIED_SECURITY_MASTER_SOURCE
                or not identity_view.sources
            ):
                raise AmazingDataAcquisitionError(
                    "lifecycle applicability requires verified security-master identity"
                )
            suffix_by_exchange = {"SSE": "SH", "SZSE": "SZ"}
            expected_list_dates = evaluation.prelisting_list_dates
            expected_delist_dates = evaluation.postdelisting_delist_dates
            observed_list_dates: dict[str, date] = {}
            observed_delist_dates: dict[str, date] = {}
            for record in identity_view.records:
                suffix = suffix_by_exchange.get(record.exchange)
                if suffix is None:
                    continue
                provider_symbol = f"{record.symbol}.{suffix}"
                if provider_symbol in expected_list_dates:
                    previous = observed_list_dates.get(provider_symbol)
                    if previous is not None and previous != record.valid_from:
                        raise AmazingDataAcquisitionError(
                            "verified security-master LISTDATE is ambiguous for a pre-listing pair"
                        )
                    observed_list_dates[provider_symbol] = record.valid_from
                if provider_symbol in expected_delist_dates and record.delist_date is not None:
                    previous = observed_delist_dates.get(provider_symbol)
                    if previous is not None and previous != record.delist_date:
                        raise AmazingDataAcquisitionError(
                            "verified security-master DELISTDATE is ambiguous "
                            "for a post-delisting pair"
                        )
                    observed_delist_dates[provider_symbol] = record.delist_date
            if observed_list_dates != expected_list_dates:
                raise AmazingDataAcquisitionError(
                    "verified security-master LISTDATE does not match captured applicability"
                )
            if observed_delist_dates != expected_delist_dates:
                raise AmazingDataAcquisitionError(
                    "verified security-master DELISTDATE does not match captured applicability"
                )
        returned_first_date = evaluation.returned_first_date
        returned_last_date = evaluation.returned_last_date
        if returned_first_date is None or returned_last_date is None:
            raise AmazingDataAcquisitionError(
                "AmazingData daily-bar response has no returned date range"
            )
        receipt = _issue_amazingdata_acquisition_receipt(
            source_snapshot=source_snapshot,
            requested_scope_start=capture.partition.scope_start,
            requested_scope_end=capture.partition.scope_end,
            security_universe_count=evaluation.monthly_security_count,
            security_universe_hash=evaluation.monthly_security_set_hash,
            calendar_trading_day_count=evaluation.session_count,
            calendar_trading_days_hash=evaluation.session_set_hash,
            returned_first_date=returned_first_date,
            returned_last_date=returned_last_date,
            returned_trading_day_count=evaluation.returned_trading_day_count,
            returned_trading_days_hash=evaluation.returned_trading_days_hash,
            returned_row_count=evaluation.returned_row_count,
            operations=capture.operations,
            semantic_operations=capture.semantic_operations,
            positive_trade_operations=capture.positive_trade_operations,
            completeness_evaluation=evaluation,
            retrieved_at_utc=capture.retrieved_at_utc,
        )
        _persist_capture_catalog(self.raw_writer, receipt)
        try:
            receipt.verify_retained_capture(capture.raw_root)
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
