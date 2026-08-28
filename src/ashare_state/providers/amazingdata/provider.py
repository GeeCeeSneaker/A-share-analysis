"""AmazingData production provider facade (task book section 3.1).

Every public method:
- goes through the session (login-scoped, stdout-isolated),
- runs under an explicit retry budget with class-aware retries
  (audit P0-03: classify FIRST, retry only network/timeout/rate-limit),
- enforces the capability use mode (audit P1-02: PRODUCTION requires
  APPROVED capabilities; SPIKE must be explicit opt-in),
- records a RawEnvelope for EVERY exchange, success OR failure
  (audit P1-04: failed calls are auditable evidence too).

Method signatures follow the SDK manual; parameter corrections happen in
Spike B2-B7 (real-account evidence) - never silently.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ashare_state.providers.amazingdata.capability import CAPABILITY_REGISTRY, CapabilityStatus
from ashare_state.providers.amazingdata.errors import (
    ProviderCapabilityNotApprovedError,
    ProviderError,
    classify_sdk_error,
)
from ashare_state.providers.amazingdata.sdk_loader import SdkIdentity, probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.stdout_capture import CapturedStdout, sdk_stdout_into
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget, run_with_budget
from ashare_state.providers.exchange import ProviderExchange


class ProviderUseMode(StrEnum):
    """Audit P1-02: capability gating mode.

    SPIKE      - explicit opt-in; CANDIDATE capabilities callable (Spike only)
    PRODUCTION - default; only APPROVED capabilities callable
    """

    SPIKE = "SPIKE"
    PRODUCTION = "PRODUCTION"


@dataclass(frozen=True)
class RawEnvelope:
    """Task book section 6 contract (record per SDK exchange).

    Audit P1-04: envelopes are produced for FAILED calls too (status/error
    fields), so a denial is auditable evidence rather than a lost event.

    CR-1.2 (audit R4-A2.4 section 3.3): ``request_params`` carries the FULL
    real request parameters (complete code lists, dates, options) - never a
    count/first-N summary. ``request_params_hash`` is the SHA-256 of the
    canonical JSON of those full params, so equal-size requests over
    DIFFERENT symbols hash differently and the request is reconstructable
    from the persisted (scrubbed) meta alone.
    """

    provider: str = "amazingdata"
    provider_dataset: str = ""
    endpoint: str = ""

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_params: dict[str, Any] = field(default_factory=dict)
    request_params_hash: str = ""

    requested_at: str = ""
    received_at: str = ""

    sdk_version: str | None = None
    runtime_version: str | None = None
    account_profile_id: str = "UNKNOWN"

    row_count: int = 0
    schema_hash: str = ""  # filled by the raw writer (columns+types)
    content_hash: str = ""  # filled by the raw writer (payload bytes)

    source_revision: str | None = None
    raw_file_uri: str | None = None
    quality_flags: list[str] = field(default_factory=list)

    # audit P1-04 outcome fields
    status: str = "OK"  # OK | ERROR
    error_class: str | None = None
    duration_ms: float = 0.0
    attempt_count: int = 1
    capability_status: str | None = None

    @staticmethod
    def params_hash(params: dict[str, Any]) -> str:
        import json

        canonical = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
        # full SHA-256 (audit P2: no truncation - collision-proof request id)
        return hashlib.sha256(canonical.encode()).hexdigest()


class AmazingDataProvider:
    """Facade over BaseData / InfoData / MarketData SDK classes."""

    def __init__(
        self,
        session: AmazingDataSession,
        *,
        identity: SdkIdentity | None = None,
        budget: TimeBudget | None = None,
        retry: RetryPolicy | None = None,
        use_mode: ProviderUseMode = ProviderUseMode.PRODUCTION,
    ) -> None:
        self.session = session
        self.identity = identity or probe_identity()
        self.budget = budget or TimeBudget()
        self.retry = retry or RetryPolicy()
        self.use_mode = use_mode
        # DIAGNOSTIC-ONLY (CR-1.1 audit §3.2-B): last_envelopes may be kept
        # for debugging/inspection; correctness and lineage paths are
        # FORBIDDEN from reverse-searching it - they consume the explicit
        # ProviderExchange returned by call_exchange / attached to errors.
        self.last_envelopes: list[RawEnvelope] = []

    def _call_or_payload(self, *args: object, **kwargs: object) -> Any:
        """Business convenience path (audit section 43): returns .payload."""
        exchange = self.call_exchange(*args, **kwargs)  # type: ignore[arg-type]
        return exchange.payload

    def _call_or_exchange(self, *args: object, **kwargs: object) -> Any:
        """Explicit exchange path (CR-1.1 audit §3.2-A): returns the
        ProviderExchange itself - probes / RawWriter / audit paths MUST
        consume this, never the payload convenience wrapper."""
        return self.call_exchange(*args, **kwargs)  # type: ignore[arg-type]

    # ------------------------------------------------------------ internals
    def _gate_capability(self, capability: str | None) -> CapabilityStatus | None:
        """Audit P1-02 / R2-P1-02: PRODUCTION refuses CANDIDATE capabilities
        with a GOVERNANCE error (never ProviderPermissionError - that class
        is reserved for broker-side entitlement)."""
        if capability is None:
            return None
        cap = CAPABILITY_REGISTRY[capability]
        if (
            self.use_mode is ProviderUseMode.PRODUCTION
            and cap.status is not CapabilityStatus.APPROVED
        ):
            msg = (
                f"capability {capability!r} is {cap.status}, not APPROVED; "
                "PRODUCTION use mode allows APPROVED capabilities only - "
                "spike usage must explicitly opt in with ProviderUseMode.SPIKE"
            )
            raise ProviderCapabilityNotApprovedError(msg, context={"capability": capability})
        return cap.status

    def call_exchange(
        self,
        endpoint: str,
        dataset: str,
        fn: Callable[[], Any],
        *,
        params: dict[str, Any] | None = None,
        require_capability: str | None = None,
    ) -> Any:
        """One SDK exchange: gated, stdout-captured, budgeted, recorded.

        R4-A3 A3-01 (audit 20260826 section 7.2): the LIFECYCLE gate fires
        FIRST - after a terminal SDK/auth failure the endpoint function is
        NEVER invoked (early stop: ProviderLifecycleTerminalError, a typed
        error carrying the terminal state/reason/evidence, raised before
        any capability check or SDK call)."""
        self.session.lifecycle.require_ready(endpoint)
        cap_status = self._gate_capability(require_capability)
        params = params or {}
        requested_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        holder = CapturedStdout()
        account_ctx = {
            "account_profile_id": self.session.profile.account_profile_id,
            "permission_codes": self.session.profile.permission_codes,
        }

        def envelope(
            status: str, error_class: str | None, attempts: int, row_count: int
        ) -> RawEnvelope:
            env = RawEnvelope(
                provider_dataset=dataset,
                endpoint=endpoint,
                request_params=dict(params),  # CR-1.2: FULL real params
                request_params_hash=RawEnvelope.params_hash(params),
                requested_at=requested_at,
                received_at=datetime.now(UTC).isoformat(),
                sdk_version=self.identity.sdk_version if self.identity else None,
                runtime_version=self.identity.tgw_runtime_version if self.identity else None,
                account_profile_id=self.session.profile.account_profile_id,
                row_count=row_count,
                status=status,
                error_class=error_class,
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                attempt_count=attempts,
                capability_status=str(cap_status) if cap_status else None,
            )
            self.last_envelopes.append(env)
            return env

        attempt_state = {"attempts": 0}

        def invoke() -> Any:
            # classify INSIDE the budget loop so retry decisions use the
            # typed class (audit P0-03: permission errors never retry)
            attempt_state["attempts"] += 1
            with sdk_stdout_into(holder):
                try:
                    return fn()
                except ProviderError:
                    raise
                except Exception as exc:  # noqa: BLE001 - classification boundary
                    raise classify_sdk_error(
                        exc, endpoint=endpoint, account_context=account_ctx
                    ) from exc

        try:
            result = run_with_budget(
                invoke,
                budget=self.budget,
                retry=self.retry,
                endpoint=endpoint,
            )
        except ProviderError as exc:
            env = envelope("ERROR", type(exc).__name__, attempt_state["attempts"], 0)
            # CR-1.1 (audit §3.2-D): the FAILED exchange is a first-class
            # object attached to the raised error - callers never reverse-
            # search last_envelopes (diagnostic-only list) for it.
            exc.exchange = ProviderExchange(envelope=env, payload=None)
            raise
        env = envelope("OK", None, attempt_state["attempts"], _count_rows(result))
        return ProviderExchange(envelope=env, payload=result)

    def _base(self) -> Any:
        return self.session.sdk.BaseData()

    def _info(self) -> Any:
        return self.session.sdk.InfoData()

    # -------------------------------------------------------------- queries
    def get_code_list_exchange(self, security_type: str | None = None) -> Any:
        params = {"security_type": security_type} if security_type else {}
        fn = (
            (lambda: self._base().get_code_list(**params))
            if params
            else (lambda: self._base().get_code_list())
        )
        return self._call_or_exchange(
            "BaseData.get_code_list",
            "code_list",
            fn,
            params=params,
            require_capability="security_master",
        )

    def get_code_list(self, security_type: str | None = None) -> list[str]:
        return self.get_code_list_exchange(security_type).payload

    def get_stock_basic_exchange(self, code_list: list[str]) -> Any:
        return self._call_or_exchange(
            "InfoData.get_stock_basic",
            "stock_basic",
            lambda: self._info().get_stock_basic(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="security_master",
        )

    def get_stock_basic(self, code_list: list[str]) -> Any:
        return self.get_stock_basic_exchange(code_list).payload

    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> Any:
        return self._call_or_exchange(
            "InfoData.get_history_stock_status",
            "history_stock_status",
            lambda: self._info().get_history_stock_status(
                start_date=start_date, end_date=end_date, code_list=code_list
            ),
            params={
                "start_date": start_date,
                "end_date": end_date,
                "code_list": list(code_list),
            },
            require_capability="security_status_history",
        )

    def get_history_stock_status(self, start_date: int, end_date: int, code_list: list[str]) -> Any:
        return self.get_history_stock_status_exchange(start_date, end_date, code_list).payload

    def get_adj_factor_exchange(self, code_list: list[str]) -> Any:
        return self._call_or_exchange(
            "BaseData.get_adj_factor",
            "adj_factor",
            lambda: self._base().get_adj_factor(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="adj_factor",
        )

    def get_adj_factor(self, code_list: list[str]) -> Any:
        return self.get_adj_factor_exchange(code_list).payload

    def get_backward_factor_exchange(self, code_list: list[str]) -> Any:
        return self._call_or_exchange(
            "BaseData.get_backward_factor",
            "backward_factor",
            lambda: self._base().get_backward_factor(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="adj_factor",
        )

    def get_backward_factor(self, code_list: list[str]) -> Any:
        return self.get_backward_factor_exchange(code_list).payload

    def get_dividend_exchange(self, code_list: list[str]) -> Any:
        """Corporate-action event records (dividend/right issue).

        R4-A2.4 P0-05: the CA validator needs an EVENT FACT SOURCE (exact
        ex-date + event type), not just the adj factor stream. This
        endpoint is the provider-side event SoR (capability
        ``corporate_action`` -> InfoData.get_dividend).
        """
        return self._call_or_exchange(
            "InfoData.get_dividend",
            "corporate_action",
            lambda: self._info().get_dividend(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="corporate_action",
        )

    def get_right_issue_exchange(self, code_list: list[str]) -> Any:
        """Right-issue event records (R4-A2.5 P0-04).

        Dividend and right-issue are SEPARATE event streams in the
        corporate_action capability (InfoData.get_right_issue): a DIVIDEND
        record can never substitute a RIGHT_ISSUE expectation in the CA
        golden validation.
        """
        return self._call_or_exchange(
            "InfoData.get_right_issue",
            "corporate_action",
            lambda: self._info().get_right_issue(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="corporate_action",
        )

    def get_right_issue(self, code_list: list[str]) -> Any:
        return self.get_right_issue_exchange(code_list).payload

    def get_bj_code_mapping_exchange(self, code_list: list[str]) -> Any:
        """Dedicated Beijing Stock Exchange code-mapping endpoint
        (R4-B1 B1-02, audit 20260828): capability ``code_mapping_bj`` ->
        InfoData.get_bj_code_mapping. A generic stock-code list is a
        stand-in and can NEVER prove this endpoint."""
        return self._call_or_exchange(
            "InfoData.get_bj_code_mapping",
            "code_mapping_bj",
            lambda: self._info().get_bj_code_mapping(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="code_mapping_bj",
        )

    def get_bj_code_mapping(self, code_list: list[str]) -> Any:
        return self.get_bj_code_mapping_exchange(code_list).payload

    def get_dividend(self, code_list: list[str]) -> Any:
        return self.get_dividend_exchange(code_list).payload

    def get_equity_structure_exchange(self, code_list: list[str]) -> Any:
        """Dedicated equity-structure endpoint (R4-B1 B1-02):
        capability ``equity_structure`` -> InfoData.get_equity_structure.
        ``get_stock_basic`` is a stand-in and can NEVER prove it."""
        return self._call_or_exchange(
            "InfoData.get_equity_structure",
            "equity_structure",
            lambda: self._info().get_equity_structure(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="equity_structure",
        )

    def get_equity_structure(self, code_list: list[str]) -> Any:
        return self.get_equity_structure_exchange(code_list).payload

    def get_industry_base_info_exchange(self, code_list: list[str]) -> Any:
        """Dedicated industry-taxonomy endpoint (R4-B1 B1-02):
        capability ``industry_taxonomy`` -> InfoData.get_industry_base_info.
        ``get_stock_basic`` is a stand-in and can NEVER prove it."""
        return self._call_or_exchange(
            "InfoData.get_industry_base_info",
            "industry_taxonomy",
            lambda: self._info().get_industry_base_info(code_list=code_list),
            params={"code_list": list(code_list)},
            require_capability="industry_taxonomy",
        )

    def get_industry_base_info(self, code_list: list[str]) -> Any:
        return self.get_industry_base_info_exchange(code_list).payload

    def get_calendar_exchange(self, market: str = "SH") -> Any:
        return self._call_or_exchange(
            "BaseData.get_calendar",
            "trade_calendar",
            lambda: self._base().get_calendar(market=market),
            params={"market": market},
            require_capability="trade_calendar",
        )

    def get_calendar(self, market: str = "SH") -> Any:
        return self.get_calendar_exchange(market).payload

    def get_hist_code_list_exchange(
        self, security_type: str, start_date: int, end_date: int
    ) -> Any:
        return self._call_or_exchange(
            "BaseData.get_hist_code_list",
            "hist_code_list",
            lambda: self._base().get_hist_code_list(
                security_type=security_type, start_date=start_date, end_date=end_date
            ),
            params={
                "security_type": security_type,
                "start_date": start_date,
                "end_date": end_date,
            },
            require_capability="security_master",
        )

    def get_hist_code_list(self, security_type: str, start_date: int, end_date: int) -> Any:
        return self.get_hist_code_list_exchange(security_type, start_date, end_date).payload

    def query_kline_exchange(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        kline_type: str = "DAY",
        trading_days: list[int] | None = None,
    ) -> Any:
        """Explicit-exchange kline query.

        CR-1.2 (audit R4-A2.4 section 2.3, option A): the trading-calendar
        prerequisite is EXPLICIT - audit/formal callers must first fetch +
        persist ``get_calendar_exchange`` and pass the windowed ``trading_days``
        here. Passing ``trading_days=None`` is allowed ONLY on the business
        convenience path (``query_kline``), which fetches the calendar
        internally and is FORBIDDEN on spike/formal evidence paths (static
        AST test). The calendar exchange of the convenience path never
        reaches formal evidence.
        """
        days = trading_days
        if days is None:
            calendar = self.get_calendar()
            days = [d for d in (calendar or []) if begin_date <= int(d) <= end_date]
        return self._call_or_exchange(
            "MarketData.query_kline",
            "daily_bar",
            lambda: self._market(days or [begin_date, end_date]).query_kline(
                code_list=code_list,
                begin_date=begin_date,
                end_date=end_date,
                kline_type=kline_type,
            ),
            params={
                "code_list": list(code_list),
                "begin_date": begin_date,
                "end_date": end_date,
                "kline_type": kline_type,
                "trading_days": list(days),
            },
            require_capability="daily_bar",
        )

    def query_kline(
        self,
        code_list: list[str],
        *,
        begin_date: int,
        end_date: int,
        kline_type: str = "DAY",
    ) -> Any:
        """Business convenience path (NOT for spike/formal evidence paths)."""
        return self.query_kline_exchange(
            code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
        ).payload

    def _market(self, trading_days: list[int]) -> Any:
        """MarketData(calendar) built from EXPLICIT trading days.

        CR-1/CR-1.2 (audit section 44 + R4-A2.4 section 2.3): the calendar
        fetch is a REAL SDK call and gets its OWN exchange - the formal path
        persists it via ``get_calendar_exchange`` and passes the windowed
        days here; nothing calendar-related is buried inside the kline
        exchange on the explicit path.
        """
        return self.session.sdk.MarketData(list(trading_days))


def _count_rows(result: Any) -> int:
    if result is None:
        return 0
    if isinstance(result, dict):
        return sum(len(v) for v in result.values() if hasattr(v, "__len__"))
    if hasattr(result, "__len__"):
        try:
            return len(result)
        except TypeError:
            return 1
    return 1
