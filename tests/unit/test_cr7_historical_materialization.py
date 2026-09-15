"""Adversarial tests for the bounded CR-7 historical implementation."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from ashare_state.providers.amazingdata.authoritative_history import (
    AmazingDataAcquisitionError,
    AmazingDataHistoryAcquisition,
)
from ashare_state.providers.amazingdata.operations import (
    DAILY_BAR_KLINE,
    HIST_CODE_LIST,
    HISTORY_STOCK_STATUS,
    TRADE_ACTIVITY_SNAPSHOT,
    TRADE_CALENDAR,
)
from ashare_state.providers.amazingdata.provider import AmazingDataProvider, RawEnvelope
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.research import (
    AMAZINGDATA_CALENDAR_MARKET,
    AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION,
    AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
    AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD,
    COMPLETE_OBSERVED_DAILY_BAR_SCOPE,
    AmazingDataAcquisitionReceipt,
    AuthoritativeCoverageEvidence,
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
    build_authoritative_coverage_basis_descriptor,
    build_authoritative_coverage_evidence_from_acquisition,
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
from ashare_state.storage import apply_migrations
from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter

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
            partial=partial,
        )
        for partition in expected_partition_keys()
    )


class _FakeAmazingDataProvider(AmazingDataProvider):
    """A typed-facade fake used only to exercise the acquisition boundary."""

    def __init__(self) -> None:
        self.calendar = _provider_exchange(
            TRADE_CALENDAR,
            {"market": AMAZINGDATA_CALENDAR_MARKET},
            [20191231, 20200102, 20200103, 20200203],
        )
        self.code_list = _provider_exchange(
            HIST_CODE_LIST,
            {
                "security_type": AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
                "start_date": 20200101,
                "end_date": 20200131,
            },
            ["000001.SZ", "600000.SH"],
        )
        self.exact_code_lists = {
            (20200102, 20200102): _provider_exchange(
                HIST_CODE_LIST,
                {
                    "security_type": AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
                    "start_date": 20200102,
                    "end_date": 20200102,
                },
                ["000001.SZ", "600000.SH"],
            ),
            (20200103, 20200103): _provider_exchange(
                HIST_CODE_LIST,
                {
                    "security_type": AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
                    "start_date": 20200103,
                    "end_date": 20200103,
                },
                ["000001.SZ", "600000.SH"],
            ),
        }

        def status_frame() -> pl.DataFrame:
            return pl.DataFrame(
                {
                    "MARKET_CODE": ["SH", "SH"],
                    "TRADE_DATE": [20200102, 20200103],
                    "PRECLOSE": [10.0, 10.5],
                    "HIGH_LIMITED": [11.0, 11.55],
                    "LOW_LIMITED": [9.0, 9.45],
                    "PRICE_HIGH_LMT_RATE": [0.1, 0.1],
                    "PRICE_LOW_LMT_RATE": [0.1, 0.1],
                    "IS_ST_SEC": [0, 0],
                    "IS_SUSP_SEC": [0, 0],
                    "IS_WD_SEC": [0, 0],
                    "IS_XR_SEC": [0, 0],
                }
            )

        self.status = _provider_exchange(
            HISTORY_STOCK_STATUS,
            {
                "begin_date": 20200101,
                "end_date": 20200131,
                "code_list": ["000001.SZ", "600000.SH"],
                "is_local": False,
            },
            {
                "000001.SZ": status_frame(),
                "600000.SH": status_frame(),
            },
        )

        def frame_for(symbol: str) -> pl.DataFrame:
            return pl.DataFrame(
                {
                    "code": [symbol, symbol],
                    "kline_time": [
                        datetime(2020, 1, 2),
                        datetime(2020, 1, 3),
                    ],
                    "open": [9.8, 10.2],
                    "high": [10.1, 10.7],
                    "low": [9.5, 10.0],
                    "close": [10.0, 10.5],
                    "volume": [100.0, 120.0],
                    "amount": [1000.0, 1260.0],
                }
            )

        self.kline = _provider_exchange(
            DAILY_BAR_KLINE,
            {
                "code_list": ["000001.SZ", "600000.SH"],
                "begin_date": 20200101,
                "end_date": 20200131,
                "kline_type": "DAY",
                "period": 10008,
                "trading_days": [20200102, 20200103],
            },
            {"000001.SZ": frame_for("000001.SZ"), "600000.SH": frame_for("600000.SH")},
        )

    def get_calendar_exchange(self, market: str = "SH") -> ProviderExchange:
        return self.calendar

    def get_hist_code_list_exchange(
        self, security_type: str, start_date: int, end_date: int
    ) -> ProviderExchange:
        if (start_date, end_date) == (20200101, 20200131):
            return self.code_list
        return self.exact_code_lists[(start_date, end_date)]

    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> ProviderExchange:
        return self.status

    def query_kline_exchange(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        kline_type: str = "DAY",
        trading_days: list[int] | None = None,
    ) -> ProviderExchange:
        return self.kline


class _PositiveFallbackFakeAmazingDataProvider(_FakeAmazingDataProvider):
    """Fake provider with exactly one zero-column status member."""

    def __init__(self) -> None:
        super().__init__()
        status_payload = dict(self.status.payload)
        status_payload["000001.SZ"] = pl.DataFrame()
        self.status = _provider_exchange(
            HISTORY_STOCK_STATUS,
            self.status.envelope.request_params,
            status_payload,
        )
        self.snapshots = {
            day: _provider_exchange(
                TRADE_ACTIVITY_SNAPSHOT,
                {
                    "code_list": ["000001.SZ"],
                    "begin_date": day,
                    "end_date": day,
                    "begin_time": 93000000,
                    "end_time": 150000000,
                },
                {
                    "000001.SZ": pl.DataFrame(
                        {
                            "code": ["000001.SZ"],
                            "trade_time": [datetime(day // 10000, (day // 100) % 100, day % 100)],
                            "num_trades": [1],
                        }
                    )
                },
            )
            for day in (20200102, 20200103)
        }

    def query_snapshot_exchange(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        begin_time: int = 93000000,
        end_time: int = 150000000,
    ) -> ProviderExchange:
        assert code_list == ["000001.SZ"]
        assert begin_date == end_date
        assert (begin_time, end_time) == (93000000, 150000000)
        return self.snapshots[begin_date]


def _provider_exchange(spec: Any, params: dict[str, Any], payload: Any) -> ProviderExchange:
    now = "2026-08-01T00:00:00+00:00"
    envelope = RawEnvelope(
        provider_dataset=spec.provider_dataset,
        endpoint=spec.endpoint,
        request_params=params,
        request_params_hash=RawEnvelope.params_hash(params),
        requested_at=now,
        received_at=now,
        operation_id=spec.operation_id,
        normalization_surface=spec.normalization_surface,
    )
    return ProviderExchange(envelope=envelope, payload=payload)


def _acquisition_receipt(
    tmp_path: Path,
    *,
    provider: AmazingDataProvider | None = None,
) -> Any:
    source_snapshot = _projection([])
    acquisition = AmazingDataHistoryAcquisition(
        provider or _FakeAmazingDataProvider(),
        _anchored_writer(tmp_path / "raw", ingest_run_id="unit-test-acquisition"),
        source_snapshot,
    )
    return acquisition.acquire_month(PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1))


def _anchored_writer(raw_root: Path, *, ingest_run_id: str) -> AnchoredRawEvidenceWriter:
    conn = duckdb.connect(":memory:")
    apply_migrations(conn, Path(__file__).parents[2] / "migrations")
    return AnchoredRawEvidenceWriter(conn, raw_root, ingest_run_id=ingest_run_id)


def _authoritative_evidence(
    partition: PartitionKey,
    tmp_path: Path,
) -> AuthoritativeCoverageEvidence:
    receipt = _acquisition_receipt(tmp_path)
    receipt_partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    if partition != receipt_partition:
        raise AssertionError(f"test receipt is only for {receipt_partition.logical_key}")
    return build_authoritative_coverage_evidence_from_acquisition(partition, receipt)


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
    )
    partial = build_fixture_coverage_basis_descriptor(
        PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 2),
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
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


def test_authoritative_adapter_emits_only_with_sealed_upstream_evidence(tmp_path: Path) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    evidence = _authoritative_evidence(partition, tmp_path)
    descriptor = build_authoritative_coverage_basis_descriptor(partition, evidence)

    assert descriptor.completeness_method == AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD
    assert descriptor.evidence_class is CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM
    assert descriptor.authoritative_evidence is evidence
    assert descriptor.authoritative_evidence.coverage_basis_evidence_hash

    forged = descriptor.as_dict()
    forged["completeness_method"] = AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD
    forged_bytes = canonical_json(
        {key: forged[key] for key in forged if key != "coverage_basis_artifact_hash"}
    ).encode()
    forged["coverage_basis_artifact_hash"] = sha256_hex(forged_bytes)
    with pytest.raises(CoverageBasisError, match="typed evidence sidecar"):
        CoverageBasisDescriptor.from_mapping(forged, artifact_bytes=forged_bytes)


def test_authoritative_materializer_requires_the_retained_capture_root(tmp_path: Path) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    evidence = _authoritative_evidence(partition, tmp_path)
    descriptor = build_authoritative_coverage_basis_descriptor(partition, evidence)
    materializer = OfflineHistoricalMaterializer(
        tmp_path / "materialized",
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )
    with pytest.raises(HistoricalMaterializationError, match="capture root"):
        materializer.plan(_fixture_projection(), coverage_bases=(descriptor,))


def test_bounded_authoritative_materialization_is_readable_and_idempotent(
    tmp_path: Path,
) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    projection = _projection([_row(date(2020, 1, 2), "security-sse")])
    evidence = _authoritative_evidence(partition, tmp_path)
    descriptor = build_authoritative_coverage_basis_descriptor(partition, evidence)
    materializer = OfflineHistoricalMaterializer(
        tmp_path / "materialized",
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
        authoritative_capture_root=tmp_path / "raw",
    )

    first = materializer.materialize(
        projection,
        coverage_bases=(descriptor,),
        materialization_partitions=(partition,),
        build_timestamp="2026-09-15T00:00:00+00:00",
    )
    manifest_path = tmp_path / "materialized" / first.manifest_uri
    reader = HistoricalMaterializationReader.from_manifest(
        manifest_path,
        authoritative_capture_root=tmp_path / "raw",
    )
    loaded = reader.load_security_daily(
        split=ResearchSplit.DEVELOPMENT,
        start="2020-01-02",
        end="2020-01-02",
    )
    assert loaded.height == 1
    assert reader.manifest["logical_partition_count"] == 1
    assert reader.manifest["materialization_scope"]["kind"] == "BOUNDED_PARTITIONS"
    with pytest.raises(HistoricalReadError, match="materialization scope"):
        reader.load_security_daily(
            split=ResearchSplit.DEVELOPMENT,
            start="2020-02-01",
            end="2020-02-01",
        )

    replay = materializer.materialize(
        projection,
        coverage_bases=(descriptor,),
        materialization_partitions=(partition,),
        build_timestamp="2026-09-16T00:00:00+00:00",
    )
    assert replay.idempotent_replay is True

    changed = _projection([_row(date(2020, 1, 2), "security-sse", close=11.5)])
    with pytest.raises(MaterializationConflictError, match="content|inventory"):
        materializer.materialize(
            changed,
            coverage_bases=(descriptor,),
            materialization_partitions=(partition,),
            build_timestamp="2026-09-15T00:00:00+00:00",
        )


def test_bounded_scope_orders_multiple_typed_partitions(tmp_path: Path) -> None:
    first = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    second = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 2)
    materializer = OfflineHistoricalMaterializer(
        tmp_path,
        writer_runtime_lock_hash=_writer_hash(),
        build_code_fingerprint=BUILD_FINGERPRINT,
    )

    plan = materializer.plan(
        _projection([_row(date(2020, 1, 2), "security-sse")]),
        materialization_partitions=(second, first),
    )

    assert plan.materialization_partitions == (first, second)
    assert len(plan.logical_partition_inventory) == 2
    assert plan.coverage_evidence_class is CoverageEvidenceClass.UNRESOLVED


def test_authoritative_evidence_rejects_stale_selection_fields_and_wrong_scope(
    tmp_path: Path,
) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    evidence = _authoritative_evidence(partition, tmp_path)

    stale_selection = evidence.as_dict(include_artifact_hash=False)
    stale_selection["source_selection_fingerprint"] = "0" * 64
    stale_selection_bytes = canonical_json(stale_selection).encode()
    with pytest.raises(CoverageBasisError, match="fields are not exact"):
        AuthoritativeCoverageEvidence.from_mapping(
            stale_selection,
            artifact_bytes=stale_selection_bytes,
            artifact_hash=sha256_hex(stale_selection_bytes),
        )

    wrong_scope = evidence.as_dict(include_artifact_hash=False)
    wrong_scope["claimed_scope_start"] = "2020-02-01"
    wrong_scope["claimed_scope_end"] = "2020-02-29"
    wrong_scope["upstream_inventory_scope_start"] = "2020-02-01"
    wrong_scope["upstream_inventory_scope_end"] = "2020-02-29"
    wrong_scope_bytes = canonical_json(wrong_scope).encode()
    with pytest.raises(CoverageBasisError, match="receipt|scope"):
        AuthoritativeCoverageEvidence.from_mapping(
            wrong_scope,
            artifact_bytes=wrong_scope_bytes,
            artifact_hash=sha256_hex(wrong_scope_bytes),
        )


def test_authoritative_evidence_rejects_tampered_bytes_and_downgrade(tmp_path: Path) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    evidence = _authoritative_evidence(partition, tmp_path)
    payload = evidence.as_dict(include_artifact_hash=False)
    with pytest.raises(CoverageBasisError, match="not canonical|does not match bytes"):
        AuthoritativeCoverageEvidence.from_mapping(
            payload,
            artifact_bytes=evidence.artifact_bytes + b"tampered",
            artifact_hash=evidence.coverage_basis_evidence_hash,
        )

    with pytest.raises(CoverageBasisError, match="explicitly claim complete"):
        replace(evidence, completeness_claim="PARTIAL_OBSERVED_DAILY_BAR_SCOPE")

    partial = build_fixture_coverage_basis_descriptor(
        partition,
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_manifest_hash=SNAPSHOT_MANIFEST_HASH,
        partial=True,
    )
    escalated = partial.as_dict()
    escalated["completeness_method"] = AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD
    escalated["completeness_claim"] = COMPLETE_OBSERVED_DAILY_BAR_SCOPE
    escalated_bytes = canonical_json(
        {key: escalated[key] for key in escalated if key != "coverage_basis_artifact_hash"}
    ).encode()
    escalated["coverage_basis_artifact_hash"] = sha256_hex(escalated_bytes)
    with pytest.raises(CoverageBasisError, match="typed evidence sidecar"):
        CoverageBasisDescriptor.from_mapping(
            escalated,
            artifact_bytes=escalated_bytes,
        )


def test_authority_cannot_be_minted_from_arbitrary_bytes_or_replayed_catalog(
    tmp_path: Path,
) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    receipt = _acquisition_receipt(tmp_path)
    evidence = build_authoritative_coverage_evidence_from_acquisition(partition, receipt)

    assert (
        "upstream_statement_bytes"
        not in inspect.signature(build_authoritative_coverage_evidence_from_acquisition).parameters
    )
    replayed = AmazingDataAcquisitionReceipt.from_mapping(receipt.as_dict())
    build_authoritative_coverage_evidence_from_acquisition(partition, replayed)

    evidence_payload = evidence.as_dict(include_artifact_hash=False)
    replayed_evidence = AuthoritativeCoverageEvidence.from_mapping(
        evidence_payload,
        artifact_bytes=evidence.artifact_bytes,
        artifact_hash=evidence.coverage_basis_evidence_hash,
    )
    assert replayed_evidence.acquisition_receipt.receipt_hash == receipt.receipt_hash


def test_acquisition_uses_closed_single_session_requests(tmp_path: Path) -> None:
    receipt = _acquisition_receipt(tmp_path)

    assert receipt.semantic_operations
    for operation in receipt.semantic_operations:
        payload = json.loads(
            (tmp_path / "raw" / Path(operation.captured_evidence_uri)).read_text(encoding="utf-8")
        )
        request_params = payload["request_params"]
        assert request_params["start_date"] == request_params["end_date"]


def test_acquisition_persists_and_replays_the_raw_capture_chain(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    receipt = _acquisition_receipt(tmp_path)
    receipt.verify_retained_capture(raw_root)
    replayed = AmazingDataAcquisitionReceipt.from_mapping(receipt.as_dict())
    replayed.verify_retained_capture(raw_root)

    catalog_path = raw_root.joinpath(*receipt.source_capture_uri.split("/"))
    catalog_path.write_bytes(b"tampered")
    with pytest.raises(CoverageBasisError, match="catalog"):
        replayed.verify_retained_capture(raw_root)


def test_fixed_amazingdata_policy_uses_direct_receipt_fields() -> None:
    import ashare_state.research.historical as historical

    assert not hasattr(historical, "AuthoritativeSourceSelection")
    assert (
        "source_selection_fingerprint"
        not in historical.AmazingDataAcquisitionReceipt.__annotations__
    )
    assert "source_selection" not in historical.AmazingDataAcquisitionReceipt.__annotations__
    assert (
        "source_selection_fingerprint"
        not in historical.AuthoritativeCoverageEvidence.__annotations__
    )
    assert "source_selection" not in historical.AuthoritativeCoverageEvidence.__annotations__
    assert "source_selection_fingerprint" not in historical.CoverageBasisDescriptor.__annotations__
    assert "source_selection" not in historical.CoverageBasisDescriptor.__annotations__


def test_positive_trade_fallback_is_retained_and_replayed(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    receipt = _acquisition_receipt(
        tmp_path,
        provider=_PositiveFallbackFakeAmazingDataProvider(),
    )

    assert receipt.positive_trade_fallback_version == (AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION)
    assert len(receipt.positive_trade_operations) == 2
    assert receipt.completeness_evaluation.positive_trade_pair_count == 2
    receipt.verify_retained_capture(raw_root)
    replayed = AmazingDataAcquisitionReceipt.from_mapping(receipt.as_dict())
    replayed.verify_retained_capture(raw_root)

    snapshot = receipt.positive_trade_operations[0]
    snapshot_meta = raw_root / Path(snapshot.exchange.captured_evidence_uri)
    snapshot_meta.write_bytes(snapshot_meta.read_bytes() + b"tampered")
    with pytest.raises(CoverageBasisError, match="positive-trade snapshot evidence hash"):
        replayed.verify_retained_capture(raw_root)


def test_old_acquisition_receipt_version_is_rejected(tmp_path: Path) -> None:
    receipt = _acquisition_receipt(tmp_path)
    payload = receipt.as_dict()
    payload["receipt_version"] = "amazingdata-history-acquisition-receipt-v3"
    with pytest.raises(CoverageBasisError, match="unknown AmazingData acquisition receipt version"):
        AmazingDataAcquisitionReceipt.from_mapping(payload)


def test_legacy_source_selection_fields_are_rejected(tmp_path: Path) -> None:
    receipt = _acquisition_receipt(tmp_path)
    payload = receipt.as_dict()
    payload["source_selection"] = {"selection_fingerprint": "0" * 64}
    with pytest.raises(CoverageBasisError, match="fields are not exact"):
        AmazingDataAcquisitionReceipt.from_mapping(payload)


def test_acquisition_rejects_partial_daily_bar_response(tmp_path: Path) -> None:
    provider = _FakeAmazingDataProvider()
    payload = provider.kline.payload
    assert isinstance(payload, dict)
    provider.kline = _provider_exchange(
        DAILY_BAR_KLINE,
        provider.kline.envelope.request_params,
        {
            "000001.SZ": payload["000001.SZ"].head(1),
            "600000.SH": payload["600000.SH"],
        },
    )
    acquisition = AmazingDataHistoryAcquisition(
        provider,
        _anchored_writer(tmp_path / "raw", ingest_run_id="unit-test-partial"),
        _projection([]),
    )
    with pytest.raises(AmazingDataAcquisitionError, match="month completeness"):
        acquisition.acquire_month(PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1))


def test_acquisition_rejects_daily_bar_schema_drift(tmp_path: Path) -> None:
    provider = _FakeAmazingDataProvider()
    payload = provider.kline.payload
    assert isinstance(payload, dict)
    invalid_frame = payload["000001.SZ"].select(["kline_time", "close"])
    provider.kline = _provider_exchange(
        DAILY_BAR_KLINE,
        provider.kline.envelope.request_params,
        {"000001.SZ": invalid_frame, "600000.SH": payload["600000.SH"]},
    )
    acquisition = AmazingDataHistoryAcquisition(
        provider,
        _anchored_writer(tmp_path / "raw", ingest_run_id="unit-test-schema-drift"),
        _projection([]),
    )
    with pytest.raises(AmazingDataAcquisitionError, match="month completeness"):
        acquisition.acquire_month(PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1))


def test_authoritative_reader_protocol_tamper_stays_fail_closed(tmp_path: Path) -> None:
    partition = PartitionKey(ResearchSplit.DEVELOPMENT, 2020, 1)
    evidence = _authoritative_evidence(partition, tmp_path)
    payload = evidence.as_dict(include_artifact_hash=False)
    payload["acquisition_receipt"]["retrieved_at_utc"] = "2026-07-01T00:00:00+00:00"
    tampered_bytes = canonical_json(payload).encode()
    with pytest.raises(CoverageBasisError):
        AuthoritativeCoverageEvidence.from_mapping(
            payload,
            artifact_bytes=tampered_bytes,
            artifact_hash=sha256_hex(tampered_bytes),
        )


def _coverage_evidence_relative_path_for_test(
    evidence: AuthoritativeCoverageEvidence,
) -> str:
    return f"coverage_basis_evidence/{evidence.coverage_basis_evidence_hash}.json"


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
        coverage_basis_id="fixture-basis-altered",
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
