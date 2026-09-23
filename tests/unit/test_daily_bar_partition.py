from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import ashare_state.canonical.daily_bar as daily_bar
from ashare_state.canonical.daily_bar import DailyBarPartitionError, write_daily_bar_partitions
from ashare_state.canonical.daily_bar_event import daily_bar_event_eligibility_binding


def _row(
    *,
    close: float = 10.0,
    security_id: str | None = None,
    trade_date: date = date(2026, 6, 30),
) -> dict[str, Any]:
    identity = security_id or "00000000-0000-0000-0000-000000000001"
    return {
        "canonical_domain": "daily_bar",
        "canonical_key": f'["{identity}","{trade_date.isoformat()}"]',
        "canonical_run_id": "excluded-run-marker",
        "security_id": identity,
        "trade_date": trade_date,
        "open": 9.0,
        "high": 11.0,
        "low": 8.0,
        "close": close,
        "pre_close": 9.5,
        "volume": 1000.0,
        "amount": 10000.0,
        "provider": "fixture-provider",
        "provider_dataset": "daily_bar",
        "request_id": f"request-{identity[-1]}",
    }


def _vintage_evidence(
    *,
    received_at: str = "2026-07-01T00:00:00+00:00",
    run_id: str = "normalized-daily-run",
) -> list[dict[str, str]]:
    return [
        {
            "run_id": run_id,
            "role": "source",
            "provider": "amazingdata",
            "provider_dataset": "daily_bar",
            "endpoint": "MarketData.query_kline",
            "raw_request_id": "request-daily-run",
            "raw_evidence_uri": "raw/daily/request-daily-run.json",
            "raw_evidence_hash": "a" * 64,
            "normalized_manifest_uri": "normalized/daily/run/manifest.json",
            "normalized_manifest_hash": "b" * 64,
            "received_at": received_at,
        }
    ]


def _write(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    source_snapshot_as_of: datetime = datetime(2026, 7, 1, tzinfo=UTC),
) -> tuple[dict[str, Any], ...]:
    months = {str(row["trade_date"])[:7] for row in rows}
    return write_daily_bar_partitions(
        rows,
        normalized_root=root,
        source_snapshot_as_of=source_snapshot_as_of,
        source_vintage_evidence_by_partition={
            month: _vintage_evidence(
                received_at=source_snapshot_as_of.isoformat()
            )
            for month in months
        },
    )


def test_layout_rewrite_preserves_logical_revision(tmp_path: Path, monkeypatch) -> None:
    original = _write(tmp_path, [_row()])[0]
    monkeypatch.setattr(daily_bar, "DAILY_BAR_LAYOUT_REVISION", "l0-month-fixed16-test-rewrite")
    rewritten = _write(tmp_path, [_row()])[0]

    assert rewritten["data_revision"] == original["data_revision"]
    assert rewritten["logical_content_hash"] == original["logical_content_hash"]
    assert rewritten["layout_revision"] != original["layout_revision"]
    assert rewritten["artifact_set_hash"] != original["artifact_set_hash"]
    assert (tmp_path / original["fact_artifact"]["uri"]).is_file()
    assert (tmp_path / rewritten["fact_artifact"]["uri"]).is_file()


def test_partition_binds_event_contract_and_exact_later_source_vintage(tmp_path: Path) -> None:
    received_at = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)
    partition = write_daily_bar_partitions(
        [_row()],
        normalized_root=tmp_path,
        source_snapshot_as_of=received_at,
        source_vintage_evidence_by_partition={
            "2026-06": _vintage_evidence(received_at=received_at.isoformat())
        },
    )[0]
    manifest = json.loads(
        (tmp_path / partition["partition_manifest_uri"]).read_text(encoding="utf-8")
    )

    assert partition["source_vintage_as_of"] == received_at.isoformat()
    assert partition["market_as_of"] == "2026-06-30T07:00:00+00:00"
    assert manifest["source_vintage_as_of"] == received_at.isoformat()
    assert manifest["source_vintage_evidence"] == _vintage_evidence(
        received_at=received_at.isoformat()
    )
    assert manifest["event_eligibility"] == daily_bar_event_eligibility_binding()
    assert "market_available_at" not in manifest


def test_multi_month_partitions_bind_only_their_exact_source_vintages(tmp_path: Path) -> None:
    june_received = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    july_received = datetime(2026, 7, 2, 8, 0, tzinfo=UTC)
    partitions = write_daily_bar_partitions(
        [_row(trade_date=date(2026, 6, 30)), _row(trade_date=date(2026, 7, 1))],
        normalized_root=tmp_path,
        source_snapshot_as_of=datetime(2026, 7, 3, 8, 0, tzinfo=UTC),
        source_vintage_evidence_by_partition={
            "2026-06": _vintage_evidence(
                received_at=june_received.isoformat(), run_id="june-source-run"
            ),
            "2026-07": _vintage_evidence(
                received_at=july_received.isoformat(), run_id="july-source-run"
            ),
        },
    )

    assert [entry["partition"] for entry in partitions] == ["2026-06", "2026-07"]
    assert [entry["source_vintage_as_of"] for entry in partitions] == [
        june_received.isoformat(),
        july_received.isoformat(),
    ]
    assert [entry["source_vintage_evidence"][0]["run_id"] for entry in partitions] == [
        "june-source-run",
        "july-source-run",
    ]


def test_changed_closed_month_fails_before_publishing_new_revision(tmp_path: Path) -> None:
    original = _write(tmp_path, [_row()])
    original_manifests = list(tmp_path.rglob("manifest.json"))

    with pytest.raises(DailyBarPartitionError, match="closed daily-bar month 2026-06"):
        _write(tmp_path, [_row(close=10.5)])

    assert list(tmp_path.rglob("manifest.json")) == original_manifests
    assert len(original) == 1


def test_closed_month_uses_exchange_local_market_clock(tmp_path: Path) -> None:
    before_local_month_end = datetime(2026, 6, 30, 15, 0, tzinfo=UTC)
    _write(tmp_path, [_row()], source_snapshot_as_of=before_local_month_end)
    after_local_month_end = datetime(2026, 6, 30, 16, 30, tzinfo=UTC)

    with pytest.raises(DailyBarPartitionError, match="closed daily-bar month 2026-06"):
        _write(tmp_path, [_row(close=10.5)], source_snapshot_as_of=after_local_month_end)


def test_open_month_content_change_gets_a_new_logical_revision(tmp_path: Path) -> None:
    clock = datetime(2026, 6, 30, 7, 0, tzinfo=UTC)
    first = write_daily_bar_partitions(
        [_row()],
        normalized_root=tmp_path,
        source_snapshot_as_of=clock,
        source_vintage_evidence_by_partition={
            "2026-06": _vintage_evidence(received_at=clock.isoformat())
        },
    )[0]
    second = write_daily_bar_partitions(
        [_row(close=10.5)],
        normalized_root=tmp_path,
        source_snapshot_as_of=clock,
        source_vintage_evidence_by_partition={
            "2026-06": _vintage_evidence(received_at=clock.isoformat())
        },
    )[0]

    assert first["logical_content_hash"] != second["logical_content_hash"]
    assert first["data_revision"] != second["data_revision"]
    assert first["fact_artifact"]["uri"] != second["fact_artifact"]["uri"]


def test_new_month_append_leaves_closed_month_artifacts_untouched(tmp_path: Path) -> None:
    june_clock = datetime(2026, 6, 30, 23, 59, tzinfo=UTC)
    june = _write(tmp_path, [_row()], source_snapshot_as_of=june_clock)[0]
    june_fact = tmp_path / june["fact_artifact"]["uri"]
    june_bytes = june_fact.read_bytes()

    july_clock = datetime(2026, 7, 1, 7, 0, tzinfo=UTC)
    july = _write(
        tmp_path,
        [_row(trade_date=date(2026, 7, 1))],
        source_snapshot_as_of=july_clock,
    )

    assert [entry["partition"] for entry in july] == ["2026-07"]
    assert june_fact.read_bytes() == june_bytes
    assert len(list(tmp_path.rglob("fact.parquet"))) == 2


def test_partition_manifest_is_the_last_published_file(tmp_path: Path, monkeypatch) -> None:
    original_write = daily_bar._immutable_write

    def fail_manifest(path: Path, payload: bytes) -> None:
        if path.name == "manifest.json":
            raise OSError("injected manifest publish failure")
        original_write(path, payload)

    monkeypatch.setattr(daily_bar, "_immutable_write", fail_manifest)
    with pytest.raises(OSError, match="injected manifest publish failure"):
        _write(tmp_path, [_row()])

    assert len(list(tmp_path.rglob("fact.parquet"))) == 1
    assert len(list(tmp_path.rglob("lineage.parquet"))) == 1
    assert list(tmp_path.rglob("manifest.json")) == []
