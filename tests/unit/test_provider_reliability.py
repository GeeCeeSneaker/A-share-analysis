"""Provider reliability tests (audit P0-03 / P1-02 / P1-04 / P1-09 / P1-13 / P1-14)."""

from __future__ import annotations

import logging

import pytest

from ashare_state.providers.amazingdata.capability import CAPABILITY_REGISTRY
from ashare_state.providers.amazingdata.errors import (
    ProviderPermissionError,
    ProviderSdkInternalError,
    classify_sdk_error,
)
from ashare_state.providers.amazingdata.provider import (
    AmazingDataProvider,
    ProviderUseMode,
)
from ashare_state.providers.errors import (
    ProviderNetworkError,
    is_retryable,
)


class TestClassificationConservative:
    """Audit P1-09: unknown shapes default to SdkInternal, not Permission."""

    def test_unhashable_list_is_internal_not_permission(self):
        exc = TypeError("unhashable type: 'list'")
        out = classify_sdk_error(exc, endpoint="get_code_info")
        assert isinstance(out, ProviderSdkInternalError)

    def test_none_subscript_still_permission(self):
        """The VERIFIED denial shape keeps its mapping."""
        exc = TypeError("'NoneType' object is not subscriptable")
        out = classify_sdk_error(exc, endpoint="get_calendar")
        assert isinstance(out, ProviderPermissionError)

    def test_unknown_valueerror_is_internal(self):
        out = classify_sdk_error(ValueError("weird"), endpoint="ep")
        assert isinstance(out, ProviderSdkInternalError)
        assert out.__cause__ is not None


class TestRetryPolicy:
    def test_network_is_retryable(self):
        assert is_retryable(ProviderNetworkError("x"))

    def test_permission_not_retryable(self):
        assert not is_retryable(ProviderPermissionError("x"))


class TestCapabilityUseMode:
    def test_production_mode_refuses_candidate(self):
        """Audit P1-02 / R2-P1-02: PRODUCTION + CANDIDATE -> GOVERNANCE
        error (never ProviderPermissionError - that is broker-side only)."""
        from ashare_state.providers.amazingdata.session import AccountProfile
        from ashare_state.providers.errors import ProviderCapabilityNotApprovedError

        session = _FakeSession(AccountProfile())
        provider = AmazingDataProvider(session, use_mode=ProviderUseMode.PRODUCTION)
        with pytest.raises(ProviderCapabilityNotApprovedError, match="not APPROVED"):
            provider._gate_capability("daily_bar")  # noqa: SLF001

    def test_spike_mode_allows_candidate(self):
        from ashare_state.providers.amazingdata.session import AccountProfile

        session = _FakeSession(AccountProfile())
        provider = AmazingDataProvider(session, use_mode=ProviderUseMode.SPIKE)
        status = provider._gate_capability("daily_bar")  # noqa: SLF001
        assert status is not None
        assert "daily_bar" in CAPABILITY_REGISTRY

    def test_default_mode_is_production(self):
        from ashare_state.providers.amazingdata.session import AccountProfile

        session = _FakeSession(AccountProfile())
        provider = AmazingDataProvider.__new__(AmazingDataProvider)
        assert provider  # placeholder - default tested via constructor below
        provider2 = AmazingDataProvider(session, identity=_FakeIdentity())
        assert provider2.use_mode is ProviderUseMode.PRODUCTION


class TestFailedCallEnvelope:
    def test_failed_call_records_error_envelope(self):
        """Audit P1-04: envelope exists for FAILED calls with error class."""
        from ashare_state.providers.amazingdata.session import AccountProfile

        session = _FakeSession(AccountProfile())
        provider = AmazingDataProvider(
            session,
            identity=_FakeIdentity(),
            use_mode=ProviderUseMode.SPIKE,
        )

        def denied():
            raise TypeError("'NoneType' object is not subscriptable")

        with pytest.raises(ProviderPermissionError):
            provider._call(  # noqa: SLF001
                "FakeData.endpoint",
                "fake_dataset",
                denied,
                params={"x": 1},
                require_capability="daily_bar",
            )
        assert len(provider.last_envelopes) == 1
        env = provider.last_envelopes[0]
        assert env.status == "ERROR"
        assert env.error_class == "ProviderPermissionError"
        assert env.duration_ms >= 0.0
        assert env.capability_status == "CANDIDATE"
        assert env.request_params_hash  # full sha-256 now

    def test_successful_call_envelope_ok(self):
        from ashare_state.providers.amazingdata.session import AccountProfile

        session = _FakeSession(AccountProfile())
        provider = AmazingDataProvider(
            session,
            identity=_FakeIdentity(),
            use_mode=ProviderUseMode.SPIKE,
        )
        result = provider._call(  # noqa: SLF001
            "FakeData.endpoint",
            "fake_dataset",
            lambda: ["a", "b"],
            require_capability="daily_bar",
        )
        assert result == ["a", "b"]
        env = provider.last_envelopes[-1]
        assert env.status == "OK"
        assert env.error_class is None
        assert env.row_count == 2
        assert len(env.request_params_hash) == 64  # full sha-256


class TestPrintfStyleSecretLogging:
    def test_printf_style_secret_is_masked_without_format_error(self):
        """Audit P1-13: masking must not break %-formatting."""
        from ashare_state.logging_setup import SecretMaskingFilter

        logger = logging.getLogger("test.printf")
        logger.setLevel(logging.INFO)
        filter_ = SecretMaskingFilter()

        class _Rec:
            pass

        record = logging.LogRecord(
            "test.printf", logging.INFO, __file__, 1, "password=%s", ("hunter2",), None
        )
        assert filter_.filter(record)
        output = record.getMessage()
        assert "hunter2" not in output
        assert "***MASKED***" in output
        # and formatting itself never raises
        _ = record.getMessage()

    def test_printf_style_without_secret_untouched(self):
        from ashare_state.logging_setup import SecretMaskingFilter

        record = logging.LogRecord("t", logging.INFO, __file__, 1, "rows=%d", (42,), None)
        assert SecretMaskingFilter().filter(record)
        assert record.getMessage() == "rows=42"


class TestSecretStrConfig:
    def test_settings_repr_does_not_expose_password(self, monkeypatch):
        """Audit P1-14."""
        monkeypatch.setenv("TGW_PASSWORD", "super-secret-123")
        monkeypatch.setenv("TGW_USERNAME", "acct")
        from ashare_state.config import Settings

        settings = Settings(_env_file=None)
        assert "super-secret-123" not in repr(settings)
        assert "super-secret-123" not in str(settings.model_dump())
        assert settings.tgw_password.get_secret_value() == "super-secret-123"


# ------------------------------------------------------------------ fakes


class _FakeSession:
    def __init__(self, profile) -> None:
        self.profile = profile


class _FakeIdentity:
    sdk_version = "fake-1.0"
    tgw_runtime_version = "fake-rt"
