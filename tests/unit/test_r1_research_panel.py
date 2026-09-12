"""Focused CR-7 R1 contract and immutable research-panel tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ashare_state.research import (
    CoverageState,
    IdentityView,
    ResearchEligibility,
    ResearchManifestError,
    ResearchPanelBuilder,
    ResearchPanelError,
    ResearchPanelReader,
    ResearchReaderError,
    ResearchSplit,
    assign_research_split,
    load_research_security_daily,
)

SNAPSHOT_ID = "snapshot-r1-fixture"
CANONICAL_RUN_ID = "canonical-r1-fixture"
AVAILABLE_AT = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)


def _identity_view() -> IdentityView:
    return IdentityView.from_rows(
        [
            {
                "security_id": "security-sse",
                "symbol": "600000",
                "exchange": "SSE",
                "valid_from": "1999-01-01",
            },
            {
                "security_id": "security-szse",
                "symbol": "000001",
                "exchange": "SZSE",
                "valid_from": "1991-01-01",
            },
        ],
        version="identity-fixture-v1",
    )


def _row(
    trade_date: date,
    security_id: str,
    *,
    high: float = 11.0,
    low: float = 9.0,
    eligibility: str | None = None,
) -> dict[str, Any]:
    return {
        "canonical_domain": "daily_bar",
        "canonical_key": json.dumps([security_id, trade_date.isoformat()], separators=(",", ":")),
        "security_id": security_id,
        "trade_date": trade_date,
        "available_at": AVAILABLE_AT,
        "canonical_run_id": CANONICAL_RUN_ID,
        "snapshot_id": SNAPSHOT_ID,
        "source_row_identity_hash": f"source-{security_id}-{trade_date.isoformat()}",
        "open": 10.0,
        "high": high,
        "low": low,
        "close": 10.5,
        "pre_close": None,
        "volume": 100.0,
        "amount": 2000.0,
        **({"research_eligibility": eligibility} if eligibility else {}),
    }


def _build(tmp_path: Path):
    builder = ResearchPanelBuilder(
        None,
        raw_root=tmp_path / "raw",
        normalized_root=tmp_path / "normalized",
        research_root=tmp_path / "research",
    )
    rows = [
        _row(date(2020, 1, 1), "security-sse"),
        _row(date(2023, 12, 31), "security-szse"),
        _row(date(2024, 1, 1), "security-sse"),
        _row(date(2025, 12, 31), "security-szse"),
        _row(date(2026, 1, 1), "security-sse"),
        _row(date(2026, 6, 30), "security-szse"),
        _row(date(2022, 5, 5), "security-missing"),
        _row(date(2022, 5, 6), "security-sse", high=8.0, low=12.0),
        _row(
            date(2022, 5, 7),
            "security-sse",
            eligibility=ResearchEligibility.EXPERIMENTAL.value,
        ),
    ]
    result = builder._build_fixture_from_rows(  # noqa: SLF001 - explicit test-only fixture
        rows,
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_as_of="2026-09-01T00:00:00+00:00",
        source_canonical_run_id=CANONICAL_RUN_ID,
        source_readmodel_contract_version="readmodel-v1",
        source_snapshot_manifest_hash="a" * 64,
        source_snapshot_semantic_hash="b" * 64,
        identity_view=_identity_view(),
        build_timestamp="2026-09-12T00:00:00+00:00",
    )
    return builder, result, rows


def test_boundaries_disabled_rows_and_replay_are_deterministic(tmp_path: Path) -> None:
    builder, first, _ = _build(tmp_path)
    manifest_path = tmp_path / "research" / first.manifest_uri
    reader = ResearchPanelReader.from_manifest(manifest_path, allow_test_fixture=True)

    development = reader.load_security_daily(split=ResearchSplit.DEVELOPMENT)
    validation = reader.load_security_daily(split="validation_a")
    holdout = reader.load_security_daily(split="holdout")
    disabled = reader.load_disabled_security_daily()

    assert development.height == 2
    assert validation.height == 2
    assert holdout.height == 2
    assert set(development.get_column("research_split").to_list()) == {"development"}
    assert set(holdout.get_column("trade_date").to_list()) == {
        date(2026, 1, 1),
        date(2026, 6, 30),
    }
    assert disabled.height == 3
    assert set(disabled.get_column("research_eligibility").to_list()) == {
        ResearchEligibility.DISABLED_UNRESOLVED.value,
        ResearchEligibility.EXPERIMENTAL.value,
    }
    assert disabled.filter(pl.col("research_exclusion_reason") == "identity_unresolved").height == 1
    assert disabled.filter(pl.col("research_exclusion_reason") == "invalid_ohlc").height == 1
    assert disabled.filter(pl.col("research_exclusion_reason") == "upstream_unresolved").height == 1
    assert development.get_column("pre_close").null_count() == development.height
    assert "holdout" not in development.get_column("research_split").to_list()

    replay = builder._build_fixture_from_rows(  # noqa: SLF001 - explicit test-only fixture
        _build(tmp_path)[2],
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_as_of="2026-09-01T00:00:00+00:00",
        source_canonical_run_id=CANONICAL_RUN_ID,
        source_readmodel_contract_version="readmodel-v1",
        source_snapshot_manifest_hash="a" * 64,
        source_snapshot_semantic_hash="b" * 64,
        identity_view=_identity_view(),
        build_timestamp="2026-09-12T00:00:00+00:00",
    )
    assert first.content_hash == replay.content_hash
    assert first.manifest_hash == replay.manifest_hash
    assert replay.idempotent_replay is True

    assert reader.manifest.price_basis == "UNADJUSTED_CANONICAL"
    assert reader.manifest.universe_basis == "OBSERVED_DAILY_BAR_UNIVERSE"
    assert reader.manifest.index_panel_state == "DISABLED_UNVERIFIED_INDEX_IDENTITY"
    assert reader.manifest.feature_run_id is None


def test_reader_requires_explicit_split_and_rejects_cross_split_range(tmp_path: Path) -> None:
    _, result, _ = _build(tmp_path)
    manifest_path = tmp_path / "research" / result.manifest_uri

    with pytest.raises(TypeError):
        load_research_security_daily(manifest_path)  # type: ignore[call-arg]

    with pytest.raises(ResearchManifestError, match="test-only"):
        load_research_security_daily(manifest_path, split="development")

    reader = ResearchPanelReader.from_manifest(manifest_path, allow_test_fixture=True)
    with pytest.raises(ResearchReaderError, match="crosses"):
        reader.load_security_daily(split="development", start="2019-12-31")
    with pytest.raises(ResearchReaderError, match="unknown research fields"):
        reader.load_security_daily(
            split="development",
            columns=["close", "ALL_A_SHARES"],
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("price_basis", "ADJUSTED"),
        ("universe_basis", "ALL_A_SHARES"),
        ("coverage_state", CoverageState.PARTIAL_OBSERVED_DAILY_BAR_COVERAGE.value),
    ],
)
def test_reader_fails_closed_on_semantic_widening(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    _, result, _ = _build(tmp_path)
    manifest_path = tmp_path / "research" / result.manifest_uri
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload[field] = replacement
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    if field == "coverage_state":
        reader = ResearchPanelReader.from_manifest(manifest_path, allow_test_fixture=True)
        with pytest.raises(ResearchReaderError, match="coverage_state"):
            reader.load_security_daily(split="development")
    else:
        with pytest.raises(ResearchManifestError):
            ResearchPanelReader.from_manifest(manifest_path, allow_test_fixture=True)


def test_split_boundaries_and_identity_overlap_fail_closed() -> None:
    assert assign_research_split("2020-01-01") is ResearchSplit.DEVELOPMENT
    assert assign_research_split("2023-12-31") is ResearchSplit.DEVELOPMENT
    assert assign_research_split("2024-01-01") is ResearchSplit.VALIDATION_A
    assert assign_research_split("2025-12-31") is ResearchSplit.VALIDATION_A
    assert assign_research_split("2026-01-01") is ResearchSplit.HOLDOUT
    assert assign_research_split("2026-06-30") is ResearchSplit.HOLDOUT
    assert assign_research_split("2019-12-31") is ResearchSplit.WARMUP
    assert assign_research_split("2026-07-01") is ResearchSplit.OUTSIDE_WINDOW

    with pytest.raises(Exception, match="overlapping"):
        IdentityView.from_rows(
            [
                {
                    "security_id": "s",
                    "symbol": "600000",
                    "exchange": "SSE",
                    "valid_from": "2020-01-01",
                    "valid_to": "2021-01-01",
                },
                {
                    "security_id": "s",
                    "symbol": "600001",
                    "exchange": "SSE",
                    "valid_from": "2020-06-01",
                },
            ],
            version="bad-v1",
        )


def test_builder_rejects_pit_violation_and_duplicate_primary_key(tmp_path: Path) -> None:
    builder = ResearchPanelBuilder(
        None,
        raw_root=tmp_path / "raw",
        normalized_root=tmp_path / "normalized",
        research_root=tmp_path / "research",
    )
    row = _row(date(2022, 5, 5), "security-sse")
    common = {
        "source_snapshot_id": SNAPSHOT_ID,
        "source_canonical_run_id": CANONICAL_RUN_ID,
        "source_readmodel_contract_version": "readmodel-v1",
        "source_snapshot_manifest_hash": "a" * 64,
        "source_snapshot_semantic_hash": "b" * 64,
        "identity_view": _identity_view(),
        "build_timestamp": "2026-09-12T00:00:00+00:00",
    }
    with pytest.raises(ResearchPanelError, match="PIT"):
        builder._build_fixture_from_rows(  # noqa: SLF001 - explicit test-only fixture
            [row],
            source_snapshot_as_of="2026-06-01T00:00:00+00:00",
            **common,
        )
    with pytest.raises(ResearchPanelError, match="duplicate research primary key"):
        builder._build_fixture_from_rows(  # noqa: SLF001 - explicit test-only fixture
            [row, dict(row)],
            source_snapshot_as_of="2026-09-01T00:00:00+00:00",
            **common,
        )


def test_published_machine_contract_matches_python_contract() -> None:
    contract_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "r1_research_contract_20260912.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["contract_version"] == "research-v1"
    assert contract["dataset_name"] == "research_security_daily"
    assert contract["eligibility"]["RESEARCH_DISABLED_UNRESOLVED"]["default_reader"] is False
    assert contract["semantic_constraints"]["price_basis"] == "UNADJUSTED_CANONICAL"
    assert contract["semantic_constraints"]["universe_basis"] == "OBSERVED_DAILY_BAR_UNIVERSE"
    assert contract["index_panel"]["state"] == "DISABLED_UNVERIFIED_INDEX_IDENTITY"
    assert "source_snapshot_as_of" in contract["manifest_required_fields"]


def test_unverified_rows_cannot_mint_authoritative_manifest(tmp_path: Path) -> None:
    builder = ResearchPanelBuilder(
        None,
        raw_root=tmp_path / "raw",
        normalized_root=tmp_path / "normalized",
        research_root=tmp_path / "research",
    )
    identity_view = _identity_view()
    projected = builder._project_rows(  # noqa: SLF001 - inspect publication boundary
        [_row(date(2022, 5, 5), "security-sse")],
        source_snapshot_id=SNAPSHOT_ID,
        source_snapshot_as_of=AVAILABLE_AT,
        source_canonical_run_id=CANONICAL_RUN_ID,
        source_readmodel_contract_version="readmodel-v1",
        identity_view=identity_view,
    )
    with pytest.raises(ResearchPanelError, match="verified identity"):
        builder._publish(  # noqa: SLF001 - inspect publication boundary
            projected,
            source_snapshot_id=SNAPSHOT_ID,
            source_snapshot_as_of=AVAILABLE_AT,
            source_canonical_run_id=CANONICAL_RUN_ID,
            source_readmodel_contract_version="readmodel-v1",
            source_snapshot_manifest_hash="a" * 64,
            source_snapshot_semantic_hash="b" * 64,
            identity_view=identity_view,
            build_timestamp=AVAILABLE_AT,
            coverage_state=CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
        )
    assert not (tmp_path / "research").exists()
    assert not hasattr(builder, "build_from_verified_rows")


def test_typed_numeric_violation_blocks_the_whole_fixture_build(tmp_path: Path) -> None:
    builder = ResearchPanelBuilder(
        None,
        raw_root=tmp_path / "raw",
        normalized_root=tmp_path / "normalized",
        research_root=tmp_path / "research",
    )
    row = _row(date(2022, 5, 5), "security-sse")
    row["open"] = "10.0"
    with pytest.raises(ResearchPanelError, match="typed numeric"):
        builder._build_fixture_from_rows(  # noqa: SLF001 - explicit test-only fixture
            [row],
            source_snapshot_id=SNAPSHOT_ID,
            source_snapshot_as_of="2026-09-01T00:00:00+00:00",
            source_canonical_run_id=CANONICAL_RUN_ID,
            source_readmodel_contract_version="readmodel-v1",
            source_snapshot_manifest_hash="a" * 64,
            source_snapshot_semantic_hash="b" * 64,
            identity_view=_identity_view(),
            build_timestamp="2026-09-12T00:00:00+00:00",
        )
    assert not (tmp_path / "research").exists()
