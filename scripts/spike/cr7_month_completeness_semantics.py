"""Run the bounded CR-7 Stage A month-completeness diagnostic.

The command is intentionally fixed to ``2024-01``.  It exercises the typed
AmazingData provider facade with a SPIKE-mode session, persists successful
exchanges below an ignored local raw root, and emits only counts,
classifications, and hashes.  It does not create a formal run, issue an
authoritative receipt, or enter the historical materializer: the reviewed
source-selection closure is not an in-memory CR-4 source snapshot.

Stage B (2020-01 and 2026-01) is available only through this command's
explicit ``--stage-b`` mode, which requires a sanitized Stage A ``PASS``
evaluation using the current semantics versions.
There is deliberately no free-form date/universe/resume/production option.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import duckdb

from ashare_state.providers.amazingdata.authoritative_history import (
    _validate_calendar,
    _validate_security_universe,
)
from ashare_state.providers.amazingdata.month_completeness import (
    AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION,
    AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION,
    evaluate_month_completeness,
)
from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.amazingdata.safe_diagnostics import safe_error_code
from ashare_state.providers.amazingdata.sdk_loader import probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget
from ashare_state.providers.errors import ProviderError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.research.historical import (
    AMAZINGDATA_CALENDAR_MARKET,
    AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
    AUTHORITATIVE_SOURCE_METHODS,
    AUTHORITATIVE_SOURCE_SELECTION_VERSION,
)
from ashare_state.research.models import canonical_json, sha256_hex
from ashare_state.storage import apply_migrations
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter
from ashare_state.storage.raw_writer import RawWriteResult

_ENV_KEYS = (
    "TGW_USERNAME",
    "TGW_PASSWORD",
    "TGW_SERVER_VIP",
    "TGW_SERVER_PORT",
)
_SCHEMA = "cr7.month_completeness_semantics.v1"
_RAW_INGEST_ID = "cr7-month-completeness-semantics-stage-a-20260914"
_START = date(2024, 1, 1)
_END = date(2024, 1, 31)
_STAGE = "A"
_STAGE_B_MONTHS = (
    ("2020-01", date(2020, 1, 1), date(2020, 1, 31), "DEVELOPMENT"),
    ("2026-01", date(2026, 1, 1), date(2026, 1, 31), "HOLDOUT"),
)
_STAGE_B_WORKER_TIMEOUT_SECONDS = 900
_BLOCKED_EXIT_CODE = 2
_STAGE_A_SCHEMA = "cr7.month_completeness_semantics.v1"
_STAGE_B_SCHEMA = "cr7.month_completeness_semantics.stage-b.v1"
_STAGE_A_REPORT = Path("docs/provider_verification/cr7_month_completeness_stage_a_20260914.json")
_SOURCE_CONTRACT = Path(
    "docs/provider_verification/source_selection_retrieval_closure_20260912.json"
)


def _load_env(path: Path) -> dict[str, str]:
    """Load only the four local TGW variables without logging their values."""
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


def _yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _hash_json(value: Any) -> str:
    return sha256_hex(canonical_json(value))


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
    return value if value else None


def _source_contract(repo_root: Path) -> dict[str, Any]:
    path = repo_root / _SOURCE_CONTRACT
    if not path.is_file():
        return {"path": _SOURCE_CONTRACT.as_posix(), "status": "MISSING"}
    return {
        "path": _SOURCE_CONTRACT.as_posix(),
        "status": "READ",
        "sha256": sha256_hex(path.read_bytes()),
    }


def _frame_values(frame: Any, name: str) -> list[Any]:
    try:
        column = frame.get_column(name) if hasattr(frame, "get_column") else frame[name]
        if hasattr(column, "to_list"):
            values = column.to_list()
        elif hasattr(column, "tolist"):
            values = column.tolist()
        elif hasattr(column, "to_pylist"):
            values = column.to_pylist()
        else:
            values = list(column)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("provider frame column is unreadable") from exc
    return list(values)


def _frame_row_count(frame: Any) -> int:
    shape = getattr(frame, "shape", None)
    if isinstance(shape, tuple) and shape and isinstance(shape[0], int):
        return int(shape[0])
    try:
        return len(frame)
    except TypeError as exc:
        raise ValueError("provider frame shape is unreadable") from exc


def _persisted_summary(result: RawWriteResult) -> dict[str, Any]:
    schema = sorted((table.name, table.schema_hash) for table in result.tables)
    return {
        "status": "PERSISTED_LOCAL_IGNORED_ONLY",
        "row_count": result.row_count,
        "table_count": len(result.tables),
        "null_table_count": len(result.null_tables),
        "content_hash": result.content_hash,
        "evidence_hash": result.evidence_hash,
        "schema_hash": _hash_json(schema),
    }


def _call(
    *,
    method: str,
    fn: Callable[[], ProviderExchange],
    writer: AnchoredRawEvidenceWriter,
) -> tuple[dict[str, Any], Any | None]:
    """Run and persist one exchange, returning no provider text."""
    try:
        exchange = fn()
    except ProviderError as exc:
        return {
            "method": method,
            "status": "ERROR",
            "error_code": safe_error_code(exc),
            "raw_persist": "NOT_AVAILABLE",
        }, None
    except Exception:  # noqa: BLE001 - report uses a fixed taxonomy only
        return {
            "method": method,
            "status": "ERROR",
            "error_code": "UNEXPECTED_ERROR",
            "raw_persist": "NOT_AVAILABLE",
        }, None
    if not isinstance(exchange, ProviderExchange):
        return {
            "method": method,
            "status": "ERROR",
            "error_code": "EXCHANGE_SHAPE_INVALID",
            "raw_persist": "NOT_AVAILABLE",
        }, None
    envelope = exchange.envelope
    status = str(getattr(envelope, "status", ""))
    record: dict[str, Any] = {
        "method": method,
        "status": status,
        "row_count": int(getattr(envelope, "row_count", 0) or 0),
        "request_params_hash": str(getattr(envelope, "request_params_hash", "")),
    }
    if status != "OK":
        record["raw_persist"] = "NOT_AVAILABLE_NON_OK_EXCHANGE"
        return record, None
    try:
        persisted = writer.write_exchange(exchange)
    except Exception:  # noqa: BLE001 - raw retention is an explicit gate
        record["raw_persist"] = "RAW_WRITER_ERROR"
        return record, None
    record["raw_persist"] = _persisted_summary(persisted)
    return record, exchange.payload


def _payload_shape_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"shape": type(payload).__name__, "status": "UNEXPECTED_SHAPE"}
    row_counts: list[int] = []
    null_count = 0
    schema_hashes: list[str] = []
    for value in payload.values():
        if value is None:
            null_count += 1
            continue
        try:
            row_counts.append(_frame_row_count(value))
            schema_hashes.append(_hash_json(sorted((str(column),) for column in value.columns)))
        except (AttributeError, TypeError, ValueError):
            return {"shape": "dict[str,unknown]", "status": "UNEXPECTED_MEMBER_SHAPE"}
    return {
        "shape": "dict[str,dataframe|None]",
        "status": "OK",
        "member_count": len(payload),
        "null_table_count": null_count,
        "non_null_table_count": len(row_counts),
        "non_null_row_count": sum(row_counts),
        "row_count_histogram": dict(sorted(Counter(row_counts).items())),
        "schema_set_hash": _hash_json(sorted(schema_hashes)),
    }


def _status_summary(payload: Any) -> dict[str, Any]:
    summary = _payload_shape_summary(payload)
    if summary.get("status") != "OK" or not isinstance(payload, Mapping):
        return summary
    flag_counts: Counter[str] = Counter()
    unreadable_table_count = 0
    for frame in payload.values():
        if frame is None:
            continue
        if "IS_SUSP_SEC" not in {str(column) for column in frame.columns}:
            unreadable_table_count += 1
            continue
        try:
            flag_counts.update(str(value) for value in _frame_values(frame, "IS_SUSP_SEC"))
        except ValueError:
            unreadable_table_count += 1
    return {
        **summary,
        "suspension_flag_counts": dict(sorted(flag_counts.items())),
        "flag_unreadable_table_count": unreadable_table_count,
    }


def _exact_universe_summary(
    universes: Mapping[int, list[str]],
) -> dict[str, Any]:
    counts = [len(values) for values in universes.values()]
    return {
        "session_request_count": len(universes),
        "session_security_count_histogram": dict(sorted(Counter(counts).items())),
        "session_result_set_hash": _hash_json(
            [
                [day, sha256_hex(canonical_json(sorted(values)))]
                for day, values in sorted(universes.items())
            ]
        ),
    }


def _stage_a_gate(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("STAGE_A_REPORT_MISSING")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("STAGE_A_REPORT_UNREADABLE") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("STAGE_A_REPORT_SHAPE_INVALID")
    if payload.get("schema") != _STAGE_A_SCHEMA or payload.get("stage") != "A":
        raise ValueError("STAGE_A_REPORT_IDENTITY_MISMATCH")
    scope = payload.get("scope")
    if not isinstance(scope, Mapping) or scope.get("month") != "2024-01":
        raise ValueError("STAGE_A_REPORT_SCOPE_MISMATCH")
    month = payload.get("month")
    if not isinstance(month, Mapping) and isinstance(payload.get("evaluation"), Mapping):
        # The checked-in sanitized report is flattened; the live Stage A
        # command nests the same evaluation under ``month``.
        month = {"evaluation": payload["evaluation"]}
    if not isinstance(month, Mapping):
        raise ValueError("STAGE_A_MONTH_RESULT_MISSING")
    evaluation = month.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise ValueError("STAGE_A_EVALUATION_MISSING")
    if evaluation.get("status") != "PASS":
        raise ValueError("STAGE_A_EVALUATION_NOT_ACCEPTED")
    rule_version = evaluation.get("rule_version")
    applicability_version = evaluation.get("applicability_semantics_version")
    if not isinstance(rule_version, str) or not isinstance(applicability_version, str):
        raise ValueError("STAGE_A_RULE_VERSION_MISSING")
    if rule_version != AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION:
        raise ValueError("STAGE_A_RULE_VERSION_MISMATCH")
    if applicability_version != AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION:
        raise ValueError("STAGE_A_APPLICABILITY_VERSION_MISMATCH")
    code_head = payload.get("code_head")
    if not isinstance(code_head, str) or not code_head:
        raise ValueError("STAGE_A_CODE_HEAD_MISSING")
    return {
        "status": "ACCEPTED_FOR_STAGE_B_BOUNDARY",
        "path": path.as_posix(),
        "sha256": sha256_hex(path.read_bytes()),
        "code_head": code_head,
        "evaluation_status": evaluation["status"],
        "rule_version": rule_version,
        "applicability_semantics_version": applicability_version,
    }


def _stage_b_blocked_months(reason: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for month, start, end, role in _STAGE_B_MONTHS:
        result = _blocked_month(reason, calls=[], stage="B", start=start, end=end)
        result["month_id"] = month
        result["partition"] = role
        results.append(result)
    return results


def _stage_b_spec(month_id: str) -> tuple[date, date, str]:
    for candidate, start, end, role in _STAGE_B_MONTHS:
        if candidate == month_id:
            return start, end, role
    raise ValueError("STAGE_B_MONTH_NOT_AUTHORIZED")


def _blocked_month(
    reason: str,
    *,
    calls: list[dict[str, Any]],
    stage: str,
    start: date,
    end: date,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "scope": {
            "month": start.strftime("%Y-%m"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "inclusive": True,
        },
        "status": "FAIL_CLOSED",
        "reason_code": reason,
        "calls": calls,
        "materializer_gate": {
            "status": "NOT_ENTERED_FAIL_CLOSED",
            "reason_code": "NO_ACCEPTED_MONTH_COMPLETENESS_EVALUATION",
        },
        "authoritative_receipt": {
            "status": "NOT_PRODUCED_FAIL_CLOSED",
            "reason_code": "VERIFIED_SOURCE_SNAPSHOT_NOT_SUPPLIED_TO_BOUNDED_SPIKE",
        },
    }


def _run_month(
    provider: AmazingDataProvider,
    writer: AnchoredRawEvidenceWriter,
    *,
    start: date,
    end: date,
    stage: str,
) -> dict[str, Any]:
    begin = _yyyymmdd(start)
    finish = _yyyymmdd(end)
    calls: list[dict[str, Any]] = []

    calendar_record, calendar_payload = _call(
        method="BaseData.get_calendar",
        fn=lambda: provider.get_calendar_exchange(AMAZINGDATA_CALENDAR_MARKET),
        writer=writer,
    )
    calls.append(calendar_record)
    if calendar_payload is None:
        return _blocked_month(
            "CALENDAR_EXCHANGE_UNAVAILABLE",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )
    try:
        trading_days = _validate_calendar(calendar_payload, start=start, end=end)
    except Exception:  # noqa: BLE001 - exact validator output is not emitted
        return _blocked_month(
            "CALENDAR_VALIDATION_FAILED",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )

    code_record, code_payload = _call(
        method="BaseData.get_hist_code_list",
        fn=lambda: provider.get_hist_code_list_exchange(
            AMAZINGDATA_SECURITY_UNIVERSE_SELECTION, begin, finish
        ),
        writer=writer,
    )
    calls.append(code_record)
    if code_payload is None:
        return _blocked_month(
            "MONTH_UNIVERSE_EXCHANGE_UNAVAILABLE",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )
    try:
        monthly_symbols = _validate_security_universe(code_payload)
    except Exception:  # noqa: BLE001 - exact validator output is not emitted
        return _blocked_month(
            "MONTH_UNIVERSE_VALIDATION_FAILED",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )

    status_record, status_payload = _call(
        method="InfoData.get_history_stock_status",
        fn=lambda: provider.get_history_stock_status_exchange(begin, finish, monthly_symbols),
        writer=writer,
    )
    calls.append(status_record)
    if status_payload is None:
        return _blocked_month(
            "STATUS_EXCHANGE_UNAVAILABLE",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )

    exact_day_universes: dict[int, list[str]] = {}
    exact_calls: list[dict[str, Any]] = []
    for trading_day in trading_days:

        def exact_session_exchange(
            start_day: int = trading_day,
            end_day: int = trading_day,
        ) -> ProviderExchange:
            return cast(
                ProviderExchange,
                provider.get_hist_code_list_exchange(
                    AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
                    start_day,
                    end_day,
                ),
            )

        exact_record, exact_payload = _call(
            method="BaseData.get_hist_code_list",
            fn=exact_session_exchange,
            writer=writer,
        )
        exact_calls.append(exact_record)
        if exact_payload is None:
            return _blocked_month(
                "EXACT_SESSION_UNIVERSE_EXCHANGE_UNAVAILABLE",
                calls=calls + exact_calls,
                stage=stage,
                start=start,
                end=end,
            )
        try:
            exact_day_universes[trading_day] = _validate_security_universe(exact_payload)
        except Exception:  # noqa: BLE001 - exact validator output is not emitted
            return _blocked_month(
                "EXACT_SESSION_UNIVERSE_VALIDATION_FAILED",
                calls=calls + exact_calls,
                stage=stage,
                start=start,
                end=end,
            )

    daily_record, daily_payload = _call(
        method="MarketData.query_kline",
        fn=lambda: provider.query_kline_exchange(
            monthly_symbols,
            begin_date=begin,
            end_date=finish,
            kline_type="DAY",
            trading_days=trading_days,
        ),
        writer=writer,
    )
    calls.extend(exact_calls)
    calls.append(daily_record)
    if daily_payload is None:
        return _blocked_month(
            "DAILY_BAR_EXCHANGE_UNAVAILABLE",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )

    try:
        evaluation = evaluate_month_completeness(
            monthly_symbols=monthly_symbols,
            trading_days=trading_days,
            exact_day_universes=exact_day_universes,
            status_payload=status_payload,
            daily_bar_payload=daily_payload,
        )
    except Exception:  # noqa: BLE001 - semantic failure is represented below
        return _blocked_month(
            "MONTH_COMPLETENESS_EVALUATION_FAILED",
            calls=calls,
            stage=stage,
            start=start,
            end=end,
        )

    return {
        "stage": stage,
        "scope": {
            "month": start.strftime("%Y-%m"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "inclusive": True,
        },
        "status": "PASS" if evaluation.accepted else "FAIL_CLOSED",
        "rule_version": AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION,
        "applicability_semantics_version": AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION,
        "calendar": {
            "session_count": len(trading_days),
            "session_set_hash": _hash_json(trading_days),
        },
        "monthly_universe": {
            "security_count": len(monthly_symbols),
            "security_set_hash": _hash_json(monthly_symbols),
        },
        "exact_session_universes": _exact_universe_summary(exact_day_universes),
        "status_observation": _status_summary(status_payload),
        "daily_bar_observation": _payload_shape_summary(daily_payload),
        "evaluation": evaluation.as_dict(),
        "calls": calls,
        "authoritative_receipt": {
            "status": "NOT_PRODUCED_FAIL_CLOSED",
            "reason_code": "VERIFIED_SOURCE_SNAPSHOT_NOT_SUPPLIED_TO_BOUNDED_SPIKE",
            "source_selection_closure": "CLOSURE_DESIGN_ONLY_NOT_ACTIVE",
        },
        "materializer_gate": {
            "status": "NOT_ENTERED_FAIL_CLOSED",
            "reason_code": "NO_AUTHORITATIVE_RECEIPT_ISSUED",
        },
    }


def _run_stage_a(
    provider: AmazingDataProvider,
    writer: AnchoredRawEvidenceWriter,
) -> dict[str, Any]:
    return _run_month(provider, writer, start=_START, end=_END, stage=_STAGE)


def _base_report(
    *,
    repo_root: Path,
    code_head: str | None,
    stage: str,
    stage_a_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": _SCHEMA if stage == "A" else _STAGE_B_SCHEMA,
        "checked_at": datetime.now(UTC).isoformat(),
        "code_head": code_head,
        "stage": stage,
        "provider_use_mode": ProviderUseMode.SPIKE.value,
        "source_selection": {
            "selection_version": AUTHORITATIVE_SOURCE_SELECTION_VERSION,
            "provider": "amazingdata",
            "methods": list(AUTHORITATIVE_SOURCE_METHODS),
        },
        "source_contract": _source_contract(repo_root),
        "authorization_boundary": {
            "formal_run_created": False,
            "production_activity": False,
            "broad_backfill": False,
            "stage_b_started": stage == "B",
        },
    }
    if stage == "A":
        report["scope"] = {
            "month": "2024-01",
            "start": _START.isoformat(),
            "end": _END.isoformat(),
        }
    else:
        report["scope"] = {
            "months": [month for month, _start, _end, _role in _STAGE_B_MONTHS],
            "bounded": True,
        }
    if stage_a_gate is not None:
        report["stage_a_gate"] = dict(stage_a_gate)
    return report


def _stage_b_worker_report(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    month_id: str,
    stage_a_gate: Mapping[str, Any],
) -> int:
    start, end, role = _stage_b_spec(month_id)
    report = _base_report(
        repo_root=repo_root,
        code_head=args.code_head or _git_head(repo_root),
        stage="B",
        stage_a_gate=stage_a_gate,
    )
    report["scope"] = {
        "month": month_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "inclusive": True,
        "process_isolated": True,
    }
    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        report.update(
            {
                "status": "FAIL_CLOSED",
                "provider_access": {"status": "NOT_TESTABLE", "reason_code": "MISSING_TGW_ENV"},
                "month": {
                    **_blocked_month(
                        "MISSING_TGW_ENV",
                        calls=[],
                        stage="B",
                        start=start,
                        end=end,
                    ),
                    "month_id": month_id,
                    "partition": role,
                },
            }
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE

    raw_root = (
        args.raw_root
        or Path("data/spike/cr7-month-completeness-semantics-stage-b-20260914")
        / f"month={month_id}"
        / "raw"
    )
    db_path = (
        args.db_path
        or Path("data/spike/cr7-month-completeness-semantics-stage-b-20260914")
        / f"month={month_id}"
        / "anchors.duckdb"
    )
    raw_root.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    apply_migrations(conn, repo_root / "migrations")
    session = AmazingDataSession(*credentials)
    try:
        try:
            session.login()
            identity = probe_identity(require_sdk=True)
        except ProviderError as exc:
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "provider_access": {"status": "BLOCKED", "reason_code": safe_error_code(exc)},
                    "month": {
                        **_blocked_month(
                            "PROVIDER_ACCESS_BLOCKED",
                            calls=[],
                            stage="B",
                            start=start,
                            end=end,
                        ),
                        "month_id": month_id,
                        "partition": role,
                    },
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        except Exception:  # noqa: BLE001 - no SDK text in report
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "provider_access": {"status": "BLOCKED", "reason_code": "UNEXPECTED_ERROR"},
                    "month": {
                        **_blocked_month(
                            "PROVIDER_ACCESS_BLOCKED",
                            calls=[],
                            stage="B",
                            start=start,
                            end=end,
                        ),
                        "month_id": month_id,
                        "partition": role,
                    },
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        if identity is None:
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "provider_access": {
                        "status": "BLOCKED",
                        "reason_code": "RUNTIME_IDENTITY_UNAVAILABLE",
                    },
                    "month": {
                        **_blocked_month(
                            "RUNTIME_IDENTITY_UNAVAILABLE",
                            calls=[],
                            stage="B",
                            start=start,
                            end=end,
                        ),
                        "month_id": month_id,
                        "partition": role,
                    },
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
            budget=TimeBudget(query_timeout_seconds=600.0, connect_timeout_seconds=20.0),
            retry=RetryPolicy(max_retries=0),
            use_mode=ProviderUseMode.SPIKE,
        )
        writer = AnchoredRawEvidenceWriter(
            conn,
            raw_root,
            ingest_run_id=f"cr7-month-completeness-semantics-stage-b-20260914-{month_id}",
        )
        try:
            month = _run_month(provider, writer, start=start, end=end, stage="B")
        except Exception:  # noqa: BLE001 - sanitize any month-level blocker
            month = _blocked_month(
                "MONTH_DIAGNOSTIC_UNEXPECTED_ERROR",
                calls=[],
                stage="B",
                start=start,
                end=end,
            )
        month["month_id"] = month_id
        month["partition"] = role
        report["month"] = month
        report["status"] = "PASS" if month.get("status") == "PASS" else "FAIL_CLOSED"
        _emit(report, args.output)
        return 0 if report["status"] == "PASS" else _BLOCKED_EXIT_CODE
    finally:
        session.logout()
        conn.close()


def _run_stage_b_parent(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    stage_a_gate: Mapping[str, Any],
) -> int:
    report = _base_report(
        repo_root=repo_root,
        code_head=args.code_head or _git_head(repo_root),
        stage="B",
        stage_a_gate=stage_a_gate,
    )
    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        report.update(
            {
                "status": "FAIL_CLOSED",
                "provider_access": {"status": "NOT_TESTABLE", "reason_code": "MISSING_TGW_ENV"},
                "months": _stage_b_blocked_months("MISSING_TGW_ENV"),
            }
        )
        report["authorization_boundary"]["stage_b_started"] = False
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE

    raw_root = args.raw_root or Path("data/spike/cr7-month-completeness-semantics-stage-b-20260914")
    db_root = args.db_path.parent if args.db_path else raw_root
    raw_root.mkdir(parents=True, exist_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)
    report["worker_isolation"] = {
        "status": "PROCESS_ISOLATED",
        "timeout_seconds": _STAGE_B_WORKER_TIMEOUT_SECONDS,
        "timeout_is_process_boundary": True,
    }
    months: list[dict[str, Any]] = []
    worker_access: list[dict[str, Any]] = []
    for month_id, start, end, role in _STAGE_B_MONTHS:
        month_root = raw_root / f"month={month_id}" / "raw"
        month_root.mkdir(parents=True, exist_ok=True)
        worker_output = month_root.parent / f"worker-report-{os.getpid()}.json"
        worker_db = db_root / f"{month_id}.duckdb"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_stage-b-worker-month",
            month_id,
            "--env-file",
            str(args.env_file),
            "--stage-a-report",
            str(args.stage_a_report),
            "--raw-root",
            str(month_root),
            "--db-path",
            str(worker_db),
            "--output",
            str(worker_output),
            "--code-head",
            str(report.get("code_head") or ""),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=_STAGE_B_WORKER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            month = _blocked_month(
                "SDK_NATIVE_CALL_PROCESS_TIMEOUT",
                calls=[],
                stage="B",
                start=start,
                end=end,
            )
            month.update(
                {
                    "month_id": month_id,
                    "partition": role,
                    "worker": {
                        "status": "TIMEOUT",
                        "timeout_seconds": _STAGE_B_WORKER_TIMEOUT_SECONDS,
                    },
                }
            )
            months.append(month)
            continue
        if worker_output.is_file():
            try:
                worker_payload = json.loads(worker_output.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                worker_payload = None
            worker_month = (
                worker_payload.get("month") if isinstance(worker_payload, Mapping) else None
            )
            if isinstance(worker_month, Mapping) and worker_month.get("month_id") == month_id:
                month = dict(worker_month)
                month["worker"] = {
                    "status": "REPORT_WRITTEN",
                    "exit_code": completed.returncode,
                }
                months.append(month)
                access = worker_payload.get("provider_access")
                if isinstance(access, Mapping):
                    worker_access.append(
                        {
                            "month": month_id,
                            "status": access.get("status"),
                            "sdk_version": access.get("sdk_version"),
                            "runtime_version": access.get("runtime_version"),
                        }
                    )
                continue
        month = _blocked_month(
            "STAGE_B_WORKER_REPORT_MISSING",
            calls=[],
            stage="B",
            start=start,
            end=end,
        )
        month.update(
            {
                "month_id": month_id,
                "partition": role,
                "worker": {
                    "status": "NO_SANITIZED_REPORT",
                    "exit_code": completed.returncode,
                },
            }
        )
        months.append(month)
    report["months"] = months
    report["provider_access"] = {
        "status": "PROCESS_ISOLATED_WORKERS",
        "workers": worker_access,
    }
    report["status"] = (
        "PASS" if all(item.get("status") == "PASS" for item in months) else "FAIL_CLOSED"
    )
    _emit(report, args.output)
    return 0 if report["status"] == "PASS" else _BLOCKED_EXIT_CODE


def _emit(report: Mapping[str, Any], output: Path | None) -> None:
    serialized = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def _blocked_for_stage(stage: str, reason: str) -> dict[str, Any]:
    if stage == "A":
        return {
            "month": _blocked_month(
                reason,
                calls=[],
                stage="A",
                start=_START,
                end=_END,
            )
        }
    return {"months": _stage_b_blocked_months(reason)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "run the fixed CR-7 Stage A 2024-01 diagnostic, or explicitly "
            "authorized Stage B 2020-01 and 2026-01 diagnostics"
        )
    )
    parser.add_argument(
        "--stage-b",
        action="store_true",
        help="run only the fixed Stage B months after the Stage A report gate",
    )
    parser.add_argument(
        "--_stage-b-worker-month",
        choices=[month for month, _start, _end, _role in _STAGE_B_MONTHS],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--stage-a-report", type=Path, default=_STAGE_A_REPORT)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--code-head", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    stage = "B" if args.stage_b or args._stage_b_worker_month else "A"
    stage_a_gate: dict[str, Any] | None = None
    if stage == "B":
        try:
            stage_a_gate = _stage_a_gate(args.stage_a_report)
        except ValueError as exc:
            report = _base_report(
                repo_root=repo_root,
                code_head=args.code_head or _git_head(repo_root),
                stage=stage,
            )
            report["authorization_boundary"]["stage_b_started"] = False
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "stage_a_gate": {"status": "BLOCKED", "reason_code": str(exc)},
                    **_blocked_for_stage(stage, "STAGE_A_GATE_BLOCKED"),
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE

    report = _base_report(
        repo_root=repo_root,
        code_head=args.code_head or _git_head(repo_root),
        stage=stage,
        stage_a_gate=stage_a_gate,
    )
    if args._stage_b_worker_month:
        if stage_a_gate is None:  # pragma: no cover - guarded above
            raise RuntimeError("Stage B worker started without the Stage A gate")
        return _stage_b_worker_report(
            args=args,
            repo_root=repo_root,
            month_id=args._stage_b_worker_month,
            stage_a_gate=stage_a_gate,
        )
    if stage == "B":
        if stage_a_gate is None:  # pragma: no cover - guarded above
            raise RuntimeError("Stage B started without the Stage A gate")
        return _run_stage_b_parent(
            args=args,
            repo_root=repo_root,
            stage_a_gate=stage_a_gate,
        )
    credentials = _credentials(_load_env(args.env_file))
    if credentials is None:
        report.update(
            {
                "status": "FAIL_CLOSED",
                "provider_access": {"status": "NOT_TESTABLE", "reason_code": "MISSING_TGW_ENV"},
                **_blocked_for_stage(stage, "MISSING_TGW_ENV"),
            }
        )
        _emit(report, args.output)
        return _BLOCKED_EXIT_CODE

    default_raw_root = (
        Path("data/spike/cr7-month-completeness-semantics-stage-a-20260914/raw")
        if stage == "A"
        else Path("data/spike/cr7-month-completeness-semantics-stage-b-20260914")
    )
    default_db_path = (
        Path("data/spike/cr7-month-completeness-semantics-stage-a-20260914/anchors.duckdb")
        if stage == "A"
        else Path("data/spike/cr7-month-completeness-semantics-stage-b-20260914/anchors.duckdb")
    )
    raw_root = args.raw_root or default_raw_root
    db_path = args.db_path or default_db_path
    raw_root.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    apply_migrations(conn, repo_root / "migrations")
    session = AmazingDataSession(*credentials)
    try:
        try:
            session.login()
            identity = probe_identity(require_sdk=True)
        except ProviderError as exc:
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "provider_access": {"status": "BLOCKED", "reason_code": safe_error_code(exc)},
                    **_blocked_for_stage(stage, "PROVIDER_ACCESS_BLOCKED"),
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        except Exception:  # noqa: BLE001 - no SDK text in report
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "provider_access": {"status": "BLOCKED", "reason_code": "UNEXPECTED_ERROR"},
                    **_blocked_for_stage(stage, "PROVIDER_ACCESS_BLOCKED"),
                }
            )
            _emit(report, args.output)
            return _BLOCKED_EXIT_CODE
        if identity is None:
            report.update(
                {
                    "status": "FAIL_CLOSED",
                    "provider_access": {
                        "status": "BLOCKED",
                        "reason_code": "RUNTIME_IDENTITY_UNAVAILABLE",
                    },
                    **_blocked_for_stage(stage, "RUNTIME_IDENTITY_UNAVAILABLE"),
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
            budget=TimeBudget(query_timeout_seconds=600.0, connect_timeout_seconds=20.0),
            retry=RetryPolicy(max_retries=0),
            use_mode=ProviderUseMode.SPIKE,
        )
        if stage == "A":
            writer = AnchoredRawEvidenceWriter(conn, raw_root, ingest_run_id=_RAW_INGEST_ID)
            month = _run_stage_a(provider, writer)
            report["month"] = month
            report["status"] = "PASS" if month.get("status") == "PASS" else "FAIL_CLOSED"
        _emit(report, args.output)
        return 0 if report["status"] == "PASS" else _BLOCKED_EXIT_CODE
    finally:
        session.logout()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
