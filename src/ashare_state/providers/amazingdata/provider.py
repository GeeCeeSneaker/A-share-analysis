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
    """

    provider: str = "amazingdata"
    provider_dataset: str = ""
    endpoint: str = ""

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
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
        """One SDK exchange: gated, stdout-captured, budgeted, recorded."""
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
            params={"code_list": code_list[:3], "len": len(code_list)},
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
            params={"start_date": start_date, "end_date": end_date, "codes": len(code_list)},
            require_capability="security_status_history",
        )

    def get_history_stock_status(self, start_date: int, end_date: int, code_list: list[str]) -> Any:
        return self.get_history_stock_status_exchange(start_date, end_date, code_list).payload

    def get_adj_factor_exchange(self, code_list: list[str]) -> Any:
        return self._call_or_exchange(
            "BaseData.get_adj_factor",
            "adj_factor",
            lambda: self._base().get_adj_factor(code_list=code_list),
            params={"codes": len(code_list)},
            require_capability="adj_factor",
        )

    def get_adj_factor(self, code_list: list[str]) -> Any:
        return self.get_adj_factor_exchange(code_list).payload

    def get_backward_factor_exchange(self, code_list: list[str]) -> Any:
        return self._call_or_exchange(
            "BaseData.get_backward_factor",
            "backward_factor",
            lambda: self._base().get_backward_factor(code_list=code_list),
            params={"codes": len(code_list)},
            require_capability="adj_factor",
        )

    def get_backward_factor(self, code_list: list[str]) -> Any:
        return self.get_backward_factor_exchange(code_list).payload

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
    ) -> Any:
        return self._call_or_exchange(
            "MarketData.query_kline",
            "daily_bar",
            lambda: self._market(begin_date, end_date).query_kline(
                code_list=code_list,
                begin_date=begin_date,
                end_date=end_date,
                kline_type=kline_type,
            ),
            params={
                "codes": len(code_list),
                "begin_date": begin_date,
                "end_date": end_date,
                "kline_type": kline_type,
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
        return self.query_kline_exchange(
            code_list, begin_date=begin_date, end_date=end_date, kline_type=kline_type
        ).payload

    def _market(self, begin_date: int, end_date: int) -> Any:
        """MarketData(calendar) needs the trading-day list covering the range.

        CR-1 (audit section 44): the calendar fetch is a REAL SDK call and
        gets its OWN exchange (endpoint BaseData.get_calendar) - it is never
        buried inside the query_kline envelope.
        """
        calendar = self.get_calendar()
        days = [d for d in (calendar or []) if begin_date <= int(d) <= end_date]
        return self.session.sdk.MarketData(days or [begin_date, end_date])


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
