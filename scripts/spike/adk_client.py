"""AmazingData SDK client wrapper for the Spike (B1-B9).

Contract (design ruling 9):
- The SDK is broker-distributed; its importable module name is UNKNOWN until
  B1 verifies it. It is configurable via AMAZINGDATA_MODULE env (default
  "AmazingData") and must be lazy-imported.
- Every request goes through serial throttling + bounded retry with
  exponential backoff (ruling: never trip provider risk control).
- Raw responses are archived verbatim to data/spike/raw/ as audit evidence;
  no token/credential ever enters a file or log.
- A deterministic FakeClient powers --dry-run so the whole Spike framework
  (catalog, evidence layout, report) is CI-testable without credentials.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ProviderUnavailableError(RuntimeError):
    """AmazingData SDK not installed / not importable (expected outside the
    controlled dev machine; CI must never see it as a failure)."""


class RetryBudgetExhaustedError(RuntimeError):
    """All retries exhausted on a retryable error."""


@dataclass
class ThrottlePolicy:
    request_interval_seconds: float = 1.0
    max_retries: int = 3
    retry_backoff_base_seconds: float = 2.0


@dataclass
class RequestReceipt:
    """Every SDK call returns one - the audit trail unit."""

    method: str
    params: dict[str, Any]
    ok: bool
    row_count: int
    duration_ms: float
    attempt: int
    error: str = ""
    raw_ref: str = ""  # relative path under data/spike/raw/
    content_hash: str = ""


@dataclass
class AmazingDataClient:
    """Thin wrapper: throttle, retry, archive, evidence."""

    module_name: str
    spike_root: Path
    throttle: ThrottlePolicy = field(default_factory=ThrottlePolicy)
    _last_call_ts: float = field(default=0.0, init=False)
    _request_count: int = field(default=0, init=False)
    _retry_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.raw_dir = self.spike_root / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._sdk: Any = None

    # ------------------------------------------------------------------ sdk
    def _ensure_sdk(self) -> Any:
        if self._sdk is None:
            try:
                self._sdk = __import__(self.module_name)
            except ImportError as exc:
                msg = (
                    f"AmazingData SDK module {self.module_name!r} not importable; "
                    "install the broker wheel on the controlled machine and "
                    "record it in docs/provider_verification/amazingdata.md"
                )
                raise ProviderUnavailableError(msg) from exc
        return self._sdk

    # -------------------------------------------------------------- archive
    def _archive(self, method: str, params: dict[str, Any], payload: Any) -> str:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        seq = self._request_count
        rel = f"raw/{stamp}-{seq:04d}-{method}.json"
        path = self.spike_root / rel
        doc = {
            "method": method,
            "params": _scrub(params),
            "payload": payload,
        }
        path.write_text(json.dumps(doc, ensure_ascii=False, default=str), encoding="utf-8")
        return rel

    # --------------------------------------------------------------- call
    def call(self, method: str, **params: Any) -> RequestReceipt:
        """Invoke SDK method with throttle + bounded retry; archive evidence."""
        # serial throttle
        wait = self.throttle.request_interval_seconds - (time.monotonic() - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)

        last_error = ""
        for attempt in range(1, self.throttle.max_retries + 1):
            self._request_count += 1
            self._last_call_ts = time.monotonic()
            started = time.perf_counter()
            try:
                sdk = self._ensure_sdk()
                fn = getattr(sdk, method)
                result = fn(**params)
                duration_ms = (time.perf_counter() - started) * 1000
                rows = _count_rows(result)
                raw_ref = self._archive(method, params, _to_jsonable(result))
                return RequestReceipt(
                    method=method,
                    params=dict(params),
                    ok=True,
                    row_count=rows,
                    duration_ms=duration_ms,
                    attempt=attempt,
                    raw_ref=raw_ref,
                )
            except ProviderUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001 - provider errors are opaque
                last_error = f"{type(exc).__name__}: {exc}"
                self._retry_count += 1
                if attempt < self.throttle.max_retries:
                    time.sleep(self.throttle.retry_backoff_base_seconds**attempt)
        raise RetryBudgetExhaustedError(
            f"{method} failed after {self.throttle.max_retries} attempts: {last_error}"
        )

    # -------------------------------------------------------------- stats
    def usage(self) -> dict[str, Any]:
        return {
            "request_count": self._request_count,
            "retry_count": self._retry_count,
        }


class FakeAmazingDataClient:
    """Deterministic stand-in for --dry-run (framework validation only).

    Produces plausible-but-fake responses for the B1-B7 probes so the
    catalog/evidence/report plumbing can be exercised end to end in CI.
    NOT a data source: outputs are clearly marked FAKE.
    """

    def __init__(self, spike_root: Path, throttle: ThrottlePolicy | None = None) -> None:
        self.throttle = throttle or ThrottlePolicy(request_interval_seconds=0.0)
        self._real = AmazingDataClient(
            module_name="fake", spike_root=spike_root, throttle=self.throttle
        )
        self._real._ensure_sdk = lambda: _FakeSdk()  # type: ignore[method-assign]

    def call(self, method: str, **params: Any) -> RequestReceipt:
        return self._real.call(method, **params)

    def usage(self) -> dict[str, Any]:
        return self._real.usage()


class _FakeSdk:
    """Fake SDK surface covering the Spike probe methods."""

    def __getattr__(self, name: str) -> Any:
        def _fake_method(**_params: Any) -> dict[str, Any]:
            return {
                "FAKE": True,
                "method": name,
                "rows": [
                    {
                        "SECURITY_CODE": "000001",
                        "TRADE_DATE": "2026-08-14",
                        "CLOSE": 10.5,
                        "VOLUME": 1000000,
                        "AMOUNT": 10500000.0,
                    }
                ],
            }

        return _fake_method


def _scrub(params: dict[str, Any]) -> dict[str, Any]:
    """Remove credential-looking values before archiving."""
    out = {}
    for k, v in params.items():
        if any(s in k.lower() for s in ("password", "token", "secret", "credential")):
            out[k] = "***MASKED***"
        else:
            out[k] = v
    return out


def _count_rows(payload: Any) -> int:
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return len(payload["rows"])
    if isinstance(payload, list):
        return len(payload)
    return 1


def _to_jsonable(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return repr(obj)
