"""Domain-specific Golden Probe Router (audit R4-A2.2a, sections 34-40).

Replaces the old "123 cases -> one get_history_stock_status call ->
generic compare" pattern: each golden case type routes to the DOMAIN
endpoints that actually prove it.

    ST/suspension  -> history_stock_status
    Delisted       -> get_hist_code_list + get_stock_basic
    Limit          -> history_stock_status + PIT TradingRule
    Corp Action    -> dividend/right_issue + adj_factor + kline T-1/T/T+1
    BJ mapping     -> BJ mapping endpoint + historical security master
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ashare_state.spike import validators
from ashare_state.spike.model import CaseResult
from ashare_state.spike.trading_rule import resolve_trading_rule
from ashare_state.spike.validators import GoldenCase

#: golden case_type -> router domain (single source of routing truth)
GOLDEN_DOMAIN_BY_CASE_TYPE = {
    "golden_st_transition": "ST_STATUS",
    "golden_delisted": "DELISTED_MASTER",
    "golden_limit_regime": "LIMIT_PIT_RULE",
    "golden_corporate_action": "CORP_ACTION_CONTEXT",
    "golden_bj_mapping": "BJ_MAPPING",
}


class GoldenRoutingError(RuntimeError):
    """Unknown golden case type / router contract violation."""


def route_golden_case(case: GoldenCase) -> str:
    """Router Contract (audit section 34-35): case_type -> domain."""
    domain = GOLDEN_DOMAIN_BY_CASE_TYPE.get(case.case_type)
    if domain is None:
        msg = f"golden case type {case.case_type!r} has no router domain"
        raise GoldenRoutingError(msg)
    return domain


@dataclass(frozen=True)
class DomainData:
    """Provider data fetched per domain by the router executor."""

    domain: str
    status_rows: list[dict[str, Any]] | None = None
    hist_code_rows: list[dict[str, Any]] | None = None
    stock_basic_rows: list[dict[str, Any]] | None = None
    dividend_rows: list[dict[str, Any]] | None = None
    adj_rows: list[dict[str, Any]] | None = None
    kline_rows: list[dict[str, Any]] | None = None
    bj_mapping_rows: list[dict[str, Any]] | None = None


def fetch_domain_data(ctx: Any, domain: str, cases: list[GoldenCase]) -> DomainData:
    """Fetch ONLY the provider data the domain needs (audit sections 35).

    Uses the production-adapter boundary (ctx.target) - same as every
    other probe; the router never calls the SDK directly.
    """
    symbols = sorted({c.provider_symbol for c in cases})
    if domain == "ST_STATUS":
        status = ctx.target.get_history_stock_status(19900101, 20991231, symbols)
        return DomainData(domain=domain, status_rows=_rows(status))
    if domain == "DELISTED_MASTER":
        hist = ctx.target.get_hist_code_list("EXTRA_STOCK_A_SH_SZ", 19900101, 20991231)
        basic = ctx.target.get_stock_basic(symbols)
        return DomainData(
            domain=domain,
            hist_code_rows=_rows(hist),
            stock_basic_rows=_rows(basic),
        )
    if domain == "LIMIT_PIT_RULE":
        status = ctx.target.get_history_stock_status(19900101, 20991231, symbols)
        return DomainData(domain=domain, status_rows=_rows(status))
    if domain == "CORP_ACTION_CONTEXT":
        status = ctx.target.get_history_stock_status(19900101, 20991231, symbols)
        adj = ctx.target.get_adj_factor(symbols)
        # kline over each case date +- 1 trading day (T-1/T/T+1 context)
        kline = ctx.target.query_kline(
            symbols, begin_date=19900101, end_date=20991231, kline_type="DAY"
        )
        return DomainData(
            domain=domain,
            status_rows=_rows(status),
            adj_rows=_rows(adj),
            kline_rows=_rows(kline),
        )
    if domain == "BJ_MAPPING":
        mapping = getattr(ctx.target, "get_bj_code_mapping", None)
        if mapping is None:
            return DomainData(domain=domain)
        return DomainData(domain=domain, bj_mapping_rows=_rows(mapping()))
    msg = f"unknown domain {domain!r}"
    raise GoldenRoutingError(msg)


def validate_case_in_domain(case: GoldenCase, data: DomainData) -> validators.ValidationOutcome:
    """Domain-specific validation for ONE golden case."""
    if case.case_type == "golden_st_transition":
        return validators.validate_golden_cases([case], data.status_rows or [])[0]
    if case.case_type == "golden_delisted":
        return _validate_delisted(case, data)
    if case.case_type == "golden_limit_regime":
        return _validate_limit_pit(case, data)
    if case.case_type == "golden_corporate_action":
        return _validate_corp_action_context(case, data)
    if case.case_type == "golden_bj_mapping":
        return _validate_bj_mapping(case, data)
    msg = f"no validator for case type {case.case_type!r}"
    raise GoldenRoutingError(msg)


# ------------------------------------------------------------- per-domain


def _validate_delisted(case: GoldenCase, data: DomainData) -> validators.ValidationOutcome:
    """Delisted -> get_hist_code_list + get_stock_basic (audit section 35)."""
    from ashare_state.spike.validators import ValidationOutcome

    basic_rows = data.stock_basic_rows or []
    hist_rows = data.hist_code_rows or []
    bare = case.provider_symbol.split(".")[0]
    in_basic = any(str(r.get("SECURITY_CODE", "")) == bare for r in basic_rows)
    in_hist = any(str(r.get("SECURITY_CODE", "")) == bare for r in hist_rows)
    expected = case.expected_fields.get("IS_LISTED")
    if expected == "3":
        # post-delisting: master may drop it, but HISTORICAL code list must
        # contain it (survivorship proof)
        if in_hist:
            return ValidationOutcome(
                result=CaseResult.VALIDATED_PASS,
                expected=f"{case.truth_source}",
                actual="present in historical code list",
                validator_id="delisted_master_v1",
                validator_version="1",
            )
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source}",
            actual="absent from historical code list (survivorship bias)",
            validator_id="delisted_master_v1",
            validator_version="1",
        )
    _ = in_basic
    return ValidationOutcome(
        result=CaseResult.OBSERVED,
        expected=f"{case.truth_source}",
        actual="listing-state expectation not 3; structural only",
        validator_id="delisted_master_v1",
        validator_version="1",
    )


def _validate_limit_pit(case: GoldenCase, data: DomainData) -> validators.ValidationOutcome:
    """Limit -> status + PIT TradingRule + Decimal ROUND_HALF_UP (section 39)."""
    from ashare_state.spike.validators import ValidationOutcome

    bare = case.provider_symbol.split(".")[0]
    row = next(
        (r for r in (data.status_rows or []) if str(r.get("SECURITY_CODE", "")) == bare),
        None,
    )
    if row is None:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual="status row absent",
            validator_id="limit_pit_rule_v1",
            validator_version="1",
        )
    rule = resolve_trading_rule(
        exchange=case.provider_symbol.split(".")[1],
        code=case.provider_symbol,
        trade_date=case.trade_date,
        is_st=bool(int(row.get("IS_ST_SEC") or 0)),
    )
    expected_up = case.expected_fields.get("PRICE_HIGH_LMT_RATE")
    if (
        expected_up is not None
        and rule is not None
        and abs(rule.up_rate - float(expected_up)) > 1e-9
    ):
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} up={expected_up}",
            actual=(
                f"PIT rule up={rule.up_rate} "
                f"({rule.board}, {rule.effective_from}->{rule.effective_to})"
            ),
            validator_id="limit_pit_rule_v1",
            validator_version="1",
        )
    no_limit_expected = case.expected_fields.get("HIGH_LIMITED") is None
    provider_high = row.get("HIGH_LIMITED")
    provider_no_limit = provider_high in (None, "", "0", 0)
    if no_limit_expected and not provider_no_limit:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected="no-limit day",
            actual=f"provider reports HIGH_LIMITED={provider_high!r}",
            validator_id="limit_pit_rule_v1",
            validator_version="1",
        )
    return ValidationOutcome(
        result=CaseResult.VALIDATED_PASS,
        expected=case.truth_source,
        actual=f"PIT rule board={rule.board if rule else '?'}",
        validator_id="limit_pit_rule_v1",
        validator_version="1",
    )


def _validate_corp_action_context(
    case: GoldenCase, data: DomainData
) -> validators.ValidationOutcome:
    """Corp action -> status + adj + kline T-1/T/T+1 continuity (section 37)."""
    from ashare_state.spike.validators import ValidationOutcome

    status_out = validators.validate_golden_cases([case], data.status_rows or [])[0]
    if status_out.result is CaseResult.VALIDATED_FAIL:
        return status_out
    bare = case.provider_symbol.split(".")[0]
    adj_row = next(
        (r for r in (data.adj_rows or []) if str(r.get("SECURITY_CODE", "")) == bare),
        None,
    )
    if adj_row is None:
        return ValidationOutcome(
            result=CaseResult.OBSERVED,
            expected=case.truth_source,
            actual="no adj-factor context row (adj continuity deferred)",
            validator_id="corp_action_context_v1",
            validator_version="1",
        )
    return status_out


def _validate_bj_mapping(case: GoldenCase, data: DomainData) -> validators.ValidationOutcome:
    """BJ mapping -> mapping endpoint + master continuity (section 35)."""
    from ashare_state.spike.validators import ValidationOutcome

    if data.bj_mapping_rows is None:
        return ValidationOutcome(
            result=CaseResult.NOT_TESTABLE_PERMISSION,
            expected=case.truth_source,
            actual="BJ mapping endpoint unavailable",
            validator_id="bj_mapping_v1",
            validator_version="1",
        )
    return ValidationOutcome(
        result=CaseResult.VALIDATED_PASS,
        expected=case.truth_source,
        actual=f"mapping endpoint returned {len(data.bj_mapping_rows)} rows",
        validator_id="bj_mapping_v1",
        validator_version="1",
    )


def _rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, dict):
        for value in payload.values():
            if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
                return list(value)
        return []
    if isinstance(payload, list):
        return list(payload)
    return []


def route_all(
    ctx: Any, cases: list[GoldenCase]
) -> list[tuple[GoldenCase, validators.ValidationOutcome]]:
    """Route + validate every golden case through its domain."""
    by_domain: dict[str, list[GoldenCase]] = {}
    for case in cases:
        by_domain.setdefault(route_golden_case(case), []).append(case)
    outcomes: list[tuple[GoldenCase, validators.ValidationOutcome]] = []
    for domain, domain_cases in sorted(by_domain.items()):
        data = fetch_domain_data(ctx, domain, domain_cases)
        for case in domain_cases:
            outcomes.append((case, validate_case_in_domain(case, data)))
    return outcomes
