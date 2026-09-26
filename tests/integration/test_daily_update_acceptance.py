"""Daily-update acceptance pointer recovery tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import duckdb
import pytest

from ashare_state.storage.migrations import apply_migrations
from ashare_state.storage.raw_writer import verify_raw_evidence
from ashare_state.update import runner as daily_update
from ashare_state.update.runner import (
    DailyUpdateRunner,
    RepositoryIdentity,
    _AcceptedSnapshot,
)


def _test_universe() -> list[str]:
    return sorted(
        [f"{code:06d}.SH" for code in range(600000, 600100)]
        + [f"{code:06d}.SZ" for code in range(1, 101)]
        + [f"{code:06d}.SZ" for code in range(300001, 300101)]
        + [f"{code:06d}.SH" for code in range(688001, 688101)]
    )


def _master_rows(symbols: list[str]) -> list[dict[str, str]]:
    return [
        {
            "SECURITY_CODE": symbol[:6],
            "MARKET_CODE": "1" if symbol.endswith(".SH") else "2",
            "LISTING_DATE": "19990101",
            "IS_LISTED": "1",
        }
        for symbol in symbols
    ]


def _exchange(dataset, endpoint, surface, payload, params):
    from ashare_state.providers.amazingdata.provider import RawEnvelope
    from ashare_state.providers.exchange import ProviderExchange

    requested_at = "2026-07-08T00:00:00+00:00"
    received_at = "2026-07-08T00:00:01+00:00"
    envelope = RawEnvelope(
        provider="amazingdata",
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=str(uuid4()),
        request_params=params,
        request_params_hash=RawEnvelope.params_hash(params),
        requested_at=requested_at,
        received_at=received_at,
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TEST_SIMULATION_FAKE",
        row_count=len(payload) if hasattr(payload, "__len__") else 1,
        operation_id=f"{endpoint}#{surface}",
        normalization_surface=surface,
    )
    return ProviderExchange(envelope=envelope, payload=payload)


@pytest.mark.integration
def test_pinned_baseline_is_not_replaced_by_an_interrupted_snapshot(
    conn, env_root, tmp_path, monkeypatch
):
    data_root = tmp_path / "data"
    runner = DailyUpdateRunner(
        conn,
        provider=None,
        repository_root=tmp_path,
        data_root=data_root,
        raw_root=env_root["raw"],
        normalized_root=env_root["normalized"],
    )
    accepted = _AcceptedSnapshot("accepted-base", date(2026, 6, 30), {})
    runner._record_initial_baseline(accepted, RepositoryIdentity("a" * 40, False))

    now = "2026-09-26 00:00:00+00:00"
    conn.execute(
        "INSERT INTO meta_snapshot_build ("
        "snapshot_id, canonical_run_id, canonical_manifest_uri, canonical_manifest_hash, "
        "canonical_as_of, requested_domains_json, requested_domains_hash, "
        "snapshot_contract_version, builder_code_fingerprint, row_count_total, status, "
        "started_at, completed_at"
        ") VALUES ('interrupted-snapshot', 'canonical-run', 'canonical.json', ?, ?, ?, ?, "
        "'snapshot-v1', ?, 1, 'SUCCESS', ?, ?)",
        ["b" * 64, now, '["daily_bar"]', "c" * 64, "d" * 64, now, now],
    )
    verified_manifest = {
        "snapshot_id": "accepted-base",
        "artifacts": {
            "daily_bar": {"partitions": [{"partition": "2026-06", "max_trade_date": "2026-06-30"}]}
        },
    }
    monkeypatch.setattr(
        daily_update,
        "verify_snapshot",
        lambda *_args, **_kwargs: SimpleNamespace(manifest=verified_manifest),
    )

    latest = runner._latest_accepted_snapshot()

    assert latest.snapshot_id == "accepted-base"
    assert latest.through == date(2026, 6, 30)


@pytest.mark.integration
def test_five_session_append_unit_check_and_exact_target_replay(
    conn, env_root, tmp_path, monkeypatch
):
    """Exercise the full daily pipeline over a bounded 5-session fake feed.

    This proves orchestration, append preservation, VWAP diagnostics and
    same-target no-provider replay; it is deliberately not a substitute for
    the separate retained real-provider acceptance run.
    """
    import polars as pl

    from ashare_state.canonical.canonicalizer import CanonicalRunner
    from ashare_state.normalization.runner import NormalizationRunner
    from ashare_state.snapshot.builder import SnapshotBuilder
    from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter
    from ashare_state.update.runner import DailyUpdateRunner

    universe = _test_universe()
    master = _master_rows(universe)
    root = tmp_path / "data"
    repository = RepositoryIdentity("a" * 40, False)
    monkeypatch.setattr(daily_update, "read_repository_identity", lambda _root: repository)

    def capture(dataset, endpoint, surface, payload, params):
        exchange = _exchange(dataset, endpoint, surface, payload, params)
        AnchoredRawEvidenceWriter(
            conn, env_root["raw"], ingest_run_id="five-session-acceptance-baseline"
        ).write_exchange(exchange)
        normalized = NormalizationRunner(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        ).run(provider_dataset=dataset, request_id=exchange.request_id)
        assert normalized.status == "SUCCESS"
        assert normalized.quarantined_count == 0

    capture(
        "stock_basic",
        "InfoData.get_stock_basic",
        "security_master",
        master,
        {"code_list": universe},
    )
    baseline_members = [universe[index] for index in (0, 100, 200, 300)]
    baseline_payload = {
        symbol: pl.DataFrame(
            {
                "KLINE_TIME": [20260630],
                "KLINE_TYPE": ["DAY"],
                "OPEN_PRICE": [10.0],
                "HIGH_PRICE": [11.0],
                "LOW_PRICE": [9.0],
                "CLOSE_PRICE": [10.5],
                "VOLUME": [1000.0],
                "AMOUNT": [10500.0],
            }
        )
        for symbol in baseline_members
    }
    capture(
        "daily_bar",
        "MarketData.query_kline",
        "daily_bar",
        baseline_payload,
        {
            "code_list": baseline_members,
            "begin_date": 20260630,
            "end_date": 20260630,
            "trading_days": [20260630],
            "period": 10008,
        },
    )
    baseline_canonical = CanonicalRunner(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).run(datetime(2026, 7, 9, tzinfo=UTC), domains=("daily_bar",))
    assert baseline_canonical.status == "SUCCESS", conn.execute(
        "SELECT finding_class, blocking, detail_json "
        "FROM meta_canonical_reconciliation_finding "
        "WHERE canonical_run_id = ?",
        [baseline_canonical.canonical_run_id],
    ).fetchall()
    baseline_snapshot = SnapshotBuilder(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).build_daily_partition_set((baseline_canonical.canonical_run_id,))
    assert baseline_snapshot.row_count_total == len(baseline_members)

    sessions = ["20260701", "20260702", "20260703", "20260706", "20260707"]

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        def _reply(self, dataset, endpoint, surface, payload, params):
            self.calls += 1
            return _exchange(dataset, endpoint, surface, payload, params)

        def get_calendar_exchange(self, market):
            return self._reply(
                "trade_calendar",
                "BaseData.get_calendar",
                "trade_calendar",
                ["20260630", *sessions],
                {"market": market},
            )

        def get_hist_code_list_exchange(self, security_type, start_date, end_date):
            return self._reply(
                "hist_code_list",
                "BaseData.get_hist_code_list",
                "security_master",
                universe,
                {
                    "security_type": security_type,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )

        def get_stock_basic_exchange(self, code_list):
            selected = set(code_list)
            rows = [
                row
                for row in master
                if f"{row['SECURITY_CODE']}."
                f"{'SH' if row['MARKET_CODE'] == '1' else 'SZ'}" in selected
            ]
            return self._reply(
                "stock_basic",
                "InfoData.get_stock_basic",
                "security_master",
                rows,
                {"code_list": list(code_list)},
            )

        def query_kline_exchange(
            self, code_list, *, begin_date, end_date, kline_type, trading_days
        ):
            day_payload = {
                symbol: pl.DataFrame(
                    {
                        "KLINE_TIME": [begin_date],
                        "KLINE_TYPE": [kline_type],
                        "OPEN_PRICE": [10.0],
                        "HIGH_PRICE": [11.0],
                        "LOW_PRICE": [9.0],
                        "CLOSE_PRICE": [10.5],
                        "VOLUME": [1000.0],
                        "AMOUNT": [10500.0],
                    }
                )
                for symbol in code_list
            }
            return self._reply(
                "daily_bar",
                "MarketData.query_kline",
                "daily_bar",
                day_payload,
                {
                    "code_list": list(code_list),
                    "begin_date": begin_date,
                    "end_date": end_date,
                    "kline_type": kline_type,
                    "trading_days": list(trading_days),
                },
            )

    provider = FakeProvider()
    runner = DailyUpdateRunner(
        conn,
        provider=provider,
        repository_root=tmp_path,
        data_root=root,
        raw_root=env_root["raw"],
        normalized_root=env_root["normalized"],
        evidence_backup_root=tmp_path / "backup",
        batch_size=500,
        now=lambda: datetime(2026, 7, 10, tzinfo=UTC),
    )

    result = runner.run(date(2026, 7, 7))

    assert result.status == "SUCCESS"
    assert result.accepted_through == date(2026, 7, 7)
    assert result.expected_member_count == 5 * len(universe)
    assert result.returned_bar_count == 5 * len(universe)
    assert result.retention_status == "SUCCESS"
    assert provider.calls == 2 + 5 + 1 + 5
    manifest_path = root / str(result.manifest_uri)
    manifest_bytes = manifest_path.read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == result.manifest_hash
    manifest = json.loads(manifest_bytes)
    assert manifest["repository"] == {"commit_sha": "a" * 40, "dirty": False}
    assert manifest["session_count"] == 5
    assert set(manifest["unit_sanity_check"]) == {"60", "00", "30", "688"}
    assert all(item["contract"] == "DIRECT" for item in manifest["unit_sanity_check"].values())

    from ashare_state.update.retention import verify_daily_update_archives

    verified = verify_daily_update_archives(
        conn,
        data_root=root,
        secondary_root=tmp_path / "backup",
    )
    assert (verified.checked_count, verified.verified_count, verified.issues) == (1, 1, ())

    archive_path = (
        tmp_path / "backup" / "archives" / "daily_update" / f"run={result.update_run_id}.zip"
    )
    archive_bytes = archive_path.read_bytes()

    from zipfile import ZipFile

    daily_receipt = next(
        item for item in manifest["request_receipts"] if item["provider_dataset"] == "daily_bar"
    )
    restored_raw_root = tmp_path / "restore-smoke" / "raw"
    restored_dataset = restored_raw_root / "provider=amazingdata" / "dataset=daily_bar"
    restored_dataset.mkdir(parents=True)
    with ZipFile(
        tmp_path / "backup" / "archives" / "daily_update" / f"run={result.update_run_id}.zip"
    ) as archive:
        raw_meta_bytes = archive.read(f"raw/{daily_receipt['raw_evidence_uri']}")
        raw_meta = json.loads(raw_meta_bytes)
        (restored_dataset / f"{daily_receipt['request_id']}.meta.json").write_bytes(raw_meta_bytes)
        for table in raw_meta["tables"]:
            filename = table["file"]
            target = restored_dataset.joinpath(*filename.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                archive.read(f"raw/provider=amazingdata/dataset=daily_bar/{filename}")
            )

    restored_evidence = verify_raw_evidence(
        restored_raw_root,
        provider="amazingdata",
        dataset="daily_bar",
        request_id=daily_receipt["request_id"],
    )
    assert restored_evidence.evidence_hash == daily_receipt["raw_evidence_hash"]
    anchor = conn.execute(
        "SELECT provider, provider_dataset, request_id, evidence_uri, evidence_hash, endpoint, "
        "operation_id, normalization_surface, payload_kind, ingest_run_id, created_at "
        "FROM meta_raw_evidence_anchor WHERE provider_dataset = 'daily_bar' AND request_id = ?",
        [daily_receipt["request_id"]],
    ).fetchone()
    assert anchor is not None
    restored_conn = duckdb.connect(":memory:")
    try:
        apply_migrations(restored_conn, Path(__file__).resolve().parents[2] / "migrations")
        restored_conn.execute(
            "INSERT INTO meta_raw_evidence_anchor VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            anchor,
        )
        restored_normalized = NormalizationRunner(
            restored_conn,
            raw_root=restored_raw_root,
            normalized_root=tmp_path / "restore-smoke" / "normalized",
        ).run(provider_dataset="daily_bar", request_id=daily_receipt["request_id"])
    finally:
        restored_conn.close()
    assert restored_normalized.status == "SUCCESS"
    assert restored_normalized.normalized_count == len(universe)

    archive_path.write_bytes(archive_bytes[:-1] + bytes([archive_bytes[-1] ^ 0x01]))
    corrupted = verify_daily_update_archives(
        conn,
        data_root=root,
        secondary_root=tmp_path / "backup",
    )
    assert corrupted.verified_count == 0
    assert corrupted.issues[0]["update_run_id"] == result.update_run_id
    archive_path.write_bytes(archive_bytes)

    repeated = runner.run(date(2026, 7, 7))

    assert repeated.idempotent_replay is True
    assert repeated.snapshot_id == result.snapshot_id
    assert repeated.retention_status == "NOT_APPLICABLE"
    assert provider.calls == 2 + 5 + 1 + 5
