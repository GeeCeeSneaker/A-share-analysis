"""Regression tests for the sealed Formal replay's status-only boundary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def replay_module():
    path = Path(__file__).parents[2] / "scripts" / "spike" / "formal_readonly_replay.py"
    spec = importlib.util.spec_from_file_location("formal_readonly_replay_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_status_boundary_lets_native_identity_win_over_unqualified_outer_key(replay_module):
    rows, unresolved = replay_module._status_keyed_table_rows(
        {"table-name": [{"MARKET_CODE": "600519.SH", "TRADE_DATE": "20240102"}]}
    )

    assert not unresolved
    assert replay_module.canonical_status_view(rows)[0]["PROVIDER_SYMBOL"] == "600519.SH"


def test_status_boundary_uses_qualified_outer_key_for_null_identity_cell(replay_module):
    rows, unresolved = replay_module._status_keyed_table_rows(
        {"600519.SH": [{"MARKET_CODE": None, "TRADE_DATE": "20240102"}]}
    )

    assert not unresolved
    assert replay_module.canonical_status_view(rows)[0]["PROVIDER_SYMBOL"] == "600519.SH"


def test_status_boundary_keeps_unqualified_empty_member_unresolved(replay_module):
    rows, unresolved = replay_module._status_keyed_table_rows({"table-name": None})

    assert rows == []
    assert dict(unresolved) == {"STATUS_MEMBER_EMPTY_OR_NULL_WITHOUT_QUALIFIED_KEY": 1}


def test_status_boundary_rejects_qualified_key_row_conflict(replay_module):
    with pytest.raises(replay_module.ProviderRowShapeError, match="identity conflict"):
        replay_module._status_keyed_table_rows(
            {"600519.SH": [{"MARKET_CODE": "000001.SZ", "TRADE_DATE": "20240102"}]}
        )


def test_core_projection_downgrades_deferred_history_fixture(replay_module):
    projection = replay_module._core_capability_projection(
        [
            {
                "case_types": ["history_start_2020"],
                "replay": {
                    "classification": "REPLAY_VALIDATED_PASS",
                    "result": "VALIDATED_PASS",
                    "deferred_fixture": "300104.SZ",
                },
            }
        ]
    )
    history = next(
        item for item in projection["capabilities"] if item["capability_id"] == "history_start_2020"
    )

    assert history["replay_status"] == "UNRESOLVED"
    assert history["replay_classification"] == "REPLAY_CORE_UNRESOLVED"
    assert history["reason_codes"] == ["HISTORICAL_DELISTED_FIXTURE_DEFERRED"]
