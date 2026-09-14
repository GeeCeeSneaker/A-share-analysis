"""Probe a same-source positive trading-activity semantic for CR-7.

This diagnostic is deliberately narrower than the month-completeness runner.
It reads the one retained 2024-01 status-schema blocker, verifies that the
member is applicable on the retained exact-session calendar, and makes one
AmazingData ``MarketData.query_snapshot`` call for that member and month.

Only a documented positive activity field can resolve a session here.  A
non-empty snapshot, a price, a quote, an empty response, or a missing response
is never treated as proof of trading.  The probe does not change
``month_completeness.py`` and does not create a materialization or a
production/formal run.

The provider response and credentials stay in local ignored paths.  The
report contains hashes, field names, shapes, counts, and per-session boolean
observations only; it never contains the provider symbol or raw values.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import pyarrow.parquet as pq

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.amazingdata.sdk_loader import probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStderr,
    CapturedStdout,
    sdk_stderr_into,
    sdk_stdout_into,
)
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage import apply_migrations
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter

_SCHEMA = "cr7.positive_semantic_fallback.v1"
_TARGET_MEMBER_SHA256 = "2f3fcbddeafab98dcacf9a6b3b006b7192f704c9741cdf3eac96240083df1f54"
_BATCH_REQUEST_ID = "2a0ff664-3c1e-4e4d-b40e-86b71758c48c"
_CALENDAR_REQUEST_ID = "e3ad7f2e-4816-4deb-9fa6-021d12142de1"
_STATUS_DATASET = "history_stock_status"
_STATUS_ENDPOINT = "InfoData.get_history_stock_status"
_STATUS_SURFACE = "security_status_history"
_HIST_CODE_DATASET = "hist_code_list"
_CALENDAR_DATASET = "trade_calendar"
_SNAPSHOT_DATASET = "historical_snapshot"
_SNAPSHOT_ENDPOINT = "MarketData.query_snapshot"
_SNAPSHOT_SURFACE = "trade_activity_snapshot_diagnostic"
_SNAPSHOT_OPERATION_ID = f"{_SNAPSHOT_ENDPOINT}#{_SNAPSHOT_SURFACE}"
_START = 20240101
_END = 20240131
_MONTH = "2024-01"
_BEGIN_TIME = 93000000
_END_TIME = 150000000
_EXPECTED_SESSION_COUNT = 22
_BLOCKED_EXIT_CODE = 2
_ENV_KEYS = (
    "TGW_USERNAME",
    "TGW_PASSWORD",
    "TGW_SERVER_VIP",
    "TGW_SERVER_PORT",
)

# The names are the public SDK contract surface.  The first item is the raw
# TGW field; the remaining items are the names exposed after AmazingData's
# stock snapshot conversion.  We do not use prices, quotes, row presence, or
# zero values as activity evidence.
_ACTIVITY_FIELDS: dict[str, tuple[str, ...]] = {
    "num_trades": ("num_trades",),
    "total_volume_trade": ("total_volume_trade", "volume"),
    "total_value_trade": ("total_value_trade", "amount"),
}


class DiagnosticBlockedError(RuntimeError):
    """A fixed, sanitized blocker code for the bounded diagnostic."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _load_env(path: Path) -> dict[str, str]:
    """Read only the four local TGW variables without logging values."""
    values = {key: value for key, value in os.environ.items() if key in _ENV_KEYS}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key not in _ENV_KEYS or key in values:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def _credentials(env: Mapping[str, str]) -> tuple[str, str, str, int] | None:
    if not all(env.get(key) for key in _ENV_KEYS):
        return None
    try:
        port = int(env["TGW_SERVER_PORT"])
    except (TypeError, ValueError):
        return None
    return env["TGW_USERNAME"], env["TGW_PASSWORD"], env["TGW_SERVER_VIP"], port


def _git_head(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _dataset_root(raw_root: Path, dataset: str) -> Path:
    return raw_root / "provider=amazingdata" / f"dataset={dataset}"


def _table_path(raw_root: Path, dataset_root: Path, file_name: str) -> Path:
    candidate = Path(file_name)
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0] == "provider=amazingdata":
        return raw_root / candidate
    return dataset_root / candidate


def _read_table(
    raw_root: Path, dataset: str, meta: Mapping[str, Any]
) -> tuple[Any, Path, Mapping[str, Any]]:
    """Read and byte-verify a retained one-table raw exchange."""
    tables = meta.get("tables")
    if not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], Mapping):
        raise DiagnosticBlockedError("RETAINED_TABLE_SET_INVALID")
    table = tables[0]
    dataset_root = _dataset_root(raw_root, dataset)
    path = _table_path(raw_root, dataset_root, str(table.get("file") or ""))
    if not path.is_file():
        raise DiagnosticBlockedError("RETAINED_TABLE_PAYLOAD_MISSING")
    try:
        payload_hash = _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise DiagnosticBlockedError("RETAINED_TABLE_PAYLOAD_UNREADABLE") from exc
    if payload_hash != str(table.get("content_hash") or ""):
        raise DiagnosticBlockedError("RETAINED_TABLE_PAYLOAD_HASH_MISMATCH")
    try:
        return pq.read_table(path), path, table
    except (OSError, ValueError) as exc:
        raise DiagnosticBlockedError("RETAINED_TABLE_PARQUET_UNREADABLE") from exc


def _retained_target(raw_root: Path) -> tuple[str, dict[str, Any]]:
    """Resolve the one retained zero-column status member without exposing it."""
    dataset_root = _dataset_root(raw_root, _STATUS_DATASET)
    meta_path = dataset_root / f"{_BATCH_REQUEST_ID}.meta.json"
    batch_dir = dataset_root / _BATCH_REQUEST_ID
    if not meta_path.is_file() or not batch_dir.is_dir():
        raise DiagnosticBlockedError("RETAINED_BATCH_EVIDENCE_MISSING")
    try:
        meta_bytes = meta_path.read_bytes()
        meta = json.loads(meta_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiagnosticBlockedError("RETAINED_BATCH_META_UNREADABLE") from exc
    if not isinstance(meta, Mapping):
        raise DiagnosticBlockedError("RETAINED_BATCH_META_SHAPE_INVALID")
    if (
        meta.get("provider") != "amazingdata"
        or meta.get("provider_dataset") != _STATUS_DATASET
        or meta.get("endpoint") != _STATUS_ENDPOINT
        or meta.get("normalization_surface") != _STATUS_SURFACE
        or meta.get("request_id") != _BATCH_REQUEST_ID
        or meta.get("status") != "OK"
    ):
        raise DiagnosticBlockedError("RETAINED_BATCH_IDENTITY_MISMATCH")
    params = meta.get("request_params")
    if not isinstance(params, Mapping):
        raise DiagnosticBlockedError("RETAINED_BATCH_PARAMS_MISSING")
    if (
        params.get("begin_date") != _START
        or params.get("end_date") != _END
        or params.get("is_local") is not False
        or not isinstance(params.get("code_list"), list)
    ):
        raise DiagnosticBlockedError("RETAINED_BATCH_SCOPE_MISMATCH")

    matches: list[tuple[Mapping[str, Any], Path]] = []
    tables = meta.get("tables")
    if not isinstance(tables, list):
        raise DiagnosticBlockedError("RETAINED_BATCH_TABLES_MISSING")
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        file_name = Path(str(table.get("file") or "")).name
        if _sha256_text(file_name) != _TARGET_MEMBER_SHA256:
            continue
        candidates = [path for path in batch_dir.rglob("*.parquet") if path.name == file_name]
        if len(candidates) == 1:
            matches.append((table, candidates[0]))
    if len(matches) != 1:
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_NOT_UNIQUE")

    table, table_path = matches[0]
    try:
        schema = pq.read_schema(table_path)
        parquet_meta = pq.ParquetFile(table_path).metadata
        row_count = int(parquet_meta.num_rows) if parquet_meta is not None else 0
        table_hash = _sha256_bytes(table_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_PARQUET_UNREADABLE") from exc
    columns = tuple(str(name) for name in schema.names)
    if row_count != 0 or columns:
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_SHAPE_CHANGED")
    provider_member = str(table.get("name") or "")
    if not provider_member:
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_ID_MISSING")
    if table_hash != str(table.get("content_hash") or ""):
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_PAYLOAD_HASH_MISMATCH")
    return provider_member, {
        "member_identity_sha256": _TARGET_MEMBER_SHA256,
        "provider_member_sha256": _sha256_text(provider_member),
        "batch_request_id": _BATCH_REQUEST_ID,
        "batch_meta_sha256": _sha256_bytes(meta_bytes),
        "batch_request_params_hash": str(meta.get("request_params_hash") or ""),
        "batch_payload_kind": str(meta.get("payload_kind") or ""),
        "batch_row_count": int(meta.get("row_count") or 0),
        "batch_table_count": len(tables),
        "batch_table_content_hash": table_hash,
        "batch_table_schema_hash": str(table.get("schema_hash") or ""),
        "batch_table_row_count": row_count,
    }


def _values_from_table(table: Any) -> list[Any]:
    columns = tuple(str(name) for name in getattr(table, "column_names", ()))
    if columns != ("value",):
        raise DiagnosticBlockedError("RETAINED_VALUE_TABLE_SCHEMA_INVALID")
    try:
        return table["value"].to_pylist()
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise DiagnosticBlockedError("RETAINED_VALUE_TABLE_UNREADABLE") from exc


def _load_applicable_sessions(raw_root: Path, provider_member: str) -> dict[str, Any]:
    """Prove the target is applicable on the retained exact-session dates."""
    calendar_root = _dataset_root(raw_root, _CALENDAR_DATASET)
    calendar_meta_path = calendar_root / f"{_CALENDAR_REQUEST_ID}.meta.json"
    if not calendar_meta_path.is_file():
        raise DiagnosticBlockedError("RETAINED_CALENDAR_EVIDENCE_MISSING")
    try:
        calendar_meta_bytes = calendar_meta_path.read_bytes()
        calendar_meta = json.loads(calendar_meta_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiagnosticBlockedError("RETAINED_CALENDAR_META_UNREADABLE") from exc
    if not isinstance(calendar_meta, Mapping):
        raise DiagnosticBlockedError("RETAINED_CALENDAR_META_SHAPE_INVALID")
    if (
        calendar_meta.get("provider") != "amazingdata"
        or calendar_meta.get("provider_dataset") != _CALENDAR_DATASET
        or calendar_meta.get("endpoint") != "BaseData.get_calendar"
        or calendar_meta.get("request_id") != _CALENDAR_REQUEST_ID
        or calendar_meta.get("status") != "OK"
        or (calendar_meta.get("request_params") or {}).get("market") != "SH"
    ):
        raise DiagnosticBlockedError("RETAINED_CALENDAR_IDENTITY_MISMATCH")
    calendar_table, _, calendar_table_meta = _read_table(raw_root, _CALENDAR_DATASET, calendar_meta)
    calendar_values = _values_from_table(calendar_table)
    calendar_dates = sorted(
        {int(value) for value in calendar_values if _START <= int(value) <= _END}
    )
    if len(calendar_dates) != _EXPECTED_SESSION_COUNT:
        raise DiagnosticBlockedError("RETAINED_CALENDAR_SESSION_COUNT_MISMATCH")

    hist_root = _dataset_root(raw_root, _HIST_CODE_DATASET)
    exact_by_date: dict[int, tuple[str, str]] = {}
    for meta_path in sorted(hist_root.glob("*.meta.json")):
        try:
            meta_bytes = meta_path.read_bytes()
            meta = json.loads(meta_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiagnosticBlockedError("RETAINED_HIST_CODE_META_UNREADABLE") from exc
        if not isinstance(meta, Mapping):
            raise DiagnosticBlockedError("RETAINED_HIST_CODE_META_SHAPE_INVALID")
        params = meta.get("request_params")
        if not isinstance(params, Mapping):
            continue
        begin = params.get("start_date")
        end = params.get("end_date")
        if begin != end or not isinstance(begin, int) or not _START <= begin <= _END:
            continue
        if params.get("security_type") != "EXTRA_STOCK_A_SH_SZ":
            raise DiagnosticBlockedError("RETAINED_HIST_CODE_SCOPE_MISMATCH")
        request_id = str(meta.get("request_id") or "")
        if (
            meta.get("provider") != "amazingdata"
            or meta.get("provider_dataset") != _HIST_CODE_DATASET
            or meta.get("endpoint") != "BaseData.get_hist_code_list"
            or meta.get("status") != "OK"
            or not request_id
        ):
            raise DiagnosticBlockedError("RETAINED_HIST_CODE_IDENTITY_MISMATCH")
        if begin in exact_by_date:
            raise DiagnosticBlockedError("RETAINED_HIST_CODE_DUPLICATE_EXACT_DATE")
        table, _, _ = _read_table(raw_root, _HIST_CODE_DATASET, meta)
        values = _values_from_table(table)
        present = any(str(value) == provider_member for value in values)
        exact_by_date[begin] = (request_id, "PRESENT" if present else "ABSENT")

    if set(exact_by_date) != set(calendar_dates):
        raise DiagnosticBlockedError("RETAINED_HIST_CODE_EXACT_SESSION_SET_MISMATCH")
    absent_dates = sorted(date for date, (_, state) in exact_by_date.items() if state != "PRESENT")
    if absent_dates:
        raise DiagnosticBlockedError("TARGET_NOT_APPLICABLE_ON_RETAINED_SESSION")
    request_ids = sorted(request_id for request_id, _ in exact_by_date.values())
    return {
        "calendar_request_id": _CALENDAR_REQUEST_ID,
        "calendar_meta_sha256": _sha256_bytes(calendar_meta_bytes),
        "calendar_table_content_hash": str(calendar_table_meta.get("content_hash") or ""),
        "calendar_session_count": len(calendar_dates),
        "exact_session_dates": calendar_dates,
        "exact_hist_code_request_count": len(request_ids),
        "exact_hist_code_request_ids_sha256": _sha256_text("\n".join(request_ids)),
        "target_present_session_count": len(calendar_dates),
        "applicability_status": "TARGET_PRESENT_ON_ALL_RETAINED_EXACT_SESSIONS",
    }


def _contract_evidence() -> dict[str, Any]:
    """Inspect only the installed public SDK contract, without logging values."""
    try:
        import AmazingData.query_api.market_data as market_data
        import AmazingData.utils.constant as constant
        import tgw

        query_doc = str(market_data.MarketData.query_snapshot.__doc__ or "")
        tgw_doc = str(tgw.QuerySnapshot.__doc__ or "")
        annotations = getattr(constant.Snapshot, "__annotations__", {})
        l1_fields = {str(name) for name in dir(tgw.MDSnapshotL1)}
        required_low_level = {"num_trades", "total_volume_trade", "total_value_trade"}
        required_typed = {"num_trades", "volume", "amount"}
        missing_low_level = sorted(required_low_level - l1_fields)
        missing_typed = sorted(required_typed - set(annotations))
        package_version = importlib.metadata.version("AmazingData")
        tgw_version = importlib.metadata.version("tgw")
    except (ImportError, AttributeError, KeyError, importlib.metadata.PackageNotFoundError):
        return {
            "status": "BLOCKED",
            "documentation_level": "SDK_PUBLIC_CONTRACT_UNAVAILABLE",
            "positive_field_contract_available": False,
        }

    fields = [
        {
            "semantic_id": "trade_count",
            "raw_sdk_field": "tgw.MDSnapshotL1.num_trades",
            "typed_sdk_field": "AmazingData.utils.constant.Snapshot.num_trades",
            "normalized_names": ["num_trades"],
            "meaning_basis": "public field identifier and typed integer annotation",
        },
        {
            "semantic_id": "executed_volume",
            "raw_sdk_field": "tgw.MDSnapshotL1.total_volume_trade",
            "typed_sdk_field": "AmazingData.utils.constant.Snapshot.volume",
            "normalized_names": ["volume"],
            "meaning_basis": "public total-volume-trade identifier and typed volume annotation",
        },
        {
            "semantic_id": "executed_amount",
            "raw_sdk_field": "tgw.MDSnapshotL1.total_value_trade",
            "typed_sdk_field": "AmazingData.utils.constant.Snapshot.amount",
            "normalized_names": ["amount"],
            "meaning_basis": "public total-value-trade identifier and typed amount annotation",
        },
    ]
    positive_available = not missing_low_level and not missing_typed
    return {
        "status": "CANDIDATE" if positive_available else "BLOCKED",
        "documentation_level": "PUBLIC_INSTALLED_SDK_CONTRACT_FIELD_IDENTIFIERS",
        "package": "AmazingData",
        "package_version": package_version,
        "tgw_package": "tgw",
        "tgw_package_version": tgw_version,
        "api": _SNAPSHOT_ENDPOINT,
        "api_doc_sha256": _sha256_text(query_doc),
        "low_level_api_doc_sha256": _sha256_text(tgw_doc),
        "api_declares_level_1_snapshot": "level-1" in query_doc.lower(),
        "api_declares_date_window_return_shape": "dataframe" in query_doc.lower(),
        "positive_field_contract_available": positive_available,
        "missing_low_level_fields": missing_low_level,
        "missing_typed_fields": missing_typed,
        "separate_vendor_field_prose_found": False,
        "field_semantics": fields,
        "positive_fact_rule": (
            "A finite strictly-positive num_trades, total_volume_trade/volume, or "
            "total_value_trade/amount in a returned L1 snapshot row is a positive "
            "executed-activity fact; row presence, price/quote, zero, empty, and "
            "absence are not facts."
        ),
        "vendor_public_surface": (
            "http://www.chinastock.com.cn/newsite/cgs-services/strategyTrade/geWuInstitution.html"
        ),
    }


def _status_label(status: Any) -> str:
    """Map only known SDK status values; never emit arbitrary SDK text."""
    known = ("kSuccess", "kDataEmpty")
    try:
        import tgw

        for name in known:
            if status == getattr(tgw.ErrorCode, name):
                return name
    except (AttributeError, ImportError):
        pass
    name_value = getattr(status, "name", None)
    if name_value in known:
        return str(name_value)
    if isinstance(status, str):
        return "STRING_KNOWN" if status in known else "STRING_OTHER"
    if status is None:
        return "NONE"
    return "OTHER"


def _shape_summary(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(value).__name__ if value is not None else "None"}
    if value is None:
        return result
    columns = getattr(value, "columns", None)
    result["column_count"] = len(columns) if columns is not None else None
    result["columns"] = [str(column) for column in columns] if columns is not None else []
    try:
        result["row_count"] = len(value)
    except TypeError:
        result["row_count"] = None
    return result


def _snapshot_callback_spy(events: list[dict[str, Any]]) -> AbstractContextManager[Any]:
    """Capture SDK callback statuses/shapes without retaining callback values."""
    try:
        import AmazingData.query_api.market_data as market_data
    except ImportError as exc:
        raise DiagnosticBlockedError("SDK_CALLBACK_HOOK_UNAVAILABLE") from exc
    original = getattr(market_data, "SnapshotSpi", None)
    if not isinstance(original, type):
        raise DiagnosticBlockedError("SDK_CALLBACK_HOOK_UNAVAILABLE")

    class SnapshotSpy(original):  # type: ignore[misc, valid-type]
        def OnResponse(self, data: Any, status: Any) -> Any:  # noqa: N802 - SDK callback name
            request = getattr(self, "_req", None)
            request_date = getattr(request, "date", None)
            events.append(
                {
                    "request_date": int(request_date) if isinstance(request_date, int) else None,
                    "status": _status_label(status),
                    "data_is_none": data is None,
                    "data_shape": _shape_summary(data),
                }
            )
            return super().OnResponse(data, status)

    return patch.object(market_data, "SnapshotSpi", SnapshotSpy)


def _callback_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(event.get("status")) for event in events)
    none_count = sum(1 for event in events if event.get("data_is_none") is True)
    by_date: dict[str, dict[str, int]] = {}
    for event in events:
        date = event.get("request_date")
        if not isinstance(date, int):
            continue
        bucket = by_date.setdefault(str(date), {})
        label = str(event.get("status"))
        bucket[label] = bucket.get(label, 0) + 1
    return {
        "event_count": len(events),
        "status_counts": dict(sorted(status_counts.items())),
        "data_is_none_count": none_count,
        "data_non_none_count": len(events) - none_count,
        "status_counts_by_date": dict(sorted(by_date.items())),
    }


def _finite_positive(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric) and numeric > 0


def _analyze_frame(frame: Any) -> dict[str, Any]:
    """Return only shape and positive-field counts, never field values."""
    shape = _shape_summary(frame)
    if frame is None:
        return {
            "status": "NO_RESPONSE",
            "frame_shape": shape,
            "activity_fields_present": [],
            "positive_fields": [],
            "positive_row_count": 0,
            "field_positive_row_counts": {},
        }
    if type(frame).__name__ != "DataFrame" or not hasattr(frame, "to_dict"):
        return {
            "status": "UNREADABLE_FRAME_SHAPE",
            "frame_shape": shape,
            "activity_fields_present": [],
            "positive_fields": [],
            "positive_row_count": 0,
            "field_positive_row_counts": {},
        }
    columns = [str(column) for column in getattr(frame, "columns", ())]
    by_lower = {column.lower(): column for column in columns}
    selected: dict[str, str] = {}
    for semantic, aliases in _ACTIVITY_FIELDS.items():
        for alias in aliases:
            actual = by_lower.get(alias.lower())
            if actual is not None:
                selected[semantic] = actual
                break
    try:
        records = frame.to_dict(orient="records")
    except (TypeError, ValueError, AttributeError):
        return {
            "status": "UNREADABLE_FRAME_SHAPE",
            "frame_shape": shape,
            "activity_fields_present": sorted(selected),
            "positive_fields": [],
            "positive_row_count": 0,
            "field_positive_row_counts": {},
        }
    if not isinstance(records, list) or any(not isinstance(record, Mapping) for record in records):
        return {
            "status": "UNREADABLE_FRAME_SHAPE",
            "frame_shape": shape,
            "activity_fields_present": sorted(selected),
            "positive_fields": [],
            "positive_row_count": 0,
            "field_positive_row_counts": {},
        }
    field_hits = Counter()
    positive_rows = 0
    for record in records:
        row_positive = False
        for semantic, column in selected.items():
            if _finite_positive(record.get(column)):
                field_hits[semantic] += 1
                row_positive = True
        positive_rows += int(row_positive)
    positive_fields = sorted(field_hits)
    if positive_rows:
        status = "POSITIVE_EXECUTED_ACTIVITY"
    elif selected:
        status = "NO_POSITIVE_ACTIVITY_VALUE"
    else:
        status = "NO_DOCUMENTED_ACTIVITY_FIELD"
    return {
        "status": status,
        "frame_shape": shape,
        "activity_fields_present": sorted(selected),
        "positive_fields": positive_fields,
        "positive_row_count": positive_rows,
        "field_positive_row_counts": dict(sorted(field_hits.items())),
    }


def _assess_payload(payload: Any, sessions: list[int], provider_member: str) -> dict[str, Any]:
    """Evaluate all applicable sessions with a positive-only rule."""
    if not isinstance(payload, Mapping):
        return {
            "status": "STOP(BLOCKED)",
            "outcome": "STOP(BLOCKED)",
            "reason_code": "SNAPSHOT_RESPONSE_SHAPE_INVALID",
            "applicable_session_count": len(sessions),
            "positive_session_count": 0,
            "session_observations": [],
        }
    date_map: dict[int, Any] = {}
    for key, value in payload.items():
        try:
            date = int(key)
        except (TypeError, ValueError):
            return {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": "SNAPSHOT_RESPONSE_DATE_KEY_INVALID",
                "applicable_session_count": len(sessions),
                "positive_session_count": 0,
                "session_observations": [],
            }
        if date in date_map:
            return {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": "SNAPSHOT_RESPONSE_DUPLICATE_DATE",
                "applicable_session_count": len(sessions),
                "positive_session_count": 0,
                "session_observations": [],
            }
        date_map[date] = value
    expected = set(sessions)
    extras = sorted(set(date_map) - expected)
    if extras:
        return {
            "status": "STOP(BLOCKED)",
            "outcome": "STOP(BLOCKED)",
            "reason_code": "SNAPSHOT_RESPONSE_EXTRA_SESSION",
            "applicable_session_count": len(sessions),
            "returned_session_count": len(date_map),
            "extra_session_count": len(extras),
            "positive_session_count": 0,
            "session_observations": [],
        }

    observations: list[dict[str, Any]] = []
    positive_dates: list[int] = []
    structural_reason: str | None = None
    for date in sessions:
        member_map = date_map.get(date)
        if not isinstance(member_map, Mapping):
            observation = {
                "date": date,
                "status": "UNREADABLE_SESSION_MEMBER_MAP",
                "member_present": False,
            }
            structural_reason = structural_reason or "SNAPSHOT_SESSION_MEMBER_MAP_INVALID"
        elif provider_member not in member_map:
            observation = {
                "date": date,
                "status": "MEMBER_NOT_RETURNED",
                "member_present": False,
            }
        elif len(member_map) != 1:
            observation = {
                "date": date,
                "status": "EXTRA_MEMBER_RETURNED",
                "member_present": True,
                "returned_member_count": len(member_map),
            }
            structural_reason = structural_reason or "SNAPSHOT_RESPONSE_EXTRA_MEMBER"
        else:
            frame_observation = _analyze_frame(member_map[provider_member])
            observation = {"date": date, "member_present": True, **frame_observation}
            if frame_observation.get("status") == "POSITIVE_EXECUTED_ACTIVITY":
                positive_dates.append(date)
        observations.append(observation)

    positive_count = len(positive_dates)
    result: dict[str, Any] = {
        "applicable_session_count": len(sessions),
        "returned_session_count": len(date_map),
        "positive_session_count": positive_count,
        "positive_session_dates": positive_dates,
        "session_observations": observations,
        "fallback_rule_encoded": False,
    }
    if structural_reason:
        result.update(
            {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": structural_reason,
            }
        )
    elif positive_count == len(sessions):
        result.update(
            {
                "status": "PROVIDER_SEMANTIC_RESOLVED",
                "outcome": "PROVIDER_SEMANTIC_RESOLVED",
                "implementation_status": "EVIDENCE_ONLY_PENDING_REVIEW",
                "review_required_before_rule_change": True,
            }
        )
    else:
        result.update(
            {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": "NO_POSITIVE_ACTIVITY_ON_ALL_APPLICABLE_SESSIONS",
            }
        )
    return result


def _count_rows(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, Mapping):
        return sum(_count_rows(item) for item in value.values())
    try:
        return len(value)
    except TypeError:
        return 0


def _raw_persist_summary(result: Any) -> dict[str, Any]:
    tables = tuple(getattr(result, "tables", ()))
    return {
        "status": "PERSISTED_LOCAL_IGNORED_ONLY",
        "request_id": str(getattr(result, "request_id", "")),
        "payload_kind": str(getattr(result, "payload_kind", "")),
        "row_count": int(getattr(result, "row_count", 0) or 0),
        "table_count": len(tables),
        "schema_hashes": sorted(str(getattr(table, "schema_hash", "")) for table in tables),
        "evidence_hash": str(getattr(result, "evidence_hash", "")),
    }


def _persist_session_frames(
    conn: Any,
    raw_root: Path,
    payload: Any,
    sessions: list[int],
    provider_member: str,
    *,
    parent_params_hash: str,
    identity: Any,
    account_profile_id: str,
) -> dict[str, Any]:
    """Retain returned per-session frames as separate local raw exchanges.

    ``MarketData.query_snapshot`` returns a nested ``date -> member ->
    DataFrame`` mapping, while the repository raw writer intentionally accepts
    one-level table mappings only.  The SDK sends one low-level request per
    date, so retaining each returned frame as its own child exchange preserves
    the provider table bytes without flattening or inventing a nested table.
    Missing date/member entries are not materialized as fake empty payloads.
    """
    if not isinstance(payload, Mapping):
        raise DiagnosticBlockedError("SNAPSHOT_RAW_SESSION_MAP_INVALID")
    date_map: dict[int, Any] = {}
    for key, value in payload.items():
        try:
            date_map[int(key)] = value
        except (TypeError, ValueError) as exc:
            raise DiagnosticBlockedError("SNAPSHOT_RAW_DATE_KEY_INVALID") from exc
    writer = AnchoredRawEvidenceWriter(
        conn,
        raw_root,
        ingest_run_id="cr7-positive-semantic-fallback-20260914",
    )
    results: list[Any] = []
    for date in sessions:
        member_map = date_map.get(date)
        if not isinstance(member_map, Mapping) or provider_member not in member_map:
            continue
        frame = member_map[provider_member]
        params = {
            "code_list": [provider_member],
            "begin_date": date,
            "end_date": date,
            "begin_time": _BEGIN_TIME,
            "end_time": _END_TIME,
            "parent_request_params_hash": parent_params_hash,
        }
        envelope = RawEnvelope(
            provider="amazingdata",
            provider_dataset=_SNAPSHOT_DATASET,
            endpoint=_SNAPSHOT_ENDPOINT,
            request_id=str(uuid.uuid4()),
            request_params=params,
            request_params_hash=RawEnvelope.params_hash(params),
            requested_at=datetime.now(UTC).isoformat(),
            received_at=datetime.now(UTC).isoformat(),
            sdk_version=identity.sdk_version,
            runtime_version=identity.tgw_runtime_version,
            account_profile_id=account_profile_id,
            row_count=_count_rows(frame),
            status="OK",
            duration_ms=0.0,
            attempt_count=1,
            capability_status="CANDIDATE",
            operation_id=_SNAPSHOT_OPERATION_ID,
            normalization_surface=_SNAPSHOT_SURFACE,
        )
        results.append(writer.write_exchange(ProviderExchange(envelope=envelope, payload=frame)))
    return {
        "status": "PERSISTED_LOCAL_IGNORED_ONLY",
        "exchange_count": len(results),
        "expected_exchange_count": len(sessions),
        "row_count": sum(int(getattr(result, "row_count", 0) or 0) for result in results),
        "payload_kinds": sorted({str(getattr(result, "payload_kind", "")) for result in results}),
        "request_ids_sha256": _sha256_text(
            "\n".join(sorted(str(getattr(result, "request_id", "")) for result in results))
        ),
        "evidence_hashes_sha256": _sha256_text(
            "\n".join(sorted(str(getattr(result, "evidence_hash", "")) for result in results))
        ),
    }


def _base_report(repo_root: Path, code_head: str | None) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "checked_at": datetime.now(UTC).isoformat(),
        "code_head": code_head,
        "scope": {
            "month": _MONTH,
            "start": "2024-01-01",
            "end": "2024-01-31",
            "inclusive": True,
            "member_selection": "ONE_RETAINED_STATUS_SCHEMA_MISMATCH_MEMBER",
            "query_surface": _SNAPSHOT_ENDPOINT,
            "begin_time": _BEGIN_TIME,
            "end_time": _END_TIME,
        },
        "authorization_boundary": {
            "formal_run_created": False,
            "production_activity": False,
            "broad_backfill": False,
            "stage_b_started": False,
            "other_members_queried": False,
            "other_months_queried": False,
            "month_completeness_changed": False,
        },
        "repository": {"root": repo_root.name},
    }


def _emit(report: Mapping[str, Any], output: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def _blocked(report: dict[str, Any], reason_code: str, output: Path | None, **extra: Any) -> int:
    report.update(
        {"status": "STOP(BLOCKED)", "outcome": "STOP(BLOCKED)", "reason_code": reason_code}
    )
    report.update(extra)
    _emit(report, output)
    return _BLOCKED_EXIT_CODE


def main() -> int:
    parser = argparse.ArgumentParser(
        description="run the fixed CR-7 positive-semantic fallback probe"
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--retained-raw-root",
        type=Path,
        default=Path("data/spike/cr7-month-completeness-semantics-stage-a-20260914/raw"),
    )
    parser.add_argument(
        "--diagnostic-raw-root",
        type=Path,
        default=Path("data/spike/cr7-positive-semantic-fallback-20260914/raw"),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/spike/cr7-positive-semantic-fallback-20260914/anchors.duckdb"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    report = _base_report(repo_root, _git_head(repo_root))
    contract = _contract_evidence()
    report["contract_evidence"] = contract
    if contract.get("positive_field_contract_available") is not True:
        return _blocked(report, "NO_PUBLIC_POSITIVE_ACTIVITY_FIELD_CONTRACT", args.output)

    try:
        provider_member, retained_summary = _retained_target(args.retained_raw_root)
        applicability = _load_applicable_sessions(args.retained_raw_root, provider_member)
    except DiagnosticBlockedError as exc:
        return _blocked(report, exc.reason_code, args.output, retained_batch={"status": "NOT_READ"})
    report["retained_batch"] = retained_summary
    report["applicability"] = applicability
    sessions = list(applicability["exact_session_dates"])

    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        return _blocked(
            report,
            "MISSING_TGW_ENV",
            args.output,
            provider_access={"status": "NOT_TESTABLE"},
        )

    args.diagnostic_raw_root.mkdir(parents=True, exist_ok=True)
    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(args.db_path))
    apply_migrations(conn, repo_root / "migrations")
    session = AmazingDataSession(*credentials)
    events: list[dict[str, Any]] = []
    try:
        try:
            session.login()
            identity = probe_identity(require_sdk=True)
        except ProviderError as exc:
            return _blocked(
                report,
                "PROVIDER_ACCESS_BLOCKED",
                args.output,
                provider_access={"status": "BLOCKED", "error_code": type(exc).__name__},
            )
        except Exception:  # noqa: BLE001 - no SDK text in a sanitized report
            return _blocked(
                report,
                "PROVIDER_ACCESS_UNEXPECTED_ERROR",
                args.output,
                provider_access={"status": "BLOCKED"},
            )
        if identity is None:
            return _blocked(
                report,
                "RUNTIME_IDENTITY_UNAVAILABLE",
                args.output,
                provider_access={"status": "BLOCKED"},
            )
        report["provider_access"] = {
            "status": "AUTHENTICATED_RUNTIME_READY",
            "sdk_version": identity.sdk_version,
            "tgw_package_version": identity.tgw_package_version,
            "runtime_version": identity.tgw_runtime_version,
            "python_version": identity.python_version,
            "abi_dir": identity.abi_dir,
        }

        params = {
            "code_list": [provider_member],
            "begin_date": _START,
            "end_date": _END,
            "begin_time": _BEGIN_TIME,
            "end_time": _END_TIME,
        }
        started = time.monotonic()
        try:
            with (
                _snapshot_callback_spy(events),
                sdk_stdout_into(CapturedStdout(), independent=True),
                sdk_stderr_into(CapturedStderr()),
            ):
                payload = session.sdk.MarketData(sessions).query_snapshot(**params)
        except DiagnosticBlockedError as exc:
            return _blocked(
                report,
                exc.reason_code,
                args.output,
                callback=_callback_summary(events),
            )
        except ProviderError as exc:
            return _blocked(
                report,
                "SNAPSHOT_QUERY_UNAVAILABLE",
                args.output,
                callback=_callback_summary(events),
                single_exchange={"status": "ERROR", "error_class": type(exc).__name__},
            )
        except Exception:  # noqa: BLE001 - no provider text in a sanitized report
            return _blocked(
                report,
                "SNAPSHOT_QUERY_UNEXPECTED_ERROR",
                args.output,
                callback=_callback_summary(events),
                single_exchange={"status": "ERROR"},
            )

        parent_params_hash = RawEnvelope.params_hash(params)
        semantic_assessment = _assess_payload(payload, sessions, provider_member)
        try:
            persisted = _persist_session_frames(
                conn,
                args.diagnostic_raw_root,
                payload,
                sessions,
                provider_member,
                parent_params_hash=parent_params_hash,
                identity=identity,
                account_profile_id=session.profile.account_profile_id,
            )
        except Exception:  # noqa: BLE001 - raw evidence failure is fail-closed
            return _blocked(
                report,
                "SNAPSHOT_RAW_PERSIST_FAILED",
                args.output,
                callback=_callback_summary(events),
                single_exchange={"status": "OK", "request_params_hash": parent_params_hash},
            )

        report["single_exchange"] = {
            "status": "OK",
            "request_params_hash": parent_params_hash,
            "row_count": _count_rows(payload),
            "payload_type": type(payload).__name__,
            "logical_member_count": 1,
            "logical_month_count": 1,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }
        report["callback"] = _callback_summary(events)
        report["raw_persist"] = persisted
        report.update(semantic_assessment)
        _emit(report, args.output)
        return 0 if report.get("status") == "PROVIDER_SEMANTIC_RESOLVED" else _BLOCKED_EXIT_CODE
    except DiagnosticBlockedError as exc:
        return _blocked(report, exc.reason_code, args.output)
    except Exception:  # noqa: BLE001 - no raw/provider text in a sanitized report
        return _blocked(report, "DIAGNOSTIC_UNEXPECTED_ERROR", args.output)
    finally:
        session.logout()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
