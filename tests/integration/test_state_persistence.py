"""CR-6.2 State identity, immutable publication, and replay tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from ashare_state.features.models import (
    FeatureVerifierError,
    VerifiedFeatureRun,
)
from ashare_state.state import (
    STATE_SET_ID,
    StateBuilder,
    StateBuilderError,
    StateVerifierError,
    state_manifest_uri,
    verify_state_run_for_consumption,
)

pytestmark = pytest.mark.integration

_AVAILABLE_AT = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)


def _feature_row(trade_date: date = date(2026, 3, 12)) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "source_snapshot_id": "snapshot-1",
        "feature_set_id": "market-state-base-v1",
        "feature_available_at": _AVAILABLE_AT,
        "input_lineage_hash": "a" * 64,
        "universe_rule_id": "OBSERVED_DAILY_BAR_UNIVERSE",
        "observed_security_count": 10,
        "valid_raw_return_count": 10,
        "advancer_count": 6,
        "decliner_count": 3,
        "unchanged_count": 1,
        "advancer_ratio_observed": 0.6,
        "mean_raw_return_observed": 0.01,
        "median_raw_return_observed": 0.005,
        "valid_ma20_count": 10,
        "pct_above_ma20_observed": 0.7,
        "valid_mom20_count": 10,
        "pct_positive_mom20_observed": 0.8,
    }


def _feature_run() -> VerifiedFeatureRun:
    feature_manifest_uri = (
        "feature/contract=feature-v1/snapshot=snapshot-1/"
        "run=feature-run-1/manifest.json"
    )
    record = {
        "feature_run_id": "feature-run-1",
        "manifest_uri": feature_manifest_uri,
        "manifest_hash": "f" * 64,
        "feature_semantic_hash": "e" * 64,
        "feature_registry_hash": "d" * 64,
    }
    return VerifiedFeatureRun(
        feature_run_id="feature-run-1",
        snapshot_id="snapshot-1",
        canonical_run_id="canonical-run-1",
        feature_set_id="market-state-base-v1",
        manifest={"feature_registry_hash": "d" * 64},
        ledger_record=record,
        security_rows=(),
        market_rows=(_feature_row(),),
        finding_rows=(),
    )


def _create_ledger(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE meta_state_build (
            state_run_id VARCHAR PRIMARY KEY,
            feature_run_id VARCHAR NOT NULL,
            feature_manifest_uri VARCHAR NOT NULL,
            feature_manifest_hash VARCHAR NOT NULL,
            feature_semantic_hash VARCHAR NOT NULL,
            feature_set_id VARCHAR NOT NULL,
            feature_registry_hash VARCHAR NOT NULL,
            state_set_id VARCHAR NOT NULL,
            state_set_version VARCHAR NOT NULL,
            state_registry_version VARCHAR NOT NULL,
            state_registry_hash VARCHAR NOT NULL,
            state_contract_version VARCHAR NOT NULL,
            state_builder_code_fingerprint VARCHAR NOT NULL,
            manifest_uri VARCHAR NOT NULL,
            manifest_hash VARCHAR NOT NULL,
            artifact_set_hash VARCHAR NOT NULL,
            state_semantic_hash VARCHAR NOT NULL,
            finding_set_hash VARCHAR NOT NULL,
            state_row_count INTEGER NOT NULL,
            finding_count INTEGER NOT NULL,
            status VARCHAR NOT NULL,
            error_message VARCHAR,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def _patch_feature_verifier(monkeypatch: pytest.MonkeyPatch, feature_run: VerifiedFeatureRun) -> None:
    monkeypatch.setattr(
        "ashare_state.state.builder.verify_feature_run_for_consumption",
        lambda *args, **kwargs: feature_run,
    )
    monkeypatch.setattr(
        "ashare_state.state.verifier.verify_feature_run_for_consumption",
        lambda *args, **kwargs: feature_run,
    )


def test_builder_publishes_and_public_verifier_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        builder = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root)
        result = builder.build("feature-run-1", STATE_SET_ID)
        assert result.status == "SUCCESS"
        assert result.state_row_count == 1
        assert (root / result.manifest_uri).is_file()

        verified = verify_state_run_for_consumption(
            conn,
            result.state_run_id,
            raw_root=tmp_path / "raw",
            normalized_root=root,
        )
        assert verified.state_run_id == result.state_run_id
        assert len(verified.state_rows) == 1

        replay = builder.build("feature-run-1", STATE_SET_ID)
        assert replay.idempotent_replay is True
        assert replay.manifest_hash == result.manifest_hash
    finally:
        conn.close()


def test_tampered_state_artifact_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        builder = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root)
        result = builder.build("feature-run-1", STATE_SET_ID)
        artifact_uri = (
            state_manifest_uri("feature-run-1", result.state_run_id)
            .rsplit("/", 1)[0]
            + "/market_daily_state.parquet"
        )
        (root / artifact_uri).write_bytes(b"tampered")
        with pytest.raises(StateVerifierError, match="content"):
            verify_state_run_for_consumption(
                conn,
                result.state_run_id,
                raw_root=tmp_path / "raw",
                normalized_root=root,
            )
    finally:
        conn.close()


def test_feature_verification_failure_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> VerifiedFeatureRun:
        raise FeatureVerifierError("blocked")

    monkeypatch.setattr(
        "ashare_state.state.builder.verify_feature_run_for_consumption",
        fail,
    )
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        builder = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root)
        with pytest.raises(StateBuilderError, match="not consumable"):
            builder.build("missing-feature", STATE_SET_ID)
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0
        assert not root.exists()
    finally:
        conn.close()
