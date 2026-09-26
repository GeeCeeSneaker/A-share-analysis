"""Offline contracts for the tracked daily update path."""

from __future__ import annotations

from datetime import date

import pytest

from ashare_state.update import retention as evidence_retention
from ashare_state.update import runner as daily_update
from ashare_state.update.runner import (
    DailyUpdateError,
    DailyUpdateRunner,
    RepositoryIdentity,
    _AcceptedSnapshot,
    measure_volume_amount_units,
)


def _rows(amount_over_volume: float) -> list[dict[str, float | str]]:
    return [
        {
            "provider_symbol": "600000.SH",
            "amount": amount_over_volume,
            "volume": 1.0,
            "low": 9.0,
            "high": 11.0,
        },
        {
            "provider_symbol": "000001.SZ",
            "amount": amount_over_volume,
            "volume": 1.0,
            "low": 9.0,
            "high": 11.0,
        },
        {
            "provider_symbol": "300750.SZ",
            "amount": amount_over_volume,
            "volume": 1.0,
            "low": 9.0,
            "high": 11.0,
        },
        {
            "provider_symbol": "688981.SH",
            "amount": amount_over_volume,
            "volume": 1.0,
            "low": 9.0,
            "high": 11.0,
        },
    ]


@pytest.mark.unit
def test_volume_amount_contract_accepts_direct_vwap_per_each_board() -> None:
    result = measure_volume_amount_units(_rows(10.0), minimum_rows_per_segment=1)

    assert set(result) == {"60", "00", "30", "688"}
    assert {entry["contract"] for entry in result.values()} == {"DIRECT"}
    assert {entry["amount_over_volume_multiplier"] for entry in result.values()} == {1.0}


@pytest.mark.unit
def test_volume_amount_contract_detects_100x_alternative() -> None:
    result = measure_volume_amount_units(_rows(1000.0), minimum_rows_per_segment=1)

    assert {entry["contract"] for entry in result.values()} == {"AMOUNT_PER_100_VOLUME"}
    assert {entry["amount_over_volume_multiplier"] for entry in result.values()} == {0.01}


@pytest.mark.unit
def test_volume_amount_contract_fails_closed_when_a_board_is_missing() -> None:
    rows = _rows(10.0)[:-1]

    with pytest.raises(DailyUpdateError, match="board 688"):
        measure_volume_amount_units(rows, minimum_rows_per_segment=1)


@pytest.mark.unit
def test_volume_amount_contract_requires_minimum_bounded_sample() -> None:
    with pytest.raises(DailyUpdateError, match="only 1 usable rows"):
        measure_volume_amount_units(_rows(10.0), minimum_rows_per_segment=2)


@pytest.mark.unit
def test_same_accepted_target_is_idempotent_and_makes_no_provider_calls(tmp_path, monkeypatch):
    class _NeverCallProvider:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected Provider call: {name}")

    runner = DailyUpdateRunner(
        conn=None,
        provider=_NeverCallProvider(),
        repository_root=tmp_path,
        data_root=tmp_path / "data",
        raw_root=tmp_path / "data" / "raw",
        normalized_root=tmp_path / "data" / "normalized",
    )
    accepted = _AcceptedSnapshot(
        snapshot_id="accepted-snapshot",
        through=date(2026, 6, 30),
        manifest={},
    )
    monkeypatch.setattr(runner, "_latest_accepted_snapshot", lambda: accepted)

    plan = runner.plan(date(2026, 6, 30))
    result = runner.run(date(2026, 6, 30))

    assert plan.action == "NO_PROVIDER_WORK"
    assert result.idempotent_replay is True
    assert result.snapshot_id == accepted.snapshot_id


@pytest.mark.unit
def test_dirty_repository_is_rejected_before_provider_calls(tmp_path, monkeypatch):
    class _NeverCallProvider:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected Provider call: {name}")

    runner = DailyUpdateRunner(
        conn=None,
        provider=_NeverCallProvider(),
        repository_root=tmp_path,
        data_root=tmp_path / "data",
        raw_root=tmp_path / "data" / "raw",
        normalized_root=tmp_path / "data" / "normalized",
    )
    monkeypatch.setattr(
        runner,
        "_latest_accepted_snapshot",
        lambda: _AcceptedSnapshot("accepted-snapshot", date(2026, 6, 30), {}),
    )
    monkeypatch.setattr(
        daily_update,
        "read_repository_identity",
        lambda _path: RepositoryIdentity("0" * 40, True),
    )

    with pytest.raises(DailyUpdateError, match="repository state is dirty"):
        runner.run(date(2026, 7, 1))


@pytest.mark.unit
def test_evidence_backup_failure_is_prominent_but_does_not_raise(tmp_path, monkeypatch):
    events = []
    runner = DailyUpdateRunner(
        conn=None,
        provider=None,
        repository_root=tmp_path,
        data_root=tmp_path / "data",
        raw_root=tmp_path / "data" / "raw",
        normalized_root=tmp_path / "data" / "normalized",
        evidence_backup_root=tmp_path / "backup",
        progress=events.append,
    )

    def fail_backup(*_args, **_kwargs):
        raise OSError("private physical path must not escape")

    monkeypatch.setattr(evidence_retention, "archive_daily_update", fail_backup)

    status = runner._retain_evidence("accepted-run-id")

    assert status == "BACKUP_FAILED"
    assert events == [
        {
            "stage": "EVIDENCE_RETENTION_FAILED",
            "update_run_id": "accepted-run-id",
            "failure_class": "OSError",
            "warning": "daily update is accepted, but its evidence backup needs attention",
        }
    ]
