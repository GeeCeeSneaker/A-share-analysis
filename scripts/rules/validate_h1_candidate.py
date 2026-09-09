"""Validate the Trading Rule H1 COMPILED candidate before independent review.

This is deliberately a small candidate/readiness check, not a generic evidence
framework and not a REVIEWED publication tool. It proves that:

- the corrected candidate parses under the production TradingRuleBook schema;
- the candidate rule-id set exactly matches its first-party source contract;
- every rule points at its own contract locator;
- every referenced source is HTTPS on an explicit first-party allowlist;
- source roles are governed; and
- the existing ACTIVE selector was not silently advanced to this candidate.

Raw evidence bytes/hashes are intentionally a later independent-review/seal
requirement. The implementer must not convert this check into self-approval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from ashare_state.spike.trading_rule import TradingRuleBook

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VERSION = "v20260909-h1-compiled"
DEFAULT_RULES = REPO_ROOT / "configs" / "trading_rules" / "versions" / DEFAULT_VERSION / "rules.yaml"
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "configs"
    / "trading_rules"
    / "versions"
    / DEFAULT_VERSION
    / "evidence_source_contract.json"
)
ACTIVE_MANIFEST = REPO_ROOT / "configs" / "trading_rules" / "rule_manifest.json"


class H1CandidateError(RuntimeError):
    """Fail-closed candidate/source-contract validation error."""


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise H1CandidateError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise H1CandidateError(f"JSON root must be an object: {path}")
    return value


def validate_h1_candidate(
    rules_path: Path = DEFAULT_RULES,
    contract_path: Path = DEFAULT_CONTRACT,
    active_manifest_path: Path = ACTIVE_MANIFEST,
) -> dict[str, int | str]:
    book = TradingRuleBook.load(rules_path)
    if book.review_status != "COMPILED":
        raise H1CandidateError(
            f"candidate must remain COMPILED before independent review; got {book.review_status!r}"
        )

    contract = _load_json(contract_path)
    if contract.get("schema_version") != "RULE_EVIDENCE_SOURCE_CONTRACT_V0.1":
        raise H1CandidateError("unsupported H1 source-contract schema")
    if contract.get("stage") != "SOURCE_CONTRACT_ONLY_NOT_REVIEW_SEAL":
        raise H1CandidateError("H1 source contract must remain pre-seal at implementer stage")
    if contract.get("dataset_version") != book.version:
        raise H1CandidateError(
            f"source contract dataset_version {contract.get('dataset_version')!r} "
            f"!= candidate {book.version!r}"
        )

    policy = contract.get("policy")
    if not isinstance(policy, dict):
        raise H1CandidateError("source contract policy must be an object")
    if policy.get("first_party_required") is not True:
        raise H1CandidateError("H1 must require first-party evidence")
    if policy.get("implementer_may_self_seal") is not False:
        raise H1CandidateError("implementer self-seal must remain forbidden")

    allowed_hosts = set(policy.get("allowed_hosts") or [])
    allowed_roles = set(policy.get("allowed_roles") or [])
    if not allowed_hosts or not allowed_roles:
        raise H1CandidateError("allowed source hosts/roles must be explicit and non-empty")

    sources = contract.get("sources")
    rule_sources = contract.get("rule_sources")
    if not isinstance(sources, dict) or not isinstance(rule_sources, dict):
        raise H1CandidateError("sources and rule_sources must be objects")

    rule_by_id = {rule.rule_id: rule for rule in book.rules}
    if len(rule_by_id) != len(book.rules):
        raise H1CandidateError("candidate contains duplicate rule_id values")

    candidate_ids = set(rule_by_id)
    contract_ids = set(rule_sources)
    if candidate_ids != contract_ids:
        missing = sorted(candidate_ids - contract_ids)
        extra = sorted(contract_ids - candidate_ids)
        raise H1CandidateError(f"rule/source set mismatch; missing={missing}, extra={extra}")

    referenced_sources: set[str] = set()
    for rule_id, rule in rule_by_id.items():
        expected_ref = f"evidence_source_contract.json#{rule_id}"
        if rule.source_ref != expected_ref:
            raise H1CandidateError(
                f"{rule_id}: source_ref must be exact contract locator {expected_ref!r}; "
                f"got {rule.source_ref!r}"
            )
        refs = rule_sources[rule_id]
        if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x for x in refs):
            raise H1CandidateError(f"{rule_id}: source list must be non-empty strings")
        referenced_sources.update(refs)

    undefined = sorted(referenced_sources - set(sources))
    if undefined:
        raise H1CandidateError(f"undefined source ids referenced by rules: {undefined}")

    for source_id in sorted(referenced_sources):
        item = sources[source_id]
        if not isinstance(item, dict):
            raise H1CandidateError(f"{source_id}: source entry must be an object")
        url = item.get("url")
        role = item.get("role")
        kind = item.get("kind")
        locator = item.get("locator")
        if not all(isinstance(x, str) and x.strip() for x in (url, role, kind, locator)):
            raise H1CandidateError(f"{source_id}: url/role/kind/locator must be non-empty strings")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            raise H1CandidateError(
                f"{source_id}: source must be HTTPS on first-party allowlist; got {url!r}"
            )
        if role not in allowed_roles:
            raise H1CandidateError(f"{source_id}: unsupported evidence role {role!r}")
        # This is intentionally pre-seal. Fake/non-null raw hashes at this stage
        # are refused so the implementer cannot manufacture review evidence.
        if item.get("artifact_sha256") is not None or item.get("artifact_size") is not None:
            raise H1CandidateError(
                f"{source_id}: raw artifact identity belongs to independent review/seal, not COMPILED stage"
            )

    seal_requirements = contract.get("review_seal_requirements")
    if not isinstance(seal_requirements, dict):
        raise H1CandidateError("review_seal_requirements must be an object")
    required_true = {
        "source_contract_rule_set_must_exactly_match_candidate_rule_set",
        "every_referenced_source_must_be_first_party",
        "reviewer_must_capture_exact_raw_artifact_bytes",
        "sealed_bundle_must_record_each_raw_artifact_sha256_and_size",
        "sealed_bundle_must_preserve_rule_to_source_mapping",
        "independent_reviewer_must_close_transition_boundaries",
    }
    not_enabled = sorted(key for key in required_true if seal_requirements.get(key) is not True)
    if not_enabled:
        raise H1CandidateError(f"required review/seal controls disabled: {not_enabled}")

    active = _load_json(active_manifest_path)
    if active.get("rule_version") == contract.get("candidate_version"):
        raise H1CandidateError("H1 COMPILED candidate must not be ACTIVE before independent review")

    return {
        "rule_count": len(book.rules),
        "source_count": len(referenced_sources),
        "review_status": book.review_status,
        "active_rule_version": str(active.get("rule_version", "")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--active-manifest", type=Path, default=ACTIVE_MANIFEST)
    args = parser.parse_args()
    result = validate_h1_candidate(args.rules, args.contract, args.active_manifest)
    print(json.dumps({"status": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
