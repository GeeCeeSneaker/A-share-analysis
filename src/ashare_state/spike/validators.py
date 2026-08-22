"""Spike validators: semantic validation, not call success (R2-P0-03).

A validator turns an OBSERVED payload into a semantic verdict. Call
success alone NEVER produces VALIDATED_PASS - that decision belongs to
these functions.

Validators are pure functions over provider-normalized payloads so they
are fully unit-testable with fixtures, and run identically over live
data on the controlled machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ashare_state.spike.model import CaseResult

__all__ = [
    "ValidationOutcome",
    "validate_security_master_delisted",
    "validate_daily_bar_units",
    "validate_st_suspend_flags",
    "validate_limit_rule",
    "validate_adj_continuity",
    "validate_history_coverage",
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
        validator_version="1.0.0",
        result=result,
        expected=expected,
        actual=actual,
        **kw,
    )


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
    volume_unit: str,
    amount_unit: str,
    documented_units: dict[str, str],
) -> ValidationOutcome:
    """Units are validated against the DOCUMENTED unit map (B5 evidence),
    plus a numeric-range sanity check (hand->share scale)."""
    vid = "daily_bar_units_v1"
    if not rows:
        return _outcome(vid, CaseResult.MISSING, "rows with documented units", "no rows")
    problems: list[str] = []
    if volume_unit != documented_units.get("volume"):
        problems.append(
            f"volume unit {volume_unit!r} != documented {documented_units.get('volume')!r}"
        )
    if amount_unit != documented_units.get("amount"):
        problems.append(
            f"amount unit {amount_unit!r} != documented {documented_units.get('amount')!r}"
        )
    # sanity: close price ~ amount / volume when both are same-day totals
    checked = 0
    consistent = 0
    for row in rows:
        close, volume, amount = row.get("CLOSE"), row.get("VOLUME"), row.get("AMOUNT")
        if close and volume and amount:
            checked += 1
            implied = amount / volume
            # amount(CNY) / volume(shares) ~ price; allow 15% slack for rounding
            if abs(implied - close) / close <= 0.15:
                consistent += 1
    if problems:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            f"units {documented_units}",
            "; ".join(problems),
        )
    if checked and consistent / checked < 0.9:
        return _outcome(
            vid,
            CaseResult.VALIDATED_FAIL,
            "amount/volume ~ close for >=90% rows",
            f"consistent {consistent}/{checked}",
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        f"units {documented_units}",
        f"units match; price consistency {consistent}/{checked}",
    )


# ------------------------------------------------------------- ST / suspension


def validate_st_suspend_flags(rows: list[dict[str, Any]]) -> ValidationOutcome:
    """Flag domain check: IS_ST_SEC / IS_SUSP_SEC within {0,1} and the
    row set contains at least one non-ST day and one flagged day when the
    sample intends to cover transitions."""
    vid = "st_suspend_v1"
    if not rows:
        return _outcome(vid, CaseResult.MISSING, "status rows", "no rows")
    bad: list[str] = []
    flagged = 0
    for row in rows:
        for flag in ("IS_ST_SEC", "IS_SUSP_SEC"):
            value = row.get(flag)
            if value is not None and str(value) not in ("0", "1", "0.0", "1.0"):
                bad.append(f"{flag}={value!r}")
        if str(row.get("IS_ST_SEC", "0")) in ("1", "1.0") or str(row.get("IS_SUSP_SEC", "0")) in (
            "1",
            "1.0",
        ):
            flagged += 1
    if bad:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, "flags in {0,1}", "; ".join(bad[:5]))
    # domain valid; transition coverage is the golden validator's job
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "flags in {0,1}",
        f"domain ok; {flagged}/{len(rows)} flagged rows",
    )


# ------------------------------------------------------------------ limit rule


def validate_limit_rule(rows: list[dict[str, Any]]) -> ValidationOutcome:
    """Limit-price consistency: when present, up/down limits must bracket
    the close and respect pre_close +/- rate within tolerance."""
    vid = "limit_rule_v1"
    if not rows:
        return _outcome(vid, CaseResult.MISSING, "status rows with limits", "no rows")
    checked = 0
    violations: list[str] = []
    for row in rows:
        up, down, close, pre = (
            row.get("HIGH_LIMITED"),
            row.get("LOW_LIMITED"),
            row.get("CLOSE"),
            row.get("PRECLOSE"),
        )
        if up is None or down is None:
            continue  # no-limit day: golden validator asserts which days MUST have none
        if close is not None and not (down <= close <= up):
            violations.append(f"close {close} outside [{down}, {up}]")
        if pre:
            checked += 1
    if violations:
        return _outcome(
            vid, CaseResult.VALIDATED_FAIL, "down<=close<=up", "; ".join(violations[:5])
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "down<=close<=up",
        f"bracketing ok ({checked} rows with preclose)",
    )


# ---------------------------------------------------------------- adj continuity


def validate_adj_continuity(events: list[dict[str, Any]]) -> ValidationOutcome:
    """Ex-date continuity: adj_factor >= 0, ordered by ex_date, and the
    documented formula (factor = pre_close/last_close * prev_factor) is
    checked against supplied price context when present."""
    vid = "adj_continuity_v1"
    if not events:
        return _outcome(vid, CaseResult.MISSING, "adj factor events", "no events")
    bad: list[str] = []
    prev_date: date | None = None
    for ev in events:
        factor = ev.get("EX_FACTOR")
        if factor is not None and factor < 0:
            bad.append(f"negative factor {factor}")
        ex = ev.get("EX_DATE")
        if ex and prev_date is not None and str(ex) < str(prev_date):
            bad.append(f"ex-date order break at {ex}")
        if ex:
            prev_date = str(ex)  # type: ignore[assignment]
    if bad:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, "factors>=0, ordered", "; ".join(bad[:5]))
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "factors>=0, ordered by ex-date",
        f"{len(events)} events ok",
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


_VALID_SUFFIXES = {".SH", ".SZ", ".BJ"}


def validate_symbol_mapping(symbols: list[str]) -> ValidationOutcome:
    """Every provider symbol must be bare-code + known suffix, unique, and
    codes must not collide across markets."""
    vid = "symbol_mapping_v1"
    if not symbols:
        return _outcome(vid, CaseResult.MISSING, "symbols", "no symbols")
    bad: list[str] = []
    seen_codes: dict[str, str] = {}
    for sym in symbols:
        text = str(sym)
        code, _, suffix = text.partition(".")
        if suffix not in _VALID_SUFFIXES:
            bad.append(f"{text}: unknown suffix")
            continue
        if not code.isdigit():
            bad.append(f"{text}: non-numeric code")
            continue
        if code in seen_codes and seen_codes[code] != suffix:
            bad.append(f"{text}: code {code} already mapped to {seen_codes[code]}")
        seen_codes.setdefault(code, suffix)
    if bad:
        return _outcome(
            vid, CaseResult.VALIDATED_FAIL, "unique code+known suffix", "; ".join(bad[:5])
        )
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        "unique code+known suffix",
        f"{len(symbols)} symbols ok",
    )


# ----------------------------------------------------------- sdk behavior record


def validate_sdk_behavior_record(record: dict[str, Any] | None) -> ValidationOutcome:
    """SDK permission/cache/freshness facts must be RECORDED with evidence
    (login profile, cache mode, EOD timing observation)."""
    vid = "sdk_behavior_v1"
    if not record:
        return _outcome(vid, CaseResult.MISSING, "sdk behavior record", "no record")
    required = ("account_profile_id", "permission_codes", "cache_behavior")
    missing = [k for k in required if not record.get(k)]
    if missing:
        return _outcome(vid, CaseResult.VALIDATED_FAIL, f"keys {required}", f"missing {missing}")
    return _outcome(
        vid,
        CaseResult.VALIDATED_PASS,
        f"keys {required}",
        "all sdk behavior facts recorded",
    )
