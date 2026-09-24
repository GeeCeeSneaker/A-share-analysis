"""Offline, month-bounded Canonical migration from retained Issue #76 evidence.

The script never imports or calls a provider client. It copies only the
normalized-input tree and the CR-2 ledger into a separate output root, then
builds one month's Canonical truth at a time. The retained root is read-only.

Representative audit (seven high-value months):
    uv run python scripts/spike/issue76_c1_migrate.py \
      --source-root <retained-root> --output-root <isolated-audit-root>

Full migration after the representative audit passes:
    uv run python scripts/spike/issue76_c1_migrate.py \
      --source-root <retained-root> --output-root <isolated-migration-root> \
      --all-months --no-month-snapshots

The monthly snapshots are useful for representative contract testing only.
The full archive's single logical Snapshot is published by the archive-set
builder after all 78 monthly Canonical partitions have passed.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from ashare_state.canonical.canonicalizer import CanonicalRunner
from ashare_state.canonical.daily_bar import iter_daily_bar_partition_rows
from ashare_state.canonical.identity import approved_provider_identity_events
from ashare_state.canonical.verifier import (
    read_canonical_run_manifest,
    verify_canonical_run_for_consumption,
)
from ashare_state.readmodel.duckdb_model import DuckDBReadModel
from ashare_state.snapshot.builder import SnapshotBuilder
from ashare_state.snapshot.verifier import verify_snapshot

DEFAULT_AUDIT_MONTHS = (
    "2020-01",  # LISTDATE / pre-listing applicability
    "2020-02",  # DELISTDATE applicability
    "2023-01",  # approved suspension event begins
    "2023-02",  # approved suspension event crosses month boundary
    "2024-01",  # ordinary historical month
    "2025-02",  # approved provider-symbol transition
    "2026-01",  # latest retained month in the accepted sample
)
STATE_FILENAME = "c1_monthly_migration_state.json"
STATE_VERSION = "issue76-c1-monthly-migration-v1"
PROVIDER_TREE = "provider=amazingdata"
IDENTITY_LISTDATE_SUPPLEMENT = {
    "target_month": "2022-09",
    "source_month": "2023-02",
    "provider_dataset": "stock_basic",
    "request_id": "e0979f16-5c56-4fc9-bd66-1b934e30e771",
    "normalization_run_id": "e478b724-8040-52f2-99a2-d7c0de7b8f9c",
    "raw_file_sha256": "403e2d0444e6127d1ad97acc3060ad38bdaf2c0cc112997ab4424285749d13eb",
    "raw_evidence_hash": "79ebc807ac89b723ca948b13ae009f9028847476b73894f7dd67bf50b7f4cc8b",
    "normalized_manifest_uri": (
        "provider=amazingdata/dataset=stock_basic/"
        "raw_request=e0979f16-5c56-4fc9-bd66-1b934e30e771/contract=cr2.1-v1/"
        "run=e478b724-8040-52f2-99a2-d7c0de7b8f9c/manifest.json"
    ),
    "normalized_manifest_sha256": (
        "228110892e8d8976cd7f6ee6e284b2344ab8ba791df82a2ddb0840932f30c660"
    ),
    "normalized_output_uri": (
        "provider=amazingdata/dataset=stock_basic/"
        "raw_request=e0979f16-5c56-4fc9-bd66-1b934e30e771/contract=cr2.1-v1/"
        "run=e478b724-8040-52f2-99a2-d7c0de7b8f9c/main.parquet"
    ),
    "normalized_output_sha256": "65d8aceddcd10242f92cf85c947c8df5d7b21df97bc6f6c426ee7d6f136770d2",
    "source_vintage_as_of": "2026-09-18T00:44:51.537152+00:00",
    "request_code_count": 4926,
    "response_row_count": 4925,
    "fact_count": 1669,
    "fact_set_sha256": "5c30ab57cf47c9d72d47174f51f40869667788f995416b0e8f12e7ef8139eeb7",
    "scope_csv": "docs/project/ISSUE76_2022-09_IDENTITY_MISSING_PAIRS.csv",
    "scope_csv_sha256": "e21963940a2f6e7bd44a941a100419626ec681c4f0a418f442b77d3bc42a1e56",
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _list_date_text(value: Any) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        parsed = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    else:
        parsed = date.fromisoformat(text[:10])
    return parsed.isoformat()


def _identity_fact_set_hash(facts: dict[str, str]) -> str:
    payload = [{"provider_symbol": symbol, "list_date": facts[symbol]} for symbol in sorted(facts)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _project_supplemental_identity_rows(
    rows: tuple[tuple[tuple[str, Any], ...], ...],
    *,
    request_id: str,
    expected_facts: dict[str, str],
) -> tuple[tuple[tuple[str, Any], ...], ...]:
    """Expose only the authorized LISTDATE facts from one retained source run."""
    projected: list[tuple[tuple[str, Any], ...]] = []
    observed: dict[str, str] = {}
    for packed_row in rows:
        row = dict(packed_row)
        if str(row.get("raw_request") or "") != request_id:
            projected.append(packed_row)
            continue
        symbol = str(row.get("provider_symbol") or "").strip().upper()
        if symbol not in expected_facts:
            continue
        list_date = _list_date_text(row.get("list_date"))
        if list_date != expected_facts[symbol] or symbol in observed:
            raise RuntimeError(f"supplemental LISTDATE fact differs or repeats for {symbol}")
        observed[symbol] = list_date
        # Mutable stock_basic fields are deliberately not exposed to the bridge.
        projected.append(tuple(sorted({"provider_symbol": symbol, "list_date": list_date}.items())))
    if observed != expected_facts:
        raise RuntimeError(
            "supplemental retained LISTDATE source does not provide the exact approved symbol set"
        )
    return tuple(projected)


def _current_rss_bytes() -> int:
    if sys.platform == "win32":

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
        get_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MemoryCounters),
            ctypes.c_ulong,
        ]
        get_memory_info.restype = ctypes.c_int
        ok = get_memory_info(process, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize) if ok else 0
    if sys.platform.startswith("linux"):
        try:
            pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE")
        except OSError, ValueError, IndexError:
            return 0
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value * 1024 if sys.platform.startswith("linux") else value
    except ImportError, OSError, ValueError:
        return 0


class _PeakRssSampler:
    def __init__(self) -> None:
        self.peak = _current_rss_bytes()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, _current_rss_bytes())
            self._stop.wait(0.05)

    def __enter__(self) -> _PeakRssSampler:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.peak = max(self.peak, _current_rss_bytes())


def _month_range() -> tuple[str, ...]:
    output: list[str] = []
    year, month = 2020, 1
    while (year, month) <= (2026, 6):
        output.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return tuple(output)


def _safe_distinct_roots(source_root: Path, output_root: Path) -> None:
    source = source_root.resolve()
    output = output_root.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise RuntimeError(
            "source-root and output-root must be disjoint; retained data is read-only"
        )


def _tree_inventory(root: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if path.is_file():
            file_count += 1
            total_bytes += path.stat().st_size
    return file_count, total_bytes


def _source_fingerprint(source_root: Path) -> dict[str, str]:
    state_path = source_root / "execution_state.json"
    ledger_path = source_root / "ledger.duckdb"
    if not state_path.is_file() or not ledger_path.is_file():
        raise FileNotFoundError("retained root must contain execution_state.json and ledger.duckdb")
    return {
        "execution_state_sha256": _sha256_file(state_path),
        "source_ledger_sha256": _sha256_file(ledger_path),
    }


def _initialize_output(source_root: Path, output_root: Path) -> dict[str, Any]:
    """Create a clean derived-data root once; never clear or overwrite it."""
    _safe_distinct_roots(source_root, output_root)
    source_norm = source_root / "normalized"
    source_provider = source_norm / PROVIDER_TREE
    source_ledger = source_root / "ledger.duckdb"
    source_raw = source_root / "authoritative_capture"
    if not source_provider.is_dir() or not source_raw.is_dir():
        raise FileNotFoundError(
            "retained normalized provider or authoritative_capture tree is missing"
        )
    marker_path = output_root / STATE_FILENAME
    fingerprint = _source_fingerprint(source_root)

    if marker_path.is_file():
        state = json.loads(marker_path.read_text(encoding="utf-8"))
        if (
            state.get("state_version") != STATE_VERSION
            or state.get("source_root") != str(source_root.resolve())
            or state.get("source_fingerprint") != fingerprint
        ):
            raise RuntimeError("existing migration state does not match this retained source")
        if (
            not (output_root / "ledger.duckdb").is_file()
            or not (output_root / "normalized" / PROVIDER_TREE).is_dir()
        ):
            raise RuntimeError("migration output is incomplete; preserve it for inspection")
        return state

    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(
            "output-root is non-empty and has no migration marker; refusing to overwrite"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    normalized_root = output_root / "normalized"
    normalized_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_provider, normalized_root / PROVIDER_TREE)
    shutil.copy2(source_ledger, output_root / "ledger.duckdb")

    # This derived lane is intentionally rebuilt from verified CR-2 inputs.
    # Old Canonical/Snapshot rows refer to large pre-C1 artifacts that are
    # not copied into this isolated root; remove only those rows from the
    # copied ledger, never from the retained source ledger.
    conn = duckdb.connect(str(output_root / "ledger.duckdb"))
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM meta_snapshot_build")
        conn.execute("DELETE FROM meta_canonical_reconciliation_finding")
        conn.execute("DELETE FROM meta_canonicalization_run")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    provider_files, provider_bytes = _tree_inventory(normalized_root / PROVIDER_TREE)
    state = {
        "state_version": STATE_VERSION,
        "source_root": str(source_root.resolve()),
        "source_fingerprint": fingerprint,
        "normalized_input_copy": {"file_count": provider_files, "byte_count": provider_bytes},
        "provider_calls": 0,
        "provider_calls_scope": "this offline migration process only",
        "processed_months": {},
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    _atomic_json(marker_path, state)
    return state


def _load_month_run_ids(
    conn: Any,
    source_root: Path,
    output_root: Path,
    source_state: dict[str, Any],
    month: str,
) -> tuple[set[str], dict[str, str], datetime, dict[str, Any] | None]:
    try:
        month_state = source_state["months"][month]
    except KeyError as exc:
        raise RuntimeError(f"retained execution state has no month {month}") from exc
    if (
        month_state.get("status") != "PASS"
        or month_state.get("coverage") != "PASS"
        or month_state.get("retained_capture_replay") != "PASS"
        or int(month_state.get("unresolved_pair_count", -1)) != 0
        or int(month_state.get("missing_required_pair_count", -1)) != 0
        or int(month_state.get("extra_returned_pair_count", -1)) != 0
        or int(month_state.get("structural_error_count", -1)) != 0
    ):
        raise RuntimeError(f"retained month {month} is not a complete PASS; refusing migration")

    request_fields = {
        "daily_bar": "daily_bar_request_id",
        "hist_code_list": "hist_code_list_request_id",
        "stock_basic": "stock_basic_request_id",
    }
    request_ids = {dataset: str(month_state[field]) for dataset, field in request_fields.items()}
    if len(set(request_ids.values())) != len(request_ids):
        raise RuntimeError(f"retained month {month} has a reused request id across datasets")
    allowed: set[str] = set()
    received_at_values: list[datetime] = []
    for dataset, request_id in request_ids.items():
        rows = conn.execute(
            "SELECT normalization_run_id, raw_evidence_uri, raw_request_id "
            "FROM meta_provider_normalization_run "
            "WHERE provider='amazingdata' AND provider_dataset=? AND raw_request_id=? "
            "AND status='SUCCESS'",
            [dataset, request_id],
        ).fetchall()
        if len(rows) != 1:
            raise RuntimeError(
                f"retained {month} {dataset} request does not resolve to one SUCCESS run"
            )
        allowed.add(str(rows[0][0]))
        raw_meta_path = source_root / "authoritative_capture" / str(rows[0][1])
        try:
            raw_meta = json.loads(raw_meta_path.read_text(encoding="utf-8"))
            received_at = datetime.fromisoformat(
                str(raw_meta["received_at"]).replace("Z", "+00:00")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise RuntimeError(f"retained {month} {dataset} receipt time is unreadable") from exc
        if (
            str(raw_meta.get("request_id")) != request_id
            or str(rows[0][2]) != request_id
            or received_at.tzinfo is None
            or received_at.utcoffset() is None
        ):
            raise RuntimeError(f"retained {month} {dataset} receipt identity/time is invalid")
        received_at_values.append(received_at.astimezone(UTC))

    identity_supplement = _load_identity_listdate_supplement(
        conn,
        source_root=source_root,
        output_root=output_root,
        source_state=source_state,
        month=month,
        month_state=month_state,
    )
    if identity_supplement is not None:
        supplement_run_id = str(identity_supplement["normalization_run_id"])
        if supplement_run_id in allowed:
            raise RuntimeError("supplemental LISTDATE run duplicates a monthly input run")
        allowed.add(supplement_run_id)
        request_ids["identity_listdate_source"] = str(identity_supplement["request_id"])
        received_at_values.append(
            datetime.fromisoformat(
                str(identity_supplement["source_vintage_as_of"]).replace("Z", "+00:00")
            )
        )
    input_cutoff = max(received_at_values)
    retained_snapshot_cutoff = datetime.fromisoformat(
        str(month_state["source_snapshot_as_of"]).replace("Z", "+00:00")
    )
    if (
        retained_snapshot_cutoff.tzinfo is None
        or retained_snapshot_cutoff.utcoffset() is None
        or input_cutoff > retained_snapshot_cutoff.astimezone(UTC)
    ):
        raise RuntimeError(f"retained {month} input receipt exceeds its source snapshot cutoff")
    return allowed, request_ids, input_cutoff, identity_supplement


def _load_identity_listdate_supplement(
    conn: Any,
    *,
    source_root: Path,
    output_root: Path,
    source_state: dict[str, Any],
    month: str,
    month_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate the one PM-authorized retained LISTDATE supplement for 2022-09."""
    spec = IDENTITY_LISTDATE_SUPPLEMENT
    if month != spec["target_month"]:
        return None

    repo_root = Path(__file__).resolve().parents[2]
    scope_path = repo_root / spec["scope_csv"]
    if _sha256_file(scope_path) != spec["scope_csv_sha256"]:
        raise RuntimeError("2022-09 LISTDATE symbol-scope CSV hash differs")
    with scope_path.open("r", encoding="utf-8", newline="") as stream:
        scope_rows = list(csv.DictReader(stream))
    symbols = [str(row.get("provider_symbol") or "").strip().upper() for row in scope_rows]
    symbol_set = set(symbols)
    if (
        len(symbols) != int(spec["fact_count"])
        or len(symbol_set) != len(symbols)
        or any(not symbol for symbol in symbols)
    ):
        raise RuntimeError("2022-09 LISTDATE symbol-scope CSV is not the exact unique set")

    source_month = source_state.get("months", {}).get(spec["source_month"])
    if (
        not isinstance(source_month, dict)
        or source_month.get("status") != "PASS"
        or source_month.get("coverage") != "PASS"
        or source_month.get("retained_capture_replay") != "PASS"
        or source_month.get("stock_basic_request_id") != spec["request_id"]
    ):
        raise RuntimeError("LISTDATE source request is not bound to retained PASS month 2023-02")

    rows = conn.execute(
        "SELECT normalization_run_id, raw_evidence_uri, normalized_manifest_uri, "
        "normalized_manifest_hash, raw_request_id "
        "FROM meta_provider_normalization_run "
        "WHERE provider='amazingdata' AND provider_dataset='stock_basic' "
        "AND raw_request_id=? AND status='SUCCESS'",
        [spec["request_id"]],
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError("retained supplemental LISTDATE request has no unique SUCCESS run")
    run_id, raw_uri_value, manifest_uri_value, ledger_manifest_hash, ledger_request_id = rows[0]
    raw_uri = str(raw_uri_value)
    manifest_uri = str(manifest_uri_value)
    if (
        str(run_id) != spec["normalization_run_id"]
        or str(ledger_request_id) != spec["request_id"]
        or manifest_uri != spec["normalized_manifest_uri"]
        or str(ledger_manifest_hash) != spec["normalized_manifest_sha256"]
    ):
        raise RuntimeError("supplemental LISTDATE normalization ledger seal differs")

    raw_evidence_path = source_root / "authoritative_capture" / raw_uri
    if raw_evidence_path.name.endswith(".meta.json"):
        raw_meta_path = raw_evidence_path
        raw_path = raw_evidence_path.with_suffix("").with_suffix(".parquet")
    else:
        raw_path = raw_evidence_path
        raw_meta_path = raw_path.with_suffix(".meta.json")
    manifest_path = output_root / "normalized" / manifest_uri
    source_manifest_path = source_root / "normalized" / manifest_uri
    if (
        not raw_path.is_file()
        or not raw_meta_path.is_file()
        or not manifest_path.is_file()
        or not source_manifest_path.is_file()
    ):
        raise RuntimeError("supplemental LISTDATE retained evidence is incomplete")
    raw_file_hash = _sha256_file(raw_path)
    manifest_hash = _sha256_file(manifest_path)
    if (
        raw_file_hash != spec["raw_file_sha256"]
        or manifest_hash != spec["normalized_manifest_sha256"]
        or _sha256_file(source_manifest_path) != manifest_hash
    ):
        raise RuntimeError("supplemental LISTDATE retained raw/manifest hash differs")

    raw_meta = json.loads(raw_meta_path.read_text(encoding="utf-8"))
    received_at_text = str(raw_meta.get("received_at") or "")
    try:
        received_at = datetime.fromisoformat(received_at_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("supplemental LISTDATE receipt time is invalid") from exc
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise RuntimeError("supplemental LISTDATE receipt time has no timezone")
    received_at_text = received_at.astimezone(UTC).isoformat()
    if (
        raw_meta.get("provider") != "amazingdata"
        or raw_meta.get("provider_dataset") != "stock_basic"
        or raw_meta.get("request_id") != spec["request_id"]
        or raw_meta.get("status") != "OK"
        or int(raw_meta.get("row_count", -1)) != int(spec["response_row_count"])
        or raw_meta.get("content_hash") != spec["raw_file_sha256"]
        or received_at_text != spec["source_vintage_as_of"]
    ):
        raise RuntimeError("supplemental LISTDATE raw receipt does not match its pinned identity")
    requested_symbols_value = raw_meta.get("request_params", {}).get("code_list")
    if (
        not isinstance(requested_symbols_value, list)
        or len(requested_symbols_value) != int(spec["request_code_count"])
        or len(set(requested_symbols_value)) != len(requested_symbols_value)
        or not symbol_set.issubset(
            {str(value).strip().upper() for value in requested_symbols_value}
        )
    ):
        raise RuntimeError(
            "supplemental LISTDATE request scope does not cover the exact blocker set"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("provider") != "amazingdata"
        or manifest.get("provider_dataset") != "stock_basic"
        or manifest.get("raw_request_id") != spec["request_id"]
        or manifest.get("raw_evidence_hash") != spec["raw_evidence_hash"]
        or int(manifest.get("input_count", -1)) != int(spec["response_row_count"])
        or int(manifest.get("normalized_count", -1)) != int(spec["response_row_count"])
    ):
        raise RuntimeError("supplemental LISTDATE normalized manifest identity/count differs")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 1:
        raise RuntimeError("supplemental LISTDATE normalization must have one output")
    output_entry = outputs[0]
    if (
        output_entry.get("output_name") != "main"
        or output_entry.get("uri") != spec["normalized_output_uri"]
        or int(output_entry.get("row_count", -1)) != int(spec["response_row_count"])
        or output_entry.get("content_hash") != spec["normalized_output_sha256"]
    ):
        raise RuntimeError("supplemental LISTDATE normalized output seal differs")
    output_path = output_root / "normalized" / str(output_entry["uri"])
    source_output_path = source_root / "normalized" / str(output_entry["uri"])
    if (
        not output_path.is_file()
        or not source_output_path.is_file()
        or _sha256_file(output_path) != spec["normalized_output_sha256"]
        or _sha256_file(source_output_path) != spec["normalized_output_sha256"]
    ):
        raise RuntimeError("supplemental LISTDATE normalized output bytes differ")

    raw_frame = pl.read_parquet(raw_path, columns=["MARKET_CODE", "LISTDATE"])
    normalized_frame = pl.read_parquet(output_path, columns=["provider_symbol", "list_date"])
    if raw_frame.height != int(spec["response_row_count"]) or normalized_frame.height != int(
        spec["response_row_count"]
    ):
        raise RuntimeError("supplemental LISTDATE source row count differs")
    raw_facts: dict[str, str] = {}
    for row in raw_frame.iter_rows(named=True):
        symbol = str(row.get("MARKET_CODE") or "").strip().upper()
        if symbol not in symbol_set:
            continue
        if symbol in raw_facts:
            raise RuntimeError(f"supplemental raw LISTDATE repeats {symbol}")
        raw_facts[symbol] = _list_date_text(row.get("LISTDATE"))
    facts: dict[str, str] = {}
    for row in normalized_frame.iter_rows(named=True):
        symbol = str(row.get("provider_symbol") or "").strip().upper()
        if symbol not in symbol_set:
            continue
        if symbol in facts:
            raise RuntimeError(f"supplemental normalized LISTDATE repeats {symbol}")
        facts[symbol] = _list_date_text(row.get("list_date"))
    if raw_facts != facts or set(facts) != symbol_set:
        raise RuntimeError("supplemental raw and normalized LISTDATE facts do not close exactly")
    fact_hash = _identity_fact_set_hash(facts)
    if fact_hash != spec["fact_set_sha256"]:
        raise RuntimeError("supplemental LISTDATE fact-set hash differs")

    month_cutoff = datetime.fromisoformat(
        str(month_state["source_snapshot_as_of"]).replace("Z", "+00:00")
    )
    if (
        month_cutoff.tzinfo is None
        or month_cutoff.utcoffset() is None
        or received_at.astimezone(UTC) > month_cutoff.astimezone(UTC)
    ):
        raise RuntimeError("supplemental LISTDATE source is after the 2022-09 retained cutoff")

    daily_request_id = str(month_state["daily_bar_request_id"])
    daily_runs = conn.execute(
        "SELECT normalized_manifest_uri FROM meta_provider_normalization_run "
        "WHERE provider='amazingdata' AND provider_dataset='daily_bar' "
        "AND raw_request_id=? AND status='SUCCESS'",
        [daily_request_id],
    ).fetchall()
    if len(daily_runs) != 1:
        raise RuntimeError("2022-09 daily-bar normalized run is not unique for LISTDATE checks")
    daily_manifest = json.loads(
        (output_root / "normalized" / str(daily_runs[0][0])).read_text(encoding="utf-8")
    )
    daily_outputs = [
        entry for entry in daily_manifest.get("outputs", []) if entry.get("output_name") == "main"
    ]
    if len(daily_outputs) != 1:
        raise RuntimeError("2022-09 daily-bar output is not uniquely sealed")
    daily_path = output_root / "normalized" / str(daily_outputs[0]["uri"])
    min_bar_frame = (
        pl.scan_parquet(daily_path)
        .filter(pl.col("provider_symbol").is_in(sorted(symbol_set)))
        .group_by("provider_symbol")
        .agg(pl.col("kline_time").min().alias("first_bar_date"))
        .collect()
    )
    min_bar_dates = {
        str(row["provider_symbol"]): _list_date_text(row["first_bar_date"])
        for row in min_bar_frame.iter_rows(named=True)
    }
    if set(min_bar_dates) != symbol_set or any(
        date.fromisoformat(facts[symbol]) > date.fromisoformat(min_bar_dates[symbol])
        for symbol in symbol_set
    ):
        raise RuntimeError("supplemental LISTDATE does not precede every affected 2022-09 bar")

    return {
        "source_month": spec["source_month"],
        "request_id": spec["request_id"],
        "normalization_run_id": str(run_id),
        "raw_evidence_uri": raw_uri,
        "raw_file_sha256": raw_file_hash,
        "raw_evidence_hash": str(manifest["raw_evidence_hash"]),
        "normalized_manifest_uri": manifest_uri,
        "normalized_manifest_sha256": manifest_hash,
        "normalized_output_uri": str(output_entry["uri"]),
        "normalized_output_sha256": str(output_entry["content_hash"]),
        "source_vintage_as_of": received_at_text,
        "fact_count": len(facts),
        "fact_set_sha256": fact_hash,
        "facts": facts,
    }


class _MonthBoundedCanonicalRunner(CanonicalRunner):
    """Private migration-only input fence: at most one retained month enters memory."""

    def __init__(
        self,
        *args: Any,
        allowed_run_ids: set[str],
        identity_supplement: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._allowed_run_ids = frozenset(allowed_run_ids)
        self._identity_supplement = identity_supplement

    def _build_snapshot(self, as_of_dt: datetime, requested: tuple[str, ...]) -> Any:
        snapshot = super()._build_snapshot(as_of_dt, requested)
        if self._identity_supplement is None:
            return snapshot
        request_id = str(self._identity_supplement["request_id"])
        source_rows: list[tuple[tuple[str, Any], ...]] = []
        for run in snapshot.runs:
            if run.seal.role != "identity_master" or not run.seal.pit_available:
                continue
            output = run.output("main")
            if output is None:
                continue
            if run.seal.raw_request_id != request_id:
                source_rows.extend(output.rows)
                continue
            for packed_row in output.rows:
                tagged_row = dict(packed_row)
                tagged_row["raw_request"] = request_id
                source_rows.append(tuple(sorted(tagged_row.items())))
        projected_rows = _project_supplemental_identity_rows(
            tuple(source_rows),
            request_id=request_id,
            expected_facts=dict(self._identity_supplement["facts"]),
        )
        return replace(snapshot, available_master_rows=projected_rows)

    def _surface_runs(
        self, normalization_surface: str, provider_datasets: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        rows = super()._surface_runs(normalization_surface, provider_datasets)
        return [row for row in rows if str(row["normalization_run_id"]) in self._allowed_run_ids]


def _sealed_provider_symbol_ranges(
    conn: Any,
    output_root: Path,
    partition: dict[str, Any],
    expected_rows: int,
) -> dict[str, dict[str, Any]]:
    """Join exact Canonical lineage ordinals back to the sealed CR-2 bar output."""
    canonical_by_ordinal: dict[int, tuple[str, str]] = {}
    normalization_run_ids: set[str] = set()
    output_names: set[str] = set()
    for row in iter_daily_bar_partition_rows(output_root / "normalized", partition):
        ordinal = int(row["source_row_ordinal"])
        if ordinal in canonical_by_ordinal:
            raise RuntimeError("Canonical daily partition repeats a source row ordinal")
        canonical_by_ordinal[ordinal] = (
            str(row["trade_date"])[:10],
            str(row["security_id"]),
        )
        normalization_run_ids.add(str(row["source_normalization_run_id"]))
        output_names.add(str(row["source_output_name"]))
    if len(canonical_by_ordinal) != expected_rows or len(normalization_run_ids) != 1:
        raise RuntimeError("Canonical daily lineage does not map one-to-one to its retained input")
    if len(output_names) != 1:
        raise RuntimeError("Canonical daily lineage references multiple normalized outputs")
    normalization_run_id = next(iter(normalization_run_ids))
    output_name = next(iter(output_names))
    run = conn.execute(
        "SELECT normalized_manifest_uri, normalized_manifest_hash "
        "FROM meta_provider_normalization_run WHERE normalization_run_id=?",
        [normalization_run_id],
    ).fetchone()
    if run is None:
        raise RuntimeError("Canonical daily lineage source is absent from the CR-2 ledger")
    normalized_root = output_root / "normalized"
    normalized_manifest_path = normalized_root / str(run[0])
    manifest_bytes = normalized_manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != str(run[1]):
        raise RuntimeError("retained daily-bar normalized manifest hash differs")
    normalized_manifest = json.loads(manifest_bytes.decode("utf-8"))
    matches = [
        entry
        for entry in normalized_manifest.get("outputs", [])
        if str(entry.get("output_name")) == output_name
    ]
    if len(matches) != 1:
        raise RuntimeError("Canonical daily lineage does not bind one normalized output")
    output_entry = matches[0]
    output_path = normalized_root / str(output_entry["uri"])
    if _sha256_file(output_path) != str(output_entry["content_hash"]):
        raise RuntimeError("retained daily-bar normalized output hash differs")
    source_rows = pl.read_parquet(output_path, columns=["provider_symbol", "kline_time"])
    if source_rows.height != expected_rows:
        raise RuntimeError("retained daily-bar normalized row count differs from Canonical")

    symbol_ranges: dict[str, dict[str, Any]] = {}
    for ordinal, source_row in enumerate(source_rows.iter_rows(named=True)):
        canonical_row = canonical_by_ordinal.get(ordinal)
        if canonical_row is None:
            raise RuntimeError("retained daily-bar source ordinal is absent from Canonical")
        symbol = str(source_row.get("provider_symbol") or "")
        if not symbol:
            raise RuntimeError("retained daily-bar source has an empty provider symbol")
        trade_day_value = source_row.get("kline_time")
        if isinstance(trade_day_value, datetime):
            trade_date = trade_day_value.date().isoformat()
        elif isinstance(trade_day_value, int):
            trade_date = datetime.strptime(str(trade_day_value), "%Y%m%d").date().isoformat()
        elif hasattr(trade_day_value, "isoformat"):
            trade_date = trade_day_value.isoformat()
        else:
            raise RuntimeError("retained daily-bar source has an invalid kline_time value")
        if canonical_row[0] != trade_date:
            raise RuntimeError("Canonical trade_date differs from its exact source row ordinal")
        entry = symbol_ranges.setdefault(
            symbol,
            {
                "count": 0,
                "min_trade_date": trade_date,
                "max_trade_date": trade_date,
                "security_ids": set(),
            },
        )
        entry["count"] += 1
        entry["min_trade_date"] = min(entry["min_trade_date"], trade_date)
        entry["max_trade_date"] = max(entry["max_trade_date"], trade_date)
        entry["security_ids"].add(canonical_row[1])
    return symbol_ranges


def _validate_month_rows(
    conn: Any,
    output_root: Path,
    month: str,
    partition: dict[str, Any],
    month_state: dict[str, Any],
) -> dict[str, Any]:
    if partition.get("partition") != month:
        raise RuntimeError(
            f"Canonical emitted {partition.get('partition')} for requested month {month}"
        )
    expected_rows = int(month_state["returned_row_count"])
    if int(partition.get("row_count", -1)) != expected_rows:
        raise RuntimeError(f"Canonical row count differs from retained coverage for {month}")

    event = next(
        (
            item
            for item in approved_provider_identity_events()
            if item.old_provider_symbol == "300114.SZ" and item.new_provider_symbol == "302132.SZ"
        ),
        None,
    )
    symbol_ranges = _sealed_provider_symbol_ranges(conn, output_root, partition, expected_rows)

    completeness = month_state["completeness"]
    prelisting = completeness.get("prelisting_list_dates", {})
    postdelisting = completeness.get("postdelisting_delist_dates", {})
    for symbol, list_date in prelisting.items():
        observed = symbol_ranges.get(str(symbol))
        if observed and observed["min_trade_date"] < str(list_date):
            raise RuntimeError(f"Canonical has a pre-LISTDATE daily bar for {symbol} in {month}")
    for symbol, delist_date in postdelisting.items():
        observed = symbol_ranges.get(str(symbol))
        if observed and observed["max_trade_date"] >= str(delist_date):
            raise RuntimeError(
                f"Canonical has a daily bar on/after DELISTDATE for {symbol} in {month}"
            )

    identity_transition: dict[str, Any] | None = None
    if month == "2025-02":
        if event is None:
            raise RuntimeError("approved 300114/302132 identity event is absent")
        old = symbol_ranges.get(event.old_provider_symbol)
        new = symbol_ranges.get(event.new_provider_symbol)
        if not old or not new:
            raise RuntimeError(
                "2025-02 Canonical partition lacks one side of the approved symbol transition"
            )
        if old["max_trade_date"] >= event.effective_from.isoformat():
            raise RuntimeError("old provider symbol crossed the approved effective date")
        if new["min_trade_date"] < event.effective_from.isoformat():
            raise RuntimeError("new provider symbol appears before the approved effective date")
        old_ids = old["security_ids"]
        new_ids = new["security_ids"]
        if old_ids != {event.security_id} or new_ids != {event.security_id}:
            raise RuntimeError(
                "approved provider-symbol transition did not preserve the stable security_id"
            )
        identity_transition = {
            "old_symbol_rows": old["count"],
            "new_symbol_rows": new["count"],
            "effective_from": event.effective_from.isoformat(),
            "same_security_id": True,
        }

    if month in {"2023-01", "2023-02"}:
        event_record = completeness.get("official_suspension_event")
        if not isinstance(event_record, dict):
            raise RuntimeError(
                f"approved suspension evidence is absent from retained month {month}"
            )
        if (
            str(event_record.get("event_id")) != "300114-suspension-2023-01"
            or str(event_record.get("security")) != "300114.SZ"
            or str(event_record.get("suspended_from")) != "2023-01-12"
            or str(event_record.get("resumes_on")) != "2023-02-02"
        ):
            raise RuntimeError(f"approved suspension event scope differs in {month}")
        expected_suspension_pairs = {"2023-01": 106, "2023-02": 173}[month]
        observed_suspension_pairs = int(
            completeness.get("classification_counts", {}).get("SUSPENSION_NON_TRADING", 0)
        )
        if observed_suspension_pairs != expected_suspension_pairs:
            raise RuntimeError(
                f"approved suspension pair count differs for {month}: "
                f"{observed_suspension_pairs} != {expected_suspension_pairs}"
            )

    return {
        "row_count": expected_rows,
        "market_as_of": partition["market_as_of"],
        "source_vintage_as_of": partition["source_vintage_as_of"],
        "source_vintage_receipt_count": len(partition.get("source_vintage_evidence", [])),
        "prelisting_symbol_count": len(prelisting),
        "postdelisting_symbol_count": len(postdelisting),
        "identity_transition": identity_transition,
        "suspension_classification_count": int(
            completeness.get("classification_counts", {}).get("SUSPENSION_NON_TRADING", 0)
        ),
        "unresolved_pair_count": int(month_state["unresolved_pair_count"]),
    }


def _run_month(
    *,
    source_root: Path,
    output_root: Path,
    source_state: dict[str, Any],
    migration_state: dict[str, Any],
    month: str,
    build_month_snapshot: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    month_state = source_state["months"][month]
    conn = duckdb.connect(str(output_root / "ledger.duckdb"))
    try:
        allowed_run_ids, request_ids, run_as_of, identity_supplement = _load_month_run_ids(
            conn, source_root, output_root, source_state, month
        )
        runner = _MonthBoundedCanonicalRunner(
            conn,
            raw_root=source_root / "authoritative_capture",
            normalized_root=output_root / "normalized",
            allowed_run_ids=allowed_run_ids,
            identity_supplement=identity_supplement,
        )
        result = runner.run(run_as_of, domains=("daily_bar",))
        if result.status != "SUCCESS" or result.selected_count != int(
            month_state["returned_row_count"]
        ):
            raise RuntimeError(
                f"Canonical {month} did not PASS exact coverage: "
                f"status={result.status}, selected={result.selected_count}, "
                f"expected={month_state['returned_row_count']}"
            )
        _record, canonical_manifest, _as_of = read_canonical_run_manifest(
            conn, result.canonical_run_id, normalized_root=output_root / "normalized"
        )
        inputs = canonical_manifest.get("input_normalized_runs", [])
        actual_input_ids = {str(entry.get("run_id")) for entry in inputs}
        if actual_input_ids != allowed_run_ids:
            raise RuntimeError(f"Canonical {month} consumed an unexpected month/input set")
        if identity_supplement is not None:
            identity_seals = [
                entry
                for entry in inputs
                if str(entry.get("run_id")) == str(identity_supplement["normalization_run_id"])
            ]
            if len(identity_seals) != 1:
                raise RuntimeError("Canonical manifest does not bind one supplemental LISTDATE run")
            identity_seal = identity_seals[0]
            if (
                str(identity_seal.get("raw_request_id")) != str(identity_supplement["request_id"])
                or str(identity_seal.get("raw_evidence_hash"))
                != str(identity_supplement["raw_evidence_hash"])
                or str(identity_seal.get("normalized_manifest_uri"))
                != str(identity_supplement["normalized_manifest_uri"])
                or str(identity_seal.get("normalized_manifest_hash"))
                != str(identity_supplement["normalized_manifest_sha256"])
                or str(identity_seal.get("received_at"))
                != str(identity_supplement["source_vintage_as_of"])
                or datetime.fromisoformat(str(canonical_manifest["as_of"]))
                < datetime.fromisoformat(str(identity_supplement["source_vintage_as_of"]))
            ):
                raise RuntimeError(
                    "Canonical manifest does not bind the exact LISTDATE source vintage"
                )
        partitions = canonical_manifest.get("daily_bar_partitions")
        if not isinstance(partitions, list) or len(partitions) != 1:
            raise RuntimeError(f"Canonical {month} must emit exactly one monthly L0 partition")
        partition_result = _validate_month_rows(
            conn, output_root, month, partitions[0], month_state
        )
        verify_canonical_run_for_consumption(
            conn,
            result.canonical_run_id,
            raw_root=source_root / "authoritative_capture",
            normalized_root=output_root / "normalized",
        )

        snapshot_result: dict[str, Any] | None = None
        readmodel_result: dict[str, Any] | None = None
        if build_month_snapshot:
            snapshot = SnapshotBuilder(
                conn,
                raw_root=source_root / "authoritative_capture",
                normalized_root=output_root / "normalized",
            ).build(result.canonical_run_id)
            verified = verify_snapshot(
                conn,
                snapshot.snapshot_id,
                raw_root=source_root / "authoritative_capture",
                normalized_root=output_root / "normalized",
            )
            readmodel = DuckDBReadModel(
                conn,
                raw_root=source_root / "authoritative_capture",
                normalized_root=output_root / "normalized",
            )
            built = readmodel.rebuild(snapshot.snapshot_id)
            readmodel.verify_readmodel(snapshot.snapshot_id)
            db = readmodel.open_read_only(snapshot.snapshot_id)
            try:
                count = int(db.execute("SELECT count(*) FROM rm_daily_bar").fetchone()[0])
                kind_row = db.execute(
                    "SELECT table_type FROM information_schema.tables "
                    "WHERE table_name='rm_daily_bar'"
                ).fetchone()
                if count != int(month_state["returned_row_count"]):
                    raise RuntimeError(
                        f"ordinary rm_daily_bar reader returned {count} rows for {month}"
                    )
                if kind_row is None or str(kind_row[0]).upper() != "VIEW":
                    raise RuntimeError("rm_daily_bar is not an external view")
            finally:
                db.close()
            replay_snapshot = SnapshotBuilder(
                conn,
                raw_root=source_root / "authoritative_capture",
                normalized_root=output_root / "normalized",
            ).build(result.canonical_run_id)
            if not replay_snapshot.idempotent_replay:
                raise RuntimeError(f"logical Snapshot exact replay failed for {month}")
            snapshot_result = {
                "snapshot_id": snapshot.snapshot_id,
                "verified": str(verified.ledger_record["status"]) == "SUCCESS",
                "idempotent_replay": replay_snapshot.idempotent_replay,
                "row_count": count,
            }
            readmodel_result = {
                "db_uri": built.db_uri,
                "daily_bar_relation": "VIEW",
                "row_count": count,
                "fact_copy": False,
            }

        replay_runner = _MonthBoundedCanonicalRunner(
            conn,
            raw_root=source_root / "authoritative_capture",
            normalized_root=output_root / "normalized",
            allowed_run_ids=allowed_run_ids,
            identity_supplement=identity_supplement,
        )
        replay = replay_runner.run(run_as_of, domains=("daily_bar",))
        if not replay.idempotent_replay or replay.canonical_run_id != result.canonical_run_id:
            raise RuntimeError(f"Canonical exact replay failed for {month}")
        result_record = {
            "month": month,
            "status": "PASS",
            "canonical_run_id": result.canonical_run_id,
            "canonical_replay": replay.idempotent_replay,
            "selected_count": result.selected_count,
            "decision_count": result.decision_count,
            "input_run_count": len(allowed_run_ids),
            "input_request_ids": request_ids,
            "identity_listdate_source": (
                {key: value for key, value in identity_supplement.items() if key != "facts"}
                if identity_supplement is not None
                else None
            ),
            "canonical_source_cutoff": run_as_of.isoformat(),
            "retained_snapshot_cutoff": month_state["source_snapshot_as_of"],
            "source_capture_provider_calls": int(
                month_state.get("provider_calls_during_capture", 0)
            ),
            "provider_calls": 0,
            "provider_calls_scope": (
                "current offline migration process; no provider client is imported"
            ),
            "partition": partition_result,
            "snapshot": snapshot_result,
            "readmodel": readmodel_result,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "completed_at_utc": datetime.now(UTC).isoformat(),
        }
        migration_state["processed_months"][month] = result_record
        _atomic_json(output_root / STATE_FILENAME, migration_state)
        return result_record
    finally:
        conn.close()


def _publish_archive_snapshot(
    *, source_root: Path, output_root: Path, migration_state: dict[str, Any]
) -> dict[str, Any]:
    months = _month_range()
    processed = migration_state.get("processed_months")
    if not isinstance(processed, dict) or set(processed) != set(months):
        raise RuntimeError("archive Snapshot requires exactly 78 completed Canonical months")
    canonical_run_ids: list[str] = []
    expected_month_rows: dict[str, int] = {}
    for month in months:
        entry = processed[month]
        if not isinstance(entry, dict) or entry.get("status") != "PASS":
            raise RuntimeError(f"archive Snapshot requires a PASS record for {month}")
        run_id = str(entry.get("canonical_run_id", ""))
        row_count = int(entry.get("partition", {}).get("row_count", -1))
        if not run_id or row_count < 0:
            raise RuntimeError(f"archive Snapshot record for {month} is incomplete")
        canonical_run_ids.append(run_id)
        expected_month_rows[month] = row_count
    if len(set(canonical_run_ids)) != len(months):
        raise RuntimeError("archive Snapshot month records reuse a Canonical run id")

    conn = duckdb.connect(str(output_root / "ledger.duckdb"))
    try:
        builder = SnapshotBuilder(
            conn,
            raw_root=source_root / "authoritative_capture",
            normalized_root=output_root / "normalized",
        )
        with _PeakRssSampler() as sampler:
            built = builder.build_daily_partition_set(canonical_run_ids)
            verified = verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=source_root / "authoritative_capture",
                normalized_root=output_root / "normalized",
                retain_domain_rows=False,
            )
            if verified.ledger_record.get("status") != "SUCCESS":
                raise RuntimeError("archive logical Snapshot did not verify SUCCESS")

            replay = builder.build_daily_partition_set(canonical_run_ids)
            if not replay.idempotent_replay or replay.snapshot_id != built.snapshot_id:
                raise RuntimeError("archive logical Snapshot exact replay failed")

            readmodel = DuckDBReadModel(
                conn,
                raw_root=source_root / "authoritative_capture",
                normalized_root=output_root / "normalized",
                readmodel_root=output_root / "readmodel",
            )
            readmodel_result = readmodel.rebuild(built.snapshot_id)
            readmodel.verify_readmodel(built.snapshot_id)
            db = readmodel.open_read_only(built.snapshot_id)
            try:
                relation = db.execute(
                    "SELECT table_type FROM information_schema.tables "
                    "WHERE table_name='rm_daily_bar'"
                ).fetchone()
                if relation is None or str(relation[0]).upper() != "VIEW":
                    raise RuntimeError("archive rm_daily_bar is not an external VIEW")
                aggregate = db.execute(
                    "SELECT count(*), count(DISTINCT strftime(trade_date, '%Y-%m')), "
                    "min(trade_date), max(trade_date), count(DISTINCT canonical_run_id) "
                    "FROM rm_daily_bar"
                ).fetchone()
                ownership = db.execute(
                    "SELECT canonical_run_id, strftime(min(trade_date), '%Y-%m'), count(*) "
                    "FROM rm_daily_bar GROUP BY canonical_run_id"
                ).fetchall()
            finally:
                db.close()

            row_count = int(aggregate[0])
            if (
                row_count != sum(expected_month_rows.values())
                or int(aggregate[1]) != len(months)
                or int(aggregate[4]) != len(months)
            ):
                raise RuntimeError("archive ordinary reader row/month/source inventory differs")
            actual_month_rows = {str(item[1]): int(item[2]) for item in ownership}
            if actual_month_rows != expected_month_rows:
                raise RuntimeError("archive ordinary reader month row counts differ from Canonical")
            if {str(month) for _run_id, month, _count in ownership} != set(months):
                raise RuntimeError("archive ordinary reader has a missing/extra calendar month")
            snapshot_dir = (output_root / "normalized" / built.manifest_uri).parent
            if list(snapshot_dir.rglob("*.parquet")):
                raise RuntimeError("logical Snapshot unexpectedly copied daily Parquet facts")

            manifest = json.loads(
                (output_root / "normalized" / built.manifest_uri).read_text(encoding="utf-8")
            )
            snapshot_summary = {
                "status": "PASS",
                "snapshot_contract_version": manifest["snapshot_contract_version"],
                "snapshot_id": built.snapshot_id,
                "manifest_uri": built.manifest_uri,
                "manifest_hash": built.manifest_hash,
                "canonical_source_set_hash": manifest["canonical_source_set_hash"],
                "canonical_source_count": len(manifest["canonical_sources"]),
                "partition_count": len(manifest["artifacts"]["daily_bar"]["partitions"]),
                "row_count": row_count,
                "market_as_of": manifest["market_as_of"],
                "source_vintage_as_of": manifest["source_vintage_as_of"],
                "canonical_anchor_run_id": built.canonical_run_id,
                "deep_verify": True,
                "idempotent_replay": replay.idempotent_replay,
                "readmodel_db_uri": readmodel_result.db_uri,
                "ordinary_relation": "VIEW",
                "ordinary_reader_month_count": int(aggregate[1]),
                "ordinary_reader_source_run_count": int(aggregate[4]),
                "ordinary_reader_min_trade_date": str(aggregate[2]),
                "ordinary_reader_max_trade_date": str(aggregate[3]),
                "snapshot_fact_copy": False,
                "provider_calls": 0,
                "provider_calls_scope": "archive Snapshot/readmodel process only",
                "completed_at_utc": datetime.now(UTC).isoformat(),
            }
        return {
            **snapshot_summary,
            "peak_rss_bytes": sampler.peak,
            "peak_rss_mib": round(sampler.peak / (1024 * 1024), 2),
        }
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--months", help="comma-separated representative months; defaults to the C1 audit set"
    )
    parser.add_argument(
        "--all-months", action="store_true", help="process all 78 months, 2020-01 through 2026-06"
    )
    parser.add_argument(
        "--no-month-snapshots",
        action="store_true",
        help=(
            "build Canonical only (required for the 78-month archive pass; "
            "archive Snapshot is separate)"
        ),
    )
    parser.add_argument(
        "--publish-archive-snapshot",
        action="store_true",
        help=(
            "publish and validate one 78-month logical Snapshot from existing PASS Canonical "
            "state; does not rerun Canonical migration"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    if args.publish_archive_snapshot and (
        args.all_months or args.months or args.no_month_snapshots
    ):
        raise SystemExit("--publish-archive-snapshot is a separate, resume-safe operation")
    if args.all_months and args.months:
        raise SystemExit("--all-months and --months are mutually exclusive")
    if args.publish_archive_snapshot:
        months = ()
    elif args.all_months:
        months = _month_range()
    elif args.months:
        months = tuple(sorted({item.strip() for item in args.months.split(",") if item.strip()}))
    else:
        months = DEFAULT_AUDIT_MONTHS
    if (not months and not args.publish_archive_snapshot) or any(
        len(month) != 7 or month[4] != "-" for month in months
    ):
        raise SystemExit("months must be YYYY-MM values")
    build_month_snapshots = (
        not args.no_month_snapshots and not args.all_months and not args.publish_archive_snapshot
    )

    migration_state = _initialize_output(source_root, output_root)
    if args.publish_archive_snapshot:
        result = _publish_archive_snapshot(
            source_root=source_root,
            output_root=output_root,
            migration_state=migration_state,
        )
        migration_state["archive_snapshot"] = result
        _atomic_json(output_root / STATE_FILENAME, migration_state)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    source_state = json.loads((source_root / "execution_state.json").read_text(encoding="utf-8"))
    preflight_conn = duckdb.connect(str(output_root / "ledger.duckdb"), read_only=True)
    try:
        cutoffs: dict[str, str] = {}
        for month in months:
            _allowed, _request_ids, cutoff, _identity_supplement = _load_month_run_ids(
                preflight_conn, source_root, output_root, source_state, month
            )
            cutoff_text = cutoff.isoformat()
            prior_month = cutoffs.get(cutoff_text)
            if prior_month is not None:
                raise RuntimeError(
                    f"month-bounded Canonical context collision: {prior_month} and {month} "
                    "share the same exact retained input cutoff"
                )
            cutoffs[cutoff_text] = month
    finally:
        preflight_conn.close()
    samples: list[dict[str, Any]] = []
    with _PeakRssSampler() as sampler:
        for month in months:
            record = _run_month(
                source_root=source_root,
                output_root=output_root,
                source_state=source_state,
                migration_state=migration_state,
                month=month,
                build_month_snapshot=build_month_snapshots,
            )
            samples.append(record)
            print(json.dumps(record, sort_keys=True), flush=True)
    summary = {
        "state_version": STATE_VERSION,
        "status": "PASS" if len(samples) == len(months) else "STOP(BLOCKED)",
        "months_requested": list(months),
        "months_passed_this_invocation": len(samples),
        "provider_calls": 0,
        "provider_calls_scope": "current offline migration process only",
        "month_snapshots_built": build_month_snapshots,
        "peak_rss_bytes": sampler.peak,
        "peak_rss_mib": round(sampler.peak / (1024 * 1024), 2),
        "output_root": str(output_root),
        "finished_at_utc": datetime.now(UTC).isoformat(),
    }
    migration_state["last_invocation"] = summary
    _atomic_json(output_root / STATE_FILENAME, migration_state)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
