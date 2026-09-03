"""CR-5 deterministic Feature Layer contract tests."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from test_snapshot import _canonical_success

from ashare_state.features import (
    FEATURE_SET_ID,
    FeatureBuilder,
    FeatureBuilderError,
    FeatureVerifierError,
    compute_feature_set,
    feature_artifact_schema,
    get_feature_set,
    semantic_hash,
    verify_feature_run_for_consumption,
)
from ashare_state.readmodel import DuckDBReadModel
from ashare_state.snapshot import SnapshotBuilder

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ashare_state" / "features"


def _build_feature(conn, env_root, *, domains=("daily_bar",)):
    canonical = _canonical_success(conn, env_root, domains=domains)
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
    return snapshot, FeatureBuilder(
        conn,
        raw_root=env_root["raw"],
        normalized_root=env_root["normalized"],
    ).build(snapshot.snapshot_id, FEATURE_SET_ID)


@pytest.mark.integration
class TestFeatureBoundary:
    def test_verified_readmodel_build_and_public_verify(self, conn, env_root):
        snapshot, built = _build_feature(conn, env_root)
        assert built.snapshot_id == snapshot.snapshot_id
        assert built.status == "SUCCESS"
        assert built.security_row_count == 2
        assert built.market_row_count == 1
        assert built.finding_count > 0

        verified = verify_feature_run_for_consumption(
            conn,
            built.feature_run_id,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        assert verified.feature_run_id == built.feature_run_id
        assert len(verified.security_rows) == 2
        assert len(verified.market_rows) == 1
        assert len(verified.finding_rows) == built.finding_count

    def test_exact_retry_is_idempotent(self, conn, env_root):
        snapshot, first = _build_feature(conn, env_root)
        second = FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        ).build(snapshot.snapshot_id, FEATURE_SET_ID)
        assert second.feature_run_id == first.feature_run_id
        assert second.idempotent_replay is True
        assert second.manifest_hash == first.manifest_hash

    def test_unknown_feature_set_fails_closed(self, conn, env_root):
        snapshot, _ = _build_feature(conn, env_root)
        before = int(
            conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0]
        )
        builder = FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        with pytest.raises(FeatureBuilderError, match="not registered"):
            builder.build(snapshot.snapshot_id, "caller-window-17")
        assert int(conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0]) == before

    def test_missing_readmodel_is_not_rebuilt(self, conn, env_root):
        canonical = _canonical_success(conn, env_root, domains=("daily_bar",))
        snapshot = SnapshotBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        ).build(canonical.canonical_run_id)
        builder = FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        with pytest.raises(FeatureBuilderError, match="ReadModel"):
            builder.build(snapshot.snapshot_id, FEATURE_SET_ID)
        assert not (env_root["normalized"] / "feature").exists()

    def test_missing_daily_bar_domain_fails_closed(self, conn, env_root):
        canonical = _canonical_success(conn, env_root, domains=("trade_calendar",))
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
        with pytest.raises(FeatureBuilderError, match="rm_daily_bar"):
            FeatureBuilder(
                conn,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            ).build(snapshot.snapshot_id, FEATURE_SET_ID)

    def test_verifier_rejects_tampered_feature_bytes(self, conn, env_root):
        _, built = _build_feature(conn, env_root)
        manifest_path = env_root["normalized"] / built.manifest_uri
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = env_root["normalized"] / manifest["artifacts"]["feature_findings"]["uri"]
        artifact_path.write_bytes(b"tampered feature bytes")
        with pytest.raises(FeatureVerifierError, match="content is tampered"):
            verify_feature_run_for_consumption(
                conn,
                built.feature_run_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_verifier_rejects_business_rebind_even_when_all_feature_seals_rebound(
        self, conn, env_root
    ):
        _, built = _build_feature(conn, env_root)
        manifest_path = env_root["normalized"] / built.manifest_uri
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = env_root["normalized"] / manifest["artifacts"][
            "security_daily_features"
        ]["uri"]
        rows = pl.read_parquet(artifact_path).to_dicts()
        rows[0]["raw_return_1"] = 123.0
        frame = pl.DataFrame(rows, schema=feature_artifact_schema("security_daily_features"))
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        data = buffer.getvalue()
        artifact_path.write_bytes(data)
        entry = manifest["artifacts"]["security_daily_features"]
        entry["content_hash"] = hashlib.sha256(data).hexdigest()
        entry["schema_hash"] = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
        entry["row_count"] = frame.height
        entry["semantic_hash"] = semantic_hash(frame.to_dicts())
        manifest["artifact_set_hash"] = hashlib.sha256(
            json.dumps(
                manifest["artifacts"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        manifest["feature_semantic_hash"] = semantic_hash(
            [
                *frame.to_dicts(),
                *pl.read_parquet(
                    env_root["normalized"]
                    / manifest["artifacts"]["market_daily_features"]["uri"]
                ).to_dicts(),
            ]
        )
        manifest_bytes = json.dumps(
            manifest, sort_keys=True, indent=1, ensure_ascii=False
        ).encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)
        conn.execute(
            "UPDATE meta_feature_build SET manifest_hash = ?, artifact_set_hash = ?, "
            "feature_semantic_hash = ? WHERE feature_run_id = ?",
            [
                hashlib.sha256(manifest_bytes).hexdigest(),
                manifest["artifact_set_hash"],
                manifest["feature_semantic_hash"],
                built.feature_run_id,
            ],
        )
        with pytest.raises(FeatureVerifierError, match="differs from Verified ReadModel replay"):
            verify_feature_run_for_consumption(
                conn,
                built.feature_run_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_feature_package_has_no_forbidden_imports(self):
        forbidden = (
            "ashare_state.providers",
            "ashare_state.normalization",
            "ashare_state.storage.raw_writer",
            "ashare_state.canonical.canonicalizer",
            "ashare_state.strategy",
            "ashare_state.backtest",
            "ashare_state.portfolio",
            "ashare_state.trading",
        )
        for path in SRC_ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                assert not any(
                    name == prefix or name.startswith(prefix + ".")
                    for name in names
                    for prefix in forbidden
                ), path

    def test_registry_is_static_and_versioned(self):
        registry = get_feature_set(FEATURE_SET_ID)
        assert registry.feature_registry_version == "feature-registry-v1"
        assert registry.registry_hash
        assert registry.price_basis == "UNADJUSTED_CANONICAL"
        assert registry.universe_rule_id == "OBSERVED_DAILY_BAR_UNIVERSE"
        assert "ma_close_obs_20" in registry.feature_names
        assert "pct_above_ma20_observed" in registry.feature_names
        with pytest.raises(ValueError):
            get_feature_set("adjusted-return")


def _source_row(index: int, *, snapshot_id: str = "snapshot-1") -> dict[str, Any]:
    trade_date = date(2026, 1, 1) + timedelta(days=index)
    close = 100.0 + index * 0.5
    return {
        "canonical_domain": "daily_bar",
        "canonical_key": json.dumps(
            ["SEC-1", trade_date.isoformat()],
            separators=(",", ":"),
        ),
        "security_id": "SEC-1",
        "trade_date": trade_date,
        "available_at": datetime(2026, 3, 10, tzinfo=UTC),
        "snapshot_id": snapshot_id,
        "canonical_run_id": "canonical-1",
        "source_row_identity_hash": f"{index:064x}",
        "open": close - 0.25,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "pre_close": close - 0.5,
        "amount": 1000.0 + index,
    }


def _fixture_rows(count: int = 65) -> list[dict[str, Any]]:
    return [_source_row(index) for index in range(count)]


@pytest.mark.unit
class TestFeatureFormulas:
    def test_ordered_formula_fixture(self):
        rows = _fixture_rows()
        feature_set = get_feature_set(FEATURE_SET_ID)
        computed = compute_feature_set(
            rows,
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=feature_set,
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        target = computed.security_rows[60]
        expected_ma5 = sum(row["close"] for row in rows[56:61]) / 5
        expected_lag5 = rows[60]["close"] / rows[55]["close"] - 1.0
        expected_amount = rows[60]["amount"] / (
            sum(row["amount"] for row in rows[41:61]) / 20
        )
        raw_returns = [
            row["close"] / row["pre_close"] - 1.0 for row in rows[41:61]
        ]
        expected_vol = math.sqrt(
            sum(
                (value - (sum(raw_returns) / 20)) ** 2
                for value in raw_returns
            )
            / 20
        )
        assert target["ma_close_obs_5"] == pytest.approx(expected_ma5)
        assert target["return_lag_obs_5"] == pytest.approx(expected_lag5)
        assert target["amount_to_mean_obs_20"] == pytest.approx(expected_amount)
        assert target["vol_raw_return_obs_20"] == pytest.approx(expected_vol)
        assert target["feature_available_at"] == datetime(2026, 3, 10, tzinfo=UTC)
        market = computed.market_rows[60]
        assert market["observed_security_count"] == 1
        assert market["valid_raw_return_count"] == 1
        assert market["advancer_count"] == 1
        assert market["advancer_ratio_observed"] == 1.0

    def test_missing_denominator_is_null_with_finding(self):
        row = _source_row(0)
        row["pre_close"] = 0.0
        computed = compute_feature_set(
            [row],
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        assert computed.security_rows[0]["raw_return_1"] is None
        assert any(
            finding["feature_name"] == "raw_return_1"
            and finding["finding_class"] == "UNSAFE_DENOMINATOR"
            for finding in computed.finding_rows
        )
        assert all(
            value is None or math.isfinite(float(value))
            for row in computed.security_rows
            for value in row.values()
            if isinstance(value, float)
        )

    def test_observation_gap_is_not_filled(self):
        first = _source_row(0)
        second = _source_row(10)
        computed = compute_feature_set(
            [first, second],
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        assert computed.security_rows[1]["ma_close_obs_5"] is None
        assert any(
            finding["feature_name"] == "ma_close_obs_5"
            and finding["finding_class"] == "INSUFFICIENT_HISTORY"
            for finding in computed.finding_rows
        )

    def test_future_observation_does_not_change_target(self):
        rows = _fixture_rows()
        baseline = compute_feature_set(
            rows,
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        changed = [dict(row) for row in rows]
        changed[-1]["close"] = 999999.0
        future = compute_feature_set(
            changed,
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        assert baseline.security_rows[60] == future.security_rows[60]

    def test_input_order_does_not_change_truth(self):
        rows = _fixture_rows()
        forward = compute_feature_set(
            rows,
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        reverse = compute_feature_set(
            list(reversed(rows)),
            snapshot_id="snapshot-1",
            canonical_run_id="canonical-1",
            feature_run_id="feature-1",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 3, 10, tzinfo=UTC),
        )
        assert semantic_hash(forward.security_rows) == semantic_hash(reverse.security_rows)
        assert semantic_hash(forward.market_rows) == semantic_hash(reverse.market_rows)
