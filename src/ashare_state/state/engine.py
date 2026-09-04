"""CR-6 deterministic descriptive State computation.

This module consumes only a VerifiedFeatureRun market projection. It does
not know how Feature values are calculated and has no access to providers,
raw/canonical/snapshot/readmodel storage, future labels, or strategy code.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ashare_state.features.models import VerifiedFeatureRun, canonical_json, semantic_hash
from ashare_state.state.models import StateBuilderError, StateFinding, state_input_lineage_hash
from ashare_state.state.registry import StateExecutionPlan, StateSet, compile_state_execution_plan
from ashare_state.state.schema import STATE_EVIDENCE_FEATURES

__all__ = [
    "ComputedStateSet",
    "STATE_EVIDENCE_FEATURES",
    "StateEngineError",
    "compute_state_set",
]


class StateEngineError(StateBuilderError):
    """The verified Feature projection violates the State input contract."""


@dataclass(frozen=True)
class ComputedStateSet:
    state_rows: tuple[dict[str, Any], ...]
    finding_rows: tuple[dict[str, Any], ...]

    @property
    def state_semantic_hash(self) -> str:
        return semantic_hash(self.state_rows)

    @property
    def finding_set_hash(self) -> str:
        return semantic_hash(self.finding_rows)


def _number(row: Mapping[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise StateEngineError(f"State input {name} has an invalid numeric type: {value!r}")
    converted = float(value)
    if not math.isfinite(converted):
        raise StateEngineError(f"State input {name} is non-finite")
    return converted


def _count(row: Mapping[str, Any], name: str) -> int | None:
    value = row.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateEngineError(f"State input {name} has an invalid count type: {value!r}")
    return value


def _finding(
    trade_date: date,
    state_name: str,
    finding_class: str,
    detail: Mapping[str, Any],
) -> dict[str, Any]:
    return StateFinding(
        trade_date=trade_date,
        state_name=state_name,
        finding_class=finding_class,
        detail_json=canonical_json(detail),
    ).as_dict()


def _return_center(
    row: Mapping[str, Any],
    trade_date: date,
    findings: list[dict[str, Any]],
) -> str:
    mean = _number(row, "mean_raw_return_observed")
    median = _number(row, "median_raw_return_observed")
    if mean is None or median is None:
        findings.append(
            _finding(
                trade_date,
                "return_center_state",
                "STATE_INPUT_NULL",
                {
                    "inputs": [
                        name
                        for name in ("mean_raw_return_observed", "median_raw_return_observed")
                        if row.get(name) is None
                    ]
                },
            )
        )
        return "UNKNOWN"
    if mean > 0 and median > 0:
        return "POSITIVE_CENTER"
    if mean < 0 and median < 0:
        return "NEGATIVE_CENTER"
    return "MIXED_CENTER"


def _daily_participation(
    row: Mapping[str, Any],
    trade_date: date,
    findings: list[dict[str, Any]],
) -> str:
    names = (
        "valid_raw_return_count",
        "advancer_count",
        "decliner_count",
        "unchanged_count",
    )
    counts = {name: _count(row, name) for name in names}
    missing = [name for name, value in counts.items() if value is None]
    if missing:
        findings.append(
            _finding(
                trade_date,
                "daily_participation_state",
                "STATE_INPUT_NULL",
                {"inputs": missing},
            )
        )
        return "UNKNOWN"

    valid = counts["valid_raw_return_count"]
    advancers = counts["advancer_count"]
    decliners = counts["decliner_count"]
    unchanged = counts["unchanged_count"]
    assert valid is not None
    assert advancers is not None
    assert decliners is not None
    assert unchanged is not None
    if min(valid, advancers, decliners, unchanged) < 0:
        raise StateEngineError("daily participation counts must be non-negative")
    if advancers + decliners + unchanged != valid:
        raise StateEngineError(
            "daily participation count invariant violated: "
            "advancer + decliner + unchanged must equal valid"
        )
    if valid <= 0:
        findings.append(
            _finding(
                trade_date,
                "daily_participation_state",
                "STATE_INPUT_EMPTY_DENOMINATOR",
                {"input": "valid_raw_return_count", "value": valid},
            )
        )
        return "UNKNOWN"

    ratio = row.get("advancer_ratio_observed")
    if ratio is not None:
        observed_ratio = _number(row, "advancer_ratio_observed")
        assert observed_ratio is not None
        if observed_ratio != advancers / valid:
            raise StateEngineError(
                "advancer_ratio_observed does not equal advancer_count / valid_raw_return_count"
            )
    if advancers > decliners:
        return "ADVANCE_DOMINANT"
    if decliners > advancers:
        return "DECLINE_DOMINANT"
    return "BALANCED"


def _trend_participation(
    row: Mapping[str, Any],
    trade_date: date,
    findings: list[dict[str, Any]],
) -> str:
    names = (
        "valid_ma20_count",
        "pct_above_ma20_observed",
        "valid_mom20_count",
        "pct_positive_mom20_observed",
    )
    values = {name: row.get(name) for name in names}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        findings.append(
            _finding(
                trade_date,
                "trend_participation_state",
                "STATE_INPUT_NULL",
                {"inputs": missing},
            )
        )
        return "UNKNOWN"

    ma_count = _count(row, "valid_ma20_count")
    mom_count = _count(row, "valid_mom20_count")
    ma_ratio = _number(row, "pct_above_ma20_observed")
    mom_ratio = _number(row, "pct_positive_mom20_observed")
    assert ma_count is not None
    assert mom_count is not None
    assert ma_ratio is not None
    assert mom_ratio is not None
    if ma_count <= 0 or mom_count <= 0:
        findings.append(
            _finding(
                trade_date,
                "trend_participation_state",
                "STATE_INPUT_EMPTY_DENOMINATOR",
                {
                    "inputs": [
                        name
                        for name, count in (
                            ("valid_ma20_count", ma_count),
                            ("valid_mom20_count", mom_count),
                        )
                        if count <= 0
                    ]
                },
            )
        )
        return "UNKNOWN"
    if ma_ratio > 1 or ma_ratio < 0 or mom_ratio > 1 or mom_ratio < 0:
        raise StateEngineError("trend participation ratios must be within [0, 1]")
    if ma_ratio > 0.5 and mom_ratio > 0.5:
        return "BROAD_POSITIVE"
    if ma_ratio < 0.5 and mom_ratio < 0.5:
        return "BROAD_NEGATIVE"
    return "MIXED"


def _market_structure(
    dimensions: Mapping[str, str],
) -> str:
    if any(
        dimensions[name] == "UNKNOWN"
        for name in (
            "return_center_state",
            "daily_participation_state",
            "trend_participation_state",
        )
    ):
        return "UNKNOWN"
    center = dimensions["return_center_state"]
    daily = dimensions["daily_participation_state"]
    trend = dimensions["trend_participation_state"]
    if (
        center == "POSITIVE_CENTER"
        and daily == "ADVANCE_DOMINANT"
        and trend == "BROAD_POSITIVE"
    ):
        return "BROAD_ADVANCE"
    if (
        center == "NEGATIVE_CENTER"
        and daily == "DECLINE_DOMINANT"
        and trend == "BROAD_NEGATIVE"
    ):
        return "BROAD_DECLINE"
    if center == "POSITIVE_CENTER":
        return "POSITIVE_MIXED_PARTICIPATION"
    if center == "NEGATIVE_CENTER":
        return "NEGATIVE_MIXED_PARTICIPATION"
    return "MIXED"


def _validate_row_identity(
    row: Mapping[str, Any],
    feature_run: VerifiedFeatureRun,
) -> tuple[date, datetime, str, str]:
    trade_date = row.get("trade_date")
    if not isinstance(trade_date, date):
        raise StateEngineError("Feature market row trade_date must be a date")
    available_at = row.get("feature_available_at")
    if not isinstance(available_at, datetime) or available_at.tzinfo is None:
        raise StateEngineError("Feature market row feature_available_at must be timezone-aware")
    source_snapshot_id = row.get("source_snapshot_id")
    if source_snapshot_id != feature_run.snapshot_id:
        raise StateEngineError("Feature market row carries a foreign source_snapshot_id")
    feature_set_id = row.get("feature_set_id")
    if feature_set_id != feature_run.feature_set_id:
        raise StateEngineError("Feature market row carries a foreign feature_set_id")
    lineage = row.get("input_lineage_hash")
    if not isinstance(lineage, str) or len(lineage) != 64:
        raise StateEngineError("Feature market row input_lineage_hash is not a SHA-256 value")
    universe_rule_id = row.get("universe_rule_id")
    if not isinstance(universe_rule_id, str) or not universe_rule_id:
        raise StateEngineError("Feature market row universe_rule_id is missing")
    return trade_date, available_at, str(source_snapshot_id), str(universe_rule_id)


_HANDLER_BY_NAME = {
    "return_center": _return_center,
    "daily_participation": _daily_participation,
    "trend_participation": _trend_participation,
}


def compute_state_set(
    feature_run: VerifiedFeatureRun,
    *,
    state_run_id: str,
    state_set: StateSet,
) -> ComputedStateSet:
    """Compute the exact V1 State set from one verified Feature run."""
    if not isinstance(feature_run, VerifiedFeatureRun):
        raise StateEngineError("compute_state_set requires a VerifiedFeatureRun")
    plan: StateExecutionPlan
    try:
        plan = compile_state_execution_plan(state_set)
    except Exception as exc:
        raise StateEngineError(f"State Registry cannot be honestly executed: {exc}") from exc

    ordered_rows = sorted(
        (dict(row) for row in feature_run.market_rows),
        key=lambda row: row.get("trade_date"),
    )
    seen_dates: set[date] = set()
    state_rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for row in ordered_rows:
        trade_date, available_at, source_snapshot_id, universe_rule_id = _validate_row_identity(
            row, feature_run
        )
        if trade_date in seen_dates:
            raise StateEngineError("Feature market rows have duplicate trade_date keys")
        seen_dates.add(trade_date)
        dimensions: dict[str, str] = {}
        row_findings: list[dict[str, Any]] = []
        for entry in plan.entries:
            if entry.handler == "market_structure":
                dimensions[entry.spec.state_name] = _market_structure(dimensions)
            else:
                handler = _HANDLER_BY_NAME[entry.handler]
                dimensions[entry.spec.state_name] = handler(row, trade_date, row_findings)

        evidence = {name: row.get(name) for name in STATE_EVIDENCE_FEATURES}
        state_row = {
            "trade_date": trade_date,
            "source_feature_run_id": feature_run.feature_run_id,
            "source_snapshot_id": source_snapshot_id,
            "source_canonical_run_id": feature_run.canonical_run_id,
            "state_run_id": state_run_id,
            "state_set_id": state_set.state_set_id,
            "state_contract_version": state_set.contract_version,
            "state_available_at": available_at,
            "source_feature_input_lineage_hash": row["input_lineage_hash"],
            "universe_rule_id": universe_rule_id,
            "evidence_observed_security_count": evidence["observed_security_count"],
            "evidence_valid_raw_return_count": evidence["valid_raw_return_count"],
            "evidence_advancer_count": evidence["advancer_count"],
            "evidence_decliner_count": evidence["decliner_count"],
            "evidence_unchanged_count": evidence["unchanged_count"],
            "evidence_advancer_ratio_observed": evidence["advancer_ratio_observed"],
            "evidence_mean_raw_return_observed": evidence["mean_raw_return_observed"],
            "evidence_median_raw_return_observed": evidence["median_raw_return_observed"],
            "evidence_valid_ma20_count": evidence["valid_ma20_count"],
            "evidence_pct_above_ma20_observed": evidence["pct_above_ma20_observed"],
            "evidence_valid_mom20_count": evidence["valid_mom20_count"],
            "evidence_pct_positive_mom20_observed": evidence["pct_positive_mom20_observed"],
            "return_center_state": dimensions["return_center_state"],
            "daily_participation_state": dimensions["daily_participation_state"],
            "trend_participation_state": dimensions["trend_participation_state"],
            "market_structure_state": dimensions["market_structure_state"],
        }
        state_row["input_lineage_hash"] = state_input_lineage_hash(
            source_feature_run_id=feature_run.feature_run_id,
            trade_date=trade_date,
            source_feature_input_lineage_hash=row["input_lineage_hash"],
            source_feature_available_at=available_at,
            evidence=evidence,
            state_registry_version=state_set.state_registry_version,
            state_registry_hash=state_set.registry_hash,
            state_rule_ids=tuple(spec.rule_id for spec in plan.declarations),
        )
        state_rows.append(state_row)
        findings.extend(row_findings)

    findings.sort(
        key=lambda row: (
            row["trade_date"],
            row["state_name"],
            row["finding_class"],
            row["detail_json"],
        )
    )
    return ComputedStateSet(tuple(state_rows), tuple(findings))
