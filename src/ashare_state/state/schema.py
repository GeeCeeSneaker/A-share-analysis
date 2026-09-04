"""CR-6 versioned typed State artifact schemas."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

__all__ = [
    "FINDING_CLASSES",
    "MARKET_STATE_COLUMNS",
    "STATE_ARTIFACT_NAMES",
    "STATE_ENUM_VALUES",
    "STATE_EVIDENCE_FEATURES",
    "STATE_FINDING_COLUMNS",
    "StateSchemaError",
    "frame_for_artifact",
    "state_artifact_columns",
    "state_artifact_schema",
]


STATE_ARTIFACT_NAMES = ("market_daily_state", "state_findings")

STATE_EVIDENCE_FEATURES = (
    "observed_security_count",
    "valid_raw_return_count",
    "advancer_count",
    "decliner_count",
    "unchanged_count",
    "advancer_ratio_observed",
    "mean_raw_return_observed",
    "median_raw_return_observed",
    "valid_ma20_count",
    "pct_above_ma20_observed",
    "valid_mom20_count",
    "pct_positive_mom20_observed",
)

MARKET_STATE_COLUMNS = (
    "trade_date",
    "source_feature_run_id",
    "source_snapshot_id",
    "source_canonical_run_id",
    "state_run_id",
    "state_set_id",
    "state_contract_version",
    "state_available_at",
    "source_feature_input_lineage_hash",
    "input_lineage_hash",
    "universe_rule_id",
    "evidence_observed_security_count",
    "evidence_valid_raw_return_count",
    "evidence_advancer_count",
    "evidence_decliner_count",
    "evidence_unchanged_count",
    "evidence_advancer_ratio_observed",
    "evidence_mean_raw_return_observed",
    "evidence_median_raw_return_observed",
    "evidence_valid_ma20_count",
    "evidence_pct_above_ma20_observed",
    "evidence_valid_mom20_count",
    "evidence_pct_positive_mom20_observed",
    "return_center_state",
    "daily_participation_state",
    "trend_participation_state",
    "market_structure_state",
)

STATE_FINDING_COLUMNS = (
    "trade_date",
    "state_name",
    "finding_class",
    "detail_json",
)

STATE_ENUM_VALUES = {
    "return_center_state": (
        "POSITIVE_CENTER",
        "NEGATIVE_CENTER",
        "MIXED_CENTER",
        "UNKNOWN",
    ),
    "daily_participation_state": (
        "ADVANCE_DOMINANT",
        "DECLINE_DOMINANT",
        "BALANCED",
        "UNKNOWN",
    ),
    "trend_participation_state": (
        "BROAD_POSITIVE",
        "BROAD_NEGATIVE",
        "MIXED",
        "UNKNOWN",
    ),
    "market_structure_state": (
        "BROAD_ADVANCE",
        "BROAD_DECLINE",
        "POSITIVE_MIXED_PARTICIPATION",
        "NEGATIVE_MIXED_PARTICIPATION",
        "MIXED",
        "UNKNOWN",
    ),
}

FINDING_CLASSES = (
    "STATE_INPUT_NULL",
    "STATE_INPUT_EMPTY_DENOMINATOR",
    "STATE_INPUT_INVARIANT_VIOLATION",
    "STATE_RULE_UNAVAILABLE",
)


class StateSchemaError(ValueError):
    """A State artifact name or physical schema is not the V1 contract."""


def _schemas() -> dict[str, pl.Schema]:
    return {
        "market_daily_state": pl.Schema(
            [
                ("trade_date", pl.Date()),
                ("source_feature_run_id", pl.String()),
                ("source_snapshot_id", pl.String()),
                ("source_canonical_run_id", pl.String()),
                ("state_run_id", pl.String()),
                ("state_set_id", pl.String()),
                ("state_contract_version", pl.String()),
                ("state_available_at", pl.Datetime(time_unit="us", time_zone="UTC")),
                ("source_feature_input_lineage_hash", pl.String()),
                ("input_lineage_hash", pl.String()),
                ("universe_rule_id", pl.String()),
                ("evidence_observed_security_count", pl.Int64()),
                ("evidence_valid_raw_return_count", pl.Int64()),
                ("evidence_advancer_count", pl.Int64()),
                ("evidence_decliner_count", pl.Int64()),
                ("evidence_unchanged_count", pl.Int64()),
                ("evidence_advancer_ratio_observed", pl.Float64()),
                ("evidence_mean_raw_return_observed", pl.Float64()),
                ("evidence_median_raw_return_observed", pl.Float64()),
                ("evidence_valid_ma20_count", pl.Int64()),
                ("evidence_pct_above_ma20_observed", pl.Float64()),
                ("evidence_valid_mom20_count", pl.Int64()),
                ("evidence_pct_positive_mom20_observed", pl.Float64()),
                ("return_center_state", pl.String()),
                ("daily_participation_state", pl.String()),
                ("trend_participation_state", pl.String()),
                ("market_structure_state", pl.String()),
            ]
        ),
        "state_findings": pl.Schema(
            [
                ("trade_date", pl.Date()),
                ("state_name", pl.String()),
                ("finding_class", pl.String()),
                ("detail_json", pl.String()),
            ]
        ),
    }


_SCHEMAS = _schemas()


def state_artifact_columns(name: str) -> tuple[str, ...]:
    if name == "market_daily_state":
        return MARKET_STATE_COLUMNS
    if name == "state_findings":
        return STATE_FINDING_COLUMNS
    raise StateSchemaError(f"unknown State artifact {name!r}")


def state_artifact_schema(name: str) -> pl.Schema:
    try:
        return _SCHEMAS[name]
    except KeyError as exc:
        raise StateSchemaError(f"unknown State artifact {name!r}") from exc


def frame_for_artifact(name: str, rows: Sequence[Mapping[str, object]]) -> pl.DataFrame:
    columns = state_artifact_columns(name)
    schema = state_artifact_schema(name)
    aligned = [{column: row.get(column) for column in columns} for row in rows]
    return pl.DataFrame(aligned, schema=schema)
