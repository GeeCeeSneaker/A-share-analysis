"""Offline contract tests for the CR-7 positive-semantic diagnostic."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _load_probe():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "spike"
        / ("cr7_positive_semantic_fallback.py")
    )
    spec = importlib.util.spec_from_file_location("cr7_positive_semantic_fallback_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


class DataFrame:
    """Small pandas-compatible test double; no provider SDK is needed."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        names: list[str] = []
        for row in rows:
            for name in row:
                if name not in names:
                    names.append(name)
        self.columns = tuple(names)

    def __len__(self) -> int:
        return len(self._rows)

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return list(self._rows)


def test_positive_activity_requires_a_documented_activity_field() -> None:
    positive = probe._analyze_frame(DataFrame([{"num_trades": 1, "last": 10.0}]))
    assert positive["status"] == "POSITIVE_EXECUTED_ACTIVITY"
    assert positive["positive_fields"] == ["num_trades"]
    assert positive["positive_row_count"] == 1

    price_only = probe._analyze_frame(DataFrame([{"last": 10.0, "bid_price1": 9.9}]))
    assert price_only["status"] == "NO_DOCUMENTED_ACTIVITY_FIELD"
    assert price_only["positive_row_count"] == 0


def test_zero_negative_nan_and_empty_values_do_not_prove_trading() -> None:
    result = probe._analyze_frame(
        DataFrame(
            [
                {"volume": 0, "amount": 0, "num_trades": None},
                {"volume": -1, "amount": float("nan"), "num_trades": 0},
            ]
        )
    )
    assert result["status"] == "NO_POSITIVE_ACTIVITY_VALUE"
    assert result["positive_fields"] == []
    assert result["positive_row_count"] == 0

    empty = probe._analyze_frame(DataFrame([]))
    assert empty["status"] == "NO_DOCUMENTED_ACTIVITY_FIELD"
    assert empty["positive_row_count"] == 0


def test_all_applicable_sessions_can_resolve_but_rule_stays_unencoded() -> None:
    member = "opaque-member-for-test"
    sessions = [20240102, 20240103]
    payload = {
        20240102: {member: DataFrame([{"volume": 100, "amount": 1000}])},
        20240103: {member: DataFrame([{"num_trades": 2}])},
    }

    result = probe._assess_payload(payload, sessions, member)

    assert result["status"] == "PROVIDER_SEMANTIC_RESOLVED"
    assert result["outcome"] == "PROVIDER_SEMANTIC_RESOLVED"
    assert result["positive_session_count"] == 2
    assert result["positive_session_dates"] == sessions
    assert result["fallback_rule_encoded"] is False
    assert result["implementation_status"] == "EVIDENCE_ONLY_PENDING_REVIEW"
    assert result["review_required_before_rule_change"] is True


def test_missing_session_or_extra_member_fails_closed() -> None:
    member = "opaque-member-for-test"
    missing = probe._assess_payload(
        {20240102: {member: DataFrame([{"num_trades": 1}])}},
        [20240102, 20240103],
        member,
    )
    assert missing["status"] == "STOP(BLOCKED)"
    assert missing["reason_code"] == "SNAPSHOT_SESSION_MEMBER_MAP_INVALID"
    assert missing["positive_session_count"] == 1

    extra_member = probe._assess_payload(
        {
            20240102: {
                member: DataFrame([{"num_trades": 1}]),
                "unexpected": DataFrame([{"num_trades": 1}]),
            }
        },
        [20240102],
        member,
    )
    assert extra_member["status"] == "STOP(BLOCKED)"
    assert extra_member["reason_code"] == "SNAPSHOT_RESPONSE_EXTRA_MEMBER"
