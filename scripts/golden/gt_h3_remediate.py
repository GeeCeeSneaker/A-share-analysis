"""Verify the governed GT-H3R v4 -> v5 remediation outputs.

The v5 bytes are produced by ``candidate.py rebuild`` using the committed
explicit plan.  This module is intentionally a verifier: it never writes a
dataset, changes ACTIVE, binds evidence, or runs the review seal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.golden_store import (  # noqa: E402
    cases_from_dataset_bytes,
    recompute_manifest_statistics,
    review_identity_hash_for_doc,
    semantic_hash_for_doc,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = ROOT / "data" / "golden" / "provider" / "amazingdata"
REMEDIATION_ROOT = ROOT / "docs" / "golden" / "gt_h3" / "remediation"
PRIOR_RESULT = ROOT / "docs" / "golden" / "gt_h3" / "GT_H3_HUMAN_REVIEW_RESULT.jsonl"
SUPPORTING_SOURCES_PATH = REMEDIATION_ROOT / "GT_H3R_V5_SUPPORTING_OFFICIAL_SOURCES.jsonl"
V4_VERSION = "v4-candidate-20260906"
V5_VERSION = "v5-candidate-20260907"
V4_DATASET_HASH = "8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b"

SOURCE_ONLY_IDS = {
    "GT-LIMIT-CN20-300015",
    "GT-LIMIT-CN20-300059",
    "GT-LIMIT-CN20-300124",
    "GT-LIMIT-CN20-300274",
    "GT-LIMIT-CN20-300750",
    "GT-LIMIT-ST5-600518-20190603",
    "GT-LIMIT-ST5-600518-20191028",
    "GT-LIMIT-IPO44-601995",
    "GT-LIMIT-IPO44-605499",
    "GT-H2-ST-ST_ADD-002022-20220506",
}
FACT_CORRECTION_IDS = {
    "GT-LIMIT-STARNO-20200723",
    "GT-H2-ST-ST_ADD-300965-20240429",
}
NEW_ID_BY_OLD_ID = {
    "GT-LIMIT-STARNO-20200723": "GT-LIMIT-STAR20-688981-20200723",
    "GT-H2-ST-ST_ADD-300965-20240429": "GT-H2-ST-ST_ADD-300965-20240426",
}

COMPOSITE_CASE_IDS = {
    "GT-LIMIT-ST5-600518-20190603",
    "GT-LIMIT-ST5-600518-20191028",
    "GT-LIMIT-STARNO-20200723",
    "GT-LIMIT-IPO44-601995",
    "GT-LIMIT-IPO44-605499",
}
OFFICIAL_HOSTS = {
    "sse.com.cn",
    "www.sse.com.cn",
    "static.sse.com.cn",
    "star.sse.com.cn",
    "szse.cn",
    "www.szse.cn",
    "static.cninfo.com.cn",
    "cninfo.com.cn",
    "disc.static.szse.cn",
}
NOT_HUMAN_VERIFIED = "CANDIDATE_SOURCES_DECLARED_NOT_HUMAN_VERIFIED"
NOT_MATERIALIZED = "NOT_MATERIALIZED_IN_GT_H3R"

EXPECTED_SOURCE_REFS = {
    "GT-LIMIT-CN20-300015": "P020231230545310237980.pdf",
    "GT-LIMIT-CN20-300059": "P020231230545310237980.pdf",
    "GT-LIMIT-CN20-300124": "P020231230545310237980.pdf",
    "GT-LIMIT-CN20-300274": "P020231230545310237980.pdf",
    "GT-LIMIT-CN20-300750": "P020231230545310237980.pdf",
    "GT-LIMIT-ST5-600518-20190603": "c_20121216_10785153.shtml",
    "GT-LIMIT-ST5-600518-20191028": "c_20121216_10785153.shtml",
    "GT-LIMIT-IPO44-601995": "c_20150912_3988761.shtml",
    "GT-LIMIT-IPO44-605499": "c_20150912_3988761.shtml",
    "GT-H2-ST-ST_ADD-002022-20220506": "1213259774.PDF",
    "GT-LIMIT-STAR20-688981-20200723": "8c544552dc7e4c83a863440179f0b9de.pdf",
    "GT-H2-ST-ST_ADD-300965-20240426": "1219804789.PDF",
}


class RemediationError(RuntimeError):
    """GT-H3R remediation contract violation."""


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationError(f"cannot read JSONL {path}: {exc}") from exc


def _load_v4() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((GOLDEN_ROOT / "truth_manifest_v4.json").read_text(encoding="utf-8"))
    dataset_bytes = (GOLDEN_ROOT / "golden_cases_v4.jsonl").read_bytes()
    digest = hashlib.sha256(dataset_bytes).hexdigest()
    if digest != V4_DATASET_HASH or manifest.get("dataset_hash") != V4_DATASET_HASH:
        raise RemediationError(
            "v4 dataset or manifest hash does not match the adjudicated baseline"
        )
    if manifest.get("truth_version") != V4_VERSION:
        raise RemediationError("v4 manifest truth_version changed")
    try:
        cases_from_dataset_bytes(dataset_bytes, V4_VERSION)
    except Exception as exc:
        raise RemediationError(f"v4 dataset is not loadable: {exc}") from exc
    return manifest, _jsonl(GOLDEN_ROOT / "golden_cases_v4.jsonl")


def _load_v5() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    version_path = GOLDEN_ROOT / "truth_manifest_v5.json"
    active_path = GOLDEN_ROOT / "truth_manifest.json"
    version_manifest = json.loads(version_path.read_text(encoding="utf-8"))
    active_manifest = json.loads(active_path.read_text(encoding="utf-8"))
    if active_manifest != version_manifest:
        raise RemediationError("ACTIVE pointer is not byte-equivalent to truth_manifest_v5.json")
    if version_manifest.get("truth_version") != V5_VERSION:
        raise RemediationError("v5 manifest truth_version is unexpected")
    dataset_path = GOLDEN_ROOT / str(version_manifest.get("dataset_file", ""))
    dataset_bytes = dataset_path.read_bytes()
    if hashlib.sha256(dataset_bytes).hexdigest() != version_manifest.get("dataset_hash"):
        raise RemediationError("v5 dataset hash does not match truth_manifest_v5.json")
    try:
        cases = cases_from_dataset_bytes(dataset_bytes, V5_VERSION)
    except Exception as exc:
        raise RemediationError(f"v5 dataset is not loadable: {exc}") from exc
    stats = recompute_manifest_statistics(cases)
    for field in (
        "case_count",
        "counts_by_type",
        "review_summary",
        "distinct_events",
        "distinct_securities",
        "st_add_events",
        "st_remove_events",
        "distinct_delisted_securities",
    ):
        if version_manifest.get(field) != stats[field]:
            raise RemediationError(f"v5 manifest field {field} is not self-consistent")
    if version_manifest.get("case_count") != 125:
        raise RemediationError("v5 must contain exactly 125 cases")
    if version_manifest.get("review_summary") != {"COMPILED": 125}:
        raise RemediationError("v5 must remain COMPILED 125/125")
    return version_manifest, _jsonl(dataset_path)


def _load_prior_results() -> dict[str, dict[str, Any]]:
    rows = _jsonl(PRIOR_RESULT)
    if len(rows) != 125:
        raise RemediationError("prior human result must contain 125 rows")
    result = {str(row.get("case")): row for row in rows}
    if len(result) != 125 or {row.get("decision") for row in rows} != {"APPROVE", "REJECT"}:
        raise RemediationError("prior human result has duplicate IDs or invalid decisions")
    counts = {
        decision: sum(row["decision"] == decision for row in rows)
        for decision in ("APPROVE", "REJECT")
    }
    if counts != {"APPROVE": 113, "REJECT": 12}:
        raise RemediationError(f"unexpected prior decision counts: {counts}")
    return result


def _stable_fields(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "golden_case_id": doc["golden_case_id"],
        "case_type": doc["case_type"],
        "provider_symbol": doc["provider_symbol"],
        "trade_date": doc["trade_date"],
        "truth_source": doc["truth_source"],
        "expected_fields": doc["expected_fields"],
        "event_id": doc["event_id"],
        "event_class": doc["event_class"],
        "event_subtype": doc.get("event_subtype", ""),
        "event_effective_date": doc.get("event_effective_date", ""),
        "source_evidence_scope": doc.get("source_evidence_scope", ""),
    }


def _validate_exact_scope(old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> None:
    old_by_id = {row["golden_case_id"]: row for row in old_rows}
    new_by_id = {row["golden_case_id"]: row for row in new_rows}
    if len(old_by_id) != 125 or len(new_by_id) != 125:
        raise RemediationError("v4/v5 case IDs must each be unique and contain 125 rows")
    expected_new_ids = {NEW_ID_BY_OLD_ID.get(old_id, old_id) for old_id in old_by_id}
    if set(new_by_id) != expected_new_ids:
        raise RemediationError("v5 case ID set differs outside the two adjudicated rekeys")

    for old_id, old in old_by_id.items():
        new_id = NEW_ID_BY_OLD_ID.get(old_id, old_id)
        new = new_by_id[new_id]
        if old_id not in SOURCE_ONLY_IDS | FACT_CORRECTION_IDS:
            if _stable_fields(old) != _stable_fields(new):
                raise RemediationError(f"unexpected v5 semantic change outside rejects: {old_id}")
        elif old_id in SOURCE_ONLY_IDS:
            old_stable = _stable_fields(old)
            new_stable = _stable_fields(new)
            old_stable["source_ref"] = old.get("source_ref", "")
            new_stable["source_ref"] = new.get("source_ref", "")
            old_stable.pop("source_ref", None)
            new_stable.pop("source_ref", None)
            if old_stable != new_stable:
                raise RemediationError(f"evidence-only row changed semantics: {old_id}")
            expected_suffix = EXPECTED_SOURCE_REFS[old_id]
            if not str(new.get("source_ref", "")).endswith(expected_suffix):
                raise RemediationError(f"{old_id} has the wrong replacement source")

    star = new_by_id[NEW_ID_BY_OLD_ID["GT-LIMIT-STARNO-20200723"]]
    if (
        star["provider_symbol"],
        star["trade_date"],
        star["event_id"],
        star["event_class"],
        star["expected_fields"],
    ) != (
        "688981.SH",
        "20200723",
        "REGIME-STAR-20",
        "LIMIT_REGIME",
        {"PRICE_HIGH_LMT_RATE": 0.2},
    ):
        raise RemediationError("AG-027 v5 boundary correction is not exact")
    st = new_by_id[NEW_ID_BY_OLD_ID["GT-H2-ST-ST_ADD-300965-20240429"]]
    if (
        st["provider_symbol"],
        st["trade_date"],
        st["event_effective_date"],
        st["event_subtype"],
        st["expected_fields"],
    ) != ("300965.SZ", "20240426", "20240426", "ST_ADD", {"IS_ST_SEC": True}):
        raise RemediationError("AG-096 v5 effective-date correction is not exact")
    for new_id in NEW_ID_BY_OLD_ID.values():
        if not str(new_by_id[new_id].get("source_ref", "")).endswith(EXPECTED_SOURCE_REFS[new_id]):
            raise RemediationError(f"{new_id} has the wrong replacement source")
    for doc in new_rows:
        if doc.get("review_status") != "COMPILED":
            raise RemediationError("v5 contains non-COMPILED review status")
        if any(
            doc.get(field)
            for field in (
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "source_artifact_ref",
                "source_artifact_hash",
                "source_artifact_kind",
                "source_retrieved_at",
            )
        ):
            raise RemediationError("v5 contains review or evidence provenance")
        if doc.get("case_semantic_hash") != semantic_hash_for_doc(doc):
            raise RemediationError(f"v5 semantic hash mismatch: {doc['golden_case_id']}")


def _validate_carry_forward(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    ledger_rows = _jsonl(REMEDIATION_ROOT / "v4_to_v5_human_review_carry_forward.jsonl")
    if len(ledger_rows) != 125:
        raise RemediationError("carry-forward ledger must contain 125 rows")
    old_by_id = {row["golden_case_id"]: row for row in old_rows}
    new_by_id = {row["golden_case_id"]: row for row in new_rows}
    seen_old: set[str] = set()
    eligible = 0
    for row in ledger_rows:
        old_id = str(row.get("old_case_id", ""))
        new_id = str(row.get("new_case_id", ""))
        if old_id in seen_old or old_id not in old_by_id:
            raise RemediationError(f"invalid or duplicate ledger old_case_id: {old_id}")
        seen_old.add(old_id)
        expected_new_id = NEW_ID_BY_OLD_ID.get(old_id, old_id)
        if new_id != expected_new_id or new_id not in new_by_id:
            raise RemediationError(f"ledger new_case_id mismatch for {old_id}")
        old_hash = review_identity_hash_for_doc(old_by_id[old_id])
        new_hash = review_identity_hash_for_doc(new_by_id[new_id])
        if (
            row.get("old_case_semantic_hash") != old_hash
            or row.get("new_case_semantic_hash") != new_hash
        ):
            raise RemediationError(f"review identity hash mismatch for {old_id}")
        prior = results[old_id]
        if row.get("prior_decision") != prior["decision"]:
            raise RemediationError(f"prior decision mismatch for {old_id}")
        expected_eligible = (
            prior["decision"] == "APPROVE" and old_id == new_id and old_hash == new_hash
        )
        if row.get("carry_forward_eligible") is not expected_eligible:
            raise RemediationError(f"carry-forward eligibility mismatch for {old_id}")
        if expected_eligible:
            eligible += 1
        if row.get("old_dataset_case_semantic_hash") != old_by_id[old_id].get("case_semantic_hash"):
            raise RemediationError(f"old dataset hash trace missing for {old_id}")
        if row.get("new_dataset_case_semantic_hash") != new_by_id[new_id].get("case_semantic_hash"):
            raise RemediationError(f"new dataset hash trace missing for {old_id}")
    if seen_old != set(old_by_id) or eligible != 113:
        raise RemediationError(f"carry-forward counts are wrong: eligible={eligible}")
    return eligible, len(ledger_rows) - eligible


def _validate_supporting_sources(
    old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]
) -> None:
    """Validate the Human-review source contract without claiming fact proof.

    This sidecar is deliberately separate from Golden truth.  It declares the
    official materials a reviewer must inspect, but it contains neither
    retrieved bytes nor a ``fact_proved`` assertion.  Composite cases require
    a rule artifact and a case/date applicability artifact; the other seven
    delta rows retain their single primary source.
    """
    rows = _jsonl(SUPPORTING_SOURCES_PATH)
    if len(rows) != 12:
        raise RemediationError("supporting-source sidecar must contain exactly 12 rows")
    old_by_id = {str(row["golden_case_id"]): row for row in old_rows}
    new_by_id = {str(row["golden_case_id"]): row for row in new_rows}
    expected_old_ids = SOURCE_ONLY_IDS | FACT_CORRECTION_IDS
    if {str(row.get("old_case_id", "")) for row in rows} != expected_old_ids:
        raise RemediationError("supporting-source sidecar does not cover the exact 12-case delta")
    seen_case_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        old_id = str(row.get("old_case_id", ""))
        case_id = str(row.get("case_id", ""))
        expected_case_id = NEW_ID_BY_OLD_ID.get(old_id, old_id)
        if old_id not in old_by_id or case_id != expected_case_id or case_id not in new_by_id:
            raise RemediationError(
                f"supporting-source sidecar row {index} has an invalid case mapping"
            )
        if case_id in seen_case_ids:
            raise RemediationError(f"supporting-source sidecar has duplicate case_id: {case_id}")
        seen_case_ids.add(case_id)
        if row.get("truth_version") != V5_VERSION:
            raise RemediationError(f"{old_id}: supporting-source truth_version is unexpected")
        if row.get("evidence_status") != NOT_HUMAN_VERIFIED:
            raise RemediationError(f"{old_id}: supporting-source status must remain candidate-only")
        for field in (
            "human_review_result",
            "human_review_feedback",
            "reviewed_by",
            "reviewed_at",
        ):
            if row.get(field, "") not in ("", None):
                raise RemediationError(
                    f"{old_id}: supporting-source review field is populated: {field}"
                )
        if "fact_proved" in row:
            raise RemediationError(
                f"{old_id}: supporting-source sidecar must not claim fact_proved"
            )
        sources = row.get("required_official_sources")
        if not isinstance(sources, list) or not sources:
            raise RemediationError(f"{old_id}: supporting-source list is empty")
        roles: set[str] = set()
        for source_index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                raise RemediationError(f"{old_id}: source {source_index} is not an object")
            required = (
                "role",
                "source_name",
                "official_source_ref",
                "artifact_kind",
                "proof_scope",
                "required_claim",
            )
            missing = [field for field in required if not str(source.get(field, ""))]
            if missing:
                raise RemediationError(f"{old_id}: source {source_index} is missing {missing}")
            if source.get("source_sha256", "") != "":
                raise RemediationError(
                    f"{old_id}: source bytes/hash must not be asserted before review"
                )
            if source.get("hash_status", NOT_MATERIALIZED) != NOT_MATERIALIZED:
                raise RemediationError(f"{old_id}: source hash status is not candidate-only")
            role = str(source["role"])
            roles.add(role)
            parsed = urlparse(str(source["official_source_ref"]))
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
                raise RemediationError(
                    f"{old_id}: source {source_index} is not an allowed HTTPS official host"
                )
            searchable_text = " ".join(
                str(source.get(field, ""))
                for field in ("source_name", "official_source_ref", "proof_scope")
            ).lower()
            forbidden_label = any(
                token in searchable_text for token in ("provider", "search", "sdk", "摘要")
            ) or re.search(r"(?<![a-z])ai(?![a-z])", searchable_text)
            if forbidden_label:
                raise RemediationError(
                    f"{old_id}: source {source_index} contains a forbidden locator label"
                )
        if old_id in COMPOSITE_CASE_IDS:
            if len(sources) < 2 or not {"RULE", "APPLICABILITY"}.issubset(roles):
                raise RemediationError(
                    f"{old_id}: composite case requires RULE and APPLICABILITY sources"
                )
        elif "APPLICABILITY" in roles:
            raise RemediationError(
                f"{old_id}: non-composite case must not add an applicability source"
            )
    expected_case_ids = {NEW_ID_BY_OLD_ID.get(old_id, old_id) for old_id in expected_old_ids}
    if seen_case_ids != set(new_by_id) & expected_case_ids:
        raise RemediationError("supporting-source sidecar case coverage is incomplete")


def verify() -> dict[str, Any]:
    v4_manifest, old_rows = _load_v4()
    v5_manifest, new_rows = _load_v5()
    results = _load_prior_results()
    _validate_exact_scope(old_rows, new_rows)
    eligible, not_eligible = _validate_carry_forward(old_rows, new_rows, results)
    _validate_supporting_sources(old_rows, new_rows)
    delta_lines = (
        (REMEDIATION_ROOT / "GT_H3R_V5_REVIEW_TABLE.md").read_text(encoding="utf-8").splitlines()
    )
    delta_case_ids = {
        row["golden_case_id"]
        for row in old_rows
        if row["golden_case_id"] in SOURCE_ONLY_IDS | FACT_CORRECTION_IDS
    }
    table_case_ids = {
        part.strip().strip("`")
        for line in delta_lines
        if line.startswith("| ")
        for part in line.split("|")[1:3]
        if part.strip().startswith("GT-")
    }
    table_text = "\n".join(delta_lines)
    if (
        "制度规则材料/主官方材料" not in table_text
        or "案例适用性材料（复合事实必填）" not in table_text
    ):
        raise RemediationError("v5 delta review table must split rule and applicability materials")
    for old_id in COMPOSITE_CASE_IDS:
        matching = [line for line in delta_lines if f"| {old_id} |" in line]
        if len(matching) != 1 or matching[0].count("](https://") < 2:
            raise RemediationError(f"{old_id}: review table must show both official source links")
    if not delta_case_ids.issubset(table_case_ids) or len(table_case_ids) != 12:
        raise RemediationError("v5 delta review table does not list exactly the 12 old case IDs")
    return {
        "v4_truth_version": v4_manifest["truth_version"],
        "v4_dataset_hash": v4_manifest["dataset_hash"],
        "v5_truth_version": v5_manifest["truth_version"],
        "v5_dataset_hash": v5_manifest["dataset_hash"],
        "case_count": v5_manifest["case_count"],
        "carry_forward_eligible": eligible,
        "carry_forward_not_eligible": not_eligible,
        "delta_human_review_cases": 12,
        "review_summary": v5_manifest["review_summary"],
        "review_seal": "NOT_RUN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GT-H3R v5 remediation outputs")
    parser.add_argument("command", choices=["verify"])
    parser.parse_args()
    try:
        print(json.dumps(verify(), ensure_ascii=False, sort_keys=True))
    except (OSError, KeyError, TypeError, ValueError, RemediationError) as exc:
        print(f"gt-h3r remediation error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
