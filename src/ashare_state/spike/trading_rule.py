"""PIT trading-rule resolution (R4-P0-15 hardened; R4-A2.3 section 8).

Institutional FACTS (rates / tick / effective windows / board patterns)
live in ``configs/trading_rules/*.yaml`` - a versioned, reviewable data
layer. This module only: load, validate, PIT-match, conflict-detect,
resolve, and compute Decimal limit prices.

Fail-closed contract (audit R4-A2.3 section 8.3):
  - 0 matching rules                 -> RuleUnresolvedError
  - >1 equally-valid rules           -> RuleUnresolvedError
  - unknown board / exchange         -> RuleUnresolvedError
  - first-N-session determination requires listing_date + a PIT trading
    calendar; a missing calendar row NEVER falls back to calendar-day
    approximation (no "calendar days * 2" shortcuts)
  - RULE_UNRESOLVED blocks the case; it never silently degrades to
    "MAIN 10%".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

_LISTING_AGE_RULES = ("NONE", "FIRST_5_DAYS_NO_LIMIT", "IPO_DAY_44_36")
_ROUNDING_MODES = ("ROUND_HALF_UP",)

#: default rule data location (repo-relative; override for tests)
_DEFAULT_RULES_DIR = Path("configs/trading_rules")


class RuleUnresolvedError(RuntimeError):
    """Fail-closed outcome when the PIT rule cannot be uniquely resolved."""


def _yyyymmdd(value: Any) -> int:
    text = str(value).strip().replace("-", "").replace("/", "")
    if len(text) == 8 and text.isdigit():
        return int(text)
    msg = f"invalid date {value!r}: expected YYYYMMDD"
    raise RuleUnresolvedError(msg)


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class TradingRuleRow:
    """One institutional rule fact, loaded from the versioned data layer."""

    rule_id: str
    board: str
    exchanges: tuple[str, ...]
    code_patterns: tuple[str, ...]
    effective_from: int
    effective_to: int
    st_state: bool | None  # None = ANY
    listing_age_rule: str
    up_rate: Decimal
    down_rate: Decimal
    tick_size: Decimal
    rounding_mode: str
    source_ref: str


@dataclass(frozen=True)
class TradingRule:
    """A PIT-resolved rule for (symbol, trade_date).

    Kept backwards-compatible with the pre-R4-A2.3 consumer surface
    (up_rate/down_rate/tick_size/limit_prices/effective window).
    """

    rule_id: str
    exchange: str
    code: str
    board: str
    effective_from: int
    effective_to: int
    up_rate: Decimal
    down_rate: Decimal
    tick_size: Decimal
    rounding_mode: str
    listing_age_rule: str
    source_ref: str
    source_version: str
    review_status: str
    first_n_session: bool = False  # True when resolved INTO a first-N rule

    @property
    def is_no_limit(self) -> bool:
        return self.up_rate == 0 and self.down_rate == 0

    def limit_prices(self, pre_close: Any) -> tuple[Decimal, Decimal]:
        """Decimal limit prices, tick-rounded (ROUND_HALF_UP, audit 8.6)."""
        pre = _to_decimal(pre_close)
        up = self._round_to_tick(pre * (Decimal(1) + self.up_rate))
        down = self._round_to_tick(pre * (Decimal(1) - self.down_rate))
        return up, down

    def _round_to_tick(self, price: Decimal) -> Decimal:
        tick = self.tick_size if self.tick_size > 0 else Decimal("0.01")
        if self.rounding_mode == "ROUND_HALF_UP":
            return price.quantize(tick, rounding=ROUND_HALF_UP)
        return price.quantize(tick, rounding=ROUND_HALF_UP)


def _pattern_match(pattern: str, bare_code: str) -> bool:
    if len(pattern) != len(bare_code):
        return False
    return all(p == "x" or p == c for p, c in zip(pattern, bare_code, strict=True))


def _parse_st_state(raw: Any) -> bool | None:
    """P1-04 (audit R4-A2.4 section 11.4): STRICT st_state parsing.

    bool -> bool; the strings 'true'/'false' (case-insensitive) -> bool;
    'any'/None -> None (rule ignores ST state). ANY OTHER string is a
    schema error - ``bool('false')`` truthiness would silently INVERT the
    rule (a YAML author writing st_state: "false" must never get True)."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip()
    lowered = text.lower()
    if lowered == "any":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    msg = (
        f"invalid st_state {raw!r}: use a bool, 'true'/'false', or 'any' "
        "(truthiness parsing is forbidden - audit R4-A2.4 section 11.4)"
    )
    raise ValueError(msg)


def first_n_sessions(
    trade_date: Any,
    listing_date: Any,
    calendar: Sequence[Any],
    n: int = 5,
) -> bool:
    """Is trade_date within the first N TRADING SESSIONS after listing?

    Session index comes from the PIT trading calendar - never from
    calendar-day arithmetic ("* 2" approximations are forbidden,
    audit section 8.5).

    Fail-closed rules:
      - listing date inside the calendar window but MISSING  -> error
      - trade date missing from the calendar                 -> error
      - trade date before listing                            -> error
      - listing before the calendar window starts -> False (the listing's
        first-N window predates the calendar; any in-calendar day is past it)
    """
    day = _yyyymmdd(trade_date)
    listed = _yyyymmdd(listing_date)
    days = sorted({int(d) for d in calendar})
    if not days:
        msg = "empty trading calendar - cannot determine first-N sessions"
        raise RuleUnresolvedError(msg)
    if day not in days:
        msg = f"trade date {day} missing from trading calendar"
        raise RuleUnresolvedError(msg)
    if listed not in days:
        if listed < days[0]:
            return False
        msg = f"listing date {listed} missing from trading calendar"
        raise RuleUnresolvedError(msg)
    if day < listed:
        msg = f"trade date {day} is before listing date {listed}"
        raise RuleUnresolvedError(msg)
    return days.index(day) - days.index(listed) < n


class TradingRuleBook:
    """Loads + validates + PIT-resolves the versioned rule data layer."""

    def __init__(
        self,
        rules: Sequence[TradingRuleRow],
        *,
        version: str = "",
        source_version: str = "",
        review_status: str = "",
        dataset_files: tuple[str, ...] = (),
        content_hash: str = "",
        review_provenance: dict[str, Any] | None = None,
    ) -> None:
        self.rules: tuple[TradingRuleRow, ...] = tuple(rules)
        self.version = version
        self.source_version = source_version
        self.review_status = review_status
        # R4-A2.4 P0-03: dataset identity for run binding
        self.dataset_files = dataset_files
        self.content_hash = content_hash
        self.review_provenance = dict(review_provenance or {})
        problems = self.validate()
        if problems:
            msg = "trading rule data invalid: " + "; ".join(problems)
            raise ValueError(msg)

    # ------------------------------------------------------------- loading
    @classmethod
    def load(cls, path: Path | str | None = None) -> TradingRuleBook:
        """Load from a YAML file or a directory of YAML files.

        Default: ``configs/trading_rules`` resolved against the repo root
        (cwd of the test/CLI entry point) or against the package location
        when the cwd has no configs directory.
        """
        import hashlib

        target = Path(path) if path is not None else cls._default_rules_dir()
        files = (
            sorted(target.glob("*.yaml")) + sorted(target.glob("*.yml"))
            if target.is_dir()
            else [target]
        )
        if not files or not files[0].is_file():
            msg = f"trading rule data not found: {target}"
            raise FileNotFoundError(msg)
        rules: list[TradingRuleRow] = []
        doc_meta: dict[str, str] = {}
        provenance: dict[str, Any] = {}
        digest = hashlib.sha256()
        names: list[str] = []
        for file in files:
            digest.update(file.name.encode("utf-8"))
            digest.update(file.read_bytes())
            names.append(file.name)
            doc = yaml.safe_load(file.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                msg = f"rule file {file} must be a mapping"
                raise ValueError(msg)
            for key in ("version", "source_version", "review_status"):
                value = str(doc.get(key, "") or "")
                if key in doc_meta and doc_meta[key] != value:
                    msg = f"rule file {file}: {key} conflicts with a previous file"
                    raise ValueError(msg)
                doc_meta[key] = doc_meta.get(key, value)
            for key in (
                "reviewed_by",
                "reviewed_at",
                "source_artifact_ref",
                "source_artifact_hash",
                "source_artifact_kind",
                "source_retrieved_at",
            ):
                if key in doc:
                    if key in provenance and provenance[key] != doc[key]:
                        msg = f"rule file {file}: {key} conflicts with a previous file"
                        raise ValueError(msg)
                    provenance[key] = doc[key]
            rules.extend(cls._rows_from(doc, file))
        return cls(
            rules,
            version=doc_meta.get("version", ""),
            source_version=doc_meta.get("source_version", ""),
            review_status=doc_meta.get("review_status", ""),
            dataset_files=tuple(names),
            content_hash=digest.hexdigest(),
            review_provenance=provenance,
        )

    @staticmethod
    def _default_rules_dir() -> Path:
        cwd_path = Path.cwd() / _DEFAULT_RULES_DIR
        if cwd_path.is_dir():
            return cwd_path
        # fall back to the package-anchored repo layout (src/../configs)
        pkg_path = Path(__file__).resolve().parents[3] / _DEFAULT_RULES_DIR
        if pkg_path.is_dir():
            return pkg_path
        return cwd_path

    @classmethod
    def _rows_from(cls, doc: dict[str, Any], file: Path) -> list[TradingRuleRow]:
        rows: list[TradingRuleRow] = []
        for entry in doc.get("rules", []) or []:
            missing = [
                key
                for key in (
                    "rule_id",
                    "board",
                    "exchanges",
                    "code_patterns",
                    "effective_from",
                    "effective_to",
                    "up_rate",
                    "down_rate",
                    "tick_size",
                )
                if key not in entry
            ]
            if missing:
                msg = f"rule file {file}: rule missing fields {missing}"
                raise ValueError(msg)
            st_raw = entry.get("st_state", None)
            rows.append(
                TradingRuleRow(
                    rule_id=str(entry["rule_id"]),
                    board=str(entry["board"]),
                    exchanges=tuple(str(e).upper() for e in entry["exchanges"]),
                    code_patterns=tuple(str(p) for p in entry["code_patterns"]),
                    effective_from=_yyyymmdd(entry["effective_from"]),
                    effective_to=_yyyymmdd(entry["effective_to"]),
                    st_state=_parse_st_state(st_raw),
                    listing_age_rule=str(entry.get("listing_age_rule", "NONE") or "NONE"),
                    up_rate=_to_decimal(entry["up_rate"]),
                    down_rate=_to_decimal(entry["down_rate"]),
                    tick_size=_to_decimal(entry["tick_size"]),
                    rounding_mode=str(entry.get("rounding_mode", "ROUND_HALF_UP")),
                    source_ref=str(entry.get("source_ref", "")),
                )
            )
        return rows

    # ----------------------------------------------------------- validation
    def validate(self) -> list[str]:
        problems: list[str] = []
        seen_ids: set[str] = set()
        for rule in self.rules:
            if rule.rule_id in seen_ids:
                problems.append(f"duplicate rule_id {rule.rule_id}")
            seen_ids.add(rule.rule_id)
            if not rule.exchanges:
                problems.append(f"{rule.rule_id}: empty exchanges")
            if not rule.code_patterns:
                problems.append(f"{rule.rule_id}: empty code_patterns")
            if rule.effective_from > rule.effective_to:
                problems.append(f"{rule.rule_id}: effective_from > effective_to")
            if not (Decimal(0) <= rule.up_rate <= Decimal(1)):
                problems.append(f"{rule.rule_id}: up_rate out of [0,1]")
            if not (Decimal(0) <= rule.down_rate <= Decimal(1)):
                problems.append(f"{rule.rule_id}: down_rate out of [0,1]")
            if rule.tick_size <= 0:
                problems.append(f"{rule.rule_id}: tick_size must be > 0")
            if rule.listing_age_rule not in _LISTING_AGE_RULES:
                problems.append(
                    f"{rule.rule_id}: unknown listing_age_rule {rule.listing_age_rule!r}"
                )
            if rule.rounding_mode not in _ROUNDING_MODES:
                problems.append(f"{rule.rule_id}: unknown rounding_mode {rule.rounding_mode!r}")
        if not self.rules:
            problems.append("no rules loaded")
        return problems

    # ------------------------------------------------------------ resolving
    def resolve(
        self,
        *,
        exchange: str,
        code: str,
        trade_date: Any,
        is_st: bool = False,
        listing_date: Any = None,
        calendar: Sequence[Any] | None = None,
    ) -> TradingRule:
        """Full PIT resolve (needs listing_date + calendar when any
        candidate rule depends on listing age). Raises RuleUnresolvedError
        on 0 / ambiguous / missing-context matches."""
        selected, day, exch, bare = self._select_candidates(
            exchange, code, trade_date, is_st
        )
        age_rules = {r.listing_age_rule for r in selected}
        first_n = False
        if any(rule != "NONE" for rule in age_rules):
            if listing_date is None or not calendar:
                msg = (
                    f"RULE_UNRESOLVED: {exch} {bare} on {day} has listing-age-dependent "
                    "candidates (e.g. first-N no-limit) but listing_date/trading calendar "
                    "were not provided - refusing to guess (audit section 8.3)"
                )
                raise RuleUnresolvedError(msg)
            ipo_day = _yyyymmdd(listing_date) == day
            if ipo_day and any(r.listing_age_rule == "IPO_DAY_44_36" for r in selected):
                selected = [
                    r for r in selected if r.listing_age_rule == "IPO_DAY_44_36"
                ]
                first_n = True
            else:
                first_n = first_n_sessions(day, listing_date, calendar, n=5)
                if first_n and any(
                    r.listing_age_rule == "FIRST_5_DAYS_NO_LIMIT" for r in selected
                ):
                    selected = [
                        r for r in selected if r.listing_age_rule == "FIRST_5_DAYS_NO_LIMIT"
                    ]
                else:
                    selected = [r for r in selected if r.listing_age_rule == "NONE"]
                    first_n = False
        else:
            selected = [r for r in selected if r.listing_age_rule == "NONE"]
        if not selected:
            msg = (
                f"RULE_UNRESOLVED: no listing-age rule applies for {exch} {bare} on {day} "
                "(candidate rules exist but none matches the listing-age state)"
            )
            raise RuleUnresolvedError(msg)
        if len(selected) > 1:
            ids = ", ".join(sorted(r.rule_id for r in selected))
            msg = (
                f"RULE_UNRESOLVED: >1 equally-valid rules for {exch} {bare} on {day} "
                f"(is_st={is_st}): {ids} (audit section 8.3)"
            )
            raise RuleUnresolvedError(msg)
        return self._to_rule(selected[0], exch=exch, code=bare, first_n=first_n)

    def resolve_limit_regime(
        self,
        *,
        exchange: str,
        code: str,
        trade_date: Any,
        is_st: bool = False,
    ) -> TradingRule:
        """Resolve the limit regime for a day that is KNOWN (from caller
        context) not to be a no-limit listing window day - e.g. provider
        status rows that carry an actual HIGH_LIMITED price. Selects the
        NONE listing-age rule; raises when only listing-age rules exist."""
        selected, day, exch, bare = self._select_candidates(
            exchange, code, trade_date, is_st
        )
        selected = [r for r in selected if r.listing_age_rule == "NONE"]
        if not selected:
            msg = (
                f"RULE_UNRESOLVED: no non-IPO limit regime for {exch} {bare} on {day} "
                "(only listing-age-dependent rules apply)"
            )
            raise RuleUnresolvedError(msg)
        if len(selected) > 1:
            ids = ", ".join(sorted(r.rule_id for r in selected))
            msg = (
                f"RULE_UNRESOLVED: >1 equally-valid rules for {exch} {bare} on {day}: {ids}"
            )
            raise RuleUnresolvedError(msg)
        return self._to_rule(selected[0], exch=exch, code=bare, first_n=False)

    # -------------------------------------------------------------- private
    def _select_candidates(
        self, exchange: str, code: str, trade_date: Any, is_st: bool
    ) -> tuple[list[TradingRuleRow], int, str, str]:
        bare = str(code).strip()
        suffix = ""
        if "." in bare:
            bare, suffix = bare.rsplit(".", 1)
            suffix = suffix.strip().upper()
        exch = str(exchange).strip().upper() if exchange else suffix
        if exch not in ("SH", "SZ", "BJ"):
            msg = f"RULE_UNRESOLVED: unknown exchange {exch!r} for code {bare!r}"
            raise RuleUnresolvedError(msg)
        day = _yyyymmdd(trade_date)
        candidates = [
            rule
            for rule in self.rules
            if exch in rule.exchanges
            and any(_pattern_match(p, bare) for p in rule.code_patterns)
            and rule.effective_from <= day <= rule.effective_to
        ]
        if not candidates:
            msg = (
                f"RULE_UNRESOLVED: no matching rule for {exch} {bare} on {day} "
                "(unknown board or date outside every effective window)"
            )
            raise RuleUnresolvedError(msg)
        st_specific = [r for r in candidates if r.st_state is not None and r.st_state == is_st]
        st_any = [r for r in candidates if r.st_state is None]
        selected = st_specific or st_any
        if not selected:
            msg = (
                f"RULE_UNRESOLVED: is_st={is_st} has no applicable rule for "
                f"{exch} {bare} on {day}"
            )
            raise RuleUnresolvedError(msg)
        return selected, day, exch, bare

    def _to_rule(
        self, row: TradingRuleRow, *, exch: str, code: str, first_n: bool
    ) -> TradingRule:
        return TradingRule(
            rule_id=row.rule_id,
            exchange=exch,
            code=code,
            board=row.board,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            up_rate=row.up_rate,
            down_rate=row.down_rate,
            tick_size=row.tick_size,
            rounding_mode=row.rounding_mode,
            listing_age_rule=row.listing_age_rule,
            source_ref=row.source_ref,
            source_version=self.source_version,
            review_status=self.review_status,
            first_n_session=first_n,
        )


_DEFAULT_BOOK: TradingRuleBook | None = None

#: allowed source artifact kinds (aligned with the golden review gate)
_REVIEW_ARTIFACT_KINDS = (
    "OTHER_OFFICIAL",
    "EXCHANGE_NOTICE",
    "REGULATOR_DOC",
    "DATASET_DOC",
)


def trading_rule_review_gate(
    book: TradingRuleBook,
    *,
    rules_root: Path | str | None = None,
) -> list[str]:
    """R4-A2.4 P0-04: Trading Rule Review Gate.

    The rule dataset follows the same lifecycle as golden truth:
    COMPILED (candidate, usable by dry-run/trial with explicit provenance)
    -> REVIEWED (human-reviewed, required for PRODUCTION runs/verdicts).

    Checks (each failure is a returned problem):
      - review_status must be REVIEWED for formal use (COMPILED is reported
        explicitly - the caller decides whether that blocks)
      - REVIEWED requires complete provenance (reviewed_by/reviewed_at/
        source_artifact_ref/source_artifact_hash/source_artifact_kind/
        source_retrieved_at)
      - the referenced source artifact must resolve under rules_root (or
        the rule dataset's own directory) and hash to source_artifact_hash
    """
    problems: list[str] = []
    if book.review_status != "REVIEWED":
        problems.append(
            f"trading rule dataset is {book.review_status or 'UNKNOWN'} - not fully "
            "human-reviewed (COMPILED candidates are dry-run/trial only)"
        )
        return problems
    prov = book.review_provenance
    missing = [
        key
        for key in (
            "reviewed_by",
            "reviewed_at",
            "source_artifact_ref",
            "source_artifact_hash",
            "source_artifact_kind",
            "source_retrieved_at",
        )
        if not str(prov.get(key, "") or "").strip()
    ]
    if missing:
        problems.append(f"REVIEWED dataset missing provenance fields: {missing}")
        return problems
    if str(prov.get("source_artifact_kind")) not in _REVIEW_ARTIFACT_KINDS:
        problems.append(
            f"source_artifact_kind {prov.get('source_artifact_kind')!r} not in "
            f"{_REVIEW_ARTIFACT_KINDS}"
        )
    ref = str(prov.get("source_artifact_ref"))
    expected_hash = str(prov.get("source_artifact_hash"))
    import hashlib

    # artifact resolution roots: explicit rules_root first, then the
    # loader's default rules dir (respects tests/installed layouts)
    roots = [Path(p) for p in (rules_root,) if p is not None]
    roots.append(TradingRuleBook._default_rules_dir())
    artifact_path: Path | None = None
    for root in roots:
        candidate = root / ref
        if candidate.is_file():
            artifact_path = candidate
            break
    if artifact_path is None:
        problems.append(f"source artifact not found: {ref}")
    else:
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != expected_hash:
            problems.append(f"source artifact hash mismatch: {ref}")
    return problems


def load_bound_rule_book(
    *,
    rule_file: str,
    rule_version: str,
    rule_hash: str,
    repo_root: Path | str | None = None,
) -> TradingRuleBook:
    """R4-A2.4 P0-03: load the RUN-BOUND rule dataset and verify its
    integrity (bytes hash + version). Verdicts/replays resolve rules
    through THIS loader, never through the working tree's current state -
    an ACTIVE/working-tree advance can never leak into a historical run."""
    import hashlib

    candidates = []
    if repo_root is not None:
        candidates.append(Path(repo_root) / rule_file)
    else:
        candidates.append(Path.cwd() / rule_file)
        # fallback: the package-anchored repo layout (respects a patched
        # _default_rules_dir in tests and installed-package runs)
        default_dir = TradingRuleBook._default_rules_dir()
        repo_anchor = default_dir.parent.parent if default_dir.is_absolute() else None
        if repo_anchor is not None:
            candidates.append(repo_anchor / rule_file)
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        msg = f"bound trading rule dataset missing: {rule_file}"
        raise RuleUnresolvedError(msg)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != rule_hash:
        msg = (
            f"bound trading rule dataset hash mismatch for {rule_file}: "
            "the file changed after the run was created (expected "
            f"{rule_hash[:16]}..., got {actual[:16]}...)"
        )
        raise RuleUnresolvedError(msg)
    book = TradingRuleBook.load(path)
    if book.version != rule_version:
        msg = (
            f"bound trading rule dataset version mismatch: run bound {rule_version!r}, "
            f"file now {book.version!r}"
        )
        raise RuleUnresolvedError(msg)
    return book


def default_rule_book() -> TradingRuleBook:
    """Process-wide cached book loaded from configs/trading_rules."""
    global _DEFAULT_BOOK
    if _DEFAULT_BOOK is None:
        _DEFAULT_BOOK = TradingRuleBook.load()
    return _DEFAULT_BOOK


def resolve_trading_rule(
    *,
    exchange: str,
    code: str,
    trade_date: Any,
    is_st: bool = False,
    listing_date: Any = None,
    calendar: Sequence[Any] | None = None,
    book: TradingRuleBook | None = None,
) -> TradingRule:
    """Full PIT resolve - raises RuleUnresolvedError (fail closed)."""
    active = book if book is not None else default_rule_book()
    return active.resolve(
        exchange=exchange,
        code=code,
        trade_date=trade_date,
        is_st=is_st,
        listing_date=listing_date,
        calendar=calendar,
    )


def resolve_limit_regime(
    *,
    exchange: str,
    code: str,
    trade_date: Any,
    is_st: bool = False,
    book: TradingRuleBook | None = None,
) -> TradingRule:
    """Limit-regime resolve for known-not-first-N days (see book docs)."""
    active = book if book is not None else default_rule_book()
    return active.resolve_limit_regime(
        exchange=exchange, code=code, trade_date=trade_date, is_st=is_st
    )


__all__ = [
    "RuleUnresolvedError",
    "TradingRule",
    "TradingRuleBook",
    "TradingRuleRow",
    "default_rule_book",
    "first_n_sessions",
    "load_bound_rule_book",
    "resolve_limit_regime",
    "resolve_trading_rule",
    "trading_rule_review_gate",
]
