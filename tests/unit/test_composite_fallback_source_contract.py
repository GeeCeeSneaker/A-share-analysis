"""Regression checks for the design-only composite source contract."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_CONTRACT_DIR = _ROOT / "docs" / "provider_verification"
_CONTRACT = _CONTRACT_DIR / "composite_fallback_source_contract_20260912.json"


def _load_contract() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_contract_is_pinned_to_current_main_and_is_design_only():
    contract = _load_contract()

    assert contract["base_main_commit"] == "661dddfe7bba2f8ff13a3f7512bde4e1a15db383"
    assert contract["status"] == "DESIGN_ONLY_NOT_ACTIVE"
    assert contract["recommendation"] == "SOURCE_SELECTION_STILL_UNRESOLVED"
    assert contract["formal_run_authorized"] is False
    assert contract["production_authorized"] is False
    assert contract["runtime_policy_changed"] is False


def test_contract_has_exactly_the_five_scheduler_capabilities():
    contract = _load_contract()

    assert [capability["id"] for capability in contract["capabilities"]] == [
        "security_lifecycle_pit",
        "historical_status_by_day",
        "corporate_actions",
        "bj_identity_mapping",
        "history_fixture",
    ]


def test_each_matrix_row_has_required_contract_columns_and_is_blocked():
    contract = _load_contract()
    required = {
        "primary_source",
        "fallback_or_first_party_sources",
        "exact_fields",
        "pit_rule",
        "conflict_precedence",
        "evidence_contract",
        "implementation_impact",
    }

    for capability in contract["capabilities"]:
        assert required <= capability.keys()
        assert capability["primary_source"]
        assert capability["fallback_or_first_party_sources"]
        assert capability["exact_fields"]
        assert capability["pit_rule"]
        assert capability["conflict_precedence"]
        assert capability["evidence_contract"]
        assert capability["implementation_impact"]
        assert capability["activation_status"] == "BLOCKED"


def test_contract_preserves_fail_closed_and_no_silent_mapping_invariants():
    contract = _load_contract()
    invariants = " ".join(contract["global_invariants"])
    status = next(
        capability
        for capability in contract["capabilities"]
        if capability["id"] == "historical_status_by_day"
    )
    mapping = next(
        capability
        for capability in contract["capabilities"]
        if capability["id"] == "bj_identity_mapping"
    )

    assert "fail closed" in invariants
    assert "available_at <= as_of" in invariants
    assert "last-write-wins" in invariants
    assert (
        "never hides a mapping request or silently rewrites code_list"
        in mapping["evidence_contract"]["request_identity_rule"]
    )
    assert "Malformed or double-missing" in status["pit_rule"]


def test_history_fixture_is_deferred_and_does_not_relax_global_baseline():
    contract = _load_contract()
    fixture = next(
        capability
        for capability in contract["capabilities"]
        if capability["id"] == "history_fixture"
    )
    decision = fixture["evidence_contract"]["current_decision"]
    failure_rule = fixture["evidence_contract"]["failure_rule"]

    assert "601558.SH remains PROPOSED_NOT_ACTIVATED" in decision
    assert "600068.SH is an equally explicit alternative candidate" in decision
    assert "300104.SZ remains INAPPLICABLE_FOR_2020_BASELINE" in decision
    assert "do not modify the global 2020-01-01 baseline" in failure_rule


def test_license_compatibility_is_split_by_source_class():
    contract = _load_contract()
    compatibility = contract["license_and_usage_compatibility"]
    classes = {item["id"]: item for item in compatibility["source_classes"]}

    assert compatibility["status"] == "UNRESOLVED_PER_SOURCE_CLASS"
    assert {
        "exchange_announcement_disclosure_document",
        "bse_mapping_cutover_document",
        "exchange_corporate_action_record",
        "exchange_quotation_or_processed_market_data",
        "cninfo_original_issuer_document_transport",
    } <= classes.keys()
    assert classes["bse_mapping_cutover_document"]["license_decision"] == (
        "PROJECT_DECISION_REQUIRED"
    )
    market_data = classes["exchange_quotation_or_processed_market_data"]
    assert market_data["venue_decisions"]["BSE"] == "LICENSE_REQUIRED"
    assert (
        "must not be classified as licensed BSE 行情信息"
        in classes["bse_mapping_cutover_document"]["not_market_data_authority"]
    )


def test_sources_and_capability_rows_bind_class_specific_license_fields():
    contract = _load_contract()
    sources = {source["id"]: source for source in contract["sources"]}

    assert sources["exchange_lifecycle_events"]["source_class"] == (
        "exchange_announcement_disclosure_document"
    )
    assert sources["bse_code_mapping"]["source_class"] == "bse_mapping_cutover_document"
    assert sources["exchange_quotation_or_processed_market_data"]["license_decision"] == (
        "BLOCKED_PENDING_PER_VENUE_LICENSE_DECISION"
    )
    assert all("license_decision" in source for source in sources.values())
    assert all(
        "license_decision_class" in capability["evidence_contract"]
        or "license_decision_classes" in capability["evidence_contract"]
        for capability in contract["capabilities"]
    )
