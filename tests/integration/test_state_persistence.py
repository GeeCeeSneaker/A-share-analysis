"""CR-6.2 State identity, immutable publication, and replay tests."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from ashare_state.features.models import (
    FeatureVerifierError,
    VerifiedFeatureRun,
    canonical_json,
    semantic_hash,
)
from ashare_state.state import (
    STATE_INPUT_INVARIANT_VIOLATION,
    STATE_RULE_UNAVAILABLE,
    STATE_SET_ID,
    StateBuilder,
    StateBuilderError,
    StateEngineError,
    StateFatalError,
    StateVerifierError,
    state_artifact_schema,
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


def _feature_run(
    feature_run_id: str = "feature-run-1",
    *,
    rows: tuple[dict[str, Any], ...] | None = None,
) -> VerifiedFeatureRun:
    feature_manifest_uri = (
        f"feature/contract=feature-v1/snapshot=snapshot-1/run={feature_run_id}/manifest.json"
    )
    record = {
        "feature_run_id": feature_run_id,
        "manifest_uri": feature_manifest_uri,
        "manifest_hash": "f" * 64,
        "feature_semantic_hash": "e" * 64,
        "feature_registry_hash": "d" * 64,
    }
    return VerifiedFeatureRun(
        feature_run_id=feature_run_id,
        snapshot_id="snapshot-1",
        canonical_run_id="canonical-run-1",
        feature_set_id="market-state-base-v1",
        manifest={"feature_registry_hash": "d" * 64},
        ledger_record=record,
        security_rows=(),
        market_rows=rows if rows is not None else (_feature_row(),),
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


def _patch_feature_verifier(
    monkeypatch: pytest.MonkeyPatch, feature_run: VerifiedFeatureRun
) -> None:
    monkeypatch.setattr(
        "ashare_state.state.builder.verify_feature_run_for_consumption",
        lambda *args, **kwargs: feature_run,
    )
    monkeypatch.setattr(
        "ashare_state.state.verifier.verify_feature_run_for_consumption",
        lambda *args, **kwargs: feature_run,
    )


def _state_artifact_path(root: Path, result: Any, name: str) -> Path:
    manifest = json.loads((root / result.manifest_uri).read_text(encoding="utf-8"))
    return root / manifest["artifacts"][name]["uri"]


def _rebind_state_artifact(
    conn: Any,
    root: Path,
    result: Any,
    name: str,
    frame: pl.DataFrame,
) -> None:
    manifest_path = root / result.manifest_uri
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_path = root / manifest["artifacts"][name]["uri"]
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    data = buffer.getvalue()
    artifact_path.write_bytes(data)
    entry = manifest["artifacts"][name]
    entry.update(
        {
            "content_hash": hashlib.sha256(data).hexdigest(),
            "schema_hash": hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest(),
            "row_count": frame.height,
            "semantic_hash": semantic_hash(frame.to_dicts()),
        }
    )
    if name == "market_daily_state":
        manifest["state_semantic_hash"] = semantic_hash(frame.to_dicts())
    else:
        manifest["finding_set_hash"] = semantic_hash(frame.to_dicts())
    manifest["state_row_count"] = int(manifest["artifacts"]["market_daily_state"]["row_count"])
    manifest["finding_count"] = int(manifest["artifacts"]["state_findings"]["row_count"])
    manifest["artifact_set_hash"] = hashlib.sha256(
        canonical_json(manifest["artifacts"]).encode("utf-8")
    ).hexdigest()
    manifest_bytes = json.dumps(
        manifest,
        sort_keys=True,
        indent=1,
        ensure_ascii=False,
    ).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    conn.execute(
        "UPDATE meta_state_build SET manifest_hash = ?, artifact_set_hash = ?, "
        "state_semantic_hash = ?, finding_set_hash = ?, state_row_count = ?, "
        "finding_count = ? WHERE state_run_id = ?",
        [
            hashlib.sha256(manifest_bytes).hexdigest(),
            manifest["artifact_set_hash"],
            manifest["state_semantic_hash"],
            manifest["finding_set_hash"],
            manifest["state_row_count"],
            manifest["finding_count"],
            result.state_run_id,
        ],
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
            state_manifest_uri("feature-run-1", result.state_run_id).rsplit("/", 1)[0]
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


@pytest.mark.parametrize(
    "failure_detail",
    (
        "unknown feature_run_id",
        "non-SUCCESS Feature",
        "damaged Feature manifest",
        "damaged Feature artifact",
        "damaged Feature finding",
        "foreign ReadModel",
    ),
)
def test_feature_verifier_failure_matrix_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_detail: str,
) -> None:
    def fail(*args: object, **kwargs: object) -> VerifiedFeatureRun:
        raise FeatureVerifierError(failure_detail)

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
            builder.build("feature-run-1", STATE_SET_ID)
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0
        assert not root.exists()
    finally:
        conn.close()


def test_two_feature_runs_have_distinct_state_identity_and_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = {
        "feature-run-1": _feature_run("feature-run-1"),
        "feature-run-2": _feature_run("feature-run-2"),
    }
    monkeypatch.setattr(
        "ashare_state.state.builder.verify_feature_run_for_consumption",
        lambda _conn, feature_run_id, **_kwargs: runs[feature_run_id],
    )
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        builder = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root)
        first = builder.build("feature-run-1", STATE_SET_ID)
        second = builder.build("feature-run-2", STATE_SET_ID)
        assert first.state_run_id != second.state_run_id
        assert first.manifest_uri != second.manifest_uri
        assert (root / first.manifest_uri).is_file()
        assert (root / second.manifest_uri).is_file()
    finally:
        conn.close()


def test_state_invariant_failure_is_typed_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _feature_row()
    row["unchanged_count"] = 2
    feature_run = _feature_run(rows=(row,))
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        builder = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root)
        with pytest.raises(StateEngineError) as exc_info:
            builder.build("feature-run-1", STATE_SET_ID)
        assert exc_info.value.error_code == STATE_INPUT_INVARIANT_VIOLATION
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0
        assert not root.exists()
    finally:
        conn.close()


def test_registry_unavailable_is_typed_before_publication(tmp_path: Path) -> None:
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        builder = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root)
        with pytest.raises(StateFatalError) as exc_info:
            builder.build("feature-run-1", "unregistered-state-set")
        assert exc_info.value.error_code == STATE_RULE_UNAVAILABLE
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0
        assert not root.exists()
    finally:
        conn.close()


def test_artifact_bytes_are_deterministic_on_exact_retry(
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
        first = builder.build("feature-run-1", STATE_SET_ID)
        manifest_bytes = (root / first.manifest_uri).read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        artifact_bytes = {
            name: (root / entry["uri"]).read_bytes()
            for name, entry in manifest["artifacts"].items()
        }
        conn.execute("DELETE FROM meta_state_build WHERE state_run_id = ?", [first.state_run_id])
        retry = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        assert retry.state_run_id == first.state_run_id
        assert retry.manifest_hash == first.manifest_hash
        assert (root / retry.manifest_uri).read_bytes() == manifest_bytes
        retry_manifest = json.loads((root / retry.manifest_uri).read_text(encoding="utf-8"))
        assert {
            name: (root / entry["uri"]).read_bytes()
            for name, entry in retry_manifest["artifacts"].items()
        } == artifact_bytes
    finally:
        conn.close()


def test_manifest_is_last_and_failure_has_no_success_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    from ashare_state.state import builder as builder_module

    real_write = builder_module._write_immutable
    calls: list[Path] = []

    def fail_manifest(path: Path, data: bytes) -> None:
        calls.append(path)
        if path.name == "manifest.json":
            raise RuntimeError("injected manifest failure")
        real_write(path, data)

    monkeypatch.setattr(builder_module, "_write_immutable", fail_manifest)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        with pytest.raises(RuntimeError, match="manifest"):
            StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
                "feature-run-1", STATE_SET_ID
            )
        assert [path.name for path in calls] == [
            "market_daily_state.parquet",
            "state_findings.parquet",
            "manifest.json",
        ]
        assert not list(root.rglob("manifest.json"))
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0
    finally:
        conn.close()


def test_ledger_commit_failure_exact_retry_recovers(
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
        real_commit = builder._commit_ledger
        attempts = [0]

        def fail_once(values: Any) -> None:
            if attempts[0] == 0:
                attempts[0] += 1
                raise RuntimeError("injected ledger commit failure")
            real_commit(values)

        monkeypatch.setattr(builder, "_commit_ledger", fail_once)
        with pytest.raises(RuntimeError, match="ledger commit failure"):
            builder.build("feature-run-1", STATE_SET_ID)
        assert list(root.rglob("manifest.json"))
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0

        retry = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        assert retry.status == "SUCCESS"
        assert retry.idempotent_replay is False
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 1
    finally:
        conn.close()


def test_partial_identical_residue_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    from ashare_state.state import builder as builder_module

    real_write = builder_module._write_immutable
    calls: list[Path] = []

    def fail_second(path: Path, data: bytes) -> None:
        calls.append(path)
        if len(calls) == 2:
            raise RuntimeError("injected partial artifact failure")
        real_write(path, data)

    monkeypatch.setattr(builder_module, "_write_immutable", fail_second)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        with pytest.raises(RuntimeError, match="partial artifact"):
            StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
                "feature-run-1", STATE_SET_ID
            )
        assert calls[0].is_file()
        assert not calls[1].exists()
        assert not list(root.rglob("manifest.json"))
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0

        retry = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        assert retry.status == "SUCCESS"
        assert calls[0].read_bytes()
        assert calls[1].is_file()
    finally:
        conn.close()


def test_conflicting_residue_refuses_without_new_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    from ashare_state.state import builder as builder_module

    real_write = builder_module._write_immutable
    calls: list[Path] = []

    def fail_second(path: Path, data: bytes) -> None:
        calls.append(path)
        if len(calls) == 2:
            raise RuntimeError("injected partial artifact failure")
        real_write(path, data)

    monkeypatch.setattr(builder_module, "_write_immutable", fail_second)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        with pytest.raises(RuntimeError, match="partial artifact"):
            StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
                "feature-run-1", STATE_SET_ID
            )
        original_path = calls[0]
        original_path.write_bytes(b"conflicting residue")
        with pytest.raises(StateBuilderError, match="different bytes"):
            StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
                "feature-run-1", STATE_SET_ID
            )
        assert conn.execute("SELECT COUNT(*) FROM meta_state_build").fetchone()[0] == 0
        assert original_path.read_bytes() == b"conflicting residue"
    finally:
        conn.close()


def test_wall_clock_timezone_does_not_change_identity_or_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    from ashare_state.state import builder as builder_module

    class UtcClock:
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 3, 12, 8, 0, tzinfo=UTC)

    class ShanghaiClock:
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 3, 12, 16, 0, tzinfo=timezone(timedelta(hours=8)))

    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        monkeypatch.setattr(builder_module, "datetime", UtcClock)
        first = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        manifest_bytes = (root / first.manifest_uri).read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        artifact_bytes = {
            name: (root / entry["uri"]).read_bytes()
            for name, entry in manifest["artifacts"].items()
        }
        conn.execute("DELETE FROM meta_state_build WHERE state_run_id = ?", [first.state_run_id])
        monkeypatch.setattr(builder_module, "datetime", ShanghaiClock)
        second = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        assert second.state_run_id == first.state_run_id
        assert second.manifest_hash == first.manifest_hash
        assert (root / second.manifest_uri).read_bytes() == manifest_bytes
        second_manifest = json.loads((root / second.manifest_uri).read_text(encoding="utf-8"))
        assert {
            name: (root / entry["uri"]).read_bytes()
            for name, entry in second_manifest["artifacts"].items()
        } == artifact_bytes
    finally:
        conn.close()


@pytest.mark.parametrize(
    "tamper_kind",
    ("schema", "row_count", "semantic"),
)
def test_physical_recompute_rejects_state_pair_rebind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        result = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        frame = pl.read_parquet(_state_artifact_path(root, result, "market_daily_state"))
        if tamper_kind == "schema":
            changed = pl.DataFrame({"trade_date": [date(2026, 3, 12)]})
        elif tamper_kind == "row_count":
            changed = pl.concat([frame, frame])
        else:
            rows = frame.to_dicts()
            rows[0]["return_center_state"] = "NEGATIVE_CENTER"
            changed = pl.DataFrame(
                rows,
                schema=state_artifact_schema("market_daily_state"),
            )
        _rebind_state_artifact(conn, root, result, "market_daily_state", changed)
        expected_message = {
            "schema": "schema differs",
            "row_count": "row count differs",
            "semantic": "differs from deterministic replay",
        }[tamper_kind]
        with pytest.raises(StateVerifierError, match=expected_message):
            verify_state_run_for_consumption(
                conn,
                result.state_run_id,
                raw_root=tmp_path / "raw",
                normalized_root=root,
            )
    finally:
        conn.close()


def test_evidence_rebind_is_rejected_by_independent_feature_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        result = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        frame = pl.read_parquet(_state_artifact_path(root, result, "market_daily_state"))
        rows = frame.to_dicts()
        rows[0]["evidence_mean_raw_return_observed"] = 0.99
        changed = pl.DataFrame(rows, schema=state_artifact_schema("market_daily_state"))
        _rebind_state_artifact(conn, root, result, "market_daily_state", changed)
        with pytest.raises(StateVerifierError, match="differs from deterministic replay"):
            verify_state_run_for_consumption(
                conn,
                result.state_run_id,
                raw_root=tmp_path / "raw",
                normalized_root=root,
            )
    finally:
        conn.close()


def test_business_state_rebind_is_rejected_by_independent_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_run = _feature_run()
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        result = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        frame = pl.read_parquet(_state_artifact_path(root, result, "market_daily_state"))
        rows = frame.to_dicts()
        rows[0]["return_center_state"] = "NEGATIVE_CENTER"
        changed = pl.DataFrame(rows, schema=state_artifact_schema("market_daily_state"))
        _rebind_state_artifact(conn, root, result, "market_daily_state", changed)
        with pytest.raises(StateVerifierError, match="differs from deterministic replay"):
            verify_state_run_for_consumption(
                conn,
                result.state_run_id,
                raw_root=tmp_path / "raw",
                normalized_root=root,
            )
    finally:
        conn.close()


def test_finding_rebind_is_rejected_by_deterministic_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _feature_row()
    row["mean_raw_return_observed"] = None
    feature_run = _feature_run(rows=(row,))
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        result = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        frame = pl.read_parquet(_state_artifact_path(root, result, "state_findings"))
        rows = frame.to_dicts()
        rows[0]["detail_json"] = '{"inputs":["forged"]}'
        changed = pl.DataFrame(rows, schema=state_artifact_schema("state_findings"))
        _rebind_state_artifact(conn, root, result, "state_findings", changed)
        with pytest.raises(StateVerifierError, match="differs from deterministic replay"):
            verify_state_run_for_consumption(
                conn,
                result.state_run_id,
                raw_root=tmp_path / "raw",
                normalized_root=root,
            )
    finally:
        conn.close()


def test_fatal_class_is_not_accepted_as_persisted_finding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _feature_row()
    row["mean_raw_return_observed"] = None
    feature_run = _feature_run(rows=(row,))
    _patch_feature_verifier(monkeypatch, feature_run)
    conn = duckdb.connect(":memory:")
    _create_ledger(conn)
    try:
        root = tmp_path / "normalized"
        result = StateBuilder(conn, raw_root=tmp_path / "raw", normalized_root=root).build(
            "feature-run-1", STATE_SET_ID
        )
        frame = pl.read_parquet(_state_artifact_path(root, result, "state_findings"))
        rows = frame.to_dicts()
        rows[0]["finding_class"] = STATE_RULE_UNAVAILABLE
        changed = pl.DataFrame(rows, schema=state_artifact_schema("state_findings"))
        _rebind_state_artifact(conn, root, result, "state_findings", changed)
        with pytest.raises(StateVerifierError, match="unknown finding_class"):
            verify_state_run_for_consumption(
                conn,
                result.state_run_id,
                raw_root=tmp_path / "raw",
                normalized_root=root,
            )
    finally:
        conn.close()
