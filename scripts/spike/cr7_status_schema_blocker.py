"""Diagnose the single CR-7 2024-01 status-schema blocker.

This spike is intentionally narrower than the month-completeness runner:
it reads one retained, locally ignored Stage A batch to identify the one
opaque member with a zero-column response, then makes exactly one live
AmazingData request for that member over the fixed ``2024-01`` window.

The retained raw evidence and the singleton response are never copied into
the repository.  The emitted report contains only request identities, hashes,
shape metadata, and the fixed fail-closed outcome.  In particular, an empty
status response is never converted into ``IS_SUSP_SEC=0``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import pyarrow.parquet as pq

from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.amazingdata.sdk_loader import probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage import apply_migrations
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter

_SCHEMA = "cr7.status_schema_blocker.v1"
_TARGET_MEMBER_SHA256 = "2f3fcbddeafab98dcacf9a6b3b006b7192f704c9741cdf3eac96240083df1f54"
_BATCH_REQUEST_ID = "2a0ff664-3c1e-4e4d-b40e-86b71758c48c"
_DATASET = "history_stock_status"
_ENDPOINT = "InfoData.get_history_stock_status"
_SURFACE = "security_status_history"
_START = 20240101
_END = 20240131
_MONTH = "2024-01"
_BLOCKED_EXIT_CODE = 2
_ENV_KEYS = (
    "TGW_USERNAME",
    "TGW_PASSWORD",
    "TGW_SERVER_VIP",
    "TGW_SERVER_PORT",
)


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


def _dataset_root(raw_root: Path) -> Path:
    return raw_root / "provider=amazingdata" / f"dataset={_DATASET}"


def _retained_member(raw_root: Path) -> dict[str, Any]:
    """Resolve the fixed opaque member and validate its retained shape."""
    dataset_root = _dataset_root(raw_root)
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
        or meta.get("provider_dataset") != _DATASET
        or meta.get("endpoint") != _ENDPOINT
        or meta.get("normalization_surface") != _SURFACE
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

    tables = meta.get("tables")
    if not isinstance(tables, list):
        raise DiagnosticBlockedError("RETAINED_BATCH_TABLES_MISSING")
    matches: list[tuple[Mapping[str, Any], Path]] = []
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
    except (OSError, ValueError) as exc:
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_PARQUET_UNREADABLE") from exc
    columns = tuple(str(name) for name in schema.names)
    if row_count != 0 or columns:
        raise DiagnosticBlockedError("ANOMALOUS_MEMBER_SHAPE_CHANGED")
    return {
        "member_identity_sha256": _TARGET_MEMBER_SHA256,
        "batch_request_id": _BATCH_REQUEST_ID,
        "batch_meta_sha256": _sha256_bytes(meta_bytes),
        "batch_request_params_hash": str(meta.get("request_params_hash") or ""),
        "batch_payload_kind": str(meta.get("payload_kind") or ""),
        "batch_row_count": int(meta.get("row_count") or 0),
        "batch_table_count": len(tables),
        "batch_table_content_hash": str(table.get("content_hash") or ""),
        "batch_table_schema_hash": str(table.get("schema_hash") or ""),
        "batch_table_row_count": row_count,
        "provider_member": str(table.get("name") or ""),
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


def _callback_spy(events: list[dict[str, Any]]) -> AbstractContextManager[Any]:
    """Capture SDK callback status without retaining callback data values."""
    try:
        import AmazingData.download_data.download_info_data as download_info_data
    except ImportError as exc:
        raise DiagnosticBlockedError("SDK_CALLBACK_HOOK_UNAVAILABLE") from exc
    original = getattr(download_info_data, "HistStockStatusSpi", None)
    if not isinstance(original, type):
        raise DiagnosticBlockedError("SDK_CALLBACK_HOOK_UNAVAILABLE")

    class StatusSpy(original):  # type: ignore[misc, valid-type]
        def OnResponse(self, data: Any, status: Any) -> Any:  # noqa: N802 - SDK callback name
            events.append(
                {
                    "status": _status_label(status),
                    "data_is_none": data is None,
                    "data_shape": _shape_summary(data),
                }
            )
            return super().OnResponse(data, status)

    return patch.object(download_info_data, "HistStockStatusSpi", StatusSpy)


def _callback_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(event.get("status")) for event in events)
    none_count = sum(1 for event in events if event.get("data_is_none") is True)
    return {
        "event_count": len(events),
        "status_counts": dict(sorted(status_counts.items())),
        "data_is_none_count": none_count,
        "data_non_none_count": len(events) - none_count,
    }


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


def _assess_shape(
    callback: Mapping[str, Any],
    frame_shape: Mapping[str, Any],
    raw_persist: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate shape attribution from status semantics.

    ``kDataEmpty`` is a provider/runtime observation, not a status fact.  The
    helper deliberately returns a blocked outcome even when the adapter and
    raw writer preserve the empty shape exactly.
    """
    event_count = int(callback.get("event_count") or 0)
    status_counts = callback.get("status_counts")
    all_empty_callbacks = (
        event_count > 0
        and status_counts == {"kDataEmpty": event_count}
        and callback.get("data_is_none_count") == event_count
    )
    adapter_preserved = (
        frame_shape.get("type") == "DataFrame"
        and frame_shape.get("row_count") == 0
        and frame_shape.get("column_count") == 0
        and raw_persist.get("row_count") == 0
        and raw_persist.get("table_count") == 1
    )
    return {
        "shape_attribution": {
            "facade_payload_policy": "SDK_PAYLOAD_FORWARDED_WITHOUT_STATUS_FIELD_SYNTHESIS",
            "raw_writer_shape_preserved": adapter_preserved,
            "provider_callback_signal": "KDATAEMPTY_WITH_NONE_DATA"
            if all_empty_callbacks
            else "NOT_EXCLUSIVELY_KDATAEMPTY",
            "attribution": "API_OR_RUNTIME_EMPTY_RESPONSE_NOT_ADAPTER_COLUMN_LOSS"
            if all_empty_callbacks and adapter_preserved
            else "NOT_ESTABLISHED",
        },
        "semantic_assessment": {
            "empty_response_means_is_susp_sec_zero": False,
            "empty_response_means_no_status_change": False,
            "positive_provider_rule_observed": False,
            "rule_status": "NOT_DEFINED_BY_OBSERVED_AMAZINGDATA_CONTRACT",
        },
        "status": "STOP(BLOCKED)",
        "outcome": "STOP(BLOCKED)",
        "reason_code": "NO_POSITIVE_PROVIDER_SEMANTIC_RULE",
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
        },
        "authorization_boundary": {
            "formal_run_created": False,
            "production_activity": False,
            "broad_backfill": False,
            "stage_b_started": False,
            "other_members_queried": False,
        },
        "repository": {"root": repo_root.name},
    }


def _emit(report: Mapping[str, Any], output: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def main() -> int:
    parser = argparse.ArgumentParser(description="run the fixed CR-7 status-schema blocker probe")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--retained-raw-root",
        type=Path,
        default=Path("data/spike/cr7-month-completeness-semantics-stage-a-20260914/raw"),
    )
    parser.add_argument(
        "--diagnostic-raw-root",
        type=Path,
        default=Path("data/spike/cr7-status-schema-blocker-20260914/raw"),
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/spike/cr7-status-schema-blocker-20260914/anchors.duckdb"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    report = _base_report(repo_root, _git_head(repo_root))
    try:
        retained = _retained_member(args.retained_raw_root)
    except DiagnosticBlockedError as exc:
        report.update(
            {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": exc.reason_code,
                "retained_batch": {"status": "NOT_READ"},
            }
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE

    provider_member = str(retained.pop("provider_member"))
    report["retained_batch"] = retained
    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        report.update(
            {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": "MISSING_TGW_ENV",
                "provider_access": {"status": "NOT_TESTABLE"},
            }
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE

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
            report.update(
                {
                    "status": "STOP(BLOCKED)",
                    "outcome": "STOP(BLOCKED)",
                    "reason_code": "PROVIDER_ACCESS_BLOCKED",
                    "provider_access": {"status": "BLOCKED", "error_code": type(exc).__name__},
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        except Exception:  # noqa: BLE001 - no SDK text in a sanitized report
            report.update(
                {
                    "status": "STOP(BLOCKED)",
                    "outcome": "STOP(BLOCKED)",
                    "reason_code": "PROVIDER_ACCESS_UNEXPECTED_ERROR",
                    "provider_access": {"status": "BLOCKED"},
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        if identity is None:
            report.update(
                {
                    "status": "STOP(BLOCKED)",
                    "outcome": "STOP(BLOCKED)",
                    "reason_code": "RUNTIME_IDENTITY_UNAVAILABLE",
                    "provider_access": {"status": "BLOCKED"},
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE

        report["provider_access"] = {
            "status": "AUTHENTICATED_RUNTIME_READY",
            "sdk_version": identity.sdk_version,
            "runtime_version": identity.tgw_runtime_version,
        }
        provider = AmazingDataProvider(
            session,
            identity=identity,
            use_mode=ProviderUseMode.SPIKE,
            budget=TimeBudget(query_timeout_seconds=75.0, connect_timeout_seconds=20.0),
            retry=RetryPolicy(max_retries=0),
        )
        try:
            with _callback_spy(events):
                exchange = provider.get_history_stock_status_exchange(
                    _START,
                    _END,
                    [provider_member],
                )
        except DiagnosticBlockedError as exc:
            report.update(
                {
                    "status": "STOP(BLOCKED)",
                    "outcome": "STOP(BLOCKED)",
                    "reason_code": exc.reason_code,
                    "callback": _callback_summary(events),
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        except ProviderError as exc:
            report.update(
                {
                    "status": "STOP(BLOCKED)",
                    "outcome": "STOP(BLOCKED)",
                    "reason_code": "SINGLE_MEMBER_EXCHANGE_UNAVAILABLE",
                    "callback": _callback_summary(events),
                    "single_exchange": {
                        "status": "ERROR",
                        "error_class": type(exc).__name__,
                    },
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE

        if not isinstance(exchange, ProviderExchange):
            raise DiagnosticBlockedError("SINGLE_EXCHANGE_SHAPE_INVALID")
        payload = exchange.payload
        if not isinstance(payload, Mapping) or provider_member not in payload:
            raise DiagnosticBlockedError("SINGLE_MEMBER_NOT_PRESENT_IN_RESPONSE")
        frame = payload[provider_member]
        frame_shape = _shape_summary(frame)
        writer = AnchoredRawEvidenceWriter(
            conn,
            args.diagnostic_raw_root,
            ingest_run_id="cr7-status-schema-blocker-20260914",
        )
        persisted = writer.write_exchange(exchange)
        callback = _callback_summary(events)
        report["single_exchange"] = {
            "status": str(getattr(exchange.envelope, "status", "")),
            "request_id": str(getattr(exchange.envelope, "request_id", "")),
            "request_params_hash": str(getattr(exchange.envelope, "request_params_hash", "")),
            "row_count": int(getattr(exchange.envelope, "row_count", 0) or 0),
            "payload_type": type(payload).__name__,
            "member_present": True,
            "member_shape": frame_shape,
        }
        report["callback"] = callback
        report["raw_persist"] = _raw_persist_summary(persisted)
        report.update(
            _assess_shape(
                callback,
                frame_shape,
                report["raw_persist"],
            )
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE
    except DiagnosticBlockedError as exc:
        report.update(
            {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": exc.reason_code,
            }
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE
    except Exception:  # noqa: BLE001 - no raw/provider text in report
        report.update(
            {
                "status": "STOP(BLOCKED)",
                "outcome": "STOP(BLOCKED)",
                "reason_code": "DIAGNOSTIC_UNEXPECTED_ERROR",
            }
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE
    finally:
        session.logout()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
