"""GT-H2 clean-corpus lineage, packet, and formal-gate contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from ashare_state.spike.golden_store import GoldenTruthStore, review_readiness_gate

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
H2_ROOT = REPO_ROOT / "docs" / "golden" / "gt_h2"


def _load_source_context():
    """Load the source-only preparation helper without packaging ``scripts``."""

    path = REPO_ROOT / "scripts" / "golden" / "gt_h2_prepare.py"
    spec = importlib.util.spec_from_file_location("gt_h2_prepare_for_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._source_context


_source_context = _load_source_context()

V3_VERSION = "v3-candidate-20260822"
V3_HASH = "ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e"
SOURCE_EVIDENCE_SCOPE = "CASE_SPECIFIC_OFFICIAL_ARTIFACT"
PORTAL_ONLY_LOCATORS = {
    "https://www.bse.cn/",
    "https://www.cninfo.com.cn/new/disclosure",
    "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
    "https://www.szse.cn/lawrules/rule/trade/",
}
ALLOWED_OFFICIAL_HOSTS = {
    "www.sse.com.cn",
    "sse.com.cn",
    "static.sse.com.cn",
    "www.szse.cn",
    "szse.com.cn",
    "disc.static.szse.cn",
    "static.cninfo.com.cn",
    "www.cninfo.com.cn",
    "www.bse.cn",
}


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _repository_text_hash(path: Path) -> str:
    """Hash repository-canonical text bytes across local line-ending snapshots."""

    data = path.read_bytes().replace(b"\r\n", b"\n")
    if path.suffix == ".json" and data.endswith(b"\n"):
        data = data[:-1]
    return hashlib.sha256(data).hexdigest()


def _is_case_specific_official_locator(value: str) -> bool:
    parsed = urlparse(value)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    denied = {locator.rstrip("/") for locator in PORTAL_ONLY_LOCATORS}
    if normalized in denied:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc in ALLOWED_OFFICIAL_HOSTS
        and parsed.path not in {"", "/"}
    )


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
            "ST_ADD": 36,
            "ST_REMOVE": 11,
            "STAR_ST_ADD": 2,
            "STAR_ST_REMOVE": 1,
        }
        assert sum(c.provider_symbol.endswith(".SH") for c in st) == 12
        assert sum(c.provider_symbol.startswith("688") for c in st) == 3
        assert any(c.event_subtype == "STAR_ST_REMOVE" for c in st)
        assert actions["DIVIDEND_EX_DATE"] == 20
        assert actions["RIGHT_ISSUE_EX_DATE"] == 5
        right_issues = [case for case in cases if case.event_class == "RIGHT_ISSUE_EX_DATE"]
        assert all(case.trade_date >= "20200101" for case in right_issues)
        assert all(case.provider_symbol != "002202.SZ" for case in right_issues)
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
                "902eee047d73b578a3de28fd0e9f610a52dadf5f836ae9b5b6eef21195f8ca80"
            ),
            "truth_manifest_v3.json": (
                "9f77fc6e6487f7ffa97b3d56647ad9008ca9ebd06f3788f73a63f492028e1937"
            ),
        }
        for name, expected in expected_hashes.items():
            assert _repository_text_hash(GOLDEN_ROOT / name) == expected

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
            "source_evidence_scope",
            "human_review_checklist",
        }
        for row in packet:
            assert required <= row.keys()
            parsed = urlparse(str(row["official_source_ref"]))
            assert parsed.scheme in {"http", "https"}
            assert parsed.netloc in ALLOWED_OFFICIAL_HOSTS
            assert row["fact_proved"] is True
            assert row["source_evidence_scope"] == SOURCE_EVIDENCE_SCOPE
            assert _is_case_specific_official_locator(str(row["official_source_ref"]))
            assert isinstance(row["human_review_checklist"], list)
            assert row["human_review_checklist"]

        structural = [row for row in packet if row["event_class"] in {"ST_TRANSITION", "DELIST"}]
        assert all(row["event_effective_date"] for row in structural)
        assert all("trade_date" in row["date_semantics"] for row in packet)

    def test_known_portal_only_locators_are_rejected(self):
        assert all(
            not _is_case_specific_official_locator(locator) for locator in PORTAL_ONLY_LOCATORS
        )

    def test_limit_source_selection_is_exact_and_semantically_aligned(self):
        star_doc = {
            "event_class": "LIMIT_REGIME",
            "event_id": "REGIME-STAR-20",
            "provider_symbol": "688036.SH",
            "trade_date": "20210601",
            "expected_fields": {"PRICE_HIGH_LMT_RATE": 0.2},
        }
        st_doc = {
            "event_class": "LIMIT_REGIME",
            "event_id": "REGIME-ST-5",
            "provider_symbol": "600518.SH",
            "trade_date": "20190603",
            "expected_fields": {
                "PRICE_HIGH_LMT_RATE": 0.05,
                "PRICE_LOW_LMT_RATE": 0.05,
            },
        }
        star_name, star_ref, _, _, _ = _source_context(star_doc)
        st_name, st_ref, _, _, _ = _source_context(st_doc)

        assert "STAR Market" in star_name
        assert "20%" in star_name
        assert star_ref.endswith("8c544552dc7e4c83a863440179f0b9de.pdf")
        assert "Risk-Warning" in st_name
        assert "5%" in st_name
        assert st_ref.endswith("c_20210531_5478105.shtml")
        assert 'if "ST" in event_id' not in (
            REPO_ROOT / "scripts" / "golden" / "gt_h2_prepare.py"
        ).read_text(encoding="utf-8")
        assert 'if "STAR" in event_id' not in (
            REPO_ROOT / "scripts" / "golden" / "gt_h2_prepare.py"
        ).read_text(encoding="utf-8")

        packet = _jsonl(H2_ROOT / "review_packet_index.jsonl")
        star_rows = [row for row in packet if row["event_id"] == "REGIME-STAR-20"]
        st_rows = [row for row in packet if row["event_id"] == "REGIME-ST-5"]
        assert len(star_rows) == 5
        assert len(st_rows) == 4
        assert all(row["expected_fields"]["PRICE_HIGH_LMT_RATE"] == 0.2 for row in star_rows)
        assert all("STAR Market" in row["official_source_name"] for row in star_rows)
        assert all(
            "Risk-Warning" in row["official_source_name"]
            for row in st_rows
            if row["provider_symbol"].endswith(".SH")
        )

    def test_bj_packet_truth_matches_executable_validator_contract(self):
        cases = GoldenTruthStore(GOLDEN_ROOT).load()[0]
        bj = [case for case in cases if case.event_class == "BJ_CODE_MIGRATION"]

        assert len(bj) == 3
        for case in bj:
            assert case.expected_fields == {
                "PRICE_HIGH_LMT_RATE": 0.3,
                "PRICE_LOW_LMT_RATE": 0.3,
            }
            assert "historical security master" in case.truth_source
            assert "old-to-new" not in case.truth_source
            assert "920 segment" not in case.truth_source

        packet = _jsonl(H2_ROOT / "review_packet_index.jsonl")
        bj_packet = [row for row in packet if row["event_class"] == "BJ_CODE_MIGRATION"]
        assert len(bj_packet) == 3
        for row in bj_packet:
            checklist = " ".join(row["human_review_checklist"])
            assert "historical security master" in checklist
            assert "run-bound BSE rule" in checklist
            assert "old-to-new code relation" in checklist

    def test_report_keeps_review_and_provider_boundaries_explicit(self):
        report = (H2_ROOT / "GT_H2_CORPUS_REPORT.md").read_text(encoding="utf-8")
        assert "only intended formal blocker after candidate construction is human review" in report
        assert "does not claim human review" in report
        assert "No raw bulk web pages or PDFs are committed" in report
        assert "Production B1-B7" in report
        assert "Data Sufficiency" in report
