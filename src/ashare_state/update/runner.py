"""Bounded production daily-bar update orchestration.

The service composes existing Provider, anchored-raw, normalization, Canonical,
Snapshot, and ReadModel boundaries.  It deliberately does not own a scheduler,
queue, or alternate persistence format.  Provider keys and date coverage are
reconciled before Canonical publication; each Canonical month is scoped to its
exact source run set while all discovered historical input seals remain part
of the continuity audit.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.canonical.canonicalizer import CanonicalRunner
from ashare_state.canonical.verifier import (
    read_canonical_run_manifest,
    verify_canonical_run_for_consumption,
)
from ashare_state.normalization.runner import NormalizationRunner
from ashare_state.snapshot.builder import SnapshotBuilder
from ashare_state.snapshot.verifier import verify_snapshot
from ashare_state.storage.atomic_files import write_file_atomic
from ashare_state.storage.paths import physical_from_logical_uri, to_logical_uri
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter

_SECURITY_TYPE = "EXTRA_STOCK_A_SH_SZ"
_MARKETS = ("SH", "SZ")
_REQUIRED_SEGMENTS = ("60", "00", "30", "688")
_UNIT_SCALES = (("DIRECT", 1.0), ("AMOUNT_PER_100_VOLUME", 0.01), ("100X_AMOUNT_PER_VOLUME", 100.0))


class DailyUpdateError(RuntimeError):
    """A daily update cannot proceed or cannot be accepted safely."""


@dataclass(frozen=True)
class RepositoryIdentity:
    commit_sha: str
    dirty: bool


@dataclass(frozen=True)
class DailyUpdatePlan:
    through_date: date
    accepted_through: date
    accepted_snapshot_id: str
    action: str
    note: str


@dataclass(frozen=True)
class DailyUpdateResult:
    status: str
    through_date: date
    accepted_through: date
    snapshot_id: str
    update_run_id: str | None
    manifest_uri: str | None
    manifest_hash: str | None
    idempotent_replay: bool
    expected_member_count: int = 0
    returned_bar_count: int = 0
    retention_status: str = "NOT_CONFIGURED"


@dataclass(frozen=True)
class _AcceptedSnapshot:
    snapshot_id: str
    through: date
    manifest: dict[str, Any]

    @property
    def partitions(self) -> list[dict[str, Any]]:
        artifacts = self.manifest.get("artifacts")
        daily = artifacts.get("daily_bar") if isinstance(artifacts, dict) else None
        partitions = daily.get("partitions") if isinstance(daily, dict) else None
        if not isinstance(partitions, list) or not partitions:
            raise DailyUpdateError("accepted daily Snapshot has no partition set")
        if any(not isinstance(item, dict) for item in partitions):
            raise DailyUpdateError("accepted daily Snapshot partition set is malformed")
        return partitions


def read_repository_identity(repository_root: Path) -> RepositoryIdentity:
    """Read the exact Git commit and working-tree state without shell interpolation."""
    root = Path(repository_root).resolve()
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise DailyUpdateError("cannot establish tracked repository identity") from exc
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit.lower()):
        raise DailyUpdateError("Git returned an invalid commit identity")
    return RepositoryIdentity(commit_sha=commit.lower(), dirty=bool(status.strip()))


def measure_volume_amount_units(
    rows: Sequence[Mapping[str, Any]], *, minimum_rows_per_segment: int = 100
) -> dict[str, dict[str, int | str | float]]:
    """Find the unique 1x/100x VWAP scale matching valid OHLC ranges.

    This reports a unit contract only when every required board segment has
    enough usable rows and one scale places at least 99% of them inside its
    own low/high interval.  The returned scale is the multiplier applied to
    ``amount / volume`` to obtain a price in the provider's recorded price
    units; it is not silently applied to the DTO.
    """
    if minimum_rows_per_segment < 1:
        raise ValueError("minimum_rows_per_segment must be positive")
    samples: dict[str, list[tuple[float, float, float]]] = {
        segment: [] for segment in _REQUIRED_SEGMENTS
    }
    for row in rows:
        symbol = str(row.get("provider_symbol") or "").split(".", 1)[0]
        segment = next((item for item in _REQUIRED_SEGMENTS if symbol.startswith(item)), None)
        if segment is None:
            continue
        try:
            amount = float(row["amount"])
            volume = float(row["volume"])
            low = float(row["low"])
            high = float(row["high"])
        except KeyError, TypeError, ValueError:
            continue
        if not all(math.isfinite(value) for value in (amount, volume, low, high)):
            continue
        if amount <= 0 or volume <= 0 or low <= 0 or high < low:
            continue
        samples[segment].append((amount / volume, low, high))

    diagnostics: dict[str, dict[str, int | str | float]] = {}
    for segment in _REQUIRED_SEGMENTS:
        values = samples[segment]
        if len(values) < minimum_rows_per_segment:
            raise DailyUpdateError(
                f"VWAP unit check for board {segment} has only {len(values)} usable rows; "
                f"requires {minimum_rows_per_segment}"
            )
        matches: list[tuple[str, float, int]] = []
        for label, scale in _UNIT_SCALES:
            count = sum(low <= ratio * scale <= high for ratio, low, high in values)
            matches.append((label, scale, count))
        winners = [item for item in matches if item[2] / len(values) >= 0.99]
        if len(winners) != 1:
            raise DailyUpdateError(
                f"VWAP unit check for board {segment} is ambiguous or below 99% agreement"
            )
        label, scale, count = winners[0]
        diagnostics[segment] = {
            "usable_rows": len(values),
            "matching_rows": count,
            "match_rate": count / len(values),
            "amount_over_volume_multiplier": scale,
            "contract": label,
        }
    return diagnostics


class DailyUpdateRunner:
    """Execute one or more consecutive SH/SZ daily-bar updates through a date."""

    def __init__(
        self,
        conn: Any,
        *,
        provider: Any,
        repository_root: Path,
        data_root: Path,
        raw_root: Path,
        normalized_root: Path,
        evidence_backup_root: Path | None = None,
        batch_size: int = 500,
        now: Callable[[], datetime] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("daily update batch_size must be between 1 and 1000")
        self.conn = conn
        self.provider = provider
        self.repository_root = Path(repository_root).resolve()
        self.data_root = Path(data_root).resolve()
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
        self.evidence_backup_root = (
            Path(evidence_backup_root).resolve() if evidence_backup_root is not None else None
        )
        self.batch_size = batch_size
        self._now = now or (lambda: datetime.now(UTC))
        self._progress = progress or (lambda _event: None)

    def plan(self, through: date) -> DailyUpdatePlan:
        target = _require_date(through)
        accepted = self._latest_accepted_snapshot()
        if target <= accepted.through:
            return DailyUpdatePlan(
                through_date=target,
                accepted_through=accepted.through,
                accepted_snapshot_id=accepted.snapshot_id,
                action="NO_PROVIDER_WORK",
                note="A verified accepted daily Snapshot already covers the requested date.",
            )
        return DailyUpdatePlan(
            through_date=target,
            accepted_through=accepted.through,
            accepted_snapshot_id=accepted.snapshot_id,
            action="FETCH_PROVIDER_CALENDAR",
            note=(
                "The exact SH/SZ sessions must be resolved from the Provider calendar; "
                "--plan does not log in or make network requests."
            ),
        )

    def run(self, through: date) -> DailyUpdateResult:
        target = _require_date(through)
        base = self._latest_accepted_snapshot()
        if target <= base.through:
            return DailyUpdateResult(
                status="SUCCESS",
                through_date=target,
                accepted_through=base.through,
                snapshot_id=base.snapshot_id,
                update_run_id=None,
                manifest_uri=None,
                manifest_hash=None,
                idempotent_replay=True,
                retention_status="NOT_APPLICABLE",
            )

        repository = read_repository_identity(self.repository_root)
        if repository.dirty:
            raise DailyUpdateError(
                "accepted daily update refused: tracked repository state is dirty; "
                "commit the reviewed code and rerun"
            )

        started = self._now().astimezone(UTC)
        update_run_id = str(uuid.uuid4())
        self._record_initial_baseline(base, repository)
        raw_writer = AnchoredRawEvidenceWriter(
            self.conn, self.raw_root, ingest_run_id=update_run_id
        )
        normalizer = NormalizationRunner(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        request_receipts: list[dict[str, Any]] = []

        calendars: dict[str, list[date]] = {}
        for market in _MARKETS:

            def calendar_call(market: str = market) -> Any:
                return self.provider.get_calendar_exchange(market)

            exchange, normalized = self._request(
                calendar_call,
                "trade_calendar",
                raw_writer,
                normalizer,
                request_receipts,
            )
            values = exchange.payload
            if not isinstance(values, list) or not values:
                raise DailyUpdateError(f"Provider {market} calendar is empty or malformed")
            # For this WHOLE_PAYLOAD mapper the single DTO contains the
            # calendar list, while normalization_count preserves the
            # source-member denominator (not the DTO row count).
            if normalized.input_count != len(values) or normalized.normalized_count != len(values):
                raise DailyUpdateError(
                    f"Provider {market} calendar denominator does not reconcile "
                    f"(input={normalized.input_count}, values={len(values)}, "
                    f"normalized={normalized.normalized_count})"
                )
            calendars[market] = _calendar_dates(values)
            self._emit(
                "PROVIDER_CALENDAR_PASS", market=market, session_count=len(calendars[market])
            )

        sh_sessions = [day for day in calendars["SH"] if base.through < day <= target]
        sz_sessions = [day for day in calendars["SZ"] if base.through < day <= target]
        if sh_sessions != sz_sessions:
            raise DailyUpdateError("SH and SZ Provider calendars disagree in the requested window")
        sessions = sh_sessions
        calendar_end = min(max(calendars["SH"]), max(calendars["SZ"]))
        if calendar_end < target:
            raise DailyUpdateError(
                "Provider calendar does not cover the requested through date; "
                "refusing to infer missing sessions"
            )
        if not sessions:
            return DailyUpdateResult(
                status="SUCCESS",
                through_date=target,
                accepted_through=base.through,
                snapshot_id=base.snapshot_id,
                update_run_id=None,
                manifest_uri=None,
                manifest_hash=None,
                idempotent_replay=True,
                retention_status="NOT_APPLICABLE",
            )

        session_universes: dict[date, list[str]] = {}
        identity_run_ids_by_month: dict[str, set[str]] = {}
        for trading_day in sessions:
            value = _yyyymmdd(trading_day)

            def universe_call(value: int = value) -> Any:
                return self.provider.get_hist_code_list_exchange(_SECURITY_TYPE, value, value)

            exchange, normalized = self._request(
                universe_call,
                "hist_code_list",
                raw_writer,
                normalizer,
                request_receipts,
            )
            symbols = _security_symbols(exchange.payload)
            if normalized.input_count != len(symbols) or normalized.normalized_count != len(
                symbols
            ):
                raise DailyUpdateError(
                    f"security universe denominator does not reconcile for {trading_day}"
                )
            session_universes[trading_day] = symbols
            identity_run_ids_by_month.setdefault(trading_day.strftime("%Y-%m"), set()).add(
                normalized.normalization_run_id
            )
            self._emit(
                "SESSION_UNIVERSE_PASS",
                trade_date=trading_day.isoformat(),
                expected_member_count=len(symbols),
            )

        universe = sorted({symbol for symbols in session_universes.values() for symbol in symbols})
        stock_basic_run_ids: set[str] = set()
        basic_symbols: set[str] = set()
        for batch in _chunks(universe, self.batch_size):

            def basic_call(batch: Sequence[str] = batch) -> Any:
                return self.provider.get_stock_basic_exchange(list(batch))

            _, normalized = self._request(
                basic_call,
                "stock_basic",
                raw_writer,
                normalizer,
                request_receipts,
            )
            rows = self._read_normalized_rows(normalized, "main")
            received_symbols = [str(row.get("provider_symbol") or "") for row in rows]
            if (
                normalized.input_count != len(batch)
                or normalized.normalized_count != len(batch)
                or len(received_symbols) != len(set(received_symbols))
                or set(received_symbols) != set(batch)
                or any(not row.get("list_date") for row in rows)
            ):
                raise DailyUpdateError("stock-basic identity keys/list dates do not reconcile")
            basic_symbols.update(received_symbols)
            stock_basic_run_ids.add(normalized.normalization_run_id)
        if basic_symbols != set(universe):
            raise DailyUpdateError("stock-basic output does not cover the exact requested universe")

        new_rows_by_month: dict[str, list[dict[str, Any]]] = {}
        session_evidence: list[dict[str, Any]] = []
        expected_member_count = 0
        returned_bar_count = 0
        for trading_day in sessions:
            symbols = session_universes[trading_day]
            expected_member_count += len(symbols)
            day_rows: list[dict[str, Any]] = []
            request_ids: list[str] = []
            normalized_ids: list[str] = []
            empty_member_count = 0
            for batch in _chunks(symbols, self.batch_size):

                def daily_call(
                    batch: Sequence[str] = batch, trading_day: date = trading_day
                ) -> Any:
                    return self.provider.query_kline_exchange(
                        list(batch),
                        begin_date=_yyyymmdd(trading_day),
                        end_date=_yyyymmdd(trading_day),
                        kline_type="DAY",
                        trading_days=[_yyyymmdd(trading_day)],
                    )

                exchange, normalized = self._request(
                    daily_call,
                    "daily_bar",
                    raw_writer,
                    normalizer,
                    request_receipts,
                )
                payload = exchange.payload
                if not isinstance(payload, Mapping):
                    raise DailyUpdateError("daily-bar response is not a member-key mapping")
                response_keys = [str(key) for key in payload]
                if len(response_keys) != len(set(response_keys)) or set(response_keys) != set(
                    batch
                ):
                    raise DailyUpdateError(
                        "daily-bar response member keys do not equal the exact request "
                        f"for {trading_day}"
                    )
                for member in batch:
                    frame = payload[member]
                    if frame is None:
                        empty_member_count += 1
                    else:
                        try:
                            if len(frame) == 0:
                                empty_member_count += 1
                        except TypeError as exc:
                            raise DailyUpdateError(
                                "daily-bar member has no measurable row count"
                            ) from exc
                rows = self._read_normalized_rows(normalized, "main")
                if normalized.normalized_count != len(rows) or normalized.quarantined_count != 0:
                    raise DailyUpdateError("daily-bar normalized row count does not reconcile")
                seen_symbols: set[str] = set()
                for row in rows:
                    symbol = str(row.get("provider_symbol") or "")
                    if symbol not in set(batch):
                        raise DailyUpdateError("daily-bar output contains an unrequested security")
                    if symbol in seen_symbols:
                        raise DailyUpdateError("daily-bar output repeats a security/date key")
                    if _to_date(row.get("kline_time")) != trading_day:
                        raise DailyUpdateError("daily-bar output contains an out-of-window date")
                    seen_symbols.add(symbol)
                day_rows.extend(rows)
                request_ids.append(str(exchange.envelope.request_id))
                normalized_ids.append(normalized.normalization_run_id)
            new_rows_by_month.setdefault(trading_day.strftime("%Y-%m"), []).extend(day_rows)
            returned_bar_count += len(day_rows)
            session_evidence.append(
                {
                    "trade_date": trading_day.isoformat(),
                    "expected_member_count": len(symbols),
                    "expected_symbols_sha256": _hash_json(symbols),
                    "response_member_count": len(symbols),
                    "returned_bar_count": len(day_rows),
                    "explicit_empty_member_count": empty_member_count,
                    "request_ids": request_ids,
                    "normalization_run_ids": normalized_ids,
                }
            )
            self._emit(
                "SESSION_DAILY_BAR_PASS",
                trade_date=trading_day.isoformat(),
                expected_member_count=len(symbols),
                returned_bar_count=len(day_rows),
                explicit_empty_member_count=empty_member_count,
            )
        if returned_bar_count == 0:
            raise DailyUpdateError("the requested sessions returned no daily-bar rows")

        # The captured rows are bounded to the requested sessions, normally
        # five for the initial June-boundary acceptance check.
        unit_contract = measure_volume_amount_units(
            [row for rows in new_rows_by_month.values() for row in rows]
        )
        current_snapshot = base
        canonical_runs: list[dict[str, Any]] = []
        readmodel_results: list[dict[str, Any]] = []
        for month in sorted(new_rows_by_month):
            month_rows = new_rows_by_month[month]
            month_partition = _partition_for_month(current_snapshot.partitions, month)
            scoped_ids = set(identity_run_ids_by_month.get(month, set()))
            scoped_ids.update(stock_basic_run_ids)
            prior_month_rows = 0
            if month_partition is not None:
                prior_month_rows = int(month_partition["row_count"])
                prior_source_id = str(month_partition["source_canonical_run_id"])
                _, prior_manifest, _ = read_canonical_run_manifest(
                    self.conn,
                    prior_source_id,
                    normalized_root=self.normalized_root,
                )
                prior_inputs = prior_manifest.get("input_normalized_runs")
                if not isinstance(prior_inputs, list):
                    raise DailyUpdateError("open-month Canonical source manifest is malformed")
                scoped_ids.update(
                    str(item["run_id"])
                    for item in prior_inputs
                    if isinstance(item, dict)
                    and item.get("run_id")
                    and (
                        item.get("role") == "identity_master"
                        or item.get("provider_dataset") == "daily_bar"
                    )
                )
            scoped_ids.update(
                receipt["normalization_run_id"]
                for receipt in request_receipts
                if receipt["provider_dataset"] == "daily_bar" and receipt["trade_month"] == month
            )
            if not scoped_ids:
                raise DailyUpdateError(f"no governed inputs were captured for {month}")

            canonical = CanonicalRunner(
                self.conn,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
                scoped_input_run_ids=scoped_ids,
            ).run(self._now().astimezone(UTC), domains=("daily_bar",))
            if canonical.status != "SUCCESS":
                finding_summary = self.conn.execute(
                    "SELECT finding_class, blocking, count(*), min(substr(detail_json, 1, 300)) "
                    "FROM meta_canonical_reconciliation_finding "
                    "WHERE canonical_run_id = ? "
                    "GROUP BY finding_class, blocking ORDER BY finding_class, blocking",
                    [canonical.canonical_run_id],
                ).fetchall()
                raise DailyUpdateError(
                    f"Canonical month {month} did not succeed "
                    f"(status={canonical.status}, findings={finding_summary})"
                )
            _, canonical_manifest, _ = read_canonical_run_manifest(
                self.conn,
                canonical.canonical_run_id,
                normalized_root=self.normalized_root,
            )
            partitions = canonical_manifest.get("daily_bar_partitions")
            if (
                not isinstance(partitions, list)
                or len(partitions) != 1
                or not isinstance(partitions[0], dict)
                or str(partitions[0].get("partition")) != month
            ):
                raise DailyUpdateError(
                    f"Canonical {month} did not emit exactly one monthly partition"
                )
            expected_rows = prior_month_rows + len(month_rows)
            if (
                canonical.selected_count != expected_rows
                or int(partitions[0].get("row_count", -1)) != expected_rows
            ):
                raise DailyUpdateError(
                    f"Canonical {month} count does not reconcile with the accepted append"
                )
            verify_canonical_run_for_consumption(
                self.conn,
                canonical.canonical_run_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )

            source_ids = [
                str(item["source_canonical_run_id"])
                for item in current_snapshot.partitions
                if str(item.get("partition") or "") != month
            ]
            source_ids.append(canonical.canonical_run_id)
            snapshot = SnapshotBuilder(
                self.conn,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            ).build_daily_partition_set(source_ids)
            verified = verify_snapshot(
                self.conn,
                snapshot.snapshot_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
                retain_domain_rows=False,
            )
            readmodel = self._rebuild_readmodel(snapshot.snapshot_id)
            readmodel_results.append(asdict(readmodel))
            current_snapshot = _AcceptedSnapshot(
                snapshot_id=snapshot.snapshot_id,
                through=_snapshot_through(verified.manifest),
                manifest=verified.manifest,
            )
            canonical_runs.append(
                {
                    "month": month,
                    "canonical_run_id": canonical.canonical_run_id,
                    "selected_count": canonical.selected_count,
                    "existing_partition_row_count": prior_month_rows,
                    "new_bar_row_count": len(month_rows),
                    "snapshot_id": snapshot.snapshot_id,
                    "readmodel_db_uri": readmodel.db_uri,
                }
            )
            self._emit(
                "MONTH_SNAPSHOT_PASS",
                month=month,
                canonical_rows=canonical.selected_count,
                snapshot_id=snapshot.snapshot_id,
            )

        if current_snapshot.through < sessions[-1]:
            raise DailyUpdateError("final Snapshot does not reach the last requested session")

        manifest_doc = {
            "manifest_schema": "ashare-daily-update-v1",
            "update_run_id": update_run_id,
            "started_at": started.isoformat(),
            "completed_at": self._now().astimezone(UTC).isoformat(),
            "through_date": target.isoformat(),
            "accepted_boundary_before_update": base.through.isoformat(),
            "base_snapshot_id": base.snapshot_id,
            "snapshot_id": current_snapshot.snapshot_id,
            "snapshot_manifest_hash": self._snapshot_manifest_hash(current_snapshot.snapshot_id),
            "repository": {"commit_sha": repository.commit_sha, "dirty": repository.dirty},
            "markets": list(_MARKETS),
            "session_count": len(sessions),
            "expected_member_count": expected_member_count,
            "returned_bar_count": returned_bar_count,
            "sessions": session_evidence,
            "unit_sanity_check": unit_contract,
            "request_receipts": request_receipts,
            "canonical_months": canonical_runs,
            "readmodels": readmodel_results,
            "acceptance": "SUCCESS",
        }
        manifest_bytes = json.dumps(
            manifest_doc, sort_keys=True, indent=2, ensure_ascii=False, default=str
        ).encode("utf-8")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = self.data_root / "manifests" / "daily_update" / f"run={update_run_id}.json"
        manifest_uri = to_logical_uri(self.data_root, manifest_path)
        write_file_atomic(
            manifest_path,
            manifest_bytes,
            expected_sha256=manifest_hash,
            allow_existing_identical=True,
        )
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_hash:
            raise DailyUpdateError("daily update manifest failed its post-write integrity check")
        self._record_success(
            update_run_id=update_run_id,
            through=target,
            base_snapshot_id=base.snapshot_id,
            snapshot_id=current_snapshot.snapshot_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            repository=repository,
            session_count=len(sessions),
            expected_member_count=expected_member_count,
            returned_bar_count=returned_bar_count,
            started=started,
            completed=self._now().astimezone(UTC),
        )
        retention_status = self._retain_evidence(update_run_id)
        return DailyUpdateResult(
            status="SUCCESS",
            through_date=target,
            accepted_through=current_snapshot.through,
            snapshot_id=current_snapshot.snapshot_id,
            update_run_id=update_run_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            idempotent_replay=False,
            expected_member_count=expected_member_count,
            returned_bar_count=returned_bar_count,
            retention_status=retention_status,
        )

    def _retain_evidence(self, update_run_id: str) -> str:
        if self.evidence_backup_root is None:
            self._emit(
                "EVIDENCE_RETENTION_NOT_CONFIGURED",
                update_run_id=update_run_id,
                warning="accepted run is not copied to a secondary evidence root",
            )
            return "NOT_CONFIGURED"
        from ashare_state.update.retention import archive_daily_update

        try:
            result = archive_daily_update(
                self.conn,
                update_run_id=update_run_id,
                data_root=self.data_root,
                raw_root=self.raw_root,
                secondary_root=self.evidence_backup_root,
            )
        except Exception as exc:  # noqa: BLE001 - retention must not undo data acceptance
            self._emit(
                "EVIDENCE_RETENTION_FAILED",
                update_run_id=update_run_id,
                failure_class=type(exc).__name__,
                warning="daily update is accepted, but its evidence backup needs attention",
            )
            return "BACKUP_FAILED"
        self._emit(
            "EVIDENCE_RETENTION_SUCCESS",
            update_run_id=result.update_run_id,
            archive_uri=result.archive_uri,
            archive_sha256=result.archive_sha256,
            entry_count=result.entry_count,
        )
        return "SUCCESS"

    def _request(
        self,
        call: Callable[[], Any],
        dataset: str,
        raw_writer: AnchoredRawEvidenceWriter,
        normalizer: NormalizationRunner,
        receipts: list[dict[str, Any]],
    ) -> tuple[Any, Any]:
        try:
            exchange = call()
        except Exception as exc:  # noqa: BLE001 - persist attached failed exchange safely
            failed_exchange = getattr(exc, "exchange", None)
            if failed_exchange is not None:
                with suppress(Exception):
                    self._persist_and_normalize(
                        failed_exchange, dataset, raw_writer, normalizer, receipts
                    )
            raise DailyUpdateError(f"Provider request failed for {dataset}") from None
        if str(getattr(getattr(exchange, "envelope", None), "provider_dataset", "")) != dataset:
            raise DailyUpdateError(f"Provider returned the wrong typed exchange for {dataset}")
        normalized = self._persist_and_normalize(
            exchange, dataset, raw_writer, normalizer, receipts
        )
        return exchange, normalized

    def _persist_and_normalize(
        self,
        exchange: Any,
        dataset: str,
        raw_writer: AnchoredRawEvidenceWriter,
        normalizer: NormalizationRunner,
        receipts: list[dict[str, Any]],
    ) -> Any:
        persisted = raw_writer.write_exchange(exchange)
        result = normalizer.run(provider_dataset=dataset, request_id=persisted.request_id)
        if result.status != "SUCCESS" or result.quarantined_count:
            raise DailyUpdateError(
                f"normalization blocked for {dataset} ({result.error_class or result.status})"
            )
        receipt = {
            "provider_dataset": dataset,
            "request_id": persisted.request_id,
            "raw_evidence_uri": persisted.evidence_uri,
            "raw_evidence_hash": persisted.evidence_hash,
            "normalization_run_id": result.normalization_run_id,
            "normalization_manifest_uri": result.manifest_uri,
            "normalization_manifest_hash": result.manifest_hash,
        }
        if dataset == "daily_bar":
            params = getattr(exchange.envelope, "request_params", {}) or {}
            start_date = int(params.get("begin_date", 0))
            yyyymm = start_date // 100
            receipt["trade_month"] = f"{yyyymm // 100:04d}-{yyyymm % 100:02d}"
        receipts.append(receipt)
        return result

    def _read_normalized_rows(self, result: Any, output_name: str) -> list[dict[str, Any]]:
        if not result.manifest_uri or not result.manifest_hash:
            raise DailyUpdateError("normalized output manifest is missing")
        path = self.normalized_root / result.manifest_uri
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != result.manifest_hash:
                raise DailyUpdateError("normalized manifest hash differs from its ledger seal")
            manifest = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DailyUpdateError("normalized output manifest cannot be read") from exc
        matches = [
            item
            for item in manifest.get("outputs", [])
            if isinstance(item, dict) and item.get("output_name") == output_name
        ]
        if len(matches) != 1:
            raise DailyUpdateError(f"normalized output {output_name!r} is not uniquely sealed")
        entry = matches[0]
        output_path = self.normalized_root / str(entry.get("uri") or "")
        try:
            output_bytes = output_path.read_bytes()
            if hashlib.sha256(output_bytes).hexdigest() != str(entry.get("content_hash")):
                raise DailyUpdateError("normalized output bytes differ from their manifest hash")
            frame = pl.read_parquet(output_path)
        except DailyUpdateError:
            raise
        except Exception as exc:  # noqa: BLE001 - safe artifact boundary
            raise DailyUpdateError("normalized output artifact cannot be read") from exc
        if frame.height != int(entry.get("row_count", -1)):
            raise DailyUpdateError("normalized output row count differs from its manifest")
        return frame.to_dicts()

    def _latest_accepted_snapshot(self) -> _AcceptedSnapshot:
        accepted_update: tuple[Any, ...] | None = None
        try:
            has_update_ledger = self.conn.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = 'meta_daily_update_run'"
            ).fetchone()[0]
            if has_update_ledger:
                accepted_update = self.conn.execute(
                    "SELECT update_run_id, status, snapshot_id, through_date, manifest_uri, "
                    "manifest_hash, repository_commit_sha, worktree_dirty, base_snapshot_id "
                    "FROM meta_daily_update_run "
                    "WHERE status IN ('BASELINE', 'SUCCESS') "
                    "ORDER BY through_date DESC, "
                    "CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END DESC, "
                    "completed_at DESC, update_run_id DESC LIMIT 1"
                ).fetchone()
            rows = []
            if accepted_update is None:
                rows = self.conn.execute(
                    "SELECT snapshot_id FROM meta_snapshot_build "
                    "WHERE status='SUCCESS' AND requested_domains_json='[\"daily_bar\"]' "
                    "ORDER BY completed_at DESC, snapshot_id DESC LIMIT 1"
                ).fetchall()
        except Exception as exc:  # noqa: BLE001 - missing/malformed baseline is a clear blocker
            raise DailyUpdateError(
                "daily Snapshot ledger is unavailable; initialize and restore the accepted baseline"
            ) from exc
        if accepted_update is None and not rows:
            raise DailyUpdateError(
                "no accepted daily-bar Snapshot exists in the configured database; "
                "restore the accepted history baseline before updating"
            )
        snapshot_id = str(accepted_update[2]) if accepted_update is not None else str(rows[0][0])
        try:
            verified = verify_snapshot(
                self.conn,
                snapshot_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
                retain_domain_rows=False,
            )
            through = _snapshot_through(verified.manifest)
            if accepted_update is not None:
                if str(accepted_update[1]) == "SUCCESS":
                    self._verify_update_manifest(accepted_update, verified.manifest)
                elif str(accepted_update[1]) != "BASELINE":
                    raise DailyUpdateError("daily update ledger has an unsupported accepted status")
                ledger_through = _to_date(accepted_update[3])
                if ledger_through > through:
                    through = ledger_through
        except Exception as exc:  # noqa: BLE001 - never fall back behind a damaged latest seal
            raise DailyUpdateError(
                f"latest successful daily Snapshot {snapshot_id} failed verification"
            ) from exc
        return _AcceptedSnapshot(snapshot_id, through, verified.manifest)

    def _verify_update_manifest(
        self, record: tuple[Any, ...], snapshot_manifest: Mapping[str, Any]
    ) -> None:
        (
            update_run_id,
            _status,
            snapshot_id,
            through_date,
            manifest_uri,
            manifest_hash,
            commit_sha,
            dirty,
            base_snapshot_id,
        ) = record
        if dirty or not manifest_uri or not manifest_hash:
            raise DailyUpdateError("accepted daily update ledger record is incomplete or dirty")
        try:
            path = physical_from_logical_uri(self.data_root, str(manifest_uri))
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != str(manifest_hash):
                raise DailyUpdateError("accepted daily update manifest hash does not match")
            manifest = json.loads(content.decode("utf-8"))
        except DailyUpdateError:
            raise
        except Exception as exc:  # noqa: BLE001 - manifest is an acceptance boundary
            raise DailyUpdateError("accepted daily update manifest cannot be read") from exc
        if not isinstance(manifest, dict):
            raise DailyUpdateError("accepted daily update manifest is malformed")
        repository = manifest.get("repository")
        if (
            manifest.get("acceptance") != "SUCCESS"
            or manifest.get("update_run_id") != str(update_run_id)
            or manifest.get("through_date") != _to_date(through_date).isoformat()
            or manifest.get("base_snapshot_id") != str(base_snapshot_id)
            or manifest.get("snapshot_id") != str(snapshot_id)
            or not isinstance(repository, dict)
            or repository.get("commit_sha") != str(commit_sha)
            or repository.get("dirty") is not False
            or manifest.get("snapshot_manifest_hash")
            != self._snapshot_manifest_hash(str(snapshot_id))
            or snapshot_manifest.get("snapshot_id") != str(snapshot_id)
        ):
            raise DailyUpdateError(
                "accepted daily update manifest does not match its ledger/Snapshot"
            )

    def _record_initial_baseline(
        self, baseline: _AcceptedSnapshot, repository: RepositoryIdentity
    ) -> None:
        """Pin the pre-update accepted Snapshot so interrupted outputs stay unaccepted."""
        now = self._now().astimezone(UTC)
        baseline_id = f"baseline:{baseline.snapshot_id}"
        try:
            self.conn.execute("BEGIN TRANSACTION")
            existing = self.conn.execute(
                "SELECT 1 FROM meta_daily_update_run "
                "WHERE status IN ('BASELINE', 'SUCCESS') LIMIT 1"
            ).fetchone()
            if existing is None:
                self.conn.execute(
                    "INSERT INTO meta_daily_update_run ("
                    "update_run_id, through_date, base_snapshot_id, snapshot_id, "
                    "manifest_uri, manifest_hash, repository_commit_sha, worktree_dirty, "
                    "session_count, expected_member_count, returned_bar_count, status, "
                    "started_at, completed_at"
                    ") VALUES (?, ?, ?, ?, NULL, NULL, ?, FALSE, 0, 0, 0, 'BASELINE', ?, ?)",
                    [
                        baseline_id,
                        baseline.through,
                        baseline.snapshot_id,
                        baseline.snapshot_id,
                        repository.commit_sha,
                        now,
                        now,
                    ],
                )
            self.conn.execute("COMMIT")
        except Exception as exc:  # noqa: BLE001 - rollback baseline pin on failure
            with suppress(Exception):
                self.conn.execute("ROLLBACK")
            raise DailyUpdateError("cannot pin the pre-update accepted Snapshot") from exc

    def _rebuild_readmodel(self, snapshot_id: str) -> Any:
        from ashare_state.readmodel.duckdb_model import DuckDBReadModel

        readmodel = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        result = readmodel.rebuild(snapshot_id)
        readmodel.verify_readmodel(snapshot_id)
        return result

    def _snapshot_manifest_hash(self, snapshot_id: str) -> str:
        row = self.conn.execute(
            "SELECT manifest_hash FROM meta_snapshot_build WHERE snapshot_id = ?", [snapshot_id]
        ).fetchone()
        if row is None or not row[0]:
            raise DailyUpdateError("accepted Snapshot has no manifest hash")
        return str(row[0])

    def _record_success(
        self,
        *,
        update_run_id: str,
        through: date,
        base_snapshot_id: str,
        snapshot_id: str,
        manifest_uri: str,
        manifest_hash: str,
        repository: RepositoryIdentity,
        session_count: int,
        expected_member_count: int,
        returned_bar_count: int,
        started: datetime,
        completed: datetime,
    ) -> None:
        try:
            self.conn.execute("BEGIN TRANSACTION")
            self.conn.execute(
                "INSERT INTO meta_daily_update_run ("
                "update_run_id, through_date, base_snapshot_id, snapshot_id, manifest_uri, "
                "manifest_hash, repository_commit_sha, worktree_dirty, session_count, "
                "expected_member_count, returned_bar_count, status, started_at, completed_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUCCESS', ?, ?)",
                [
                    update_run_id,
                    through,
                    base_snapshot_id,
                    snapshot_id,
                    manifest_uri,
                    manifest_hash,
                    repository.commit_sha,
                    repository.dirty,
                    session_count,
                    expected_member_count,
                    returned_bar_count,
                    started,
                    completed,
                ],
            )
            self.conn.execute("COMMIT")
        except Exception as exc:  # noqa: BLE001 - rollback record attempt, preserve immutable artifacts
            with suppress(Exception):
                self.conn.execute("ROLLBACK")
            raise DailyUpdateError("daily update acceptance ledger commit failed") from exc

    def _emit(self, stage: str, **fields: object) -> None:
        self._progress({"stage": stage, **fields})


def _partition_for_month(partitions: Sequence[dict[str, Any]], month: str) -> dict[str, Any] | None:
    matches = [item for item in partitions if str(item.get("partition") or "") == month]
    if len(matches) > 1:
        raise DailyUpdateError(f"accepted daily Snapshot has duplicate partition {month}")
    if not matches:
        return None
    if not matches[0].get("source_canonical_run_id"):
        raise DailyUpdateError(
            f"accepted daily Snapshot partition {month} lacks its Canonical source"
        )
    return matches[0]


def _snapshot_through(manifest: Mapping[str, Any]) -> date:
    artifacts = manifest.get("artifacts")
    daily = artifacts.get("daily_bar") if isinstance(artifacts, dict) else None
    partitions = daily.get("partitions") if isinstance(daily, dict) else None
    if not isinstance(partitions, list) or not partitions:
        raise DailyUpdateError("verified daily Snapshot has no partitions")
    days = [
        date.fromisoformat(str(item["max_trade_date"])[:10])
        for item in partitions
        if isinstance(item, dict) and item.get("max_trade_date")
    ]
    if len(days) != len(partitions):
        raise DailyUpdateError("verified daily Snapshot has a malformed partition date")
    return max(days)


def _security_symbols(payload: Any) -> list[str]:
    if not isinstance(payload, list) or not payload:
        raise DailyUpdateError("historical security universe is empty or malformed")
    symbols: list[str] = []
    for value in payload:
        if not isinstance(value, str):
            raise DailyUpdateError("historical security universe contains a non-string key")
        symbol = value.strip().upper()
        if len(symbol) != 9 or symbol[6:] not in (".SH", ".SZ") or not symbol[:6].isdigit():
            raise DailyUpdateError(
                "historical security universe contains an unsupported market key"
            )
        symbols.append(symbol)
    if len(symbols) != len(set(symbols)):
        raise DailyUpdateError("historical security universe contains duplicate keys")
    return sorted(symbols)


def _calendar_dates(values: list[Any]) -> list[date]:
    result = [_to_date(value) for value in values]
    if len(result) != len(set(result)):
        raise DailyUpdateError("Provider calendar contains duplicate sessions")
    return sorted(result)


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError as exc:
            raise DailyUpdateError("Provider response contains an invalid date") from exc
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise DailyUpdateError("Provider response contains an invalid date") from exc


def _require_date(value: date) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError("through must be a date, not a datetime")
    return value


def _yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _chunks(values: Sequence[str], size: int) -> list[tuple[str, ...]]:
    return [tuple(values[start : start + size]) for start in range(0, len(values), size)]


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()
