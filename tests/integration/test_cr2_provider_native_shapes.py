"""Focused CR-2 regressions for the observed AmazingData response shapes."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ashare_state.normalization.runner import NormalizationRunner
from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage.raw_anchor import _enroll_anchor
from ashare_state.storage.raw_writer import RawWriter


def _persist(
    conn: Any,
    roots: dict[str, Path],
    *,
    dataset: str,
    endpoint: str,
    request_id: str,
    payload: Any,
    surface: str,
) -> None:
    envelope = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=request_id,
        request_params={},
        request_params_hash=RawEnvelope.params_hash({}),
        requested_at="2026-09-15T00:00:00+00:00",
        received_at="2026-09-15T00:00:01+00:00",
        account_profile_id="TEST_PROFILE",
        normalization_surface=surface,
    )
    result = RawWriter(roots["raw"]).write(ProviderExchange(envelope, payload))
    meta = roots["raw"] / f"provider=amazingdata/dataset={dataset}/{request_id}.meta.json"
    _enroll_anchor(
        conn,
        roots["raw"],
        provider="amazingdata",
        provider_dataset=dataset,
        request_id=request_id,
        evidence_hash=hashlib.sha256(meta.read_bytes()).hexdigest(),
    )
    assert result.request_id == request_id


def _bar_frame(*, code: str | None = None, market: str | None = None) -> pl.DataFrame:
    row: dict[str, Any] = {
        "KLINE_TIME": [20240102],
        "KLINE_TYPE": ["DAY"],
        "OPEN_PRICE": [10.0],
        "HIGH_PRICE": [11.0],
        "LOW_PRICE": [9.0],
        "CLOSE_PRICE": [10.5],
        "PRE_CLOSE_PRICE": [10.0],
        "VOLUME": [100.0],
        "AMOUNT": [1050.0],
    }
    if code is not None:
        row["SECURITY_CODE"] = [code]
    if market is not None:
        row["MARKET_CODE"] = [market]
    return pl.DataFrame(row)


@pytest.mark.integration
def test_hist_scalar_symbols_normalize_without_inventing_pit_dates(conn, env_root):
    _persist(
        conn,
        env_root,
        dataset="hist_code_list",
        endpoint="BaseData.get_hist_code_list",
        request_id="hist-scalar",
        payload=["000001.SZ", "600000.SH"],
        surface="security_master",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="hist_code_list", request_id="hist-scalar")

    assert result.status == "SUCCESS"
    assert result.input_count == result.normalized_count == 2
    output = pl.read_parquet(
        env_root["normalized"]
        / "provider=amazingdata/dataset=hist_code_list/raw_request=hist-scalar"
        / "contract=cr2.1-v1"
        / f"run={result.normalization_run_id}/main.parquet"
    )
    assert set(output["provider_symbol"].to_list()) == {"000001.SZ", "600000.SH"}
    assert output["list_date"].to_list() == [None, None]


@pytest.mark.integration
@pytest.mark.parametrize("symbol", ["000001", "000001.XX"])
def test_hist_scalar_malformed_symbols_fail_closed(conn, env_root, symbol):
    _persist(
        conn,
        env_root,
        dataset="hist_code_list",
        endpoint="BaseData.get_hist_code_list",
        request_id=f"hist-invalid-{symbol.replace('.', '-')}",
        payload=[symbol],
        surface="security_master",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(
        provider_dataset="hist_code_list",
        request_id=f"hist-invalid-{symbol.replace('.', '-')}",
    )

    assert result.status == "BLOCKED"
    assert result.normalized_count == 0
    assert result.quarantined_count == 1


@pytest.mark.integration
def test_daily_bar_member_map_normalizes_every_present_member(conn, env_root):
    _persist(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        request_id="daily-member-map",
        payload={
            "600000.SH": _bar_frame(),
            "000001.SZ": _bar_frame(),
            "999999.SZ": None,
            "300000.SZ": pl.DataFrame(),
        },
        surface="daily_bar",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="daily_bar", request_id="daily-member-map")

    assert result.status == "SUCCESS"
    assert result.input_count == result.normalized_count == 2
    output = pl.read_parquet(
        env_root["normalized"]
        / "provider=amazingdata/dataset=daily_bar/raw_request=daily-member-map"
        / "contract=cr2.1-v1"
        / f"run={result.normalization_run_id}/main.parquet"
    )
    assert set(output["provider_symbol"].to_list()) == {"000001.SZ", "600000.SH"}
    assert "__provider_member_key__" not in output.columns


@pytest.mark.integration
def test_daily_bar_member_map_accepts_provider_lowercase_datetime_row(conn, env_root):
    frame = pl.DataFrame(
        {
            "code": ["000001.SZ"],
            "kline_time": [datetime(2024, 1, 2)],
            "open": [9.39],
            "high": [9.42],
            "low": [9.21],
            "close": [9.21],
            "volume": [115836645.0],
            "amount": [1075742252.45],
        }
    )
    _persist(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        request_id="daily-provider-row-shape",
        payload={"000001.SZ": frame},
        surface="daily_bar",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="daily_bar", request_id="daily-provider-row-shape")

    assert result.status == "SUCCESS"
    assert result.normalized_count == 1
    output = pl.read_parquet(
        env_root["normalized"]
        / "provider=amazingdata/dataset=daily_bar/raw_request=daily-provider-row-shape"
        / "contract=cr2.1-v1"
        / f"run={result.normalization_run_id}/main.parquet"
    )
    assert output["provider_symbol"].to_list() == ["000001.SZ"]
    assert output["kline_time"].to_list() == [20240102]


@pytest.mark.integration
def test_daily_bar_member_identity_conflict_is_quarantined_at_member_locator(conn, env_root):
    _persist(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        request_id="daily-member-conflict",
        payload={"600000.SH": _bar_frame(code="000001", market="2")},
        surface="daily_bar",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="daily_bar", request_id="daily-member-conflict")

    assert result.status == "BLOCKED"
    assert result.normalized_count == 0
    assert result.quarantined_count == 1
    row = conn.execute(
        "SELECT raw_table_name, raw_row_ordinal, source_key, error_class "
        "FROM meta_provider_quarantine WHERE raw_request_id = ?",
        ["daily-member-conflict"],
    ).fetchone()
    assert row == ("600000.SH", 0, "000001", "MAPPING_VALIDATION_FAILED")


@pytest.mark.integration
def test_daily_bar_invalid_empty_member_key_blocks(conn, env_root):
    _persist(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        request_id="daily-invalid-empty-member",
        payload={"000001": pl.DataFrame()},
        surface="daily_bar",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="daily_bar", request_id="daily-invalid-empty-member")

    assert result.status == "BLOCKED"
    assert result.error_class == "MAPPING_VALIDATION_FAILED"
    assert result.normalized_count == 0
    assert result.quarantined_count == 0


@pytest.mark.integration
def test_default_stock_basic_index_stays_unusable_and_blocks(conn, env_root):
    pandas = pytest.importorskip("pandas")
    frame = pandas.DataFrame(
        {
            "MARKET_CODE": ["2"],
            "SECURITY_NAME": ["平安银行"],
            "LISTDATE": [19910403],
            "IS_LISTED": [1],
        }
    )
    _persist(
        conn,
        env_root,
        dataset="stock_basic",
        endpoint="InfoData.get_stock_basic",
        request_id="stock-default-index",
        payload=frame,
        surface="security_master",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="stock_basic", request_id="stock-default-index")

    assert result.status == "BLOCKED"
    assert result.quarantined_count == 1
    message = conn.execute(
        "SELECT error_message FROM meta_provider_quarantine WHERE raw_request_id = ?",
        ["stock-default-index"],
    ).fetchone()[0]
    assert "required field" in str(message)
    assert "__index_level_0__" in str(message)


@pytest.mark.integration
def test_stock_basic_conflicting_symbol_carrier_blocks(conn, env_root):
    pandas = pytest.importorskip("pandas")
    frame = pandas.DataFrame(
        {
            "MARKET_CODE": ["000001.SZ"],
            "SECURITY_CODE": ["600000"],
            "LISTDATE": [19910403],
            "IS_LISTED": [1],
        }
    )
    _persist(
        conn,
        env_root,
        dataset="stock_basic",
        endpoint="InfoData.get_stock_basic",
        request_id="stock-conflicting-carrier",
        payload=frame,
        surface="security_master",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="stock_basic", request_id="stock-conflicting-carrier")

    assert result.status == "BLOCKED"
    assert result.normalized_count == 0
    assert result.quarantined_count == 1


@pytest.mark.integration
def test_stock_basic_batch_concat_index_does_not_hide_symbol_carrier(conn, env_root):
    pandas = pytest.importorskip("pandas")
    frame = pandas.DataFrame(
        {
            "MARKET_CODE": ["000001.SZ", "600000.SH"],
            "LISTDATE": [19910403, 19991110],
            "IS_LISTED": [1, 1],
        },
        # This is the observed SDK batch-concat index shape: repeated
        # synthetic zeroes, not provider-owned identity.
        index=pandas.Index([0, 0]),
    )
    _persist(
        conn,
        env_root,
        dataset="stock_basic",
        endpoint="InfoData.get_stock_basic",
        request_id="stock-batch-carrier",
        payload=frame,
        surface="security_master",
    )

    raw = RawWriter(env_root["raw"]).read(
        provider="amazingdata", dataset="stock_basic", request_id="stock-batch-carrier"
    )
    assert "__index_level_0__" in raw.columns

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="stock_basic", request_id="stock-batch-carrier")

    assert result.status == "SUCCESS"
    assert result.input_count == result.normalized_count == 2


@pytest.mark.integration
def test_stock_basic_market_code_symbol_alias_maps_listdate(conn, env_root):
    pandas = pytest.importorskip("pandas")
    frame = pandas.DataFrame(
        {
            # AmazingData's observed stock_basic literal is named
            # MARKET_CODE but carries the full provider symbol.
            "MARKET_CODE": ["000001.SZ"],
            "SECURITY_NAME": ["平安银行"],
            "LISTDATE": [19910403],
            "IS_LISTED": [1],
        }
    )
    _persist(
        conn,
        env_root,
        dataset="stock_basic",
        endpoint="InfoData.get_stock_basic",
        request_id="stock-market-code-symbol",
        payload=frame,
        surface="security_master",
    )

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="stock_basic", request_id="stock-market-code-symbol")

    assert result.status == "SUCCESS"
    assert result.normalized_count == 1
    output = pl.read_parquet(
        env_root["normalized"]
        / "provider=amazingdata/dataset=stock_basic/raw_request=stock-market-code-symbol"
        / "contract=cr2.1-v1"
        / f"run={result.normalization_run_id}/main.parquet"
    )
    assert output["provider_symbol"].to_list() == ["000001.SZ"]
    assert output["list_date"].to_list() == ["1991-04-03"]


@pytest.mark.integration
def test_non_default_stock_basic_index_is_preserved_and_listdate_mapped(conn, env_root):
    pandas = pytest.importorskip("pandas")
    frame = pandas.DataFrame(
        {
            "MARKET_CODE": ["2"],
            "SECURITY_NAME": ["平安银行"],
            "LISTDATE": [19910403],
            "DELISTDATE": [None],
            "IS_LISTED": [1],
        },
        index=pandas.Index(["000001.SZ"]),
    )
    _persist(
        conn,
        env_root,
        dataset="stock_basic",
        endpoint="InfoData.get_stock_basic",
        request_id="stock-index",
        payload=frame,
        surface="security_master",
    )

    raw = RawWriter(env_root["raw"]).read(
        provider="amazingdata", dataset="stock_basic", request_id="stock-index"
    )
    assert "__index_level_0__" in raw.columns

    result = NormalizationRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(provider_dataset="stock_basic", request_id="stock-index")

    assert result.status == "SUCCESS"
    output = pl.read_parquet(
        env_root["normalized"]
        / "provider=amazingdata/dataset=stock_basic/raw_request=stock-index"
        / "contract=cr2.1-v1"
        / f"run={result.normalization_run_id}/main.parquet"
    )
    assert output["provider_symbol"].to_list() == ["000001.SZ"]
    assert output["list_date"].to_list() == ["1991-04-03"]
    assert output["is_listed"].to_list() == [1]
