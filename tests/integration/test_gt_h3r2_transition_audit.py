from ashare_state.spike.st_transition_audit import (
    transition_audit_publication_gate,
    validate_transition_audit,
)


def _candidate(case_id: str, subtype: str) -> dict:
    return {
        "golden_case_id": case_id,
        "provider_symbol": "600000.SH",
        "event_subtype": subtype,
        "event_effective_date": "20240101",
        "event_class": "ST_TRANSITION",
    }


def _evidence() -> dict:
    return {
        "source_ref": "https://www.sse.com.cn/official.pdf",
        "locator": "page 1, official transition statement",
        "status": "OFFICIAL_SOURCE_REVIEWED",
    }


def _audit(candidate: dict, pre: bool | None, effective: bool, valid: bool = True) -> dict:
    return {
        "golden_case_id": candidate["golden_case_id"],
        "provider_symbol": candidate["provider_symbol"],
        "event_subtype": candidate["event_subtype"],
        "event_effective_date": candidate["event_effective_date"],
        "pre_effective_is_st": pre,
        "effective_is_st": effective,
        "pre_state_official_evidence": _evidence(),
        "effective_state_official_evidence": _evidence(),
        "transition_valid": valid,
        "audit_status": "PASS" if valid else "INVALID_ST_LEVEL_CHANGE",
        "judgment": "test",
    }


def test_binary_add_transition_passes():
    candidate = _candidate("add", "ST_ADD")
    audit = _audit(candidate, False, True)
    assert validate_transition_audit([audit], [candidate]) == []
    assert transition_audit_publication_gate([audit], [candidate]) == []


def test_st_to_star_st_is_not_binary_add():
    candidate = _candidate("level", "ST_ADD")
    audit = _audit(candidate, True, True, valid=False)
    problems = transition_audit_publication_gate([audit], [candidate])
    assert any("transition_valid is not true" in problem for problem in problems)
    assert any("must prove False -> True" in problem for problem in problems)


def test_star_st_to_st_is_not_binary_remove():
    candidate = _candidate("level-remove", "ST_REMOVE")
    audit = _audit(candidate, False, False, valid=False)
    problems = transition_audit_publication_gate([audit], [candidate])
    assert any("transition_valid is not true" in problem for problem in problems)
    assert any("must prove True -> False" in problem for problem in problems)


def test_pending_evidence_fails_closed():
    candidate = _candidate("pending", "ST_ADD")
    audit = _audit(candidate, None, True, valid=False)
    audit["pre_state_official_evidence"] = {
        "source_ref": "",
        "locator": "",
        "status": "MISSING_PRE_STATE_OFFICIAL_EVIDENCE",
    }
    problems = transition_audit_publication_gate([audit], [candidate])
    assert any("pre_state_official_evidence" in problem for problem in problems)


def test_coverage_binds_exact_case_set():
    first = _candidate("one", "ST_ADD")
    second = _candidate("two", "ST_REMOVE")
    audit = _audit(first, False, True)
    structural = validate_transition_audit([audit], [first, second])
    assert any("coverage missing" in problem for problem in structural)


def test_effective_state_is_bound_to_subtype():
    candidate = _candidate("wrong-effective", "ST_ADD")
    audit = _audit(candidate, False, False)
    structural = validate_transition_audit([audit], [candidate])
    assert any("effective_is_st does not match subtype" in problem for problem in structural)
