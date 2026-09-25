from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import polars as pl
import pytest

from ashare_state.normalization.runner import NormalizationRunner
from ashare_state.spike.row_adapter import (
    ProviderRowShapeError,
    key_preserving_table_rows,
)

_SPIKE_SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spike"
sys.path.insert(0, str(_SPIKE_SCRIPT_DIR))
_ISSUE95_BUILD = importlib.import_module("issue95_status_limit_build")
BuildFailure = _ISSUE95_BUILD.BuildFailure
Issue95Build = _ISSUE95_BUILD.Issue95Build
_atomic_json = _ISSUE95_BUILD._atomic_json
_candidate_status_probe_sizes = _ISSUE95_BUILD._candidate_status_probe_sizes


def _status_row(code: str = "600000", market: str = "1", day: int = 20200102) -> dict[str, object]:
    return {
        "SECURITY_CODE": code,
        "MARKET_CODE": market,
        "TRADE_DATE": day,
        "PRECLOSE": 10.0,
        "HIGH_LIMITED": 11.0,
        "LOW_LIMITED": 9.0,
        "IS_ST_SEC": 0,
        "IS_SUSP_SEC": 0,
    }


def _scope(*, symbols: list[str] | None = None) -> dict[str, object]:
    return {
        "begin_date": 20200101,
        "end_date": 20200131,
        "code_list": symbols or ["600000.SH"],
    }


def test_status_member_map_keeps_key_and_requires_independent_row_identity() -> None:
    payload = {"600000.SH": [_status_row()]}

    rows, locators = NormalizationRunner._status_rows_for_normalization(
        payload,
        request_params=_scope(),
    )

    assert len(rows) == 1
    assert rows[0]["PROVIDER_SYMBOL"] == "600000.SH"
    assert rows[0]["SECURITY_CODE"] == "600000"
    assert rows[0]["MARKET_CODE"] == "1"
    assert rows[0]["TRADE_DATE"] == "20200102"
    assert locators == [("600000.SH", 0)]

    unkeyed = {"600000.SH": [{"TRADE_DATE": 20200102, "IS_ST_SEC": 0}]}
    with pytest.raises(ProviderRowShapeError):
        NormalizationRunner._status_rows_for_normalization(
            unkeyed,
            request_params=_scope(),
        )


def test_status_member_map_rejects_key_identity_date_and_duplicate_conflicts() -> None:
    with pytest.raises(ProviderRowShapeError):
        NormalizationRunner._status_rows_for_normalization(
            {"600000.SH": [_status_row(code="600001")]},
            request_params=_scope(),
        )

    with pytest.raises(ProviderRowShapeError):
        NormalizationRunner._status_rows_for_normalization(
            {"600000.SH": [_status_row(day=20200203)]},
            request_params=_scope(),
        )

    with pytest.raises(ProviderRowShapeError):
        NormalizationRunner._status_rows_for_normalization(
            {"600000.SH": [_status_row(), _status_row()]},
            request_params=_scope(),
        )


def test_status_list_rows_must_match_the_request_symbols() -> None:
    with pytest.raises(ProviderRowShapeError):
        NormalizationRunner._status_rows_for_normalization(
            [_status_row()],
            request_params=_scope(symbols=["000001.SZ"]),
        )


def test_key_preserving_adapter_can_fail_closed_on_missing_embedded_identity() -> None:
    payload = {"600000.SH": [{"TRADE_DATE": 20200102}]}

    permissive = key_preserving_table_rows(payload)
    assert permissive[0]["PROVIDER_SYMBOL"] == "600000.SH"

    with pytest.raises(ProviderRowShapeError):
        key_preserving_table_rows(payload, require_embedded_identity=True)


def test_status_batch_probe_sizes_are_bounded_by_provider_evidence() -> None:
    assert _candidate_status_probe_sizes(500, 300) == [8, 16, 32, 64, 125, 250]
    assert _candidate_status_probe_sizes(8, 1000) == [8]
    assert _candidate_status_probe_sizes(1000, 7) == []


def test_normalized_status_domain_pair_keys_match(tmp_path) -> None:
    runner = Issue95Build.__new__(Issue95Build)
    status_frame = pl.DataFrame(
        {
            "security_code": ["600000"],
            "market_code": ["1"],
            "trade_date": [20200102],
        }
    )
    limit_frame = pl.DataFrame({"provider_symbol": ["600000.SH"], "trade_date": [20200102]})
    status_path = tmp_path / "security-status.parquet"
    limit_path = tmp_path / "limit-price.parquet"
    status_frame.write_parquet(status_path)
    limit_frame.write_parquet(limit_path)

    expected = {("600000.SH", 20200102)}
    assert (
        runner._status_output_pairs("security_status", status_path, expected_row_count=1)
        == expected
    )
    assert runner._status_output_pairs("limit_price", limit_path, expected_row_count=1) == expected


def test_empty_normalized_status_projection_has_an_empty_key_set(tmp_path) -> None:
    runner = Issue95Build.__new__(Issue95Build)
    empty_path = tmp_path / "empty-projection.parquet"
    pl.DataFrame().write_parquet(empty_path)

    assert runner._status_output_pairs("limit_price", empty_path, expected_row_count=0) == set()


def test_normalized_status_domain_pair_keys_reject_missing_and_duplicate_rows(
    tmp_path,
) -> None:
    runner = Issue95Build.__new__(Issue95Build)
    missing_key_path = tmp_path / "missing-key.parquet"
    pl.DataFrame({"provider_symbol": [None], "trade_date": [20200102]}).write_parquet(
        missing_key_path
    )
    with pytest.raises(BuildFailure, match="STATUS_PROJECTION_KEY_MISSING"):
        runner._status_output_pairs("limit_price", missing_key_path, expected_row_count=1)

    duplicate_path = tmp_path / "duplicate.parquet"
    pl.DataFrame(
        {
            "provider_symbol": ["600000.SH", "600000.SH"],
            "trade_date": [20200102, 20200102],
        }
    ).write_parquet(duplicate_path)
    with pytest.raises(BuildFailure, match="STATUS_PROJECTION_DUPLICATE_KEY"):
        runner._status_output_pairs("limit_price", duplicate_path, expected_row_count=2)


def test_atomic_manifest_replace_retries_a_transient_permission_error(
    tmp_path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "execution_manifest.json"
    path_type = type(tmp_path)
    original_replace = path_type.replace
    attempts = 0

    def fail_once(self, target) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("synthetic sharing violation")
        original_replace(self, target)

    monkeypatch.setattr(path_type, "replace", fail_once)
    monkeypatch.setattr(_ISSUE95_BUILD.time, "sleep", lambda _delay: None)

    _atomic_json(manifest_path, {"status": "RUNNING"})

    assert attempts == 2
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {"status": "RUNNING"}
