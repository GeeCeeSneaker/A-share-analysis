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
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ashare_state.canonical import CanonicalRunner
from ashare_state.canonical.canonicalizer import (
    _canonical_json,
    _rows_semantic_hash,
)
from ashare_state.canonical.verifier import (
    CanonicalConsumptionError,
    verify_canonical_run_for_consumption,
)
from ashare_state.snapshot import (
    SNAPSHOT_CONTRACT_VERSION,
    SnapshotBuilder,
    SnapshotBuilderError,
    SnapshotSchemaError,
    SnapshotVerifierError,
    snapshot_builder_code_fingerprint,
    snapshot_manifest_uri,
    validate_canonical_key,
    verify_snapshot,
)
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


def _rebind_snapshot_artifact(env_root, conn, result, domain: str, mutate) -> None:
    """Rebind one artifact's physical and aggregate seals after a row edit."""
    manifest_path = env_root["normalized"] / str(result.manifest_uri)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_path = env_root["normalized"] / str(manifest["artifacts"][domain]["uri"])
    rows = pl.read_parquet(artifact_path).to_dicts()
    mutate(rows[0])
    frame = pl.DataFrame(rows, schema=polars_domain_schema(domain))
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    artifact_bytes = buffer.getvalue()
    artifact_path.write_bytes(artifact_bytes)
    entry = manifest["artifacts"][domain]
    entry["content_hash"] = hashlib.sha256(artifact_bytes).hexdigest()
    entry["schema_hash"] = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
    entry["row_count"] = frame.height
    entry["semantic_hash"] = _rows_semantic_hash(rows)
    manifest["artifact_set_hash"] = hashlib.sha256(
        _canonical_json(manifest["artifacts"]).encode("utf-8")
    ).hexdigest()
    manifest["snapshot_semantic_hash"] = hashlib.sha256(
        _canonical_json({d: a["semantic_hash"] for d, a in manifest["artifacts"].items()}).encode(
            "utf-8"
        )
    ).hexdigest()
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, indent=1, ensure_ascii=False
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    conn.execute(
        "UPDATE meta_snapshot_build SET manifest_hash = ?, artifact_set_hash = ?, "
        "snapshot_semantic_hash = ? WHERE snapshot_id = ?",
        [
            hashlib.sha256(manifest_bytes).hexdigest(),
            manifest["artifact_set_hash"],
            manifest["snapshot_semantic_hash"],
            result.snapshot_id,
        ],
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
        expected_uri = snapshot_manifest_uri(built.snapshot_id, AS_OF_LATE)
        assert str(rows[0][0]) == expected_uri == built.manifest_uri
        assert str(rows[0][1]) == built.manifest_hash
        manifest = _snapshot_manifest(env_root, built)
        assert set(manifest["artifacts"]) == {"daily_bar", "trade_calendar"}
        for domain, entry in manifest["artifacts"].items():
            assert (env_root["normalized"] / str(entry["uri"])).is_file()
            assert int(entry["row_count"]) == (2 if domain == "daily_bar" else 2)

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
        assert conn.execute(
            "SELECT COUNT(*) FROM meta_snapshot_build WHERE snapshot_id = ?", [snapshot_id]
        ).fetchone()[0] == 0

        retry = _build(conn, env_root, result.canonical_run_id)
        assert retry.snapshot_id == snapshot_id
        assert retry.idempotent_replay is False
        assert verify_snapshot(
            conn,
            snapshot_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        ).snapshot_id == snapshot_id


    def test_partial_residue_recovers(self, conn, env_root, monkeypatch):
        """A missing deterministic artifact is written on exact retry."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        builder = SnapshotBuilder(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        )

        monkeypatch.setattr(
            builder, "_commit_ledger", lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected ledger commit failure")
            )
        )
        with pytest.raises(RuntimeError):
            builder.build(result.canonical_run_id)
        manifest_path = next((env_root["normalized"] / "snapshot").rglob("manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])
        artifact_path.unlink()
        retry = _build(conn, env_root, result.canonical_run_id)
        assert retry.status == "SUCCESS"
        assert artifact_path.is_file()


    def test_conflicting_residue_refuses(self, conn, env_root, monkeypatch):
        """A deterministic path with different bytes is a hard conflict."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        builder = SnapshotBuilder(
            conn, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
        )
        monkeypatch.setattr(
            builder, "_commit_ledger", lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected ledger commit failure")
            )
        )
        with pytest.raises(RuntimeError):
            builder.build(result.canonical_run_id)
        manifest_path = next((env_root["normalized"] / "snapshot").rglob("manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])
        artifact_path.write_bytes(b"conflicting bytes")
        with pytest.raises(SnapshotBuilderError, match="conflict|different bytes"):
            _build(conn, env_root, result.canonical_run_id)
        assert conn.execute(
            "SELECT COUNT(*) FROM meta_snapshot_build"
        ).fetchone()[0] == 0

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

        shutil.rmtree(env_root["normalized"] / f"snapshot/contract={SNAPSHOT_CONTRACT_VERSION}")
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

        shutil.rmtree(env_root["normalized"] / f"snapshot/contract={SNAPSHOT_CONTRACT_VERSION}")
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
        + the builder code fingerprint - all present in the manifest
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
        assert manifest["canonical_as_of"] == AS_OF_LATE.isoformat()
        assert manifest["snapshot_contract_version"] == SNAPSHOT_CONTRACT_VERSION
        assert manifest["snapshot_builder_code_fingerprint"] == snapshot_builder_code_fingerprint()
        assert manifest["snapshot_base_hash"]

    def test_artifact_set_equals_requested_domains(self, conn, env_root):
        """Mandatory 17: the artifact set is EXACTLY the requested
        domain set - a single-domain snapshot carries no other domain
        file."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        assert list(manifest["artifacts"]) == ["daily_bar"]
        base = env_root["normalized"] / f"snapshot/contract={SNAPSHOT_CONTRACT_VERSION}"
        assert sorted(p.name for p in base.rglob("*.parquet")) == ["daily_bar.parquet"]

    def test_domain_partitioned_rows(self, conn, env_root):
        """Mandatory 18: each domain's parquet carries exactly its own
        rows with the typed snapshot schema."""
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
            frame = pl.read_parquet(env_root["normalized"] / str(entry["uri"]))
            assert frame.height == count
            assert {r["canonical_domain"] for r in frame.to_dicts()} == {domain}
            assert str(frame.schema) == str(polars_domain_schema(domain))
        assert built.row_count_total == sum(expected_counts.values())

    def test_rows_sorted_by_canonical_key(self, conn, env_root):
        """Mandatory 19 (stable order): the per-domain rows are
        written in a FIXED stable order (sorted by canonical_key)."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        rows = pl.read_parquet(
            env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])
        ).to_dicts()
        keys = [r["canonical_key"] for r in rows]
        assert keys == sorted(keys)

    def test_lineage_preserved_verbatim(self, conn, env_root):
        """Mandatory 21: every canonical lineage field is preserved
        verbatim; only canonical_run_id / snapshot_id are added as
        snapshot projections."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        canonical_manifest = _canonical_manifest(env_root, result)
        canonical_rows = pl.read_parquet(
            env_root["normalized"] / str(canonical_manifest["artifacts"]["selected"]["uri"])
        ).to_dicts()
        built = _build(conn, env_root, result.canonical_run_id)
        manifest = _snapshot_manifest(env_root, built)
        snapshot_rows = pl.read_parquet(
            env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])
        ).to_dicts()
        assert len(snapshot_rows) == len(canonical_rows)
        for c, s in zip(canonical_rows, snapshot_rows, strict=True):
            for field in (
                "availability_basis",
                "availability_policy_version",
                "selected_provider",
                "source_normalization_run_id",
                "source_output_name",
                "source_row_ordinal",
                "source_row_identity_hash",
                "source_raw_request_id",
                "source_raw_evidence_hash",
                "source_mapper_identity",
                "source_policy_version",
                "canonical_contract_version",
                "canonical_key",
                "security_id",
                "canonical_domain",
                "open",
                "close",
            ):
                assert s[field] == c[field], field
            # typed time projections preserve the exact instants
            assert s["available_at"].isoformat() == c["available_at"]
            assert s["ingested_at"].isoformat() == c["ingested_at"]
            assert s["trade_date"].isoformat() == c["trade_date"]
            assert s["snapshot_id"] == built.snapshot_id
            assert s["canonical_run_id"] == result.canonical_run_id

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
        assert len(verified.domain_rows["daily_bar"]) == 2

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
        with pytest.raises(SnapshotVerifierError, match="manifest bytes"):
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
        uri = str(manifest["artifacts"]["daily_bar"]["uri"])
        (env_root["normalized"] / uri).write_bytes(b"tampered-domain")
        with pytest.raises(SnapshotVerifierError, match="bytes tampered"):
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
        (env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])).unlink()
        with pytest.raises(SnapshotVerifierError, match="artifact missing"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )


    def test_verify_snapshot_business_tamper_with_rebound_seals(self, conn, env_root):
        """Business bytes plus every snapshot seal rebound still fail
        against the verified canonical projection."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        _rebind_snapshot_artifact(
            env_root, conn, built, "daily_bar", lambda row: row.__setitem__("close", 999.0)
        )
        with pytest.raises(SnapshotVerifierError, match="canonical projection"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )


    def test_verify_snapshot_lineage_tamper_with_rebound_seals(self, conn, env_root):
        """Lineage bytes plus every snapshot seal rebound still fail
        against the verified canonical projection."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        _rebind_snapshot_artifact(
            env_root,
            conn,
            built,
            "daily_bar",
            lambda row: row.__setitem__("source_raw_request_id", "forged-request"),
        )
        with pytest.raises(SnapshotVerifierError, match="canonical projection"):
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
            lambda doc: doc["artifacts"]["daily_bar"].__setitem__("schema_hash", "0" * 64),
        )
        with pytest.raises(SnapshotVerifierError, match="schema hash"):
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
        with pytest.raises(SnapshotVerifierError, match="snapshot_semantic_hash"):
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
        with pytest.raises(SnapshotVerifierError, match="deterministic anchor"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_builder_fingerprint_mismatch(self, conn, env_root, monkeypatch):
        """Mandatory 27: a snapshot built by a DIFFERENT builder code
        version cannot be verified by the current builder."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        import ashare_state.snapshot.verifier as verifier_module

        monkeypatch.setattr(verifier_module, "snapshot_builder_code_fingerprint", lambda: "f" * 64)
        with pytest.raises(SnapshotVerifierError, match="DIFFERENT snapshot builder"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_canonical_drift_fails(self, conn, env_root):
        """Mandatory 28: the canonical run is tampered AFTER the
        snapshot build -> the canonical provenance cross-bind fails
        closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        canonical_manifest = _canonical_manifest(env_root, result)
        uri = str(canonical_manifest["artifacts"]["selected"]["uri"])
        (env_root["normalized"] / uri).write_bytes(b"post-build-tamper")
        with pytest.raises(SnapshotVerifierError, match="DAMAGED"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verify_snapshot_canonical_input_disappearance(self, conn, env_root):
        """Mandatory 28 (ledger leg): the canonical run's consumed
        CR-2 input disappears after the snapshot build -> the
        provenance cross-bind (consumption verifier) fails closed."""
        result = _canonical_success(conn, env_root, domains=("daily_bar",))
        built = _build(conn, env_root, result.canonical_run_id)
        conn.execute(
            "DELETE FROM meta_provider_normalization_run WHERE raw_request_id = 'req-bars'"
        )
        with pytest.raises(SnapshotVerifierError, match="DAMAGED|no longer intact"):
            verify_snapshot(
                conn,
                built.snapshot_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

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
        with pytest.raises(SnapshotVerifierError, match="requested_domains"):
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
        uri = env_root["normalized"] / str(manifest["artifacts"]["daily_bar"]["uri"])
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
