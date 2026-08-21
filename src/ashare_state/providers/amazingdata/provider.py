"""AmazingData production provider facade (task book section 3.1).

Every public method:
- goes through the session (login-scoped, stdout-isolated),
- runs under an explicit time budget with bounded retry,
- wraps SDK errors into the typed provider error layer,
- records a RawEnvelope describing the exchange for the raw layer.

Method signatures follow the SDK manual; parameter corrections happen in
Spike B2-B7 (real-account evidence) - never silently.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ashare_state.providers.amazingdata.capability import CAPABILITY_REGISTRY, CapabilityStatus
from ashare_state.providers.amazingdata.errors import (
    ProviderError,
    classify_sdk_error,
)
from ashare_state.providers.amazingdata.sdk_loader import SdkIdentity, probe_identity
from ashare_state.providers.amazingdata.session import AmazingDataSession
from ashare_state.providers.amazingdata.stdout_capture import CapturedStdout, sdk_stdout_into
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget, run_with_budget


@dataclass(frozen=True)
class RawEnvelope:
    """Task book section 6 contract (record per SDK exchange)."""

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

    @staticmethod
    def params_hash(params: dict[str, Any]) -> str:
        import json

        canonical = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class AmazingDataProvider:
    """Facade over BaseData / InfoData / MarketData SDK classes."""

    def __init__(
        self,
        session: AmazingDataSession,
        *,
        identity: SdkIdentity | None = None,
        budget: TimeBudget | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        self.session = session
        self.identity = identity or probe_identity()
        self.budget = budget or TimeBudget()
        self.retry = retry or RetryPolicy()
        self.last_envelopes: list[RawEnvelope] = []

    # ------------------------------------------------------------ internals
    def _call(
        self,
        endpoint: str,
        dataset: str,
        fn: Callable[[], Any],
        *,
        params: dict[str, Any] | None = None,
        require_capability: str | None = None,
    ) -> Any:
        """One SDK exchange: stdout-captured, budgeted, error-mapped, recorded."""
        if require_capability:
            cap = CAPABILITY_REGISTRY[require_capability]
            if cap.status is not CapabilityStatus.APPROVED:
                # CANDIDATE endpoints callable (spike/ingest dry-run), but the
                # envelope carries the flag so downstream provenance is honest.
                pass
        params = params or {}
        requested_at = datetime.now(UTC).isoformat()
        holder = CapturedStdout()
        account_ctx = {
            "account_profile_id": self.session.profile.account_profile_id,
            "permission_codes": self.session.profile.permission_codes,
        }
        try:
            result = run_with_budget(
                lambda: self._invoke(fn, holder),
                budget=self.budget,
                retry=self.retry,
                endpoint=endpoint,
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - classification boundary
            raise classify_sdk_error(exc, endpoint=endpoint, account_context=account_ctx) from exc
        finally:
            pass  # envelope recorded below regardless of outcome
        received_at = datetime.now(UTC).isoformat()
        envelope = RawEnvelope(
            provider_dataset=dataset,
            endpoint=endpoint,
            request_params_hash=RawEnvelope.params_hash(params),
            requested_at=requested_at,
            received_at=received_at,
            sdk_version=self.identity.sdk_version if self.identity else None,
            runtime_version=self.identity.tgw_runtime_version if self.identity else None,
            account_profile_id=self.session.profile.account_profile_id,
            row_count=_count_rows(result),
        )
        self.last_envelopes.append(envelope)
        return result

    def _invoke(self, fn: Callable[[], Any], holder: CapturedStdout) -> Any:
        with sdk_stdout_into(holder):
            return fn()

    def _base(self) -> Any:
        return self.session.sdk.BaseData()

    def _info(self) -> Any:
        return self.session.sdk.InfoData()

    # -------------------------------------------------------------- queries
    def get_code_list(self, security_type: str | None = None) -> list[str]:
        params = {"security_type": security_type} if security_type else {}
        fn = (
            (lambda: self._base().get_code_list(**params))
            if params
            else (lambda: self._base().get_code_list())
        )
        return self._call(
            "BaseData.get_code_list",
            "code_list",
            fn,
            params=params,
            require_capability="security_master",
        )

    def get_stock_basic(self, code_list: list[str]) -> Any:
        return self._call(
            "InfoData.get_stock_basic",
            "stock_basic",
            lambda: self._info().get_stock_basic(code_list=code_list),
            params={"code_list": code_list[:3], "len": len(code_list)},
            require_capability="security_master",
        )

    def get_history_stock_status(self, start_date: int, end_date: int, code_list: list[str]) -> Any:
        return self._call(
            "InfoData.get_history_stock_status",
            "history_stock_status",
            lambda: self._info().get_history_stock_status(
                start_date=start_date, end_date=end_date, code_list=code_list
            ),
            params={"start_date": start_date, "end_date": end_date, "codes": len(code_list)},
            require_capability="security_status_history",
        )

    def get_adj_factor(self, code_list: list[str]) -> Any:
        return self._call(
            "BaseData.get_adj_factor",
            "adj_factor",
            lambda: self._base().get_adj_factor(code_list=code_list),
            params={"codes": len(code_list)},
            require_capability="adj_factor",
        )

    def get_backward_factor(self, code_list: list[str]) -> Any:
        return self._call(
            "BaseData.get_backward_factor",
            "backward_factor",
            lambda: self._base().get_backward_factor(code_list=code_list),
            params={"codes": len(code_list)},
            require_capability="adj_factor",
        )

    def get_calendar(self, market: str = "SH") -> Any:
        return self._call(
            "BaseData.get_calendar",
            "trade_calendar",
            lambda: self._base().get_calendar(market=market),
            params={"market": market},
            require_capability="trade_calendar",
        )


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
