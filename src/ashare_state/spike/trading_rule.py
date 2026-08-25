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

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
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
        """Load the rule dataset.

        R4-A2.5 P0-02 (audit 20260825 section 3.5) - explicit version model:

        - ``path`` is a DIRECTORY (or None -> default rules dir):
          read ``rule_manifest.json`` (the ACTIVE selector) and load ONLY
          the declared ``dataset_files`` (relative to that root), verifying
          the combined ``dataset_hash``. Historical versions under
          ``versions/`` coexist but are NEVER auto-merged - the old
          "glob every yaml in the directory" semantics is GONE.
        - ``path`` is a FILE: load exactly that one yaml (standalone/test
          or bound-version direct load).

        The ACTIVE manifest is the single unambiguous selector; run
        bindings capture (version, dataset_files, dataset_hash) and are
        loaded via ``load_bound_rule_book`` without reading ACTIVE.
        """
        target = Path(path) if path is not None else cls._default_rules_dir()
        if target.is_dir():
            book, _manifest = load_active_rules(target)
            return book
        if not target.is_file():
            msg = f"trading rule data not found: {target}"
            raise FileNotFoundError(msg)
        return cls.load_version_files([target])

    @classmethod
    def load_version_files(cls, files: list[Path]) -> TradingRuleBook:
        """Load an EXPLICIT list of rule yaml files as one dataset (used
        by the ACTIVE selector and by run-bound loads)."""
        import hashlib

        if not files or not files[0].is_file():
            msg = f"trading rule data not found: {files}"
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
        selected, day, exch, bare = self._select_candidates(exchange, code, trade_date, is_st)
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
                selected = [r for r in selected if r.listing_age_rule == "IPO_DAY_44_36"]
                first_n = True
            else:
                first_n = first_n_sessions(day, listing_date, calendar, n=5)
                if first_n and any(r.listing_age_rule == "FIRST_5_DAYS_NO_LIMIT" for r in selected):
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
        selected, day, exch, bare = self._select_candidates(exchange, code, trade_date, is_st)
        selected = [r for r in selected if r.listing_age_rule == "NONE"]
        if not selected:
            msg = (
                f"RULE_UNRESOLVED: no non-IPO limit regime for {exch} {bare} on {day} "
                "(only listing-age-dependent rules apply)"
            )
            raise RuleUnresolvedError(msg)
        if len(selected) > 1:
            ids = ", ".join(sorted(r.rule_id for r in selected))
            msg = f"RULE_UNRESOLVED: >1 equally-valid rules for {exch} {bare} on {day}: {ids}"
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
                f"RULE_UNRESOLVED: is_st={is_st} has no applicable rule for {exch} {bare} on {day}"
            )
            raise RuleUnresolvedError(msg)
        return selected, day, exch, bare

    def _to_rule(self, row: TradingRuleRow, *, exch: str, code: str, first_n: bool) -> TradingRule:
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

#: R4-A2.5 P0-02: the ACTIVE selector file inside the rules root
RULE_MANIFEST_FILE = "rule_manifest.json"
#: R4-A2.5 P0-03: review artifacts live under this subdir of the rules root
RULE_EVIDENCE_SUBDIR = "evidence"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RuleDatasetManifest:
    """R4-A2.5 P0-02 (audit 20260825 section 3.5): the ACTIVE rule-version
    selector. Historical versions under versions/ coexist immutably; the
    manifest is the single unambiguous pointer."""

    rule_version: str
    review_status: str
    dataset_files: tuple[str, ...]  # relative to the rules root
    dataset_hash: str  # sha256 over (rel_path + bytes) of every file
    source_version: str = ""
    #: the yaml ``version:`` field inside the dataset files (content
    #: version) - distinct from rule_version (the selector/directory id)
    dataset_version: str = ""
    review_provenance: dict[str, Any] = field(default_factory=dict)


def _dataset_files_hash(root: Path, rel_files: Sequence[str]) -> str:
    """Deterministic combined hash over the rule dataset: for every file
    (sorted) the relative path + the file bytes. Used by the manifest AND
    the run bindings - one algorithm everywhere."""
    import hashlib

    digest = hashlib.sha256()
    for rel in sorted(rel_files):
        digest.update(rel.replace("\\", "/").encode("utf-8"))
        digest.update((root / rel).read_bytes())
    return digest.hexdigest()


def _confined(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root`` refusing traversal (R4-A2.5 P0-03:
    review-gate evidence hardening - no absolute paths, no '..')."""
    normalized = rel.replace("\\", "/")
    if not normalized or normalized.startswith(("/", "\\")) or ":" in normalized.split("/")[0]:
        msg = f"evidence ref must be relative: {rel!r}"
        raise RuleUnresolvedError(msg)
    candidate = (root / normalized).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        msg = f"evidence ref escapes the evidence root: {rel!r}"
        raise RuleUnresolvedError(msg) from exc
    return candidate


def load_rule_manifest(root: Path | str) -> RuleDatasetManifest:
    """Load + schema-validate the ACTIVE rule manifest (fail closed)."""
    root = Path(root)
    manifest_path = root / RULE_MANIFEST_FILE
    if not manifest_path.is_file():
        msg = f"trading rule manifest missing: {manifest_path}"
        raise RuleUnresolvedError(msg)
    import json

    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"trading rule manifest unreadable: {exc}"
        raise RuleUnresolvedError(msg) from exc
    problems: list[str] = []
    version = str(doc.get("rule_version", "") or "")
    status = str(doc.get("review_status", "") or "")
    files = [str(f) for f in doc.get("dataset_files", []) or []]
    dataset_hash = str(doc.get("dataset_hash", "") or "")
    if not version:
        problems.append("rule_version missing")
    if status not in ("COMPILED", "REVIEWED"):
        problems.append(f"review_status must be COMPILED|REVIEWED, got {status!r}")
    if not files:
        problems.append("dataset_files empty")
    if not _HEX64.match(dataset_hash):
        problems.append("dataset_hash must be 64 lower-hex chars")
    if problems:
        msg = "trading rule manifest invalid: " + "; ".join(problems)
        raise RuleUnresolvedError(msg)
    for rel in files:
        if not (root / rel).is_file():
            msg = f"manifest dataset file missing: {rel}"
            raise RuleUnresolvedError(msg)
    return RuleDatasetManifest(
        rule_version=version,
        review_status=status,
        dataset_files=tuple(files),
        dataset_hash=dataset_hash,
        source_version=str(doc.get("source_version", "") or ""),
        dataset_version=str(doc.get("dataset_version", "") or ""),
        review_provenance=dict(doc.get("review_provenance", {}) or {}),
    )


def load_active_rules(
    root: Path | str | None = None,
) -> tuple[TradingRuleBook, RuleDatasetManifest]:
    """Load the ACTIVE rule version selected by rule_manifest.json and
    verify the dataset integrity (combined hash recomputed over the
    declared files - tampering ANY dataset file or the manifest's hash
    blocks here, i.e. new_run/TRIAL/PRODUCTION fail fast).

    R4-A2.5 P0-02: COMPILED and REVIEWED versions coexist immutably under
    versions/; only the manifest decides which one is ACTIVE."""
    target = Path(root) if root is not None else TradingRuleBook._default_rules_dir()
    manifest = load_rule_manifest(target)
    actual = _dataset_files_hash(target, manifest.dataset_files)
    if actual != manifest.dataset_hash:
        msg = (
            f"ACTIVE trading rule dataset hash mismatch for {manifest.rule_version}: "
            f"declared {manifest.dataset_hash[:16]}..., recomputed {actual[:16]}... "
            "- the rule data was tampered with (audit 20260825 section 3.2)"
        )
        raise RuleUnresolvedError(msg)
    book = TradingRuleBook.load_version_files([target / rel for rel in manifest.dataset_files])
    if manifest.dataset_version and book.version != manifest.dataset_version:
        msg = (
            f"ACTIVE trading rule dataset version mismatch: manifest says "
            f"{manifest.dataset_version!r}, files say {book.version!r}"
        )
        raise RuleUnresolvedError(msg)
    return book, manifest


def trading_rule_review_gate(
    book: TradingRuleBook,
    *,
    rules_root: Path | str | None = None,
) -> list[str]:
    """R4-A2.4 P0-04 + R4-A2.5 P0-03: Trading Rule Review Gate.

    The rule dataset follows the same lifecycle as golden truth:
    COMPILED (candidate, usable by dry-run/trial with explicit provenance)
    -> REVIEWED (human-reviewed, required for PRODUCTION runs/verdicts).

    Hardened provenance verification (audit 20260825 section 4):
      - review_status must be REVIEWED for formal use
      - REVIEWED requires complete provenance (reviewed_by/reviewed_at/
        source_artifact_ref/source_artifact_hash/source_artifact_kind/
        source_retrieved_at)
      - source_artifact_ref is RELATIVE to the EVIDENCE root
        (rules_root/evidence) and is path-confined: absolute paths and
        '..' traversal are REJECTED before any filesystem access
      - source_artifact_hash must be 64 lower-hex chars
      - reviewed_at / source_retrieved_at must be ISO-8601 timestamps
      - the artifact bytes must hash to source_artifact_hash
    """
    import hashlib
    from datetime import datetime

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
    expected_hash = str(prov.get("source_artifact_hash", ""))
    if not _HEX64.match(expected_hash):
        problems.append(f"source_artifact_hash must be 64 lower-hex chars, got {expected_hash!r}")
        return problems
    for ts_key in ("reviewed_at", "source_retrieved_at"):
        try:
            datetime.fromisoformat(str(prov.get(ts_key, "")))
        except ValueError:
            problems.append(f"{ts_key} is not an ISO-8601 timestamp: {prov.get(ts_key)!r}")
    if problems:
        return problems
    ref = str(prov.get("source_artifact_ref"))
    root = Path(rules_root) if rules_root is not None else TradingRuleBook._default_rules_dir()
    evidence_root = root / RULE_EVIDENCE_SUBDIR
    try:
        artifact_path = _confined(evidence_root, ref)
    except RuleUnresolvedError as exc:
        problems.append(f"source_artifact_ref rejected: {exc}")
        return problems
    if not artifact_path.is_file():
        problems.append(f"source artifact not found under evidence root: {ref}")
        return problems
    actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual != expected_hash:
        problems.append(f"source artifact hash mismatch: {ref}")
    return problems


def load_bound_rule_book(
    *,
    rule_version: str,
    dataset_files: Sequence[str],
    dataset_hash: str,
    repo_root: Path | str | None = None,
    rules_root: Path | str | None = None,
) -> TradingRuleBook:
    """R4-A2.4 P0-03 + R4-A2.5 P0-02: load the RUN-BOUND rule dataset and
    verify its integrity. The binding captures the dataset FILES LIST and
    the combined hash over (relative path + bytes) of every file - exactly
    the manifest's algorithm - so tampering ANY bound file (not just the
    first) blocks the replay. Verdicts/replays resolve rules through THIS
    loader, never through the working tree's ACTIVE state."""
    if not dataset_files:
        msg = "bound trading rule dataset has no files"
        raise RuleUnresolvedError(msg)
    candidates: list[Path] = []
    if rules_root is not None:
        candidates.append(Path(rules_root))
    elif repo_root is not None:
        candidates.append(Path(repo_root) / "configs" / "trading_rules")
    else:
        default_dir = TradingRuleBook._default_rules_dir()
        candidates.append(default_dir)
    root = next((c for c in candidates if (c / dataset_files[0]).is_file()), None)
    if root is None:
        msg = f"bound trading rule dataset missing: {list(dataset_files)}"
        raise RuleUnresolvedError(msg)
    for rel in dataset_files:
        try:
            _confined(root, rel)
        except RuleUnresolvedError as exc:
            msg = f"bound dataset file rejected: {rel} ({exc})"
            raise RuleUnresolvedError(msg) from exc
        if not (root / rel).is_file():
            msg = f"bound trading rule dataset file missing: {rel}"
            raise RuleUnresolvedError(msg)
    actual = _dataset_files_hash(root, dataset_files)
    if actual != dataset_hash:
        msg = (
            f"bound trading rule dataset hash mismatch (expected {dataset_hash[:16]}..., "
            f"recomputed {actual[:16]}...): the dataset changed after the run was "
            "created (audit 20260825 section 3.4)"
        )
        raise RuleUnresolvedError(msg)
    book = TradingRuleBook.load_version_files([root / rel for rel in dataset_files])
    if book.version != rule_version:
        msg = (
            f"bound trading rule dataset version mismatch: run bound {rule_version!r}, "
            f"files now {book.version!r}"
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
    "RuleDatasetManifest",
    "RuleUnresolvedError",
    "RULE_EVIDENCE_SUBDIR",
    "RULE_MANIFEST_FILE",
    "TradingRule",
    "TradingRuleBook",
    "TradingRuleRow",
    "default_rule_book",
    "first_n_sessions",
    "load_active_rules",
    "load_bound_rule_book",
    "load_rule_manifest",
    "resolve_limit_regime",
    "resolve_trading_rule",
    "trading_rule_review_gate",
]
