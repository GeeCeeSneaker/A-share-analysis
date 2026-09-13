"""Adversarial tests for the bounded CR-7 historical implementation."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from ashare_state.research import (
    COMPLETE_OBSERVED_DAILY_BAR_SCOPE,
    CoverageBasisDescriptor,
    CoverageBasisError,
    CoverageEvidenceClass,
    CoverageState,
    HistoricalMaterializationError,
    HistoricalMaterializationReader,
    HistoricalReadError,
    IdentityRecord,
    IdentitySource,
    IdentityView,
    MaterializationConflictError,
    OfflineHistoricalMaterializer,
    PartitionKey,
    ResearchEligibility,
    ResearchSplit,
    VerifiedResearchProjection,
    build_fixture_coverage_basis_descriptor,
    compute_coverage_basis_set_hash,
    compute_writer_runtime_lock_hash,
    expected_partition_keys,
)
from ashare_state.research.models import (
    VERIFIED_SECURITY_MASTER_SOURCE,
    canonical_json,
    sha256_hex,
)

SNAPSHOT_ID = "cr7-offline-snapshot"
SNAPSHOT_MANIFEST_HASH = "a" * 64
SNAPSHOT_SEMANTIC_HASH = "b" * 64
CANONICAL_RUN_ID = "cr7-offline-canonical"
AVAILABLE_AT = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
BUILD_FINGERPRINT = "c" * 64


def _writer_hash(suffix: str = "1") -> str:
    return compute_writer_runtime_lock_hash(
        dependency_lock_content_hash="d" * 64,
        python_runtime_identity=f"CPython-3.14-{suffix}",
        parquet_writer_engine_identity="polars-1.x-pyarrow-17.x",
    )


def _row(
    trade_date: date,
    security_id: str,
    *,
    exchange: str | None = "SSE",
    eligibility: str = ResearchEligibility.ENABLED.value,
    exclusion_reason: str | None = None,
    close: float = 10.5,
) -> dict[str, Any]:
    assigned = (
        "warmup"
        if trade_date < date(2020, 1, 1)
        else "outside_window"
        if trade_date > date(2026, 6, 30)
        else (
            "development"
            if trade_date <= date(2023, 12, 31)
            else "validation_a"
            if trade_date <= date(2025, 12, 31)
            else "holdout"
        )
    )
    return {
        "trade_date": trade_date,
        "security_id": security_id,
        "symbol": None if exchange is None else "600000",
        "exchange": exchange,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": close,
        "pre_close": None,
        "volume": 100.0,
        "amount": 2_000.0,
        "research_split": assigned,
        "research_eligibility": eligibility,
        "research_exclusion_reason": exclusion_reason,
        "data_quality_state": (
            "VERIFIED" if eligibility == ResearchEligibility.ENABLED.value else "UNRESOLVED"
        ),
        "available_at": AVAILABLE_AT,
        "source_snapshot_id": SNAPSHOT_ID,
        "source_readmodel_contract_version": "readmodel-v1",
        "source_canonical_run_id": CANONICAL_RUN_ID,
        "source_canonical_domain": "daily_bar",
        "source_canonical_key": json.dumps(
            [security_id, trade_date.isoformat()], separators=(",", ":")
        ),
        "source_row_identity_hash": f"row-{security_id}-{trade_date.isoformat()}",
        "identity_view_version": "identity-fixture-v1",
        "identity_view_hash": "e" * 64,
    }


def _projection(rows: list[dict[str, Any]]) -> VerifiedResearchProjection:
    identity_view = IdentityView._from_verified_security_master(  # noqa: SLF001
        (
            IdentityRecord(
                security_id="security-sse",
                symbol="600000",
                exchange="SSE",
                valid_from=date(1999, 1, 1),
            ),
        ),
        sources=(
            IdentitySource(
                source_kind=VERIFIED_SECURITY_MASTER_SOURCE,
                canonical_run_id=CANONICAL_RUN_ID,
                canonical_as_of="2026-09-01T00:00:00+00:00",
                normalization_run_id="cr7-offline-identity",
                provider="fixture",
                normalization_surface="security_master",
                provider_dataset="fixture_code_list",
                endpoint="fixture.identity",
                normalized_manifest_uri="fixture/identity/manifest.json",
                normalized_manifest_hash="f" * 64,
                normalized_output_name="main",
                normalized_output_uri="fixture/identity/main.parquet",
                normalized_output_hash="1" * 64,
                normalized_output_schema_hash="2" * 64,
                normalized_output_row_count=1,
                normalized_output_set_hash="3" * 64,
                normalized_semantic_hash="4" * 64,
                verification="HEALTHY",
                pit_available=True,
            ),
        ),
    )
    for row in rows:
        row["identity_view_version"] = identity_view.version
        row["identity_view_hash"] = identity_view.content_hash
    return VerifiedResearchProjection(
        rows=tuple(rows),
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_as_of=datetime(2026, 9, 1, tzinfo=UTC),
        source_canonical_run_id=CANONICAL_RUN_ID,
        source_readmodel_contract_version="readmodel-v1",
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        source_snapshot_semantic_hash=SNAPSHOT_SEMANTIC_HASH,
        identity_view=identity_view,
    )


def _fixture_projection() -> VerifiedResearchProjection:
    return _projection(
        [
            _row(date(2020, 1, 1), "security-sse"),
            _row(
                date(2020, 1, 2),
                "fixture-bse",
                exchange="BSE",
                eligibility=ResearchEligibility.DISABLED_UNRESOLVED.value,
                exclusion_reason="bse_identity_boundary_unresolved",
            ),
            _row(
                date(2019, 12, 31),
                "outside-row",
                exchange=None,
                eligibility=ResearchEligibility.DISABLED_UNRESOLVED.value,
                exclusion_reason="outside_research_window",
            ),
        ]
    )


def _january_basis() -> Any:
    return build_fixture_coverage_basis_descriptor(
        PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1),
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        source_selection_fingerprint="selection-fixture-v1",
    )


def _full_window_fixture_projection() -> VerifiedResearchProjection:
    return _projection(
        [_row(partition.scope_start, "security-sse") for partition in expected_partition_keys()]
    )


def _full_window_fixture_bases(*, partial: bool = False) -> tuple[CoverageBasisDescriptor, ...]:
    return tuple(
        build_fixture_coverage_basis_descriptor(
            partition,
            source_snapshot_id=SNAPSHOT_ID,
            source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
            source_selection_fingerprint=f"selection-{partition.logical_key}",
            partial=partial,
        )
        for partition in expected_partition_keys()
    )


def test_plan_has_78_months_and_keeps_bse_out_of_enabled_route(tmp_path: Path) -> None:
    projection = _fixture_projection()
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    plan = materializer.plan(projection, coverage_bases=(_january_basis(),))

    assert len(expected_partition_keys()) == 78
    assert len(plan.logical_partition_inventory) == 78
    assert plan.coverage_state is CoverageState.UNRESOLVED_NOT_FOR_RESEARCH
    assert plan.coverage_evidence_class is CoverageEvidenceClass.UNRESOLVED
    assert plan.excluded_row_count == 1
    assert {artifact.route for artifact in plan.artifacts} == {"research_enabled", "disabled"}
    assert all(
        artifact.route != "research_enabled" or artifact.row_count == 1
        for artifact in plan.artifacts
    )
    january = next(
        item
        for item in plan.logical_partition_inventory
        if item["research_split"] == "development"
        and item["calendar_year"] == 2020
        and item["calendar_month"] == 1
    )
    assert january["routes"]["research_enabled"]["row_count"] == 1
    assert january["routes"]["disabled"]["row_count"] == 1
    assert january["routes"]["research_enabled"]["coverage_state"] == (
        CoverageState.OBSERVED_DAILY_BAR_COVERAGE.value
    )
    enabled_routes = [
        item["routes"]["research_enabled"] for item in plan.logical_partition_inventory
    ]
    assert (
        sum(
            entry["coverage_state"] == CoverageState.OBSERVED_DAILY_BAR_COVERAGE.value
            for entry in enabled_routes
        )
        == 1
    )
    assert (
        sum(
            entry["coverage_state"] == CoverageState.UNRESOLVED_NOT_FOR_RESEARCH.value
            for entry in enabled_routes
        )
        == 77
    )
    result = materializer.materialize(
        projection,
        coverage_bases=(_january_basis(),),
        build_timestamp="2026-09-13T00:00:00+00:00",
    )
    with pytest.raises(HistoricalReadError, match="partial or unresolved"):
        HistoricalMaterializationReader.from_manifest(tmp_path / result.manifest_uri)


def test_fixture_complete_never_unlocks_ordinary_historical_reader(tmp_path: Path) -> None:
    projection = _full_window_fixture_projection()
    bases = _full_window_fixture_bases()
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    plan = materializer.plan(projection, coverage_bases=bases)
    assert plan.coverage_state is CoverageState.OBSERVED_DAILY_BAR_COVERAGE
    assert plan.coverage_evidence_class is CoverageEvidenceClass.TEST_FIXTURE_ONLY
    assert all(
        item["routes"]["research_enabled"]["coverage_state"]
        == CoverageState.OBSERVED_DAILY_BAR_COVERAGE.value
        for item in plan.logical_partition_inventory
    )
    result = materializer.materialize(
        projection,
        coverage_bases=bases,
        build_timestamp="2026-09-13T00:00:00+00:00",
    )
    with pytest.raises(HistoricalReadError, match="non-authoritative|fixture-only"):
        HistoricalMaterializationReader.from_manifest(tmp_path / result.manifest_uri)


def test_historical_boundary_does_not_use_r1_publisher_or_unverified_identity() -> None:
    import ashare_state.research.historical as historical

    materializer_source = inspect.getsource(historical.OfflineHistoricalMaterializer)
    assert "ResearchPanelBuilder" not in materializer_source
    assert "build_from_readmodel" not in materializer_source
    caller_identity_projection = VerifiedResearchProjection(
        rows=(),
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_as_of=datetime(2026, 9, 1, tzinfo=UTC),
        source_canonical_run_id=CANONICAL_RUN_ID,
        source_readmodel_contract_version="readmodel-v1",
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        source_snapshot_semantic_hash=SNAPSHOT_SEMANTIC_HASH,
        identity_view=IdentityView.from_rows([], version="caller-fixture-v1"),
    )
    with pytest.raises(HistoricalMaterializationError, match="unverified caller"):
        OfflineHistoricalMaterializer(
            Path("fixture-a"),
            writer_runtime_lock_hash=_writer_hash(),
            build_code_fingerprint=BUILD_FINGERPRINT,
        ).plan(caller_identity_projection)


def test_sparse_verified_projection_without_basis_is_not_observed(tmp_path: Path) -> None:
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    plan = materializer.plan(_fixture_projection())
    assert plan.coverage_state is CoverageState.UNRESOLVED_NOT_FOR_RESEARCH
    result = materializer.materialize(
        _fixture_projection(),
        build_timestamp="2026-09-13T00:00:00+00:00",
    )
    with pytest.raises(HistoricalReadError, match="partial or unresolved"):
        HistoricalMaterializationReader.from_manifest(tmp_path / result.manifest_uri)


def test_partial_basis_is_explicit_but_reader_stays_blocked(tmp_path: Path) -> None:
    projection = _full_window_fixture_projection()
    partial_bases = _full_window_fixture_bases(partial=True)
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    plan = materializer.plan(projection, coverage_bases=partial_bases)
    assert plan.coverage_state is CoverageState.PARTIAL_OBSERVED_DAILY_BAR_COVERAGE
    assert plan.coverage_evidence_class is CoverageEvidenceClass.TEST_FIXTURE_ONLY
    result = materializer.materialize(
        projection,
        coverage_bases=partial_bases,
        build_timestamp="2026-09-13T00:00:00+00:00",
    )
    with pytest.raises(HistoricalReadError, match="partial or unresolved"):
        HistoricalMaterializationReader.from_manifest(tmp_path / result.manifest_uri)


def test_mixed_complete_partial_basis_is_order_independent(tmp_path: Path) -> None:
    projection = _projection(
        [
            _row(date(2020, 1, 1), "security-sse"),
            _row(date(2020, 2, 3), "security-sse"),
        ]
    )
    complete = build_fixture_coverage_basis_descriptor(
        PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1),
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        source_selection_fingerprint="selection-complete",
    )
    partial = build_fixture_coverage_basis_descriptor(
        PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 2),
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        source_selection_fingerprint="selection-partial",
        partial=True,
    )
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    states_by_order: list[dict[str, CoverageState]] = []
    for descriptors in ((complete, partial), (partial, complete)):
        plan = materializer.plan(projection, coverage_bases=descriptors)
        states_by_order.append(
            {
                evaluation.partition.logical_key: evaluation.state
                for evaluation in plan.coverage_evaluations
                if evaluation.partition in {complete.partition_key, partial.partition_key}
            }
        )
        assert plan.coverage_state is CoverageState.UNRESOLVED_NOT_FOR_RESEARCH
    assert states_by_order == [
        {
            complete.partition_key.logical_key: CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
            partial.partition_key.logical_key: CoverageState.PARTIAL_OBSERVED_DAILY_BAR_COVERAGE,
        },
        {
            complete.partition_key.logical_key: CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
            partial.partition_key.logical_key: CoverageState.PARTIAL_OBSERVED_DAILY_BAR_COVERAGE,
        },
    ]


def test_coverage_basis_rejects_forged_method_and_exact_bytes_are_bound() -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    basis = _january_basis()
    assert basis.as_dict()["completeness_claim"] == COMPLETE_OBSERVED_DAILY_BAR_SCOPE
    assert sha256_hex(basis.artifact_bytes) == basis.coverage_basis_artifact_hash
    forged = basis.as_dict()
    forged["completeness_method"] = "COMPLETE_WHATEVER_CALLER_SAYS_V1"
    forged_bytes = canonical_json(
        {key: forged[key] for key in forged if key != "coverage_basis_artifact_hash"}
    )
    forged["coverage_basis_artifact_hash"] = sha256_hex(forged_bytes)
    with pytest.raises(CoverageBasisError, match="unknown versioned completeness_method"):
        CoverageBasisDescriptor.from_mapping(forged, artifact_bytes=forged_bytes.encode())
    wrong_bytes = basis.artifact_bytes + b"\n"
    with pytest.raises(CoverageBasisError, match="exact canonical"):
        CoverageBasisDescriptor.from_mapping(basis.as_dict(), artifact_bytes=wrong_bytes)
    assert partition == basis.partition_key


def test_writer_lock_and_basis_change_identity() -> None:
    projection = _fixture_projection()
    basis = _january_basis()
    first = OfflineHistoricalMaterializer(
        Path("fixture-a"),
        writer_runtime_lock_hash=_writer_hash("1"),
        build_code_fingerprint=BUILD_FINGERPRINT,
    ).plan(projection, coverage_bases=(basis,))
    second = OfflineHistoricalMaterializer(
        Path("fixture-a"),
        writer_runtime_lock_hash=_writer_hash("2"),
        build_code_fingerprint=BUILD_FINGERPRINT,
    ).plan(projection, coverage_bases=(basis,))
    changed_basis = build_fixture_coverage_basis_descriptor(
        basis.partition_key,
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        source_selection_fingerprint="selection-fixture-v2",
    )
    third = OfflineHistoricalMaterializer(
        Path("fixture-a"),
        writer_runtime_lock_hash=_writer_hash("1"),
        build_code_fingerprint=BUILD_FINGERPRINT,
    ).plan(projection, coverage_bases=(changed_basis,))
    assert first.materialization_id != second.materialization_id
    assert first.materialization_id != third.materialization_id
    assert compute_coverage_basis_set_hash((basis,)) != compute_coverage_basis_set_hash(
        (changed_basis,)
    )


def test_staging_failure_is_invisible_and_same_identity_can_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ashare_state.research.historical as historical

    projection = _fixture_projection()
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    original = historical.write_file_atomic
    calls = 0

    def fail_after_first(path: Path, data: bytes, **kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("injected staging failure")
        return original(path, data, **kwargs)

    monkeypatch.setattr(historical, "write_file_atomic", fail_after_first)
    with pytest.raises(OSError, match="injected"):
        materializer.materialize(
            projection,
            coverage_bases=(_january_basis(),),
            build_timestamp="2026-09-13T00:00:00+00:00",
        )
    dataset_root = tmp_path / "research_security_daily"
    assert not (dataset_root / "contract=cr7-history-materialization-v1").exists()
    assert list((dataset_root / ".staging").iterdir())

    monkeypatch.setattr(historical, "write_file_atomic", original)
    resumed = materializer.materialize(
        projection,
        coverage_bases=(_january_basis(),),
        build_timestamp="2026-09-13T00:00:00+00:00",
    )
    assert resumed.idempotent_replay is False
    assert (tmp_path / resumed.manifest_uri).is_file()
    assert (tmp_path / resumed.success_uri).is_file()


def test_identical_replay_is_byte_stable_and_changed_bytes_conflict(tmp_path: Path) -> None:
    projection = _fixture_projection()
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    first = materializer.materialize(
        projection,
        coverage_bases=(_january_basis(),),
        build_timestamp="2026-09-13T00:00:00+00:00",
    )
    committed = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / first.manifest_uri).parent.rglob("*")
        if path.is_file()
    }
    replay = materializer.materialize(
        projection,
        coverage_bases=(_january_basis(),),
        build_timestamp="2026-09-14T00:00:00+00:00",
    )
    assert replay.idempotent_replay is True
    assert committed == {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / first.manifest_uri).parent.rglob("*")
        if path.is_file()
    }
    changed_rows = [dict(row) for row in projection.rows]
    changed_rows[0]["close"] = 10.6
    with pytest.raises(MaterializationConflictError, match="content|inventory"):
        materializer.materialize(
            _projection(changed_rows),
            coverage_bases=(_january_basis(),),
            build_timestamp="2026-09-13T00:00:00+00:00",
        )


def test_projection_rows_cannot_mix_splits_or_duplicate_primary_keys(tmp_path: Path) -> None:
    row = _row(date(2020, 1, 1), "security-sse")
    duplicate = dict(row)
    with pytest.raises(Exception, match="duplicate historical primary key"):
        OfflineHistoricalMaterializer(
            tmp_path,
            writer_runtime_lock_hash=_writer_hash(),
            build_code_fingerprint=BUILD_FINGERPRINT,
        ).plan(_projection([row, duplicate]))
    split_mismatch = dict(row)
    split_mismatch["research_split"] = "validation_a"
    with pytest.raises(Exception, match="research_split"):
        OfflineHistoricalMaterializer(
            tmp_path,
            writer_runtime_lock_hash=_writer_hash(),
            build_code_fingerprint=BUILD_FINGERPRINT,
        ).plan(_projection([split_mismatch]))
