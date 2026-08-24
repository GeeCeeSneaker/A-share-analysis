"""Domain-specific Golden Probe Router (audit R4-A2.2a sections 34-40,
hardened R4-A2.3 section 6).

Replaces the old "123 cases -> one get_history_stock_status call ->
generic compare" pattern: each golden case type routes to the DOMAIN
endpoints that actually prove it.

    ST/suspension  -> history_stock_status
    Delisted       -> get_hist_code_list + get_stock_basic
    Limit          -> history_stock_status (EXACT trade_date) + hist master
                      (listing_date, same PIT context) + trade calendar
                      + PIT rule book (versioned data layer)
    Corp Action    -> trade calendar + status + adj_factor + kline
                      T-1/T/T+1 window (real continuity validation)
    BJ mapping     -> historical security master + exact-date status
                      (independent semantic proof, audit section 10)

R4-A2.3 P0-04 (audit section 6): every domain fetch goes through EXPLICIT
ProviderExchanges persisted by the RawWriter; DomainData is built from the
EXACT persisted payloads; every case binds to the domain's multi-endpoint
EVIDENCE BUNDLE (manifest listing all raw refs + hashes + request_ids).
No lambda: None pseudo-calls, no payload-without-evidence fetches.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ashare_state.providers.errors import (
    ProviderError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderSchemaError,
)
from ashare_state.spike import validators
from ashare_state.spike.model import CaseResult
from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    resolve_limit_regime,
    resolve_trading_rule,
)
from ashare_state.spike.validators import GoldenCase, ValidationOutcome

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
    """Provider data fetched per domain, built from the EXACT payloads of
    the persisted exchanges (audit section 6.2)."""

    domain: str
    status_rows: list[dict[str, Any]] | None = None
    hist_code_rows: list[dict[str, Any]] | None = None
    stock_basic_rows: list[dict[str, Any]] | None = None
    adj_rows: list[dict[str, Any]] | None = None
    kline_rows: list[dict[str, Any]] | None = None
    calendar_days: list[int] | None = None


# ------------------------------------------------------------------ bundle


class _DomainCollector:
    """Persists every exchange of ONE domain fetch through the run's
    RawWriter and builds the multi-endpoint evidence bundle manifest
    (audit section 6.3): all raw refs + content hashes + request_ids."""

    def __init__(self, ctx: Any, domain: str) -> None:
        self.ctx = ctx
        self.domain = domain
        self.entries: list[dict[str, Any]] = []
        self.request_ids: list[str] = []

    def persist(self, exchange: Any) -> Any:
        """Persist one SUCCESS exchange; returns its exact payload."""
        meta = self.ctx.evidence_from_exchange(exchange)
        self._record(meta)
        return exchange.payload

    def persist_failure(self, exc: ProviderError, *, endpoint: str, dataset: str) -> None:
        """Persist the FAILED exchange (first-class failure object)."""
        meta = self.ctx.failure_evidence(exc, endpoint=endpoint, dataset=dataset)
        self._record(meta)

    def _record(self, meta: dict[str, Any]) -> None:
        self.entries.append(
            {
                "request_id": meta.get("request_id", ""),
                "endpoint": meta.get("endpoint", ""),
                "provider_dataset": meta.get("provider_dataset", ""),
                "status": meta.get("status", ""),
                "error_class": meta.get("error_class"),
                "evidence_ref": meta.get("evidence_ref", ""),
                "content_hash": meta.get("content_hash", ""),
            }
        )
        self.request_ids.append(str(meta.get("request_id", "")))

    def bundle_evidence(self) -> dict[str, Any]:
        """Write the bundle manifest (immutable) and return the evidence
        meta every case of this domain binds to."""
        if not self.entries:
            return {
                "evidence_ref": "",
                "content_hash": "",
                "request_ids": [],
                "domain": self.domain,
            }
        bundle_id = f"{self.domain.lower()}-{uuid.uuid4().hex[:8]}"
        run = self.ctx.run
        raw_root = self.ctx.store.raw_dir(run)
        bundle_dir = raw_root / "bundles"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        doc = {
            "bundle_id": bundle_id,
            "spike_run_id": run.spike_run_id,
            "domain": self.domain,
            "exchanges": self.entries,
        }
        payload_bytes = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1).encode(
            "utf-8"
        )
        from ashare_state.storage.atomic_files import write_file_atomic

        bundle_path = bundle_dir / f"{bundle_id}.json"
        write_file_atomic(bundle_path, payload_bytes)
        run_prefix = f"{run.run_kind.value.lower()}/{run.spike_run_id}/raw/"
        bundle_ref = f"{run_prefix}bundles/{bundle_path.name}"
        bundle_hash = hashlib.sha256(payload_bytes).hexdigest()
        return {
            "evidence_ref": bundle_ref,
            "content_hash": bundle_hash,
            "request_ids": list(self.request_ids),
            "domain": self.domain,
            "bundle": True,
        }


# ------------------------------------------------------------------- fetch


def fetch_domain_data(
    ctx: Any, domain: str, cases: list[GoldenCase], collector: _DomainCollector
) -> DomainData:
    """Fetch ONLY the provider data the domain needs, through EXPLICIT
    exchanges persisted by the RawWriter (audit sections 6.1-6.2). Uses
    the production-adapter boundary (ctx.target) - the router never calls
    the SDK directly and never fetches without evidence."""
    symbols = sorted({c.provider_symbol for c in cases})
    if domain == "ST_STATUS":
        status = collector.persist(
            ctx.target.get_history_stock_status_exchange(19900101, 20991231, symbols)
        )
        return DomainData(domain=domain, status_rows=_rows(status))
    if domain == "DELISTED_MASTER":
        hist = collector.persist(
            ctx.target.get_hist_code_list_exchange("EXTRA_STOCK_A_SH_SZ", 19900101, 20991231)
        )
        basic = collector.persist(ctx.target.get_stock_basic_exchange(symbols))
        return DomainData(
            domain=domain,
            hist_code_rows=_rows(hist),
            stock_basic_rows=_rows(basic),
        )
    if domain == "LIMIT_PIT_RULE":
        # audit section 9.2: listing_date must come from the SAME PIT
        # context (hist master), the calendar from a dedicated exchange
        status = collector.persist(
            ctx.target.get_history_stock_status_exchange(19900101, 20991231, symbols)
        )
        hist = collector.persist(
            ctx.target.get_hist_code_list_exchange("EXTRA_STOCK_A_SH_SZ", 19900101, 20991231)
        )
        calendar = collector.persist(ctx.target.get_calendar_exchange())
        return DomainData(
            domain=domain,
            status_rows=_rows(status),
            hist_code_rows=_rows(hist),
            calendar_days=_calendar_days(calendar),
        )
    if domain == "CORP_ACTION_CONTEXT":
        # audit section 9.3: event record + adj factor around event +
        # kline T-1/T/T+1 + PIT trading calendar
        calendar = collector.persist(ctx.target.get_calendar_exchange())
        status = collector.persist(
            ctx.target.get_history_stock_status_exchange(19900101, 20991231, symbols)
        )
        adj = collector.persist(ctx.target.get_adj_factor_exchange(symbols))
        begin, end = _event_window(cases)
        kline = collector.persist(
            ctx.target.query_kline_exchange(
                symbols, begin_date=begin, end_date=end, kline_type="DAY"
            )
        )
        return DomainData(
            domain=domain,
            status_rows=_rows(status),
            adj_rows=_rows(adj),
            kline_rows=_rows(kline),
            calendar_days=_calendar_days(calendar),
        )
    if domain == "BJ_MAPPING":
        # audit section 10: independent semantic proof - historical master
        # (code continuity) + exact-date status (BSE +/-30% regime)
        hist = collector.persist(
            ctx.target.get_hist_code_list_exchange("EXTRA_STOCK_A_SH_SZ", 19900101, 20991231)
        )
        dates = sorted(int(c.trade_date) for c in cases)
        status = collector.persist(
            ctx.target.get_history_stock_status_exchange(dates[0], dates[-1], symbols)
        )
        return DomainData(
            domain=domain,
            hist_code_rows=_rows(hist),
            status_rows=_rows(status),
        )
    msg = f"unknown domain {domain!r}"
    raise GoldenRoutingError(msg)


def validate_case_in_domain(
    case: GoldenCase, data: DomainData
) -> validators.ValidationOutcome:
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
                validator_version="2",
            )
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source}",
            actual="absent from historical code list (survivorship bias)",
            validator_id="delisted_master_v1",
            validator_version="2",
        )
    _ = in_basic
    return ValidationOutcome(
        result=CaseResult.OBSERVED,
        expected=f"{case.truth_source}",
        actual="listing-state expectation not 3; structural only",
        validator_id="delisted_master_v1",
        validator_version="2",
    )


def _status_row_exact(
    status_rows: list[dict[str, Any]], bare: str, trade_date: str
) -> tuple[list[dict[str, Any]], str]:
    """P0-08 (audit section 9.2): match status rows by (SECURITY_CODE,
    TRADE_DATE) EXACTLY. 0 rows and >1 rows are both structural failures
    (fail closed) - never "first match wins"."""
    matches = [
        r
        for r in status_rows
        if str(r.get("SECURITY_CODE", "")) == bare
        and str(r.get("TRADE_DATE", "")) == trade_date
    ]
    problem = ""
    if not matches:
        problem = f"no status row for ({bare}, {trade_date}) - exact match required"
    elif len(matches) > 1:
        problem = f"ambiguous: {len(matches)} status rows for ({bare}, {trade_date})"
    return matches, problem


def _validate_limit_pit(case: GoldenCase, data: DomainData) -> validators.ValidationOutcome:
    """Limit -> status EXACT trade_date + hist listing_date (same PIT
    context) + trade calendar + data-driven rule book (sections 8-9)."""
    bare = case.provider_symbol.split(".")[0]
    suffix = case.provider_symbol.split(".")[1] if "." in case.provider_symbol else "SH"
    matches, problem = _status_row_exact(data.status_rows or [], bare, case.trade_date)
    if problem:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=problem,
            reason_code="STATUS_EXACT_MATCH_FAILURE",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    row = matches[0]
    hist_row = next(
        (r for r in (data.hist_code_rows or []) if str(r.get("SECURITY_CODE", "")) == bare),
        None,
    )
    listing_date = str((hist_row or {}).get("LISTING_DATE", "") or "")
    if not listing_date:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=(
                "listing_date missing from PIT security-master context "
                "(audit section 9.2 - no None-default rule degradation)"
            ),
            reason_code="LISTING_DATE_MISSING",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    calendar = data.calendar_days or []
    if not calendar:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual="PIT trading calendar missing - first-N sessions undecidable",
            reason_code="CALENDAR_MISSING",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    is_st = str(row.get("IS_ST_SEC", "0")) in ("1", "1.0", "true", "True")
    try:
        rule = resolve_trading_rule(
            exchange=suffix,
            code=case.provider_symbol,
            trade_date=case.trade_date,
            is_st=is_st,
            listing_date=listing_date,
            calendar=calendar,
        )
    except RuleUnresolvedError as exc:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=f"RULE_UNRESOLVED: {exc}",
            reason_code="RULE_UNRESOLVED",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    # no-limit expectation (first-N sessions etc.)
    if rule.is_no_limit:
        provider_high = row.get("HIGH_LIMITED")
        if provider_high not in (None, "", "0", 0, "0.0", 0.0):
            return ValidationOutcome(
                result=CaseResult.VALIDATED_FAIL,
                expected=f"{case.truth_source} (no-limit session, rule={rule.rule_id})",
                actual=f"provider reports HIGH_LIMITED={provider_high!r}",
                reason_code="NO_LIMIT_CONTRADICTION",
                validator_id="limit_pit_rule_v2",
                validator_version="2",
            )
        return ValidationOutcome(
            result=CaseResult.VALIDATED_PASS,
            expected=case.truth_source,
            actual=f"no-limit session consistent (rule={rule.rule_id})",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    expected_up = case.expected_fields.get("PRICE_HIGH_LMT_RATE")
    expected_down = case.expected_fields.get("PRICE_LOW_LMT_RATE")
    up_mismatch = expected_up is not None and abs(float(rule.up_rate) - float(expected_up)) > 1e-9
    down_mismatch = (
        expected_down is not None and abs(float(rule.down_rate) - float(expected_down)) > 1e-9
    )
    if up_mismatch or down_mismatch:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} up={expected_up} down={expected_down}",
            actual=(
                f"PIT rule up={rule.up_rate} down={rule.down_rate} "
                f"({rule.rule_id}, {rule.effective_from}->{rule.effective_to})"
            ),
            reason_code="LIMIT_RATE_MISMATCH",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    # price consistency vs the rule's Decimal limit prices (1-tick tolerance)
    pre_close = row.get("PRECLOSE")
    provider_high = row.get("HIGH_LIMITED")
    provider_low = row.get("LOW_LIMITED")
    price_problem = ""
    if pre_close not in (None, "", 0, "0"):
        try:
            exp_up, exp_down = rule.limit_prices(str(pre_close))
            tick = float(rule.tick_size)
            if provider_high not in (None, "", 0, "0") and abs(
                float(provider_high) - float(exp_up)
            ) > tick + 1e-9:
                price_problem = (
                    f"HIGH_LIMITED {provider_high} != rule {exp_up} "
                    f"(preclose {pre_close}, rule {rule.rule_id})"
                )
            elif provider_low not in (None, "", 0, "0") and abs(
                float(provider_low) - float(exp_down)
            ) > tick + 1e-9:
                price_problem = (
                    f"LOW_LIMITED {provider_low} != rule {exp_down} "
                    f"(preclose {pre_close}, rule {rule.rule_id})"
                )
        except (TypeError, ValueError):
            price_problem = f"non-numeric preclose/high/low ({pre_close!r})"
    if price_problem:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (Decimal ROUND_HALF_UP limit prices)",
            actual=price_problem,
            reason_code="LIMIT_PRICE_MISMATCH",
            validator_id="limit_pit_rule_v2",
            validator_version="2",
        )
    return ValidationOutcome(
        result=CaseResult.VALIDATED_PASS,
        expected=case.truth_source,
        actual=(
            f"rate + price consistent (rule={rule.rule_id}, "
            f"preclose {pre_close} -> [{row.get('LOW_LIMITED')}, {row.get('HIGH_LIMITED')}])"
        ),
        validator_id="limit_pit_rule_v2",
        validator_version="2",
    )


def _validate_corp_action_context(
    case: GoldenCase, data: DomainData
) -> validators.ValidationOutcome:
    """Corp action T-1/T/T+1 REAL validation (audit section 9.3).

    Project definitions (documented in ADR-009 / DEVLOG):
      - exact event date: an adj-factor row has EX_DATE == T
      - factor transition location: factor(T-1 window) != factor(T window)
      - raw price discontinuity: when factor != 1 the raw return differs
        from the adjusted return (the ex-date jump is factor-explained)
      - adjusted continuity: |adj_ret| <= 35% (single-day adjusted move)
      - missing session / suspension: T-1/T/T+1 bars must exist; when the
        status rows flag suspension on the missing day the case is
        NOT_TESTABLE_TIME(SUSPENSION), never a silent PASS
    """
    bare = case.provider_symbol.split(".")[0]
    t_day = case.trade_date
    calendar = sorted(int(d) for d in (data.calendar_days or []))
    if not calendar or int(t_day) not in calendar:
        return ValidationOutcome(
            result=CaseResult.NOT_TESTABLE_TIME,
            expected=case.truth_source,
            actual=f"trade date {t_day} is not a calendar trading day (or calendar missing)",
            reason_code="CALENDAR_MISSING_EVENT_DAY",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    idx = calendar.index(int(t_day))
    if idx == 0 or idx == len(calendar) - 1:
        return ValidationOutcome(
            result=CaseResult.NOT_TESTABLE_TIME,
            expected=case.truth_source,
            actual="calendar does not bracket T-1/T+1",
            reason_code="CALENDAR_WINDOW_EDGE",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    t_prev = calendar[idx - 1]
    t_next = calendar[idx + 1]

    # event-day field expectation (IS_WD_SEC etc.) on the EXACT T row
    status_out = validators.validate_golden_cases(
        [case], [r for r in (data.status_rows or []) if str(r.get("TRADE_DATE", "")) == t_day]
    )[0]
    if status_out.result is CaseResult.VALIDATED_FAIL:
        return status_out

    # suspension semantics on T (audit section 9.3)
    status_t_rows = [
        r
        for r in (data.status_rows or [])
        if str(r.get("SECURITY_CODE", "")) == bare and str(r.get("TRADE_DATE", "")) == t_day
    ]
    suspended_t = any(
        str(r.get("IS_SUSP_SEC", "0")) in ("1", "1.0", "true", "True") for r in status_t_rows
    )

    # kline T-1/T/T+1 (exact-date rows for this symbol)
    kline_by_day: dict[str, dict[str, Any]] = {}
    for row in data.kline_rows or []:
        code = str(row.get("SECURITY_CODE", ""))
        if code == bare or code == case.provider_symbol:
            kline_by_day[str(row.get("KLINE_TIME", row.get("TRADE_DATE", "")))] = row
    missing = [d for d in (t_prev, int(t_day), t_next) if str(d) not in kline_by_day]
    if missing:
        if suspended_t:
            return ValidationOutcome(
                result=CaseResult.NOT_TESTABLE_TIME,
                expected=case.truth_source,
                actual=f"security suspended on event day; bars missing for {missing}",
                reason_code="SUSPENSION_AT_EVENT",
                validator_id="corp_action_context_v2",
                validator_version="2",
            )
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (kline T-1/T/T+1 required)",
            actual=f"kline rows missing for days {missing}",
            reason_code="KLINE_CONTEXT_MISSING",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )

    # exact event date + factor transition at T
    adj_rows = sorted(
        (
            r
            for r in (data.adj_rows or [])
            if str(r.get("SECURITY_CODE", "")) == bare
            and str(r.get("EX_DATE", "")).strip() != ""
        ),
        key=lambda r: str(r.get("EX_DATE", "")),
    )
    adj_at_t = [r for r in adj_rows if str(r.get("EX_DATE", "")) == t_day]
    if not adj_at_t:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (adj-factor row with EX_DATE == T)",
            actual="no adj-factor row at the event date (exact event date unproven)",
            reason_code="ADJ_EVENT_DATE_MISSING",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    factor_t = float(adj_at_t[0].get("EX_FACTOR", 0) or 0)
    before = [r for r in adj_rows if str(r.get("EX_DATE", "")) < t_day]
    factor_prev = float(before[-1].get("EX_FACTOR", 1) or 1) if before else 1.0
    if factor_t <= 0:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=f"non-positive EX_FACTOR {factor_t!r} at event date",
            reason_code="ADJ_FACTOR_INVALID",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    if factor_t == factor_prev:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (factor transition at T)",
            actual=f"factor did not change at T ({factor_prev} -> {factor_t})",
            reason_code="ADJ_NO_TRANSITION",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )

    # raw discontinuity + adjusted continuity
    try:
        close_prev = float(kline_by_day[str(t_prev)].get("CLOSE_PRICE", 0) or 0)
        close_t = float(kline_by_day[str(t_day)].get("CLOSE_PRICE", 0) or 0)
    except (TypeError, ValueError):
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual="non-numeric close prices in T-1/T kline rows",
            reason_code="KLINE_NUMERIC_INVALID",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    if close_prev <= 0 or close_t <= 0:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=f"non-positive closes (T-1={close_prev}, T={close_t})",
            reason_code="KLINE_CLOSE_INVALID",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    raw_ret = close_t / close_prev - 1
    adj_ret = (close_t * factor_t) / (close_prev * factor_prev) - 1
    if abs(adj_ret) > 0.35:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=f"adjusted continuity broken: adj_ret={adj_ret:.4f} (> 35%)",
            reason_code="ADJ_CONTINUITY_BROKEN",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    if factor_t != 1.0 and abs(raw_ret - adj_ret) < 1e-12:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=(
                f"raw return equals adjusted return ({raw_ret:.4f}) while factor != 1 - "
                "ex-date discontinuity unexplained"
            ),
            reason_code="RAW_DISCONTINUITY_UNEXPLAINED",
            validator_id="corp_action_context_v2",
            validator_version="2",
        )
    return ValidationOutcome(
        result=CaseResult.VALIDATED_PASS,
        expected=case.truth_source,
        actual=(
            f"event at T confirmed: factor {factor_prev}->{factor_t}, "
            f"raw_ret={raw_ret:.4f}, adj_ret={adj_ret:.4f} (continuity held)"
        ),
        validator_id="corp_action_context_v2",
        validator_version="2",
    )


def _validate_bj_mapping(case: GoldenCase, data: DomainData) -> validators.ValidationOutcome:
    """BJ/BSE independent semantic proof (audit section 10, P1).

    Two independent evidence legs (no BJ mapping endpoint assumed):
      1. historical security master: the BJ code exists (code continuity
         across the 2021-11-15 BSE opening migration)
      2. exact-date status row + data-driven rule book: the BSE +/-30%
         limit regime actually holds on the case's trade date
    """
    bare = case.provider_symbol.split(".")[0]
    suffix = case.provider_symbol.split(".")[1] if "." in case.provider_symbol else "BJ"
    hist_rows = [
        r for r in (data.hist_code_rows or []) if str(r.get("SECURITY_CODE", "")) == bare
    ]
    if not hist_rows:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (code continuity: {bare} in hist master)",
            actual="absent from historical security master - no continuity evidence",
            reason_code="BJ_MASTER_ABSENT",
            validator_id="bj_mapping_v2",
            validator_version="2",
        )
    matches, problem = _status_row_exact(data.status_rows or [], bare, case.trade_date)
    if problem:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=problem,
            reason_code="STATUS_EXACT_MATCH_FAILURE",
            validator_id="bj_mapping_v2",
            validator_version="2",
        )
    row = matches[0]
    provider_high = row.get("HIGH_LIMITED")
    if provider_high in (None, "", 0, "0", "0.0", 0.0):
        return ValidationOutcome(
            result=CaseResult.NOT_TESTABLE_TIME,
            expected=case.truth_source,
            actual="no-limit day (BSE listing-day regime) - limit regime not testable",
            reason_code="BJ_NO_LIMIT_DAY",
            validator_id="bj_mapping_v2",
            validator_version="2",
        )
    is_st = str(row.get("IS_ST_SEC", "0")) in ("1", "1.0", "true", "True")
    try:
        rule = resolve_limit_regime(
            exchange=suffix,
            code=case.provider_symbol,
            trade_date=case.trade_date,
            is_st=is_st,
        )
    except RuleUnresolvedError as exc:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=case.truth_source,
            actual=f"RULE_UNRESOLVED: {exc}",
            reason_code="RULE_UNRESOLVED",
            validator_id="bj_mapping_v2",
            validator_version="2",
        )
    if float(rule.up_rate) != 0.30 or float(rule.down_rate) != 0.30:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (BSE +/-30%)",
            actual=f"PIT rule resolved to {rule.up_rate}/{rule.down_rate} ({rule.rule_id})",
            reason_code="BJ_REGIME_MISMATCH",
            validator_id="bj_mapping_v2",
            validator_version="2",
        )
    pre_close = row.get("PRECLOSE")
    price_problem = ""
    if pre_close not in (None, "", 0, "0"):
        try:
            exp_up, exp_down = rule.limit_prices(str(pre_close))
            tick = float(rule.tick_size)
            if abs(float(provider_high) - float(exp_up)) > tick + 1e-9:
                price_problem = f"HIGH_LIMITED {provider_high} != rule {exp_up}"
        except (TypeError, ValueError):
            price_problem = f"non-numeric preclose/high ({pre_close!r})"
    if price_problem:
        return ValidationOutcome(
            result=CaseResult.VALIDATED_FAIL,
            expected=f"{case.truth_source} (BSE +/-30% Decimal prices)",
            actual=price_problem,
            reason_code="BJ_PRICE_MISMATCH",
            validator_id="bj_mapping_v2",
            validator_version="2",
        )
    return ValidationOutcome(
        result=CaseResult.VALIDATED_PASS,
        expected=case.truth_source,
        actual=(
            f"code continuity + BSE 30% regime proven "
            f"(high {provider_high} vs rule {rule.rule_id})"
        ),
        validator_id="bj_mapping_v2",
        validator_version="2",
    )


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Extract row dicts from any supported payload shape (frames/lists)."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        rows: list[dict[str, Any]] = []
        for value in payload.values():
            rows.extend(_rows(value))
        return rows
    if isinstance(payload, list):
        return [r if isinstance(r, dict) else {"value": r} for r in payload]
    rows_method = getattr(payload, "rows", None)
    if callable(rows_method):  # polars.DataFrame
        return [dict(zip(payload.columns, row, strict=True)) for row in rows_method()]
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):  # pandas.DataFrame
        return to_dict(orient="records")
    return [{"value": payload}]


def _flat(payload: Any) -> list[Any]:
    """Flatten a calendar payload (list of ints/strs, or frame)."""
    rows = _rows(payload)
    if rows and all(set(r.keys()) <= {"value"} for r in rows):
        return [r.get("value") for r in rows]
    return rows


def _calendar_days(payload: Any) -> list[int]:
    """Extract trading-day ints from any calendar payload shape
    (list[int] / list[str] / DataFrame / dict-of)."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        days: list[int] = []
        for value in payload.values():
            days.extend(_calendar_days(value))
        return sorted(set(days))
    if isinstance(payload, list):
        out: list[int] = []
        for item in payload:
            if isinstance(item, dict):
                for key in ("CAL_DATE", "TRADING_DATE", "TRADE_DATE", "CALENDAR_DATE"):
                    if key in item:
                        out.extend(_calendar_days([item[key]]))
                        break
                else:
                    out.extend(_calendar_days(list(item.values())))
            else:
                digits = "".join(ch for ch in str(item) if ch.isdigit())
                if len(digits) >= 8:
                    out.append(int(digits[:8]))
        return sorted(set(out))
    rows_method = getattr(payload, "rows", None)
    if callable(rows_method):  # polars.DataFrame
        return _calendar_days(
            [dict(zip(payload.columns, r, strict=True)) for r in rows_method()]
        )
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            records = to_dict(orient="records")
        except TypeError:
            records = None
        if records is not None:
            return _calendar_days(records)
    return _calendar_days([payload])


def _event_window(cases: list[GoldenCase]) -> tuple[int, int]:
    """Kline pull window around the case dates (calendar-day padding is
    only the PULL range - session logic uses the PIT calendar)."""
    dates = sorted(int(str(c.trade_date)) for c in cases)
    start = datetime.strptime(str(dates[0]), "%Y%m%d") - timedelta(days=15)
    end = datetime.strptime(str(dates[-1]), "%Y%m%d") + timedelta(days=15)
    return int(start.strftime("%Y%m%d")), int(end.strftime("%Y%m%d"))


# ------------------------------------------------------------------ router


def _failure_outcome(
    exc: ProviderError, case: GoldenCase
) -> validators.ValidationOutcome:
    """Domain-level failure classification (same mapping as ProbeExecutor)."""
    if isinstance(exc, ProviderPermissionError):
        result = CaseResult.NOT_TESTABLE_PERMISSION
        reason = "PROVIDER_PERMISSION"
    elif isinstance(exc, ProviderRateLimitError):
        result = CaseResult.NOT_TESTABLE_ACCOUNT
        reason = "PROVIDER_RATE_LIMIT"
    elif isinstance(exc, ProviderSchemaError):
        result = CaseResult.VALIDATED_FAIL
        reason = "PROVIDER_SCHEMA"
    else:
        result = CaseResult.MISSING
        reason = "PROVIDER_INTERNAL"
    return ValidationOutcome(
        result=result,
        expected=case.truth_source,
        actual=f"{type(exc).__name__}: {exc}"[:300],
        reason_code=reason,
        validator_id="golden_router_domain_fetch",
        validator_version="2",
    )


def route_all(
    ctx: Any, cases: list[GoldenCase]
) -> list[tuple[GoldenCase, validators.ValidationOutcome, dict[str, Any]]]:
    """Route + validate every golden case through its domain.

    R4-A2.3 P0-04 (audit section 6): each domain fetch persists its
    exchanges via the RawWriter FIRST, DomainData comes from those exact
    payloads, and every case binds to the domain evidence bundle - the
    validation data and the evidence are the SAME provider exchanges.
    """
    by_domain: dict[str, list[GoldenCase]] = {}
    for case in cases:
        by_domain.setdefault(route_golden_case(case), []).append(case)
    outcomes: list[tuple[GoldenCase, validators.ValidationOutcome, dict[str, Any]]] = []
    for domain, domain_cases in sorted(by_domain.items()):
        collector = _DomainCollector(ctx, domain)
        try:
            data = fetch_domain_data(ctx, domain, domain_cases, collector)
        except ProviderError as exc:
            # the failed exchange is a first-class object: persist it into
            # the same bundle, then classify every case of the domain
            collector.persist_failure(
                exc, endpoint="domain_fetch", dataset=f"golden_{domain.lower()}"
            )
            evidence = collector.bundle_evidence()
            for case in domain_cases:
                outcomes.append((case, _failure_outcome(exc, case), evidence))
            continue
        evidence = collector.bundle_evidence()
        for case in domain_cases:
            outcomes.append((case, validate_case_in_domain(case, data), evidence))
    return outcomes
