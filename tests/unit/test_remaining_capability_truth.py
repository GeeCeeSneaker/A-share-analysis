"""Schema and boundary tests for the six-item capability closure bundle."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_BUNDLE = _ROOT / "docs" / "provider_verification" / "remaining_capability_truth_20260912.json"


def _load_bundle() -> dict:
    return json.loads(_BUNDLE.read_text(encoding="utf-8"))


def test_bundle_is_pinned_to_clean_main_and_has_no_execution_authority():
    bundle = _load_bundle()

    assert bundle["base_main_commit"] == "6ad53a84111fa9b8cc86276d4ed78c9b08f8e469"
    assert bundle["recommendation"] == "COMPOSITE/FALLBACK_SOURCE_REQUIRED"
    assert bundle["recommendation_is_diagnostic_only"] is True
    assert bundle["formal_run_authorized"] is False
    assert bundle["provider_calls_in_this_closure"] == 0
    assert bundle["golden_h1_baseline_mutated"] is False


def test_bundle_contains_exactly_the_six_scheduled_blockers():
    bundle = _load_bundle()

    assert [item["id"] for item in bundle["blockers"]] == [
        "status-double-missing-shape",
        "delisted-pit-semantics",
        "bj-mapping-truth",
        "bse-historical-status",
        "corporate-action-semantics",
        "history-fixture-300104",
    ]


def test_bj_truth_is_independent_and_does_not_claim_golden_pass():
    item = next(i for i in _load_bundle()["blockers"] if i["id"] == "bj-mapping-truth")
    truth = item["independent_truth"]

    assert truth == {
        "security_name": "贝特瑞",
        "listing_date": "2020-07-27",
        "old_code": "835185",
        "new_code": "920185",
        "source_id": "bse-code-mapping",
    }
    assert item["classification"] == "FIRST_PARTY_MAPPING_FACT_BOUND_BUT_GOLDEN_CONTRACT_NOT_MET"


def test_bse_empty_and_300104_fixture_have_opposite_classifications():
    blockers = {item["id"]: item for item in _load_bundle()["blockers"]}
    bse = blockers["bse-historical-status"]
    history = blockers["history-fixture-300104"]

    assert bse["classification"].startswith("NOT_INAPPLICABLE_")
    assert history["classification"] == "INAPPLICABLE_FOR_2020_BASELINE"
    assert history["replacement_candidate"]["provider_symbol"] == "601558.SH"
    assert history["replacement_candidate"]["status"] == "PROPOSED_NOT_ACTIVATED"


def test_first_party_sources_are_official_and_have_direct_http_200_receipts():
    sources = _load_bundle()["sources"]
    official = [source for source in sources if source.get("kind", "").startswith("FIRST_PARTY_")]

    assert len(official) >= 6
    assert all(source["http_status"] == 200 for source in official)
    assert all(
        source["url"].startswith(
            (
                "https://www.bse.cn/",
                "https://www.szse.cn/",
                "https://www.sse.com.cn/",
                "https://star.sse.com.cn/",
            )
        )
        for source in official
    )
    assert all(len(source["sha256"]) == 64 for source in official)
