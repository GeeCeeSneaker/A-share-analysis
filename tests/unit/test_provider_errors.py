"""Provider error layer tests (task book section 3.2: no raw SDK errors cross)."""

from __future__ import annotations

import pytest

from ashare_state.providers.amazingdata.errors import (
    ProviderAuthError,
    ProviderEmptyResultError,
    ProviderNetworkError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderSdkInternalError,
    ProviderTimeoutError,
    classify_sdk_error,
    wrap_sdk_call,
)


class TestClassify:
    def test_none_subscript_maps_to_permission(self):
        """Observed entitlement-denial shape (connectivity evidence)."""
        exc = TypeError("'NoneType' object is not subscriptable")
        out = classify_sdk_error(
            exc, endpoint="get_calendar", account_context={"permission_codes": "3|4|32|33"}
        )
        assert isinstance(out, ProviderPermissionError)
        assert "entitlement" in str(out).lower()

    def test_query_fail_with_permission_context(self):
        exc = Exception("查询失败")
        out = classify_sdk_error(
            exc, endpoint="query_snapshot", account_context={"permission_codes": "3|4"}
        )
        assert isinstance(out, ProviderPermissionError)

    def test_query_fail_without_context_is_timeout_class(self):
        exc = Exception("查询失败")
        out = classify_sdk_error(exc, endpoint="query_snapshot")
        assert isinstance(out, ProviderTimeoutError)

    def test_network_keywords(self):
        for msg in ("connection refused", "connect timeout", "reset by peer"):
            out = classify_sdk_error(Exception(msg), endpoint="login")
            assert isinstance(out, ProviderNetworkError), msg

    def test_rate_limit_keywords(self):
        out = classify_sdk_error(Exception("weekly flow exceeded"), endpoint="q")
        assert isinstance(out, ProviderRateLimitError)

    def test_unclassifiable_becomes_internal_with_cause(self):
        exc = ValueError("weird stuff")
        out = classify_sdk_error(exc, endpoint="anything")
        assert isinstance(out, ProviderSdkInternalError)
        assert out.__cause__ is exc

    def test_timeout_error_passthrough(self):
        out = classify_sdk_error(TimeoutError("10s"), endpoint="q")
        assert isinstance(out, ProviderTimeoutError)

    def test_auth_keywords(self):
        out = classify_sdk_error(Exception("login fail: user disabled"), endpoint="login")
        assert isinstance(out, ProviderAuthError)

    def test_empty_result_hint(self):
        out = classify_sdk_error(Exception("no data"), endpoint="q", response=None)
        assert isinstance(out, ProviderEmptyResultError)

    def test_context_carries_endpoint(self):
        out = classify_sdk_error(RuntimeError("x"), endpoint="ep_name")
        assert out.context["endpoint"] == "ep_name"


class TestWrapDecorator:
    def test_wrap_success(self):
        @wrap_sdk_call("ep")
        def fn():
            return 42

        assert fn() == 42

    def test_wrap_maps_and_preserves_cause(self):
        @wrap_sdk_call("ep")
        def fn():
            raise TypeError("'NoneType' object is not subscriptable")

        with pytest.raises(ProviderPermissionError) as excinfo:
            fn()
        assert isinstance(excinfo.value.__cause__, TypeError)

    def test_provider_errors_pass_through_unwrapped(self):
        @wrap_sdk_call("ep")
        def fn():
            raise ProviderTimeoutError("already typed")

        with pytest.raises(ProviderTimeoutError):
            fn()
