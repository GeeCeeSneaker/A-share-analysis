"""GT-H2 clean-corpus lineage, packet, and formal-gate contracts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from ashare_state.spike.golden_store import GoldenTruthStore, review_readiness_gate

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
H2_ROOT = REPO_ROOT / "docs" / "golden" / "gt_h2"
V3_VERSION = "v3-candidate-20260822"
V3_HASH = "ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e"


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


class TestGTH2CleanCorpus:
    def test_active_candidate_passes_clean_readiness_and_all_non_review_gates(self):
        store = GoldenTruthStore(GOLDEN_ROOT)
        cases, manifest = store.load()

        assert manifest.truth_version == "v4-candidate-20260906"
        assert manifest.manifest_schema == 2
        assert manifest.case_count == 128
        assert manifest.counts_by_type == {
            "golden_bj_mapping": 3,
            "golden_corporate_action": 25,
            "golden_delisted": 20,
            "golden_limit_regime": 30,
            "golden_st_transition": 50,
        }
        assert review_readiness_gate(cases, manifest) == []
        assert store.quantity_gate(cases, manifest) == []
        assert store.event_coverage_gate(cases, manifest) == []
        assert store.production_formal_gate(cases, manifest) == [
            (
                "golden truth not fully human-reviewed (REVIEWED 0/128; "
                "audit section 39 requires every golden entry reviewed before P0-M-1B)"
            )
        ]

        for case in cases:
            assert case.review_status == "COMPILED"
            assert not case.reviewed_by
            assert not case.reviewed_at
            assert not case.source_artifact_ref
            assert not case.source_artifact_hash
            assert not case.source_artifact_kind
            assert not case.source_retrieved_at

    def test_structural_and_corporate_action_semantics_are_real_cases(self):
        cases = GoldenTruthStore(GOLDEN_ROOT).load()[0]
        st = [case for case in cases if case.event_class == "ST_TRANSITION"]
        delisted = [case for case in cases if case.event_class == "DELIST"]
        actions = Counter(case.event_class for case in cases)

        assert len({(c.provider_symbol, c.event_effective_date, c.event_subtype) for c in st}) == 50
        assert len({(c.provider_symbol, c.event_effective_date) for c in delisted}) == 20
        assert len({c.provider_symbol for c in delisted}) == 20
        assert Counter(c.event_subtype for c in st) == {
            "ST_ADD": 37,
            "ST_REMOVE": 12,
            "STAR_ST_ADD": 1,
        }
        assert actions["DIVIDEND_EX_DATE"] == 20
        assert actions["RIGHT_ISSUE_EX_DATE"] == 5
        assert all(c.event_effective_date == c.trade_date for c in st + delisted)
        assert all(c.expected_fields.get("IS_LISTED") == "3" for c in delisted)
        assert all(
            c.expected_fields.get("event_type") == "RIGHT_ISSUE"
            for c in cases
            if c.event_class == "RIGHT_ISSUE_EX_DATE"
        )

    def test_rebuild_plan_covers_v3_once_and_preserves_immutable_files(self):
        plan = json.loads((H2_ROOT / "rebuild_plan_v4.json").read_text(encoding="utf-8"))
        source = _jsonl(GOLDEN_ROOT / "golden_cases_v3.jsonl")
        operations = plan["operations"]
        source_ids = [row["golden_case_id"] for row in source]
        old_operations = [op for op in operations if op["op"] != "ADD"]
        add_operations = [op for op in operations if op["op"] == "ADD"]

        assert plan["source_truth_version"] == V3_VERSION
        assert plan["source_dataset_hash"] == V3_HASH
        assert Counter(op["op"] for op in operations) == Counter(
            {"DROP": 70, "REPLACE": 53, "ADD": 75}
        )
        assert Counter(op["golden_case_id"] for op in old_operations) == Counter(source_ids)
        assert len({op["golden_case_id"] for op in add_operations}) == 75
        assert all(op["golden_case_id"].startswith("GT-H2-") for op in add_operations)
        assert all(
            op["op"] == "DROP"
            for op, old in zip(old_operations, source, strict=True)
            if old["event_class"] in {"ST_TRANSITION", "DELIST", "NEGATIVE_SAMPLE"}
        )

        expected_hashes = {
            "golden_cases_v1.jsonl": (
                "b19b807612ca20436aeb766ba216ff47880c9ed6bd5843e446e547841612c1c8"
            ),
            "golden_cases_v2.jsonl": (
                "d36c1845c0780a3a063919062c3a55aa2227e98152a1993319a0f1cf4b3c1631"
            ),
            "golden_cases_v3.jsonl": V3_HASH,
            "truth_manifest_v2.json": (
                "b9f9377a69050d48ac9b8b2ec4a87ef75bd34bd0b4318d42f0bfcdf162ac209d"
            ),
            "truth_manifest_v3.json": (
                "3402d8689575ae7e3920bd05773dc528d3e5866c640ab37587dfa21854702a18"
            ),
        }
        for name, expected in expected_hashes.items():
            assert hashlib.sha256((GOLDEN_ROOT / name).read_bytes()).hexdigest() == expected

    def test_review_packet_has_exact_coverage_and_official_references(self):
        cases, _ = GoldenTruthStore(GOLDEN_ROOT).load()
        packet = _jsonl(H2_ROOT / "review_packet_index.jsonl")
        case_ids = [case.golden_case_id for case in cases]
        packet_ids = [row["golden_case_id"] for row in packet]

        assert packet_ids == case_ids
        assert len(packet_ids) == len(set(packet_ids)) == 128
        required = {
            "golden_case_id",
            "case_type",
            "provider_symbol",
            "trade_date",
            "event_id",
            "event_class",
            "event_subtype",
            "event_effective_date",
            "date_semantics",
            "expected_fields",
            "source_ref",
            "official_source_name",
            "official_source_ref",
            "official_source_name/ref",
            "artifact_kind_candidate",
            "fact_proved",
            "human_review_checklist",
        }
        for row in packet:
            assert required <= row.keys()
            parsed = urlparse(str(row["official_source_ref"]))
            assert parsed.scheme in {"http", "https"}
            assert parsed.netloc in {
                "www.sse.com.cn",
                "sse.com.cn",
                "www.szse.cn",
                "szse.cn",
                "disc.static.szse.cn",
                "static.cninfo.com.cn",
                "www.cninfo.com.cn",
                "www.bse.cn",
            }
            assert row["fact_proved"] is True
            assert isinstance(row["human_review_checklist"], list)
            assert row["human_review_checklist"]

        structural = [row for row in packet if row["event_class"] in {"ST_TRANSITION", "DELIST"}]
        assert all(row["event_effective_date"] for row in structural)
        assert all("trade_date" in row["date_semantics"] for row in packet)

    def test_report_keeps_review_and_provider_boundaries_explicit(self):
        report = (H2_ROOT / "GT_H2_CORPUS_REPORT.md").read_text(encoding="utf-8")
        assert "only intended formal blocker after candidate construction is human review" in report
        assert "does not claim human review" in report
        assert "No raw bulk web pages or PDFs are committed" in report
        assert "Production B1-B7" in report
        assert "Data Sufficiency" in report
