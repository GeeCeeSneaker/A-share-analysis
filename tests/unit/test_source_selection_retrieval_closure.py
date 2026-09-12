"""Regression checks for the minimal source-selection/retrieval closure."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_CONTRACT = (
    _ROOT / "docs" / "provider_verification" / "source_selection_retrieval_closure_20260912.json"
)


def _load_contract() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_contract_is_pinned_to_merged_main_and_has_no_execution_authority():
    contract = _load_contract()

    assert contract["base_main_commit"] == "538bf8ea1f62cac4461215ac316484acf078b09a"
    assert contract["status"] == "CLOSURE_DESIGN_ONLY_NOT_ACTIVE"
    assert contract["recommendation"] == "SOURCE_SELECTION_STILL_UNRESOLVED"
    assert contract["formal_run_authorized"] is False
    assert contract["production_authorized"] is False
    assert contract["runtime_policy_changed"] is False
    assert contract["provider_calls_in_this_closure"] == 0


def test_contract_has_exactly_the_five_scheduler_capabilities():
    contract = _load_contract()

    assert [item["id"] for item in contract["capabilities"]] == [
        "security_lifecycle_pit",
        "historical_status_by_day",
        "corporate_actions",
        "bj_identity_mapping",
        "history_fixture",
    ]


def test_every_source_class_binds_use_terms_retrieval_and_minimum_artifact():
    contract = _load_contract()
    required_use = {
        "retrieval",
        "local_retention",
        "parsing",
        "derived_facts",
        "redistribution",
    }
    required_retrieval = {
        "canonical_locators",
        "request_identity",
        "stable_record_identity",
        "representation",
        "cache_and_version",
        "availability_and_pit",
        "fail_closed",
    }

    for source in contract["source_classes"]:
        assert source["selection_status"] in {
            "SELECTED_PRIMARY",
            "SELECTED_SUPPORTING",
            "NOT_SELECTED",
        }
        assert required_use <= source["exact_project_use"].keys()
        assert source["terms_or_authorization_basis"]["project_decision_status"]
        assert required_retrieval <= source["retrieval_contract"].keys()
        assert source["retrieval_contract"]["representation"]["allowed"] is not None
        assert source["minimum_retained_artifact"]
        assert source["capability_impact"]


def test_minimal_selection_excludes_market_data_and_cninfo():
    contract = _load_contract()
    sources = {source["id"]: source for source in contract["source_classes"]}
    selected = {
        source["id"]
        for source in contract["source_classes"]
        if source["selection_status"].startswith("SELECTED")
    }

    assert "exchange_quotation_or_processed_market_data" not in selected
    assert "cninfo_original_issuer_document_transport" not in selected
    assert (
        sources["exchange_quotation_or_processed_market_data"]["terms_or_authorization_basis"][
            "project_decision_status"
        ]
        == "NOT_SELECTED"
    )
    assert sources["cninfo_original_issuer_document_transport"]["selection_status"] == (
        "NOT_SELECTED"
    )


def test_selected_classes_remain_blocked_until_class_decisions_are_resolved():
    contract = _load_contract()

    for source in contract["source_classes"]:
        if source["selection_status"].startswith("SELECTED"):
            assert source["terms_or_authorization_basis"]["project_decision_status"] == (
                "STILL_UNRESOLVED"
            )

    assert all(item["status"] == "BLOCKED" for item in contract["capabilities"])


def test_history_fixture_keeps_300104_inapplicable_and_candidates_deferred():
    fixture = next(
        item for item in _load_contract()["capabilities"] if item["id"] == "history_fixture"
    )

    assert fixture["current_fixture_decision"] == {
        "300104.SZ": "INAPPLICABLE_FOR_2020_BASELINE",
        "601558.SH": "PROPOSED_NOT_ACTIVATED",
        "600068.SH": "UNACTIVATED_ALTERNATIVE_ONLY",
    }
    assert "exchange_quotation_or_processed_market_data" not in fixture["selected_source_classes"]
    assert "global 2020 baseline" in " ".join(_load_contract()["global_invariants"]).lower()


def test_capability_source_references_are_declared_source_classes():
    contract = _load_contract()
    source_ids = {source["id"] for source in contract["source_classes"]}

    for capability in contract["capabilities"]:
        assert set(capability["selected_source_classes"]) <= source_ids
        assert set(capability["retrieval_contract_refs"]) <= source_ids
        assert set(capability["minimum_artifact_refs"]) <= source_ids

    assert all(
        source["id"] != "exchange_quotation_or_processed_market_data"
        for capability in contract["capabilities"]
        for source in contract["source_classes"]
        if source["id"] in capability["selected_source_classes"]
    )
