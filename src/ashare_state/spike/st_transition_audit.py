"""Fail-closed transition semantics for the GT-H3R2 ST audit.

This module deliberately keeps the audit ledger outside the Golden row schema.
It validates the binary state transition independently of expected_fields:
ST_ADD must prove false -> true and ST_REMOVE must prove true -> false.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from urllib.parse import urlparse

ST_ADD_SUBTYPES = frozenset({"ST_ADD", "STAR_ST_ADD"})
ST_REMOVE_SUBTYPES = frozenset({"ST_REMOVE", "STAR_ST_REMOVE"})
ST_SUBTYPES = ST_ADD_SUBTYPES | ST_REMOVE_SUBTYPES

# This is an allowlist for evidence locators, not a substitute for opening
# and reading the cited first-party document.
OFFICIAL_HOSTS = frozenset(
    {
        "www.sse.com.cn",
        "static.sse.com.cn",
        "star.sse.com.cn",
        "www.szse.cn",
        "disc.static.szse.cn",
        "static.cninfo.com.cn",
        "www.cninfo.com.cn",
        "www.csrc.gov.cn",
        "static.csrc.gov.cn",
        "www.bse.cn",
        "www.bseinfo.com",
    }
)

REQUIRED_AUDIT_FIELDS = (
    "golden_case_id",
    "provider_symbol",
    "event_subtype",
    "event_effective_date",
    "pre_effective_is_st",
    "effective_is_st",
    "pre_state_official_evidence",
    "effective_state_official_evidence",
    "transition_valid",
    "audit_status",
    "judgment",
)


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _expected_effective_state(subtype: object) -> bool | None:
    if subtype in ST_ADD_SUBTYPES:
        return True
    if subtype in ST_REMOVE_SUBTYPES:
        return False
    return None


def _candidate_st_rows(
    candidate_rows: Sequence[Mapping[str, object]],
) -> tuple[list[Mapping[str, object]], list[str]]:
    rows: list[Mapping[str, object]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(candidate_rows, start=1):
        if not isinstance(row, Mapping):
            problems.append(f"candidate row {index}: expected an object")
            continue
        if row.get("event_class") != "ST_TRANSITION":
            continue
        case_id = str(row.get("golden_case_id", ""))
        if not case_id:
            problems.append(f"candidate row {index}: missing golden_case_id")
        elif case_id in seen:
            problems.append(f"candidate ST_TRANSITION {case_id}: duplicate ID")
        else:
            seen.add(case_id)
        if _expected_effective_state(row.get("event_subtype")) is None:
            problems.append(
                f"candidate ST_TRANSITION {case_id}: unsupported event_subtype "
                f"{row.get('event_subtype')!r}"
            )
        rows.append(row)
    return rows, problems


def _evidence_is_complete(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    status = value.get("status")
    source_ref = str(value.get("source_ref", "")).strip()
    locator = str(value.get("locator", "")).strip()
    parsed = urlparse(source_ref)
    return (
        status == "OFFICIAL_SOURCE_REVIEWED"
        and parsed.scheme in {"http", "https"}
        and parsed.hostname in OFFICIAL_HOSTS
        and bool(locator)
    )


def validate_transition_audit(
    audit_rows: Sequence[Mapping[str, object]],
    candidate_rows: Sequence[Mapping[str, object]],
) -> list[str]:
    """Validate complete one-row-per-ST coverage and field identity binding.

    A false transition_valid is allowed in this structural check: it means
    the row is either disproved or still pending.  The publication gate below
    is the fail-closed check that requires every row to be proven valid.
    """

    candidate_st, problems = _candidate_st_rows(candidate_rows)
    expected_by_id = {str(row.get("golden_case_id")): row for row in candidate_st}
    audit_by_id: dict[str, Mapping[str, object]] = {}

    for index, row in enumerate(audit_rows, start=1):
        if not isinstance(row, Mapping):
            problems.append(f"audit row {index}: expected an object")
            continue
        missing = [field for field in REQUIRED_AUDIT_FIELDS if field not in row]
        if missing:
            problems.append(
                f"audit row {index} {row.get('golden_case_id', '?')}: "
                f"missing fields {missing}"
            )
        case_id = str(row.get("golden_case_id", ""))
        if not case_id:
            problems.append(f"audit row {index}: missing golden_case_id")
            continue
        if case_id in audit_by_id:
            problems.append(f"audit {case_id}: duplicate ID")
            continue
        audit_by_id[case_id] = row
        candidate = expected_by_id.get(case_id)
        if candidate is None:
            problems.append(
                f"audit {case_id}: not present in candidate ST_TRANSITION rows"
            )
            continue
        for field in ("provider_symbol", "event_subtype", "event_effective_date"):
            if row.get(field) != candidate.get(field):
                problems.append(
                    f"audit {case_id}: {field} does not match candidate "
                    f"({row.get(field)!r} != {candidate.get(field)!r})"
                )
        if not _is_bool(row.get("transition_valid")):
            problems.append(f"audit {case_id}: transition_valid must be boolean")
        effective_expected = _expected_effective_state(row.get("event_subtype"))
        if not _is_bool(row.get("effective_is_st")):
            problems.append(f"audit {case_id}: effective_is_st must be boolean")
        elif (
            effective_expected is not None
            and row.get("effective_is_st") != effective_expected
        ):
            problems.append(
                f"audit {case_id}: effective_is_st does not match subtype "
                f"{row.get('event_subtype')}"
            )
        pre_state = row.get("pre_effective_is_st")
        if pre_state is not None and not _is_bool(pre_state):
            problems.append(
                f"audit {case_id}: pre_effective_is_st must be boolean or null"
            )
        for field in (
            "pre_state_official_evidence",
            "effective_state_official_evidence",
        ):
            if not isinstance(row.get(field), Mapping):
                problems.append(f"audit {case_id}: {field} must be an object")

    missing_ids = sorted(set(expected_by_id) - set(audit_by_id))
    if missing_ids:
        problems.append(
            "audit coverage missing ST_TRANSITION IDs: "
            + ", ".join(missing_ids[:10])
            + (" ..." if len(missing_ids) > 10 else "")
        )
    return problems


def transition_audit_publication_gate(
    audit_rows: Sequence[Mapping[str, object]],
    candidate_rows: Sequence[Mapping[str, object]],
) -> list[str]:
    """Return fail-closed reasons preventing publication of a clean candidate."""

    problems = validate_transition_audit(audit_rows, candidate_rows)
    if problems:
        return problems

    candidate_st, _ = _candidate_st_rows(candidate_rows)
    audit_by_id = {
        str(row.get("golden_case_id")): row
        for row in audit_rows
        if isinstance(row, Mapping)
    }
    for candidate in candidate_st:
        case_id = str(candidate["golden_case_id"])
        row = audit_by_id[case_id]
        subtype = row.get("event_subtype")
        expected_pre = subtype in ST_REMOVE_SUBTYPES
        expected_effective = _expected_effective_state(subtype)
        if row.get("transition_valid") is not True:
            problems.append(
                f"audit {case_id}: transition_valid is not true "
                f"({row.get('audit_status', 'UNSPECIFIED')})"
            )
        if row.get("pre_effective_is_st") is not expected_pre:
            problems.append(
                f"audit {case_id}: ST transition must prove "
                f"{expected_pre} -> {expected_effective}, "
                f"observed pre={row.get('pre_effective_is_st')!r}"
            )
        if row.get("effective_is_st") is not expected_effective:
            problems.append(
                f"audit {case_id}: effective state does not prove {expected_effective}"
            )
        if row.get("audit_status") != "PASS":
            problems.append(
                f"audit {case_id}: audit_status must be PASS "
                f"(got {row.get('audit_status')!r})"
            )
        for field in (
            "pre_state_official_evidence",
            "effective_state_official_evidence",
        ):
            if not _evidence_is_complete(row.get(field)):
                problems.append(
                    f"audit {case_id}: {field} is not a fully reviewed "
                    "first-party official locator"
                )
    return problems
