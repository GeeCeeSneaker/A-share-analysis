"""CR-5 deterministic Feature Layer contract tests."""

from __future__ import annotations

import ast
import hashlib
import inspect
import io
import json
import math
from dataclasses import replace
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
    compile_feature_execution_plan,
    compute_feature_set,
    feature_artifact_schema,
    feature_base_hash_from_primitives,
    feature_id_from_base_hash,
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

        manifest = json.loads(
            (env_root["normalized"] / built.manifest_uri).read_text(encoding="utf-8")
        )
        market_frame = pl.read_parquet(
            env_root["normalized"] / manifest["artifacts"]["market_daily_features"]["uri"]
        )
        assert market_frame.schema["advancer_ratio_observed"] == pl.Float64
        assert market_frame.schema["valid_ma20_count"] == pl.Int64
        assert market_frame.schema["valid_mom20_count"] == pl.Int64

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
        before = int(conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0])
        builder = FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        with pytest.raises(FeatureBuilderError, match="not registered"):
            builder.build(snapshot.snapshot_id, "caller-window-17")
        assert int(conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0]) == before

    def test_unknown_snapshot_fails_closed(self, conn, env_root):
        builder = FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        with pytest.raises(FeatureBuilderError, match="ReadModel"):
            builder.build("missing-snapshot", FEATURE_SET_ID)
        assert not (env_root["normalized"] / "feature").exists()

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
        artifact_path = (
            env_root["normalized"] / manifest["artifacts"]["security_daily_features"]["uri"]
        )
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
                    env_root["normalized"] / manifest["artifacts"]["market_daily_features"]["uri"]
                ).to_dicts(),
            ]
        )
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False).encode(
            "utf-8"
        )
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


def _build_readmodel(conn, env_root, *, domains=("daily_bar",)):
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
    return snapshot


def _mutate_feature_spec(feature_set, feature_name: str, **changes):
    return replace(
        feature_set,
        features=tuple(
            replace(spec, **changes) if spec.feature_name == feature_name else spec
            for spec in feature_set.features
        ),
    )


def _rebind_manifest(
    conn,
    env_root,
    built,
    mutate,
    *,
    ledger_updates: dict[str, Any] | None = None,
):
    manifest_path = env_root["normalized"] / built.manifest_uri
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest_bytes = json.dumps(
        manifest,
        sort_keys=True,
        indent=1,
        ensure_ascii=False,
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    assignments = ["manifest_hash = ?"]
    values: list[Any] = [hashlib.sha256(manifest_bytes).hexdigest()]
    for field, value in (ledger_updates or {}).items():
        assignments.append(f"{field} = ?")
        values.append(value)
    values.append(built.feature_run_id)
    conn.execute(
        f"UPDATE meta_feature_build SET {', '.join(assignments)} "
        "WHERE feature_run_id = ?",
        values,
    )


def _compute_rows(rows, feature_set=None):
    return compute_feature_set(
        rows,
        snapshot_id="snapshot-1",
        canonical_run_id="canonical-1",
        feature_run_id="feature-1",
        feature_set=feature_set or get_feature_set(FEATURE_SET_ID),
        snapshot_as_of=datetime(2026, 3, 12, tzinfo=UTC),
    )


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
        expected_amount = rows[60]["amount"] / (sum(row["amount"] for row in rows[41:61]) / 20)
        raw_returns = [row["close"] / row["pre_close"] - 1.0 for row in rows[41:61]]
        expected_vol = math.sqrt(
            sum((value - (sum(raw_returns) / 20)) ** 2 for value in raw_returns) / 20
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
        assert computed.market_rows[0]["advancer_ratio_observed"] is None
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
        assert semantic_hash(forward.finding_rows) == semantic_hash(reverse.finding_rows)


@pytest.mark.unit
class TestFeatureRegistryHonestExecution:
    @pytest.mark.parametrize(
        ("feature_name", "field", "value"),
        [
            ("ma_close_obs_20", "window_length", 17),
            ("return_lag_obs_20", "lag", 17),
            ("raw_return_1", "formula_rule_id", "UNIMPLEMENTED_RULE"),
            ("raw_return_1", "denominator_policy", "UNIMPLEMENTED_POLICY"),
            ("raw_return_1", "missingness_policy", "UNIMPLEMENTED_POLICY"),
            ("raw_return_1", "availability_rule", "UNIMPLEMENTED_RULE"),
            ("ma_close_obs_20", "window_basis", "MARKET_SESSIONS"),
        ],
    )
    def test_registry_semantic_drift_fails_closed(
        self, feature_name, field, value
    ):
        feature_set = _mutate_feature_spec(
            get_feature_set(FEATURE_SET_ID),
            feature_name,
            **{field: value},
        )
        with pytest.raises(FeatureEngineError, match="honestly executed"):
            _compute_rows(_fixture_rows(), feature_set)

    def test_registry_extra_feature_is_not_executable(self):
        registry = get_feature_set(FEATURE_SET_ID)
        extra = replace(registry.features[-1], feature_name="future_feature")
        mutated = replace(registry, features=(*registry.features, extra))
        with pytest.raises(FeatureEngineError, match="honestly executed"):
            _compute_rows(_fixture_rows(), mutated)

    def test_supported_feature_without_execution_handler_fails_closed(self):
        feature_set = _mutate_feature_spec(
            get_feature_set(FEATURE_SET_ID),
            "raw_return_1",
            eligibility="BLOCKED_PENDING_SEMANTICS",
        )
        with pytest.raises(FeatureEngineError, match="honestly executed"):
            _compute_rows(_fixture_rows(), feature_set)

    def test_blocked_semantics_are_typed_and_cannot_be_renamed_into_supported(self):
        registry = get_feature_set(FEATURE_SET_ID)
        renamed = _mutate_feature_spec(
            registry,
            "raw_return_1",
            feature_name="adjusted_return",
        )
        with pytest.raises(FeatureEngineError, match="exact V1 execution set"):
            _compute_rows(_fixture_rows(), renamed)

        untyped = replace(registry, blocked_semantics=("adjusted return",))
        with pytest.raises(ValueError, match="typed classifications"):
            compile_feature_execution_plan(untyped)

    def test_registry_window_drift_writes_no_artifact_or_ledger(
        self, conn, env_root, monkeypatch
    ):
        snapshot = _build_readmodel(conn, env_root)
        mutated = _mutate_feature_spec(
            get_feature_set(FEATURE_SET_ID),
            "ma_close_obs_20",
            window_length=17,
        )
        from ashare_state.features import builder as builder_module

        monkeypatch.setattr(builder_module, "get_feature_set", lambda _id: mutated)
        builder = FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )
        with pytest.raises(FeatureBuilderError, match="honestly executed"):
            builder.build(snapshot.snapshot_id, FEATURE_SET_ID)
        assert not (env_root["normalized"] / "feature").exists()
        assert conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0] == 0


@pytest.mark.integration
class TestFeatureSealCrossBinding:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("price_basis", "ADJUSTED"),
            ("window_basis", "MARKET_SESSIONS"),
            ("universe_rule_id", "ALL_A_SHARES"),
        ],
    )
    def test_manifest_semantic_field_rebind_refused(self, conn, env_root, field, value):
        _, built = _build_feature(conn, env_root)
        _rebind_manifest(
            conn,
            env_root,
            built,
            lambda manifest: manifest.update({field: value}),
        )
        with pytest.raises(FeatureVerifierError, match="manifest field"):
            verify_feature_run_for_consumption(
                conn,
                built.feature_run_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    @pytest.mark.parametrize(
        "field",
        ["security_row_count", "market_row_count", "finding_count"],
    )


    def test_verifier_rejects_lineage_rebind_even_when_all_seals_rebound(
        self, conn, env_root
    ):
        _, built = _build_feature(conn, env_root)
        manifest_path = env_root["normalized"] / built.manifest_uri
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_path = (
            env_root["normalized"]
            / manifest["artifacts"]["security_daily_features"]["uri"]
        )
        rows = pl.read_parquet(artifact_path).to_dicts()
        rows[0]["input_lineage_hash"] = "0" * 64
        frame = pl.DataFrame(
            rows,
            schema=feature_artifact_schema("security_daily_features"),
        )
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
            manifest,
            sort_keys=True,
            indent=1,
            ensure_ascii=False,
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

    def test_manifest_and_ledger_counts_are_physically_recomputed(
        self, conn, env_root, field
    ):
        _, built = _build_feature(conn, env_root)
        _rebind_manifest(
            conn,
            env_root,
            built,
            lambda manifest: manifest.update({field: 999999}),
            ledger_updates={field: 999999},
        )
        with pytest.raises(FeatureVerifierError, match="physical artifact rows"):
            verify_feature_run_for_consumption(
                conn,
                built.feature_run_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_snapshot_as_of_is_cross_bound_to_verified_snapshot(self, conn, env_root):
        _, built = _build_feature(conn, env_root)
        forged_as_of = "2026-03-11T00:00:00+00:00"
        _rebind_manifest(
            conn,
            env_root,
            built,
            lambda manifest: manifest.update({"snapshot_as_of": forged_as_of}),
            ledger_updates={
                "snapshot_as_of": datetime(2026, 3, 11, tzinfo=UTC),
            },
        )
        with pytest.raises(FeatureVerifierError):
            verify_feature_run_for_consumption(
                conn,
                built.feature_run_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )

    def test_success_ledger_error_message_is_not_consumable(self, conn, env_root):
        _, built = _build_feature(conn, env_root)
        conn.execute(
            "UPDATE meta_feature_build SET error_message = ? WHERE feature_run_id = ?",
            ["forged error", built.feature_run_id],
        )
        with pytest.raises(FeatureVerifierError, match="error_message"):
            verify_feature_run_for_consumption(
                conn,
                built.feature_run_id,
                raw_root=env_root["raw"],
                normalized_root=env_root["normalized"],
            )


@pytest.mark.unit
class TestFeatureFormulaAndMissingnessClosure:
    def test_all_same_row_formulas_have_exact_fixture_values(self):
        rows = _fixture_rows(2)
        computed = _compute_rows(rows)
        row = computed.security_rows[1]
        source = rows[1]
        assert row["raw_return_1"] == pytest.approx(source["close"] / source["pre_close"] - 1)
        assert row["gap_open_raw"] == pytest.approx(source["open"] / source["pre_close"] - 1)
        assert row["intraday_return_raw"] == pytest.approx(source["close"] / source["open"] - 1)
        assert row["amplitude_preclose_raw"] == pytest.approx(
            (source["high"] - source["low"]) / source["pre_close"]
        )

    def test_all_observed_windows_and_lags_use_declared_boundaries(self):
        rows = _fixture_rows(65)
        computed = _compute_rows(rows)
        target = computed.security_rows[60]
        for length in (5, 20, 60):
            expected_mean = sum(row["close"] for row in rows[61 - length : 61]) / length
            assert target[f"ma_close_obs_{length}"] == pytest.approx(expected_mean)
            expected_lag = rows[60]["close"] / rows[60 - length]["close"] - 1
            assert target[f"return_lag_obs_{length}"] == pytest.approx(expected_lag)

    @pytest.mark.parametrize("prior_close", [0.0, -1.0])
    def test_lag_non_positive_prior_close_is_unsafe_denominator(self, prior_close):
        rows = _fixture_rows(21)
        rows[0]["close"] = prior_close
        computed = _compute_rows(rows)
        target_date = rows[20]["trade_date"]
        assert computed.security_rows[20]["return_lag_obs_20"] is None
        assert any(
            finding["trade_date"] == target_date
            and finding["feature_name"] == "return_lag_obs_20"
            and finding["finding_class"] == "UNSAFE_DENOMINATOR"
            for finding in computed.finding_rows
        )

    @pytest.mark.parametrize("close_value", [0.0, -1.0])
    def test_close_to_ma_non_positive_mean_is_unsafe_denominator(self, close_value):
        rows = _fixture_rows(20)
        for row in rows:
            row["close"] = close_value
            row["pre_close"] = 1.0
            row["open"] = 1.0
        computed = _compute_rows(rows)
        assert computed.security_rows[-1]["close_to_ma_obs_20"] is None
        assert any(
            finding["feature_name"] == "close_to_ma_obs_20"
            and finding["finding_class"] == "UNSAFE_DENOMINATOR"
            for finding in computed.finding_rows
        )

    def test_market_breadth_ignores_uncomparable_ma_values_without_crashing(self):
        first = _fixture_rows(21)
        second = [_source_row(i) for i in range(21)]
        for row in second:
            row["security_id"] = "SEC-2"
            row["canonical_key"] = json.dumps(
                ["SEC-2", row["trade_date"].isoformat()],
                separators=(",", ":"),
            )
            row["source_row_identity_hash"] = (
                f"{1000 + int(row['source_row_identity_hash'], 16):064x}"
            )
        for row in first:
            row["close"] = -1.0
            row["pre_close"] = 1.0
            row["open"] = 1.0
        computed = _compute_rows([*first, *second])
        market = computed.market_rows[-1]
        assert market["observed_security_count"] == 2
        assert market["valid_ma20_count"] == 1
        assert market["pct_above_ma20_observed"] == pytest.approx(1.0)

    def test_nonfinite_input_becomes_null_and_never_enters_artifact(self):
        row = _source_row(0)
        row["close"] = math.inf
        computed = _compute_rows([row])
        assert all(
            value is None or not isinstance(value, float) or math.isfinite(value)
            for output in (*computed.security_rows, *computed.market_rows)
            for value in output.values()
        )
        assert any(
            finding["feature_name"] == "raw_return_1"
            and finding["finding_class"] == "NON_FINITE_RESULT"
            for finding in computed.finding_rows
        )

    def test_active_amount_missingness_ignores_old_history_gap(self):
        rows = _fixture_rows(121)
        rows[0]["amount"] = None
        computed = _compute_rows(rows)
        target_date = rows[-1]["trade_date"]
        active = [
            finding
            for finding in computed.finding_rows
            if finding["trade_date"] == target_date
            and finding["feature_name"] == "amount_to_mean_obs_20"
            and finding["finding_class"] == "OPTIONAL_INPUT_MISSING"
        ]
        assert active == []

    def test_active_amount_missingness_counts_only_active_span(self):
        rows = _fixture_rows(41)
        rows[25]["amount"] = None
        computed = _compute_rows(rows)
        target = [
            finding
            for finding in computed.finding_rows
            if finding["trade_date"] == rows[-1]["trade_date"]
            and finding["feature_name"] == "amount_to_mean_obs_20"
            and finding["finding_class"] == "OPTIONAL_INPUT_MISSING"
        ]
        assert len(target) == 1
        detail = json.loads(target[0]["detail_json"])
        assert detail["skipped_invalid_or_null_amount_rows"] == 1
        assert detail["active_input_row_count"] == 21

    def test_active_volatility_missingness_counts_only_active_span(self):
        rows = _fixture_rows(41)
        rows[25]["pre_close"] = 0.0
        computed = _compute_rows(rows)
        target = [
            finding
            for finding in computed.finding_rows
            if finding["trade_date"] == rows[-1]["trade_date"]
            and finding["feature_name"] == "vol_raw_return_obs_20"
            and finding["finding_class"] == "OPTIONAL_INPUT_MISSING"
        ]
        assert len(target) == 1
        detail = json.loads(target[0]["detail_json"])
        assert detail["skipped_invalid_raw_return_rows"] == 1
        assert detail["active_input_row_count"] == 21

    def test_incremental_windows_do_not_rescan_history_prefix(self):
        engine_source = (SRC_ROOT / "engine.py").read_text(encoding="utf-8")
        assert "security_rows[: index + 1]" not in engine_source
        verifier_source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ashare_state"
            / "features"
            / "verifier.py"
        ).read_text(encoding="utf-8")
        assert "security_keys: set" in verifier_source


@pytest.mark.unit
class TestFeaturePITAndMarketDeterminism:
    def test_active_span_available_at_is_pit_max(self):
        rows = _fixture_rows(41)
        rows[20]["amount"] = None
        rows[20]["available_at"] = datetime(2026, 3, 9, tzinfo=UTC)
        rows[25]["available_at"] = datetime(2026, 3, 11, tzinfo=UTC)
        computed = _compute_rows(rows)
        target = computed.security_rows[-1]
        assert target["feature_available_at"] == datetime(2026, 3, 11, tzinfo=UTC)

    def test_security_lineage_changes_when_source_identity_changes(self):
        rows = _fixture_rows(2)
        first = _compute_rows(rows)
        changed = [dict(row) for row in rows]
        changed[0]["source_row_identity_hash"] = "f" * 64
        second = _compute_rows(changed)
        assert first.security_rows[0]["input_lineage_hash"] != second.security_rows[0][
            "input_lineage_hash"
        ]

    def test_market_mean_median_are_order_deterministic(self):
        first = _fixture_rows(21)
        second = [_source_row(i) for i in range(21)]
        for row in second:
            row["security_id"] = "SEC-2"
            row["canonical_key"] = json.dumps(
                ["SEC-2", row["trade_date"].isoformat()],
                separators=(",", ":"),
            )
            row["source_row_identity_hash"] = (
                f"{1000 + int(row['source_row_identity_hash'], 16):064x}"
            )
            row["close"] += 10.0
        forward = _compute_rows([*first, *second])
        reverse = _compute_rows([*second, *first])
        assert forward.market_rows[-1]["mean_raw_return_observed"] == reverse.market_rows[-1][
            "mean_raw_return_observed"
        ]
        assert forward.market_rows[-1]["median_raw_return_observed"] == reverse.market_rows[-1][
            "median_raw_return_observed"
        ]


@pytest.mark.integration
class TestFeatureRecoverablePublication:
    def _builder(self, conn, env_root):
        return FeatureBuilder(
            conn,
            raw_root=env_root["raw"],
            normalized_root=env_root["normalized"],
        )

    def test_ledger_failure_exact_retry_recovers(self, conn, env_root, monkeypatch):
        snapshot = _build_readmodel(conn, env_root)
        builder = self._builder(conn, env_root)
        monkeypatch.setattr(
            builder,
            "_commit_ledger",
            lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected ledger commit failure")
            ),
        )
        with pytest.raises(RuntimeError, match="ledger commit failure"):
            builder.build(snapshot.snapshot_id, FEATURE_SET_ID)
        manifests = list((env_root["normalized"] / "feature").rglob("manifest.json"))
        assert len(manifests) == 1
        assert conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0] == 0

        retry = self._builder(conn, env_root).build(snapshot.snapshot_id, FEATURE_SET_ID)
        assert retry.status == "SUCCESS"
        assert retry.idempotent_replay is False

    def test_partial_identical_residue_recovers(self, conn, env_root, monkeypatch):
        snapshot = _build_readmodel(conn, env_root)
        builder = self._builder(conn, env_root)
        monkeypatch.setattr(
            builder,
            "_commit_ledger",
            lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected ledger commit failure")
            ),
        )
        with pytest.raises(RuntimeError):
            builder.build(snapshot.snapshot_id, FEATURE_SET_ID)
        manifest_path = next((env_root["normalized"] / "feature").rglob("manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing_path = (
            env_root["normalized"]
            / manifest["artifacts"]["feature_findings"]["uri"]
        )
        missing_path.unlink()
        retry = self._builder(conn, env_root).build(snapshot.snapshot_id, FEATURE_SET_ID)
        assert retry.status == "SUCCESS"
        assert missing_path.is_file()

    def test_conflicting_residue_refuses(self, conn, env_root, monkeypatch):
        snapshot = _build_readmodel(conn, env_root)
        builder = self._builder(conn, env_root)
        monkeypatch.setattr(
            builder,
            "_commit_ledger",
            lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected ledger commit failure")
            ),
        )
        with pytest.raises(RuntimeError):
            builder.build(snapshot.snapshot_id, FEATURE_SET_ID)
        manifest_path = next((env_root["normalized"] / "feature").rglob("manifest.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        conflict_path = (
            env_root["normalized"]
            / manifest["artifacts"]["security_daily_features"]["uri"]
        )
        conflict_path.write_bytes(b"conflicting feature bytes")
        with pytest.raises(FeatureBuilderError, match="conflict|different bytes"):
            self._builder(conn, env_root).build(snapshot.snapshot_id, FEATURE_SET_ID)
        assert conn.execute("SELECT COUNT(*) FROM meta_feature_build").fetchone()[0] == 0

    def test_feature_artifact_bytes_are_deterministic(self, conn, env_root):
        snapshot, first = _build_feature(conn, env_root)
        manifest_path = env_root["normalized"] / first.manifest_uri
        first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        first_artifacts = first_manifest["artifacts"]
        conn.execute(
            "DELETE FROM meta_feature_build WHERE feature_run_id = ?",
            [first.feature_run_id],
        )
        retry = self._builder(conn, env_root).build(snapshot.snapshot_id, FEATURE_SET_ID)
        second_manifest = json.loads(
            (env_root["normalized"] / retry.manifest_uri).read_text(encoding="utf-8")
        )
        assert retry.feature_run_id == first.feature_run_id
        assert retry.manifest_hash == first.manifest_hash
        assert second_manifest["artifacts"] == first_artifacts


@pytest.mark.unit
class TestFeatureIdentityAndBoundary:
    def test_registry_and_builder_fingerprints_enter_feature_identity(self):
        values = {
            "snapshot_id": "snapshot-1",
            "snapshot_manifest_hash": "a" * 64,
            "snapshot_semantic_hash": "b" * 64,
            "snapshot_as_of": "2026-03-10T00:00:00+00:00",
            "readmodel_contract_version": "readmodel-v1",
            "readmodel_builder_code_fingerprint": "c" * 64,
            "feature_set_id": FEATURE_SET_ID,
            "feature_set_version": "1",
            "feature_registry_version": "feature-registry-v1",
            "feature_registry_hash": "d" * 64,
            "feature_contract_version": "feature-v1",
            "feature_builder_code_fingerprint": "e" * 64,
        }
        first = feature_id_from_base_hash(
            feature_base_hash_from_primitives(**values)
        )
        changed = dict(values, feature_registry_hash="f" * 64)
        second = feature_id_from_base_hash(
            feature_base_hash_from_primitives(**changed)
        )
        assert first != second

    def test_feature_builder_requires_explicit_world_arguments(self):
        parameters = list(inspect.signature(FeatureBuilder.build).parameters)
        assert parameters == ["self", "snapshot_id", "feature_set_id"]
