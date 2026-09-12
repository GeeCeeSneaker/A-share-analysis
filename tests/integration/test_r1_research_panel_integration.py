"""CR-7 R1 fixed-fixture ReadModel -> panel -> reader integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_snapshot import AS_OF_LATE, _canonical, _persist_raw, _seed_base

from ashare_state.readmodel import DuckDBReadModel
from ashare_state.research import (
    ResearchPanelBuilder,
    ResearchPanelReader,
    ResearchSplit,
    load_research_security_daily,
)
from ashare_state.snapshot import SnapshotBuilder


@pytest.mark.integration
def test_verified_readmodel_research_panel_reader_replay(
    conn,
    env_root,
    tmp_path: Path,
) -> None:
    """A fixed offline source reaches the public reader only via ReadModel."""
    _seed_base(conn, env_root)
    _persist_raw(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        surface="daily_bar",
        request_id="req-r1-bars",
        payload=[
            {
                "SECURITY_CODE": "600000",
                "MARKET_CODE": "1",
                "KLINE_TIME": 20200101,
                "KLINE_TYPE": "DAY",
                "OPEN_PRICE": "10.0",
                "HIGH_PRICE": "11.0",
                "LOW_PRICE": "9.0",
                "CLOSE_PRICE": "10.5",
                "VOLUME": "100",
                "AMOUNT": "2000.0",
            },
            {
                "SECURITY_CODE": "600000",
                "MARKET_CODE": "1",
                "KLINE_TIME": 20240101,
                "KLINE_TYPE": "DAY",
                "OPEN_PRICE": "11.0",
                "HIGH_PRICE": "12.0",
                "LOW_PRICE": "10.0",
                "CLOSE_PRICE": "11.5",
                "VOLUME": "110",
                "AMOUNT": "2200.0",
            },
            {
                "SECURITY_CODE": "600000",
                "MARKET_CODE": "1",
                "KLINE_TIME": 20260101,
                "KLINE_TYPE": "DAY",
                "OPEN_PRICE": "12.0",
                "HIGH_PRICE": "13.0",
                "LOW_PRICE": "11.0",
                "CLOSE_PRICE": "12.5",
                "VOLUME": "120",
                "AMOUNT": "2400.0",
            },
            {
                "SECURITY_CODE": "000001",
                "MARKET_CODE": "2",
                "KLINE_TIME": 20200101,
                "KLINE_TYPE": "DAY",
                "OPEN_PRICE": "20.0",
                "HIGH_PRICE": "21.0",
                "LOW_PRICE": "19.0",
                "CLOSE_PRICE": "20.5",
                "VOLUME": "200",
                "AMOUNT": "4000.0",
            },
            {
                "SECURITY_CODE": "000001",
                "MARKET_CODE": "2",
                "KLINE_TIME": 20240101,
                "KLINE_TYPE": "DAY",
                "OPEN_PRICE": "21.0",
                "HIGH_PRICE": "22.0",
                "LOW_PRICE": "20.0",
                "CLOSE_PRICE": "21.5",
                "VOLUME": "210",
                "AMOUNT": "4200.0",
            },
            {
                "SECURITY_CODE": "000001",
                "MARKET_CODE": "2",
                "KLINE_TIME": 20260101,
                "KLINE_TYPE": "DAY",
                "OPEN_PRICE": "22.0",
                "HIGH_PRICE": "23.0",
                "LOW_PRICE": "21.0",
                "CLOSE_PRICE": "22.5",
                "VOLUME": "220",
                "AMOUNT": "4400.0",
            },
        ],
    )
    canonical = _canonical(
        conn,
        env_root,
        AS_OF_LATE,
        domains=("daily_bar",),
    )
    assert canonical.status == "SUCCESS"
    snapshot = SnapshotBuilder(
        conn,
        raw_root=env_root["raw"],
        normalized_root=env_root["normalized"],
    ).build(canonical.canonical_run_id)
    DuckDBReadModel(
        conn,
        raw_root=env_root["raw"],
        normalized_root=env_root["normalized"],
    ).rebuild(snapshot.snapshot_id)

    builder = ResearchPanelBuilder(
        conn,
        raw_root=env_root["raw"],
        normalized_root=env_root["normalized"],
        research_root=tmp_path / "research",
    )
    result = builder.build_from_readmodel(
        snapshot.snapshot_id,
        build_timestamp="2026-09-12T00:00:00+00:00",
    )
    manifest_path = tmp_path / "research" / result.manifest_uri
    development = load_research_security_daily(
        manifest_path,
        split=ResearchSplit.DEVELOPMENT,
        columns=["trade_date", "symbol", "close", "source_snapshot_id"],
    )
    validation = load_research_security_daily(manifest_path, split="validation_a")
    holdout = load_research_security_daily(manifest_path, split="holdout")

    assert development.height == 2
    assert validation.height == 2
    assert holdout.height == 2
    assert set(development.get_column("symbol").to_list()) == {"600000", "000001"}
    assert set(development.get_column("source_snapshot_id").to_list()) == {snapshot.snapshot_id}
    assert builder.index_panel_status() == "DISABLED_UNVERIFIED_INDEX_IDENTITY"

    manifest = ResearchPanelReader.from_manifest(manifest_path).manifest
    assert manifest.publication_mode == "AUTHORITATIVE_READMODEL"
    assert manifest.identity_source_kind == "VERIFIED_CR2_SECURITY_MASTER"
    assert len(manifest.identity_sources) == 1
    identity_source = manifest.identity_sources[0]
    assert identity_source.canonical_run_id == canonical.canonical_run_id
    assert identity_source.normalization_run_id
    assert identity_source.normalized_manifest_hash
    assert identity_source.normalized_output_hash
    assert identity_source.normalized_output_uri

    replay = builder.build_from_readmodel(
        snapshot.snapshot_id,
        build_timestamp="2026-09-12T00:00:00+00:00",
    )
    assert replay.content_hash == result.content_hash
    assert replay.manifest_hash == result.manifest_hash
    assert replay.idempotent_replay is True
