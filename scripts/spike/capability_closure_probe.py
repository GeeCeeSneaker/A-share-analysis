"""Run the six authorized AmazingData capability-closure probes.

This is a targeted, non-Production preflight.  It deliberately does not
create a ``SpikeRun``, mutate the Golden set, or write a catalog/verdict.
Credentials are read only from ``TGW_*`` environment variables (or a local
ignored ``.env`` file).  Each successful or failed provider exchange is
written to the ignored local raw area; the report contains only counts,
schemas, hashes, and fixed taxonomy labels.

Usage::

    uv run python scripts/spike/capability_closure_probe.py \
      --output data/spike/capability-closure-20260911/report.json

The exact symbol lists are retained in the local raw envelope parameters and
are represented in the report by a count and a deterministic set hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ashare_state.providers.amazingdata.provider import AmazingDataProvider, ProviderUseMode
from ashare_state.providers.amazingdata.safe_diagnostics import safe_error_code
from ashare_state.providers.amazingdata.sdk_loader import probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage.raw_writer import RawWriter, RawWriteResult

_ENV_KEYS = (
    "TGW_USERNAME",
    "TGW_PASSWORD",
    "TGW_SERVER_VIP",
    "TGW_SERVER_PORT",
)
_RAW_INGEST_ID = "capability-closure-preflight-20260911"
_STATUS_SYMBOLS = [
    "002058.SZ",
    "002217.SZ",
    "002313.SZ",
    "002366.SZ",
    "600382.SH",
    "688500.SH",
    "605499.SH",
    "603887.SH",
]
_BSE_SYMBOLS = ["835185.BJ"]
_BASIC_SYMBOLS = ["601558.SH", "600068.SH", "300104.SZ", "835185.BJ"]
_DIVIDEND_SYMBOLS = [
    "600519.SH",
    "601318.SH",
    "600036.SH",
    "000858.SZ",
    "000333.SZ",
    "601398.SH",
    "000651.SZ",
    "000002.SZ",
    "600900.SH",
    "600104.SH",
]
_RIGHT_ISSUE_SYMBOLS = ["002142.SZ", "300475.SZ", "002788.SZ", "601555.SH", "000750.SZ"]
_HISTORY_BEGIN = 19900101
_HISTORY_END = 20991231
_BSE_BEGIN = 20220101
_BSE_END = 20221231
_CA_BEGIN = 20190101
_CA_END = 20241231
_FIXTURE_BEGIN = 20200101
_FIXTURE_END = 20200110


def _load_env(path: Path) -> dict[str, str]:
    """Load only TGW variables; never print or persist their values."""
    values = {key: value for key, value in os.environ.items() if key in _ENV_KEYS}
    if path.is_file():
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


def _credentials(env: dict[str, str]) -> tuple[str, str, str, int] | None:
    if not all(env.get(key) for key in _ENV_KEYS):
        return None
    try:
        port = int(env["TGW_SERVER_PORT"])
    except (TypeError, ValueError):
        return None
    return env["TGW_USERNAME"], env["TGW_PASSWORD"], env["TGW_SERVER_VIP"], port


def _symbol_scope(symbols: list[str]) -> dict[str, Any]:
    canonical = json.dumps(symbols, ensure_ascii=False, separators=(",", ":"))
    return {
        "symbol_count": len(symbols),
        "symbol_set_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _date_scope(begin_date: int, end_date: int) -> dict[str, int]:
    return {"begin_date": begin_date, "end_date": end_date}


def _as_frame(value: Any) -> Any | None:
    """Convert supported provider tables to pandas without importing it early."""
    try:
        import pandas as pd
    except ImportError:
        return None
    if isinstance(value, pd.DataFrame):
        return value
    try:
        import pyarrow as pa

        if isinstance(value, pa.Table):
            return value.to_pandas()
    except ImportError:
        pass
    to_pandas = getattr(value, "to_pandas", None)
    if callable(to_pandas):
        try:
            frame = to_pandas()
        except Exception:  # noqa: BLE001 - shape inspection must not abort the probe
            return None
        return frame if isinstance(frame, pd.DataFrame) else None
    if isinstance(value, list):
        if not value:
            return pd.DataFrame()
        if all(isinstance(row, dict) for row in value):
            return pd.DataFrame(value)
        return pd.DataFrame({"value": value})
    return None


def _table_parts(payload: Any) -> tuple[list[tuple[str, Any]], int, str | None]:
    """Return named frames, explicit-null count, and an unsupported shape label."""
    if isinstance(payload, dict):
        tables: list[tuple[str, Any]] = []
        null_count = 0
        for name, value in payload.items():
            if value is None:
                null_count += 1
                continue
            frame = _as_frame(value)
            if frame is None:
                return [], null_count, type(value).__name__
            tables.append((str(name), frame))
        return tables, null_count, None
    frame = _as_frame(payload)
    if frame is None:
        return [], 0, type(payload).__name__
    return [("table", frame)], 0, None


def _field_stats(
    tables: list[tuple[str, Any]], field: str, *, date: bool = False
) -> dict[str, int]:
    import pandas as pd

    table_count = 0
    row_count = 0
    null_count = 0
    invalid_count = 0
    for _, frame in tables:
        if field not in frame.columns:
            continue
        table_count += 1
        series = frame[field]
        row_count += len(series)
        null_count += int(series.isna().sum())
        if date:
            try:
                invalid_count += int(pd.to_datetime(series, errors="coerce").isna().sum())
            except (TypeError, ValueError):
                invalid_count += len(series)
    return {
        "table_count": table_count,
        "row_count": row_count,
        "null_count": null_count,
        "invalid_count": invalid_count,
        "nonnull_count": row_count - null_count,
    }


def _progress_date_shape(tables: list[tuple[str, Any]], date_field: str) -> dict[str, int]:
    """Aggregate missing event dates by the provider's progress code."""
    counts: dict[str, int] = {}
    for _, frame in tables:
        if "DIV_PROGRESS" not in frame.columns or date_field not in frame.columns:
            continue
        for progress, group in frame.groupby("DIV_PROGRESS", dropna=False):
            key = str(progress)
            missing = int(group[date_field].isna().sum())
            counts[key] = counts.get(key, 0) + missing
    return counts


def _payload_summary(payload: Any) -> dict[str, Any]:
    tables, null_count, unsupported = _table_parts(payload)
    columns = sorted({str(column) for _, frame in tables for column in frame.columns})
    summary: dict[str, Any] = {
        "payload_type": type(payload).__name__,
        "table_count": len(tables),
        "null_table_count": null_count,
        "row_count": sum(len(frame) for _, frame in tables),
        "table_names": [name for name, _ in tables],
        "table_row_counts": {name: len(frame) for name, frame in tables},
        "columns": columns,
        "unsupported_member_type": unsupported,
        "field_stats": {
            field: _field_stats(
                tables,
                field,
                date=field
                in {
                    "TRADE_DATE",
                    "DATE_EX",
                    "EX_DIVIDEND_DATE",
                    "DELISTING_DATE",
                    "DELISTDATE",
                    "LISTDATE",
                },
            )
            for field in (
                "TRADE_DATE",
                "DATE_EX",
                "EX_DIVIDEND_DATE",
                "IS_LISTED",
                "DELISTING_DATE",
                "DELISTDATE",
                "LISTDATE",
                "MARKET_CODE",
                "SECURITY_CODE",
            )
        },
        "dividend_progress_missing_date_rows": _progress_date_shape(tables, "DATE_EX"),
    }
    return summary


def _calendar_days(payload: Any) -> list[int]:
    tables, _, _ = _table_parts(payload)
    values: list[int] = []
    for _, frame in tables:
        column = next(
            (
                candidate
                for candidate in ("TRADE_DATE", "DATE", "CALENDAR_DATE", "value")
                if candidate in frame.columns
            ),
            None,
        )
        if column is None:
            continue
        for value in frame[column].tolist():
            try:
                text = str(value)
                if len(text) >= 8 and text[:8].isdigit():
                    values.append(int(text[:8]))
                else:
                    values.append(int(value.strftime("%Y%m%d")))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
    return sorted(set(values))


def _payload_contains_symbol(payload: Any, target: str) -> bool:
    target_code = target.split(".", 1)[0]
    tables, _, _ = _table_parts(payload)
    for _, frame in tables:
        for column in ("MARKET_CODE", "SECURITY_CODE", "STOCK_CODE", "CODE", "value"):
            if column not in frame.columns:
                continue
            for value in frame[column].tolist():
                if str(value).split(".", 1)[0] == target_code:
                    return True
    return False


def _artifact_summary(result: RawWriteResult) -> dict[str, Any]:
    return {
        "meta_uri": result.meta_uri,
        "evidence_hash": result.evidence_hash,
        "payload_kind": result.payload_kind,
        "row_count": result.row_count,
        "null_tables": list(result.null_tables),
        "payload_artifacts": [
            {
                "uri": ref.uri,
                "content_hash": ref.content_hash,
                "schema_hash": ref.schema_hash,
                "row_count": ref.row_count,
            }
            for ref in result.payload_artifacts
        ],
    }


def _call(
    *,
    probe_id: str,
    request: dict[str, Any],
    fn: Callable[[], ProviderExchange],
    writer: RawWriter,
) -> tuple[dict[str, Any], Any | None]:
    """Execute one exchange, preserving failure evidence without raw output."""
    record: dict[str, Any] = {"probe_id": probe_id, "request": request}
    exchange: ProviderExchange | None = None
    try:
        exchange = fn()
    except ProviderError as exc:
        record["status"] = "ERROR"
        record["error_code"] = safe_error_code(exc)
        exchange = exc.exchange
    except Exception:  # noqa: BLE001 - fixed taxonomy only in the report
        record["status"] = "ERROR"
        record["error_code"] = "UNEXPECTED_ERROR"

    if exchange is None:
        return record, None

    envelope = exchange.envelope
    record["exchange"] = {
        "request_id": exchange.request_id,
        "endpoint": str(getattr(envelope, "endpoint", "")),
        "provider_dataset": str(getattr(envelope, "provider_dataset", "")),
        "status": str(getattr(envelope, "status", "")),
        "row_count": int(getattr(envelope, "row_count", 0) or 0),
        "request_params_hash": str(getattr(envelope, "request_params_hash", "")),
        "capability_status": getattr(envelope, "capability_status", None),
    }
    record["status"] = record["exchange"]["status"]
    try:
        persisted = writer.write(exchange)
    except Exception:  # noqa: BLE001 - persistence outcome is explicit below
        record["raw_write_status"] = "RAW_WRITER_ERROR"
    else:
        record["raw_write_status"] = "OK"
        record["raw_artifact"] = _artifact_summary(persisted)

    if record["status"] == "OK":
        record["payload_summary"] = _payload_summary(exchange.payload)
        return record, exchange.payload
    return record, None


def _error_classification(record: dict[str, Any]) -> str:
    if record.get("status") == "OK":
        return ""
    if record.get("error_code") in {
        "ProviderAuthError",
        "ProviderPermissionError",
        "ProviderUnavailableError",
        "ProviderNetworkError",
    }:
        return "PERMISSION/ENDPOINT_LIMITATION"
    return "STILL_UNRESOLVED"


def _status_finding(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "OK":
        return {
            "classification": _error_classification(record),
            "finding": "targeted native status request did not complete",
        }
    summary = record.get("payload_summary", {})
    stats = summary.get("field_stats", {}).get("TRADE_DATE", {})
    invalid = int(stats.get("invalid_count", 0))
    if invalid:
        return {
            "classification": "STILL_UNRESOLVED",
            "finding": (
                "native response contains missing or unparseable TRADE_DATE rows; "
                "the observed shape is recorded, but no production non-observation "
                "discard rule is authorized without a provider contract"
            ),
            "invalid_trade_date_rows": invalid,
        }
    return {
        "classification": "STILL_UNRESOLVED",
        "finding": "targeted native response did not reproduce the sealed malformed-date rows",
        "invalid_trade_date_rows": 0,
    }


def _bse_finding(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "OK":
        return {
            "classification": _error_classification(record),
            "finding": "exact BSE historical status request did not complete",
        }
    rows = int(record.get("payload_summary", {}).get("row_count", 0))
    return {
        "classification": "PROVIDER_CONFIRMED",
        "finding": (
            "exact native request returned an empty result"
            if rows == 0
            else (
                "exact native request returned historical rows; prior empty result "
                "was not reproduced"
            )
        ),
        "row_count": rows,
        "semantic_status": "STILL_UNRESOLVED",
    }


def _basic_finding(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "OK":
        return {
            "classification": _error_classification(record),
            "finding": "stock-basic request did not complete",
        }
    summary = record.get("payload_summary", {})
    stats = summary.get("field_stats", {})
    observed = int(summary.get("row_count", 0))
    requested = int(record.get("request", {}).get("symbol_count", 0))
    available = [
        field
        for field in ("IS_LISTED", "DELISTDATE", "LISTDATE")
        if int(stats.get(field, {}).get("table_count", 0)) > 0
    ]
    if available:
        return {
            "classification": "PROVIDER_CONFIRMED",
            "finding": "stock-basic response exposes delisting-related fields",
            "fields": available,
            "row_count": observed,
            "requested_symbol_count": requested,
            "semantic_status": "STILL_UNRESOLVED",
        }
    return {
        "classification": "STILL_UNRESOLVED",
        "finding": "stock-basic response does not expose the required delisting fields",
        "row_count": observed,
        "requested_symbol_count": requested,
    }


def _mapping_finding(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") != "OK":
        return {
            "classification": _error_classification(record),
            "finding": "dedicated BJ mapping endpoint request did not complete",
        }
    rows = int(record.get("payload_summary", {}).get("row_count", 0))
    return {
        "classification": "PROVIDER_CONFIRMED" if rows else "STILL_UNRESOLVED",
        "finding": (
            "dedicated endpoint returned a non-empty mapping table"
            if rows
            else "dedicated endpoint returned no mapping rows"
        ),
        "row_count": rows,
    }


def _ca_finding(record: dict[str, Any], field: str) -> dict[str, Any]:
    if record.get("status") != "OK":
        return {
            "classification": _error_classification(record),
            "finding": "corporate-action request did not complete",
        }
    summary = record.get("payload_summary", {})
    stats = summary.get("field_stats", {}).get(field, {})
    rows = int(summary.get("row_count", 0))
    if rows == 0:
        return {
            "classification": "STILL_UNRESOLVED",
            "finding": "no native event rows returned for the targeted symbols",
            "row_count": 0,
        }
    if int(stats.get("table_count", 0)) == 0:
        return {
            "classification": "PROVIDER_CONFIRMED",
            "finding": f"non-empty native event response lacks required {field} column",
            "row_count": rows,
        }
    missing = int(stats.get("invalid_count", 0))
    progress_missing = summary.get("dividend_progress_missing_date_rows", {})
    observed_non_event_missing = sum(
        int(progress_missing.get(code, 0)) for code in ("1", "2", "12")
    )
    unexpected_missing = max(0, missing - observed_non_event_missing)
    if field == "DATE_EX" and missing:
        return {
            "classification": "STILL_UNRESOLVED",
            "finding": (
                "native dividend response contains missing DATE_EX values; the "
                "observed progress-code correlation is not a semantic contract "
                "and no production filter is applied"
            ),
            "row_count": rows,
            "missing_or_invalid_rows": missing,
            "observed_progress_missing_rows": observed_non_event_missing,
            "unexpected_missing_or_invalid_rows": unexpected_missing,
        }
    return {
        "classification": "PROVIDER_CONFIRMED" if unexpected_missing else "STILL_UNRESOLVED",
        "finding": (
            f"native event response contains missing or invalid {field} values"
            if missing
            else f"native event response contains the required {field} field"
        ),
        "row_count": rows,
        "missing_or_invalid_rows": missing,
        "unexpected_missing_or_invalid_rows": unexpected_missing,
    }


def _fixture_finding(
    basic: dict[str, Any],
    history: dict[str, Any],
    kline: dict[str, Any],
    control_kline: dict[str, Any],
    *,
    history_contains_target: bool,
) -> dict[str, Any]:
    if (
        basic.get("status") != "OK"
        or history.get("status") != "OK"
        or kline.get("status") != "OK"
        or control_kline.get("status") != "OK"
    ):
        return {
            "classification": next(
                (
                    _error_classification(record)
                    for record in (history, kline, control_kline, basic)
                    if record.get("status") != "OK"
                ),
                "STILL_UNRESOLVED",
            ),
            "finding": "300104.SZ basic/tradability preflight did not complete",
        }
    bars = int(kline.get("payload_summary", {}).get("row_count", 0))
    control_bars = int(control_kline.get("payload_summary", {}).get("row_count", 0))
    if bars and control_bars:
        return {
            "classification": "PROVIDER_CONFIRMED",
            "finding": "stock-basic and daily-kline endpoints returned evidence for 300104.SZ",
            "bar_row_count": bars,
            "historical_code_list_contains_target": history_contains_target,
            "applicability_status": "STILL_UNRESOLVED",
        }
    if control_bars:
        return {
            "classification": "PROVIDER_CONFIRMED",
            "finding": (
                "daily-kline adapter returned a control symbol but no 300104.SZ bars; "
                "the fixture is not currently usable for historical tradability"
            ),
            "bar_row_count": 0,
            "control_bar_row_count": control_bars,
            "historical_code_list_contains_target": history_contains_target,
            "replacement_candidate": "600519.SH",
            "applicability_status": "STILL_UNRESOLVED",
        }
    return {
        "classification": "STILL_UNRESOLVED",
        "finding": "daily-kline endpoint returned no target or control bars in the fixture window",
        "bar_row_count": 0,
        "control_bar_row_count": control_bars,
        "historical_code_list_contains_target": history_contains_target,
    }


def _empty_report(*, code_head: str = "") -> dict[str, Any]:
    return {
        "schema": "amazingdata.capability_closure_preflight.v1",
        "probe_mode": "TARGETED_NON_PRODUCTION",
        "checked_at": datetime.now(UTC).isoformat(),
        "code_head": code_head or None,
        "status": "NOT_TESTABLE_ACCOUNT",
        "formal_run_created": False,
        "catalog_mutated": False,
        "verdict_mutated": False,
        "calls": [],
        "capability_closure": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="run targeted non-Production capability probes")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/spike/capability-closure-20260911/raw"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--code-head",
        default="",
        help="source commit being exercised; recorded in the sanitized receipt",
    )
    args = parser.parse_args()

    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        report = _empty_report(code_head=args.code_head)
        report["error_code"] = "MISSING_TGW_ENV"
        _emit(report, args.output)
        return 2

    session = AmazingDataSession(*credentials)
    writer = RawWriter(args.raw_root, ingest_run_id=_RAW_INGEST_ID)
    calls: dict[str, dict[str, Any]] = {}
    payloads: dict[str, Any] = {}
    try:
        profile = session.login()
        identity = probe_identity(require_sdk=True)
        if identity is None:
            report = _empty_report(code_head=args.code_head)
            report["status"] = "NOT_TESTABLE_RUNTIME"
            report["error_code"] = "ProviderUnavailableError"
            _emit(report, args.output)
            return 2
        provider = AmazingDataProvider(
            session,
            identity=identity,
            budget=TimeBudget(query_timeout_seconds=90.0, connect_timeout_seconds=20.0),
            retry=RetryPolicy(max_retries=0),
            use_mode=ProviderUseMode.SPIKE,
        )

        def run(probe_id: str, request: dict[str, Any], fn: Callable[[], ProviderExchange]) -> None:
            record, payload = _call(probe_id=probe_id, request=request, fn=fn, writer=writer)
            calls[probe_id] = record
            if payload is not None:
                payloads[probe_id] = payload

        run(
            "status_date_shape",
            {**_symbol_scope(_STATUS_SYMBOLS), **_date_scope(_HISTORY_BEGIN, _HISTORY_END)},
            lambda: provider.get_history_stock_status_exchange(
                _HISTORY_BEGIN, _HISTORY_END, _STATUS_SYMBOLS
            ),
        )
        run(
            "bse_historical_status",
            {**_symbol_scope(_BSE_SYMBOLS), **_date_scope(_BSE_BEGIN, _BSE_END)},
            lambda: provider.get_history_stock_status_exchange(_BSE_BEGIN, _BSE_END, _BSE_SYMBOLS),
        )
        run(
            "delisted_stock_basic",
            _symbol_scope(_BASIC_SYMBOLS),
            lambda: provider.get_stock_basic_exchange(_BASIC_SYMBOLS),
        )
        run(
            "fixture_300104_history_code_list",
            {
                "security_type": "EXTRA_STOCK_A_SH_SZ",
                **_date_scope(_FIXTURE_BEGIN, 20200720),
            },
            lambda: provider.get_hist_code_list_exchange(
                "EXTRA_STOCK_A_SH_SZ", _FIXTURE_BEGIN, 20200720
            ),
        )
        run(
            "bj_mapping_endpoint",
            _symbol_scope(["430047.BJ"]),
            lambda: provider.get_bj_code_mapping_exchange(["430047.BJ"]),
        )
        run(
            "dividend_event_shape",
            {**_symbol_scope(_DIVIDEND_SYMBOLS), **_date_scope(_CA_BEGIN, _CA_END)},
            lambda: provider.get_dividend_exchange(
                _DIVIDEND_SYMBOLS, begin_date=_CA_BEGIN, end_date=_CA_END
            ),
        )
        run(
            "right_issue_event_shape",
            {**_symbol_scope(_RIGHT_ISSUE_SYMBOLS), **_date_scope(_CA_BEGIN, _CA_END)},
            lambda: provider.get_right_issue_exchange(
                _RIGHT_ISSUE_SYMBOLS, begin_date=_CA_BEGIN, end_date=_CA_END
            ),
        )
        run(
            "fixture_sz_calendar",
            {"market": "SZ"},
            lambda: provider.get_calendar_exchange("SZ"),
        )
        calendar = _calendar_days(payloads.get("fixture_sz_calendar"))
        fixture_days = [day for day in calendar if _FIXTURE_BEGIN <= day <= _FIXTURE_END]
        if fixture_days:
            run(
                "fixture_300104_daily_kline",
                {
                    **_symbol_scope(["300104.SZ"]),
                    **_date_scope(_FIXTURE_BEGIN, _FIXTURE_END),
                    "trading_day_count": len(fixture_days),
                    "trading_days_sha256": hashlib.sha256(
                        json.dumps(fixture_days, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                },
                lambda: provider.query_kline_exchange(
                    ["300104.SZ"],
                    begin_date=_FIXTURE_BEGIN,
                    end_date=_FIXTURE_END,
                    kline_type="DAY",
                    trading_days=fixture_days,
                ),
            )
            run(
                "fixture_600519_control_daily_kline",
                {
                    **_symbol_scope(["600519.SH"]),
                    **_date_scope(_FIXTURE_BEGIN, _FIXTURE_END),
                    "trading_day_count": len(fixture_days),
                },
                lambda: provider.query_kline_exchange(
                    ["600519.SH"],
                    begin_date=_FIXTURE_BEGIN,
                    end_date=_FIXTURE_END,
                    kline_type="DAY",
                    trading_days=fixture_days,
                ),
            )
        else:
            calls["fixture_300104_daily_kline"] = {
                "probe_id": "fixture_300104_daily_kline",
                "status": "SKIPPED",
                "error_code": "CALENDAR_WINDOW_EMPTY",
                "request": {
                    **_symbol_scope(["300104.SZ"]),
                    **_date_scope(_FIXTURE_BEGIN, _FIXTURE_END),
                },
            }
            calls["fixture_600519_control_daily_kline"] = {
                "probe_id": "fixture_600519_control_daily_kline",
                "status": "SKIPPED",
                "error_code": "CALENDAR_WINDOW_EMPTY",
                "request": {
                    **_symbol_scope(["600519.SH"]),
                    **_date_scope(_FIXTURE_BEGIN, _FIXTURE_END),
                },
            }

        closure = {
            "status_date_shape": _status_finding(calls["status_date_shape"]),
            "delisted_semantics": _basic_finding(calls["delisted_stock_basic"]),
            "bj_mapping_endpoint": _mapping_finding(calls["bj_mapping_endpoint"]),
            "bse_historical_status": _bse_finding(calls["bse_historical_status"]),
            "corporate_actions": {
                "dividend": _ca_finding(calls["dividend_event_shape"], "DATE_EX"),
                "right_issue": _ca_finding(calls["right_issue_event_shape"], "EX_DIVIDEND_DATE"),
            },
            "history_fixture_300104": _fixture_finding(
                calls["delisted_stock_basic"],
                calls["fixture_300104_history_code_list"],
                calls["fixture_300104_daily_kline"],
                calls["fixture_600519_control_daily_kline"],
                history_contains_target=_payload_contains_symbol(
                    payloads.get("fixture_300104_history_code_list"), "300104.SZ"
                ),
            ),
        }
        report = {
            "schema": "amazingdata.capability_closure_preflight.v1",
            "probe_mode": "TARGETED_NON_PRODUCTION",
            "checked_at": datetime.now(UTC).isoformat(),
            "code_head": args.code_head or None,
            "status": "COMPLETED",
            "formal_run_created": False,
            "catalog_mutated": False,
            "verdict_mutated": False,
            "account_profile_id": profile.account_profile_id,
            "sdk_version": identity.sdk_version,
            "runtime_version": identity.tgw_runtime_version,
            "calls": list(calls.values()),
            "capability_closure": closure,
            "open_semantics": [
                (
                    "delisted continuity still requires reconciliation of stock-basic "
                    "status with historical code-list semantics"
                ),
                (
                    "835185.BJ empty/non-empty result does not by itself establish "
                    "historical listing status"
                ),
                "300104.SZ provider bars do not replace independent listing/applicability evidence",
                "no result here approves a Production capability or authorizes a new Formal run",
            ],
        }
    except ProviderError as exc:
        report = _empty_report(code_head=args.code_head)
        report["status"] = "ERROR"
        report["error_code"] = safe_error_code(exc)
        report["calls"] = list(calls.values())
        return_code = 1
    except Exception:  # noqa: BLE001 - never emit raw SDK text
        report = _empty_report(code_head=args.code_head)
        report["status"] = "ERROR"
        report["error_code"] = "UNEXPECTED_ERROR"
        report["calls"] = list(calls.values())
        return_code = 1
    else:
        return_code = 0
    finally:
        session.logout()

    _emit(report, args.output)
    return return_code


def _emit(report: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    sys.exit(main())
