"""Disposable synthetic minute-layout benchmark for Issue #79 (A1).

The runner is deliberately a single script, not a benchmark framework.  It
generates deterministic synthetic minute bars, compares the three approved
layout candidates (L0/L1/L2) and the three physical security-key candidates,
and records resource/scan observations.  It never imports the provider
layer, reads credentials, or consumes retained provider payloads.

The synthetic numeric types are benchmark placeholders only.  A0 provider
precision/unit semantics remain open until a separately authorized provider
shape probe.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import resource as _resource
except ImportError:  # pragma: no cover - Windows does not ship resource.
    _resource = None

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


UTC = timezone.utc
BASE_DATE = date(2024, 1, 2)
MONTH_LABEL = "2024-01"
LAYOUTS = ("L0", "L1", "L2")
KEY_REPRESENTATIONS = ("uuid_string", "fixed16", "int64")
BUCKET_COUNT = 16
COMPRESSION = "zstd"
ROW_GROUP_SIZE = 65_536


def emit(stage: str, **values: Any) -> None:
    print(json.dumps({"stage": stage, **values}, sort_keys=True, default=str), flush=True)


def current_rss_bytes() -> int:
    """Return current process working-set/RSS without a third-party monitor."""

    if os.name == "nt":
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
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        process = get_current_process()
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MemoryCounters),
            ctypes.c_ulong,
        ]
        get_process_memory_info.restype = ctypes.c_int
        ok = get_process_memory_info(process, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize) if ok else 0

    # Linux/macOS resource reports KiB on Linux and bytes on macOS.
    if _resource is None:
        return 0
    value = int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform.startswith("linux") else value


def directory_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def file_inventory(root: Path) -> dict[str, tuple[int, str]]:
    inventory: dict[str, tuple[int, str]] = {}
    if not root.exists():
        return inventory
    for path in root.rglob("*"):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            inventory[str(path.relative_to(root))] = (path.stat().st_size, digest)
    return inventory


def file_count(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


class PeakSampler:
    def __init__(self, spill_root: Path) -> None:
        self.spill_root = spill_root
        self.peak_rss = 0
        self.peak_spill = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak_rss = max(self.peak_rss, current_rss_bytes())
            self.peak_spill = max(self.peak_spill, directory_bytes(self.spill_root))
            self._stop.wait(0.05)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.peak_rss = max(self.peak_rss, current_rss_bytes())
        self.peak_spill = max(self.peak_spill, directory_bytes(self.spill_root))


@dataclass
class Metric:
    name: str
    elapsed_seconds: float
    cpu_seconds: float
    peak_rss_bytes: int
    spill_peak_bytes: int
    bytes_written: int
    files_written: int
    rows: int = 0
    files_available: int | None = None
    row_groups_available: int | None = None
    files_with_matching_rows: int | None = None
    row_groups_touched: int | None = None
    bytes_read_estimate: int | None = None
    notes: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["peak_rss_gib"] = round(self.peak_rss_bytes / 1024**3, 4)
        payload["spill_peak_gib"] = round(self.spill_peak_bytes / 1024**3, 4)
        payload["bytes_written_mib"] = round(self.bytes_written / 1024**2, 3)
        payload["bytes_read_estimate_mib"] = (
            None
            if self.bytes_read_estimate is None
            else round(self.bytes_read_estimate / 1024**2, 3)
        )
        return payload


def measure(
    name: str,
    output_root: Path,
    spill_root: Path,
    operation: Callable[[], Any],
) -> tuple[Any, Metric]:
    output_root.mkdir(parents=True, exist_ok=True)
    spill_root.mkdir(parents=True, exist_ok=True)
    before_bytes = directory_bytes(output_root)
    before_files = file_count(output_root)
    sampler = PeakSampler(spill_root)
    cpu_start = time.process_time()
    started = time.monotonic()
    sampler.start()
    try:
        value = operation()
    finally:
        sampler.stop()
    metric = Metric(
        name=name,
        elapsed_seconds=round(time.monotonic() - started, 4),
        cpu_seconds=round(time.process_time() - cpu_start, 4),
        peak_rss_bytes=sampler.peak_rss,
        spill_peak_bytes=sampler.peak_spill,
        bytes_written=max(0, directory_bytes(output_root) - before_bytes),
        files_written=max(0, file_count(output_root) - before_files),
        notes=[],
    )
    return value, metric


def key_value(rep: str, ordinal: int) -> str | bytes | int:
    if rep == "uuid_string":
        return f"00000000-0000-0000-0000-{ordinal:012d}"
    if rep == "fixed16":
        return ordinal.to_bytes(16, "big")
    if rep == "int64":
        return ordinal + 1
    raise ValueError(f"unknown key representation: {rep}")


def key_type(rep: str) -> pa.DataType:
    if rep == "uuid_string":
        return pa.string()
    if rep == "fixed16":
        return pa.binary(16)
    if rep == "int64":
        return pa.int64()
    raise ValueError(rep)


def key_literal(rep: str, ordinal: int) -> str:
    value = key_value(rep, ordinal)
    if rep == "uuid_string":
        assert isinstance(value, str)
        return "'" + value.replace("'", "''") + "'"
    if rep == "fixed16":
        assert isinstance(value, bytes)
        return f"from_hex('{value.hex()}')"
    return str(value)


def _bar_time_us(day_index: int, minute_index: int) -> int:
    dt = datetime.combine(BASE_DATE + timedelta(days=day_index), datetime.min.time(), tzinfo=UTC)
    return int((dt + timedelta(minutes=minute_index)).timestamp() * 1_000_000)


def make_batch(
    *,
    rep: str,
    day_index: int,
    minute_count: int,
    security_start: int,
    security_stop: int,
    order: str,
) -> pa.Table:
    securities = list(range(security_start, security_stop))
    ordered_securities: list[int] = []
    ordered_minutes: list[int] = []
    if order == "time_first":
        for minute in range(minute_count):
            ordered_securities.extend(securities)
            ordered_minutes.extend([minute] * len(securities))
    elif order == "security_first":
        for ordinal in securities:
            ordered_securities.extend([ordinal] * minute_count)
            ordered_minutes.extend(range(minute_count))
    else:
        raise ValueError(order)

    dates = [BASE_DATE + timedelta(days=day_index)] * len(ordered_securities)
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[int] = []
    amounts: list[int] = []
    for ordinal, minute in zip(ordered_securities, ordered_minutes, strict=True):
        opening = 50.0 + (ordinal % 1000) * 0.01 + day_index * 0.1 + minute * 0.001
        close = opening + ((ordinal + minute) % 17 - 8) * 0.002
        volume = ((ordinal * 37 + minute * 13 + day_index) % 100_000) * 100
        opens.append(opening)
        highs.append(max(opening, close) + 0.01)
        lows.append(min(opening, close) - 0.01)
        closes.append(close)
        volumes.append(volume)
        amounts.append(int(round(close * volume)))

    return pa.table(
        {
            "security_key": pa.array(
                [key_value(rep, ordinal) for ordinal in ordered_securities], type=key_type(rep)
            ),
            "bar_time": pa.array(
                [_bar_time_us(day_index, minute) for minute in ordered_minutes],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "trade_date": pa.array(dates, type=pa.date32()),
            "open": pa.array(opens, type=pa.float64()),
            "high": pa.array(highs, type=pa.float64()),
            "low": pa.array(lows, type=pa.float64()),
            "close": pa.array(closes, type=pa.float64()),
            "volume": pa.array(volumes, type=pa.int64()),
            "amount": pa.array(amounts, type=pa.int64()),
        }
    )


def _write_table(writer: pq.ParquetWriter | None, path: Path, table: pa.Table) -> pq.ParquetWriter:
    if writer is None:
        writer = pq.ParquetWriter(path, table.schema, compression=COMPRESSION, use_dictionary=True)
    writer.write_table(table, row_group_size=ROW_GROUP_SIZE)
    return writer


def write_day(
    *,
    root: Path,
    rep: str,
    layout: str,
    day_index: int,
    security_count: int,
    minute_count: int,
    chunk_securities: int,
    emit_progress: bool = False,
    started_event: threading.Event | None = None,
) -> int:
    day_root = root / f"day={day_index:02d}"
    day_root.mkdir(parents=True, exist_ok=True)
    order = "security_first" if layout == "L2" else "time_first"
    writers: dict[int | None, pq.ParquetWriter] = {}
    rows = 0
    try:
        for security_start in range(0, security_count, chunk_securities):
            security_stop = min(security_count, security_start + chunk_securities)
            table = make_batch(
                rep=rep,
                day_index=day_index,
                minute_count=minute_count,
                security_start=security_start,
                security_stop=security_stop,
                order=order,
            )
            if started_event is not None and not started_event.is_set():
                started_event.set()
            if layout == "L0":
                path = day_root / "bars.parquet"
                writers[None] = _write_table(writers.get(None), path, table)
                rows += table.num_rows
            else:
                ordinals = list(range(security_start, security_stop))
                ordered = []
                if order == "time_first":
                    for _minute in range(minute_count):
                        ordered.extend(ordinals)
                else:
                    for ordinal in ordinals:
                        ordered.extend([ordinal] * minute_count)
                buckets: dict[int, list[int]] = {bucket: [] for bucket in range(BUCKET_COUNT)}
                for index, ordinal in enumerate(ordered):
                    buckets[ordinal % BUCKET_COUNT].append(index)
                for bucket, indices in buckets.items():
                    if not indices:
                        continue
                    bucket_table = table.take(pa.array(indices, type=pa.int64()))
                    path = day_root / f"bucket={bucket:02d}.parquet"
                    writers[bucket] = _write_table(writers.get(bucket), path, bucket_table)
                    rows += bucket_table.num_rows
            if emit_progress:
                emit(
                    "WRITE_CHUNK",
                    rep=rep,
                    layout=layout,
                    day=day_index,
                    rows=rows,
                )
    finally:
        for writer in writers.values():
            writer.close()
    return rows


def write_month(
    *,
    root: Path,
    rep: str,
    layout: str,
    days: int,
    security_count: int,
    minute_count: int,
    chunk_securities: int,
) -> tuple[int, list[Metric]]:
    metrics: list[Metric] = []
    total_rows = 0
    month_root = root / "fragments" / f"month={MONTH_LABEL}"
    for day_index in range(days):
        day_root = month_root / f"day={day_index:02d}"
        rows, metric = measure(
            f"daily_shape_day_{day_index:02d}",
            root,
            root / "spill",
            lambda day_root=day_root, day_index=day_index: write_day(
                root=month_root,
                rep=rep,
                layout=layout,
                day_index=day_index,
                security_count=security_count,
                minute_count=minute_count,
                chunk_securities=chunk_securities,
                emit_progress=False,
            ),
        )
        total_rows += int(rows)
        metric.rows = int(rows)
        metrics.append(metric)
        emit("WRITE_DAY", rep=rep, layout=layout, day=day_index, rows=rows)
    return total_rows, metrics


def fragment_files(month_root: Path) -> list[Path]:
    return sorted(path for path in month_root.rglob("*.parquet") if path.is_file())


def parquet_row_groups(files: list[Path]) -> int:
    return sum(pq.ParquetFile(path).metadata.num_row_groups for path in files)


def compact_files(
    *,
    files: list[Path],
    layout: str,
    destination: Path,
    started_event: threading.Event | None = None,
) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    writers: dict[str, pq.ParquetWriter] = {}
    rows = 0
    try:
        for source in files:
            if layout == "L0":
                key = "all"
                output = destination / "month.parquet"
            else:
                match = re.search(r"bucket=(\d{2})\.parquet$", source.name)
                if match is None:
                    raise RuntimeError(f"cannot identify bucket from {source}")
                key = match.group(1)
                output = destination / f"bucket={key}.parquet"
            parquet = pq.ParquetFile(source)
            for batch in parquet.iter_batches(batch_size=ROW_GROUP_SIZE):
                if started_event is not None and not started_event.is_set():
                    started_event.set()
                table = pa.Table.from_batches([batch])
                writers[key] = _write_table(writers.get(key), output, table)
                rows += table.num_rows
    finally:
        for writer in writers.values():
            writer.close()
    return rows


def make_closed_history(root: Path, history_case: str, month_count: int) -> None:
    target = root / "closed_history" / history_case
    target.mkdir(parents=True, exist_ok=True)
    for month_index in range(month_count):
        path = target / f"closed_month={month_index:02d}.json"
        if not path.exists():
            path.write_text(
                json.dumps(
                    {
                        "logical_partition_id": f"security_bar_1m/closed/{month_index:02d}",
                        "logical_content_hash": hashlib.sha256(
                            f"closed-{month_index}".encode("utf-8")
                        ).hexdigest(),
                        "immutable": True,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )


def run_daily_append(
    *,
    root: Path,
    rep: str,
    layout: str,
    history_case: str,
    security_count: int,
    minute_count: int,
    chunk_securities: int,
) -> Metric:
    make_closed_history(root, history_case, 1 if history_case == "short" else 72)
    closed_root = root / "closed_history" / history_case
    before = file_inventory(closed_root)
    append_root = root / "daily_append" / history_case / f"month={MONTH_LABEL}"
    rows, metric = measure(
        f"daily_ingest_{history_case}",
        root,
        root / "spill",
        lambda: write_day(
            root=append_root,
            rep=rep,
            layout=layout,
            day_index=20,
            security_count=security_count,
            minute_count=minute_count,
            chunk_securities=chunk_securities,
        ),
    )
    metric.rows = rows
    metric.notes = [
        f"closed_months_rewritten={before != file_inventory(closed_root)}",
        f"closed_month_count={1 if history_case == 'short' else 72}",
    ]
    return metric


def run_catchup(
    *,
    root: Path,
    rep: str,
    layout: str,
    security_count: int,
    minute_count: int,
    chunk_securities: int,
) -> Metric:
    catchup_root = root / "catchup" / f"month={MONTH_LABEL}"

    def operation() -> int:
        total = 0
        for day_index in range(20, 25):
            total += write_day(
                root=catchup_root,
                rep=rep,
                layout=layout,
                day_index=day_index,
                security_count=security_count,
                minute_count=minute_count,
                chunk_securities=chunk_securities,
            )
        return total

    rows, metric = measure("five_day_catchup", root, root / "spill", operation)
    metric.rows = rows
    return metric


def sql_source(files: list[Path]) -> str:
    quoted = ",".join("'" + path.resolve().as_posix().replace("'", "''") + "'" for path in files)
    return f"read_parquet([{quoted}], union_by_name=true, filename=true)"


def _profile_numbers(profile_path: Path) -> dict[str, int]:
    if not profile_path.is_file():
        return {}
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found: dict[str, int] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower().replace("_", " ")
                if isinstance(child, (int, float)) and "file" in normalized and "read" in normalized:
                    found[str(key)] = int(child)
                if isinstance(child, (int, float)) and "row" in normalized and "group" in normalized:
                    found[str(key)] = int(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def run_query(
    *,
    root: Path,
    name: str,
    files: list[Path],
    sql_tail: str,
    identity_table: pa.Table | None = None,
) -> Metric:
    if not files:
        raise RuntimeError(f"no parquet files for {name}")
    spill = root / "query_spill" / name
    profile = root / "profiles" / f"{name}.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    source = sql_source(files)
    candidate_bytes = sum(path.stat().st_size for path in files)
    candidate_row_groups = parquet_row_groups(files)
    result_holder: dict[str, Any] = {}

    def operation() -> None:
        conn = duckdb.connect()
        try:
            conn.execute("SET memory_limit='1GB'")
            conn.execute("SET threads=2")
            conn.execute("SET temp_directory = ?", [str(spill.resolve())])
            conn.execute("PRAGMA enable_profiling='json'")
            conn.execute(
                "PRAGMA profiling_output='" + str(profile.resolve()).replace("'", "''") + "'"
            )
            if identity_table is not None:
                conn.register("identity_dim", identity_table)
            row = conn.execute(sql_tail.format(source=source)).fetchone()
            result_holder["row"] = tuple(row or ())
        finally:
            conn.close()

    _unused, metric = measure(name, root, spill, operation)
    row = result_holder.get("row", ())
    metric.files_available = len(files)
    metric.row_groups_available = candidate_row_groups
    metric.bytes_read_estimate = candidate_bytes
    if len(row) >= 2 and isinstance(row[1], (int, float)):
        metric.files_with_matching_rows = int(row[1])
    profile_numbers = _profile_numbers(profile)
    for key, value in profile_numbers.items():
        normalized = key.lower().replace("_", " ")
        if "file" in normalized and "read" in normalized:
            metric.files_with_matching_rows = value
        if "row" in normalized and "group" in normalized:
            metric.row_groups_touched = value
    metric.notes = [
        "bytes_read_estimate is the candidate Parquet byte set, not a kernel I/O counter",
        "files_with_matching_rows is a query observation; row-group touch count is reported only when DuckDB profiling exposes it",
    ]
    return metric


def run_queries(root: Path, rep: str, layout: str, files: list[Path], security_count: int) -> list[Metric]:
    identity_keys = [key_value(rep, ordinal) for ordinal in range(security_count)]
    identity_table = pa.table(
        {
            "security_key": pa.array(identity_keys, type=key_type(rep)),
            "governance_security_id": pa.array(
                [f"security-{ordinal:08d}" for ordinal in range(security_count)],
                type=pa.string(),
            ),
            "sector_id": pa.array([ordinal % 32 for ordinal in range(security_count)], type=pa.int16()),
        }
    )
    one_key = key_literal(rep, min(1234, security_count - 1))
    keys_100 = ",".join(key_literal(rep, ordinal) for ordinal in range(min(100, security_count)))
    keys_500 = ",".join(key_literal(rep, ordinal) for ordinal in range(min(500, security_count)))
    query_day = BASE_DATE + timedelta(days=10)
    query_minute = datetime.combine(query_day, datetime.min.time(), tzinfo=UTC) + timedelta(minutes=120)
    query_start = query_minute.isoformat().replace("+00:00", "+00")
    query_end = (query_minute + timedelta(minutes=1)).isoformat().replace("+00:00", "+00")
    queries = [
        (
            "W4_full_market_one_minute",
            "SELECT count(*), count(DISTINCT filename), avg(close) FROM {source} "
            f"WHERE bar_time >= TIMESTAMPTZ '{query_start}' AND bar_time < TIMESTAMPTZ '{query_end}'",
            None,
        ),
        (
            "W5_one_security_history",
            f"SELECT count(*), count(DISTINCT filename) FROM {{source}} WHERE security_key = {one_key}",
            None,
        ),
        (
            "W6_100_security_range",
            f"SELECT count(*), count(DISTINCT filename) FROM {{source}} WHERE security_key IN ({keys_100})",
            None,
        ),
        (
            "W6_500_security_range",
            f"SELECT count(*), count(DISTINCT filename) FROM {{source}} WHERE security_key IN ({keys_500})",
            None,
        ),
        (
            "W7_resample_rolling_groupby",
            "SELECT count(*), sum(group_files) FROM ("
            "SELECT security_key, avg(close) AS avg_close, count(DISTINCT filename) AS group_files "
            "FROM {source} GROUP BY security_key)",
            None,
        ),
        (
            "W8_identity_join",
            "SELECT count(*), count(DISTINCT b.filename) FROM {source} b "
            "JOIN identity_dim i ON b.security_key = i.security_key",
            identity_table,
        ),
    ]
    metrics: list[Metric] = []
    for name, sql, table in queries:
        metric = run_query(
            root=root,
            name=name,
            files=files,
            sql_tail=sql,
            identity_table=table,
        )
        metrics.append(metric)
        emit("QUERY", rep=rep, layout=layout, workload=name, metric=metric.as_dict())
    return metrics


def run_concurrent_query(
    *, root: Path, rep: str, layout: str, files: list[Path], security_count: int
) -> dict[str, Any]:
    source_day = [path for path in files if "day=00" in str(path)]
    if not source_day:
        raise RuntimeError("cannot select an open day for concurrent compaction")
    started_event = threading.Event()
    destination = root / "concurrent_compaction" / "month=2024-01"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            compact_files,
            files=source_day,
            layout=layout,
            destination=destination,
            started_event=started_event,
        )
        if not started_event.wait(timeout=30):
            raise RuntimeError("compaction did not start within 30 seconds")
        overlap_observed = not future.done()
        metric = run_query(
            root=root,
            name="W9_query_while_compaction_active",
            files=files,
            sql_tail=(
                "SELECT count(*), count(DISTINCT filename) FROM {source} "
                "WHERE bar_time >= TIMESTAMPTZ '2024-01-12T02:00:00+00' "
                "AND bar_time < TIMESTAMPTZ '2024-01-12T02:01:00+00'"
            ),
        )
        compacted_rows = future.result()
    metric.notes = (metric.notes or []) + [
        f"overlap_observed={overlap_observed}",
        f"concurrent_compaction_rows={compacted_rows}",
        "concurrent compaction targets an open-day copy; source fragments remain immutable",
    ]
    emit("QUERY_CONCURRENT", rep=rep, layout=layout, metric=metric.as_dict())
    return {"metric": metric.as_dict(), "overlap_observed": overlap_observed}


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# A1 synthetic minute-layout benchmark",
        "",
        f"- Status: **{result['status']}**",
        f"- Resource gates: **{result['resource_gate_status']}**",
        "- Source: synthetic deterministic data only; `provider_calls=0`.",
        f"- Shape: {result['shape']['rows_per_day']:,} rows/day × {result['shape']['days']} days = {result['shape']['rows_per_month']:,} rows/open-month.",
        "- Candidate layouts: L0 month/time-first; L1 month + 16 buckets/time-first; L2 month + 16 buckets/security-first.",
        "- Candidate physical keys: UUID string, fixed 16-byte binary, INT64.",
        "- Synthetic numeric columns are placeholders; A0 numeric/provider-unit contract remains open.",
        "",
        "## Resource gate summary",
        "",
        "| key | layout | daily peak GiB | compaction peak GiB | short/long daily ratio | closed rewrite |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in result["configs"]:
        daily = item["daily_ingest"]
        daily_peak = max(float(m["peak_rss_gib"]) for m in daily)
        compaction = item["month_compaction"]
        short = next(m for m in daily if m["name"] == "daily_ingest_short")
        long = next(m for m in daily if m["name"] == "daily_ingest_long")
        ratio = max(short["elapsed_seconds"], long["elapsed_seconds"]) / max(
            0.0001, min(short["elapsed_seconds"], long["elapsed_seconds"])
        )
        rewritten = any("closed_months_rewritten=True" in note for m in daily for note in (m.get("notes") or []))
        lines.append(
            f"| {item['key_representation']} | {item['layout']} | {daily_peak:.3f} | "
            f"{compaction['peak_rss_gib']:.3f} | {ratio:.2f} | {'YES' if rewritten else '0'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The result is evidence for A1 layout selection, not a provider numeric or minute-semantic approval."
            " `files_with_matching_rows` is a query observation and `bytes_read_estimate` is the candidate"
            " Parquet byte set; exact kernel I/O counters are not claimed. A human/PM decision is still required"
            " before freezing the physical layout and starting the daily vertical refactor.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shape = {
        "security_count": args.security_count,
        "minutes_per_day": args.minutes_per_day,
        "days": args.days,
        "rows_per_day": args.security_count * args.minutes_per_day,
        "rows_per_month": args.security_count * args.minutes_per_day * args.days,
    }
    result: dict[str, Any] = {
        "schema": "issue79.a1.synthetic_minute_layout.v1",
        "status": "REVIEW",
        "source": {"kind": "SYNTHETIC_ONLY", "provider_calls": 0},
        "shape": shape,
        "candidate_layouts": list(LAYOUTS),
        "candidate_key_representations": list(KEY_REPRESENTATIONS),
        "configs": [],
        "gates": {
            "daily_peak_rss_gib_target": 2.0,
            "month_compaction_peak_rss_gib_target": 4.0,
            "daily_append_history_ratio_tolerance": 1.25,
            "closed_months_rewritten": 0,
            "snapshot_readmodel_full_fact_copies": 0,
        },
    }
    for rep in KEY_REPRESENTATIONS:
        for layout in LAYOUTS:
            config_root = output / f"key={rep}__layout={layout}"
            emit("CONFIG_START", key_representation=rep, layout=layout)
            total_rows, day_metrics = write_month(
                root=config_root,
                rep=rep,
                layout=layout,
                days=args.days,
                security_count=args.security_count,
                minute_count=args.minutes_per_day,
                chunk_securities=args.chunk_securities,
            )
            month_root = config_root / "fragments" / f"month={MONTH_LABEL}"
            files = fragment_files(month_root)
            compaction_rows, compaction_metric = measure(
                "month_compaction",
                config_root,
                config_root / "spill",
                lambda: compact_files(
                    files=files,
                    layout=layout,
                    destination=config_root / "compacted" / f"month={MONTH_LABEL}",
                ),
            )
            compaction_metric.rows = compaction_rows
            daily_metrics = [
                run_daily_append(
                    root=config_root,
                    rep=rep,
                    layout=layout,
                    history_case=case,
                    security_count=args.security_count,
                    minute_count=args.minutes_per_day,
                    chunk_securities=args.chunk_securities,
                ).as_dict()
                for case in ("short", "long")
            ]
            catchup_metric = run_catchup(
                root=config_root,
                rep=rep,
                layout=layout,
                security_count=args.security_count,
                minute_count=args.minutes_per_day,
                chunk_securities=args.chunk_securities,
            )
            query_metrics = [
                metric.as_dict()
                for metric in run_queries(
                    config_root, rep, layout, files, args.security_count
                )
            ]
            concurrent = run_concurrent_query(
                root=config_root,
                rep=rep,
                layout=layout,
                files=files,
                security_count=args.security_count,
            )
            item = {
                "key_representation": rep,
                "layout": layout,
                "rows": total_rows,
                "daily_shape_metrics": [metric.as_dict() for metric in day_metrics],
                "daily_ingest": daily_metrics,
                "five_day_catchup": catchup_metric.as_dict(),
                "month_compaction": compaction_metric.as_dict(),
                "queries": query_metrics,
                "concurrent_query": concurrent,
                "fact_copy_count_snapshot_readmodel": 0,
                "fragment_file_count": len(files),
                "fragment_row_group_count": parquet_row_groups(files),
            }
            result["configs"].append(item)
            emit("CONFIG_COMPLETE", key_representation=rep, layout=layout, rows=total_rows)
    result["resource_gate_status"] = "PASS" if _passes_resource_gates(result) else "FAIL"
    # A1 is not complete merely because the resource thresholds pass.  A
    # human/PM decision must still freeze the physical layout and key
    # representation before the daily vertical refactor is authorized.
    result["status"] = "REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION"
    (output / "benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "benchmark.md").write_text(markdown_report(result), encoding="utf-8")
    return result


def _passes_resource_gates(result: dict[str, Any]) -> bool:
    for item in result["configs"]:
        if any(
            metric["peak_rss_gib"] >= result["gates"]["daily_peak_rss_gib_target"]
            for metric in item["daily_ingest"]
        ):
            return False
        if item["month_compaction"]["peak_rss_gib"] >= result["gates"]["month_compaction_peak_rss_gib_target"]:
            return False
        if item["fact_copy_count_snapshot_readmodel"] != 0:
            return False
        if any("closed_months_rewritten=True" in note for metric in item["daily_ingest"] for note in (metric.get("notes") or [])):
            return False
        short = next(m for m in item["daily_ingest"] if m["name"] == "daily_ingest_short")
        long = next(m for m in item["daily_ingest"] if m["name"] == "daily_ingest_long")
        ratio = max(short["elapsed_seconds"], long["elapsed_seconds"]) / max(
            0.0001, min(short["elapsed_seconds"], long["elapsed_seconds"])
        )
        if ratio > result["gates"]["daily_append_history_ratio_tolerance"]:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--security-count", type=int, default=4_500)
    parser.add_argument("--minutes-per-day", type=int, default=240)
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--chunk-securities", type=int, default=250)
    args = parser.parse_args()
    result = run(args)
    emit("BENCHMARK_COMPLETE", status=result["status"], output=str(Path(args.output).resolve()))
    return 0 if result["resource_gate_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

