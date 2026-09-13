"""Run the bounded CR-7 authoritative-history source preflight.

This script is deliberately narrower than a historical build.  It calls the
reviewed AmazingData history surface for exactly three representative months,
uses one daily-bar sentinel per month, and writes raw exchanges only below an
ignored local directory.  The committed report never contains credentials,
account profiles, endpoint values, symbols, or raw provider payloads.

Provider success is not completeness evidence.  AmazingData's reviewed
surface returns observations and shapes, but the current source contract does
not provide an upstream inventory/range statement that proves a complete
monthly daily-bar universe.  Therefore this preflight records that exact
blocker and never manufactures an authoritative coverage-basis sidecar.

The three windows are constants by design:

* Development: 2020-01
* Validation A: 2024-01
* Holdout: 2026-01

No command-line date, universe, resume, verdict, or production option is
provided by this bounded probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ashare_state.providers.amazingdata.provider import AmazingDataProvider, ProviderUseMode
from ashare_state.providers.amazingdata.safe_diagnostics import safe_error_code
from ashare_state.providers.amazingdata.sdk_loader import probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.research.historical import (
    AUTHORITATIVE_SOURCE_METHODS,
    AUTHORITATIVE_SOURCE_SELECTION_VERSION,
    AuthoritativeSourceSelection,
)
from ashare_state.storage.raw_writer import RawWriter, RawWriteResult

_ENV_KEYS = (
    "TGW_USERNAME",
    "TGW_PASSWORD",
    "TGW_SERVER_VIP",
    "TGW_SERVER_PORT",
)
_SCHEMA = "cr7.authoritative_history_preflight.v1"
_RAW_INGEST_ID = "cr7-authoritative-history-preflight-20260913"
_SECURITY_TYPE = "EXTRA_STOCK_A_SH_SZ"
_SENTINEL_SYMBOL = "600519.SH"
_SOURCE_CONTRACT_RELATIVE = Path(
    "docs/provider_verification/source_selection_retrieval_closure_20260912.json"
)
_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("development", 2020, 1),
    ("validation_a", 2024, 1),
    ("holdout", 2026, 1),
)

_COMPLETENESS_BLOCKER = {
    "code": "UPSTREAM_COMPLETENESS_STATEMENT_MISSING",
    "status": "BLOCKED",
    "required_evidence": (
        "an upstream inventory/range statement or equivalent auditable source evidence "
        "that explicitly asserts complete daily_bar coverage for the inclusive month "
        "and its historical availability/PIT semantics"
    ),
    "insufficient_substitutes": [
        "successful SDK or HTTP response",
        "returned historical code-list count or hash",
        "returned calendar count or hash",
        "one sentinel security's daily-bar row count or date continuity",
    ],
    "effect": "do_not_emit_authoritative_coverage_basis",
}


def _load_env(path: Path) -> dict[str, str]:
    """Load only TGW variables without printing or persisting their values."""
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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _hash_json(value: Any) -> str:
    return _sha256_bytes(_json_bytes(value))


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return start, date.fromordinal(next_month.toordinal() - 1)


def _yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _scope_hash(values: list[Any]) -> str:
    return _hash_json(values)


def _month_scope(split: str, year: int, month: int) -> dict[str, Any]:
    start, end = _month_bounds(year, month)
    return {
        "split": split,
        "year": year,
        "month": month,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "window_inclusive": True,
    }


def _exchange_summary(exchange: ProviderExchange) -> dict[str, Any]:
    envelope = exchange.envelope
    return {
        "request_id": str(getattr(envelope, "request_id", "")),
        "status": str(getattr(envelope, "status", "")),
        "operation_id": str(getattr(envelope, "operation_id", "")),
        "normalization_surface": str(getattr(envelope, "normalization_surface", "")),
        "request_params_hash": str(getattr(envelope, "request_params_hash", "")),
        "row_count": int(getattr(envelope, "row_count", 0) or 0),
        "attempt_count": int(getattr(envelope, "attempt_count", 0) or 0),
    }


def _raw_summary(result: RawWriteResult) -> dict[str, Any]:
    return {
        "status": "PERSISTED_LOCAL_IGNORED_ONLY",
        "evidence_hash": result.evidence_hash,
        "payload_kind": result.payload_kind,
        "row_count": result.row_count,
        "payload_artifact_count": len(result.payload_artifacts),
        "payload_artifact_hashes": [artifact.content_hash for artifact in result.payload_artifacts],
        "null_table_count": len(result.null_tables),
    }


def _call(
    *,
    method: str,
    fn: Callable[[], ProviderExchange],
    writer: RawWriter,
) -> tuple[dict[str, Any], Any | None]:
    """Run one exchange and return a sanitized record plus successful payload."""
    record: dict[str, Any] = {"method": method}
    exchange: ProviderExchange | None = None
    try:
        exchange = fn()
    except ProviderError as exc:
        record["error_code"] = safe_error_code(exc)
        exchange = exc.exchange
    except Exception:  # noqa: BLE001 - fixed taxonomy is the only report output
        record["error_code"] = "UNEXPECTED_ERROR"

    if exchange is None:
        record["status"] = "ERROR"
        record["raw_persist"] = "NOT_AVAILABLE"
        return record, None

    record.update({"exchange": _exchange_summary(exchange)})
    record["status"] = record["exchange"]["status"]
    try:
        persisted = writer.write(exchange)
    except Exception:  # noqa: BLE001 - persistence outcome is explicit below
        record["raw_persist"] = "RAW_WRITER_ERROR"
    else:
        record["raw_persist"] = _raw_summary(persisted)
    if record["status"] == "OK":
        return record, exchange.payload
    return record, None


def _as_string_list(payload: Any) -> list[str] | None:
    if not isinstance(payload, list) or any(not isinstance(value, str) for value in payload):
        return None
    return [value.strip() for value in payload if value.strip()]


def _code_list_summary(payload: Any) -> dict[str, Any]:
    values = _as_string_list(payload)
    if values is None:
        return {"shape": type(payload).__name__, "status": "UNEXPECTED_SHAPE"}
    normalized = sorted(set(values))
    return {
        "shape": "list[str]",
        "status": "OK",
        "security_count": len(normalized),
        "security_set_sha256": _scope_hash(normalized),
    }


def _as_calendar_days(payload: Any) -> list[int] | None:
    if not isinstance(payload, list):
        return None
    days: list[int] = []
    for value in payload:
        if isinstance(value, bool):
            return None
        try:
            day = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if len(str(day)) != 8:
            return None
        days.append(day)
    return sorted(set(days))


def _calendar_summary(payload: Any, *, begin: int, end: int) -> tuple[dict[str, Any], list[int]]:
    days = _as_calendar_days(payload)
    if days is None:
        return {"shape": type(payload).__name__, "status": "UNEXPECTED_SHAPE"}, []
    window_days = [day for day in days if begin <= day <= end]
    return (
        {
            "shape": "list[int]",
            "status": "OK",
            "calendar_day_count": len(days),
            "calendar_days_sha256": _scope_hash(days),
            "window_trading_day_count": len(window_days),
            "window_trading_days_sha256": _scope_hash(window_days),
        },
        window_days,
    )


def _frame_summary(value: Any) -> dict[str, Any] | None:
    columns = getattr(value, "columns", None)
    if columns is None:
        return None
    shape = getattr(value, "shape", None)
    if isinstance(shape, tuple) and shape and isinstance(shape[0], int):
        row_count = shape[0]
    else:
        try:
            row_count = len(value)
        except TypeError:
            return None
    names = sorted(str(column) for column in columns)
    return {"row_count": int(row_count), "columns": names}


def _kline_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"shape": type(payload).__name__, "status": "UNEXPECTED_SHAPE"}
    table_summaries: list[dict[str, Any]] = []
    null_count = 0
    for key, value in payload.items():
        if value is None:
            null_count += 1
            continue
        summary = _frame_summary(value)
        if summary is None:
            return {
                "shape": "dict[str, unknown]",
                "status": "UNEXPECTED_MEMBER_SHAPE",
                "null_table_count": null_count,
            }
        table_summaries.append(
            {
                "member_key_sha256": _scope_hash([str(key)]),
                **summary,
            }
        )
    table_summaries.sort(key=lambda item: item["member_key_sha256"])
    return {
        "shape": "dict[str, dataframe|None]",
        "status": "OK",
        "member_count": len(payload),
        "null_table_count": null_count,
        "non_null_table_count": len(table_summaries),
        "table_summaries_sha256": _hash_json(table_summaries),
        "non_null_row_count": sum(item["row_count"] for item in table_summaries),
    }


def _not_run_month(split: str, year: int, month: int, reason: str) -> dict[str, Any]:
    return {
        **_month_scope(split, year, month),
        "status": "NOT_RUN",
        "reason": reason,
        "authoritative_completeness": dict(_COMPLETENESS_BLOCKER),
        "materializer_gate": {
            "status": "NOT_ENTERED_FAIL_CLOSED",
            "reason": "no_verified_authoritative_basis_can_be_constructed",
        },
    }


def _source_contract_info(repo_root: Path) -> dict[str, Any]:
    path = repo_root / _SOURCE_CONTRACT_RELATIVE
    if not path.is_file():
        return {
            "path": _SOURCE_CONTRACT_RELATIVE.as_posix(),
            "status": "MISSING_LOCAL_CONTRACT",
        }
    content = path.read_bytes()
    return {
        "path": _SOURCE_CONTRACT_RELATIVE.as_posix(),
        "status": "READ",
        "sha256": _sha256_bytes(content),
    }


def _base_report(*, code_head: str | None, repo_root: Path) -> dict[str, Any]:
    selection = AuthoritativeSourceSelection.reviewed_amazingdata_history()
    return {
        "schema": _SCHEMA,
        "preflight_mode": "TARGETED_NON_PRODUCTION_SPIKE",
        "checked_at": datetime.now(UTC).isoformat(),
        "code_head": code_head or None,
        "scope": [_month_scope(split, year, month) for split, year, month in _WINDOWS],
        "source_selection": {
            "selection_version": AUTHORITATIVE_SOURCE_SELECTION_VERSION,
            "source_class": selection.source_class,
            "provider": selection.provider,
            "retrieval_surface": selection.retrieval_surface,
            "methods": list(AUTHORITATIVE_SOURCE_METHODS),
            "source_domain": selection.source_domain,
            "selection_fingerprint": selection.selection_fingerprint,
        },
        "source_contract": _source_contract_info(repo_root),
        "authorization_boundary": {
            "provider_use_mode": ProviderUseMode.SPIKE.value,
            "formal_run_created": False,
            "production_activity": False,
            "catalog_mutated": False,
            "verdict_mutated": False,
            "broad_backfill": False,
            "universe_sweep": False,
        },
        "months": [],
        "authoritative_evidence": {
            "status": "NOT_PRODUCED",
            "reason": dict(_COMPLETENESS_BLOCKER),
        },
        "materializer": {
            "status": "NOT_ENTERED_FAIL_CLOSED",
            "reason": (
                "provider observations cannot substitute for a verified CR-4 projection "
                "and authoritative completeness basis"
            ),
        },
        "preflight_verdict": "FAIL_CLOSED_BLOCKED",
    }


def _run_month(
    provider: AmazingDataProvider,
    writer: RawWriter,
    *,
    split: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    start, end = _month_bounds(year, month)
    begin = _yyyymmdd(start)
    finish = _yyyymmdd(end)
    record: dict[str, Any] = {
        **_month_scope(split, year, month),
        "status": "COMPLETED_SOURCE_OBSERVATION",
        "calls": [],
    }

    calendar_record, calendar_payload = _call(
        method="BaseData.get_calendar",
        fn=lambda: provider.get_calendar_exchange("SH"),
        writer=writer,
    )
    record["calls"].append(calendar_record)
    calendar_summary, trading_days = _calendar_summary(
        calendar_payload,
        begin=begin,
        end=finish,
    )
    record["calendar"] = calendar_summary

    code_record, code_payload = _call(
        method="BaseData.get_hist_code_list",
        fn=lambda: provider.get_hist_code_list_exchange(_SECURITY_TYPE, begin, finish),
        writer=writer,
    )
    record["calls"].append(code_record)
    record["historical_code_list"] = (
        _code_list_summary(code_payload)
        if code_payload is not None
        else {"status": "NOT_AVAILABLE"}
    )

    if trading_days:
        kline_record, kline_payload = _call(
            method="MarketData.query_kline",
            fn=lambda: provider.query_kline_exchange(
                [_SENTINEL_SYMBOL],
                begin_date=begin,
                end_date=finish,
                kline_type="DAY",
                trading_days=trading_days,
            ),
            writer=writer,
        )
        record["calls"].append(kline_record)
        record["sentinel_daily_bar"] = (
            _kline_summary(kline_payload)
            if kline_payload is not None
            else {"status": "NOT_AVAILABLE"}
        )
    else:
        record["sentinel_daily_bar"] = {
            "status": "NOT_RUN",
            "reason": "calendar_window_empty_or_calendar_shape_invalid",
        }

    record["authoritative_completeness"] = dict(_COMPLETENESS_BLOCKER)
    record["materializer_gate"] = {
        "status": "NOT_ENTERED_FAIL_CLOSED",
        "reason": "no_verified_authoritative_basis_can_be_constructed",
    }
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description="run the fixed three-month CR-7 non-Production source preflight"
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/spike/cr7-authoritative-history-preflight-20260913/raw"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--code-head",
        default="",
        help="source commit being exercised; recorded in the sanitized receipt",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    report = _base_report(code_head=args.code_head, repo_root=repo_root)
    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        report["provider_access"] = {
            "status": "NOT_TESTABLE_MISSING_CREDENTIAL_ENV",
            "error_code": "MISSING_TGW_ENV",
        }
        report["months"] = [
            _not_run_month(split, year, month, "MISSING_TGW_ENV") for split, year, month in _WINDOWS
        ]
        _emit(report, args.output)
        return 2

    session = AmazingDataSession(*credentials)
    writer = RawWriter(args.raw_root, ingest_run_id=_RAW_INGEST_ID)
    try:
        try:
            session.login()
            identity = probe_identity(require_sdk=True)
        except ProviderError as exc:
            report["provider_access"] = {
                "status": "BLOCKED",
                "error_code": safe_error_code(exc),
            }
            report["months"] = [
                _not_run_month(split, year, month, "PROVIDER_ACCESS_BLOCKED")
                for split, year, month in _WINDOWS
            ]
            _emit(report, args.output)
            return 1
        except Exception:  # noqa: BLE001 - never emit SDK text
            report["provider_access"] = {
                "status": "BLOCKED",
                "error_code": "UNEXPECTED_ERROR",
            }
            report["months"] = [
                _not_run_month(split, year, month, "PROVIDER_ACCESS_BLOCKED")
                for split, year, month in _WINDOWS
            ]
            _emit(report, args.output)
            return 1

        if identity is None:
            report["provider_access"] = {
                "status": "BLOCKED",
                "error_code": "RUNTIME_IDENTITY_UNAVAILABLE",
            }
            report["months"] = [
                _not_run_month(split, year, month, "RUNTIME_IDENTITY_UNAVAILABLE")
                for split, year, month in _WINDOWS
            ]
            _emit(report, args.output)
            return 1

        report["provider_access"] = {
            "status": "AUTHENTICATED_RUNTIME_READY",
            "sdk_version": identity.sdk_version,
            "runtime_version": identity.tgw_runtime_version,
        }
        provider = AmazingDataProvider(
            session,
            identity=identity,
            budget=TimeBudget(query_timeout_seconds=90.0, connect_timeout_seconds=20.0),
            retry=RetryPolicy(max_retries=0),
            use_mode=ProviderUseMode.SPIKE,
        )
        report["months"] = [
            _run_month(provider, writer, split=split, year=year, month=month)
            for split, year, month in _WINDOWS
        ]
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
