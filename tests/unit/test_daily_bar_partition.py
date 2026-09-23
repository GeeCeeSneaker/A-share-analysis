from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import ashare_state.canonical.daily_bar as daily_bar
from ashare_state.canonical.daily_bar import DailyBarPartitionError, write_daily_bar_partitions


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


def _write(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    market_as_of: datetime = datetime(2026, 7, 1, tzinfo=UTC),
) -> tuple[dict[str, Any], ...]:
    return write_daily_bar_partitions(
        rows,
        normalized_root=root,
        market_as_of=market_as_of,
        source_vintage_as_of=market_as_of,
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


def test_changed_closed_month_fails_before_publishing_new_revision(tmp_path: Path) -> None:
    original = _write(tmp_path, [_row()])
    original_manifests = list(tmp_path.rglob("manifest.json"))

    with pytest.raises(DailyBarPartitionError, match="closed daily-bar month 2026-06"):
        _write(tmp_path, [_row(close=10.5)])

    assert list(tmp_path.rglob("manifest.json")) == original_manifests
    assert len(original) == 1


def test_closed_month_uses_exchange_local_market_clock(tmp_path: Path) -> None:
    before_local_month_end = datetime(2026, 6, 30, 15, 0, tzinfo=UTC)
    _write(tmp_path, [_row()], market_as_of=before_local_month_end)
    after_local_month_end = datetime(2026, 6, 30, 16, 30, tzinfo=UTC)

    with pytest.raises(DailyBarPartitionError, match="closed daily-bar month 2026-06"):
        _write(tmp_path, [_row(close=10.5)], market_as_of=after_local_month_end)


def test_open_month_content_change_gets_a_new_logical_revision(tmp_path: Path) -> None:
    clock = datetime(2026, 6, 15, tzinfo=UTC)
    first = write_daily_bar_partitions(
        [_row()],
        normalized_root=tmp_path,
        market_as_of=clock,
        source_vintage_as_of=clock,
    )[0]
    second = write_daily_bar_partitions(
        [_row(close=10.5)],
        normalized_root=tmp_path,
        market_as_of=clock,
        source_vintage_as_of=clock,
    )[0]

    assert first["logical_content_hash"] != second["logical_content_hash"]
    assert first["data_revision"] != second["data_revision"]
    assert first["fact_artifact"]["uri"] != second["fact_artifact"]["uri"]


def test_new_month_append_leaves_closed_month_artifacts_untouched(tmp_path: Path) -> None:
    june_clock = datetime(2026, 6, 30, 23, 59, tzinfo=UTC)
    june = _write(tmp_path, [_row()], market_as_of=june_clock)[0]
    june_fact = tmp_path / june["fact_artifact"]["uri"]
    june_bytes = june_fact.read_bytes()

    july_clock = datetime(2026, 7, 1, tzinfo=UTC)
    july = _write(
        tmp_path,
        [_row(trade_date=date(2026, 7, 1))],
        market_as_of=july_clock,
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
