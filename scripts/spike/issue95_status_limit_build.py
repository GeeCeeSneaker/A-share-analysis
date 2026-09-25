"""Month-bounded SH/SZ security_status + limit_price build for Issue #95.

This runner uses only the existing AmazingData facade, anchored raw evidence,
Normalizer, identity bridge, and Canonical contracts. All run data is written
under the ignored local ``data/spike`` root; stdout contains sanitized progress
events only. It deliberately does not call snapshots, k-lines, or corporate-
action endpoints.
"""

from __future__ import annotations

import argparse
import calendar
import ctypes
import hashlib
import json
import os
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.canonical.canonicalizer import CanonicalRunner
from ashare_state.canonical.identity import approved_provider_identity_events
from ashare_state.canonical.verifier import verify_canonical_run_for_consumption
from ashare_state.normalization.runner import NormalizationRunner, verify_normalized_run
from ashare_state.providers.amazingdata.authoritative_history import (
    _validate_calendar,
    _validate_security_universe,
)
from ashare_state.providers.amazingdata.credentials import (
    load_tgw_environment,
    resolve_tgw_credentials,
)
from ashare_state.providers.amazingdata.mapper import (
    normalize_provider_symbol,
    normalize_status_payload,
)
from ashare_state.providers.amazingdata.production_identity import (
    AccountKind,
    production_account_status,
)
from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget
from ashare_state.research.historical import AMAZINGDATA_SECURITY_UNIVERSE_SELECTION
from ashare_state.storage.connection import DuckDBConnectionManager
from ashare_state.storage.migrations import apply_migrations
from ashare_state.storage.paths import physical_from_logical_uri
from ashare_state.storage.raw_anchor import (
    AnchoredRawEvidenceWriter,
    lookup_raw_evidence_anchor,
)
from ashare_state.storage.raw_writer import verify_raw_evidence

REPO_ROOT = Path(__file__).resolve().parents[2]
START_DATE = date(2020, 1, 1)
END_DATE = date(2026, 6, 30)
STATUS_ENDPOINT = "InfoData.get_history_stock_status"
MIN_REQUEST_INTERVAL_SECONDS = 1.0
TARGETED_RETRY_DELAY_SECONDS = 30.0
MAX_TARGETED_REQUESTS_PER_MONTH = 100
MAX_RSS_BYTES = 16 * 1024**3
STATUS_BATCH_FALLBACKS = (1000, 500, 250, 125, 64, 32, 16, 8)
STATUS_BATCH_PROBE_SIZES = tuple(sorted(STATUS_BATCH_FALLBACKS))
DOMAINS = ("security_status", "limit_price")


class BuildFailureError(RuntimeError):
    """A safe, categorized stop; never includes provider exception text."""

    def __init__(self, stage: str, error_class: str) -> None:
        super().__init__(f"{stage}:{error_class}")
        self.stage = stage
        self.error_class = error_class


BuildFailure = BuildFailureError


class ProviderCallFailure(BuildFailure):
    def __init__(self, stage: str, error_class: str, *, generic_query_failure: bool) -> None:
        super().__init__(stage, error_class)
        self.generic_query_failure = generic_query_failure


@dataclass
class RateGate:
    interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS
    last_call_monotonic: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self.last_call_monotonic is not None:
            delay = self.interval_seconds - (now - self.last_call_monotonic)
            if delay > 0:
                time.sleep(delay)
        self.last_call_monotonic = time.monotonic()


def _emit(stage: str, **fields: Any) -> None:
    safe = {"stage": stage, "at_utc": datetime.now(UTC).isoformat(), **fields}
    print(json.dumps(safe, sort_keys=True, ensure_ascii=False), flush=True)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        replace_delays = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0)
        for attempt, delay in enumerate(replace_delays):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == len(replace_delays) - 1:
                    raise
                time.sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256_bytes(payload)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")
        stream.flush()


def _month_bounds(month: str) -> tuple[date, date]:
    year, number = (int(part) for part in month.split("-", 1))
    last_day = calendar.monthrange(year, number)[1]
    return date(year, number, 1), date(year, number, last_day)


def _months_in_scope() -> list[str]:
    values: list[str] = []
    cursor = date(START_DATE.year, START_DATE.month, 1)
    final = date(END_DATE.year, END_DATE.month, 1)
    while cursor <= final:
        values.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1
        )
    return values


def _candidate_status_probe_sizes(max_size: int, available_symbols: int) -> list[int]:
    return [
        size for size in STATUS_BATCH_PROBE_SIZES if size <= max_size and size <= available_symbols
    ]


def _provider_day(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


def _field(row: dict[str, Any], *names: str) -> Any:
    folded = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None


def _current_rss_bytes() -> int:
    if os.name != "nt":
        return 0

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(MemoryCounters)
    get_process = ctypes.windll.kernel32.GetCurrentProcess
    get_process.restype = ctypes.c_void_p
    process = get_process()
    get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
    get_memory_info.restype = ctypes.c_int
    return (
        int(counters.WorkingSetSize)
        if get_memory_info(process, ctypes.byref(counters), counters.cb)
        else 0
    )


def _load_credentials_from_vault() -> tuple[str, str, str, int]:
    settings = load_tgw_environment(REPO_ROOT / ".env")
    # The runner intentionally ignores process-level password overrides.
    settings.pop("TGW_PASSWORD", None)
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name in ("TGW_USERNAME", "TGW_SERVER_VIP", "TGW_SERVER_PORT"):
                if settings.get(name):
                    continue
                try:
                    value, _kind = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if isinstance(value, str) and value:
                    settings[name] = value
    return resolve_tgw_credentials(settings)


def _generic_query_failure(exc: Exception) -> bool:
    context = getattr(exc, "context", {})
    return (
        exc.__class__.__name__ == "ProviderSdkInternalError"
        and isinstance(context, dict)
        and context.get("classification_rule_id") == "QUERY_FAIL_UNCLASSIFIED"
    )


def _status_rows(
    exchange_payload: Any, request_params: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    """Validate row-owned identity/date and return rows plus empty-member count."""
    rows, _locators, empty_members = normalize_status_payload(
        exchange_payload,
        request_params=request_params,
    )
    return rows, empty_members


class Issue95Build:
    def __init__(
        self,
        *,
        run_root: Path,
        max_status_batch_size: int,
        conn: Any,
        provider: AmazingDataProvider,
    ) -> None:
        self.run_root = run_root
        self.conn = conn
        self.provider = provider
        self.raw_root = run_root / "raw"
        self.normalized_root = run_root / "normalized"
        self.canonical_root = self.normalized_root / "canonical"
        self.database_path = run_root / "ledger.duckdb"
        self.receipt_path = run_root / "receipts.jsonl"
        self.universe_root = run_root / "denominator" / "universe_by_month"
        self.status_batch_size = min(STATUS_BATCH_PROBE_SIZES)
        self.max_status_batch_size = max_status_batch_size
        self.run_id = str(uuid.uuid4())
        self.call_count = 0
        self.rate_gate = RateGate()
        self.state: dict[str, Any] = {
            "schema": "issue95_status_limit_build.v1",
            "run_id": self.run_id,
            "status": "RUNNING",
            "started_at_utc": datetime.now(UTC).isoformat(),
            "scope": {
                "exchanges": ["SH", "SZ"],
                "start_date": START_DATE.isoformat(),
                "end_date": END_DATE.isoformat(),
                "months": _months_in_scope(),
                "canonical_domains": list(DOMAINS),
            },
            "request_policy": {
                "minimum_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
                "max_retries_after_initial": 3,
                "backoff_base_seconds": 15,
                "jitter_fraction": 0.25,
                "max_backoff_seconds": 120,
                "query_budget_seconds": 300,
                "connect_budget_seconds": 15,
                "generic_query_failure_endpoint_allowlist": [STATUS_ENDPOINT],
                "status_batch_size_probe_cap": max_status_batch_size,
            },
            "receipts": {
                "file": "receipts.jsonl",
                "provider_call_count": 0,
            },
            "calendars": {},
            "identity": {},
            "months": [],
            "status_batch_size_probe": None,
            "canonical": None,
        }
        self._save_state()

    def _save_state(self) -> None:
        self.state["receipts"]["provider_call_count"] = self.call_count
        _atomic_json(self.run_root / "execution_manifest.json", self.state)

    def _record_exchange(self, exchange: Any, *, purpose: str) -> dict[str, Any]:
        envelope = getattr(exchange, "envelope", None)
        if envelope is None:
            raise BuildFailure("RAW_CAPTURE", "MISSING_PROVIDER_ENVELOPE")
        try:
            persisted = self.raw_writer.write_exchange(exchange)
            verify_raw_evidence(
                self.raw_root,
                provider=str(envelope.provider),
                dataset=str(envelope.provider_dataset),
                request_id=str(envelope.request_id),
            )
            anchor = lookup_raw_evidence_anchor(
                self.conn,
                provider=str(envelope.provider),
                provider_dataset=str(envelope.provider_dataset),
                request_id=str(envelope.request_id),
            )
        except Exception as exc:  # noqa: BLE001 - never expose SDK/filesystem details
            raise BuildFailure("RAW_CAPTURE", type(exc).__name__) from None
        if anchor is None or anchor.evidence_hash != persisted.evidence_hash:
            raise BuildFailure("RAW_CAPTURE", "RAW_EVIDENCE_ANCHOR_MISMATCH")
        self.call_count += 1
        receipt = {
            "purpose": purpose,
            "provider_dataset": str(envelope.provider_dataset),
            "endpoint": str(envelope.endpoint),
            "request_id": str(persisted.request_id),
            "request_params_sha256": str(envelope.request_params_hash),
            "raw_evidence_uri": str(persisted.evidence_uri),
            "raw_evidence_sha256": str(persisted.evidence_hash),
            "raw_content_sha256": str(persisted.content_hash),
            "row_count": int(persisted.row_count),
            "attempt_count": int(envelope.attempt_count),
            "exchange_status": str(envelope.status),
        }
        _append_jsonl(self.receipt_path, receipt)
        self._save_state()
        return receipt

    def _fetch(
        self,
        call: Callable[[], Any],
        *,
        endpoint: str,
        purpose: str,
    ) -> tuple[Any, dict[str, Any]]:
        fresh_retries = 1 if endpoint == STATUS_ENDPOINT else 0
        for fresh_attempt in range(fresh_retries + 1):
            self.rate_gate.wait()
            try:
                exchange = call()
            except Exception as exc:  # noqa: BLE001 - typed safe boundary
                failed_exchange = getattr(exc, "exchange", None)
                if failed_exchange is not None:
                    self._record_exchange(failed_exchange, purpose=purpose)
                if hasattr(self.provider, "last_envelopes"):
                    self.provider.last_envelopes.clear()
                generic_failure = _generic_query_failure(exc) and endpoint == STATUS_ENDPOINT
                if generic_failure and fresh_attempt < fresh_retries:
                    _emit(
                        "DELAYED_RETRY",
                        purpose=purpose,
                        error_class=type(exc).__name__,
                        wait_seconds=int(TARGETED_RETRY_DELAY_SECONDS),
                    )
                    time.sleep(TARGETED_RETRY_DELAY_SECONDS)
                    continue
                raise ProviderCallFailure(
                    purpose,
                    type(exc).__name__,
                    generic_query_failure=generic_failure,
                ) from None
            receipt = self._record_exchange(exchange, purpose=purpose)
            if receipt["exchange_status"] != "OK":
                if hasattr(self.provider, "last_envelopes"):
                    self.provider.last_envelopes.clear()
                raise ProviderCallFailure(
                    purpose,
                    str(
                        getattr(exchange.envelope, "error_class", None)
                        or "PROVIDER_EXCHANGE_FAILED"
                    ),
                    generic_query_failure=False,
                )
            if hasattr(self.provider, "last_envelopes"):
                self.provider.last_envelopes.clear()
            return exchange, receipt
        raise BuildFailure(purpose, "RETRY_STATE_INVALID")

    def _normalize(
        self,
        receipt: dict[str, Any],
        *,
        provider_dataset: str,
        expected_status_rows: int | None = None,
        expected_status_pairs: set[tuple[str, int]] | None = None,
    ) -> dict[str, Any]:
        try:
            result = NormalizationRunner(
                self.conn,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            ).run(
                provider_dataset=provider_dataset,
                request_id=str(receipt["request_id"]),
            )
        except Exception as exc:  # noqa: BLE001 - error details can contain provider values
            raise BuildFailure("NORMALIZE", type(exc).__name__) from None
        if result.status != "SUCCESS" or result.quarantined_count != 0 or not result.manifest_uri:
            raise BuildFailure("NORMALIZE", result.error_class or result.status)
        problems = verify_normalized_run(
            self.conn,
            result.normalization_run_id,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        if problems:
            raise BuildFailure("NORMALIZATION_VERIFY", "CLOSURE_FAILED")
        manifest_path = physical_from_logical_uri(self.normalized_root, result.manifest_uri)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = {
            str(item["output_name"]): {
                "row_count": int(item["row_count"]),
                "uri": str(item["uri"]),
                "sha256": str(item["content_hash"]),
            }
            for item in manifest.get("outputs", [])
        }
        if expected_status_rows is not None:
            for output_name in ("security_status", "limit_price"):
                output = outputs.get(output_name)
                if output is None or output["row_count"] != expected_status_rows:
                    raise BuildFailure("NORMALIZE", "STATUS_PROJECTION_COUNT_MISMATCH")
        if expected_status_pairs is not None:
            for output_name in ("security_status", "limit_price"):
                output = outputs.get(output_name)
                if output is None:
                    raise BuildFailure("NORMALIZE", "STATUS_PROJECTION_MISSING")
                output_path = physical_from_logical_uri(
                    self.normalized_root,
                    str(output["uri"]),
                )
                projected_pairs = self._status_output_pairs(
                    output_name,
                    output_path,
                    expected_row_count=output["row_count"],
                )
                if projected_pairs != expected_status_pairs:
                    raise BuildFailure("NORMALIZE", "STATUS_PROJECTION_KEY_SET_MISMATCH")
        return {
            "normalization_run_id": result.normalization_run_id,
            "manifest_uri": result.manifest_uri,
            "manifest_sha256": result.manifest_hash,
            "input_count": int(result.input_count),
            "normalized_count": int(result.normalized_count),
            "quarantined_count": int(result.quarantined_count),
            "outputs": outputs,
        }

    @staticmethod
    def _status_output_pairs(
        output_name: str,
        output_path: Path,
        *,
        expected_row_count: int,
    ) -> set[tuple[str, int]]:
        # The verified normalization manifest and the projection-count gate
        # establish this output as genuinely empty. Polars cannot select
        # named columns from the valid zero-column Parquet it writes for an
        # empty projection, so its exact natural-key set is empty as well.
        if expected_row_count == 0:
            return set()
        if output_name == "security_status":
            columns = ["security_code", "market_code", "trade_date"]
        elif output_name == "limit_price":
            columns = ["provider_symbol", "trade_date"]
        else:
            raise BuildFailure("NORMALIZE", "UNSUPPORTED_STATUS_OUTPUT")
        try:
            frame = pl.read_parquet(output_path, columns=columns)
            pairs: set[tuple[str, int]] = set()
            for row in frame.iter_rows(named=True):
                if output_name == "security_status":
                    symbol = normalize_provider_symbol(
                        str(row.get("security_code") or ""),
                        str(row.get("market_code") or ""),
                    )
                else:
                    symbol = str(row.get("provider_symbol") or "").strip().upper()
                trade_day = _provider_day(row.get("trade_date"))
                if not symbol or trade_day is None:
                    raise BuildFailure("NORMALIZE", "STATUS_PROJECTION_KEY_MISSING")
                pair = (symbol, int(trade_day.strftime("%Y%m%d")))
                if pair in pairs:
                    raise BuildFailure("NORMALIZE", "STATUS_PROJECTION_DUPLICATE_KEY")
                pairs.add(pair)
            return pairs
        except BuildFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - output schema/data stay local
            raise BuildFailure("NORMALIZE", type(exc).__name__) from None

    def initialize_storage(self) -> None:
        self.raw_root.mkdir(parents=True, exist_ok=False)
        self.normalized_root.mkdir(parents=True, exist_ok=False)
        self.universe_root.mkdir(parents=True, exist_ok=False)
        self.raw_writer = AnchoredRawEvidenceWriter(
            self.conn,
            self.raw_root,
            ingest_run_id=self.run_id,
        )

    def acquire_calendars(self) -> dict[str, set[int]]:
        calendars: dict[str, set[int]] = {}
        for market in ("SH", "SZ"):
            exchange, receipt = self._fetch(
                lambda market=market: self.provider.get_calendar_exchange(market),
                endpoint="BaseData.get_calendar",
                purpose=f"calendar_{market}",
            )
            days = _validate_calendar(exchange.payload, start=START_DATE, end=END_DATE)
            calendars[market] = set(days)
            self.state["calendars"][market] = {
                "session_count": len(days),
                "receipt": receipt,
            }
        if not calendars["SH"] or not calendars["SZ"]:
            raise BuildFailure("CALENDAR", "EMPTY_EXCHANGE_CALENDAR")
        self._save_state()
        return calendars

    def acquire_month_universes(
        self, calendars: dict[str, set[int]]
    ) -> tuple[set[str], dict[str, str]]:
        all_symbols: set[str] = set()
        universe_hashes: dict[str, str] = {}
        months = _months_in_scope()
        session_days = sorted(calendars["SH"] | calendars["SZ"])
        days_by_month: dict[str, list[int]] = {month: [] for month in months}
        for day in session_days:
            month = f"{day // 10000:04d}-{(day // 100) % 100:02d}"
            if month in days_by_month:
                days_by_month[month].append(day)

        for month_index, month in enumerate(months, start=1):
            start, end = _month_bounds(month)
            monthly_exchange, monthly_receipt = self._fetch(
                lambda start=start, end=end: self.provider.get_hist_code_list_exchange(
                    AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
                    start.year * 10000 + start.month * 100 + start.day,
                    end.year * 10000 + end.month * 100 + end.day,
                ),
                endpoint="BaseData.get_hist_code_list",
                purpose=f"monthly_universe_{month}",
            )
            monthly_symbols = set(_validate_security_universe(monthly_exchange.payload))
            if not monthly_symbols:
                raise BuildFailure("UNIVERSE", "EMPTY_MONTHLY_UNIVERSE")
            all_symbols.update(monthly_symbols)
            day_rows: list[dict[str, Any]] = []
            day_receipts: list[str] = []
            for day in days_by_month[month]:
                day_exchange, day_receipt = self._fetch(
                    lambda day=day: self.provider.get_hist_code_list_exchange(
                        AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
                        day,
                        day,
                    ),
                    endpoint="BaseData.get_hist_code_list",
                    purpose=f"session_universe_{month}",
                )
                symbols = _validate_security_universe(day_exchange.payload)
                if not set(symbols).issubset(monthly_symbols):
                    raise BuildFailure("UNIVERSE", "SESSION_SYMBOL_OUTSIDE_MONTHLY_UNIVERSE")
                day_rows.append({"trade_date": day, "symbols": symbols})
                day_receipts.append(day_receipt["raw_evidence_sha256"])
                all_symbols.update(symbols)

            if not day_rows:
                raise BuildFailure("UNIVERSE", "MONTH_HAS_NO_EXCHANGE_SESSIONS")
            universe_doc = {
                "schema": "issue95_month_universe.v1",
                "month": month,
                "monthly_symbols": sorted(monthly_symbols),
                "session_universes": day_rows,
                "monthly_universe_receipt_sha256": monthly_receipt["raw_evidence_sha256"],
                "session_receipt_set_sha256": _sha256_bytes(
                    "\n".join(day_receipts).encode("ascii")
                ),
            }
            universe_hash = _atomic_json(self.universe_root / f"{month}.json", universe_doc)
            universe_hashes[month] = universe_hash
            self.state["months"].append(
                {
                    "month": month,
                    "universe_status": "CAPTURED",
                    "monthly_symbol_count": len(monthly_symbols),
                    "exchange_session_count": len(day_rows),
                    "session_universe_receipt_count": len(day_receipts),
                    "monthly_universe_receipt_sha256": monthly_receipt["raw_evidence_sha256"],
                    "session_receipt_set_sha256": universe_doc["session_receipt_set_sha256"],
                    "universe_file_sha256": universe_hash,
                    "expected_pairs_security_status": None,
                    "expected_pairs_limit_price": None,
                    "returned_pairs": 0,
                    "unresolved_pairs": None,
                    "status_receipts": [],
                    "normalization_runs": [],
                }
            )
            self._save_state()
            _emit(
                "MONTH_UNIVERSE_CAPTURED",
                month=month,
                month_index=month_index,
                month_total=len(months),
                monthly_symbols=len(monthly_symbols),
                sessions=len(day_rows),
                provider_calls=self.call_count,
                rss_mb=round(_current_rss_bytes() / 1024**2, 1),
            )
        return all_symbols, universe_hashes

    def _read_normalized_main_rows(self, normalization: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            manifest_path = physical_from_logical_uri(
                self.normalized_root,
                str(normalization["manifest_uri"]),
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            output = next(
                item for item in manifest.get("outputs", []) if item.get("output_name") == "main"
            )
            output_path = physical_from_logical_uri(self.normalized_root, str(output["uri"]))
            return list(pl.read_parquet(output_path).iter_rows(named=True))
        except Exception as exc:  # noqa: BLE001 - details can include local/provider data
            raise BuildFailure("IDENTITY_READ", type(exc).__name__) from None

    @staticmethod
    def _identity_fact(row: dict[str, Any]) -> dict[str, Any]:
        symbol = str(row.get("provider_symbol") or "").strip().upper()
        try:
            list_date = _provider_day(row.get("list_date"))
            delist_date = _provider_day(row.get("delist_date"))
        except TypeError, ValueError:
            list_date = None
            delist_date = None
        listed_value = row.get("is_listed")
        try:
            is_listed = int(listed_value) if listed_value is not None else None
        except TypeError, ValueError:
            is_listed = None
        return {
            "provider_symbol": symbol,
            "list_date": list_date.isoformat() if list_date else None,
            "delist_date": delist_date.isoformat() if delist_date else None,
            "is_listed": is_listed,
        }

    def _merge_identity_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        requested: set[str],
        identity_facts: dict[str, dict[str, Any]],
    ) -> None:
        observed_in_request: set[str] = set()
        for row in rows:
            fact = self._identity_fact(row)
            symbol = fact["provider_symbol"]
            if not symbol or symbol not in requested:
                raise BuildFailure("IDENTITY", "STOCK_BASIC_RETURNED_UNREQUESTED_SYMBOL")
            if symbol in observed_in_request:
                raise BuildFailure("IDENTITY", "DUPLICATE_STOCK_BASIC_SYMBOL")
            observed_in_request.add(symbol)
            prior = identity_facts.get(symbol)
            if prior is not None:
                if prior["list_date"] not in (None, fact["list_date"]):
                    raise BuildFailure("IDENTITY", "CONFLICTING_LIST_DATE_FACT")
                if prior["delist_date"] not in (None, fact["delist_date"]):
                    raise BuildFailure("IDENTITY", "CONFLICTING_DELIST_DATE_FACT")
                if prior["is_listed"] not in (None, fact["is_listed"]):
                    raise BuildFailure("IDENTITY", "CONFLICTING_LISTING_STATUS_FACT")
                fact = {key: fact[key] if fact[key] is not None else prior[key] for key in fact}
            identity_facts[symbol] = fact

    def acquire_stock_basics(self, symbols: set[str]) -> dict[str, dict[str, Any]]:
        identity_facts: dict[str, dict[str, Any]] = {}
        ordered = sorted(symbols)
        batch_size = 1000
        normalized_runs: list[dict[str, Any]] = []
        for offset in range(0, len(ordered), batch_size):
            requested_list = ordered[offset : offset + batch_size]
            requested = set(requested_list)
            exchange, receipt = self._fetch(
                lambda requested_list=requested_list: self.provider.get_stock_basic_exchange(
                    requested_list
                ),
                endpoint="InfoData.get_stock_basic",
                purpose="stock_basic",
            )
            normalization = self._normalize(
                receipt,
                provider_dataset="stock_basic",
            )
            rows = self._read_normalized_main_rows(normalization)
            self._merge_identity_rows(rows, requested=requested, identity_facts=identity_facts)
            normalized_runs.append(
                {
                    "request_id": receipt["request_id"],
                    "raw_evidence_sha256": receipt["raw_evidence_sha256"],
                    "normalization_run_id": normalization["normalization_run_id"],
                    "normalization_manifest_sha256": normalization["manifest_sha256"],
                    "requested_count": len(requested_list),
                    "returned_count": len(rows),
                }
            )
            if len(normalized_runs) % 5 == 0:
                _emit(
                    "IDENTITY_CAPTURE_PROGRESS",
                    batches=len(normalized_runs),
                    requested_symbols=min(offset + batch_size, len(ordered)),
                    total_symbols=len(ordered),
                    provider_calls=self.call_count,
                )

        missing_symbols = {
            symbol
            for symbol in symbols
            if symbol not in identity_facts or identity_facts[symbol]["list_date"] is None
        }
        terminated_without_date = {
            symbol
            for symbol, fact in identity_facts.items()
            if fact["is_listed"] == 3 and fact["delist_date"] is None
        }
        repair_targets = sorted(missing_symbols | terminated_without_date)
        repair_count = 0
        if repair_targets:
            _emit(
                "IDENTITY_TARGETED_REFRESH",
                missing_count=len(missing_symbols),
                lifecycle_date_missing_count=len(terminated_without_date),
                delay_seconds=int(TARGETED_RETRY_DELAY_SECONDS),
            )
            time.sleep(TARGETED_RETRY_DELAY_SECONDS)
            for offset in range(0, min(len(repair_targets), 800), 8):
                target_list = repair_targets[offset : offset + 8]
                target = set(target_list)
                exchange, receipt = self._fetch(
                    lambda target_list=target_list: self.provider.get_stock_basic_exchange(
                        target_list
                    ),
                    endpoint="InfoData.get_stock_basic",
                    purpose="stock_basic_targeted_refresh",
                )
                normalization = self._normalize(
                    receipt,
                    provider_dataset="stock_basic",
                )
                rows = self._read_normalized_main_rows(normalization)
                self._merge_identity_rows(rows, requested=target, identity_facts=identity_facts)
                normalized_runs.append(
                    {
                        "request_id": receipt["request_id"],
                        "raw_evidence_sha256": receipt["raw_evidence_sha256"],
                        "normalization_run_id": normalization["normalization_run_id"],
                        "normalization_manifest_sha256": normalization["manifest_sha256"],
                        "requested_count": len(target_list),
                        "returned_count": len(rows),
                        "targeted_refresh": True,
                    }
                )
                repair_count += 1

        provider_returned_symbols = set(identity_facts)
        approved_static_fills = 0
        for event in approved_provider_identity_events():
            for symbol in (event.old_provider_symbol, event.new_provider_symbol):
                if symbol not in symbols:
                    continue
                current = identity_facts.get(symbol)
                if current is None or current["list_date"] is None:
                    identity_facts[symbol] = {
                        "provider_symbol": symbol,
                        "list_date": event.original_list_date.isoformat(),
                        "delist_date": current["delist_date"] if current else None,
                        "is_listed": current["is_listed"] if current else None,
                        "identity_source": "approved_static_identity_event",
                    }
                    approved_static_fills += 1

        unresolved_list_dates = sum(
            fact["list_date"] is None
            for symbol, fact in identity_facts.items()
            if symbol in symbols
        )
        unreturned_symbols = len(symbols - set(identity_facts))
        unresolved_terminated_dates = sum(
            fact["is_listed"] == 3 and fact["delist_date"] is None
            for symbol, fact in identity_facts.items()
            if symbol in symbols
        )
        identity_doc = {
            "schema": "issue95_identity_facts.v1",
            "facts": [identity_facts[symbol] for symbol in sorted(identity_facts)],
        }
        identity_hash = _atomic_json(
            self.run_root / "denominator" / "identity_facts.json", identity_doc
        )
        self.state["identity"] = {
            "requested_symbol_count": len(symbols),
            "provider_returned_symbol_count": len(provider_returned_symbols),
            "identity_covered_symbol_count": len(identity_facts),
            "missing_list_date_count": unresolved_list_dates + unreturned_symbols,
            "returned_without_list_date_count": unresolved_list_dates,
            "unreturned_symbol_count": unreturned_symbols,
            "terminated_without_delist_date_count": unresolved_terminated_dates,
            "approved_static_identity_fills": approved_static_fills,
            "targeted_refresh_requests": repair_count,
            "facts_sha256": identity_hash,
            "normalization_run_count": len(normalized_runs),
            "normalization_run_set_sha256": _sha256_bytes(
                "\n".join(
                    str(run["normalization_manifest_sha256"]) for run in normalized_runs
                ).encode("ascii")
            ),
        }
        self.state["identity"]["runs"] = normalized_runs
        self._save_state()
        _emit(
            "IDENTITY_CAPTURED",
            requested=len(symbols),
            returned=len(identity_facts),
            missing_list_dates=unresolved_list_dates,
            terminated_without_delist_dates=unresolved_terminated_dates,
            targeted_refresh_requests=repair_count,
        )
        return identity_facts

    def _expected_pairs_for_month(
        self,
        *,
        month: str,
        universe: dict[str, Any],
        calendars: dict[str, set[int]],
        identity_facts: dict[str, dict[str, Any]],
    ) -> tuple[set[tuple[str, int]], dict[str, int]]:
        monthly_symbols = set(universe["monthly_symbols"])
        daily_membership: dict[int, set[str]] = {
            int(item["trade_date"]): set(item["symbols"]) for item in universe["session_universes"]
        }
        sessions = sorted(calendars["SH"] | calendars["SZ"])
        month_start, month_end = _month_bounds(month)
        first = month_start.year * 10000 + month_start.month * 100 + month_start.day
        last = month_end.year * 10000 + month_end.month * 100 + month_end.day
        sessions = [day for day in sessions if first <= day <= last]
        expected: set[tuple[str, int]] = set()
        counts = {
            "sessions_sh": 0,
            "sessions_sz": 0,
            "prelisting_nonapplicable_pairs": 0,
            "postdelisting_nonapplicable_pairs": 0,
            "active_pairs_absent_from_exact_session_universe": 0,
            "identity_symbols_missing_list_date": 0,
            "terminated_symbols_missing_delist_date": 0,
        }
        counts["sessions_sh"] = sum(day in calendars["SH"] for day in sessions)
        counts["sessions_sz"] = sum(day in calendars["SZ"] for day in sessions)
        symbols_missing_list_date: set[str] = set()
        terminated_without_date: set[str] = set()
        for symbol in monthly_symbols:
            exchange = "SH" if symbol.endswith(".SH") else "SZ"
            fact = identity_facts.get(symbol)
            if fact is None or fact["list_date"] is None:
                symbols_missing_list_date.add(symbol)
                list_date = None
            else:
                list_date = date.fromisoformat(str(fact["list_date"]))
            if fact is not None and fact["is_listed"] == 3 and fact["delist_date"] is None:
                terminated_without_date.add(symbol)
            delist_date = (
                date.fromisoformat(str(fact["delist_date"]))
                if fact is not None and fact["delist_date"]
                else None
            )
            for day in sessions:
                if day not in calendars[exchange]:
                    continue
                day_date = date(day // 10000, day // 100 % 100, day % 100)
                if list_date is not None and list_date > day_date:
                    counts["prelisting_nonapplicable_pairs"] += 1
                    continue
                if delist_date is not None and delist_date <= day_date:
                    counts["postdelisting_nonapplicable_pairs"] += 1
                    continue
                pair = (symbol, day)
                expected.add(pair)
                if symbol not in daily_membership.get(day, set()):
                    counts["active_pairs_absent_from_exact_session_universe"] += 1
        counts["identity_symbols_missing_list_date"] = len(symbols_missing_list_date)
        counts["terminated_symbols_missing_delist_date"] = len(terminated_without_date)
        return expected, counts

    def probe_status_batch_size(
        self,
        *,
        month: str,
        universe_hash: str,
        calendars: dict[str, set[int]],
        identity_facts: dict[str, dict[str, Any]],
    ) -> int:
        """Prove a conservative live batch size before the month window.

        The SDK signature has no documented maximum. Probe only the exact
        approved status endpoint, increasing from the previously observed
        eight-symbol shape. A larger size is used for the build only after
        the live service returns independently keyed rows for that request.
        """
        universe_path = self.universe_root / f"{month}.json"
        if not universe_path.is_file() or _sha256_file(universe_path) != universe_hash:
            raise BuildFailure("STATUS_BATCH_PROBE", "MONTH_UNIVERSE_HASH_MISMATCH")
        universe = json.loads(universe_path.read_text(encoding="utf-8"))
        expected, _counts = self._expected_pairs_for_month(
            month=month,
            universe=universe,
            calendars=calendars,
            identity_facts=identity_facts,
        )
        by_day: dict[int, dict[str, list[str]]] = {}
        for symbol, day in expected:
            exchange = "SH" if symbol.endswith(".SH") else "SZ"
            by_day.setdefault(day, {"SH": [], "SZ": []})[exchange].append(symbol)
        eligible_days = [
            day
            for day, members in by_day.items()
            if len(members["SH"]) >= 4 and len(members["SZ"]) >= 4
        ]
        if not eligible_days:
            raise BuildFailure("STATUS_BATCH_PROBE", "NO_BALANCED_SH_SZ_SESSION")
        probe_day = max(eligible_days)
        members = by_day[probe_day]
        first_sh = sorted(members["SH"])[:4]
        first_sz = sorted(members["SZ"])[:4]
        ordered_symbols = (
            first_sh
            + first_sz
            + sorted(set(members["SH"] + members["SZ"]) - set(first_sh) - set(first_sz))
        )
        sizes = _candidate_status_probe_sizes(
            self.max_status_batch_size,
            len(ordered_symbols),
        )
        if not sizes or sizes[0] != STATUS_BATCH_PROBE_SIZES[0]:
            raise BuildFailure("STATUS_BATCH_PROBE", "INSUFFICIENT_PROBE_SYMBOLS")

        month_start, month_end = _month_bounds(month)
        begin = month_start.year * 10000 + month_start.month * 100 + month_start.day
        end = month_end.year * 10000 + month_end.month * 100 + month_end.day
        records: list[dict[str, Any]] = []
        selected_size: int | None = None
        rejected_size: int | None = None
        for size in sizes:
            requested = ordered_symbols[:size]
            params = {
                "begin_date": begin,
                "end_date": end,
                "code_list": requested,
                "is_local": False,
            }
            try:
                exchange, receipt = self._fetch(
                    lambda params=params: self.provider.get_history_stock_status_exchange(
                        params["begin_date"],
                        params["end_date"],
                        params["code_list"],
                    ),
                    endpoint=STATUS_ENDPOINT,
                    purpose=f"status_batch_probe_{month}_{size}",
                )
            except ProviderCallFailure as exc:
                if not exc.generic_query_failure or selected_size is None:
                    raise
                rejected_size = size
                records.append(
                    {
                        "requested_size": size,
                        "status": "QUERY_SIZE_REJECTED",
                        "error_class": exc.error_class,
                    }
                )
                break

            try:
                rows, empty_members = _status_rows(exchange.payload, params)
                returned_pairs: set[tuple[str, int]] = set()
                requested_set = set(requested)
                for row in rows:
                    symbol = str(row["PROVIDER_SYMBOL"])
                    day = int(str(row["TRADE_DATE"]))
                    pair = (symbol, day)
                    if symbol not in requested_set or pair not in expected:
                        raise BuildFailure("STATUS_BATCH_PROBE", "UNEXPECTED_PROBE_PAIR")
                    if pair in returned_pairs:
                        raise BuildFailure("STATUS_BATCH_PROBE", "DUPLICATE_PROBE_PAIR")
                    returned_pairs.add(pair)
                if not rows:
                    raise BuildFailure("STATUS_BATCH_PROBE", "NO_ROW_IDENTITY_EVIDENCE")
            except BuildFailure:
                raise
            except Exception as exc:  # noqa: BLE001 - provider row values stay local
                raise BuildFailure("STATUS_BATCH_PROBE", type(exc).__name__) from None

            records.append(
                {
                    "requested_size": size,
                    "status": "PASS",
                    "raw_evidence_sha256": receipt["raw_evidence_sha256"],
                    "raw_content_sha256": receipt["raw_content_sha256"],
                    "raw_row_count": receipt["row_count"],
                    "validated_row_count": len(rows),
                    "distinct_pair_count": len(returned_pairs),
                    "empty_member_count": empty_members,
                }
            )
            selected_size = size
            _emit(
                "STATUS_BATCH_SIZE_PROBE_PASS",
                requested_size=size,
                validated_rows=len(rows),
                raw_evidence_sha256=receipt["raw_evidence_sha256"],
            )
            del exchange, rows, returned_pairs

        if selected_size is None:
            raise BuildFailure("STATUS_BATCH_PROBE", "NO_SUPPORTED_BATCH_SIZE")
        self.status_batch_size = selected_size
        self.state["status_batch_size_probe"] = {
            "month": month,
            "session_date": probe_day,
            "tested_sizes": records,
            "selected_size": selected_size,
            "rejected_size": rejected_size,
        }
        self.state["request_policy"]["status_batch_size_selected"] = selected_size
        self._save_state()
        _emit(
            "STATUS_BATCH_SIZE_PROBE_COMPLETE",
            selected_size=selected_size,
            rejected_size=rejected_size,
            tested_count=sum(record["status"] == "PASS" for record in records),
            provider_calls=self.call_count,
        )
        return selected_size

    def capture_month_status(
        self,
        *,
        month: str,
        month_index: int,
        universe_hash: str,
        calendars: dict[str, set[int]],
        identity_facts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        universe_path = self.universe_root / f"{month}.json"
        if not universe_path.is_file() or _sha256_file(universe_path) != universe_hash:
            raise BuildFailure("UNIVERSE_VERIFY", "MONTH_UNIVERSE_HASH_MISMATCH")
        universe = json.loads(universe_path.read_text(encoding="utf-8"))
        expected, denominator_counts = self._expected_pairs_for_month(
            month=month,
            universe=universe,
            calendars=calendars,
            identity_facts=identity_facts,
        )
        monthly_symbols = sorted(set(universe["monthly_symbols"]))
        monthly_symbol_set = set(monthly_symbols)
        month_state = next(item for item in self.state["months"] if item["month"] == month)
        month_state.update(
            {
                **denominator_counts,
                "expected_pairs_security_status": len(expected),
                "expected_pairs_limit_price": len(expected),
                "missing_before_repair": None,
                "targeted_repair_requests": 0,
                "targeted_rows_returned": 0,
                "extra_pairs": 0,
                "duplicate_pairs": 0,
                "structural_errors": 0,
                "provider_suspension_flag_rows": 0,
                "provider_st_flag_rows": 0,
                "status": "CAPTURING",
            }
        )
        self._save_state()

        seen_pairs: set[tuple[str, int]] = set()
        batch_size = min(self.status_batch_size, max(len(monthly_symbols), 1))
        offset = 0
        used_batch_sizes: Counter[int] = Counter()
        receipt_rows: list[dict[str, Any]] = []
        normalization_runs: list[dict[str, Any]] = []
        empty_members = 0
        provider_rows = 0
        while offset < len(monthly_symbols):
            requested_list = monthly_symbols[offset : offset + batch_size]
            begin, finish = _month_bounds(month)
            params = {
                "begin_date": begin.year * 10000 + begin.month * 100 + begin.day,
                "end_date": finish.year * 10000 + finish.month * 100 + finish.day,
                "code_list": requested_list,
                "is_local": False,
            }
            try:
                exchange, receipt = self._fetch(
                    lambda params=params: self.provider.get_history_stock_status_exchange(
                        params["begin_date"],
                        params["end_date"],
                        params["code_list"],
                    ),
                    endpoint=STATUS_ENDPOINT,
                    purpose=f"status_limit_{month}",
                )
            except ProviderCallFailure as exc:
                smaller = next(
                    (candidate for candidate in STATUS_BATCH_FALLBACKS if candidate < batch_size),
                    None,
                )
                if exc.generic_query_failure and smaller is not None:
                    _emit(
                        "STATUS_BATCH_REDUCED",
                        month=month,
                        prior_batch_size=batch_size,
                        next_batch_size=smaller,
                        error_class=exc.error_class,
                        wait_seconds=int(TARGETED_RETRY_DELAY_SECONDS),
                    )
                    time.sleep(TARGETED_RETRY_DELAY_SECONDS)
                    batch_size = smaller
                    self.status_batch_size = smaller
                    continue
                raise
            try:
                rows, current_empty_members = _status_rows(exchange.payload, params)
            except Exception as exc:  # noqa: BLE001 - raw identity/date values stay local
                month_state["structural_errors"] += 1
                month_state["status"] = "BLOCKED_STRUCTURE"
                self._save_state()
                raise BuildFailure("STATUS_VALIDATION", type(exc).__name__) from None
            empty_members += current_empty_members
            batch_pairs: set[tuple[str, int]] = set()
            for row in rows:
                symbol = str(row["PROVIDER_SYMBOL"])
                day = int(str(row["TRADE_DATE"]))
                exchange_code = "SH" if symbol.endswith(".SH") else "SZ"
                pair = (symbol, day)
                if symbol not in monthly_symbol_set:
                    month_state["extra_pairs"] += 1
                    month_state["status"] = "BLOCKED_EXTRA"
                    self._save_state()
                    raise BuildFailure("STATUS_VALIDATION", "UNREQUESTED_STATUS_SYMBOL")
                if day not in calendars[exchange_code] or pair not in expected:
                    month_state["extra_pairs"] += 1
                    month_state["status"] = "BLOCKED_EXTRA"
                    self._save_state()
                    raise BuildFailure("STATUS_VALIDATION", "UNEXPECTED_STATUS_PAIR")
                if pair in seen_pairs or pair in batch_pairs:
                    month_state["duplicate_pairs"] += 1
                    month_state["status"] = "BLOCKED_DUPLICATE"
                    self._save_state()
                    raise BuildFailure("STATUS_VALIDATION", "DUPLICATE_STATUS_NATURAL_KEY")
                batch_pairs.add(pair)
                st_flag = _field(row, "IS_ST_SEC")
                suspension_flag = _field(row, "IS_SUSP_SEC")
                if str(st_flag).strip().lower() in {"1", "true", "yes"}:
                    month_state["provider_st_flag_rows"] += 1
                if str(suspension_flag).strip().lower() in {"1", "true", "yes"}:
                    month_state["provider_suspension_flag_rows"] += 1
            try:
                normalization = self._normalize(
                    receipt,
                    provider_dataset="history_stock_status",
                    expected_status_rows=len(rows),
                    expected_status_pairs=batch_pairs,
                )
            except BuildFailure:
                month_state["structural_errors"] += 1
                month_state["status"] = "BLOCKED_NORMALIZATION"
                self._save_state()
                raise
            seen_pairs.update(batch_pairs)
            provider_rows += len(rows)
            used_batch_sizes[len(requested_list)] += 1
            receipt_item = {
                "request_id": receipt["request_id"],
                "raw_evidence_sha256": receipt["raw_evidence_sha256"],
                "raw_content_sha256": receipt["raw_content_sha256"],
                "raw_row_count": receipt["row_count"],
                "accepted_row_count": len(rows),
                "empty_member_count": current_empty_members,
                "normalization_run_id": normalization["normalization_run_id"],
                "normalization_manifest_sha256": normalization["manifest_sha256"],
                "security_status_row_count": normalization["outputs"]["security_status"][
                    "row_count"
                ],
                "limit_price_row_count": normalization["outputs"]["limit_price"]["row_count"],
            }
            receipt_rows.append(receipt_item)
            normalization_runs.append(
                {
                    "normalization_run_id": normalization["normalization_run_id"],
                    "manifest_sha256": normalization["manifest_sha256"],
                }
            )
            month_state["status_receipts"] = receipt_rows
            month_state["normalization_runs"] = normalization_runs
            month_state["returned_pairs"] = len(seen_pairs)
            month_state["raw_rows"] = provider_rows
            month_state["empty_member_count"] = empty_members
            month_state["accepted_batch_sizes"] = dict(used_batch_sizes)
            offset += len(requested_list)
            self._save_state()
            del exchange, rows, batch_pairs

        missing = expected - seen_pairs
        missing_before_repair = len(missing)
        month_state["missing_before_repair"] = missing_before_repair
        if missing:
            grouped: dict[int, list[str]] = {}
            for symbol, day in sorted(missing, key=lambda item: (item[1], item[0])):
                grouped.setdefault(day, []).append(symbol)
            planned = sum((len(values) + 7) // 8 for values in grouped.values())
            if planned:
                time.sleep(TARGETED_RETRY_DELAY_SECONDS)
            request_budget = min(planned, MAX_TARGETED_REQUESTS_PER_MONTH)
            for day, day_symbols in sorted(grouped.items()):
                for start in range(0, len(day_symbols), 8):
                    if month_state["targeted_repair_requests"] >= request_budget:
                        break
                    requested_list = day_symbols[start : start + 8]
                    target_pairs = {(symbol, day) for symbol in requested_list}
                    params = {
                        "begin_date": day,
                        "end_date": day,
                        "code_list": requested_list,
                        "is_local": False,
                    }
                    exchange, receipt = self._fetch(
                        lambda params=params: self.provider.get_history_stock_status_exchange(
                            params["begin_date"],
                            params["end_date"],
                            params["code_list"],
                        ),
                        endpoint=STATUS_ENDPOINT,
                        purpose=f"targeted_status_repair_{month}",
                    )
                    try:
                        rows, current_empty_members = _status_rows(exchange.payload, params)
                    except Exception as exc:  # noqa: BLE001 - no row values to stdout
                        month_state["structural_errors"] += 1
                        month_state["status"] = "BLOCKED_TARGETED_STRUCTURE"
                        self._save_state()
                        raise BuildFailure(
                            "TARGETED_STATUS_VALIDATION", type(exc).__name__
                        ) from None
                    batch_pairs: set[tuple[str, int]] = set()
                    for row in rows:
                        pair = (str(row["PROVIDER_SYMBOL"]), int(str(row["TRADE_DATE"])))
                        if pair not in target_pairs or pair not in missing:
                            month_state["extra_pairs"] += 1
                            month_state["status"] = "BLOCKED_TARGETED_EXTRA"
                            self._save_state()
                            raise BuildFailure(
                                "TARGETED_STATUS_VALIDATION", "UNEXPECTED_REPAIR_PAIR"
                            )
                        if pair in seen_pairs or pair in batch_pairs:
                            month_state["duplicate_pairs"] += 1
                            month_state["status"] = "BLOCKED_TARGETED_DUPLICATE"
                            self._save_state()
                            raise BuildFailure(
                                "TARGETED_STATUS_VALIDATION", "DUPLICATE_REPAIR_PAIR"
                            )
                        batch_pairs.add(pair)
                    normalization = self._normalize(
                        receipt,
                        provider_dataset="history_stock_status",
                        expected_status_rows=len(rows),
                        expected_status_pairs=batch_pairs,
                    )
                    seen_pairs.update(batch_pairs)
                    missing.difference_update(batch_pairs)
                    month_state["targeted_repair_requests"] += 1
                    month_state["targeted_rows_returned"] += len(rows)
                    month_state["empty_member_count"] += current_empty_members
                    receipt_item = {
                        "request_id": receipt["request_id"],
                        "raw_evidence_sha256": receipt["raw_evidence_sha256"],
                        "raw_content_sha256": receipt["raw_content_sha256"],
                        "raw_row_count": receipt["row_count"],
                        "accepted_row_count": len(rows),
                        "targeted": True,
                        "normalization_run_id": normalization["normalization_run_id"],
                        "normalization_manifest_sha256": normalization["manifest_sha256"],
                        "security_status_row_count": normalization["outputs"]["security_status"][
                            "row_count"
                        ],
                        "limit_price_row_count": normalization["outputs"]["limit_price"][
                            "row_count"
                        ],
                    }
                    receipt_rows.append(receipt_item)
                    normalization_runs.append(
                        {
                            "normalization_run_id": normalization["normalization_run_id"],
                            "manifest_sha256": normalization["manifest_sha256"],
                        }
                    )
                    month_state["status_receipts"] = receipt_rows
                    month_state["normalization_runs"] = normalization_runs
                    month_state["returned_pairs"] = len(seen_pairs)
                    self._save_state()
                    del exchange, rows, batch_pairs
                if month_state["targeted_repair_requests"] >= request_budget:
                    break

        unresolved = len(missing)
        month_state.update(
            {
                "returned_pairs": len(seen_pairs),
                "returned_pairs_security_status": len(seen_pairs),
                "returned_pairs_limit_price": len(seen_pairs),
                "unresolved_pairs": unresolved,
                "unresolved_pairs_security_status": unresolved,
                "unresolved_pairs_limit_price": unresolved,
                "status_receipt_count": len(receipt_rows),
                "status_receipt_set_sha256": _sha256_bytes(
                    "\n".join(str(item["raw_evidence_sha256"]) for item in receipt_rows).encode(
                        "ascii"
                    )
                ),
                "normalization_run_count": len(normalization_runs),
                "normalization_run_set_sha256": _sha256_bytes(
                    "\n".join(str(item["manifest_sha256"]) for item in normalization_runs).encode(
                        "ascii"
                    )
                ),
                "status": "PASS" if unresolved == 0 else "BLOCKED_COMPLETENESS",
            }
        )
        self._save_state()
        _emit(
            "MONTH_STATUS_CAPTURED",
            month=month,
            month_index=month_index,
            month_total=len(_months_in_scope()),
            expected_pairs=len(expected),
            returned_pairs=len(seen_pairs),
            missing_before_repair=missing_before_repair,
            unresolved_pairs=unresolved,
            targeted_repair_requests=month_state["targeted_repair_requests"],
            batch_sizes=dict(used_batch_sizes),
            provider_calls=self.call_count,
            rss_mb=round(_current_rss_bytes() / 1024**2, 1),
        )
        return month_state

    def build_canonical(self, *, expected_per_domain: int) -> dict[str, Any]:
        if _current_rss_bytes() > MAX_RSS_BYTES:
            raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_BEFORE_CANONICAL")
        as_of = datetime.now(UTC) + timedelta(seconds=2)
        try:
            result = CanonicalRunner(
                self.conn,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            ).run(as_of=as_of, domains=list(DOMAINS))
        except Exception as exc:  # noqa: BLE001 - canonical diagnostics stay local
            raise BuildFailure("CANONICAL", type(exc).__name__) from None
        if result.status != "SUCCESS" or result.finding_count != 0 or not result.manifest_uri:
            raise BuildFailure("CANONICAL", "CANONICAL_RUN_NOT_SUCCESSFUL")
        try:
            verified = verify_canonical_run_for_consumption(
                self.conn,
                result.canonical_run_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
        except Exception as exc:  # noqa: BLE001 - verifier messages may carry local details
            raise BuildFailure("CANONICAL_VERIFY", type(exc).__name__) from None
        if verified.status != "SUCCESS" or tuple(verified.requested_domains) != tuple(
            sorted(DOMAINS)
        ):
            raise BuildFailure("CANONICAL_VERIFY", "CANONICAL_SEAL_SCOPE_MISMATCH")
        domain_counts: Counter[str] = Counter()
        for row in verified.selected_rows:
            domain_counts[str(row.get("canonical_domain") or "")] += 1
        if domain_counts["security_status"] != expected_per_domain:
            raise BuildFailure("CANONICAL_VERIFY", "SECURITY_STATUS_SELECTED_COUNT_MISMATCH")
        if domain_counts["limit_price"] != expected_per_domain:
            raise BuildFailure("CANONICAL_VERIFY", "LIMIT_PRICE_SELECTED_COUNT_MISMATCH")
        if sum(domain_counts.values()) != result.selected_count:
            raise BuildFailure("CANONICAL_VERIFY", "SELECTED_ARTIFACT_COUNT_MISMATCH")
        manifest = verified.manifest
        selected = manifest.get("artifacts", {}).get("selected")
        if not isinstance(selected, dict):
            raise BuildFailure("CANONICAL_VERIFY", "SELECTED_ARTIFACT_SEAL_MISSING")
        canonical = {
            "canonical_run_id": result.canonical_run_id,
            "as_of": result.as_of,
            "status": verified.status,
            "requested_domains": list(verified.requested_domains),
            "selected_count": result.selected_count,
            "domain_selected_counts": {
                "security_status": domain_counts["security_status"],
                "limit_price": domain_counts["limit_price"],
            },
            "decision_count": result.decision_count,
            "finding_count": result.finding_count,
            "manifest_uri": result.manifest_uri,
            "manifest_sha256": result.manifest_hash,
            "selected_artifact_uri": str(selected.get("uri") or ""),
            "selected_artifact_sha256": str(selected.get("content_hash") or ""),
            "selected_artifact_row_count": int(selected.get("row_count", -1)),
            "selected_artifact_schema_sha256": str(selected.get("schema_hash") or ""),
        }
        del verified
        del result
        replay = CanonicalRunner(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        ).run(as_of=as_of, domains=list(DOMAINS))
        if (
            replay.status != "SUCCESS"
            or not replay.idempotent_replay
            or replay.canonical_run_id != canonical["canonical_run_id"]
            or replay.as_of != canonical["as_of"]
            or replay.manifest_uri != canonical["manifest_uri"]
            or replay.manifest_hash != canonical["manifest_sha256"]
            or replay.selected_count != canonical["selected_count"]
            or replay.decision_count != canonical["decision_count"]
            or replay.finding_count != canonical["finding_count"]
        ):
            raise BuildFailure("CANONICAL_REPLAY", "EXACT_REPLAY_MISMATCH")
        canonical["replay_idempotent"] = replay.idempotent_replay
        canonical["replay_manifest_sha256"] = replay.manifest_hash
        del replay
        if _current_rss_bytes() > MAX_RSS_BYTES:
            raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_AFTER_CANONICAL_REPLAY")
        return canonical

    def write_report(self, *, status: str, blocker: dict[str, str] | None = None) -> None:
        self.state["status"] = status
        self.state["completed_at_utc"] = datetime.now(UTC).isoformat()
        if blocker is not None:
            self.state["blocker"] = blocker
        self.state["receipt_log_sha256"] = (
            _sha256_file(self.receipt_path) if self.receipt_path.is_file() else None
        )
        report_path = self.run_root / "report.json"
        report_hash = _atomic_json(report_path, self.state)
        self.state["report_sha256"] = report_hash
        self._save_state()
        self._write_markdown_report()

    def _write_markdown_report(self) -> None:
        canonical = self.state.get("canonical") or {}
        identity = self.state.get("identity", {})
        list_date_gaps = identity.get("missing_list_date_count", "not reached")
        delist_date_gaps = identity.get("terminated_without_delist_date_count", "not reached")
        lines = [
            "# Issue #95 SH/SZ status + limit-price execution",
            "",
            f"- Status: `{self.state['status']}`",
            f"- Run ID: `{self.run_id}`",
            "- Scope: SH/SZ, 2020-01 through 2026-06 (78 months)",
            f"- Provider calls: {self.call_count}",
            f"- Identity list-date gaps: {list_date_gaps}",
            f"- Terminated identities missing DELISTDATE: {delist_date_gaps}",
            "",
            (
                "| Month | Expected status/limit pairs | Returned | Unresolved | "
                "Pre-listing N/A | Post-delisting N/A | Receipt-set SHA-256 |"
            ),
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for month in self.state.get("months", []):
            lines.append(
                (
                    "| {month} | {expected} / {expected} | {returned} | "
                    "{unresolved} | {pre} | {post} | `{receipt}` |"
                ).format(
                    month=month.get("month", ""),
                    expected=month.get("expected_pairs_security_status", "—"),
                    returned=month.get("returned_pairs", 0),
                    unresolved=month.get("unresolved_pairs", "—"),
                    pre=month.get("prelisting_nonapplicable_pairs", 0),
                    post=month.get("postdelisting_nonapplicable_pairs", 0),
                    receipt=month.get("status_receipt_set_sha256", "—"),
                )
            )
        lines.extend(["", "## Canonical", ""])
        if canonical:
            canonical_status = canonical.get("status")
            finding_count = canonical.get("finding_count")
            manifest_uri = canonical.get("manifest_uri")
            manifest_sha256 = canonical.get("manifest_sha256")
            selected_uri = canonical.get("selected_artifact_uri")
            selected_sha256 = canonical.get("selected_artifact_sha256")
            lines.extend(
                [
                    f"- Run: `{canonical.get('canonical_run_id')}`",
                    f"- Status: `{canonical_status}`; findings: {finding_count}",
                    f"- Manifest: `{manifest_uri}` ({manifest_sha256})",
                    f"- Selected artifact: `{selected_uri}` ({selected_sha256})",
                    f"- Selected rows by domain: {canonical.get('domain_selected_counts')}",
                ]
            )
        else:
            lines.append(
                "Canonical was not published because a prerequisite acceptance gate failed."
            )
        lines.extend(
            [
                "",
                "## Boundaries",
                "",
                (
                    "- Only the existing `security_status` and `limit_price` Canonical domains "
                    "were requested."
                ),
                (
                    "- The shared Normalizer may retain its auxiliary `corporate_action` "
                    "projection; it was not Canonicalized."
                ),
                (
                    "- No BSE, snapshot, daily-bar, direct corporate-action, strategy, or "
                    "Formal B1-B7 work was performed."
                ),
                (
                    "- Raw payloads and identity symbols remain local under this run root "
                    "and are not part of this summary."
                ),
                "",
            ]
        )
        (self.run_root / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _run_root() -> Path:
    parent = REPO_ROOT / "data" / "spike" / "issue95_status_limit"
    parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = parent / f"run_{stamp}_{uuid.uuid4().hex[:8]}"
    run_root.mkdir(parents=False, exist_ok=False)
    return run_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-status-batch-size",
        type=int,
        choices=STATUS_BATCH_FALLBACKS,
        default=STATUS_BATCH_FALLBACKS[0],
        help="Largest candidate tested through the live endpoint before the build selects a size.",
    )
    args = parser.parse_args()
    run_root = _run_root()
    run_rel = run_root.relative_to(REPO_ROOT).as_posix()
    _emit("RUN_CREATED", run_id=run_root.name.rsplit("_", 1)[-1], output_root=run_rel)
    session: AmazingDataSession | None = None
    build: Issue95Build | None = None
    try:
        manager = DuckDBConnectionManager(run_root / "ledger.duckdb")
        with manager.owner("read_write") as conn:
            apply_migrations(conn, REPO_ROOT / "migrations")
            credentials = _load_credentials_from_vault()
            session = AmazingDataSession(*credentials)
            credentials = ("", "", "", 0)
            profile = session.login()
            account_kind, _safe_reason = production_account_status(profile)
            if account_kind is not AccountKind.PRODUCTION:
                raise BuildFailure("ACCOUNT_GATE", "FROZEN_PRODUCTION_IDENTITY_MISMATCH")
            retry = RetryPolicy(
                max_retries=3,
                backoff_base_seconds=15,
                jitter_fraction=0.25,
                max_backoff_seconds=120,
                retryable_generic_query_failure_endpoints=(STATUS_ENDPOINT,),
            )
            provider = AmazingDataProvider(
                session,
                budget=TimeBudget(query_timeout_seconds=300, connect_timeout_seconds=15),
                retry=retry,
                use_mode=ProviderUseMode.SPIKE,
            )
            build = Issue95Build(
                run_root=run_root,
                max_status_batch_size=args.max_status_batch_size,
                conn=conn,
                provider=provider,
            )
            build.initialize_storage()
            _emit("ACCOUNT_GATE_PASS", status="FROZEN_PRODUCTION_IDENTITY_MATCH")
            calendars = build.acquire_calendars()
            all_symbols, universe_hashes = build.acquire_month_universes(calendars)
            identity_facts = build.acquire_stock_basics(all_symbols)
            build.probe_status_batch_size(
                month="2025-12",
                universe_hash=universe_hashes["2025-12"],
                calendars=calendars,
                identity_facts=identity_facts,
            )

            months = _months_in_scope()
            for month_index, month in enumerate(months, start=1):
                if _current_rss_bytes() > MAX_RSS_BYTES:
                    raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_DURING_CAPTURE")
                _emit(
                    "MONTH_STATUS_START",
                    month=month,
                    month_index=month_index,
                    month_total=len(months),
                )
                month_state = build.capture_month_status(
                    month=month,
                    month_index=month_index,
                    universe_hash=universe_hashes[month],
                    calendars=calendars,
                    identity_facts=identity_facts,
                )
                if _current_rss_bytes() > MAX_RSS_BYTES:
                    raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_AFTER_MONTH")
                if month_state["status"] == "BLOCKED_COMPLETENESS":
                    _emit(
                        "MONTH_COMPLETENESS_GAP",
                        month=month,
                        unresolved_pairs=month_state["unresolved_pairs"],
                        targeted_repair_requests=month_state["targeted_repair_requests"],
                    )

            identity_state = build.state.get("identity", {})
            blockers: list[str] = []
            if len(build.state["months"]) != 78:
                blockers.append("MONTH_COUNT_NOT_78")
            if any(item.get("unresolved_pairs") != 0 for item in build.state["months"]):
                blockers.append("UNRESOLVED_APPLICABLE_PAIRS")
            if any(
                item.get("extra_pairs", 0)
                or item.get("duplicate_pairs", 0)
                or item.get("structural_errors", 0)
                for item in build.state["months"]
            ):
                blockers.append("STATUS_INTEGRITY_ERRORS")
            if identity_state.get("missing_list_date_count", 0):
                blockers.append("IDENTITY_LIST_DATE_GAPS")
            if identity_state.get("terminated_without_delist_date_count", 0):
                blockers.append("TERMINATED_DELIST_DATE_GAPS")
            if blockers:
                build.write_report(
                    status="STOP_BLOCKED",
                    blocker={
                        "gate": "PRE_CANONICAL_ACCEPTANCE",
                        "reason_codes": ",".join(blockers),
                    },
                )
                _emit(
                    "STOP_BLOCKED",
                    gate="PRE_CANONICAL_ACCEPTANCE",
                    reason_codes=blockers,
                    run_root=run_rel,
                )
                return 2

            expected_per_domain = sum(
                int(item["expected_pairs_security_status"]) for item in build.state["months"]
            )
            canonical = build.build_canonical(expected_per_domain=expected_per_domain)
            build.state["canonical"] = canonical
            build.write_report(status="PASS")
            _emit(
                "BUILD_PASS",
                run_id=build.run_id,
                provider_calls=build.call_count,
                months=78,
                expected_pairs_per_domain=expected_per_domain,
                canonical_run_id=canonical["canonical_run_id"],
                selected_rows=canonical["selected_count"],
                report_root=run_rel,
            )
            return 0
    except BuildFailure as exc:
        if build is not None:
            with suppress(Exception):
                build.write_report(
                    status="STOP_BLOCKED",
                    blocker={"gate": exc.stage, "reason_code": exc.error_class},
                )
        _emit(
            "STOP_BLOCKED",
            failure_stage=exc.stage,
            error_class=exc.error_class,
            run_root=run_rel,
        )
        return 2
    except KeyboardInterrupt:
        if build is not None:
            with suppress(Exception):
                build.write_report(status="INTERRUPTED", blocker={"gate": "INTERRUPTED"})
        _emit("RUN_INTERRUPTED", run_root=run_rel)
        return 130
    except Exception as exc:  # noqa: BLE001 - no traceback/error payload reaches terminal
        if build is not None:
            with suppress(Exception):
                build.write_report(
                    status="STOP_BLOCKED",
                    blocker={"gate": "UNEXPECTED", "error_class": type(exc).__name__},
                )
        _emit(
            "STOP_BLOCKED",
            failure_stage="UNEXPECTED",
            error_class=type(exc).__name__,
            run_root=run_rel,
        )
        return 2
    finally:
        if session is not None:
            session.logout()


if __name__ == "__main__":
    raise SystemExit(main())
