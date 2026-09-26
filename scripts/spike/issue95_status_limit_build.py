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
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO, cast

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
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStderr,
    CapturedStdout,
    sdk_stderr_into,
    sdk_stdout_into,
)
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget
from ashare_state.research.historical import AMAZINGDATA_SECURITY_UNIVERSE_SELECTION
from ashare_state.storage.connection import DuckDBConnectionManager
from ashare_state.storage.migrations import apply_migrations
from ashare_state.storage.paths import physical_from_logical_uri
from ashare_state.storage.raw_anchor import (
    AnchoredRawEvidenceWriter,
    lookup_raw_evidence_anchor,
)
from ashare_state.storage.raw_writer import read_raw_payload, verify_raw_evidence

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
_PROGRESS_STREAM: TextIO | None = None


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
    print(
        json.dumps(safe, sort_keys=True, ensure_ascii=False),
        file=_PROGRESS_STREAM,
        flush=True,
    )


@contextmanager
def _quarantine_untrusted_sdk_output() -> Iterator[None]:
    """Quarantine native SDK writes for the whole runner process.

    Per-call capture remains the primary boundary. This outer fd/Win32 handle
    capture also catches delayed SDK diagnostics that arrive after a call's
    local capture context has closed. Safe runner progress uses a duplicate of
    the original stdout handle and is the only text routed to the terminal.
    """
    global _PROGRESS_STREAM
    stdout_holder = CapturedStdout()
    stderr_holder = CapturedStderr()
    progress_stream = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    previous_progress_stream = _PROGRESS_STREAM
    try:
        with sdk_stdout_into(stdout_holder, independent=True), sdk_stderr_into(stderr_holder):
            _PROGRESS_STREAM = progress_stream
            yield
    finally:
        _PROGRESS_STREAM = previous_progress_stream
        with suppress(Exception):
            progress_stream.flush()
        progress_stream.close()
        stdout_holder.text = ""
        stderr_holder.text = ""


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
        initial_state: dict[str, Any] | None = None,
    ) -> None:
        self.run_root = run_root
        self.conn = conn
        self.provider = provider
        self.raw_root = run_root / "raw"
        self.normalized_root = run_root / "normalized"
        self.canonical_root = self.normalized_root / "canonical"
        self.database_path = run_root / "ledger.duckdb"
        self.receipt_path = run_root / "receipts.jsonl"
        self.coverage_receipt_path = run_root / "coverage_receipts.json"
        self.universe_root = run_root / "denominator" / "universe_by_month"
        self.status_batch_size = min(STATUS_BATCH_PROBE_SIZES)
        self.max_status_batch_size = max_status_batch_size
        self.run_id = str((initial_state or {}).get("run_id") or uuid.uuid4())
        self.resume_mapper_verified = (initial_state or {}).get("resume", {}).get(
            "current_mapper_replay_verified"
        ) is True
        self.call_count = int(
            ((initial_state or {}).get("receipts") or {}).get("provider_call_count") or 0
        )
        self.rate_gate = RateGate()
        self.state: dict[str, Any] = initial_state or {
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
            "coverage_receipts": {},
            "status_batch_size_probe": None,
            "canonical": None,
        }
        if initial_state is None:
            self._save_state()
        else:
            selected_batch = (self.state.get("status_batch_size_probe") or {}).get(
                "selected_size"
            ) or (self.state.get("request_policy") or {}).get("status_batch_size_selected")
            if isinstance(selected_batch, int) and selected_batch in STATUS_BATCH_FALLBACKS:
                self.status_batch_size = selected_batch

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

    def initialize_storage(self, *, resume: bool = False) -> None:
        if resume:
            if not all(
                path.is_dir() for path in (self.raw_root, self.normalized_root, self.universe_root)
            ):
                raise BuildFailure("RESUME", "RETAINED_STORAGE_DIRECTORY_MISSING")
        else:
            self.raw_root.mkdir(parents=True, exist_ok=False)
            self.normalized_root.mkdir(parents=True, exist_ok=False)
            self.universe_root.mkdir(parents=True, exist_ok=False)
        self.raw_writer = AnchoredRawEvidenceWriter(
            self.conn,
            self.raw_root,
            ingest_run_id=self.run_id,
        )

    def _read_receipt_log(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        try:
            entries = [
                json.loads(line)
                for line in self.receipt_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except Exception as exc:  # noqa: BLE001 - local receipt details stay private
            raise BuildFailure("RESUME_RECEIPTS", type(exc).__name__) from None
        if len(entries) != self.call_count:
            raise BuildFailure("RESUME_RECEIPTS", "PROVIDER_CALL_COUNT_MISMATCH")
        by_request: dict[str, dict[str, Any]] = {}
        for entry in entries:
            request_id = str(entry.get("request_id") or "")
            if not request_id or request_id in by_request:
                raise BuildFailure("RESUME_RECEIPTS", "DUPLICATE_OR_EMPTY_REQUEST_ID")
            by_request[request_id] = entry
        return entries, by_request

    def _verify_raw_receipt(
        self,
        receipt_entry: dict[str, Any],
        receipt_index: dict[str, dict[str, Any]],
    ) -> tuple[Any, dict[str, Any]]:
        request_id = str(receipt_entry.get("request_id") or "")
        log_entry = receipt_index.get(request_id)
        if log_entry is None or log_entry.get("exchange_status") != "OK":
            raise BuildFailure("RESUME_RAW", "SUCCESS_RECEIPT_NOT_FOUND")
        if (
            (
                receipt_entry.get("provider_dataset") is not None
                and log_entry.get("provider_dataset") != receipt_entry.get("provider_dataset")
            )
            or (
                receipt_entry.get("raw_evidence_sha256") is not None
                and log_entry.get("raw_evidence_sha256") != receipt_entry.get("raw_evidence_sha256")
            )
            or (
                receipt_entry.get("raw_content_sha256") is not None
                and log_entry.get("raw_content_sha256") != receipt_entry.get("raw_content_sha256")
            )
        ):
            raise BuildFailure("RESUME_RAW", "RECEIPT_HASH_OR_DATASET_MISMATCH")
        provider = "amazingdata"
        dataset = str(log_entry["provider_dataset"])
        anchor = lookup_raw_evidence_anchor(
            self.conn,
            provider=provider,
            provider_dataset=dataset,
            request_id=request_id,
        )
        if anchor is None or anchor.evidence_hash != log_entry["raw_evidence_sha256"]:
            raise BuildFailure("RESUME_RAW", "RAW_EVIDENCE_ANCHOR_MISMATCH")
        try:
            verified = verify_raw_evidence(
                self.raw_root,
                provider=provider,
                dataset=dataset,
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001 - raw details stay local
            raise BuildFailure("RESUME_RAW", type(exc).__name__) from None
        meta = verified.meta if isinstance(verified.meta, dict) else {}
        if (
            verified.evidence_hash != log_entry["raw_evidence_sha256"]
            or verified.content_hash != log_entry["raw_content_sha256"]
            or meta.get("endpoint") != log_entry.get("endpoint")
            or meta.get("request_params_hash") != log_entry.get("request_params_sha256")
            or meta.get("status") != "OK"
        ):
            raise BuildFailure("RESUME_RAW", "RAW_EVIDENCE_RECEIPT_BINDING_MISMATCH")
        return verified, meta

    @staticmethod
    def _payload_values(payload: Any, *, label: str) -> list[Any]:
        if isinstance(payload, pl.DataFrame):
            if len(payload.columns) != 1:
                raise BuildFailure("RESUME_DENOMINATOR", f"{label}_RAW_SHAPE_UNSUPPORTED")
            return payload.get_column(payload.columns[0]).to_list()
        if isinstance(payload, pl.Series):
            return payload.to_list()
        if isinstance(payload, list):
            return payload
        raise BuildFailure("RESUME_DENOMINATOR", f"{label}_RAW_SHAPE_UNSUPPORTED")

    def _persist_missing_keys(
        self,
        *,
        month: str,
        missing: set[tuple[str, int]],
        expected_count: int,
        returned_count: int,
    ) -> tuple[str, str]:
        missing_root = self.run_root / "denominator" / "missing_keys_by_month"
        missing_root.mkdir(parents=True, exist_ok=True)
        relative = Path("denominator") / "missing_keys_by_month" / f"{month}.json"
        ordered = sorted(missing, key=lambda pair: (pair[1], pair[0]))
        document = {
            "schema": "issue95_missing_key_set.v1",
            "month": month,
            "key_fields": ["provider_symbol", "trade_date"],
            "expected_pair_count": expected_count,
            "returned_pair_count": returned_count,
            "missing_pair_count": len(ordered),
            "keys": [[symbol, trade_day] for symbol, trade_day in ordered],
        }
        content_hash = _atomic_json(self.run_root / relative, document)
        return relative.as_posix(), content_hash

    def _verify_missing_keys(
        self,
        *,
        relative_uri: str,
        expected_hash: str,
        expected_count: int,
        returned_count: int,
    ) -> None:
        path = (self.run_root / relative_uri).resolve()
        try:
            path.relative_to(self.run_root.resolve())
        except ValueError:
            raise BuildFailure("MISSING_KEY_SET", "ARTIFACT_ESCAPES_RUN_ROOT") from None
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise BuildFailure("MISSING_KEY_SET", "ARTIFACT_HASH_MISMATCH")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - exact keys are local evidence
            raise BuildFailure("MISSING_KEY_SET", type(exc).__name__) from None
        keys = document.get("keys")
        if (
            document.get("schema") != "issue95_missing_key_set.v1"
            or document.get("expected_pair_count") != expected_count
            or document.get("returned_pair_count") != returned_count
            or document.get("missing_pair_count") != expected_count - returned_count
            or not isinstance(keys, list)
            or len(keys) != expected_count - returned_count
            or len({(str(item[0]), int(item[1])) for item in keys}) != len(keys)
        ):
            raise BuildFailure("MISSING_KEY_SET", "ARTIFACT_CONTENT_MISMATCH")

    def _write_coverage_receipts(self) -> None:
        receipts = self._coverage_receipt_rows()
        digest = _atomic_json(
            self.coverage_receipt_path,
            {"schema": "issue95_month_coverage_receipts.v1", "receipts": receipts},
        )
        self.state["coverage_receipts"] = {
            "uri": self.coverage_receipt_path.name,
            "record_count": len(receipts),
            "sha256": digest,
        }

    def _verify_coverage_receipts(self) -> None:
        saved = self.state["coverage_receipts"]
        if (
            not self.coverage_receipt_path.is_file()
            or _sha256_file(self.coverage_receipt_path) != saved["sha256"]
        ):
            raise BuildFailure("COVERAGE_RECEIPTS", "ARTIFACT_HASH_MISMATCH")
        try:
            document = json.loads(self.coverage_receipt_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - exact coverage values stay local
            raise BuildFailure("COVERAGE_RECEIPTS", type(exc).__name__) from None
        if (
            document.get("schema") != "issue95_month_coverage_receipts.v1"
            or document.get("receipts") is None
            or document.get("receipts") != self._coverage_receipt_rows()
            or saved.get("record_count") != len(document["receipts"])
        ):
            raise BuildFailure("COVERAGE_RECEIPTS", "ARTIFACT_CONTENT_MISMATCH")

    def _coverage_receipt_rows(self) -> list[dict[str, Any]]:
        receipts = []
        for item in self.state.get("months", []):
            coverage = item.get("coverage_status")
            if coverage not in {"COMPLETE", "PARTIAL_UPSTREAM_COVERAGE"}:
                continue
            receipts.append(
                {
                    "month": item["month"],
                    "coverage_status": coverage,
                    "expected_pairs_per_domain": int(item["expected_pairs_security_status"]),
                    "returned_pairs_per_domain": int(item["returned_pairs_security_status"]),
                    "missing_pairs_per_domain": int(item["missing_pairs_security_status"]),
                    "missing_key_set_uri": item["missing_key_set_uri"],
                    "missing_key_set_sha256": item["missing_key_set_sha256"],
                }
            )
        return receipts

    def begin_resume(self, *, source_manifest_sha256: str, source_report_sha256: str) -> None:
        self.state["resume"] = {
            "source_manifest_sha256": source_manifest_sha256,
            "source_report_sha256": source_report_sha256,
            "started_at_utc": datetime.now(UTC).isoformat(),
            "replayed_mapper_code_hash": __import__(
                "ashare_state.normalization.registry", fromlist=["MAPPER_CODE_FINGERPRINT"]
            ).MAPPER_CODE_FINGERPRINT,
            "current_mapper_replay_verified": self.resume_mapper_verified,
        }
        self.state["status"] = "RUNNING"
        self._save_state()

    def _verify_old_normalization_ref(
        self,
        normalization_ref: dict[str, Any],
        *,
        request_id: str,
        provider_dataset: str,
    ) -> None:
        expected_manifest_hash = normalization_ref.get("manifest_sha256") or normalization_ref.get(
            "normalization_manifest_sha256"
        )
        row = self.conn.execute(
            "SELECT raw_request_id, provider_dataset, normalized_manifest_hash, status "
            "FROM meta_provider_normalization_run WHERE normalization_run_id = ?",
            [normalization_ref.get("normalization_run_id")],
        ).fetchone()
        if (
            row is None
            or row[0] != request_id
            or row[1] != provider_dataset
            or row[2] != expected_manifest_hash
            or row[3] != "SUCCESS"
        ):
            raise BuildFailure("RESUME_NORMALIZATION", "RETAINED_NORMALIZATION_REF_MISMATCH")

    def _replay_identity_facts(
        self,
        *,
        identity_document: dict[str, Any],
        receipt_index: dict[str, dict[str, Any]],
        all_symbols: set[str],
    ) -> dict[str, dict[str, Any]]:
        stored_runs = self.state.get("identity", {}).get("runs")
        if not isinstance(stored_runs, list) or not stored_runs:
            raise BuildFailure("RESUME_IDENTITY", "RETAINED_IDENTITY_RUNS_MISSING")
        prior_run_hash = _sha256_bytes(
            "\n".join(str(run.get("normalization_manifest_sha256")) for run in stored_runs).encode(
                "ascii"
            )
        )
        if len(stored_runs) != int(
            self.state.get("identity", {}).get("normalization_run_count", -1)
        ) or prior_run_hash != self.state.get("identity", {}).get("normalization_run_set_sha256"):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_NORMALIZATION_SET_HASH_MISMATCH")
        replayed: dict[str, dict[str, Any]] = {}
        updated_runs: list[dict[str, Any]] = []
        for original in stored_runs:
            run = dict(original)
            request_id = str(run.get("request_id") or "")
            log_entry = receipt_index.get(request_id)
            if (
                log_entry is None
                or log_entry.get("purpose") not in {"stock_basic", "stock_basic_targeted_refresh"}
                or log_entry.get("raw_evidence_sha256") != run.get("raw_evidence_sha256")
                or log_entry.get("provider_dataset") != "stock_basic"
            ):
                raise BuildFailure("RESUME_IDENTITY", "IDENTITY_RECEIPT_BINDING_MISMATCH")
            verified, meta = self._verify_raw_receipt(log_entry, receipt_index)
            params = meta.get("request_params")
            symbols = params.get("code_list") if isinstance(params, dict) else None
            if not isinstance(symbols, list) or not symbols:
                raise BuildFailure("RESUME_IDENTITY", "IDENTITY_REQUEST_MEMBERS_MISSING")
            requested = {str(symbol).strip().upper() for symbol in symbols}
            if (
                len(requested) != len(symbols)
                or not requested.issubset(all_symbols)
                or len(requested) != int(run.get("requested_count", -1))
            ):
                raise BuildFailure("RESUME_IDENTITY", "IDENTITY_REQUEST_MEMBER_MISMATCH")
            self._verify_old_normalization_ref(
                run,
                request_id=request_id,
                provider_dataset="stock_basic",
            )
            normalization = self._normalize(
                {"request_id": request_id},
                provider_dataset="stock_basic",
            )
            rows = self._read_normalized_main_rows(normalization)
            if len(rows) != int(run.get("returned_count", -1)):
                raise BuildFailure("RESUME_IDENTITY", "IDENTITY_REPLAY_ROW_COUNT_MISMATCH")
            self._merge_identity_rows(
                rows,
                requested=requested,
                identity_facts=replayed,
            )
            if run.get("normalization_run_id") != normalization["normalization_run_id"]:
                run["prior_normalization_run_id"] = run["normalization_run_id"]
                run["prior_normalization_manifest_sha256"] = run["normalization_manifest_sha256"]
            run["normalization_run_id"] = normalization["normalization_run_id"]
            run["normalization_manifest_sha256"] = normalization["manifest_sha256"]
            updated_runs.append(run)

        approved_static_fills = 0
        for event in approved_provider_identity_events():
            for symbol in (event.old_provider_symbol, event.new_provider_symbol):
                if symbol not in all_symbols:
                    continue
                current = replayed.get(symbol)
                if current is None or current["list_date"] is None:
                    replayed[symbol] = {
                        "provider_symbol": symbol,
                        "list_date": event.original_list_date.isoformat(),
                        "delist_date": current["delist_date"] if current else None,
                        "is_listed": current["is_listed"] if current else None,
                        "identity_source": "approved_static_identity_event",
                    }
                    approved_static_fills += 1

        stored_facts = identity_document.get("facts")
        if not isinstance(stored_facts, list):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_FILE_SHAPE_INVALID")
        stored_by_symbol = {
            str(fact.get("provider_symbol") or ""): fact
            for fact in stored_facts
            if isinstance(fact, dict)
        }
        if (
            len(stored_by_symbol) != len(stored_facts)
            or replayed != stored_by_symbol
            or set(replayed) != all_symbols
        ):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_REPLAY_MISMATCH")
        identity_state = self.state["identity"]
        identity_state["runs"] = updated_runs
        identity_state["normalization_run_count"] = len(updated_runs)
        identity_state["normalization_run_set_sha256"] = _sha256_bytes(
            "\n".join(str(run["normalization_manifest_sha256"]) for run in updated_runs).encode(
                "ascii"
            )
        )
        identity_state["approved_static_identity_fills"] = approved_static_fills
        return replayed

    def _verify_current_normalization_ref(
        self,
        normalization_ref: dict[str, Any],
        *,
        request_id: str,
        provider_dataset: str,
    ) -> None:
        from ashare_state.normalization.registry import MAPPER_CODE_FINGERPRINT

        self._verify_old_normalization_ref(
            normalization_ref,
            request_id=request_id,
            provider_dataset=provider_dataset,
        )
        row = self.conn.execute(
            "SELECT mapper_code_hash FROM meta_provider_normalization_run "
            "WHERE normalization_run_id = ?",
            [normalization_ref.get("normalization_run_id")],
        ).fetchone()
        if row is None or row[0] != MAPPER_CODE_FINGERPRINT:
            raise BuildFailure("RESUME_NORMALIZATION", "CURRENT_MAPPER_REPLAY_MISSING")

    def _load_verified_resume_context(
        self,
    ) -> tuple[
        dict[str, set[int]],
        dict[str, dict[str, Any]],
        dict[str, str],
        dict[str, set[tuple[str, int]]],
        dict[str, set[str]],
    ]:
        """Reuse the sealed first-pass replay and only reconstruct in-flight months.

        The complete retained evidence replay has already been verified and
        checkpointed in ``resume.current_mapper_replay_verified``. On a later
        interruption, accepted months are bound to their saved raw/normalizer
        receipt sets and missing-key hashes instead of re-running thousands of
        identical Normalizer calls. Any in-flight month is still rebuilt from
        its raw rows before capture resumes.
        """
        if not self.resume_mapper_verified:
            raise BuildFailure("RESUME", "VERIFIED_REPLAY_CHECKPOINT_MISSING")
        entries, receipt_index = self._read_receipt_log()
        purposes: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            if entry.get("exchange_status") == "OK":
                purposes.setdefault(str(entry.get("purpose") or ""), []).append(entry)

        calendars: dict[str, set[int]] = {}
        for market in ("SH", "SZ"):
            matching = purposes.get(f"calendar_{market}", [])
            calendar_state = self.state.get("calendars", {}).get(market, {})
            receipt_ref = calendar_state.get("receipt", {})
            if len(matching) != 1 or matching[0].get("raw_evidence_sha256") != receipt_ref.get(
                "raw_evidence_sha256"
            ):
                raise BuildFailure("RESUME_CALENDAR", "CALENDAR_RECEIPT_MISMATCH")
            verified, _meta = self._verify_raw_receipt(matching[0], receipt_index)
            payload = read_raw_payload(
                self.raw_root,
                provider="amazingdata",
                dataset=str(matching[0]["provider_dataset"]),
                request_id=str(matching[0]["request_id"]),
                verified=verified,
            )
            days = _validate_calendar(
                self._payload_values(payload, label="CALENDAR"),
                start=START_DATE,
                end=END_DATE,
            )
            if len(days) != int(calendar_state.get("session_count", -1)):
                raise BuildFailure("RESUME_CALENDAR", "CALENDAR_SESSION_COUNT_MISMATCH")
            calendars[market] = set(days)

        month_states = {item["month"]: item for item in self.state.get("months", [])}
        if set(month_states) != set(_months_in_scope()):
            raise BuildFailure("RESUME_DENOMINATOR", "MONTH_SCOPE_MISMATCH")
        universe_hashes: dict[str, str] = {}
        universes: dict[str, dict[str, Any]] = {}
        all_symbols: set[str] = set()
        for month in _months_in_scope():
            month_state = month_states[month]
            universe_path = self.universe_root / f"{month}.json"
            universe_hash = str(month_state.get("universe_file_sha256") or "")
            if not universe_path.is_file() or _sha256_file(universe_path) != universe_hash:
                raise BuildFailure("RESUME_DENOMINATOR", "MONTH_UNIVERSE_HASH_MISMATCH")
            try:
                universe = json.loads(universe_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - local symbols remain private
                raise BuildFailure("RESUME_DENOMINATOR", type(exc).__name__) from None
            if (
                universe.get("schema") != "issue95_month_universe.v1"
                or universe.get("month") != month
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTH_UNIVERSE_IDENTITY_MISMATCH")
            monthly_symbols = _validate_security_universe(universe.get("monthly_symbols"))
            if monthly_symbols != universe.get("monthly_symbols"):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTH_UNIVERSE_NOT_CANONICAL")
            monthly_receipts = purposes.get(f"monthly_universe_{month}", [])
            if (
                len(monthly_receipts) != 1
                or monthly_receipts[0].get("raw_evidence_sha256")
                != month_state.get("monthly_universe_receipt_sha256")
                or monthly_receipts[0].get("raw_evidence_sha256")
                != universe.get("monthly_universe_receipt_sha256")
                or monthly_receipts[0].get("endpoint") != "BaseData.get_hist_code_list"
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTHLY_UNIVERSE_RECEIPT_MISMATCH")
            verified, _meta = self._verify_raw_receipt(monthly_receipts[0], receipt_index)
            payload = read_raw_payload(
                self.raw_root,
                provider="amazingdata",
                dataset=str(monthly_receipts[0]["provider_dataset"]),
                request_id=str(monthly_receipts[0]["request_id"]),
                verified=verified,
            )
            if (
                _validate_security_universe(self._payload_values(payload, label="MONTHLY_UNIVERSE"))
                != monthly_symbols
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTHLY_UNIVERSE_REPLAY_MISMATCH")

            session_rows = universe.get("session_universes")
            session_receipts = purposes.get(f"session_universe_{month}", [])
            if (
                not isinstance(session_rows, list)
                or len(session_rows) != int(month_state.get("exchange_session_count", -1))
                or len(session_receipts)
                != int(month_state.get("session_universe_receipt_count", -1))
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_RECEIPT_COUNT_MISMATCH")
            receipt_hash = _sha256_bytes(
                "\n".join(str(item["raw_evidence_sha256"]) for item in session_receipts).encode(
                    "ascii"
                )
            )
            if receipt_hash != month_state.get(
                "session_receipt_set_sha256"
            ) or receipt_hash != universe.get("session_receipt_set_sha256"):
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_RECEIPT_SET_MISMATCH")
            session_days: list[int] = []
            for saved, receipt in zip(session_rows, session_receipts, strict=True):
                try:
                    day = int(saved["trade_date"])
                    saved_symbols = _validate_security_universe(saved["symbols"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise BuildFailure("RESUME_DENOMINATOR", type(exc).__name__) from None
                if (
                    saved_symbols != saved.get("symbols")
                    or not set(saved_symbols).issubset(monthly_symbols)
                    or receipt.get("endpoint") != "BaseData.get_hist_code_list"
                    or not receipt.get("raw_evidence_sha256")
                ):
                    raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_ENTRY_INVALID")
                session_days.append(day)
                all_symbols.update(saved_symbols)
            if session_days != sorted(session_days):
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_ORDER_MISMATCH")
            month_start, month_finish = _month_bounds(month)
            first = month_start.year * 10000 + month_start.month * 100 + month_start.day
            last = month_finish.year * 10000 + month_finish.month * 100 + month_finish.day
            expected_sessions = sorted(
                day for day in calendars["SH"] | calendars["SZ"] if first <= day <= last
            )
            if session_days != expected_sessions:
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_CALENDAR_DATE_SET_MISMATCH")
            all_symbols.update(monthly_symbols)
            universe_hashes[month] = universe_hash
            universes[month] = universe

        identity_path = self.run_root / "denominator" / "identity_facts.json"
        identity_state = self.state.get("identity", {})
        if not identity_path.is_file() or _sha256_file(identity_path) != identity_state.get(
            "facts_sha256"
        ):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_FILE_HASH_MISMATCH")
        try:
            identity_document = json.loads(identity_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - local identity values remain private
            raise BuildFailure("RESUME_IDENTITY", type(exc).__name__) from None
        facts = identity_document.get("facts")
        if (
            identity_document.get("schema") != "issue95_identity_facts.v1"
            or not isinstance(facts, list)
            or len(facts) != int(identity_state.get("identity_covered_symbol_count", -1))
            or int(identity_state.get("requested_symbol_count", -1)) != len(all_symbols)
            or identity_state.get("missing_list_date_count") != 0
            or identity_state.get("terminated_without_delist_date_count") != 0
        ):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_SCOPE_MISMATCH")
        identity_facts = {
            str(item.get("provider_symbol") or ""): item for item in facts if isinstance(item, dict)
        }
        if len(identity_facts) != len(facts) or set(identity_facts) != all_symbols:
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_SYMBOL_SET_MISMATCH")
        identity_runs = identity_state.get("runs") or []
        identity_hash = _sha256_bytes(
            "\n".join(
                str(item.get("normalization_manifest_sha256")) for item in identity_runs
            ).encode("ascii")
        )
        if len(identity_runs) != int(
            identity_state.get("normalization_run_count", -1)
        ) or identity_hash != identity_state.get("normalization_run_set_sha256"):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_NORMALIZATION_SET_HASH_MISMATCH")
        for identity_ref in identity_runs:
            request_id = str(identity_ref.get("request_id") or "")
            receipt = receipt_index.get(request_id)
            if (
                receipt is None
                or receipt.get("purpose") not in {"stock_basic", "stock_basic_targeted_refresh"}
                or receipt.get("provider_dataset") != "stock_basic"
                or receipt.get("raw_evidence_sha256") != identity_ref.get("raw_evidence_sha256")
            ):
                raise BuildFailure("RESUME_IDENTITY", "IDENTITY_RECEIPT_BINDING_MISMATCH")
            self._verify_current_normalization_ref(
                identity_ref,
                request_id=request_id,
                provider_dataset="stock_basic",
            )

        verified_pairs: dict[str, set[tuple[str, int]]] = {}
        captured_symbols: dict[str, set[str]] = {}
        accepted = {"COMPLETE", "PARTIAL_UPSTREAM_COVERAGE"}
        reused_months = 0
        reconstructed_months = 0
        for month in _months_in_scope():
            month_state = month_states[month]
            universe = universes[month]
            expected, denominator_counts = self._expected_pairs_for_month(
                month=month,
                universe=universe,
                calendars=calendars,
                identity_facts=identity_facts,
            )
            for domain in DOMAINS:
                expected_field = f"expected_pairs_{domain}"
                saved_expected = month_state.get(expected_field)
                if saved_expected is not None and int(saved_expected) != len(expected):
                    raise BuildFailure("RESUME_DENOMINATOR", "EXPECTED_PAIR_COUNT_CHANGED")
                month_state[expected_field] = len(expected)
            month_state.update(denominator_counts)
            receipt_rows = month_state.get("status_receipts") or []
            normalization_refs = month_state.get("normalization_runs") or []
            if len(receipt_rows) != len(normalization_refs):
                raise BuildFailure("RESUME_STATUS", "STATUS_NORMALIZATION_REF_COUNT_MISMATCH")
            receipt_hash = _sha256_bytes(
                "\n".join(str(item.get("raw_evidence_sha256")) for item in receipt_rows).encode(
                    "ascii"
                )
            )
            normalization_hash = _sha256_bytes(
                "\n".join(str(item.get("manifest_sha256")) for item in normalization_refs).encode(
                    "ascii"
                )
            )
            if month_state.get("coverage_status") in accepted:
                if (
                    receipt_hash != month_state.get("status_receipt_set_sha256")
                    or normalization_hash != month_state.get("normalization_run_set_sha256")
                    or len(receipt_rows) != int(month_state.get("status_receipt_count", -1))
                    or len(normalization_refs)
                    != int(month_state.get("normalization_run_count", -1))
                ):
                    raise BuildFailure("RESUME_STATUS", "ACCEPTED_MONTH_RECEIPT_SET_MISMATCH")
                for receipt_item, normalization_ref in zip(
                    receipt_rows, normalization_refs, strict=True
                ):
                    request_id = str(receipt_item.get("request_id") or "")
                    log_entry = receipt_index.get(request_id)
                    if (
                        log_entry is None
                        or log_entry.get("purpose")
                        not in {f"status_limit_{month}", f"targeted_status_repair_{month}"}
                        or log_entry.get("provider_dataset") != "history_stock_status"
                        or log_entry.get("raw_evidence_sha256")
                        != receipt_item.get("raw_evidence_sha256")
                        or receipt_item.get("normalization_run_id")
                        != normalization_ref.get("normalization_run_id")
                        or receipt_item.get("normalization_manifest_sha256")
                        != normalization_ref.get("manifest_sha256")
                    ):
                        raise BuildFailure("RESUME_STATUS", "STATUS_RECEIPT_BINDING_MISMATCH")
                    self._verify_current_normalization_ref(
                        normalization_ref,
                        request_id=request_id,
                        provider_dataset="history_stock_status",
                    )
                expected_count = len(expected)
                returned_count = int(month_state.get("returned_pairs_security_status", -1))
                missing_count = int(month_state.get("missing_pairs_security_status", -1))
                if (
                    month_state.get("returned_pairs_limit_price") != returned_count
                    or month_state.get("returned_pairs") != returned_count
                    or month_state.get("unresolved_pairs") != missing_count
                    or month_state.get("missing_pairs_limit_price") != missing_count
                    or returned_count + missing_count != expected_count
                ):
                    raise BuildFailure("RESUME_STATUS", "ACCEPTED_MONTH_COUNT_MISMATCH")
                self._verify_missing_keys(
                    relative_uri=str(month_state.get("missing_key_set_uri") or ""),
                    expected_hash=str(month_state.get("missing_key_set_sha256") or ""),
                    expected_count=expected_count,
                    returned_count=returned_count,
                )
                verified_pairs[month] = set()
                captured_symbols[month] = set()
                reused_months += 1
                continue

            month_pairs: set[tuple[str, int]] = set()
            requested_symbols: set[str] = set()
            month_symbols = set(universe["monthly_symbols"])
            start, finish = _month_bounds(month)
            month_begin = start.year * 10000 + start.month * 100 + start.day
            month_end = finish.year * 10000 + finish.month * 100 + finish.day
            for receipt_item, normalization_ref in zip(
                receipt_rows, normalization_refs, strict=True
            ):
                request_id = str(receipt_item.get("request_id") or "")
                log_entry = receipt_index.get(request_id)
                if (
                    log_entry is None
                    or log_entry.get("purpose")
                    not in {f"status_limit_{month}", f"targeted_status_repair_{month}"}
                    or log_entry.get("provider_dataset") != "history_stock_status"
                    or log_entry.get("raw_evidence_sha256")
                    != receipt_item.get("raw_evidence_sha256")
                    or receipt_item.get("normalization_run_id")
                    != normalization_ref.get("normalization_run_id")
                    or receipt_item.get("normalization_manifest_sha256")
                    != normalization_ref.get("manifest_sha256")
                ):
                    raise BuildFailure("RESUME_STATUS", "STATUS_RECEIPT_BINDING_MISMATCH")
                verified, meta = self._verify_raw_receipt(receipt_item, receipt_index)
                params = meta.get("request_params")
                codes = params.get("code_list") if isinstance(params, dict) else None
                if not isinstance(codes, list) or not codes:
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_MEMBERS_MISSING")
                normalized_codes = [str(symbol).strip().upper() for symbol in codes]
                if len(set(normalized_codes)) != len(normalized_codes) or not set(
                    normalized_codes
                ).issubset(month_symbols):
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_MEMBER_MISMATCH")
                try:
                    begin_date = int(params["begin_date"])
                    end_date = int(params["end_date"])
                except KeyError, TypeError, ValueError:
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_WINDOW_INVALID") from None
                targeted = (
                    bool(receipt_item.get("targeted"))
                    or log_entry.get("purpose") == f"targeted_status_repair_{month}"
                )
                if begin_date == month_begin and end_date == month_end:
                    if targeted:
                        raise BuildFailure("RESUME_STATUS", "TARGETED_REQUEST_WINDOW_INVALID")
                    if requested_symbols.intersection(normalized_codes):
                        raise BuildFailure("RESUME_STATUS", "DUPLICATE_STATUS_REQUEST_SYMBOL")
                    requested_symbols.update(normalized_codes)
                elif not (
                    targeted and begin_date == end_date and month_begin <= begin_date <= month_end
                ):
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_WINDOW_INVALID")
                payload = read_raw_payload(
                    self.raw_root,
                    provider="amazingdata",
                    dataset="history_stock_status",
                    request_id=request_id,
                    verified=verified,
                )
                rows, _empty_members = _status_rows(payload, params)
                if len(rows) != int(receipt_item.get("accepted_row_count", -1)):
                    raise BuildFailure("RESUME_STATUS", "STATUS_RAW_ROW_COUNT_MISMATCH")
                for row in rows:
                    day = _provider_day(row.get("TRADE_DATE"))
                    symbol = str(row.get("PROVIDER_SYMBOL") or "").strip().upper()
                    if day is None or not symbol:
                        raise BuildFailure("RESUME_STATUS", "STATUS_ROW_KEY_INVALID")
                    pair = (symbol, int(day.strftime("%Y%m%d")))
                    if pair not in expected or pair in month_pairs:
                        raise BuildFailure("RESUME_STATUS", "STATUS_PAIR_EXTRA_OR_DUPLICATE")
                    month_pairs.add(pair)
                self._verify_current_normalization_ref(
                    normalization_ref,
                    request_id=request_id,
                    provider_dataset="history_stock_status",
                )
                if int(receipt_item.get("security_status_row_count", -1)) != len(rows) or int(
                    receipt_item.get("limit_price_row_count", -1)
                ) != len(rows):
                    raise BuildFailure("RESUME_STATUS", "STATUS_PROJECTION_COUNT_MISMATCH")
            verified_pairs[month] = month_pairs
            captured_symbols[month] = requested_symbols
            month_state["returned_pairs"] = len(month_pairs)
            month_state["returned_pairs_security_status"] = len(month_pairs)
            month_state["returned_pairs_limit_price"] = len(month_pairs)
            month_state["unresolved_pairs"] = len(expected - month_pairs)
            month_state["unresolved_pairs_security_status"] = len(expected - month_pairs)
            month_state["unresolved_pairs_limit_price"] = len(expected - month_pairs)
            if requested_symbols == month_symbols:
                missing = expected - month_pairs
                coverage = "COMPLETE" if not missing else "PARTIAL_UPSTREAM_COVERAGE"
                uri, digest = self._persist_missing_keys(
                    month=month,
                    missing=missing,
                    expected_count=len(expected),
                    returned_count=len(month_pairs),
                )
                month_state.update(
                    {
                        "status": coverage,
                        "coverage_status": coverage,
                        "missing_pairs_security_status": len(missing),
                        "missing_pairs_limit_price": len(missing),
                        "missing_key_set_uri": uri,
                        "missing_key_set_sha256": digest,
                        "status_receipt_count": len(receipt_rows),
                        "status_receipt_set_sha256": receipt_hash,
                        "normalization_run_count": len(normalization_refs),
                        "normalization_run_set_sha256": normalization_hash,
                        "monthly_symbol_capture_count": len(requested_symbols),
                    }
                )
                self._verify_missing_keys(
                    relative_uri=uri,
                    expected_hash=digest,
                    expected_count=len(expected),
                    returned_count=len(month_pairs),
                )
                self._write_coverage_receipts()
            elif receipt_rows:
                month_state["status"] = "CAPTURING"
                month_state["coverage_status"] = "CAPTURE_INCOMPLETE"
            else:
                month_state["status"] = "NOT_CAPTURED"
                month_state["coverage_status"] = "NOT_CAPTURED"
            reconstructed_months += 1

        self.state["resume"]["fast_path_reused_month_count"] = reused_months
        self.state["resume"]["fast_path_reconstructed_month_count"] = reconstructed_months
        self.state["resume"]["current_mapper_replay_verified"] = True
        from ashare_state.normalization.registry import MAPPER_CODE_FINGERPRINT

        self.state["resume"]["replayed_mapper_code_hash"] = MAPPER_CODE_FINGERPRINT
        self._verify_coverage_receipts()
        self._save_state()
        return calendars, identity_facts, universe_hashes, verified_pairs, captured_symbols

    def load_retained_context(
        self,
    ) -> tuple[
        dict[str, set[int]],
        dict[str, dict[str, Any]],
        dict[str, str],
        dict[str, set[tuple[str, int]]],
        dict[str, set[str]],
    ]:
        if self.resume_mapper_verified:
            return self._load_verified_resume_context()
        entries, receipt_index = self._read_receipt_log()
        purposes: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            purposes.setdefault(str(entry.get("purpose") or ""), []).append(entry)

        calendars: dict[str, set[int]] = {}
        for market in ("SH", "SZ"):
            purpose = f"calendar_{market}"
            matches = purposes.get(purpose, [])
            calendar_state = self.state.get("calendars", {}).get(market, {})
            receipt_ref = calendar_state.get("receipt", {})
            if len(matches) != 1 or matches[0].get("raw_evidence_sha256") != receipt_ref.get(
                "raw_evidence_sha256"
            ):
                raise BuildFailure("RESUME_CALENDAR", "CALENDAR_RECEIPT_MISMATCH")
            verified, _meta = self._verify_raw_receipt(matches[0], receipt_index)
            payload = read_raw_payload(
                self.raw_root,
                provider="amazingdata",
                dataset=str(matches[0]["provider_dataset"]),
                request_id=str(matches[0]["request_id"]),
                verified=verified,
            )
            values = self._payload_values(payload, label="CALENDAR")
            days = _validate_calendar(values, start=START_DATE, end=END_DATE)
            if len(days) != int(calendar_state.get("session_count", -1)):
                raise BuildFailure("RESUME_CALENDAR", "CALENDAR_SESSION_COUNT_MISMATCH")
            calendars[market] = set(days)

        universe_hashes: dict[str, str] = {}
        universes: dict[str, dict[str, Any]] = {}
        all_symbols: set[str] = set()
        month_states = {item["month"]: item for item in self.state.get("months", [])}
        if set(month_states) != set(_months_in_scope()):
            raise BuildFailure("RESUME_DENOMINATOR", "MONTH_SCOPE_MISMATCH")

        for month in _months_in_scope():
            month_state = month_states[month]
            universe_path = self.universe_root / f"{month}.json"
            expected_hash = str(month_state.get("universe_file_sha256") or "")
            if not universe_path.is_file() or _sha256_file(universe_path) != expected_hash:
                raise BuildFailure("RESUME_DENOMINATOR", "MONTH_UNIVERSE_HASH_MISMATCH")
            try:
                universe = json.loads(universe_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - symbols remain local
                raise BuildFailure("RESUME_DENOMINATOR", type(exc).__name__) from None
            if (
                universe.get("schema") != "issue95_month_universe.v1"
                or universe.get("month") != month
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTH_UNIVERSE_IDENTITY_MISMATCH")
            monthly_symbols = _validate_security_universe(universe.get("monthly_symbols"))
            if monthly_symbols != universe.get("monthly_symbols"):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTH_UNIVERSE_NOT_CANONICAL")

            monthly_receipts = purposes.get(f"monthly_universe_{month}", [])
            if (
                len(monthly_receipts) != 1
                or monthly_receipts[0].get("raw_evidence_sha256")
                != month_state.get("monthly_universe_receipt_sha256")
                or monthly_receipts[0].get("raw_evidence_sha256")
                != universe.get("monthly_universe_receipt_sha256")
                or monthly_receipts[0].get("endpoint") != "BaseData.get_hist_code_list"
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "MONTHLY_UNIVERSE_RECEIPT_MISMATCH")
            verified, _meta = self._verify_raw_receipt(monthly_receipts[0], receipt_index)
            payload = read_raw_payload(
                self.raw_root,
                provider="amazingdata",
                dataset=str(monthly_receipts[0]["provider_dataset"]),
                request_id=str(monthly_receipts[0]["request_id"]),
                verified=verified,
            )
            provider_monthly_symbols = _validate_security_universe(
                self._payload_values(payload, label="MONTHLY_UNIVERSE")
            )
            if provider_monthly_symbols != monthly_symbols:
                raise BuildFailure("RESUME_DENOMINATOR", "MONTHLY_UNIVERSE_REPLAY_MISMATCH")

            session_rows = universe.get("session_universes")
            session_receipts = purposes.get(f"session_universe_{month}", [])
            if (
                not isinstance(session_rows, list)
                or len(session_rows) != int(month_state.get("exchange_session_count", -1))
                or len(session_receipts)
                != int(month_state.get("session_universe_receipt_count", -1))
            ):
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_RECEIPT_COUNT_MISMATCH")
            receipt_hash = _sha256_bytes(
                "\n".join(str(item["raw_evidence_sha256"]) for item in session_receipts).encode(
                    "ascii"
                )
            )
            if receipt_hash != month_state.get(
                "session_receipt_set_sha256"
            ) or receipt_hash != universe.get("session_receipt_set_sha256"):
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_RECEIPT_SET_MISMATCH")
            session_days: list[int] = []
            for saved, receipt in zip(session_rows, session_receipts, strict=True):
                try:
                    day = int(saved["trade_date"])
                    saved_symbols = _validate_security_universe(saved["symbols"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise BuildFailure("RESUME_DENOMINATOR", type(exc).__name__) from None
                if (
                    saved_symbols != saved.get("symbols")
                    or receipt.get("endpoint") != "BaseData.get_hist_code_list"
                    or receipt.get("raw_evidence_sha256") == ""
                ):
                    raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_ENTRY_INVALID")
                verified, meta = self._verify_raw_receipt(receipt, receipt_index)
                params = meta.get("request_params")
                request_start = (
                    params.get("begin_date", params.get("start_date", -1))
                    if isinstance(params, dict)
                    else -1
                )
                request_end = params.get("end_date", -1) if isinstance(params, dict) else -1
                try:
                    valid_date_binding = int(request_start) == day and int(request_end) == day
                except TypeError, ValueError:
                    valid_date_binding = False
                if not valid_date_binding:
                    raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_DATE_MISMATCH")
                payload = read_raw_payload(
                    self.raw_root,
                    provider="amazingdata",
                    dataset=str(receipt["provider_dataset"]),
                    request_id=str(receipt["request_id"]),
                    verified=verified,
                )
                provider_symbols = _validate_security_universe(
                    self._payload_values(payload, label="SESSION_UNIVERSE")
                )
                if provider_symbols != saved_symbols or not set(provider_symbols).issubset(
                    monthly_symbols
                ):
                    raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_REPLAY_MISMATCH")
                session_days.append(day)
            if session_days != sorted(session_days):
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_UNIVERSE_ORDER_MISMATCH")
            month_start, month_finish = _month_bounds(month)
            first = month_start.year * 10000 + month_start.month * 100 + month_start.day
            last = month_finish.year * 10000 + month_finish.month * 100 + month_finish.day
            expected_sessions = sorted(
                day for day in calendars["SH"] | calendars["SZ"] if first <= day <= last
            )
            if session_days != expected_sessions:
                raise BuildFailure("RESUME_DENOMINATOR", "SESSION_CALENDAR_DATE_SET_MISMATCH")
            all_symbols.update(monthly_symbols)
            for session in session_rows:
                all_symbols.update(session["symbols"])
            universe_hashes[month] = expected_hash
            universes[month] = universe

        identity_path = self.run_root / "denominator" / "identity_facts.json"
        identity_state = self.state.get("identity", {})
        if not identity_path.is_file() or _sha256_file(identity_path) != identity_state.get(
            "facts_sha256"
        ):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_FILE_HASH_MISMATCH")
        try:
            identity_document = json.loads(identity_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - identity rows remain local
            raise BuildFailure("RESUME_IDENTITY", type(exc).__name__) from None
        if (
            identity_document.get("schema") != "issue95_identity_facts.v1"
            or len(identity_document.get("facts", []))
            != int(identity_state.get("identity_covered_symbol_count", -1))
            or int(identity_state.get("requested_symbol_count", -1)) != len(all_symbols)
            or identity_state.get("missing_list_date_count") != 0
            or identity_state.get("terminated_without_delist_date_count") != 0
        ):
            raise BuildFailure("RESUME_IDENTITY", "IDENTITY_FACT_SCOPE_MISMATCH")
        identity_facts = self._replay_identity_facts(
            identity_document=identity_document,
            receipt_index=receipt_index,
            all_symbols=all_symbols,
        )

        verified_pairs: dict[str, set[tuple[str, int]]] = {}
        captured_symbols: dict[str, set[str]] = {}
        for month in _months_in_scope():
            month_state = month_states[month]
            universe = universes[month]
            expected, denominator_counts = self._expected_pairs_for_month(
                month=month,
                universe=universe,
                calendars=calendars,
                identity_facts=identity_facts,
            )
            for domain in DOMAINS:
                old_expected = month_state.get(f"expected_pairs_{domain}")
                if old_expected is not None and int(old_expected) != len(expected):
                    raise BuildFailure("RESUME_DENOMINATOR", "EXPECTED_PAIR_COUNT_CHANGED")
                month_state[f"expected_pairs_{domain}"] = len(expected)
            month_state.update(denominator_counts)
            month_pairs: set[tuple[str, int]] = set()
            requested_symbols: set[str] = set()
            receipt_rows = month_state.get("status_receipts") or []
            normalization_refs = month_state.get("normalization_runs") or []
            if len(receipt_rows) != len(normalization_refs):
                raise BuildFailure("RESUME_STATUS", "STATUS_NORMALIZATION_REF_COUNT_MISMATCH")
            previous_status = month_state.get("status")
            previous_returned = month_state.get("returned_pairs")
            previous_unresolved = month_state.get("unresolved_pairs")
            prior_receipt_set_hash = month_state.get("status_receipt_set_sha256")
            if receipt_rows and prior_receipt_set_hash is not None:
                calculated_prior_hash = _sha256_bytes(
                    "\n".join(str(item.get("raw_evidence_sha256")) for item in receipt_rows).encode(
                        "ascii"
                    )
                )
                if calculated_prior_hash != prior_receipt_set_hash:
                    raise BuildFailure("RESUME_STATUS", "STATUS_RECEIPT_SET_HASH_MISMATCH")
            prior_normalization_set_hash = month_state.get("normalization_run_set_sha256")
            if normalization_refs and prior_normalization_set_hash is not None:
                calculated_prior_hash = _sha256_bytes(
                    "\n".join(
                        str(item.get("manifest_sha256")) for item in normalization_refs
                    ).encode("ascii")
                )
                if calculated_prior_hash != prior_normalization_set_hash:
                    raise BuildFailure("RESUME_STATUS", "NORMALIZATION_RUN_SET_HASH_MISMATCH")
            updated_receipts: list[dict[str, Any]] = []
            updated_normalizations: list[dict[str, Any]] = []
            raw_rows = 0
            empty_members = 0
            st_flag_rows = 0
            suspension_flag_rows = 0
            monthly_symbol_set = set(universe["monthly_symbols"])
            month_begin, month_end = _month_bounds(month)
            month_begin_int = month_begin.year * 10000 + month_begin.month * 100 + month_begin.day
            month_end_int = month_end.year * 10000 + month_end.month * 100 + month_end.day

            for receipt_item, old_ref in zip(receipt_rows, normalization_refs, strict=True):
                request_id = str(receipt_item.get("request_id") or "")
                log_entry = receipt_index.get(request_id)
                if (
                    log_entry is None
                    or log_entry.get("purpose")
                    not in {f"status_limit_{month}", f"targeted_status_repair_{month}"}
                    or log_entry.get("raw_evidence_sha256")
                    != receipt_item.get("raw_evidence_sha256")
                    or receipt_item.get("normalization_run_id")
                    != old_ref.get("normalization_run_id")
                    or receipt_item.get("normalization_manifest_sha256")
                    != old_ref.get("manifest_sha256")
                ):
                    raise BuildFailure("RESUME_STATUS", "STATUS_RECEIPT_BINDING_MISMATCH")
                verified, meta = self._verify_raw_receipt(receipt_item, receipt_index)
                if log_entry.get("provider_dataset") != "history_stock_status":
                    raise BuildFailure("RESUME_STATUS", "STATUS_DATASET_MISMATCH")
                params = meta.get("request_params")
                request_codes = params.get("code_list") if isinstance(params, dict) else None
                if not isinstance(request_codes, list) or not request_codes:
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_MEMBERS_MISSING")
                normalized_codes = [str(symbol).strip().upper() for symbol in request_codes]
                if len(set(normalized_codes)) != len(normalized_codes) or not set(
                    normalized_codes
                ).issubset(monthly_symbol_set):
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_MEMBER_MISMATCH")
                try:
                    begin_date = int(params["begin_date"])
                    end_date = int(params["end_date"])
                except KeyError, TypeError, ValueError:
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_WINDOW_INVALID") from None
                is_month_request = begin_date == month_begin_int and end_date == month_end_int
                is_targeted = (
                    bool(receipt_item.get("targeted"))
                    or log_entry.get("purpose") == f"targeted_status_repair_{month}"
                )
                if is_month_request:
                    if is_targeted:
                        raise BuildFailure("RESUME_STATUS", "TARGETED_REQUEST_WINDOW_INVALID")
                    requested_symbols.update(normalized_codes)
                elif not (
                    is_targeted
                    and begin_date == end_date
                    and month_begin_int <= begin_date <= month_end_int
                ):
                    raise BuildFailure("RESUME_STATUS", "STATUS_REQUEST_WINDOW_INVALID")
                payload = read_raw_payload(
                    self.raw_root,
                    provider="amazingdata",
                    dataset="history_stock_status",
                    request_id=request_id,
                    verified=verified,
                )
                try:
                    rows, current_empty_members = _status_rows(payload, params)
                except Exception as exc:  # noqa: BLE001 - raw rows remain local
                    raise BuildFailure("RESUME_STATUS", type(exc).__name__) from None
                pairs: set[tuple[str, int]] = set()
                for row in rows:
                    day = _provider_day(row.get("TRADE_DATE"))
                    if day is None:
                        raise BuildFailure("RESUME_STATUS", "STATUS_ROW_DATE_INVALID")
                    pair = (
                        str(row.get("PROVIDER_SYMBOL") or "").strip().upper(),
                        int(day.strftime("%Y%m%d")),
                    )
                    if pair not in expected or pair in month_pairs or pair in pairs:
                        raise BuildFailure("RESUME_STATUS", "STATUS_PAIR_EXTRA_OR_DUPLICATE")
                    pairs.add(pair)
                    if str(_field(row, "IS_ST_SEC")).strip().lower() in {"1", "true", "yes"}:
                        st_flag_rows += 1
                    if str(_field(row, "IS_SUSP_SEC")).strip().lower() in {
                        "1",
                        "true",
                        "yes",
                    }:
                        suspension_flag_rows += 1
                if len(rows) != int(receipt_item.get("accepted_row_count", -1)):
                    raise BuildFailure("RESUME_STATUS", "STATUS_RAW_ROW_COUNT_MISMATCH")
                self._verify_old_normalization_ref(
                    old_ref,
                    request_id=request_id,
                    provider_dataset="history_stock_status",
                )
                normalization = self._normalize(
                    {"request_id": request_id},
                    provider_dataset="history_stock_status",
                    expected_status_rows=len(rows),
                    expected_status_pairs=pairs,
                )
                if (
                    receipt_item.get("normalization_run_id")
                    != normalization["normalization_run_id"]
                ):
                    receipt_item["prior_normalization_run_id"] = receipt_item[
                        "normalization_run_id"
                    ]
                    receipt_item["prior_normalization_manifest_sha256"] = receipt_item[
                        "normalization_manifest_sha256"
                    ]
                receipt_item["normalization_run_id"] = normalization["normalization_run_id"]
                receipt_item["normalization_manifest_sha256"] = normalization["manifest_sha256"]
                receipt_item["security_status_row_count"] = normalization["outputs"][
                    "security_status"
                ]["row_count"]
                receipt_item["limit_price_row_count"] = normalization["outputs"]["limit_price"][
                    "row_count"
                ]
                receipt_item["empty_member_count"] = current_empty_members
                updated_receipts.append(receipt_item)
                updated_normalizations.append(
                    {
                        "normalization_run_id": normalization["normalization_run_id"],
                        "manifest_sha256": normalization["manifest_sha256"],
                    }
                )
                month_pairs.update(pairs)
                raw_rows += len(rows)
                empty_members += current_empty_members

            captured_symbols[month] = requested_symbols
            verified_pairs[month] = month_pairs
            month_state["status_receipts"] = updated_receipts
            month_state["normalization_runs"] = updated_normalizations
            month_state["normalization_run_count"] = len(updated_normalizations)
            month_state["normalization_run_set_sha256"] = _sha256_bytes(
                "\n".join(str(item["manifest_sha256"]) for item in updated_normalizations).encode(
                    "ascii"
                )
            )
            month_state["status_receipt_count"] = len(updated_receipts)
            month_state["status_receipt_set_sha256"] = _sha256_bytes(
                "\n".join(str(item["raw_evidence_sha256"]) for item in updated_receipts).encode(
                    "ascii"
                )
            )
            month_state["raw_rows"] = raw_rows
            month_state["empty_member_count"] = empty_members
            month_state["provider_st_flag_rows"] = st_flag_rows
            month_state["provider_suspension_flag_rows"] = suspension_flag_rows
            month_state["returned_pairs"] = len(month_pairs)
            month_state["returned_pairs_security_status"] = len(month_pairs)
            month_state["returned_pairs_limit_price"] = len(month_pairs)
            month_state["unresolved_pairs"] = len(expected - month_pairs)
            month_state["unresolved_pairs_security_status"] = len(expected - month_pairs)
            month_state["unresolved_pairs_limit_price"] = len(expected - month_pairs)
            month_state["monthly_symbol_capture_count"] = len(requested_symbols)

            full_capture = requested_symbols == monthly_symbol_set
            if receipt_rows and previous_status not in {"CAPTURING", "None"} and not full_capture:
                raise BuildFailure("RESUME_STATUS", "RETAINED_MONTH_SYMBOL_CAPTURE_INCOMPLETE")
            if full_capture:
                missing = expected - month_pairs
                if previous_status not in {None, "CAPTURING"}:
                    if previous_returned is not None and int(previous_returned) != len(month_pairs):
                        raise BuildFailure("RESUME_STATUS", "RETAINED_RETURNED_COUNT_MISMATCH")
                    if previous_unresolved is not None and int(previous_unresolved) != len(missing):
                        raise BuildFailure("RESUME_STATUS", "RETAINED_MISSING_COUNT_MISMATCH")
                coverage = "COMPLETE" if not missing else "PARTIAL_UPSTREAM_COVERAGE"
                uri, digest = self._persist_missing_keys(
                    month=month,
                    missing=missing,
                    expected_count=len(expected),
                    returned_count=len(month_pairs),
                )
                month_state.update(
                    {
                        "status": coverage,
                        "coverage_status": coverage,
                        "missing_pairs_security_status": len(missing),
                        "missing_pairs_limit_price": len(missing),
                        "missing_key_set_uri": uri,
                        "missing_key_set_sha256": digest,
                    }
                )
                self._verify_missing_keys(
                    relative_uri=uri,
                    expected_hash=digest,
                    expected_count=len(expected),
                    returned_count=len(month_pairs),
                )
            elif receipt_rows:
                month_state["status"] = "CAPTURING"
                month_state["coverage_status"] = "CAPTURE_INCOMPLETE"
            else:
                month_state["coverage_status"] = "NOT_CAPTURED"
            self._save_state()
            self._write_coverage_receipts()
            self._save_state()
            rss_bytes = _current_rss_bytes()
            _emit(
                "RETAINED_MONTH_REPLAYED",
                month=month,
                expected_pairs=len(expected),
                returned_pairs=len(month_pairs),
                coverage=month_state.get("coverage_status"),
                provider_calls=self.call_count,
                provider_calls_during_replay=0,
                rss_mib=round(rss_bytes / 1024**2, 1),
            )
            if rss_bytes >= MAX_RSS_BYTES:
                raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_DURING_REPLAY")

        self.state["resume"]["reconciled_month_count"] = sum(
            1
            for item in self.state["months"]
            if item.get("coverage_status") in {"COMPLETE", "PARTIAL_UPSTREAM_COVERAGE"}
        )
        self.state["resume"]["current_mapper_replay_verified"] = True
        from ashare_state.normalization.registry import MAPPER_CODE_FINGERPRINT

        self.state["resume"]["replayed_mapper_code_hash"] = MAPPER_CODE_FINGERPRINT
        self._save_state()
        return calendars, identity_facts, universe_hashes, verified_pairs, captured_symbols

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
        already_returned_pairs: set[tuple[str, int]] | None = None,
        already_requested_symbols: set[str] | None = None,
        repair_missing_pairs: bool = False,
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
                "status": "CAPTURING",
            }
        )
        for field in (
            "targeted_repair_requests",
            "targeted_rows_returned",
            "extra_pairs",
            "duplicate_pairs",
            "structural_errors",
            "provider_suspension_flag_rows",
            "provider_st_flag_rows",
        ):
            month_state.setdefault(field, 0)
        self._save_state()

        seen_pairs: set[tuple[str, int]] = set(already_returned_pairs or ())
        requested_before = set(already_requested_symbols or ())
        if not requested_before.issubset(monthly_symbol_set):
            raise BuildFailure("STATUS_CAPTURE", "RESUME_REQUEST_MEMBER_OUTSIDE_UNIVERSE")
        captured_symbols = set(requested_before)
        symbols_to_request = [
            symbol for symbol in monthly_symbols if symbol not in requested_before
        ]
        batch_size = min(self.status_batch_size, max(len(monthly_symbols), 1))
        offset = 0
        used_batch_sizes: Counter[int] = Counter(
            {
                int(size): int(count)
                for size, count in (month_state.get("accepted_batch_sizes") or {}).items()
            }
        )
        receipt_rows: list[dict[str, Any]] = list(month_state.get("status_receipts") or [])
        normalization_runs: list[dict[str, Any]] = list(month_state.get("normalization_runs") or [])
        empty_members = sum(int(item.get("empty_member_count") or 0) for item in receipt_rows)
        provider_rows = sum(int(item.get("accepted_row_count") or 0) for item in receipt_rows)
        while offset < len(symbols_to_request):
            requested_list = symbols_to_request[offset : offset + batch_size]
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
            captured_symbols.update(requested_list)
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
            if planned and repair_missing_pairs:
                time.sleep(TARGETED_RETRY_DELAY_SECONDS)
            request_budget = (
                min(planned, MAX_TARGETED_REQUESTS_PER_MONTH) if repair_missing_pairs else 0
            )
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

        captured_symbol_count = len(captured_symbols)
        if captured_symbol_count != len(monthly_symbol_set):
            raise BuildFailure("STATUS_CAPTURE", "MONTH_SYMBOL_CAPTURE_INCOMPLETE")
        unresolved = len(missing)
        coverage = "COMPLETE" if unresolved == 0 else "PARTIAL_UPSTREAM_COVERAGE"
        missing_uri, missing_hash = self._persist_missing_keys(
            month=month,
            missing=missing,
            expected_count=len(expected),
            returned_count=len(seen_pairs),
        )
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
                "monthly_symbol_capture_count": captured_symbol_count,
                "missing_pairs_security_status": unresolved,
                "missing_pairs_limit_price": unresolved,
                "missing_key_set_uri": missing_uri,
                "missing_key_set_sha256": missing_hash,
                "coverage_status": coverage,
                "status": coverage,
            }
        )
        self._verify_missing_keys(
            relative_uri=missing_uri,
            expected_hash=missing_hash,
            expected_count=len(expected),
            returned_count=len(seen_pairs),
        )
        self._write_coverage_receipts()
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
            coverage=coverage,
            targeted_repair_requests=month_state.get("targeted_repair_requests", 0),
            batch_sizes=dict(used_batch_sizes),
            provider_calls=self.call_count,
            rss_mb=round(_current_rss_bytes() / 1024**2, 1),
        )
        return month_state

    def prepare_canonical_attempt(self) -> datetime:
        saved_as_of = self.state.get("canonical_attempt_as_of")
        if saved_as_of:
            try:
                as_of = datetime.fromisoformat(str(saved_as_of))
            except ValueError:
                raise BuildFailure("CANONICAL", "SAVED_CANONICAL_AS_OF_INVALID") from None
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise BuildFailure("CANONICAL", "SAVED_CANONICAL_AS_OF_NOT_TIMEZONED")
        else:
            as_of = datetime.now(UTC) + timedelta(seconds=2)
            self.state["canonical_attempt_as_of"] = as_of.isoformat()

        self.state["canonical_attempt_number"] = (
            int(self.state.get("canonical_attempt_number", 0)) + 1
        )
        self.state["canonical_attempt_started_at_utc"] = datetime.now(UTC).isoformat()
        self.state["canonical_attempt_provider_calls"] = 0
        self.state["status"] = "RUNNING"
        self.state.pop("completed_at_utc", None)
        self.state.pop("blocker", None)
        self._save_state()
        return as_of

    def _canonical_rss_checkpoint(self, checkpoint: str) -> None:
        rss_bytes = _current_rss_bytes()
        checkpoints = self.state.setdefault("canonical_rss_checkpoints", [])
        checkpoints.append(
            {
                "attempt": int(self.state.get("canonical_attempt_number", 0)),
                "checkpoint": checkpoint,
                "rss_mib": round(rss_bytes / 1024**2, 1),
                "observed_at_utc": datetime.now(UTC).isoformat(),
            }
        )
        self._save_state()
        _emit(
            "CANONICAL_RSS_CHECKPOINT",
            attempt=int(self.state.get("canonical_attempt_number", 0)),
            checkpoint=checkpoint,
            rss_mib=round(rss_bytes / 1024**2, 1),
            hard_limit_mib=round(MAX_RSS_BYTES / 1024**2),
            provider_calls_during_canonical=0,
        )
        if rss_bytes >= MAX_RSS_BYTES:
            raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_DURING_CANONICAL")

    def build_canonical(
        self, *, expected_per_domain: int, as_of: datetime | None = None
    ) -> dict[str, Any]:
        if as_of is None:
            as_of = self.prepare_canonical_attempt()
        provider_calls_before = self.call_count
        self._canonical_rss_checkpoint("BEFORE_CANONICAL")
        try:
            result = CanonicalRunner(
                self.conn,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            ).run(
                as_of=as_of,
                domains=list(DOMAINS),
                progress_callback=self._canonical_rss_checkpoint,
            )
        except BuildFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - canonical diagnostics stay local
            raise BuildFailure("CANONICAL", type(exc).__name__) from None
        self._canonical_rss_checkpoint("CANONICAL_COMMIT_COMPLETE")
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
        self._canonical_rss_checkpoint("AFTER_CANONICAL_VERIFY")
        del verified
        del result
        replay = CanonicalRunner(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        ).run(
            as_of=as_of,
            domains=list(DOMAINS),
            progress_callback=lambda stage: self._canonical_rss_checkpoint(f"EXACT_REPLAY_{stage}"),
        )
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
        self._canonical_rss_checkpoint("AFTER_EXACT_REPLAY")
        if self.call_count != provider_calls_before:
            raise BuildFailure("CANONICAL", "PROVIDER_CALL_COUNT_CHANGED")
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
            "## Coverage reconciliation",
            "",
            "Missing provider pairs remain unknown; they are not converted "
            "to negative/default facts.",
        ]
        coverage = self.state.get("coverage_summary") or {}
        coverage_receipt = self.state.get("coverage_receipts") or {}
        if coverage:
            lines.extend(
                [
                    f"- Complete months: {coverage.get('complete_months', '—')}",
                    "- Partial upstream-coverage months: "
                    f"{coverage.get('partial_upstream_months', '—')}",
                    "- Expected pairs per domain: "
                    f"{coverage.get('expected_pairs_per_domain', '—')}",
                    "- Returned pairs per domain: "
                    f"{coverage.get('returned_pairs_per_domain', '—')}",
                    f"- Missing pairs per domain: {coverage.get('missing_pairs_per_domain', '—')}",
                    f"- Coverage receipt: `{coverage_receipt.get('uri', '—')}`",
                    f"  Records: {coverage_receipt.get('record_count', '—')}; "
                    f"SHA-256: {coverage_receipt.get('sha256', '—')}",
                    "",
                ]
            )
        lines.extend(
            [
                (
                    "| Month | Coverage | Expected pairs/domain | Returned pairs/domain | "
                    "Unresolved pairs/domain | Pre-listing N/A | Post-delisting N/A | "
                    "Missing-set SHA-256 | Receipt-set SHA-256 |"
                ),
                "|---|---|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for month in self.state.get("months", []):
            lines.append(
                (
                    "| {month} | {coverage} | {expected} | {returned} | "
                    "{unresolved} | {pre} | {post} | `{missing_hash}` | `{receipt}` |"
                ).format(
                    month=month.get("month", ""),
                    coverage=month.get("coverage_status", "—"),
                    expected=month.get("expected_pairs_security_status", "—"),
                    returned=month.get("returned_pairs", 0),
                    unresolved=month.get("unresolved_pairs", "—"),
                    pre=month.get("prelisting_nonapplicable_pairs", 0),
                    post=month.get("postdelisting_nonapplicable_pairs", 0),
                    missing_hash=month.get("missing_key_set_sha256", "—"),
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


def _load_resume_state(run_root: Path) -> tuple[dict[str, Any], str, str]:
    run_root = run_root.expanduser().resolve()
    manifest_path = run_root / "execution_manifest.json"
    report_path = run_root / "report.json"
    receipt_path = run_root / "receipts.jsonl"
    if not all(
        path.is_file()
        for path in (manifest_path, report_path, receipt_path, run_root / "ledger.duckdb")
    ):
        raise BuildFailure("RESUME", "RETAINED_RUN_FILE_MISSING")
    try:
        state = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - retained details remain local
        raise BuildFailure("RESUME", type(exc).__name__) from None
    if (
        state.get("schema") != "issue95_status_limit_build.v1"
        or state.get("scope")
        != {
            "exchanges": ["SH", "SZ"],
            "start_date": START_DATE.isoformat(),
            "end_date": END_DATE.isoformat(),
            "months": _months_in_scope(),
            "canonical_domains": list(DOMAINS),
        }
        or state.get("status") not in {"INTERRUPTED", "STOP_BLOCKED", "RUNNING"}
        or state.get("canonical") is not None
    ):
        raise BuildFailure("RESUME", "RETAINED_RUN_STATE_NOT_RESUMABLE")
    if not all(
        path.is_dir()
        for path in (
            run_root / "raw",
            run_root / "normalized",
            run_root / "denominator" / "universe_by_month",
        )
    ):
        raise BuildFailure("RESUME", "RETAINED_STORAGE_DIRECTORY_MISSING")
    report_hash = _sha256_file(report_path)
    if state.get("report_sha256") != report_hash:
        raise BuildFailure("RESUME", "RETAINED_REPORT_HASH_MISMATCH")
    receipt_hash = _sha256_file(receipt_path)
    expected_receipt_hash = state.get("receipt_log_sha256")
    if state.get("status") != "RUNNING" and expected_receipt_hash != receipt_hash:
        raise BuildFailure("RESUME", "RETAINED_RECEIPT_LOG_HASH_MISMATCH")
    if report.get("run_id") != state.get("run_id"):
        raise BuildFailure("RESUME", "RETAINED_REPORT_RUN_ID_MISMATCH")
    receipt_lines = [line for line in receipt_path.read_text(encoding="utf-8").splitlines() if line]
    if len(receipt_lines) != int((state.get("receipts") or {}).get("provider_call_count", -1)):
        raise BuildFailure("RESUME", "PROVIDER_CALL_COUNT_MISMATCH")
    manifest_hash = _sha256_file(manifest_path)
    return state, manifest_hash, report_hash


def _run_canonical_only(run_root: Path) -> int:
    run_root = run_root.expanduser().resolve()
    manifest_path = run_root / "execution_manifest.json"
    try:
        state = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - local evidence details stay private
        _emit(
            "STOP_BLOCKED",
            failure_stage="CANONICAL_ONLY_PREFLIGHT",
            error_class=type(exc).__name__,
            run_root=run_root.name,
        )
        return 2

    expected_scope = {
        "exchanges": ["SH", "SZ"],
        "start_date": START_DATE.isoformat(),
        "end_date": END_DATE.isoformat(),
        "months": _months_in_scope(),
        "canonical_domains": list(DOMAINS),
    }
    required_files = (
        manifest_path,
        run_root / "receipts.jsonl",
        run_root / "report.json",
        run_root / "ledger.duckdb",
        run_root / "coverage_receipts.json",
    )
    required_directories = (
        run_root / "raw",
        run_root / "normalized",
        run_root / "denominator" / "universe_by_month",
    )
    if (
        state.get("schema") != "issue95_status_limit_build.v1"
        or state.get("scope") != expected_scope
        or state.get("status") not in {"RUNNING", "INTERRUPTED", "STOP_BLOCKED"}
        or state.get("canonical") is not None
        or not isinstance(state.get("resume"), dict)
        or not all(path.is_file() for path in required_files)
        or not all(path.is_dir() for path in required_directories)
        or state.get("report_sha256") != _sha256_file(run_root / "report.json")
    ):
        _emit(
            "STOP_BLOCKED",
            failure_stage="CANONICAL_ONLY_PREFLIGHT",
            error_class="RETAINED_RUN_NOT_ELIGIBLE",
            run_root=run_root.name,
        )
        return 2

    manager = DuckDBConnectionManager(run_root / "ledger.duckdb")
    build: Issue95Build | None = None
    try:
        with manager.owner("read_write") as conn:
            apply_migrations(conn, REPO_ROOT / "migrations")
            build = Issue95Build(
                run_root=run_root,
                max_status_batch_size=STATUS_BATCH_FALLBACKS[0],
                conn=conn,
                provider=cast(AmazingDataProvider, None),
                initial_state=state,
            )
            build.initialize_storage(resume=True)
            build._read_receipt_log()

            month_states = build.state.get("months", [])
            if [item.get("month") for item in month_states] != _months_in_scope():
                raise BuildFailure("CANONICAL_ONLY_PREFLIGHT", "MONTH_SCOPE_MISMATCH")
            expected_per_domain = 0
            expected_by_coverage: Counter[str] = Counter()
            for item in month_states:
                coverage = item.get("coverage_status")
                if coverage not in {"COMPLETE", "PARTIAL_UPSTREAM_COVERAGE"}:
                    raise BuildFailure("CANONICAL_ONLY_PREFLIGHT", "MONTH_COVERAGE_INCOMPLETE")
                expected = int(item.get("expected_pairs_security_status", -1))
                returned_status = int(item.get("returned_pairs_security_status", -1))
                returned_limit = int(item.get("returned_pairs_limit_price", -1))
                missing_status = int(item.get("missing_pairs_security_status", -1))
                missing_limit = int(item.get("missing_pairs_limit_price", -1))
                if (
                    expected < 0
                    or returned_status < 0
                    or returned_status != returned_limit
                    or missing_status != expected - returned_status
                    or missing_limit != expected - returned_limit
                    or int(item.get("unresolved_pairs", -1)) != expected - returned_status
                    or any(
                        int(item.get(key, 0)) != 0
                        for key in ("extra_pairs", "duplicate_pairs", "structural_errors")
                    )
                    or not item.get("missing_key_set_uri")
                    or not item.get("missing_key_set_sha256")
                ):
                    raise BuildFailure("CANONICAL_ONLY_PREFLIGHT", "MONTH_COVERAGE_INVALID")
                build._verify_missing_keys(
                    relative_uri=str(item["missing_key_set_uri"]),
                    expected_hash=str(item["missing_key_set_sha256"]),
                    expected_count=expected,
                    returned_count=returned_status,
                )
                expected_per_domain += returned_status
                expected_by_coverage[str(coverage)] += 1

            if (
                len(month_states) != 78
                or expected_by_coverage
                != Counter({"COMPLETE": 16, "PARTIAL_UPSTREAM_COVERAGE": 62})
                or expected_per_domain != 7_459_685
                or sum(int(item["expected_pairs_security_status"]) for item in month_states)
                != 7_461_248
                or sum(int(item["missing_pairs_security_status"]) for item in month_states) != 1_563
                or int(build.state.get("identity", {}).get("missing_list_date_count", 0)) != 0
                or int(
                    build.state.get("identity", {}).get("terminated_without_delist_date_count", 0)
                )
                != 0
            ):
                raise BuildFailure("CANONICAL_ONLY_PREFLIGHT", "RECONCILED_CAPTURE_GATE_FAILED")
            build._verify_coverage_receipts()

            from ashare_state.normalization.registry import MAPPER_CODE_FINGERPRINT

            replay_state = build.state["resume"]
            replay_is_current = (
                replay_state.get("current_mapper_replay_verified") is True
                and replay_state.get("replayed_mapper_code_hash") == MAPPER_CODE_FINGERPRINT
            )
            mapper_replayed = False
            if not replay_is_current:
                prior_call_count = build.call_count
                build.resume_mapper_verified = False
                replay_state["current_mapper_replay_verified"] = False
                replay_state["current_mapper_replay_started_at_utc"] = datetime.now(UTC).isoformat()
                build._save_state()
                _emit(
                    "CURRENT_MAPPER_REPLAY_START",
                    provider_calls_during_replay=0,
                    retained_status_normalization_runs=sum(
                        int(item.get("normalization_run_count", 0)) for item in month_states
                    ),
                    retained_identity_normalization_runs=int(
                        build.state.get("identity", {}).get("normalization_run_count", 0)
                    ),
                    rss_mib=round(_current_rss_bytes() / 1024**2, 1),
                    run_root=run_root.name,
                )
                build.load_retained_context()
                mapper_replayed = True
                if build.call_count != prior_call_count:
                    raise BuildFailure("CANONICAL_ONLY_REPLAY", "PROVIDER_CALL_COUNT_CHANGED")
                replay_state = build.state["resume"]
                if (
                    replay_state.get("current_mapper_replay_verified") is not True
                    or replay_state.get("replayed_mapper_code_hash") != MAPPER_CODE_FINGERPRINT
                ):
                    raise BuildFailure("CANONICAL_ONLY_REPLAY", "CURRENT_MAPPER_REPLAY_UNVERIFIED")

                replayed_expected = sum(
                    int(item["expected_pairs_security_status"]) for item in month_states
                )
                replayed_returned = sum(
                    int(item["returned_pairs_security_status"]) for item in month_states
                )
                replayed_missing = sum(
                    int(item["missing_pairs_security_status"]) for item in month_states
                )
                replayed_coverage = Counter(
                    str(item.get("coverage_status")) for item in month_states
                )
                if (
                    replayed_expected != 7_461_248
                    or replayed_returned != 7_459_685
                    or replayed_missing != 1_563
                    or replayed_coverage
                    != Counter({"COMPLETE": 16, "PARTIAL_UPSTREAM_COVERAGE": 62})
                ):
                    raise BuildFailure("CANONICAL_ONLY_REPLAY", "COVERAGE_CHANGED_ON_REPLAY")
                for item in month_states:
                    build._verify_missing_keys(
                        relative_uri=str(item["missing_key_set_uri"]),
                        expected_hash=str(item["missing_key_set_sha256"]),
                        expected_count=int(item["expected_pairs_security_status"]),
                        returned_count=int(item["returned_pairs_security_status"]),
                    )
                build._verify_coverage_receipts()
                expected_per_domain = replayed_returned
                expected_by_coverage = replayed_coverage
                _emit(
                    "CURRENT_MAPPER_REPLAY_COMPLETE",
                    provider_calls_during_replay=0,
                    current_mapper_replay_verified=True,
                    normalization_runs_replayed=(
                        sum(int(item.get("normalization_run_count", 0)) for item in month_states)
                        + int(build.state.get("identity", {}).get("normalization_run_count", 0))
                    ),
                    rss_mib=round(_current_rss_bytes() / 1024**2, 1),
                    run_root=run_root.name,
                )

            if mapper_replayed:
                _emit(
                    "CANONICAL_DEFERRED_AFTER_NORMALIZATION_REPLAY",
                    provider_calls_during_replay=0,
                    canonical_started=False,
                    reason="FRESH_PROCESS_REQUIRED_AFTER_OFFLINE_MAPPER_REPLAY",
                    run_root=run_root.name,
                )
                return 0

            canonical_count = int(
                conn.execute("SELECT COUNT(*) FROM meta_canonicalization_run").fetchone()[0]
            )
            if canonical_count and not build.state.get("canonical_attempt_as_of"):
                raise BuildFailure("CANONICAL_ONLY_PREFLIGHT", "UNBOUND_CANONICAL_HISTORY_EXISTS")
            as_of = build.prepare_canonical_attempt()
            _emit(
                "CANONICAL_ONLY_START",
                run_id=build.run_id,
                months=len(month_states),
                returned_pairs_per_domain=expected_per_domain,
                provider_calls_during_canonical=0,
                rss_mib=round(_current_rss_bytes() / 1024**2, 1),
                run_root=run_root.name,
            )
            canonical = build.build_canonical(
                expected_per_domain=expected_per_domain,
                as_of=as_of,
            )
            build.state["coverage_summary"] = {
                "complete_months": expected_by_coverage["COMPLETE"],
                "partial_upstream_months": expected_by_coverage["PARTIAL_UPSTREAM_COVERAGE"],
                "returned_pairs_per_domain": expected_per_domain,
                "missing_pairs_per_domain": sum(
                    int(item["missing_pairs_security_status"]) for item in month_states
                ),
                "expected_pairs_per_domain": sum(
                    int(item["expected_pairs_security_status"]) for item in month_states
                ),
            }
            build.state["canonical"] = canonical
            build.write_report(status="PASS")
            _emit(
                "BUILD_PASS",
                run_id=build.run_id,
                provider_calls_during_canonical=0,
                months=78,
                returned_pairs_per_domain=expected_per_domain,
                canonical_run_id=canonical["canonical_run_id"],
                selected_rows=canonical["selected_count"],
                complete_months=expected_by_coverage["COMPLETE"],
                partial_months=expected_by_coverage["PARTIAL_UPSTREAM_COVERAGE"],
                missing_pairs_per_domain=build.state["coverage_summary"][
                    "missing_pairs_per_domain"
                ],
                report_root=run_root.name,
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
            run_root=run_root.name,
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - local diagnostics stay sanitized
        if build is not None:
            with suppress(Exception):
                build.write_report(
                    status="STOP_BLOCKED",
                    blocker={
                        "gate": "CANONICAL_ONLY_UNEXPECTED",
                        "error_class": type(exc).__name__,
                    },
                )
        _emit(
            "STOP_BLOCKED",
            failure_stage="CANONICAL_ONLY_UNEXPECTED",
            error_class=type(exc).__name__,
            run_root=run_root.name,
        )
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-status-batch-size",
        type=int,
        choices=STATUS_BATCH_FALLBACKS,
        default=STATUS_BATCH_FALLBACKS[0],
        help="Largest candidate tested through the live endpoint before the build selects a size.",
    )
    run_mode = parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--resume-run",
        type=Path,
        help=(
            "Resume an interrupted, uncanonicalized Issue #95 run using its retained "
            "local evidence."
        ),
    )
    run_mode.add_argument(
        "--canonical-only",
        type=Path,
        help=(
            "Build and verify Canonical from a reconciled retained Issue #95 run, "
            "without logging in or calling the Provider."
        ),
    )
    args = parser.parse_args()
    if args.canonical_only is not None:
        return _run_canonical_only(args.canonical_only)
    if args.resume_run is None:
        run_root = _run_root()
        initial_state = None
        source_manifest_sha256 = ""
        source_report_sha256 = ""
        run_label = run_root.relative_to(REPO_ROOT).as_posix()
    else:
        run_root = args.resume_run.expanduser().resolve()
        run_label = run_root.name
        try:
            initial_state, source_manifest_sha256, source_report_sha256 = _load_resume_state(
                run_root
            )
        except BuildFailure as exc:
            _emit(
                "STOP_BLOCKED",
                failure_stage=exc.stage,
                error_class=exc.error_class,
                run_root=run_label,
            )
            return 2
        except Exception as exc:  # noqa: BLE001 - retained local details stay private
            _emit(
                "STOP_BLOCKED",
                failure_stage="RESUME",
                error_class=type(exc).__name__,
                run_root=run_label,
            )
            return 2
    _emit(
        "RUN_RESUME_SELECTED" if initial_state is not None else "RUN_CREATED",
        run_id=(initial_state or {}).get("run_id", run_root.name.rsplit("_", 1)[-1]),
        output_root=run_label,
    )
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
                initial_state=initial_state,
            )
            build.initialize_storage(resume=initial_state is not None)
            _emit("ACCOUNT_GATE_PASS", status="FROZEN_PRODUCTION_IDENTITY_MATCH")
            retained_pairs: dict[str, set[tuple[str, int]]] = {}
            retained_symbols: dict[str, set[str]] = {}
            if initial_state is None:
                calendars = build.acquire_calendars()
                all_symbols, universe_hashes = build.acquire_month_universes(calendars)
                identity_facts = build.acquire_stock_basics(all_symbols)
                build.probe_status_batch_size(
                    month="2025-12",
                    universe_hash=universe_hashes["2025-12"],
                    calendars=calendars,
                    identity_facts=identity_facts,
                )
            else:
                canonical_count = conn.execute(
                    "SELECT COUNT(*) FROM meta_canonicalization_run"
                ).fetchone()[0]
                if int(canonical_count) != 0:
                    raise BuildFailure("RESUME", "CANONICAL_HISTORY_ALREADY_EXISTS")
                build.begin_resume(
                    source_manifest_sha256=source_manifest_sha256,
                    source_report_sha256=source_report_sha256,
                )
                (
                    calendars,
                    identity_facts,
                    universe_hashes,
                    retained_pairs,
                    retained_symbols,
                ) = build.load_retained_context()

            months = _months_in_scope()
            for month_index, month in enumerate(months, start=1):
                month_state = next(item for item in build.state["months"] if item["month"] == month)
                if month_state.get("coverage_status") in {
                    "COMPLETE",
                    "PARTIAL_UPSTREAM_COVERAGE",
                }:
                    continue
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
                    already_returned_pairs=retained_pairs.get(month),
                    already_requested_symbols=retained_symbols.get(month),
                )
                if _current_rss_bytes() > MAX_RSS_BYTES:
                    raise BuildFailure("MEMORY_GUARD", "RSS_LIMIT_REACHED_AFTER_MONTH")
                if month_state.get("coverage_status") == "PARTIAL_UPSTREAM_COVERAGE":
                    _emit(
                        "MONTH_UPSTREAM_PARTIAL_COVERAGE",
                        month=month,
                        missing_pairs=month_state["unresolved_pairs"],
                        missing_key_set_sha256=month_state["missing_key_set_sha256"],
                    )

            identity_state = build.state.get("identity", {})
            blockers: list[str] = []
            if len(build.state["months"]) != 78:
                blockers.append("MONTH_COUNT_NOT_78")
            accepted_coverage = {"COMPLETE", "PARTIAL_UPSTREAM_COVERAGE"}
            if any(
                item.get("coverage_status") not in accepted_coverage
                for item in build.state["months"]
            ):
                blockers.append("MONTH_COVERAGE_STATE_INCOMPLETE")
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
            for item in build.state["months"]:
                expected_count = int(item.get("expected_pairs_security_status") or 0)
                returned_status = int(item.get("returned_pairs_security_status") or 0)
                returned_limit = int(item.get("returned_pairs_limit_price") or 0)
                if (
                    item.get("coverage_status") not in accepted_coverage
                    or returned_status != returned_limit
                    or item.get("unresolved_pairs") != expected_count - returned_status
                    or item.get("missing_pairs_security_status") != expected_count - returned_status
                    or item.get("missing_pairs_limit_price") != expected_count - returned_limit
                    or not item.get("missing_key_set_uri")
                    or not item.get("missing_key_set_sha256")
                ):
                    blockers.append("MONTH_COVERAGE_RECEIPT_INVALID")
                    continue
                build._verify_missing_keys(
                    relative_uri=str(item["missing_key_set_uri"]),
                    expected_hash=str(item["missing_key_set_sha256"]),
                    expected_count=expected_count,
                    returned_count=returned_status,
                )
            build._verify_coverage_receipts()
            build.state["coverage_summary"] = {
                "complete_months": sum(
                    item["coverage_status"] == "COMPLETE" for item in build.state["months"]
                ),
                "partial_upstream_months": sum(
                    item["coverage_status"] == "PARTIAL_UPSTREAM_COVERAGE"
                    for item in build.state["months"]
                ),
                "expected_pairs_per_domain": sum(
                    int(item["expected_pairs_security_status"]) for item in build.state["months"]
                ),
                "returned_pairs_per_domain": sum(
                    int(item["returned_pairs_security_status"]) for item in build.state["months"]
                ),
                "missing_pairs_per_domain": sum(
                    int(item["missing_pairs_security_status"]) for item in build.state["months"]
                ),
            }
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
                    run_root=run_label,
                )
                return 2

            returned_per_domain = sum(
                int(item["returned_pairs_security_status"]) for item in build.state["months"]
            )
            canonical = build.build_canonical(expected_per_domain=returned_per_domain)
            build.state["canonical"] = canonical
            build.write_report(status="PASS")
            _emit(
                "BUILD_PASS",
                run_id=build.run_id,
                provider_calls=build.call_count,
                months=78,
                returned_pairs_per_domain=returned_per_domain,
                canonical_run_id=canonical["canonical_run_id"],
                selected_rows=canonical["selected_count"],
                complete_months=build.state["coverage_summary"]["complete_months"],
                partial_months=build.state["coverage_summary"]["partial_upstream_months"],
                missing_pairs_per_domain=build.state["coverage_summary"][
                    "missing_pairs_per_domain"
                ],
                report_root=run_label,
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
            run_root=run_label,
        )
        return 2
    except KeyboardInterrupt:
        if build is not None:
            with suppress(Exception):
                build.write_report(status="INTERRUPTED", blocker={"gate": "INTERRUPTED"})
        _emit("RUN_INTERRUPTED", run_root=run_label)
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
            run_root=run_label,
        )
        return 2
    finally:
        if session is not None:
            session.logout()


if __name__ == "__main__":
    with _quarantine_untrusted_sdk_output():
        raise SystemExit(main())
