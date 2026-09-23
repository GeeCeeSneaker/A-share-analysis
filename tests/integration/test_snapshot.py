"""CR-4 SnapshotBuilder + canonical consumption verifier integration
tests (work requirement audits 20260902 sections 3-5, CR-4.4 closure).

Coverage map (work requirement §10):
- TestCanonicalConsumptionVerifier: mandatory 1-10
- TestSnapshotBuilder: mandatory 11-30
- TestSnapshotSchemaProjection: unit-level strictness (P0-A09/PIT/key bindings)
- TestBoundaryStructure: CR-4 boundary AST guards
"""

from __future__ import annotations

import ast
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ashare_state.canonical import CanonicalRunner
from ashare_state.canonical.daily_bar import DAILY_BAR_FACT_FIELDS
from ashare_state.canonical.daily_bar_event import (
    daily_bar_event_eligibility_binding,
    daily_bar_latest_session_close_at,
)
from ashare_state.canonical.verifier import (
    CanonicalConsumptionError,
    verify_canonical_run_for_consumption,
)
from ashare_state.snapshot import (
    SnapshotBuilder,
    SnapshotBuilderError,
    SnapshotSchemaError,
    SnapshotVerifierError,
    consume_snapshot_seal,
    logical_daily_snapshot_semantics_fingerprint,
    snapshot_base_hash_from_primitives,
    snapshot_builder_code_fingerprint,
    validate_canonical_key,
    verify_snapshot,
)
from ashare_state.snapshot.builder import logical_daily_snapshot_manifest_uri
from ashare_state.snapshot.schema import polars_domain_schema, project_selected_row
from ashare_state.storage.raw_writer import RawWriter

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

T0 = datetime(2026, 8, 30, 0, 0, 1, tzinfo=UTC)
T1 = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)
AS_OF_EARLY = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
AS_OF_LATE = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)

ALL_DOMAINS = ("trade_calendar", "daily_bar", "security_status", "limit_price", "adj_factor")

SNAPSHOT_SRC = Path(__file__).resolve().parents[2] / "src" / "ashare_state" / "snapshot"
READMODEL_SRC = Path(__file__).resolve().parents[2] / "src" / "ashare_state" / "readmodel"


# ----------------------------------------------------------------- fixtures
# conn / env_root come from the shared integration conftest.


@dataclass
class _FakeEnvelope:
    provider: str = "amazingdata"
    provider_dataset: str = "daily_bar"
    endpoint: str = "MarketData.query_kline"
    request_id: str = ""
    request_params_hash: str = "h" * 16
    requested_at: str = "2026-08-30T00:00:00+00:00"
    received_at: str = "2026-08-30T00:00:01+00:00"
    sdk_version: str | None = "FAKE-1.1.9"
    runtime_version: str | None = "FAKE-V4.3.0"
    account_profile_id: str = "ACCOUNT_x"
    row_count: int = 2
    status: str = "OK"
    error_class: str | None = None
    duration_ms: float = 1.0
    attempt_count: int = 1
    normalization_surface: str = "daily_bar"
    operation_id: str = "op"
    request_params: dict[str, Any] | None = None


def _enroll(conn, roots: dict[str, Path], dataset: str, request_id: str) -> None:
    from ashare_state.storage.raw_anchor import _enroll_anchor

    _enroll_anchor(
        conn,
        roots["raw"],
        provider="amazingdata",
        provider_dataset=dataset,
        request_id=request_id,
        evidence_hash=hashlib.sha256(
            (
                roots["raw"]
                / "provider=amazingdata"
                / f"dataset={dataset}"
                / f"{request_id}.meta.json"
            ).read_bytes()
        ).hexdigest(),
    )


def _normalize(conn, roots, dataset: str, request_id: str):
    from ashare_state.normalization.runner import NormalizationRunner

    return NormalizationRunner(
        conn, raw_root=roots["raw"], normalized_root=roots["normalized"]
    ).run(provider_dataset=dataset, request_id=request_id)


def _persist_raw(
    conn,
    roots: dict[str, Path],
    *,
    dataset: str,
    endpoint: str,
    surface: str,
    request_id: str,
    payload: Any,
    params: dict[str, Any] | None = None,
    received_at: datetime = T0,
) -> None:
    writer = RawWriter(roots["raw"], ingest_run_id="ingest-test")
    env = _FakeEnvelope(
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=request_id,
        request_params=params or {},
        received_at=received_at.isoformat(),
        row_count=len(payload) if hasattr(payload, "__len__") else 1,
        normalization_surface=surface,
        operation_id=f"{endpoint}#{surface}",
    )
    from ashare_state.providers.exchange import ProviderExchange

    writer.write(ProviderExchange(envelope=env, payload=payload))
    _enroll(conn, roots, dataset, request_id)
    _normalize(conn, roots, dataset, request_id)


_MASTER_ROWS = [
    {"SECURITY_CODE": "600000", "MARKET_CODE": "1", "LISTING_DATE": "19990101", "IS_LISTED": "1"},
    {"SECURITY_CODE": "000001", "MARKET_CODE": "2", "LISTING_DATE": "19910403", "IS_LISTED": "1"},
]

_BAR_ROWS = [
    {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "KLINE_TIME": 20260814,
        "KLINE_TYPE": "DAY",
        "OPEN_PRICE": "10.0",
        "HIGH_PRICE": "11.0",
        "LOW_PRICE": "9.0",
        "CLOSE_PRICE": "10.5",
        "VOLUME": "12345",
        "AMOUNT": "67890.0",
    },
    {
        "SECURITY_CODE": "000001",
        "MARKET_CODE": "2",
        "KLINE_TIME": 20260814,
        "KLINE_TYPE": "DAY",
        "OPEN_PRICE": "20.0",
        "HIGH_PRICE": "21.0",
        "LOW_PRICE": "19.0",
        "CLOSE_PRICE": "20.5",
        "VOLUME": "100",
        "AMOUNT": "2000.0",
    },
]

_STATUS_ROWS = [
    {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "TRADE_DATE": "20260814",
        "IS_ST": "0",
        "IS_XR_SEC": "1",
        "IS_WD_SEC": "0",
        "UP_LIMIT_PRICE": "11.0",
        "DOWN_LIMIT_PRICE": "9.0",
    },
]

_ADJ_ROWS = [{"SECURITY_CODE": "600000", "EX_DATE": "20260810", "EX_FACTOR": "1.5"}]


def _canonical(conn, roots, as_of, domains=None):
    return CanonicalRunner(conn, raw_root=roots["raw"], normalized_root=roots["normalized"]).run(
        as_of, domains=domains
    )


def _seed_base(conn, env_root) -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="code_list",
        endpoint="BaseData.get_code_list",
        surface="security_master",
        request_id="req-master",
        payload=_MASTER_ROWS,
    )


def _seed_bars(conn, env_root, request_id: str = "req-bars", received_at: datetime = T0) -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        surface="daily_bar",
        request_id=request_id,
        payload=_BAR_ROWS,
        received_at=received_at,
    )


def _seed_status(conn, env_root, request_id: str = "req-status") -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="history_stock_status",
        endpoint="InfoData.get_history_stock_status",
        surface="security_status_history",
        request_id=request_id,
        payload=_STATUS_ROWS,
    )


def _seed_adj(conn, env_root, request_id: str = "req-adj") -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="adj_factor",
        endpoint="BaseData.get_adj_factor",
        surface="adj_factor",
        request_id=request_id,
        payload=_ADJ_ROWS,
    )


def _seed_cal(conn, env_root, request_id: str = "req-cal") -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="trade_calendar",
        endpoint="BaseData.get_calendar",
        surface="trade_calendar",
        request_id=request_id,
        payload=["20260810", "20260811"],
        params={"market": "SH"},
    )


def _seed_all(conn, env_root) -> None:
    _seed_base(conn, env_root)
    _seed_bars(conn, env_root)
    _seed_status(conn, env_root)
    _seed_adj(conn, env_root)
    _seed_cal(conn, env_root)


def _canonical_success(conn, env_root, domains=ALL_DOMAINS, as_of=AS_OF_LATE):
    _seed_all(conn, env_root)
    result = _canonical(conn, env_root, as_of, domains=domains)
    assert result.status == "SUCCESS", str(
        conn.execute(
            "SELECT detail_json FROM meta_canonical_reconciliation_finding "
            "WHERE canonical_run_id = ?",
            [result.canonical_run_id],
        ).fetchall()
    )
    return result


def _consume(conn, env_root, run_id):
    return verify_canonical_run_for_consumption(
        conn, run_id, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    )


def _build(conn, env_root, run_id):
    return SnapshotBuilder(
        conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
    ).build(run_id)


def _snapshot_manifest(env_root, result) -> dict[str, Any]:
    return json.loads(
        (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
    )


def _daily_partition_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(manifest["artifacts"]["daily_bar"]["partitions"])


def _daily_fact_path(env_root, manifest: dict[str, Any]) -> Path:
    partition = _daily_partition_entries(manifest)[0]
    return env_root["normalized"] / str(partition["fact_artifact"]["uri"])


def _replace_daily_fact(env_root, manifest: dict[str, Any], *, close: float) -> None:
    path = _daily_fact_path(env_root, manifest)
    table = pq.read_table(path)
    close_index = table.schema.get_field_index("close")
    table = table.set_column(
        close_index,
        table.schema.field(close_index),
        pa.array([close] * table.num_rows, type=pa.float64()),
    )
    staged = path.with_name("fact-test-rewrite.parquet")
    pq.write_table(table, staged, compression="zstd", write_statistics=False)
    staged.replace(path)


def _rebind_snapshot_manifest(env_root, conn, result, mutate) -> None:
    """Rewrite a snapshot manifest in place (mutate + rehash + update
    ONLY the ledger outer manifest_hash - the CR-4 rebind shape)."""
    path = env_root["normalized"] / str(result.manifest_uri)
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    data = json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8")
    path.write_bytes(data)
    conn.execute(
        "UPDATE meta_snapshot_build SET manifest_hash = ? WHERE snapshot_id = ?",
        [hashlib.sha256(data).hexdigest(), result.snapshot_id],
    )


def _canonical_manifest(env_root, canonical_result) -> dict[str, Any]:
    return json.loads(
        (env_root["normalized"] / str(canonical_result.manifest_uri)).read_text(encoding="utf-8")
    )


# --------------------------- CR-4.1: canonical consumption verifier (1-10)


@pytest.mark.integration
class TestCanonicalConsumptionVerifier:
    """Mandatory tests 1-10: the ONE public canonical consumption
    boundary - verified SUCCESS truth, explicit BLOCKED rejection,
    full fail-closed seal verification, no current-discovery
    requirement."""

    def test_consume_verified_success_green(self, conn, env_root):
        """Mandatory 1: a healthy canonical SUCCESS run is consumed
        with its verified truth (status / requested domains /
        materialized selected rows)."""
        result = _canonical_success(conn, env_root)
        verified = _consume(conn, env_root, result.canonical_run_id)
        assert verified.canonical_run_id == result.canonical_run_id
        assert verified.status == "SUCCESS"
        assert verified.requested_domains == tuple(sorted(ALL_DOMAINS))
        assert len(verified.selected_rows) == 7  # 2 cal + 2 bars + 1 status + 1 limit + 1 adj
        domains = {r["canonical_domain"] for r in verified.selected_rows}
        assert domains == set(ALL_DOMAINS)

    def test_consume_unknown_run_rejected(self, conn, env_root):
        """Mandatory 2: an unknown canonical id is rejected with
        NOTHING returned."""
        _seed_base(conn, env_root)
        with pytest.raises(CanonicalConsumptionError, match="does not exist"):
            _consume(conn, env_root, str(uuid.uuid4()))

    def test_consume_blocked_run_rejected(self, conn, env_root):
        """Mandatory 3: a canonical BLOCKED run (findings exist) is
        EXPLICITLY rejected - its findings are a failure record, not
        consumable truth."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        conn.execute("DELETE FROM meta_raw_evidence_anchor WHERE request_id = 'req-bars'")
        blocked = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert blocked.status == "BLOCKED"
        with pytest.raises(CanonicalConsumptionError, match="only a verified SUCCESS"):
            _consume(conn, env_root, blocked.canonical_run_id)

    def test_consume_after_superset_growth_green(self, conn, env_root):
        """Mandatory 4: C1 consumed A; a NEW CR-2 input B is ingested
        and a superset canonical run C2 is minted - consuming C1 STILL
        succeeds (no current-discovery-presence requirement: A remains
        in the authoritative ledger, identity intact, evidence
        healthy)."""
        first = _canonical_success(conn, env_root, domains=("daily_bar",))
        _seed_bars(conn, env_root, "req-new-bars", received_at=T1)
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.status == "SUCCESS"
        assert second.canonical_run_id != first.canonical_run_id
        verified = _consume(conn, env_root, first.canonical_run_id)
        assert verified.canonical_run_id == first.canonical_run_id
        assert len(verified.selected_rows) == 2  # the ORIGINAL world of C1

    def test_consume_rejects_input_ledger_drift(self, conn, env_root):
        """Mandatory 5: a sealed CR-2 input's ledger identity drifts
        after the canonical run -> consumption fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        conn.execute(
            "UPDATE meta_provider_normalization_run SET mapper_code_hash = ? "
            "WHERE raw_request_id = 'req-bars'",
            ["0" * 64],
        )
        with pytest.raises(CanonicalConsumptionError, match="ledger field .* drifted"):
            _consume(conn, env_root, result.canonical_run_id)

    def test_consume_rejects_input_disappearance(self, conn, env_root):
        """Mandatory 5 (disappearance leg): the consumed CR-2 run is
        deleted from the ledger -> consumption fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        conn.execute(
            "DELETE FROM meta_provider_normalization_run WHERE raw_request_id = 'req-bars'"
        )
        with pytest.raises(CanonicalConsumptionError, match="no longer exists"):
            _consume(conn, env_root, result.canonical_run_id)

    def test_consume_rejects_status_rebind(self, conn, env_root):
        """Mandatory 6: the canonical ledger status is rebound
        SUCCESS -> BLOCKED while the findings carry no blocking truth
        -> the typed seal (manifest status field) or the semantic
        recompute rejects the consumption - whichever fires first."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        conn.execute(
            "UPDATE meta_canonicalization_run SET status = 'BLOCKED' WHERE canonical_run_id = ?",
            [result.canonical_run_id],
        )
        with pytest.raises(CanonicalConsumptionError, match="DAMAGED"):
            _consume(conn, env_root, result.canonical_run_id)

    def test_consume_rejects_canonical_manifest_rebind(self, conn, env_root):
        """Mandatory 7: the canonical manifest is rewritten + the
        ledger outer hash rebound -> the identity seal rejects the
        consumption."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        path = env_root["normalized"] / str(result.manifest_uri)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["base_identity_hash"] = "0" * 64
        data = json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(data).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalConsumptionError, match="DAMAGED"):
            _consume(conn, env_root, result.canonical_run_id)

    def test_consume_rejects_selected_artifact_tamper(self, conn, env_root):
        """Mandatory 8/9: the canonical selected.parquet bytes are
        tampered after the run -> the artifact closure verifier
        rejects the consumption."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        manifest = _canonical_manifest(env_root, result)
        uri = str(manifest["artifacts"]["selected"]["uri"])
        (env_root["normalized"] / uri).write_bytes(b"tampered-selected")
        with pytest.raises(CanonicalConsumptionError, match="artifacts are DAMAGED"):
            _consume(conn, env_root, result.canonical_run_id)

    def test_consume_rejects_input_physical_damage(self, conn, env_root):
        """Mandatory 9 (physical leg): the CR-2 normalized output
        artifact of a consumed input is damaged -> the sealed-input
        physical verification rejects the consumption."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        run_uri = str(
            conn.execute(
                "SELECT normalized_manifest_uri FROM meta_provider_normalization_run "
                "WHERE raw_request_id = 'req-bars'"
            ).fetchone()[0]
        )
        cr2_manifest = json.loads((env_root["normalized"] / run_uri).read_text(encoding="utf-8"))
        output_uri = str(cr2_manifest["outputs"][0]["uri"])
        (env_root["normalized"] / output_uri).write_bytes(b"cr4-damaged-output")
        with pytest.raises(CanonicalConsumptionError, match="sealed CR-2 input"):
            _consume(conn, env_root, result.canonical_run_id)

    def test_builder_rejects_unverifiable_canonical_input(self, conn, env_root):
        """Mandatory 10: SnapshotBuilder on a canonical run whose
        verification fails -> NOTHING is written (no directory, no
        ledger row, no manifest)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        conn.execute("DELETE FROM meta_raw_evidence_anchor WHERE request_id = 'req-bars'")
        blocked = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert blocked.status == "BLOCKED"
        with pytest.raises((CanonicalConsumptionError, SnapshotBuilderError)):
            _build(conn, env_root, blocked.canonical_run_id)
        assert conn.execute("SELECT COUNT(*) FROM meta_snapshot_build").fetchone()[0] == 0
        assert not list((env_root["normalized"] / "snapshot").rglob("manifest.json"))


# ------------------------------- CR-4.2: SnapshotBuilder (mandatory 11-30)


@pytest.mark.integration
class TestSnapshotBuilder:
    """Mandatory tests 11-30: deterministic identity, immutable
    artifacts, idempotent replay, domain partitioning, schema/lineage
    preservation and the fail-closed verification paths."""

    def test_build_success_writes_artifacts_and_ledger(self, conn, env_root):
        """Mandatory 11: a SUCCESS build writes the per-domain
        parquet artifacts + the manifest (LAST) + exactly one ledger
        row with the deterministic URI."""
        result = _canonical_success(conn, env_root, domains=("daily_bar", "trade_calendar"))
        built = _build(conn, env_root, result.canonical_run_id)
        assert built.status == "SUCCESS"
        assert built.idempotent_replay is False
        assert built.row_count_total == 4
        rows = conn.execute(
            "SELECT manifest_uri, manifest_hash, status, row_count_total "
            "FROM meta_snapshot_build WHERE snapshot_id = ?",
            [built.snapshot_id],
        ).fetchall()
        assert len(rows) == 1
        manifest = _snapshot_manifest(env_root, built)
        expected_uri = logical_daily_snapshot_manifest_uri(
            built.snapshot_id,
            datetime.fromisoformat(manifest["market_as_of"]),
            datetime.fromisoformat(manifest["source_vintage_as_of"]),
        )
        assert str(rows[0][0]) == expected_uri == built.manifest_uri
        assert str(rows[0][1]) == built.manifest_hash
        assert set(manifest["artifacts"]) == {"daily_bar", "trade_calendar"}
        for domain, entry in manifest["artifacts"].items():
            assert int(entry["row_count"]) == (2 if domain == "daily_bar" else 2)
            if domain == "daily_bar":
                assert entry["kind"] == "canonical_partition_set"
                assert "uri" not in entry
            else:
                assert (env_root["normalized"] / str(entry["uri"])).is_file()

    def test_exact_retry_idempotent_replay(self, conn, env_root):
        """Mandatory 12: an exact second build of the same canonical
        run replays idempotently - same snapshot id, no duplicate
        ledger row, no new artifacts."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _build(conn, env_root, result.canonical_run_id)
        second = _build(conn, env_root, result.canonical_run_id)
        assert second.idempotent_replay is True
        assert second.snapshot_id == first.snapshot_id
        assert second.manifest_hash == first.manifest_hash
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM meta_snapshot_build WHERE snapshot_id = ?",
                [first.snapshot_id],
            ).fetchone()[0]
            == 1
        )

    def test_conflicting_duplicate_ledger_row_fails(self, conn, env_root):
        """Mandatory 13: a ledger row with the same snapshot id whose
        physical state cannot be verified (forged/foreign manifest
        binding) -> the replay verification fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "UPDATE meta_snapshot_build SET manifest_uri = ? WHERE snapshot_id = ?",
            [
                "snapshot/contract=snapshot-v1/as_of=20260101T000000Z/snapshot=x/manifest.json",
                built.snapshot_id,
            ],
        )
        with pytest.raises((SnapshotVerifierError, SnapshotBuilderError)):
            _build(conn, env_root, result.canonical_run_id)

    def test_crash_residue_directory_recovers(self, conn, env_root, monkeypatch):
        """Mandatory 12/13 (crash leg): a ledger commit failure leaves
        deterministic residue that an exact retry can recover."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        builder = SnapshotBuilder(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        )

        def _fail_commit(**kwargs):
            raise RuntimeError("injected ledger commit failure")

        monkeypatch.setattr(builder, "_commit_ledger", _fail_commit)
        with pytest.raises(RuntimeError, match="ledger commit failure"):
            builder.build(result.canonical_run_id)
        manifests = list((env_root["normalized"] / "snapshot").rglob("manifest.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        snapshot_id = str(manifest["snapshot_id"])
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM meta_snapshot_build WHERE snapshot_id = ?", [snapshot_id]
            ).fetchone()[0]
            == 0
        )

        retry = _build(conn, env_root, result.canonical_run_id)
        assert retry.snapshot_id == snapshot_id
        assert retry.idempotent_replay is False
        assert (
            verify_snapshot(
                conn,
                snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            ).snapshot_id
            == snapshot_id
        )

    def test_partial_residue_recovers(self, conn, env_root, monkeypatch):
        """A missing deterministic artifact is written on exact retry."""
        result = _canonical_success(conn, env_root, domains=("daily_bar", "trade_calendar"))
        builder = SnapshotBuilder(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        )

        monkeypatch.setattr(
            builder,
            "_commit_ledger",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected ledger commit failure")),
        )
        with pytest.raises(RuntimeError):
            builder.build(result.canonical_run_id)
        manifest_path = next((env_root["normalized"] / "snapshot").rglob("manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = env_root["normalized"] / str(manifest["artifacts"]["trade_calendar"]["uri"])
        artifact_path.unlink()
        retry = _build(conn, env_root, result.canonical_run_id)
        assert retry.status == "SUCCESS"
        assert artifact_path.is_file()

    def test_conflicting_residue_refuses(self, conn, env_root, monkeypatch):
        """A deterministic path with different bytes is a hard conflict."""
        result = _canonical_success(conn, env_root, domains=("daily_bar", "trade_calendar"))
        builder = SnapshotBuilder(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        )
        monkeypatch.setattr(
            builder,
            "_commit_ledger",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected ledger commit failure")),
        )
        with pytest.raises(RuntimeError):
            builder.build(result.canonical_run_id)
        manifest_path = next((env_root["normalized"] / "snapshot").rglob("manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = env_root["normalized"] / str(manifest["artifacts"]["trade_calendar"]["uri"])
        artifact_path.write_bytes(b"conflicting bytes")
        with pytest.raises(SnapshotBuilderError, match="conflict|different bytes"):
            _build(conn, env_root, result.canonical_run_id)
        assert conn.execute("SELECT COUNT(*) FROM meta_snapshot_build").fetchone()[0] == 0

    def test_snapshot_id_deterministic_across_environments(self, conn, env_root, tmp_path_factory):
        """Mandatory 14 (same-environment semantics): the snapshot
        identity is a deterministic function of the canonical
        run-level seals - wiping the snapshot layer entirely (ledger
        row + artifacts) and rebuilding from the SAME canonical run
        yields the SAME snapshot id. (Cross-environment byte equality
        is deliberately NOT asserted: the raw-evidence meta carries
        the ingest wall-clock, so canonical run ids differ across
        independently ingested environments - the identity determinism
        claim is about the same verified canonical truth.)"""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _build(conn, env_root, result.canonical_run_id)
        # wipe the snapshot layer completely, then rebuild
        conn.execute("DELETE FROM meta_snapshot_build WHERE snapshot_id = ?", [first.snapshot_id])
        import shutil

        snapshot_contract_dir = env_root["normalized"] / Path(*Path(first.manifest_uri).parts[:2])
        shutil.rmtree(snapshot_contract_dir)
        second = _build(conn, env_root, result.canonical_run_id)
        assert second.snapshot_id == first.snapshot_id
        assert second.manifest_hash == first.manifest_hash

    def test_artifacts_deterministic_bytes(self, conn, env_root, tmp_path_factory):
        """Mandatory 14 (byte level): wiping the snapshot layer and
        rebuilding from the same canonical run yields byte-identical
        artifacts (content hashes + aggregate seals)."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _build(conn, env_root, result.canonical_run_id)
        conn.execute("DELETE FROM meta_snapshot_build WHERE snapshot_id = ?", [first.snapshot_id])
        import shutil

        snapshot_contract_dir = env_root["normalized"] / Path(*Path(first.manifest_uri).parts[:2])
        shutil.rmtree(snapshot_contract_dir)
        second = _build(conn, env_root, result.canonical_run_id)
        assert second.manifest_hash == first.manifest_hash
        assert second.artifact_set_hash == first.artifact_set_hash
        assert second.snapshot_semantic_hash == first.snapshot_semantic_hash
        m1 = _snapshot_manifest(env_root, first)["artifacts"]
        m2 = _snapshot_manifest(env_root, second)["artifacts"]
        assert m1 == m2

    def test_different_canonical_run_different_snapshot(self, conn, env_root):
        """Mandatory 15: a DIFFERENT canonical run (superset input
        world) yields a DIFFERENT snapshot id; the original snapshot
        stays intact."""
        first_run = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _build(conn, env_root, first_run.canonical_run_id)
        _seed_bars(conn, env_root, "req-new-bars", received_at=T1)
        second_run = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second_run.status == "SUCCESS"
        second = _build(conn, env_root, second_run.canonical_run_id)
        assert second.snapshot_id != first.snapshot_id
        assert conn.execute("SELECT COUNT(*) FROM meta_snapshot_build").fetchone()[0] == 2

    def test_identity_from_canonical_seals_not_rows(self, conn, env_root):
        """Mandatory 16: the snapshot identity is derived from the
        canonical RUN-LEVEL seals (manifest hash / requested domains
        hash / selected semantic hash / as_of) + the snapshot contract
        + the contract-specific identity component - all present in the manifest
        and physically recomputable."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        assert manifest["canonical_run_id"] == result.canonical_run_id
        ledger_canonical = conn.execute(
            "SELECT manifest_hash, requested_domains_hash, selected_semantic_hash, as_of "
            "FROM meta_canonicalization_run WHERE canonical_run_id = ?",
            [result.canonical_run_id],
        ).fetchone()
        assert manifest["canonical_manifest_hash"] == str(ledger_canonical[0])
        assert manifest["canonical_requested_domains_hash"] == str(ledger_canonical[1])
        assert manifest["canonical_selected_semantic_hash"] == str(ledger_canonical[2])
        expected_market_as_of = daily_bar_latest_session_close_at("2026-08-14").astimezone(UTC)
        assert manifest["market_as_of"] == expected_market_as_of.isoformat()
        assert manifest["source_vintage_as_of"]
        assert datetime.fromisoformat(manifest["source_vintage_as_of"]) > expected_market_as_of
        assert "canonical_as_of" not in manifest
        assert manifest["snapshot_contract_version"] == "snapshot-daily-v2"
        assert manifest["daily_bar_event_eligibility"] == daily_bar_event_eligibility_binding()
        assert (
            manifest["artifacts"]["daily_bar"]["event_eligibility"]
            == daily_bar_event_eligibility_binding()
        )
        assert manifest["snapshot_builder_code_fingerprint"] == (
            logical_daily_snapshot_semantics_fingerprint()
        )
        assert manifest["snapshot_base_hash"]

    def test_logical_daily_snapshot_does_not_use_legacy_source_fingerprint(
        self, conn, env_root, monkeypatch
    ):
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        import ashare_state.snapshot.builder as snapshot_builder
        import ashare_state.snapshot.daily as daily_snapshot

        def fail_if_called() -> str:
            raise AssertionError("logical daily Snapshot used the legacy source fingerprint")

        monkeypatch.setattr(snapshot_builder, "snapshot_builder_code_fingerprint", fail_if_called)
        monkeypatch.setattr(
            daily_snapshot, "snapshot_builder_code_fingerprint", fail_if_called, raising=False
        )
        built = _build(conn, env_root, result.canonical_run_id)
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.snapshot_id == built.snapshot_id

    def test_logical_daily_semantics_version_changes_snapshot_identity(
        self, conn, env_root, monkeypatch
    ):
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        first = _build(conn, env_root, result.canonical_run_id)
        first_manifest = _snapshot_manifest(env_root, first)

        import ashare_state.snapshot.builder as snapshot_builder

        monkeypatch.setattr(
            snapshot_builder,
            "LOGICAL_DAILY_SNAPSHOT_SEMANTICS_VERSION",
            "snapshot-daily-semantics-test-v2",
        )
        second = _build(conn, env_root, result.canonical_run_id)
        second_manifest = _snapshot_manifest(env_root, second)

        assert first.snapshot_id != second.snapshot_id
        assert (
            first_manifest["snapshot_builder_code_fingerprint"]
            != second_manifest["snapshot_builder_code_fingerprint"]
        )

    def test_legacy_non_daily_snapshot_keeps_source_fingerprint_behavior(
        self, conn, env_root, monkeypatch
    ):
        result = _canonical_success(conn, env_root, domains=("trade_calendar",))
        import ashare_state.snapshot.builder as snapshot_builder
        import ashare_state.snapshot.verifier as snapshot_verifier

        legacy_fingerprint = snapshot_builder_code_fingerprint()
        monkeypatch.setattr(
            snapshot_builder, "snapshot_builder_code_fingerprint", lambda: legacy_fingerprint
        )
        monkeypatch.setattr(
            snapshot_verifier, "snapshot_builder_code_fingerprint", lambda: legacy_fingerprint
        )

        def fail_if_called() -> str:
            raise AssertionError("legacy Snapshot used daily semantics")

        monkeypatch.setattr(
            snapshot_builder, "logical_daily_snapshot_semantics_fingerprint", fail_if_called
        )

        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        assert manifest["snapshot_contract_version"] != "snapshot-daily-v2"
        assert manifest["snapshot_builder_code_fingerprint"] == legacy_fingerprint
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.snapshot_id == built.snapshot_id

        monkeypatch.setattr(snapshot_builder, "snapshot_builder_code_fingerprint", lambda: "f" * 64)
        monkeypatch.setattr(
            snapshot_verifier, "snapshot_builder_code_fingerprint", lambda: "f" * 64
        )
        with pytest.raises(SnapshotVerifierError, match="DIFFERENT snapshot builder code"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_artifact_set_equals_requested_domains(self, conn, env_root):
        """Mandatory 17: the artifact set is EXACTLY the requested
        domain set - a single-domain snapshot carries no other domain
        file."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        assert list(manifest["artifacts"]) == ["daily_bar"]
        base = env_root["normalized"] / Path(*Path(built.manifest_uri).parts[:2])
        assert sorted(p.name for p in base.rglob("*.parquet")) == []
        assert manifest["artifacts"]["daily_bar"]["kind"] == "canonical_partition_set"
        assert len(_daily_partition_entries(manifest)) == 1

    def test_missing_canonical_partition_blocks_snapshot_before_publication(self, conn, env_root):
        """Invalid referenced files fail before Snapshot manifest/ledger publication."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        canonical_manifest = _canonical_manifest(env_root, result)
        partition = canonical_manifest["daily_bar_partitions"][0]
        fact_path = env_root["normalized"] / str(partition["fact_artifact"]["uri"])
        fact_path.unlink()
        with pytest.raises(SnapshotBuilderError, match="partition set is not consumable"):
            _build(conn, env_root, result.canonical_run_id)
        assert list((env_root["normalized"] / "snapshot").rglob("manifest.json")) == []
        assert conn.execute("SELECT COUNT(*) FROM meta_snapshot_build").fetchone()[0] == 0

    def test_domain_partitioned_rows(self, conn, env_root):
        """Non-daily domains are copied; daily_bar references Canonical L0 files."""
        result = _canonical_success(conn, env_root)
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        expected_counts = {
            "trade_calendar": 2,
            "daily_bar": 2,
            "security_status": 1,
            "limit_price": 1,
            "adj_factor": 1,
        }
        for domain, count in expected_counts.items():
            entry = manifest["artifacts"][domain]
            assert int(entry["row_count"]) == count
            if domain == "daily_bar":
                assert entry["kind"] == "canonical_partition_set"
                assert sum(int(part["row_count"]) for part in entry["partitions"]) == count
                for part in entry["partitions"]:
                    fact_path = env_root["normalized"] / str(part["fact_artifact"]["uri"])
                    lineage_path = env_root["normalized"] / str(part["lineage_artifact"]["uri"])
                    assert pl.read_parquet(fact_path).height == count
                    assert pl.read_parquet(lineage_path).height == count
            else:
                frame = pl.read_parquet(env_root["normalized"] / str(entry["uri"]))
                assert frame.height == count
                assert {r["canonical_domain"] for r in frame.to_dicts()} == {domain}
                assert str(frame.schema) == str(polars_domain_schema(domain))
        assert built.row_count_total == sum(expected_counts.values())

    def test_rows_sorted_by_canonical_key(self, conn, env_root):
        """The fixed16 Canonical artifact is time-first, then UUID-byte ordered."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        fact = pl.read_parquet(_daily_fact_path(env_root, manifest))
        keys = list(zip(fact["trade_date"].to_list(), fact["security_id"].to_list(), strict=True))
        assert all(isinstance(identity, bytes) and len(identity) == 16 for _, identity in keys)
        assert keys == sorted(keys)

    def test_multi_month_daily_truth_is_partitioned_and_not_copied(self, conn, env_root):
        """Three deterministic month partitions remain the sole durable fact files."""
        _seed_base(conn, env_root)
        _seed_status(conn, env_root)
        _seed_adj(conn, env_root)
        _seed_cal(conn, env_root)
        monthly_bars = [
            {**row, "KLINE_TIME": trade_day}
            for trade_day in (20260630, 20260701, 20260814)
            for row in _BAR_ROWS
        ]
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-bars",
            payload=monthly_bars,
        )
        canonical = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert canonical.status == "SUCCESS"
        canonical_manifest = _canonical_manifest(env_root, canonical)
        partitions = canonical_manifest["daily_bar_partitions"]
        assert [part["partition"] for part in partitions] == [
            "2026-06",
            "2026-07",
            "2026-08",
        ]
        assert [int(part["row_count"]) for part in partitions] == [2, 2, 2]
        fact_rows = []
        for part in partitions:
            fact_path = env_root["normalized"] / str(part["fact_artifact"]["uri"])
            lineage_path = env_root["normalized"] / str(part["lineage_artifact"]["uri"])
            assert pq.ParquetFile(fact_path).schema_arrow.field("security_id").type == pa.binary(16)
            assert pq.ParquetFile(lineage_path).schema_arrow.field("security_id").type == pa.binary(
                16
            )
            assert (
                str(pq.ParquetFile(fact_path).schema.column(0).physical_type)
                == "FIXED_LEN_BYTE_ARRAY"
            )
            assert (
                str(pq.ParquetFile(lineage_path).schema.column(0).physical_type)
                == "FIXED_LEN_BYTE_ARRAY"
            )
            fact_rows.extend(pl.read_parquet(fact_path).to_dicts())
        fact_keys = [(row["trade_date"], row["security_id"]) for row in fact_rows]
        assert fact_keys == sorted(fact_keys)
        assert all(isinstance(identity, bytes) and len(identity) == 16 for _, identity in fact_keys)

        snapshot = _build(conn, env_root, canonical.canonical_run_id)
        snapshot_manifest = _snapshot_manifest(env_root, snapshot)
        assert snapshot_manifest["artifacts"]["daily_bar"]["partitions"] == partitions
        assert snapshot.row_count_total == 6
        snapshot_base = env_root["normalized"] / Path(*Path(snapshot.manifest_uri).parts[:2])
        assert list(snapshot_base.rglob("*.parquet")) == []
        audited = verify_snapshot(
            conn,
            snapshot.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert audited.domain_rows == {"daily_bar": ()}

    def test_daily_partition_set_snapshot_and_external_facade(self, conn, env_root):
        """Two independently sealed months retain their real source-run ids."""
        from ashare_state.readmodel import DuckDBReadModel

        _seed_base(conn, env_root)
        master_run_id = conn.execute(
            "SELECT normalization_run_id FROM meta_provider_normalization_run "
            "WHERE raw_request_id = 'req-master' AND status = 'SUCCESS'"
        ).fetchone()[0]
        later_cutoff = datetime(2026, 10, 1, 0, 0, 1, tzinfo=UTC)
        month_specs = (
            ("2026-08", 20260814, T0, "req-bars-2026-08"),
            ("2026-09", 20260915, later_cutoff, "req-bars-2026-09"),
        )
        daily_run_ids: dict[str, str] = {}
        for month, trade_day, received_at, request_id in month_specs:
            rows = [{**row, "KLINE_TIME": trade_day} for row in _BAR_ROWS]
            _persist_raw(
                conn,
                env_root,
                dataset="daily_bar",
                endpoint="MarketData.query_kline",
                surface="daily_bar",
                request_id=request_id,
                payload=rows,
                received_at=received_at,
            )
            daily_run_ids[month] = str(
                conn.execute(
                    "SELECT normalization_run_id FROM meta_provider_normalization_run "
                    "WHERE raw_request_id = ? AND status = 'SUCCESS'",
                    [request_id],
                ).fetchone()[0]
            )

        class _MonthScopedCanonicalRunner(CanonicalRunner):
            def __init__(self, *args: Any, allowed_run_ids: set[str], **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self.allowed_run_ids = frozenset(allowed_run_ids)

            def _surface_runs(self, normalization_surface, provider_datasets):
                rows = super()._surface_runs(normalization_surface, provider_datasets)
                return [
                    row for row in rows if str(row["normalization_run_id"]) in self.allowed_run_ids
                ]

        canonical_ids: dict[str, str] = {}
        for month, _trade_day, cutoff, _request_id in month_specs:
            runner = _MonthScopedCanonicalRunner(
                conn,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
                allowed_run_ids={str(master_run_id), daily_run_ids[month]},
            )
            result = runner.run(cutoff, domains=("daily_bar",))
            assert result.status == "SUCCESS"
            canonical_ids[month] = result.canonical_run_id

        builder = SnapshotBuilder(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        )
        built = builder.build_daily_partition_set(
            (canonical_ids["2026-09"], canonical_ids["2026-08"])
        )
        manifest = _snapshot_manifest(env_root, built)
        assert manifest["snapshot_contract_version"] == "snapshot-daily-v3"
        assert [source["partition_month"] for source in manifest["canonical_sources"]] == [
            "2026-08",
            "2026-09",
        ]
        partitions = manifest["artifacts"]["daily_bar"]["partitions"]
        assert [part["source_canonical_run_id"] for part in partitions] == [
            canonical_ids["2026-08"],
            canonical_ids["2026-09"],
        ]
        assert built.row_count_total == 4
        snapshot_dir = (env_root["normalized"] / built.manifest_uri).parent
        assert list(snapshot_dir.rglob("*.parquet")) == []

        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
            retain_domain_rows=False,
        )
        assert verified.canonical_run_id == canonical_ids["2026-09"]
        replay = builder.build_daily_partition_set(
            (canonical_ids["2026-08"], canonical_ids["2026-09"])
        )
        assert replay.idempotent_replay is True
        assert replay.snapshot_id == built.snapshot_id

        readmodel = DuckDBReadModel(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        readmodel.rebuild(built.snapshot_id)
        readmodel.verify_readmodel(built.snapshot_id)
        db = readmodel.open_read_only(built.snapshot_id)
        try:
            assert (
                db.execute(
                    "SELECT table_type FROM information_schema.tables "
                    "WHERE table_name='rm_daily_bar'"
                ).fetchone()[0]
                == "VIEW"
            )
            assert db.execute("SELECT count(*) FROM rm_daily_bar").fetchone()[0] == 4
            ownership = db.execute(
                "SELECT canonical_run_id, strftime(min(trade_date), '%Y-%m'), count(*) "
                "FROM rm_daily_bar GROUP BY canonical_run_id ORDER BY 2"
            ).fetchall()
        finally:
            db.close()
        assert ownership == [
            (canonical_ids["2026-08"], "2026-08", 2),
            (canonical_ids["2026-09"], "2026-09", 2),
        ]

    def test_canonical_source_set_hash_changes_snapshot_identity(self):
        common = {
            "canonical_run_id": "run-anchor",
            "canonical_manifest_hash": "a" * 64,
            "canonical_requested_domains_hash": "b" * 64,
            "canonical_selected_semantic_hash": "c" * 64,
            "canonical_as_of": "2026-10-01T00:00:01+00:00",
            "snapshot_contract_version": "snapshot-daily-v3",
            "snapshot_builder_code_fingerprint": "d" * 64,
        }
        left = snapshot_base_hash_from_primitives(**common, canonical_source_set_hash="e" * 64)
        right = snapshot_base_hash_from_primitives(**common, canonical_source_set_hash="f" * 64)
        assert left != right

    def test_lineage_preserved_verbatim(self, conn, env_root):
        """Snapshot keeps the exact Canonical partition/lineage seal, without copying it."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        canonical_manifest = _canonical_manifest(env_root, result)
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        canonical_partitions = canonical_manifest["daily_bar_partitions"]
        snapshot_partitions = _daily_partition_entries(manifest)
        assert snapshot_partitions == canonical_partitions
        assert manifest["artifacts"]["daily_bar"]["kind"] == "canonical_partition_set"
        for partition in snapshot_partitions:
            part_manifest = json.loads(
                (env_root["normalized"] / partition["partition_manifest_uri"]).read_text(
                    encoding="utf-8"
                )
            )
            fact_fields = set(DAILY_BAR_FACT_FIELDS) | {"security_id", "trade_date"}
            lineage_fields = set(part_manifest["constant_fields"]) | set(
                part_manifest["variable_fields"]
            )
            assert "provenance_values" not in part_manifest
            assert (
                set(
                    pl.read_parquet(
                        env_root["normalized"] / part_manifest["fact_artifact"]["uri"]
                    ).columns
                )
                == fact_fields
            )
            stored_lineage = set(
                pl.read_parquet(
                    env_root["normalized"] / part_manifest["lineage_artifact"]["uri"]
                ).columns
            )
            assert stored_lineage == {
                "security_id",
                "trade_date",
                *part_manifest["variable_fields"],
            }
            assert {
                "source_row_identity_hash",
                "source_raw_request_id",
                "source_raw_evidence_hash",
                "source_mapper_identity",
                "source_policy_version",
                "available_at",
                "ingested_at",
            } <= lineage_fields

    def test_verify_snapshot_green(self, conn, env_root):
        """Mandatory 22: verify_snapshot on a healthy build returns
        the verified truth (domains + materialized rows)."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.snapshot_id == built.snapshot_id
        assert verified.canonical_run_id == result.canonical_run_id
        assert verified.requested_domains == ("daily_bar",)
        assert verified.domain_rows == {"daily_bar": ()}
        assert verified.as_of == AS_OF_LATE
        assert verified.market_as_of == daily_bar_latest_session_close_at("2026-08-14").astimezone(
            UTC
        )
        assert verified.source_vintage_as_of is not None

    def test_verify_snapshot_seal_only_does_not_retain_rows(self, conn, env_root):
        """ReadModel consumers can consume the verified seal without a
        second full in-memory copy of every snapshot row."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
            retain_domain_rows=False,
        )
        assert verified.domain_rows == {"daily_bar": ()}
        assert int(verified.ledger_record["row_count_total"]) == 2

    def test_verify_snapshot_seal_only_uses_batched_parquet_reads(
        self, conn, env_root, monkeypatch
    ):
        """Seal-only verification must not collect a whole Parquet frame."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        import ashare_state.snapshot.verifier as snapshot_verifier

        def forbidden_full_frame_read(*args, **kwargs):
            raise AssertionError("seal-only verification must use bounded Parquet batches")

        monkeypatch.setattr(snapshot_verifier.pl, "read_parquet", forbidden_full_frame_read)
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
            retain_domain_rows=False,
        )
        assert verified.domain_rows == {"daily_bar": ()}

    def test_consume_snapshot_seal_does_not_project_canonical_rows(
        self, conn, env_root, monkeypatch
    ):
        """The downstream seal hand-off must not load selected.parquet."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        import ashare_state.snapshot.verifier as snapshot_verifier

        def _forbidden(*args, **kwargs):
            raise AssertionError("sealed snapshot consumption must not project canonical rows")

        monkeypatch.setattr(snapshot_verifier, "load_canonical_projection", _forbidden)
        monkeypatch.setattr(snapshot_verifier, "open_canonical_projection_source", _forbidden)
        monkeypatch.setattr(snapshot_verifier, "project_canonical_snapshot", _forbidden)
        monkeypatch.setattr(snapshot_verifier.pl, "read_parquet", _forbidden)
        verified = consume_snapshot_seal(
            conn,
            built.snapshot_id,
            normalized_root=env_root["normalized"],
        )
        assert verified.domain_rows == {"daily_bar": ()}
        assert verified.requested_domains == ("daily_bar",)

    def test_consume_snapshot_seal_is_shallow_but_deep_audit_detects_tamper(self, conn, env_root):
        """Routine seal consumption avoids fact scans; explicit deep audit checks bytes."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        _replace_daily_fact(env_root, manifest, close=999.0)
        consumed = consume_snapshot_seal(
            conn,
            built.snapshot_id,
            normalized_root=env_root["normalized"],
        )
        assert consumed.domain_rows == {"daily_bar": ()}
        with pytest.raises(SnapshotVerifierError, match="deep audit failed|content hash"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_consume_snapshot_seal_rejects_canonical_manifest_drift(self, conn, env_root):
        """The seal hand-off still binds the canonical manifest to its ledger."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            ["0" * 64, result.canonical_run_id],
        )
        with pytest.raises(SnapshotVerifierError, match="Canonical provenance|manifest"):
            consume_snapshot_seal(
                conn,
                built.snapshot_id,
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_consumes_canonical_seal_without_recursive_full_verify(
        self, conn, env_root, monkeypatch
    ):
        """A durable snapshot boundary must not re-run canonical closure."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        import ashare_state.canonical.verifier as canonical_verifier

        def unexpected_recursive_verify(*args, **kwargs):
            raise AssertionError("snapshot verifier recursively reverified canonical closure")

        monkeypatch.setattr(
            canonical_verifier,
            "verify_canonical_run_for_consumption",
            unexpected_recursive_verify,
        )
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.snapshot_id == built.snapshot_id

    def test_verify_snapshot_unknown_id_rejected(self, conn, env_root):
        """Mandatory 23: an unknown snapshot id is rejected."""
        _seed_base(conn, env_root)
        with pytest.raises(SnapshotVerifierError, match="does not exist"):
            verify_snapshot(
                conn,
                str(uuid.uuid4()),
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_manifest_bytes_tamper(self, conn, env_root):
        """Mandatory 24: manifest bytes tampered -> fail closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        (env_root["normalized"] / str(built.manifest_uri)).write_bytes(b"tampered-manifest")
        with pytest.raises(SnapshotVerifierError, match="manifest hash"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_manifest_field_rebind(self, conn, env_root):
        """Mandatory 24 (field leg): manifest field rebound + outer
        ledger hash -> fail closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        _rebind_snapshot_manifest(
            env_root, conn, built, lambda d: d.__setitem__("row_count_total", 999)
        )
        with pytest.raises(SnapshotVerifierError, match="row_count_total"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_domain_artifact_tamper(self, conn, env_root):
        """Mandatory 25: a domain parquet's bytes are tampered ->
        fail closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        _daily_fact_path(env_root, manifest).write_bytes(b"tampered-domain")
        with pytest.raises(
            SnapshotVerifierError,
            match="daily partition artifact|daily partition Parquet footer|deep audit failed",
        ):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_domain_artifact_missing(self, conn, env_root):
        """Mandatory 25 (missing leg): a domain parquet is deleted ->
        fail closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        _daily_fact_path(env_root, manifest).unlink()
        with pytest.raises(SnapshotVerifierError, match="artifact missing|missing"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_business_tamper_with_rebound_seals(self, conn, env_root):
        """A rehashed Snapshot cannot change the Canonical logical fact binding."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        _rebind_snapshot_manifest(
            env_root,
            conn,
            built,
            lambda doc: doc["artifacts"]["daily_bar"]["partitions"][0].__setitem__(
                "logical_content_hash", "0" * 64
            ),
        )
        with pytest.raises(SnapshotVerifierError, match="exact Canonical partitions"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_lineage_tamper_with_rebound_seals(self, conn, env_root):
        """A rehashed Snapshot cannot alter the Canonical lineage artifact binding."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        _rebind_snapshot_manifest(
            env_root,
            conn,
            built,
            lambda doc: doc["artifacts"]["daily_bar"]["partitions"][0][
                "lineage_artifact"
            ].__setitem__("content_hash", "0" * 64),
        )
        with pytest.raises(SnapshotVerifierError, match="exact Canonical partitions"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_schema_hash_is_physical(self, conn, env_root):
        """The manifest schema_hash cannot be rebound away from the
        physical schema while the outer manifest hash is rebound."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        _rebind_snapshot_manifest(
            env_root,
            conn,
            built,
            lambda doc: doc["artifacts"]["daily_bar"]["partitions"][0]["fact_artifact"].__setitem__(
                "schema_hash", "0" * 64
            ),
        )
        with pytest.raises(SnapshotVerifierError, match="exact Canonical partitions"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_identity_rebind(self, conn, env_root):
        """Mandatory 26: the ledger snapshot_semantic_hash is rebound
        -> the physical recompute fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "UPDATE meta_snapshot_build SET snapshot_semantic_hash = ? WHERE snapshot_id = ?",
            ["0" * 64, built.snapshot_id],
        )
        with pytest.raises(SnapshotVerifierError, match="ledger seal"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_uri_rebind(self, conn, env_root):
        """Mandatory 26 (uri leg): the ledger manifest_uri is rebound
        -> the deterministic anchor fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "UPDATE meta_snapshot_build SET manifest_uri = ? WHERE snapshot_id = ?",
            [
                "snapshot/contract=snapshot-v1/as_of=20200101T000000Z/"
                f"snapshot={built.snapshot_id}/manifest.json",
                built.snapshot_id,
            ],
        )
        with pytest.raises(SnapshotVerifierError, match="not deterministic"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_daily_semantics_fingerprint_mismatch(
        self, conn, env_root, monkeypatch
    ):
        """A logical daily Snapshot with a different semantics seal fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        import ashare_state.snapshot.daily as daily_snapshot

        monkeypatch.setattr(
            daily_snapshot, "logical_daily_snapshot_semantics_fingerprint", lambda: "f" * 64
        )
        with pytest.raises(SnapshotVerifierError, match="DIFFERENT output semantics"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_does_not_replay_selected_canonical_artifact(self, conn, env_root):
        """The daily fact audit depends on sealed L0 partitions, not selected.parquet replay."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        canonical_manifest = _canonical_manifest(env_root, result)
        uri = str(canonical_manifest["artifacts"]["selected"]["uri"])
        (env_root["normalized"] / uri).write_bytes(b"post-build-tamper")
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.snapshot_id == built.snapshot_id

    def test_verify_snapshot_canonical_input_disappearance(self, conn, env_root):
        """A downstream snapshot consumes the canonical manifest seal.

        Removing an upstream CR-2 ledger row after the snapshot boundary
        does not invalidate the already materialized snapshot; the canonical
        owner/continuity verifier remains responsible for deep upstream
        re-audit.
        """
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "DELETE FROM meta_provider_normalization_run WHERE raw_request_id = 'req-bars'"
        )
        verified = verify_snapshot(
            conn,
            built.snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.snapshot_id == built.snapshot_id

    def test_verify_snapshot_requested_domain_drift(self, conn, env_root):
        """Mandatory 29: the snapshot's requested domain set no longer
        equals the canonical run's (ledger domains tampered) -> fail
        closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "UPDATE meta_snapshot_build SET requested_domains_json = ? WHERE snapshot_id = ?",
            ['["daily_bar","trade_calendar"]', built.snapshot_id],
        )
        with pytest.raises(SnapshotVerifierError, match="domains differ"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_builder_immutable_no_overwrite(self, conn, env_root):
        """Mandatory 30: identical immutable bytes are a no-op and
        different bytes are rejected without overwrite."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        uri = _daily_fact_path(env_root, manifest)
        before = uri.read_bytes()
        from ashare_state.snapshot.builder import _write_immutable

        _write_immutable(uri, before)
        assert uri.read_bytes() == before
        with pytest.raises(SnapshotBuilderError, match="immutable|conflict"):
            _write_immutable(uri, b"x")
        assert uri.read_bytes() == before


def _schema_projection_row(domain: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "canonical_domain": domain,
        "available_at": "2026-08-14T00:00:01+00:00",
        "ingested_at": "2026-08-14T00:00:01+00:00",
        "availability_basis": "OBSERVED_AT_INGEST",
        "availability_policy_version": "v",
        "selected_provider": "amazingdata",
        "source_normalization_run_id": "r",
        "source_output_name": "main",
        "source_row_ordinal": 1,
        "source_row_identity_hash": "h",
        "source_raw_request_id": "q",
        "source_raw_evidence_hash": "e",
        "source_mapper_identity": "m",
        "source_policy_version": "p",
        "canonical_contract_version": "cr3-v1",
    }
    if domain == "trade_calendar":
        row.update(
            canonical_key='["SH","2026-08-14"]',
            market="SH",
            trade_date="2026-08-14",
        )
    else:
        row.update(
            canonical_key='["sec-1","2026-08-14"]',
            security_id="sec-1",
            trade_date="2026-08-14",
        )
        if domain == "adj_factor":
            row["canonical_key"] = '["sec-1","2026-08-14","adj_factor"]'
    return row


# --------------------- CR-4.2: strict schema projection (P0-A07/A09)


@pytest.mark.integration
class TestSnapshotSchemaProjection:
    """Unit-level strictness of the versioned schema registry: key
    round-trip, PIT contract and typed projection all fail closed."""

    def test_key_roundtrip_validation(self):
        validate_canonical_key("daily_bar", '["sec-1","2026-08-14"]')
        validate_canonical_key("adj_factor", '["sec-1","2026-08-10","adj_factor"]')
        with pytest.raises(SnapshotSchemaError, match="arity"):
            validate_canonical_key("daily_bar", '["sec-1"]')
        with pytest.raises(SnapshotSchemaError, match="not a JSON array"):
            validate_canonical_key("daily_bar", '"sec-1"')
        with pytest.raises(SnapshotSchemaError, match="round-trip"):
            validate_canonical_key("daily_bar", '["sec-1", "2026-08-14"]')
        with pytest.raises(SnapshotSchemaError, match="non-string"):
            validate_canonical_key("daily_bar", '["sec-1",14]')

    def test_pit_contract_enforced(self):
        row = {
            "canonical_domain": "daily_bar",
            "canonical_key": '["sec-1","2026-08-14"]',
            "security_id": "sec-1",
            "trade_date": "2026-08-14",
            "available_at": "2026-09-02T00:00:00+00:00",
            "ingested_at": "2026-09-02T00:00:00+00:00",
            "availability_basis": "OBSERVED_AT_INGEST",
            "availability_policy_version": "v",
            "selected_provider": "amazingdata",
            "source_normalization_run_id": "r",
            "source_output_name": "main",
            "source_row_ordinal": 1,
            "source_row_identity_hash": "h",
            "source_raw_request_id": "q",
            "source_raw_evidence_hash": "e",
            "source_mapper_identity": "m",
            "source_policy_version": "p",
            "canonical_contract_version": "cr3-v1",
            "open": 1.0,
        }
        as_of = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(SnapshotSchemaError, match="PIT contract"):
            project_selected_row(
                "daily_bar", row, canonical_run_id="c", snapshot_id="s", as_of=as_of
            )

    @pytest.mark.parametrize(
        ("domain", "field", "value"),
        [
            ("trade_calendar", "market", "SZ"),
            ("trade_calendar", "trade_date", "2026-08-15"),
            ("daily_bar", "security_id", "sec-2"),
            ("daily_bar", "trade_date", "2026-08-15"),
            ("security_status", "security_id", "sec-2"),
            ("security_status", "trade_date", "2026-08-15"),
            ("limit_price", "security_id", "sec-2"),
            ("limit_price", "trade_date", "2026-08-15"),
            ("adj_factor", "security_id", "sec-2"),
            ("adj_factor", "trade_date", "2026-08-15"),
        ],
    )
    def test_explicit_key_bindings_fail_closed(self, domain, field, value):
        row = _schema_projection_row(domain)
        row[field] = value
        with pytest.raises(SnapshotSchemaError, match="does not match"):
            project_selected_row(
                domain,
                row,
                canonical_run_id="c",
                snapshot_id="s",
                as_of=AS_OF_LATE,
            )

    def test_adj_factor_projection_is_typed_key_component(self):
        projected = project_selected_row(
            "adj_factor",
            _schema_projection_row("adj_factor"),
            canonical_run_id="c",
            snapshot_id="s",
            as_of=AS_OF_LATE,
        )
        assert projected["factor_type"] == "adj_factor"

    def test_typed_projection_fail_closed(self):
        base = {
            "canonical_domain": "daily_bar",
            "canonical_key": '["sec-1","2026-08-14"]',
            "security_id": "sec-1",
            "trade_date": "2026-08-14",
            "available_at": "2026-08-14T00:00:01+00:00",
            "ingested_at": "2026-08-14T00:00:01+00:00",
            "availability_basis": "OBSERVED_AT_INGEST",
            "availability_policy_version": "v",
            "selected_provider": "amazingdata",
            "source_normalization_run_id": "r",
            "source_output_name": "main",
            "source_row_ordinal": 1,
            "source_row_identity_hash": "h",
            "source_raw_request_id": "q",
            "source_raw_evidence_hash": "e",
            "source_mapper_identity": "m",
            "source_policy_version": "p",
            "canonical_contract_version": "cr3-v1",
            "open": None,
            "close": 1.5,
        }
        as_of = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
        projected = project_selected_row(
            "daily_bar", base, canonical_run_id="c", snapshot_id="s", as_of=as_of
        )
        assert projected["open"] is None  # nullable business value
        assert projected["close"] == 1.5
        from datetime import date as _date

        assert isinstance(projected["trade_date"], _date)
        from datetime import datetime as _dt

        assert isinstance(projected["available_at"], _dt)
        assert projected["available_at"].tzinfo is not None
        bad = {**base, "security_id": None}
        with pytest.raises(SnapshotSchemaError, match="non-nullable"):
            project_selected_row(
                "daily_bar", bad, canonical_run_id="c", snapshot_id="s", as_of=as_of
            )
        bad = {**base, "open": "not-a-number"}
        with pytest.raises(SnapshotSchemaError, match="expects a number"):
            project_selected_row(
                "daily_bar", bad, canonical_run_id="c", snapshot_id="s", as_of=as_of
            )


# ------------------------------------------------------- boundary structure


@pytest.mark.integration
class TestBoundaryStructure:
    """CR-4 boundary guards (work requirement §8): the snapshot and
    readmodel layers NEVER import providers / normalization / raw
    writers and NEVER compute features."""

    @pytest.mark.parametrize("src_root", [SNAPSHOT_SRC, READMODEL_SRC])
    def test_no_provider_or_normalization_access(self, src_root):
        forbidden = ("providers", "normalization", "raw_writer", "RawWriter")
        for py in sorted(src_root.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for bad in forbidden:
                            assert bad not in alias.name, f"{py.name} imports {alias.name}"
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for bad in forbidden:
                        assert bad not in module, f"{py.name} imports from {module}"

    @pytest.mark.parametrize("src_root", [SNAPSHOT_SRC, READMODEL_SRC])
    def test_no_feature_computation_dependencies(self, src_root):
        """No feature/indicator libraries: the layers only re-shape
        verified truth (polars/duckdb/hashlib are structural)."""
        forbidden = ("pandas", "talib", "numpy", "scipy", "sklearn")
        for py in sorted(src_root.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        assert root not in forbidden, f"{py.name} imports {alias.name}"
                if isinstance(node, ast.ImportFrom):
                    root = (node.module or "").split(".")[0]
                    assert root not in forbidden, f"{py.name} imports from {node.module}"

    def test_snapshot_builder_construction_signature(self):
        """The builder accepts no provider/policy/correctness knobs -
        only the governed roots + connection."""
        import inspect

        from ashare_state.snapshot import SnapshotBuilder

        params = inspect.signature(SnapshotBuilder.__init__).parameters
        for forbidden in ("policy", "policies", "tolerance", "providers", "priority"):
            assert forbidden not in params, forbidden
        build_params = inspect.signature(SnapshotBuilder.build).parameters
        assert list(build_params) == ["self", "canonical_run_id"]
