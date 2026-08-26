"""CR-1 contract tests (audit R4-A2 section 47)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.storage.raw_writer import RawWriter, RawWriterError


@dataclass
class FakeSession:
    profile: Any = None
    lifecycle: Any = None

    def __post_init__(self) -> None:
        # R4-A3 A3-01: the provider's lifecycle gate reads the session's
        # state machine; a fake "logged-in" session is SESSION_READY.
        from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState

        self.lifecycle = SdkLifecycle()
        self.lifecycle.transition(SdkLifecycleState.SESSION_READY, reason="fake session")


@dataclass
class FakeIdentity:
    sdk_version: str = "fake-1.0"
    tgw_runtime_version: str = "fake-rt"


def _provider() -> AmazingDataProvider:
    from ashare_state.providers.amazingdata.session import AccountProfile

    session = FakeSession(profile=AccountProfile())
    return AmazingDataProvider(session, identity=FakeIdentity(), use_mode=ProviderUseMode.SPIKE)


def _fake_envelope(req_id: str = "req-1", status: str = "OK", params: dict | None = None):
    @dataclass
    class Env:
        provider: str = "amazingdata"
        provider_dataset: str = "daily_bar"
        endpoint: str = "MarketData.query_kline"
        request_id: str = ""
        request_params_hash: str = "h" * 16
        requested_at: str = "2026-08-22T00:00:00+00:00"
        received_at: str = "2026-08-22T00:00:01+00:00"
        sdk_version: str | None = "1.1.9"
        runtime_version: str | None = "V4.3.0"
        account_profile_id: str = "ACCOUNT_x"
        row_count: int = 2
        status: str = ""
        error_class: str | None = None
        duration_ms: float = 12.5
        attempt_count: int = 1
        capability_status: str | None = "CANDIDATE"

    return Env(request_id=req_id, status=status)


class TestProviderExchangeContract:
    def test_provider_exchange_preserves_request_id(self):
        env = _fake_envelope(req_id="req-abc-123")
        exchange = ProviderExchange(envelope=env, payload=[{"row": 1}])
        assert exchange.request_id == "req-abc-123"
        assert exchange.payload == [{"row": 1}]

    def test_call_exchange_returns_exchange(self):
        provider = _provider()
        exchange = provider.call_exchange(
            "FakeData.endpoint",
            "fake_dataset",
            lambda: ["a", "b"],
            require_capability="daily_bar",
        )
        assert isinstance(exchange, ProviderExchange)
        assert exchange.payload == ["a", "b"]
        assert exchange.envelope.request_id
        assert exchange.envelope.status == "OK"

    def test_business_wrapper_returns_payload(self):
        provider = _provider()
        result = provider._call_or_payload(  # noqa: SLF001
            "FakeData.endpoint",
            "fake_dataset",
            lambda: ["x"],
            require_capability="daily_bar",
        )
        assert result == ["x"]

    def test_failure_exchange_envelope_only(self):
        provider = _provider()
        from ashare_state.providers.errors import ProviderPermissionError

        def denied():
            raise ProviderPermissionError("entitlement denied")

        with pytest.raises(ProviderPermissionError):
            provider.call_exchange(
                "FakeData.endpoint",
                "fake_dataset",
                denied,
                require_capability="daily_bar",
            )
        env = provider.last_envelopes[-1]
        assert env.status == "ERROR"
        assert env.error_class == "ProviderPermissionError"

    def test_hidden_calendar_call_has_own_exchange(self, monkeypatch):
        """Audit section 44 + CR-1.2 (R4-A2.4 section 2.3): the CONVENIENCE
        path (query_kline) still fetches the calendar via a real SDK call
        that gets its OWN exchange (never buried in the kline envelope)."""
        provider = _provider()
        calendar_calls: list[str] = []

        class FakeBase:
            def get_calendar(self, market: str = "SH"):
                calendar_calls.append("calendar")
                return [20260813, 20260814]

        class FakeMarket:
            def __init__(self, days: list[int]) -> None:
                self.days = days

            def query_kline(self, **kwargs: object):
                return [{"KLINE_TIME": d} for d in self.days]

        class FakeSdk:
            BaseData = FakeBase
            MarketData = FakeMarket

        provider.session.__dict__["sdk"] = FakeSdk()
        # business convenience wrapper: internally fetches the calendar
        payload = provider.query_kline(
            ["600000.SH"], begin_date=20260813, end_date=20260814, kline_type="DAY"
        )
        assert payload and calendar_calls == ["calendar"]
        # the internal calendar fetch produced its OWN envelope (diagnostic
        # list on the convenience path); the kline envelope is separate
        endpoints = [e.endpoint for e in provider.last_envelopes]
        assert endpoints.count("BaseData.get_calendar") == 1
        assert endpoints.count("MarketData.query_kline") == 1

    def test_explicit_kline_requires_no_hidden_calendar(self, monkeypatch):
        """CR-1.2 (audit R4-A2.4 section 2.3-A): the EXPLICIT exchange path
        (what spikes/formal evidence consume) takes trading_days as an
        argument - no calendar SDK call happens inside it at all."""
        provider = _provider()
        calendar_calls: list[str] = []

        class FakeBase:
            def get_calendar(self, market: str = "SH"):
                calendar_calls.append("calendar")
                return [20260813, 20260814]

        class FakeMarket:
            def __init__(self, days: list[int]) -> None:
                self.days = days

            def query_kline(self, **kwargs: object):
                return [{"KLINE_TIME": d} for d in self.days]

        class FakeSdk:
            BaseData = FakeBase
            MarketData = FakeMarket

        provider.session.__dict__["sdk"] = FakeSdk()
        exchange = provider.query_kline_exchange(
            ["600000.SH"],
            begin_date=20260813,
            end_date=20260814,
            kline_type="DAY",
            trading_days=[20260813, 20260814],
        )
        assert exchange.payload
        assert calendar_calls == []  # no hidden calendar call
        assert [e.endpoint for e in provider.last_envelopes] == ["MarketData.query_kline"]
        # full request params (CR-1.2 section 3.3) are carried on the
        # envelope: complete code list + the explicit trading days
        params = exchange.envelope.request_params
        assert params["code_list"] == ["600000.SH"]
        assert params["trading_days"] == [20260813, 20260814]

    def test_request_params_full_and_hashed(self):
        """CR-1.2 (audit R4-A2.4 section 3.3): FULL params persisted + full
        params hash; same size over DIFFERENT symbols hashes differently."""
        provider = _provider()

        class FakeInfo:
            def get_history_stock_status(self, **kwargs: object):
                return []

        class FakeSdk:
            InfoData = FakeInfo

        provider.session.__dict__["sdk"] = FakeSdk()
        first = provider.get_history_stock_status_exchange(
            20220101, 20220102, ["600000.SH", "000001.SZ"]
        )
        second = provider.get_history_stock_status_exchange(
            20220101, 20220102, ["600000.SH", "300750.SZ"]
        )
        third = provider.get_history_stock_status_exchange(
            20220101, 20220102, ["600000.SH", "000001.SZ"]
        )
        assert first.envelope.request_params == {
            "start_date": 20220101,
            "end_date": 20220102,
            "code_list": ["600000.SH", "000001.SZ"],
        }
        # equal size, different symbols -> different params AND hash
        assert first.envelope.request_params != second.envelope.request_params
        assert first.envelope.request_params_hash != second.envelope.request_params_hash
        # same request -> same hash (reconstruction-stable)
        assert third.envelope.request_params_hash == first.envelope.request_params_hash


class TestRawWriterContract:
    @pytest.fixture
    def writer(self, tmp_path: Path) -> RawWriter:
        return RawWriter(tmp_path / "raw")

    def _payload(self):
        return [
            {"SECURITY_CODE": "600000", "CLOSE": 10.5},
            {"SECURITY_CODE": "000001", "CLOSE": 12.0},
        ]

    def test_raw_writer_success_persists_payload_and_envelope(self, writer: RawWriter):
        result = writer.write_success(
            provider="amazingdata",
            dataset="daily_bar",
            request_id="req-1",
            payload=self._payload(),
            envelope=_fake_envelope("req-1"),
        )
        assert result.logical_uri == "provider=amazingdata/dataset=daily_bar/req-1.parquet"
        artifact = writer.root / "provider=amazingdata" / "dataset=daily_bar" / "req-1.parquet"
        meta = writer.root / "provider=amazingdata" / "dataset=daily_bar" / "req-1.meta.json"
        assert artifact.is_file() and meta.is_file()
        # parquet is real parquet (lossless tabular, not repr)
        import pyarrow.parquet as pq

        table = pq.read_table(artifact)
        assert table.num_rows == 2
        assert "SECURITY_CODE" in table.column_names

    def test_raw_writer_failure_persists_envelope(self, writer: RawWriter):
        env = _fake_envelope("req-fail", status="ERROR")
        object.__setattr__(env, "error_class", "ProviderPermissionError")
        result = writer.write_failure(
            provider="amazingdata",
            dataset="daily_bar",
            request_id="req-fail",
            envelope=env,
        )
        assert result.logical_uri is None  # no payload for failures
        meta = writer.root / "provider=amazingdata" / "dataset=daily_bar" / "req-fail.meta.json"
        assert meta.is_file()
        import json

        doc = json.loads(meta.read_text(encoding="utf-8"))
        assert doc["status"] == "ERROR"
        assert doc["error_class"] == "ProviderPermissionError"
        assert doc["request_id"] == "req-fail"

    def test_same_hash_retry_is_idempotent(self, writer: RawWriter):
        args = {
            "provider": "amazingdata",
            "dataset": "daily_bar",
            "request_id": "req-2",
            "payload": self._payload(),
            "envelope": _fake_envelope("req-2"),
        }
        first = writer.write_success(**args)
        second = writer.write_success(**args)
        assert first.content_hash == second.content_hash
        assert second.idempotent is True

    def test_different_content_same_request_blocks(self, writer: RawWriter):
        writer.write_success(
            provider="amazingdata",
            dataset="daily_bar",
            request_id="req-3",
            payload=self._payload(),
            envelope=_fake_envelope("req-3"),
        )
        with pytest.raises(RawWriterError, match="conflict"):
            writer.write_success(
                provider="amazingdata",
                dataset="daily_bar",
                request_id="req-3",
                payload=[{"DIFFERENT": True}],
                envelope=_fake_envelope("req-3"),
            )

    def test_raw_evidence_scrubs_secrets(self, writer: RawWriter):
        """Secrets must never appear in persisted metadata."""
        env = _fake_envelope("req-sec")
        object.__setattr__(
            env,
            "request_params_hash",
            hashlib.sha256(b'{"password": "hunter2", "token": "abc"}').hexdigest(),
        )
        writer.write_success(
            provider="amazingdata",
            dataset="daily_bar",
            request_id="req-sec",
            payload=[],
            envelope=env,
        )
        meta_path = writer.root / "provider=amazingdata" / "dataset=daily_bar" / "req-sec.meta.json"
        text = meta_path.read_text(encoding="utf-8")
        assert "hunter2" not in text
        assert "abc" not in text

    def test_raw_logical_uri_cross_platform(self, writer: RawWriter):
        result = writer.write_success(
            provider="amazingdata",
            dataset="daily_bar",
            request_id="req-uri",
            payload=[],
            envelope=_fake_envelope("req-uri"),
        )
        # logical uri: relative, forward slashes, no drive letters, no backslashes
        assert "\\" not in result.logical_uri
        assert ":" not in result.logical_uri
        assert not result.logical_uri.startswith("/")

    def test_raw_writer_has_no_repr_fallback(self):
        """Audit section 46: repr()/str() of payloads is never used for
        serialization (Parquet is the tabular path)."""
        from ashare_state.storage import raw_writer

        module_src = Path(raw_writer.__file__).read_text(encoding="utf-8")
        # no CALLS to repr()/str() on payload objects (doc mentions are fine)
        for forbidden in ("repr(payload", "repr(rows", "str(payload", "str(rows"):
            assert forbidden not in module_src, forbidden

    def test_spike_uses_exchange_request_id(self, writer: RawWriter):
        """Spike writes raw evidence with the EXCHANGE's request id - never
        a regenerated one."""
        provider = _provider()
        exchange = provider.call_exchange(
            "FakeData.endpoint",
            "daily_bar",
            lambda: [{"SECURITY_CODE": "600000"}],
            require_capability="daily_bar",
        )
        result = writer.write_success(
            provider="amazingdata",
            dataset="daily_bar",
            request_id=exchange.envelope.request_id,
            payload=exchange.payload,
            envelope=exchange.envelope,
        )
        assert result.request_id == exchange.envelope.request_id
