"""Offline regression checks for the CR-7 historical-materialization design."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from ashare_state.research import ResearchSplit, assign_research_split

_ROOT = Path(__file__).parents[2]
_CONTRACT_PATH = (
    _ROOT / "docs" / "research" / "cr7_historical_materialization_contract_20260913.json"
)


def _load_contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def _object_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        for child in value.values():
            keys.update(_object_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_object_keys(child))
        return keys
    return set()


def _month_keys(start: date, end: date) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    cursor = start.replace(day=1)
    while cursor <= end:
        keys.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return keys


def test_contract_is_pinned_to_merged_main_and_has_no_execution_authority() -> None:
    contract = _load_contract()

    assert contract["base_main_commit"] == "53257c36e8ada5576f5d2dfce0947710ee24694c"
    assert contract["status"] == "DESIGN_ONLY_NOT_ACTIVE"
    assert contract["decision"] == "DESIGN_PRECHECK_ONLY"
    assert all(value is False for value in contract["authorization"].values())
    assert contract["target_dataset"] == "research_security_daily"


def test_window_and_split_plan_are_inclusive_and_have_78_logical_months() -> None:
    contract = _load_contract()
    window = contract["target_window"]
    assert window == {
        "start": "2020-01-01",
        "end": "2026-06-30",
        "inclusive": True,
        "pre_window_data": "WARMUP_OR_PIT_ONLY_NOT_A_RESEARCH_PARTITION",
    }

    splits = contract["research_splits"]
    assert list(splits) == ["development", "validation_a", "holdout"]
    expected_months = sum(
        len(
            _month_keys(
                date.fromisoformat(details["start"]),
                date.fromisoformat(details["end"]),
            )
        )
        for details in splits.values()
    )
    assert expected_months == 78
    partition = contract["partition_contract"]
    assert partition["expected_logical_partition_count"] == expected_months
    assert partition["logical_partition_key"] == [
        "research_split",
        "calendar_year",
        "calendar_month",
    ]
    assert partition["physical_artifact_key"][0] == "research_route"
    assert partition["split_mixing"] == "forbidden"


def test_fixture_covers_boundaries_and_keeps_unresolved_rows_disabled() -> None:
    contract = _load_contract()
    fixture = contract["bounded_acceptance_fixture"]
    rows = fixture["rows"]
    boundary_dates = {
        "2020-01-01",
        "2023-12-31",
        "2024-01-01",
        "2025-12-31",
        "2026-01-01",
        "2026-06-30",
    }
    assert boundary_dates <= {row["trade_date"] for row in rows}

    for row in rows:
        if row["route"] == "research_enabled":
            assert assign_research_split(row["trade_date"]).value == row["research_split"]
        else:
            assert row["route"] == "disabled"
            assert row["coverage_state"] == "UNRESOLVED_NOT_FOR_RESEARCH"
            assert row["research_exclusion_reason"]

    bse_rows = [row for row in rows if row["security_id"] == "fixture-bse-835185"]
    assert len(bse_rows) == 1
    assert bse_rows[0]["route"] == "disabled"
    assert bse_rows[0]["research_exclusion_reason"] == "bse_identity_boundary_unresolved"

    excluded = {row["trade_date"]: row["reason"] for row in fixture["excluded_rows"]}
    assert excluded == {
        "2019-12-31": "outside_research_window",
        "2026-07-01": "outside_research_window",
    }


def test_input_contract_requires_one_verified_snapshot_and_forbids_provider_bypass() -> None:
    contract = _load_contract()["input_contract"]
    assert contract["required_entrypoint"] == "ResearchPanelBuilder.build_from_readmodel"
    assert contract["source_kind"] == "VERIFIED_CR4_READMODEL"
    assert contract["single_snapshot_rule"] == "ONE_VERIFIED_READMODEL_SNAPSHOT_PER_MATERIALIZATION"
    assert {
        "source_snapshot_id",
        "source_snapshot_manifest_hash",
        "source_snapshot_semantic_hash",
        "source_canonical_run_id",
        "identity_view_hash",
        "identity_source_lineage_hash",
    } <= set(contract["required_source_provenance"])
    assert {
        "direct_provider_calls",
        "provider_credentials_or_sdk",
        "caller_claimed_snapshot_hashes",
        "symbol_or_exchange_inference_from_security_id",
    } <= set(contract["forbidden_inputs"])


def test_coverage_scenarios_aggregate_fail_closed() -> None:
    contract = _load_contract()["bounded_acceptance_fixture"]
    rank = {
        "OBSERVED_DAILY_BAR_COVERAGE": 0,
        "PARTIAL_OBSERVED_DAILY_BAR_COVERAGE": 1,
        "UNRESOLVED_NOT_FOR_RESEARCH": 2,
    }
    for scenario in contract["scenario_matrix"]:
        states = scenario["partition_states"]
        aggregate = max(states, key=rank.__getitem__)
        assert aggregate == scenario["aggregate_state"]
        if aggregate == "OBSERVED_DAILY_BAR_COVERAGE":
            assert scenario["ordinary_read"] == "allowed_after_commit"
        else:
            assert scenario["ordinary_read"] != "allowed_after_commit"

    coverage = _load_contract()["coverage_contract"]
    assert coverage["missing_row_semantics"].startswith("a_missing_bar_is_not")
    assert coverage["denominator_semantics"].endswith("not_all_a_shares")
    assert coverage["route_scope_rule"].startswith("coverage_is_aggregated_separately")
    assert coverage["dataset_aggregation_rule"].startswith(
        "the_enabled_route_materialization_state_is_the_worst_state"
    )


def test_idempotency_identity_excludes_wall_clock_and_has_deterministic_formula() -> None:
    contract = _load_contract()["replay_and_idempotency_contract"]
    fields = contract["identity_fields"]
    assert "build_timestamp" not in fields
    assert "source_snapshot_manifest_hash" in fields
    assert "identity_view_hash" in fields
    assert contract["canonical_json_rule"].startswith("UTF-8 JSON with sorted keys")
    assert contract["idempotency_key_formula"] == "sha256(canonical_json(materialization_identity))"
    assert contract["materialization_id_formula"] == "rhm-<full_lowercase_idempotency_key>"

    identity = {field: f"value-{index}" for index, field in enumerate(fields)}
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    first = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    second = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert first == second
    assert first == first.lower()

    assert "IDEMPOTENT_REPLAY" in contract["same_identity_rule"]
    assert "never last-write-wins" in contract["same_id_different_bytes_rule"]
    assert "timestamp_rule" in contract


def test_staging_contract_requires_marker_after_all_verification_steps() -> None:
    contract = _load_contract()["staging_and_failure_atomicity"]
    order = contract["write_order"]
    assert order.index("verify_single_source_snapshot_and_readmodel") < order.index(
        "write_partition_bytes_to_non_published_staging_paths"
    )
    assert order.index("recompute_inventory_and_aggregate_hashes") < order.index(
        "write_manifest_and_success_marker"
    )
    assert contract["publication_marker"] == "_SUCCESS.json"
    assert "only_after" in contract["publication_marker_rule"]
    assert "no_new_readable_materialization" in contract["failure_rule"]
    assert "same_identity" in contract["resume_rule"]


def test_evidence_contract_is_recomputable_and_raw_payload_stays_local() -> None:
    evidence = _load_contract()["evidence_contract"]
    required_manifest = {
        "materialization_id",
        "idempotency_key",
        "target_window",
        "source_snapshot_manifest_hash",
        "identity_source_lineage_hash",
        "partition_inventory",
        "partition_inventory_hash",
        "artifact_set_hash",
        "content_hash",
        "publication_state",
    }
    assert required_manifest <= set(evidence["manifest_required_fields"])
    assert {
        "uri",
        "row_count",
        "byte_size",
        "content_hash",
        "semantic_hash",
        "schema_hash",
        "coverage_state",
    } <= set(evidence["partition_inventory_fields"])
    assert {
        "research_split",
        "calendar_year",
        "calendar_month",
        "route_descriptors",
        "enabled_route_coverage_state",
        "diagnostic_route_coverage_states",
    } <= set(evidence["logical_partition_inventory_fields"])
    assert evidence["hash_rules"]["partition_content_hash"].startswith(
        "sha256_of_exact_parquet_bytes"
    )
    assert "raw_provider_payload" in evidence["hash_rules"]["hash_inputs_must_exclude"]
    assert evidence["local_evidence_only"].startswith("the design stores hashes")


def test_design_does_not_expand_bse_index_feature_or_formal_scope() -> None:
    contract = _load_contract()
    invariants = " ".join(contract["global_invariants"])
    assert "bse_mapping_is_not_activated" in invariants
    assert "ordinary_research_reads_never_include_disabled" in invariants
    assert "raw_unadjusted_price_basis_is_not_adjusted_or_total_return" in invariants
    assert contract["authorization"]["index_activation_authorized"] is False
    assert contract["authorization"]["cr5_feature_export_authorized"] is False
    assert contract["authorization"]["formal_run_authorized"] is False
    assert ResearchSplit.HOLDOUT.value == "holdout"


def test_contract_file_is_json_and_has_no_secret_like_fields() -> None:
    contract = _load_contract()
    assert json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    forbidden_keys = {"password", "cookie", "access_token", "secret_key", "token"}
    assert not forbidden_keys.intersection(_object_keys(contract))
    assert contract["bounded_acceptance_fixture"]["provider_calls"] == 0
