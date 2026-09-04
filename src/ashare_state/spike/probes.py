"""B2-B7 probes (audit R2 sections 3/24.5/24.6/24.7 + R3-P0-03/P1-09).

Every probe:
- calls ONLY through its SpikeTarget (real = hardened adapter),
- goes through the ProbeExecutor so provider errors become STRUCTURED
  cases (never an unhandled crash leaving the run RUNNING),
- archives lossless raw evidence via the RawWriter consuming the EXPLICIT
  ProviderExchange (CR-1.1 / audit R4-A2.3 sections 3-4): Parquet payload
  artifact + .meta.json envelope, including FAILED exchanges (envelope-
  only evidence - the request audit record is never dropped),
- turns payloads into cases with SEMANTIC validators (never call-success),
- writes cases into the run-scoped catalog,
- references the SINGLE run as-of date (R3-P1-09) - no probe may hardcode
  today's date.

Golden (B4) executes the real Discover -> Freeze -> Expected -> Compare
-> Reason -> Verdict pipeline against provider data.

CR-1.1 audit section 3.2-B: this module NEVER reads
``provider.last_envelopes`` - that list is diagnostic-only. All lineage
flows through the explicit ProviderExchange returned by ``*_exchange``
target methods (or attached to a raised ProviderError).
"""

from __future__ import annotations

import uuid
from typing import Any

from ashare_state.providers.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderSchemaError,
)
from ashare_state.providers.exchange import ProviderExchange, synthetic_failure_exchange
from ashare_state.spike import validators
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunFailureReason, SpikeCase, SpikeRun
from ashare_state.spike.run_store import RunStore
from ashare_state.spike.target import SpikeTarget

# documented unit map placeholder - B5 live evidence finalizes it
DOCUMENTED_UNITS = {"volume": "shares", "amount": "CNY"}


def _rows_of(payload: Any) -> list[dict[str, Any]]:
    """Normalize SDK payload shapes into row dicts (frames / list / dict-of)."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        rows: list[dict[str, Any]] = []
        for value in payload.values():
            rows.extend(_rows_of(value))
        return rows
    if isinstance(payload, list):
        return [r if isinstance(r, dict) else {"value": r} for r in payload]
    # polars.DataFrame FIRST (it also exposes to_dict, whose no-arg form
    # returns a {column: Series} dict - list() of that is column NAMES,
    # a silent garbage row; .rows() is the correct accessor)
    rows_method = getattr(payload, "rows", None)
    if callable(rows_method) and hasattr(payload, "columns"):
        return [dict(zip(payload.columns, row, strict=True)) for row in rows_method()]
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):  # pandas.DataFrame
        try:
            records = to_dict(orient="records")
        except TypeError:  # pragma: no cover - non-pandas to_dict
            records = None
        if records is not None:
            return records
        return []
    return [{"value": payload}]


def _to_plain(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """JSON-friendly rows (numpy scalars etc. -> str via default=str)."""
    import json

    return json.loads(json.dumps(rows, default=str))


def _flat_values(payload: Any) -> list[Any]:
    """R4-A2.5 P0-05 (audit 20260825 section 6.2): flatten a scalar-list /
    single-column-frame payload into plain scalar values.

    Payload-only consumers that coerced row dicts to strings produced
    GARBAGE ("{'value': '600519.SH'}") and silently "passed" - this helper
    fails loud instead: a multi-column row that cannot be flattened
    raises (the caller decides the real shape)."""
    values: list[Any] = []
    for row in _rows_of(payload):
        if isinstance(row, dict):
            if set(row.keys()) == {"value"}:
                values.append(row["value"])
            elif len(row) == 1:
                values.append(next(iter(row.values())))
            else:
                msg = (
                    "_flat_values: multi-column row cannot be flattened to a "
                    f"scalar list (keys={sorted(row.keys())[:5]}) - the payload "
                    "is not a scalar list; consume it as rows instead"
                )
                raise ValueError(msg)
        else:
            values.append(row)
    return values


class ProbeContext:
    """Run-scoped context. CR-1.1 (audit R4-A2.3 section 4): the runtime
    evidence pipeline is ProviderExchange -> RawWriter -> Parquet + meta
    -> RawWriteResult -> SpikeCase evidence_ref/evidence_hash. Payload ->
    RunStore.write_evidence(JSON) is FORBIDDEN as the formal provider
    evidence chain.

    CR-2.4 (audit 20260901 section 3.2): the evidence pipeline is the
    ANCHORED boundary - ProviderExchange -> AnchoredRawEvidenceWriter
    (RawWriter file commit + immutable trust-anchor enrollment, one
    indivisible governed step) -> RawWriteResult. Every formal/spike
    evidence write (SUCCESS and ERROR alike) therefore always leaves a
    ``meta_raw_evidence_anchor`` row; there is no unanchored
    production write path."""

    def __init__(
        self,
        run: SpikeRun,
        store: RunStore,
        catalog: CaseCatalog,
        target: SpikeTarget,
        conn: Any,
    ) -> None:
        self.run = run
        self.store = store
        self.catalog = catalog
        self.target = target
        from ashare_state.storage.raw_anchor import AnchoredRawEvidenceWriter

        # CR-1.2 (audit R4-A2.4 section 3.4): every raw meta records the
        # run it belongs to (ingest_run_id traceability). CR-2.4: the
        # writer is the anchored boundary (write + anchor enrollment are
        # indivisible; the enrolled hash is the RawWriter COMMIT identity).
        self.raw_writer = AnchoredRawEvidenceWriter(
            conn, store.raw_dir(run), ingest_run_id=run.spike_run_id
        )

    @property
    def as_of_date(self) -> int:
        """R3-P1-09: the single run-wide as-of reference."""
        digits = "".join(ch for ch in str(self.run.as_of_date) if ch.isdigit())
        return int(digits[:8]) if len(digits) >= 8 else 20260814

    @property
    def rule_book(self):
        """R4-A2.4 P0-03 + R4-A2.5 P0-01/P0-02: the RUN-BOUND trading-rule
        book. Formal runs bind the rule dataset (version + full file list +
        combined hash) at creation; validation resolves rules through THIS
        book - never the working tree's ACTIVE state. Dry-run / unbound
        runs fall back to the ACTIVE (manifest-selected) book."""
        from ashare_state.spike.trading_rule import (
            load_active_rules,
            load_bound_rule_book,
        )

        if getattr(self.run, "trading_rule_dataset_files", None):
            return load_bound_rule_book(
                rule_version=self.run.trading_rule_version,
                dataset_files=self.run.trading_rule_dataset_files,
                dataset_hash=self.run.trading_rule_dataset_hash,
                dataset_version=getattr(self.run, "trading_rule_dataset_version", ""),
                source_version=getattr(self.run, "trading_rule_source_version", ""),
                review_status=getattr(self.run, "trading_rule_review_status", ""),
            )
        book, _manifest = load_active_rules()
        return book

    # ------------------------------------------------------------ evidence
    def evidence_from_exchange(self, exchange: ProviderExchange) -> dict[str, Any]:
        """Persist ONE ProviderExchange via the RawWriter and return the
        evidence meta for case binding. Reuses the exchange's own
        request_id (CR-1c) - never regenerates one, never reverse-searches
        last_envelopes.

        CR-1.2 (audit R4-A2.4 section 3.1-3.2): the evidence is the
        exchange META (bidirectional closure anchor); payload artifacts
        are listed separately with their own hashes."""
        result = self.raw_writer.write_exchange(exchange)
        envelope = exchange.envelope
        # evidence_ref must be relative to the run store's spike_root so
        # the evidence closure can re-verify the file bytes
        run_prefix = f"{self.run.run_kind.value.lower()}/{self.run.spike_run_id}/raw/"
        return {
            "request_id": result.request_id,
            "endpoint": envelope.endpoint,
            "provider_dataset": envelope.provider_dataset,
            "status": envelope.status,
            "error_class": envelope.error_class,
            "attempt_count": envelope.attempt_count,
            "row_count": result.row_count,
            "payload_kind": result.payload_kind,
            "evidence_ref": run_prefix + result.evidence_uri,
            "content_hash": result.evidence_hash,
            # CR-1.2: explicit artifact split (payloads + meta anchor)
            "payload_artifacts": [
                {
                    "uri": run_prefix + a.uri,
                    "content_hash": a.content_hash,
                    "schema_hash": a.schema_hash,
                    "row_count": a.row_count,
                }
                for a in result.payload_artifacts
            ],
            "meta_ref": run_prefix + result.meta_uri,
            "meta_hash": result.meta_artifact.content_hash if result.meta_artifact else "",
        }

    def failure_evidence(
        self, exc: ProviderError, *, endpoint: str, dataset: str
    ) -> dict[str, Any]:
        """Persist the FAILED exchange attached to a ProviderError (first-
        class failure object, audit section 3.2-D). If the failure never
        reached a real SDK exchange (governance gate), an honest synthetic
        envelope is recorded instead - still no shared-state lookup."""
        exchange = getattr(exc, "exchange", None)
        if exchange is None:
            exchange = synthetic_failure_exchange(endpoint=endpoint, dataset=dataset, error=exc)
        return self.evidence_from_exchange(exchange)

    # ---------------------------------------------------------------- cases
    def case(
        self,
        *,
        case_id: str,
        case_type: str,
        security: str,
        provider_symbol: str,
        trade_date: str,
        expected: str,
        actual: str,
        result: CaseResult,
        evidence_meta: dict[str, Any],
        reason_code: str = "",
        validator_id: str = "",
        validator_version: str = "",
        equivalent_pass: bool = False,
    ) -> None:
        self.catalog.add(
            SpikeCase(
                case_id=case_id,
                spike_run_id=self.run.spike_run_id,
                case_type=case_type,
                security=security,
                provider_symbol=provider_symbol,
                trade_date=trade_date,
                expected_value=expected,
                actual_value=actual,
                evidence_type="RAW_PARQUET",
                evidence_ref=str(evidence_meta.get("evidence_ref", "")),
                result=result,
                reason_code=reason_code,
                validator_id=validator_id,
                validator_version=validator_version,
                evidence_hash=str(evidence_meta.get("content_hash", "")),
                equivalent_pass=equivalent_pass,
            )
        )

    def outcome_case(
        self,
        ctx_type: str,
        symbol: str,
        trade_date: str,
        evidence: dict[str, Any],
        out: validators.ValidationOutcome,
    ) -> None:
        self.case(
            case_id=f"{ctx_type.split('_')[0]}-{ctx_type}-{symbol}-{trade_date}".upper(),
            case_type=ctx_type,
            security=symbol,
            provider_symbol=symbol,
            trade_date=trade_date,
            expected=out.expected,
            actual=out.actual,
            result=out.result,
            evidence_meta=evidence,
            reason_code=out.reason_code,
            validator_id=out.validator_id,
            validator_version=out.validator_version,
            equivalent_pass=out.equivalent_pass,
        )


class ProbeExecutor:
    """R3-P0-03: provider exceptions become structured cases.

    Mapping (audit R3 section 7):
      ProviderPermissionError -> NOT_TESTABLE_PERMISSION case
      ProviderRateLimitError  -> NOT_TESTABLE_ACCOUNT case
      ProviderAuthError       -> run FAILED_ACCOUNT (terminal) + re-raise
      ProviderSchemaError     -> VALIDATED_FAIL case
      other ProviderError     -> MISSING case (SDK internal -> gate sees
                                 SPIKE_INCOMPLETE, never a false PASS)

    CR-1.1 (audit section 3.2): ``fn`` must return the EXPLICIT
    ProviderExchange (call the target's ``*_exchange`` methods). Failure
    exchanges are first-class: the exchange attached to the raised
    ProviderError is persisted (envelope-only evidence) - the module never
    reverse-searches provider.last_envelopes.
    """

    def __init__(self, ctx: ProbeContext) -> None:
        self.ctx = ctx

    def call(
        self,
        endpoint: str,
        fn: Any,
        *,
        failure_case_type: str,
        dataset: str = "",
        trade_date: str = "",
        symbol: str = "SDK",
    ) -> tuple[Any, dict[str, Any]]:
        """Execute one exchange-returning target call; returns
        (payload, evidence_meta).

        On provider failure the case is recorded (with the failed
        exchange's envelope-only evidence) and (None, meta) is returned -
        callers skip further validation for this capability.
        """
        from ashare_state.spike.runner import fail_run

        try:
            exchange = fn()
            if not isinstance(exchange, ProviderExchange):
                msg = (
                    f"probe contract violation: {endpoint} fn must return a "
                    "ProviderExchange (CR-1.1 audit section 3.2-A) - use the "
                    "target's *_exchange methods"
                )
                raise TypeError(msg)
            meta = self.ctx.evidence_from_exchange(exchange)
            return exchange.payload, meta
        except ProviderAuthError as exc:
            # account-level fatal: terminal state, then re-raise so the CLI stops
            meta = self.ctx.failure_evidence(exc, endpoint=endpoint, dataset=dataset)
            self.ctx.case(
                case_id=f"SDK-AUTH-{uuid.uuid4().hex[:8]}",
                case_type=failure_case_type,
                security=symbol,
                provider_symbol=symbol,
                trade_date=trade_date,
                expected="authenticated account",
                actual=f"ProviderAuthError: {exc}"[:300],
                result=CaseResult.NOT_TESTABLE_ACCOUNT,
                evidence_meta=meta,
            )
            fail_run(self.ctx.store, self.ctx.run, RunFailureReason.FAILED_ACCOUNT)
            raise
        except ProviderPermissionError as exc:
            meta = self.ctx.failure_evidence(exc, endpoint=endpoint, dataset=dataset)
            self.ctx.case(
                case_id=f"SDK-PERM-{uuid.uuid4().hex[:8]}",
                case_type=failure_case_type,
                security=symbol,
                provider_symbol=symbol,
                trade_date=trade_date,
                expected="endpoint within account entitlement",
                actual=f"ProviderPermissionError: {exc}"[:300],
                result=CaseResult.NOT_TESTABLE_PERMISSION,
                evidence_meta=meta,
            )
            return None, meta
        except ProviderRateLimitError as exc:
            meta = self.ctx.failure_evidence(exc, endpoint=endpoint, dataset=dataset)
            self.ctx.case(
                case_id=f"SDK-RATE-{uuid.uuid4().hex[:8]}",
                case_type=failure_case_type,
                security=symbol,
                provider_symbol=symbol,
                trade_date=trade_date,
                expected="within flow/rate entitlement",
                actual=f"ProviderRateLimitError: {exc}"[:300],
                result=CaseResult.NOT_TESTABLE_ACCOUNT,
                evidence_meta=meta,
            )
            return None, meta
        except ProviderSchemaError as exc:
            meta = self.ctx.failure_evidence(exc, endpoint=endpoint, dataset=dataset)
            self.ctx.case(
                case_id=f"SDK-SCHEMA-{uuid.uuid4().hex[:8]}",
                case_type=failure_case_type,
                security=symbol,
                provider_symbol=symbol,
                trade_date=trade_date,
                expected="payload matches documented SDK contract",
                actual=f"ProviderSchemaError: {exc}"[:300],
                result=CaseResult.VALIDATED_FAIL,
                evidence_meta=meta,
            )
            return None, meta
        except ProviderError as exc:  # internal + unclassified
            meta = self.ctx.failure_evidence(exc, endpoint=endpoint, dataset=dataset)
            self.ctx.case(
                case_id=f"SDK-INTERNAL-{uuid.uuid4().hex[:8]}",
                case_type=failure_case_type,
                security=symbol,
                provider_symbol=symbol,
                trade_date=trade_date,
                expected="verifiable capability output",
                actual=f"{type(exc).__name__}: {exc}"[:300],
                result=CaseResult.MISSING,
                evidence_meta=meta,
            )
            return None, meta


def _observe_units(bar_rows: list[dict[str, Any]]) -> dict[str, str]:
    """R3-P0-07: derive the OBSERVED unit semantics from live data -
    amount/volume ~ price proves (shares, CNY). Independent of the
    documented constant."""
    checked = consistent = 0
    for row in bar_rows:
        try:
            close_f = float(row.get("CLOSE_PRICE") or row.get("CLOSE") or 0)
            volume_f = float(row.get("VOLUME") or 0)
            amount_f = float(row.get("AMOUNT") or 0)
        except (TypeError, ValueError):
            continue
        if close_f > 0 and volume_f > 0 and amount_f > 0:
            checked += 1
            if abs(amount_f / volume_f - close_f) / close_f <= 0.15:
                consistent += 1
    if checked and consistent / checked >= 0.9:
        return {"volume": "shares", "amount": "CNY"}
    return {"volume": "UNDETERMINED", "amount": "UNDETERMINED"}


def _calendar_ints(payload: Any) -> list[int]:
    """Extract trading-day ints from any calendar payload shape
    (list[int] / list[str] / list[dict] / frames) - CR-1.2 helper."""
    if payload is None:
        return []
    if isinstance(payload, list):
        out: list[int] = []
        for item in payload:
            if isinstance(item, dict):
                value = None
                for key in ("CAL_DATE", "TRADING_DATE", "TRADE_DATE", "CALENDAR_DATE", "value"):
                    if key in item:
                        value = item[key]
                        break
                item = value
            digits = "".join(ch for ch in str(item) if ch.isdigit())
            if len(digits) >= 8:
                out.append(int(digits[:8]))
        return out
    # frame/dict-of shapes: normalize to rows first, then recurse
    return _calendar_ints(_rows_of(payload))


def _persisted_calendar(
    ctx: ProbeContext,
    executor: ProbeExecutor,
    *,
    failure_case_type: str,
    trade_date: str,
    symbol: str = "SDK",
) -> tuple[list[int] | None, dict[str, Any]]:
    """CR-1.2 (audit R4-A2.4 section 2.3, option A): the kline trading-
    calendar prerequisite is EXPLICIT - fetch + persist the calendar
    exchange FIRST, then callers pass the windowed days to
    query_kline_exchange. A failed calendar exchange means kline MUST NOT
    fire (no fabricated success); the failure meta is already persisted."""
    calendar, cal_meta = executor.call(
        "BaseData.get_calendar",
        lambda: ctx.target.get_calendar_exchange(),
        failure_case_type=failure_case_type,
        trade_date=trade_date,
        symbol=symbol,
    )
    if calendar is None:
        return None, cal_meta
    return _calendar_ints(calendar), cal_meta


def _window_days(days: list[int], begin: int, end: int) -> list[int]:
    return [d for d in days if begin <= d <= end]


# ------------------------------------------------------------------------ B2


def probe_b2_security_master(ctx: ProbeContext) -> dict[str, Any]:
    """Security master incl. delisted (survivorship core gate)."""
    executor = ProbeExecutor(ctx)
    as_of = ctx.as_of_date  # R3-P1-09: run as-of, never hardcoded
    payload, meta = executor.call(
        "BaseData.get_hist_code_list",
        lambda: ctx.target.get_hist_code_list_exchange("EXTRA_STOCK_A_SH_SZ", 19900101, as_of),
        failure_case_type="security_master_with_delisted",
        trade_date=str(as_of),
        symbol="MARKET",
    )
    if payload is None:
        return {"result": "NOT_TESTABLE"}
    rows = _to_plain(_rows_of(payload))
    out = validators.validate_security_master_delisted(rows)
    ctx.outcome_case("security_master_with_delisted", "MARKET", str(as_of), meta, out)
    return {"rows": len(rows), "result": str(out.result)}


# ------------------------------------------------------------------------ B3


def probe_b3_core_facts(ctx: ProbeContext, sample_date: int) -> dict[str, Any]:
    """Daily bar units + ST/suspend semantics + limit rule on one date."""
    executor = ProbeExecutor(ctx)
    # CR-1.2 (audit R4-A2.4 section 2.2): the symbol-list prerequisite is an
    # EXPLICIT persisted exchange - no payload-only get_code_list on the
    # formal path.
    symbols_payload, _sym_meta = executor.call(
        "BaseData.get_code_list",
        lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
        failure_case_type="sdk_prerequisite_failure",
        trade_date=str(sample_date),
        symbol="MARKET",
    )
    symbols = (
        [str(s) for s in _flat_values(symbols_payload)][:5] if symbols_payload is not None else []
    )
    results: dict[str, Any] = {}

    # --- daily bar units (kline prerequisite: explicit persisted calendar)
    cal_days, _cal_meta = _persisted_calendar(
        ctx,
        executor,
        failure_case_type="daily_bar_units",
        trade_date=str(sample_date),
    )
    if cal_days is None or not symbols:
        results["daily_bar"] = "NOT_TESTABLE"
        if cal_days is None:
            ctx.case(
                case_id=f"B3-DAILYBAR-CALPREREQ-{sample_date}",
                case_type="daily_bar_units",
                security="SAMPLE",
                provider_symbol="SAMPLE",
                trade_date=str(sample_date),
                expected="calendar prerequisite exchange OK",
                actual="NOT_TESTABLE: calendar prerequisite failed; kline not fired",
                result=CaseResult.NOT_TESTABLE_PERMISSION,
                evidence_meta=_cal_meta,
            )
    else:
        bars, bar_meta = executor.call(
            "MarketData.query_kline",
            lambda: ctx.target.query_kline_exchange(
                symbols,
                begin_date=sample_date,
                end_date=sample_date,
                kline_type="DAY",
                trading_days=_window_days(cal_days, sample_date, sample_date),
            ),
            failure_case_type="daily_bar_units",
            trade_date=str(sample_date),
            symbol="SAMPLE",
        )
        if bars is None:
            results["daily_bar"] = "NOT_TESTABLE"
        else:
            bar_rows = _to_plain(_rows_of(bars))
            # R3-P0-07: observed units derive from live scale analysis of this
            # payload (amount/volume ~ close proves shares+CNY) - INDEPENDENT
            # of the documented constant
            observed_units = _observe_units(bar_rows)
            out = validators.validate_daily_bar_units(
                bar_rows,
                documented_units=DOCUMENTED_UNITS,
                observed_units=observed_units,
            )
            ctx.outcome_case("daily_bar_units", "SAMPLE", str(sample_date), bar_meta, out)
            results["daily_bar"] = str(out.result)

    # --- ST/suspend + limit (semantic case ids per R2 section 7)
    status, status_meta = executor.call(
        "InfoData.get_history_stock_status",
        lambda: ctx.target.get_history_stock_status_exchange(sample_date, sample_date, symbols),
        failure_case_type="historical_st_suspend",
        trade_date=str(sample_date),
        symbol="SAMPLE",
    )
    if status is None:
        results["st_suspend"] = "NOT_TESTABLE"
        results["limit"] = "NOT_TESTABLE"
    else:
        status_rows = _to_plain(_rows_of(status))
        # R4-A2.2a (audit section 36): B3 is STRUCTURAL validation only -
        # semantic ST truth belongs exclusively to the B4 reviewed golden
        # router. No fabricated expected_is_st here, ever.
        st_out = validators.validate_st_suspend_flags(status_rows, golden_facts=[])
        ctx.outcome_case("historical_st_suspend", "SAMPLE", str(sample_date), status_meta, st_out)
        # R4-A2.5 P0-01: EVERY formal limit consumer resolves rules through
        # the RUN-BOUND book (ctx.rule_book) - never the working tree
        limit_out = validators.validate_limit_rule(status_rows, book=ctx.rule_book)
        ctx.outcome_case(
            "limit_price_and_no_limit_days",
            "SAMPLE",
            str(sample_date),
            status_meta,
            limit_out,
        )
        results["st_suspend"] = str(st_out.result)
        results["limit"] = str(limit_out.result)

    # --- adj factor continuity
    adj, adj_meta = executor.call(
        "BaseData.get_adj_factor",
        lambda: ctx.target.get_adj_factor_exchange(symbols[:2]),
        failure_case_type="adj_factor_corporate_action_continuity",
        trade_date=str(sample_date),
        symbol="SAMPLE",
    )
    if adj is None:
        results["adj"] = "NOT_TESTABLE"
    else:
        adj_out = validators.validate_adj_continuity(_to_plain(_rows_of(adj)))
        ctx.outcome_case(
            "adj_factor_corporate_action_continuity",
            "SAMPLE",
            str(sample_date),
            adj_meta,
            adj_out,
        )
        results["adj"] = str(adj_out.result)
    return results


# ------------------------------------------------------------------------ B4


def probe_b4_golden(ctx: ProbeContext, sample_date: int) -> dict[str, Any]:
    """Golden pipeline (R4-A2.2a + R4-A2.3 section 6): DOMAIN-ROUTED
    comparison where every domain fetch goes through EXPLICIT
    ProviderExchanges persisted by the RawWriter; cases bind to the
    domain's evidence bundle (multi-endpoint lineage, audit section 6.3).
    Loads the RUN-BOUND dataset (R4A2-P0-02)."""
    from ashare_state.spike.golden_router import route_all
    from ashare_state.spike.golden_store import GoldenTruthStore

    if ctx.run.golden_dataset_file:
        golden_cases, golden_manifest = GoldenTruthStore().load_bound(
            dataset_file=ctx.run.golden_dataset_file,
            truth_version=ctx.run.golden_truth_version,
            dataset_hash=ctx.run.golden_dataset_hash,
        )
    else:
        # dry-run / unbound runs fall back to ACTIVE (never formal verdicts)
        golden_cases, golden_manifest = GoldenTruthStore().load()
    results: dict[str, int] = {}
    outcomes = route_all(ctx, list(golden_cases))
    for case, outcome, evidence_meta in outcomes:
        ctx.case(
            case_id=case.golden_case_id,
            case_type=case.case_type,
            security=case.provider_symbol,
            provider_symbol=case.provider_symbol,
            trade_date=case.trade_date,
            expected=f"{case.truth_source}: {case.expected_fields}",
            actual=outcome.actual,
            result=outcome.result,
            evidence_meta=evidence_meta,
            reason_code=outcome.reason_code,
            validator_id=outcome.validator_id,
            validator_version=outcome.validator_version,
            equivalent_pass=outcome.equivalent_pass,
        )
        results[str(outcome.result)] = results.get(str(outcome.result), 0) + 1
    return {
        "golden_cases": len(golden_cases),
        "golden_truth_version": golden_manifest.truth_version,
        "golden_dataset_hash": golden_manifest.dataset_hash[:16],
        "results": results,
    }


# ------------------------------------------------------------------------ B5


def probe_b5_units_pit_freshness(ctx: ProbeContext, sample_date: int) -> dict[str, Any]:
    """SDK permission/cache/freshness behavior (core gate) + EOD timing."""
    executor = ProbeExecutor(ctx)
    calendar, cal_meta = executor.call(
        "BaseData.get_calendar",
        lambda: ctx.target.get_calendar_exchange(),
        failure_case_type="sdk_permission_cache_freshness",
        trade_date=str(sample_date),
        symbol="SDK",
    )
    cal_all_days: list[int] | None = None if calendar is None else _calendar_ints(calendar)
    identity = ctx.target.identity()
    record = {
        "account_profile_id": identity.get("account_profile_id", ""),
        # R3-P0-11: the REAL permission codes come from the account profile,
        # never the profile id again
        "permission_codes": identity.get("permission_codes", ""),
        "cache_behavior": "documented_local_path_is_local",
        "calendar_rows": len(cal_all_days or []),
    }
    out = validators.validate_sdk_behavior_record(record)
    ctx.outcome_case("sdk_permission_cache_freshness", "SDK", str(sample_date), cal_meta, out)
    # history coverage core gate (audit section 38: FIXED fixtures - never
    # get_code_list()[:2], which samples provider CURRENT state, not
    # historical capability)
    fixtures = [
        "600519.SH",  # long-listed SH main board (1999)
        "000001.SZ",  # long-listed SZ main board (1991)
        "835185.BJ",  # BSE migrated listing (2021 opening)
        "300104.SZ",  # historical delisting (LeEco, delisted 2020)
    ]
    # CR-1.2: reuse the ALREADY-persisted calendar exchange above (single
    # fetch per probe) and pass its windowed days explicitly to kline.
    hist_days = (
        _window_days(cal_all_days, 20200101, sample_date) if cal_all_days is not None else None
    )
    if hist_days is None:
        bars, bar_meta = None, cal_meta
    else:
        bars, bar_meta = executor.call(
            "MarketData.query_kline",
            lambda: ctx.target.query_kline_exchange(
                fixtures,
                begin_date=20200101,
                end_date=sample_date,
                kline_type="DAY",
                trading_days=hist_days,
            ),
            failure_case_type="history_start_2020",
            trade_date=str(sample_date),
            symbol="FIXTURES",
        )
    if bars is None:
        earliest = ""
        if hist_days is None:
            # calendar prerequisite failed: coverage is NOT_TESTABLE (its
            # failure case is already recorded), never a fabricated FAIL
            ctx.case(
                case_id=f"B5-HISTCOV-CALPREREQ-{sample_date}",
                case_type="history_start_2020",
                security="FIXTURES",
                provider_symbol="FIXTURES",
                trade_date=str(sample_date),
                expected="calendar prerequisite exchange OK",
                actual="NOT_TESTABLE: calendar prerequisite failed; kline not fired",
                result=CaseResult.NOT_TESTABLE_PERMISSION,
                evidence_meta=cal_meta,
            )
            cov = None
        else:
            cov = validators.validate_history_coverage(earliest)
    else:
        rows = _to_plain(_rows_of(bars))
        earliest = min((str(r.get("KLINE_TIME", "99991231")) for r in rows), default="")
        cov = validators.validate_history_coverage(earliest)
    if cov is not None:
        ctx.outcome_case(
            "history_start_2020", "FIXTURES", str(sample_date), bar_meta, cov
        )
    # symbol mapping core gate - APPROVED exchange execution boundary
    # (CR-1.2.2 P0-01: the code-list prerequisite goes through
    # ProbeExecutor.call - success AND failure both persist as raw
    # evidence, failures become structured cases, and no caller is left
    # remembering to persist by hand). R4-A2.5 P0-05: scalar-list payloads
    # flatten via _flat_values (never coerce rows to strings).
    symbols_payload, sym_meta = executor.call(
        "BaseData.get_code_list",
        lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
        failure_case_type="symbol_mapping_unambiguous",
    )
    if symbols_payload is not None:
        symbols_all = [str(s) for s in _flat_values(symbols_payload)]
        sym_out = validators.validate_symbol_mapping(symbols_all)
        ctx.outcome_case("symbol_mapping_unambiguous", "MARKET", "", sym_meta, sym_out)
    else:
        # executor already structured the failure case + persisted the
        # failure exchange - nothing to validate, nothing left unhandled
        symbols_all = []
    # BSE/BJ independent core evidence (audit section 40): dedicated calls,
    # never "the current code list happens to include BJ"
    bse_status, bse_meta = executor.call(
        "InfoData.get_history_stock_status",
        lambda: ctx.target.get_history_stock_status_exchange(20220101, 20221231, ["835185.BJ"]),
        failure_case_type="limit_price_and_no_limit_days",
        trade_date="20220601",
        symbol="835185.BJ",
    )
    bse_rows = _to_plain(_rows_of(bse_status)) if bse_status is not None else []
    # R4-A2.5 P0-01: B5 BSE limit validation uses the run-bound book too
    bse_out = validators.validate_limit_rule(bse_rows, book=ctx.rule_book)
    ctx.outcome_case("limit_price_and_no_limit_days", "BSE", "20220601", bse_meta, bse_out)
    return {
        "calendar_rows": record["calendar_rows"],
        "earliest": earliest,
        "symbols": len(symbols_all),
        "bse_evidence_rows": len(bse_rows),
    }


# ------------------------------------------------------------------------ B6


def probe_b6_replacement(ctx: ProbeContext, sample_date: int) -> dict[str, Any]:
    """Free-float equivalence + taxonomy owner + benchmark (OPTIONAL gates).

    Real-account runs assess semantics; the structural probe records the
    OBSERVED shape so the assessment has evidence attached.
    """
    executor = ProbeExecutor(ctx)
    # CR-1.2.2 P0-01: B6's code-list prerequisite goes through the SAME
    # approved execution boundary (previously the exchange was created and
    # consumed WITHOUT persistence on both paths). R4-A2.5 P0-05:
    # _flat_values (scalar lists) - no silent row->str garbage.
    symbols_payload, _symbols_meta = executor.call(
        "BaseData.get_code_list",
        lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
        failure_case_type="free_float_equivalence",
        trade_date=str(sample_date),
        symbol="SAMPLE",
    )
    symbols = (
        [str(s) for s in _flat_values(symbols_payload)][:3] if symbols_payload is not None else []
    )
    if symbols:
        basic, basic_meta = executor.call(
            "InfoData.get_stock_basic",
            lambda: ctx.target.get_stock_basic_exchange(symbols),
            failure_case_type="free_float_equivalence",
            trade_date=str(sample_date),
            symbol="SAMPLE",
        )
    else:
        # code-list prerequisite failed (executor already structured that
        # case) - the dependent stock_basic call is NOT fired
        basic, basic_meta = None, _symbols_meta
    basic_available = basic is not None
    ctx.case(
        case_id=f"B6-FREEFLOAT-SEMANTICS-{sample_date}",
        case_type="free_float_equivalence",
        security="SAMPLE",
        provider_symbol="SAMPLE",
        trade_date=str(sample_date),
        expected="EXACT/DERIVABLE/ALTERNATIVE/MISSING vs free_share semantics",
        actual=(
            "OBSERVED: equity fields recorded; equivalence assessed live"
            if basic_available
            else "NOT_TESTABLE: stock_basic call failed"
        ),
        result=CaseResult.OBSERVED if basic_available else CaseResult.NOT_TESTABLE_PERMISSION,
        evidence_meta=basic_meta,
    )
    ctx.case(
        case_id=f"B6-TAXONOMY-OWNER-{sample_date}",
        case_type="sw_taxonomy",
        security="TAXONOMY",
        provider_symbol="TAXONOMY",
        trade_date="",
        expected="taxonomy owner identified (SW / GALAXY)",
        actual=(
            "OBSERVED: industry endpoints recorded; owner verified live"
            if basic_available
            else "NOT_TESTABLE"
        ),
        result=CaseResult.OBSERVED if basic_available else CaseResult.NOT_TESTABLE_PERMISSION,
        evidence_meta=basic_meta,
    )
    # CR-1.2: explicit persisted calendar prerequisite for the index kline
    idx_cal_days, _idx_cal_meta = _persisted_calendar(
        ctx,
        executor,
        failure_case_type="benchmark_index_availability",
        trade_date=str(sample_date),
        symbol="000300.SH",
    )
    if idx_cal_days is None:
        idx, idx_meta = None, _idx_cal_meta
    else:
        idx, idx_meta = executor.call(
            "MarketData.query_kline",
            lambda: ctx.target.query_kline_exchange(
                ["000300.SH"],
                begin_date=sample_date,
                end_date=sample_date,
                kline_type="DAY",
                trading_days=_window_days(idx_cal_days, sample_date, sample_date),
            ),
            failure_case_type="benchmark_index_availability",
            trade_date=str(sample_date),
            symbol="000300.SH",
        )
    ctx.case(
        case_id=f"B6-BENCHMARK-INDEX-{sample_date}",
        case_type="benchmark_index_availability",
        security="000300.SH",
        provider_symbol="000300.SH",
        trade_date=str(sample_date),
        expected="benchmark index daily rows present",
        actual=(f"OBSERVED: {len(_rows_of(idx))} rows" if idx is not None else "NOT_TESTABLE"),
        result=CaseResult.OBSERVED if idx is not None else CaseResult.NOT_TESTABLE_PERMISSION,
        evidence_meta=idx_meta,
    )
    return {"status": "OBSERVED" if basic_available else "NOT_TESTABLE"}


# ------------------------------------------------------------------------ B7


def probe_b7_capacity(ctx: ProbeContext, sample_date: int) -> dict[str, Any]:
    """Capacity/backfill metrics (R3-P1-08): MULTI-DAY loop structure.

    Dry-run/trial use one day; production runs pass trading_days (the
    run's calendar tail) and per-day rows/bytes/elapsed/requests are
    recorded, with first-pull vs cached-pull behavior distinguished.

    CR-1.1: request/retry counts are accumulated from each call's
    evidence meta (the explicit exchanges) - never from
    provider.last_envelopes.
    """
    import time

    executor = ProbeExecutor(ctx)
    # CR-1.2 (audit R4-A2.4 section 2.2): symbol list AND calendar are
    # explicit persisted exchanges on the formal path.
    symbols_payload, _sym_meta = executor.call(
        "BaseData.get_code_list",
        lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
        failure_case_type="capacity_backfill",
        trade_date=str(sample_date),
        symbol="MARKET",
    )
    symbols = [str(s) for s in _flat_values(symbols_payload)] if symbols_payload is not None else []
    cal_days, _cal_meta = _persisted_calendar(
        ctx,
        executor,
        failure_case_type="capacity_backfill",
        trade_date=str(sample_date),
    )
    if cal_days is None or not symbols:
        ctx.case(
            case_id=f"B7-CAPACITY-PREREQ-{sample_date}",
            case_type="capacity_backfill",
            security="ALL_A",
            provider_symbol="ALL_A",
            trade_date=str(sample_date),
            expected="symbols + calendar prerequisite exchanges OK",
            actual="NOT_TESTABLE: prerequisite exchange failed; per-day loop not fired",
            result=CaseResult.NOT_TESTABLE_PERMISSION,
            evidence_meta=_cal_meta if cal_days is None else _sym_meta,
        )
        return {
            "symbol_count": len(symbols),
            "day_window": [],
            "row_count": 0,
            "request_count": 0,
            "failure_count": 1,
            "prerequisite_failed": True,
        }
    # derive a small day window ending at the run as-of date
    days = [int(d) for d in cal_days if int(d) <= sample_date]
    window = days[-5:] if len(days) >= 5 else (days or [sample_date])

    per_day: list[dict[str, Any]] = []
    total_rows = 0
    total_bytes = 0
    total_elapsed = 0.0
    failures = 0
    request_count = 0
    retry_count = 0
    last_meta: dict[str, Any] = {}
    for day in window:
        started = time.monotonic()
        payload, meta = executor.call(
            "MarketData.query_kline",
            lambda d=day: ctx.target.query_kline_exchange(
                symbols,
                begin_date=d,
                end_date=d,
                kline_type="DAY",
                trading_days=[d],
            ),
            failure_case_type="capacity_backfill",
            trade_date=str(day),
            symbol="ALL_A",
        )
        # CR-1.1: counts come from the explicit exchange evidence, not from
        # provider.last_envelopes (diagnostic-only list)
        request_count += 1
        retry_count += max(0, int(meta.get("attempt_count", 1)) - 1)
        last_meta = meta
        elapsed = round(time.monotonic() - started, 3)
        if payload is None:
            failures += 1
            continue
        rows = _to_plain(_rows_of(payload))
        day_bytes = len(str(rows).encode("utf-8"))
        total_rows += len(rows)
        total_bytes += day_bytes
        total_elapsed += elapsed
        per_day.append(
            {
                "date": day,
                "row_count": len(rows),
                "bytes": day_bytes,
                "elapsed_seconds": elapsed,
                "rows_per_second": round(len(rows) / elapsed, 2) if elapsed else None,
                "pull": "first" if len(per_day) == 0 else "cached-or-first",
            }
        )
    metrics = {
        "symbol_count": len(symbols),
        "day_window": [str(d) for d in window],
        "row_count": total_rows,
        "bytes_received": total_bytes,
        "request_count": max(1, request_count),
        "retry_count": retry_count,
        "wall_clock_seconds": round(total_elapsed, 3),
        "throughput_rows_per_second": (
            round(total_rows / total_elapsed, 2) if total_elapsed else None
        ),
        "failure_count": failures,
        "failure_rate": round(failures / max(1, len(window)), 4),
        "peak_rss_mb": None,
        "per_day": per_day,
    }
    ctx.case(
        case_id=f"B7-CAPACITY-{sample_date}",
        case_type="capacity_backfill",
        security="ALL_A",
        provider_symbol="ALL_A",
        trade_date=str(sample_date),
        expected="capacity metrics recorded (rows/bytes/throughput per day)",
        actual=(
            f"days={len(window)} rows={total_rows} wall={total_elapsed:.1f}s failures={failures}"
        ),
        result=CaseResult.OBSERVED if not failures else CaseResult.VALIDATED_FAIL,
        evidence_meta=last_meta,
    )
    return metrics
