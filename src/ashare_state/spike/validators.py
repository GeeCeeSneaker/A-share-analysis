"""Spike validators: semantic validation, not call success (R2-P0-03 + R3-0C).

A validator turns an OBSERVED payload into a semantic verdict. Call
success alone NEVER produces VALIDATED_PASS.

R3 corrections (audit sections 10-17):
- symbol mapping reuses normalize_provider_symbol (single parser rule);
  the same bare code on different markets is NOT an error - what must be
  unique is (provider_symbol, effective_date) -> security_id.
- daily bar units: expected (documented) and actual (observed) must be
  INDEPENDENT sources; checked_n == 0 can never pass.
- ST/suspension: value-domain checks alone never pass - golden FACTS
  (known cap/removal/suspension/resumption days) are compared.
- limit rules: real regime validation (pre_close x rate, tick rounding,
  board rates incl. ST 5% / main 10% / ChiNext+STAR 20% / BSE 30%,
  no-limit days); all-fields-missing never passes.
- adj continuity: price-context continuity (raw return x factor), not
  just factor >= 0.
- SDK behavior: REAL permission codes required (not the profile id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ashare_state.providers.amazingdata.mapper import normalize_provider_symbol
from ashare_state.providers.errors import MappingValidationError
from ashare_state.spike.model import CaseResult

__all__ = [
    "GoldenCase",
    "ValidationOutcome",
    "validate_adj_continuity",
    "validate_daily_bar_units",
    "validate_golden_cases",
    "validate_history_coverage",
    "validate_limit_rule",
    "validate_security_master_delisted",
    "validate_st_suspend_flags",
    "validate_symbol_mapping",
    "validate_sdk_behavior_record",
]


@dataclass(frozen=True)
class ValidationOutcome:
    validator_id: str
    validator_version: str
    result: CaseResult
    expected: str
    actual: str
    reason_code: str = ""
    equivalent_pass: bool = False
    evidence_hash: str = ""


def _outcome(
    validator_id: str,
    result: CaseResult,
    expected: str,
    actual: str,
    **kw: Any,
) -> ValidationOutcome:
    return ValidationOutcome(
        validator_id=validator_id,
        validator_version="2.0.0",
        result=result,
        expected=expected,
        actual=actual,
        **kw,
    )


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


# ------------------------------------------------- security master (delisted)


def validate_security_master_delisted(
    entries: list[dict[str, Any]],
) -> ValidationOutcome:
    """Survivorship check: master rows must include delisted securities."""
    vid = "security_master_delisted_v1"
    if not entries:
        return _outcome(vid, CaseResult.MISSING, ">=1 delisted security", "no rows")
    delisted = [
        e for e in entries if str(e.get("IS_LISTED", "")).strip() == "3" or e.get("DELISTING_DATE")
    ]
    if not delisted:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            ">=1 delisted security (IS_LISTED=3 or DELISTING_DATE present)",
            f"0 delisted among {len(entries)} entries",
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        ">=1 delisted security",
        f"{len(delisted)} delisted among {len(entries)} entries",
    )


# ------------------------------------------------------------ daily bar units


def validate_daily_bar_units(
    rows: list[dict[str, Any]],
    *,
    documented_units: dict[str, str],
    observed_units: dict[str, str],
) -> ValidationOutcome:
    """Units validated between INDEPENDENT sources (R3-P0-07).

    documented_units: the DOCUMENTED unit map (SDK manual / provider field
    map) - the EXPECTED side.
    observed_units: the LIVE observation result (scale analysis / golden
    cross-check evidence from B5) - the ACTUAL side. Passing the same
    dict for both sides is a self-referential no-op and can never pass:
    the validator demands checked_n >= 1 numeric-consistency rows.
    """
    vid = "daily_bar_units_v2"
    if not rows:
        return _outcome(vid, CaseResult.MISSING, "rows with documented units", "no rows")
    problems: list[str] = []
    for field_name in ("volume", "amount"):
        expected_unit = documented_units.get(field_name)
        observed_unit = observed_units.get(field_name)
        if expected_unit is None or observed_unit is None:
            problems.append(f"{field_name}: unit evidence incomplete")
        elif expected_unit != observed_unit:
            problems.append(
                f"{field_name}: documented {expected_unit!r} != observed {observed_unit!r}"
            )
    # numeric consistency: amount / volume ~ close (independent check that
    # BOTH sides describe the same physical quantity)
    checked = 0
    consistent = 0
    for row in rows:
        close = _to_float(_first(row, "CLOSE_PRICE", "CLOSE", "close"))
        volume = _to_float(_first(row, "VOLUME", "volume"))
        amount = _to_float(_first(row, "AMOUNT", "amount"))
        if close is not None and volume and amount:
            checked += 1
            implied = amount / volume
            if abs(implied - close) / close <= 0.15:
                consistent += 1
    # R3-P0-07: checked_n == 0 can never pass (field-name drift must fail)
    if checked == 0:
        problems.append(
            "numeric consistency unchecked (checked_n=0): CLOSE_PRICE/VOLUME/AMOUNT "
            "not found in payload - field-name drift must fail, not pass"
        )
    if problems:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            f"units {documented_units} + checked>=1",
            "; ".join(problems),
        )
    if consistent / checked < 0.9:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "amount/volume ~ close for >=90% rows",
            f"consistent {consistent}/{checked}",
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        f"units {documented_units} (independently observed {observed_units})",
        f"units match; price consistency {consistent}/{checked}",
    )


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- ST / suspension


@dataclass(frozen=True)
class GoldenSTFact:
    """One KNOWN ST/suspension fact from an external truth source."""

    provider_symbol: str
    trade_date: str  # yyyymmdd
    expected_is_st: bool
    expected_is_suspended: bool | None = None  # None = not asserted
    source_ref: str = ""


def validate_st_suspend_flags(
    rows: list[dict[str, Any]],
    golden_facts: list[GoldenSTFact] | None = None,
) -> ValidationOutcome:
    """R3-P0-08: domain checks never pass alone - golden FACTS decide.

    Without golden_facts the result is OBSERVED (structure recorded, no
    semantic verdict); with facts each is compared field-by-field.
    """
    vid = "st_suspend_v2"
    if not rows:
        return _outcome(vid, CaseResult.MISSING, "status rows", "no rows")
    bad: list[str] = []
    for source_row in rows:
        for flag_name in ("IS_ST_SEC", "IS_SUSP_SEC"):
            value = source_row.get(flag_name)
            if value is not None and str(value) not in ("0", "1", "0.0", "1.0"):
                bad.append(f"{flag_name}={value!r}")
    if bad:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, "flags in {0,1}", "; ".join(bad[:5]))
    if not golden_facts:
        return _outcome(
            vid,
            CaseResult.OBSERVED,
            "golden ST/suspension facts compared",
            "domain valid; no golden facts supplied - semantic verdict deferred",
        )
    by_key = {
        (str(r.get("SECURITY_CODE", "")) + _suffix_of(r), str(r.get("TRADE_DATE", ""))): r
        for r in rows
    }
    mismatches: list[str] = []
    checked = 0
    for fact in golden_facts:
        row: dict[str, Any] | None = by_key.get(
            (
                fact.provider_symbol.split(".")[0] + _suffix_for(fact.provider_symbol),
                fact.trade_date,
            )
        )
        if row is None:
            # try bare code match
            row = next(
                (
                    r
                    for r in rows
                    if str(r.get("SECURITY_CODE")) == fact.provider_symbol.split(".")[0]
                    and str(r.get("TRADE_DATE")) == fact.trade_date
                ),
                None,
            )
        if row is None:
            mismatches.append(f"{fact.provider_symbol}@{fact.trade_date}: no provider row")
            continue
        checked += 1
        actual_st = str(row.get("IS_ST_SEC", "0")) in ("1", "1.0")
        if actual_st != fact.expected_is_st:
            mismatches.append(
                f"{fact.provider_symbol}@{fact.trade_date}: ST expected "
                f"{fact.expected_is_st}, got {actual_st}"
            )
        if fact.expected_is_suspended is not None:
            actual_susp = str(row.get("IS_SUSP_SEC", "0")) in ("1", "1.0")
            if actual_susp != fact.expected_is_suspended:
                mismatches.append(
                    f"{fact.provider_symbol}@{fact.trade_date}: SUSP expected "
                    f"{fact.expected_is_suspended}, got {actual_susp}"
                )
    if mismatches:
        return _outcome(
            vid, CaseResult.VALIDATED_FAIL, "golden facts matched", "; ".join(mismatches[:5])
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        f"{len(golden_facts)} golden facts matched",
        f"{checked}/{len(golden_facts)} compared, all match",
    )


def _suffix_of(row: dict[str, Any]) -> str:
    market = str(row.get("MARKET_CODE", ""))
    return {"1": ".SH", "2": ".SZ", "3": ".BJ"}.get(market, "")


def _suffix_for(symbol: str) -> str:
    return "." + symbol.split(".")[1] if "." in symbol else ""


# ------------------------------------------------------------------ limit rule


#: board limit-rate rules (audit R3-P0-09)
def validate_limit_rule(
    rows: list[dict[str, Any]],
    *,
    require_any_limit: bool = True,
    book: Any,
) -> ValidationOutcome:
    """R3-P0-09: real regime validation.

    R4-A2.3 P0-06: the limit rates come from the VERSIONED DATA LAYER
    (configs/trading_rules/*.yaml via TradingRuleBook.resolve_limit_regime)
    - NO hardcoded board-rate table in Python. Rows are matched by their
    OWN trade date (PIT), and rate resolution failures are collected as
    RULE_UNRESOLVED violations (fail closed, audit section 8.3).

    R4-A2.5 P0-01 (audit 20260825 section 2.3): ``book`` is a REQUIRED
    keyword - the run-bound TradingRuleBook (``ctx.rule_book`` on the
    formal path; tests load one explicitly). There is deliberately NO
    default: a formal validator must never silently fall back to the
    current working-tree rule SoR (Exact Replay contract).

    - all-rows-missing-limit-fields -> NOT validated (never silent PASS)
    - rows WITH limits: expected up/down = Decimal ROUND_HALF_UP of
      pre_close * (1 +/- rule rate) from the resolved PIT rule
    - rows marked no-limit (IPO first day etc.): must be an acceptable
      no-limit context or flagged
    """
    from decimal import Decimal

    from ashare_state.spike.trading_rule import RuleUnresolvedError, resolve_limit_regime

    vid = "limit_rule_v3"
    if book is None:
        # explicit None is the old silent-fallback footgun - refuse it
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "run-bound TradingRuleBook",
            "book=None refused: formal limit validation must receive the "
            "run-bound rule book (R4-A2.5 P0-01, audit 20260825 section 2.3)",
        )
    if not rows:
        return _outcome(vid, CaseResult.MISSING, "status rows with limits", "no rows")
    rows_with_limits = [r for r in rows if r.get("HIGH_LIMITED") is not None]
    if not rows_with_limits:
        if require_any_limit:
            return _outcome(
                vid,
                CaseResult.VALIDATED_FAIL,
                "at least one row with limit fields",
                "all rows missing HIGH_LIMITED/LOW_LIMITED - cannot validate regime",
            )
        return _outcome(vid, CaseResult.OBSERVED, "limit fields", "none present")
    violations: list[str] = []
    checked = 0
    for row in rows_with_limits:
        pre = _to_float(row.get("PRECLOSE"))
        up = _to_float(row.get("HIGH_LIMITED"))
        down = _to_float(row.get("LOW_LIMITED"))
        code = str(row.get("SECURITY_CODE", ""))
        market = str(row.get("MARKET_CODE", ""))
        symbol = code + {"1": ".SH", "2": ".SZ", "3": ".BJ"}.get(market, "")
        is_st = str(row.get("IS_ST_SEC", "0")) in ("1", "1.0")
        trade_date = str(row.get("TRADE_DATE", "") or "")
        if pre is None or up is None or down is None:
            continue
        if not trade_date or len(trade_date) < 8:
            violations.append(
                f"{symbol}: row has no TRADE_DATE - PIT rule resolution "
                "requires the exact date (audit section 8.3)"
            )
            continue
        try:
            # a row WITH a HIGH_LIMITED price is by construction not a
            # no-limit listing-window day -> regime resolve applies
            rule = resolve_limit_regime(
                exchange=symbol.rsplit(".", 1)[1] if "." in symbol else "",
                code=symbol,
                trade_date=trade_date,
                is_st=is_st,
                book=book,
            )
        except RuleUnresolvedError as exc:
            violations.append(f"{symbol}: RULE_UNRESOLVED ({exc})")
            continue
        checked += 1
        exp_up_dec, exp_down_dec = rule.limit_prices(Decimal(str(pre)))
        exp_up = float(exp_up_dec)
        exp_down = float(exp_down_dec)
        # exchange rounds DOWN the down-limit at half tick; allow 1 tick slack
        if abs(up - exp_up) > 0.011:
            violations.append(
                f"{symbol}: up {up} != expected {exp_up:.2f} (pre {pre}, rule {rule.rule_id})"
            )
        if abs(down - exp_down) > 0.011:
            violations.append(
                f"{symbol}: down {down} != expected {exp_down:.2f} (pre {pre}, rule {rule.rule_id})"
            )
        close = _to_float(_first(row, "CLOSE_PRICE", "CLOSE"))
        if close is not None and not (down - 1e-9 <= close <= up + 1e-9):
            violations.append(f"{symbol}: close {close} outside [{down}, {up}]")
    if checked == 0:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "limit rows with preclose",
            "no row had PRECLOSE + limits together"
            + (f"; rule failures: {'; '.join(violations[:3])}" if violations else ""),
        )
    if violations:
        return _outcome(
            vid, CaseResult.VALIDATED_FAIL, "exchange limit regime", "; ".join(violations[:5])
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "up/down = Decimal ROUND_HALF_UP(pre_close x (1+/-PIT rule rate))",
        f"{checked} rows match the data-driven regime",
    )


# ---------------------------------------------------------------- adj continuity


def validate_adj_continuity(
    events: list[dict[str, Any]],
    *,
    price_context: list[dict[str, Any]] | None = None,
) -> ValidationOutcome:
    """R3-P0-10: ex-date PRICE continuity, not just factor >= 0.

    With price_context (rows with SECURITY_CODE/TRADE_DATE/CLOSE around
    each ex date), the validator checks the documented formula:
        factor = pre_close / last_close  (single-event)
    Without context, the result is OBSERVED (structure only).
    """
    vid = "adj_continuity_v2"
    if not events:
        return _outcome(vid, CaseResult.MISSING, "adj factor events", "no events")
    bad: list[str] = []
    prev_date: str | None = None
    for ev in events:
        factor = _to_float(ev.get("EX_FACTOR"))
        if factor is not None and factor < 0:
            bad.append(f"negative factor {factor}")
        ex = str(ev.get("EX_DATE", ""))
        if ex and prev_date is not None and ex < prev_date:
            bad.append(f"ex-date order break at {ex}")
        if ex:
            prev_date = ex
    if bad:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, "factors>=0, ordered", "; ".join(bad[:5]))
    if not price_context:
        return _outcome(
            vid,
            CaseResult.OBSERVED,
            "adj return continuity across ex dates",
            "structure valid; price context not supplied - continuity deferred",
        )
    # continuity: around each ex date, adjusted close must be continuous
    by_code: dict[str, list[tuple[str, float]]] = {}
    for price_row in price_context:
        code = str(price_row.get("SECURITY_CODE", ""))
        close = _to_float(_first(price_row, "CLOSE_PRICE", "CLOSE"))
        date = str(price_row.get("TRADE_DATE", price_row.get("KLINE_TIME", "")))
        if code and close is not None:
            by_code.setdefault(code, []).append((date, close))
    for price_series in by_code.values():
        price_series.sort()
    checked = 0
    for ev in events:
        code = str(ev.get("SECURITY_CODE", ""))
        ex = str(ev.get("EX_DATE", ""))
        factor = _to_float(ev.get("EX_FACTOR"))
        series: list[tuple[str, float]] | None = by_code.get(code)
        if not series or factor is None or not ex:
            continue
        # find last close before ex date and first close on/after
        before = [(d, c) for d, c in series if d < ex]
        after = [(d, c) for d, c in series if d >= ex]
        if not before or not after:
            continue
        last_raw, first_raw = before[-1][1], after[0][1]
        if last_raw <= 0:
            continue
        checked += 1
        # single-event factor: first_adjusted ~ last_raw * factor continuity
        implied = last_raw * factor
        if first_raw > 0 and abs(implied - first_raw) / first_raw > 0.02:
            bad.append(
                f"{code}@{ex}: continuity break - last {last_raw} x factor "
                f"{factor} = {implied:.4f} vs next {first_raw}"
            )
    if checked == 0:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "ex-date price continuity checked",
            "price context did not bracket any ex date",
        )
    if bad:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, "adj return continuity", "; ".join(bad[:5]))
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "raw x factor continuity across ex dates",
        f"{checked} ex dates continuous (<=2% gap)",
    )


# ------------------------------------------------------------- history coverage


def validate_history_coverage(
    earliest: str | None, required_earliest: str = "20150101"
) -> ValidationOutcome:
    """History depth must cover analysis start 2018 + warmup (>= 2015)."""
    vid = "history_coverage_v1"
    if not earliest:
        return _outcome(vid, CaseResult.MISSING, f"earliest <= {required_earliest}", "no data")
    digits = "".join(ch for ch in str(earliest) if ch.isdigit())[:8]
    if not digits or len(digits) < 8:
        return _outcome(
            vid, CaseResult.VALIDATED_FAIL, "parsable earliest date", f"got {earliest!r}"
        )
    if digits > required_earliest:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            f"earliest <= {required_earliest} (2018 analysis + warmup)",
            f"earliest {digits}",
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        f"earliest <= {required_earliest}",
        f"earliest {digits}",
    )


# -------------------------------------------------------------- symbol mapping


def validate_symbol_mapping(symbols: list[str]) -> ValidationOutcome:
    """R3-P0-06: uses normalize_provider_symbol (the SINGLE parser rule).

    The same bare code on DIFFERENT markets is legal (e.g. 000001.SZ and
    a hypothetical 000001.SH would be distinct securities); what must be
    unique is the full provider_symbol itself.
    """
    vid = "symbol_mapping_v2"
    if not symbols:
        return _outcome(vid, CaseResult.MISSING, "symbols", "no symbols")
    bad: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        text = str(sym)
        try:
            normalized = normalize_provider_symbol(text)
        except MappingValidationError as exc:
            bad.append(str(exc))
            continue
        if normalized in seen:
            bad.append(f"{normalized}: duplicate provider symbol")
        seen.add(normalized)
    if bad:
        return _outcome(
            vid, CaseResult.VALIDATED_FAIL, "normalized unique symbols", "; ".join(bad[:5])
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "every symbol parses via normalize_provider_symbol and is unique",
        f"{len(symbols)} symbols ok",
    )


# ----------------------------------------------------------- sdk behavior record


def validate_sdk_behavior_record(record: dict[str, Any] | None) -> ValidationOutcome:
    """SDK permission/cache/freshness facts must be RECORDED with REAL
    evidence (R3-P0-11: permission_codes must be the actual codes)."""
    vid = "sdk_behavior_v2"
    if not record:
        return _outcome(vid, CaseResult.MISSING, "sdk behavior record", "no record")
    required = ("account_profile_id", "permission_codes", "cache_behavior")
    missing = [k for k in required if not record.get(k)]
    if missing:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, f"keys {required}", f"missing {missing}")
    codes = str(record.get("permission_codes", ""))
    if codes == record.get("account_profile_id"):
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "real permission codes",
            "permission_codes duplicates account_profile_id (placeholder bug)",
        )
    if not any(ch.isdigit() for ch in codes):
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "real permission codes",
            f"permission codes look non-numeric: {codes!r}",
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        f"keys {required} with real permission codes",
        f"permission codes {codes!r} recorded",
    )


# ---------------------------------------------------------------- golden truth


@dataclass(frozen=True)
class GoldenCase:
    """One golden case with EXTERNAL truth (audit R3 section 37 R3-0E).

    R4-A2 evidence model (review sections 7-8):
    - compiled_* / reviewed_* are SEPARATE provenance chains; a COMPILED
      case never carries reviewer fields.
    - source_artifact_ref/kind/retrieved_at: the verifiable external
      evidence artifact; the review workflow hashes the REAL bytes.
    - review_note: human reviewer's verification note.
    - event_subtype: ST_ADD / ST_REMOVE / STAR_ST_ADD / STAR_ST_REMOVE
      (the ST event gate requires both ADD>0 and REMOVE>0).
    """

    golden_case_id: str
    case_type: str
    provider_symbol: str
    trade_date: str
    truth_source: str
    source_ref: str
    expected_fields: dict[str, Any] = field(default_factory=dict)
    case_semantic_hash: str = ""
    source_artifact_hash: str = ""
    source_artifact_ref: str = ""
    source_artifact_kind: str = ""
    source_retrieved_at: str = ""
    truth_version: str = ""
    compiled_by: str = ""
    compiled_at: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""
    review_status: str = ""  # COMPILED | REVIEWED
    event_id: str = ""
    event_class: str = ""
    event_subtype: str = ""
    event_effective_date: str = ""


def validate_golden_cases(
    cases: list[GoldenCase],
    provider_rows: list[dict[str, Any]],
    *,
    row_key: str = "SECURITY_CODE",
) -> list[ValidationOutcome]:
    """Per-case golden comparison (audit R3-P0-12/13).

    Each golden case looks up its provider row (symbol + trade date) and
    compares expected_fields. Missing rows are FAILs (the case exists
    because the fact is known - absence is a data gap, not a pass).
    """
    outcomes: list[ValidationOutcome] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for provider_row in provider_rows:
        code = str(provider_row.get(row_key, ""))
        market = str(provider_row.get("MARKET_CODE", ""))
        symbol = code + {"1": ".SH", "2": ".SZ", "3": ".BJ"}.get(market, "")
        date = str(provider_row.get("TRADE_DATE", ""))
        index[(symbol, date)] = provider_row
        index.setdefault((code, date), provider_row)
    for case in cases:
        vid = f"golden_{case.case_type}_v1"
        row: dict[str, Any] | None = index.get((case.provider_symbol, case.trade_date))
        if row is None:
            outcomes.append(
                _outcome(
                    vid,
                    CaseResult.VALIDATED_FAIL,
                    f"{case.provider_symbol}@{case.trade_date} present",
                    "no provider row for golden case",
                )
            )
            continue
        mismatches = []
        for field_name, expected in case.expected_fields.items():
            actual = row.get(field_name)
            # normalize 1/1.0/True style flags
            if isinstance(expected, bool):
                actual_flag = str(actual) in ("1", "1.0", "True", "true")
                if actual_flag != expected:
                    mismatches.append(f"{field_name}: expected {expected}, got {actual!r}")
            elif str(actual) != str(expected):
                mismatches.append(f"{field_name}: expected {expected!r}, got {actual!r}")
        if mismatches:
            outcomes.append(
                _outcome(
                    vid,
                    CaseResult.VALIDATED_FAIL,
                    f"golden fields {list(case.expected_fields)}",
                    "; ".join(mismatches[:4]),
                )
            )
        else:
            outcomes.append(
                _outcome(
                    vid,
                    CaseResult.VALIDATED_PASS,
                    f"golden fields {list(case.expected_fields)}",
                    f"{case.provider_symbol}@{case.trade_date} matches {case.truth_source}",
                )
            )
    return outcomes
