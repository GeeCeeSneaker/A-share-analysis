"""AmazingData provider component tests (offline; no SDK required for most).

The mapper/dto/capability/session-profile layers are testable without the
broker SDK; only sdk_loader import paths need the real wheel (skipped when
absent - CI discipline).
"""

from __future__ import annotations

from datetime import date

import pytest

from ashare_state.providers.amazingdata.capability import (
    CAPABILITY_REGISTRY,
    CapabilityStatus,
    capability_status,
)
from ashare_state.providers.amazingdata.errors import ProviderUnavailableError
from ashare_state.providers.amazingdata.mapper import (
    corporate_action_flags,
    map_security_status_row,
    project_limit_price,
)
from ashare_state.providers.amazingdata.session import AccountProfile
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget, run_with_budget

pytestmark = pytest.mark.unit


class TestCapabilityRegistry:
    def test_all_capabilities_start_candidate(self):
        """Task book 21.1: nothing APPROVED before real-account Spike.

        Value equality (not `is`): the capability module may be reloaded by
        the governance tests, rebuilding the StrEnum class - values compare
        equal across reloads.
        """
        for name, cap in CAPABILITY_REGISTRY.items():
            assert cap.status == CapabilityStatus.CANDIDATE, name

    def test_status_query(self):
        assert capability_status("daily_bar") == CapabilityStatus.CANDIDATE

    def test_unknown_capability_raises(self):
        with pytest.raises(KeyError):
            capability_status("nonexistent")

    def test_status_endpoint_feeds_three_domains(self):
        """Task book 1.3: never merged into one fact owner."""
        domains = CAPABILITY_REGISTRY["security_status_history"].canonical_domains
        assert set(domains) == {
            "fact_security_status_daily",
            "fact_limit_price",
            "fact_corporate_action",
        }


class TestStatusRouting:
    """One provider row -> three domain projections (task book 1.3)."""

    ROW = {
        "MARKET_CODE": "2",
        "SECURITY_CODE": "000001",
        "TRADE_DATE": "20260814",
        "PRECLOSE": 10.0,
        "HIGH_LIMITED": 11.0,
        "LOW_LIMITED": 9.0,
        "PRICE_HIGH_LMT_RATE": 0.1,
        "PRICE_LOW_LMT_RATE": 0.1,
        "IS_ST_SEC": 0,
        "IS_SUSP_SEC": 0,
        "IS_WD_SEC": 1,
        "IS_XR_SEC": 0,
    }

    def test_status_domain_fields(self):
        dto = map_security_status_row(self.ROW)
        assert dto.security_code == "000001"
        assert dto.trade_date == date(2026, 8, 14)
        assert dto.is_st_sec == 0
        assert dto.is_susp_sec == 0

    def test_limit_price_projection(self):
        status = map_security_status_row(self.ROW)
        limit = project_limit_price(status)
        assert limit.provider_symbol == "000001.SZ"
        assert limit.up_limit == 11.0
        assert limit.down_limit == 9.0
        assert limit.up_limit_rate == 0.1

    def test_corporate_action_projection(self):
        status = map_security_status_row(self.ROW)
        symbol, ex_date, ex_div, ex_rights = corporate_action_flags(status)
        assert symbol == "000001.SZ"
        assert ex_date == date(2026, 8, 14)
        assert ex_div is True  # IS_WD_SEC = 1
        assert ex_rights is False  # IS_XR_SEC = 0

    def test_missing_columns_tolerated(self):
        """Audit P0-04: OPTIONAL fields stay None (no 1970/0.0 sentinels);
        REQUIRED fields raise MappingValidationError."""
        from ashare_state.providers.errors import MappingValidationError

        # optional-only absence: limit prices may legitimately be absent
        dto = map_security_status_row({"SECURITY_CODE": "000001", "TRADE_DATE": "20260814"})
        assert dto.security_code == "000001"
        assert dto.high_limited is None
        assert dto.trade_date == date(2026, 8, 14)

        # required security_code missing -> quarantine, not sentinel
        with pytest.raises(MappingValidationError, match="SECURITY_CODE"):
            map_security_status_row({"TRADE_DATE": "20260814"})

        # required trade_date missing -> quarantine (audit: never 1970-01-01)
        with pytest.raises(MappingValidationError, match="TRADE_DATE"):
            map_security_status_row({"SECURITY_CODE": "000001"})

        # unparsable date -> quarantine, not 1970-01-01
        with pytest.raises(MappingValidationError, match="unparsable"):
            map_security_status_row({"SECURITY_CODE": "000001", "TRADE_DATE": "garbage"})

    def test_zero_is_not_missing(self):
        """Audit P0-04: legal zero must not trigger field fallback."""
        from ashare_state.providers.amazingdata.mapper import first_present

        row = {"OPEN_PRICE": 0, "open": 99.5}
        assert first_present(row, "OPEN_PRICE", "open") == 0
        # and a zero OHLC maps to 0.0, not to the fallback column
        from ashare_state.providers.amazingdata.mapper import map_daily_bar_row

        full = dict.fromkeys(
            ("SECURITY_CODE", "KLINE_TIME", "VOLUME", "AMOUNT"),
            None,
        )
        full.update(
            {
                "SECURITY_CODE": "600000",
                "KLINE_TIME": 20260814,
                "OPEN_PRICE": 0,
                "HIGH_PRICE": 10.5,
                "LOW_PRICE": 0,
                "CLOSE_PRICE": 9.9,
                "VOLUME": 0,
                "AMOUNT": 0,
            }
        )
        bar = map_daily_bar_row(full)
        assert bar.open == 0.0
        assert bar.volume == 0.0
        assert bar.amount == 0.0

    def test_missing_ohlc_quarantines_not_zero(self):
        """Audit P0-04: absent OHLC must NOT silently become 0.0."""
        from ashare_state.providers.amazingdata.mapper import map_daily_bar_row
        from ashare_state.providers.errors import MappingValidationError

        row = {"SECURITY_CODE": "600000", "KLINE_TIME": 20260814, "VOLUME": 100, "AMOUNT": 1000}
        with pytest.raises(MappingValidationError, match="OPEN_PRICE"):
            map_daily_bar_row(row)

    def test_missing_adj_factor_quarantines_not_zero(self):
        """Audit P0-04: absent adj factor must NOT silently become 0.0."""
        from ashare_state.providers.amazingdata.mapper import map_adj_factor_row
        from ashare_state.providers.errors import MappingValidationError

        with pytest.raises(MappingValidationError, match="EX_FACTOR"):
            map_adj_factor_row(
                {"SECURITY_CODE": "600000", "EX_DATE": "20260101"}, factor_type="SINGLE"
            )


class TestAccountProfile:
    def test_trial_profile_shape(self):
        profile = AccountProfile.from_scrubbed(
            {
                "PermissionCode": "3|4|32|33",
                "SubscribeLimitNum": 100,
                "TotalWeekFlow": 10,
                "UsedWeekFlow": 0.16,
            }
        )
        assert profile.login_ok
        assert profile.profile_parsed
        assert profile.entitlement_verified
        assert profile.account_profile_id.startswith("TRIAL_SIMULATION_")
        assert profile.permission_codes == "3|4|32|33"
        assert profile.subscribe_limit == 100
        assert profile.weekly_flow_limit == 10

    def test_production_like_profile_kind(self):
        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2|3|4|32|33", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500}
        )
        assert profile.account_profile_id.startswith("ACCOUNT_")

    def test_account_profile_id_distinct_for_same_entitlements(self):
        """Audit P1-07: same entitlements, different accounts -> distinct ids."""
        entitlements = {"PermissionCode": "3|4", "SubscribeLimitNum": 100, "TotalWeekFlow": 10}
        a = AccountProfile.from_scrubbed(entitlements, host="10.0.0.1", username="userA")
        b = AccountProfile.from_scrubbed(entitlements, host="10.0.0.1", username="userB")
        assert a.account_profile_id != b.account_profile_id

    def test_unparsed_profile_keeps_auth_ok(self):
        """Audit P1-08: auth succeeded but logon json unparseable."""
        profile = AccountProfile(auth_ok=True, profile_parsed=False)
        assert profile.auth_ok
        assert not profile.profile_parsed
        assert not profile.entitlement_verified
        assert profile.account_profile_id == "UNKNOWN"

    def test_empty_profile(self):
        profile = AccountProfile.from_scrubbed(None)
        assert profile.auth_ok  # from_scrubbed(None) models "login returned, no json"
        assert not profile.profile_parsed
        assert profile.account_profile_id == "UNKNOWN"


class TestTimeBudget:
    def test_budget_exhaustion_raises_typed(self):
        """Only RETRYABLE classes exhaust into a timeout (audit P0-03)."""
        from ashare_state.providers.errors import ProviderNetworkError

        calls = []

        def always_fail():
            calls.append(1)
            raise ProviderNetworkError("sdk grinding")

        with pytest.raises(Exception, match="budget exhausted") as excinfo:
            run_with_budget(
                always_fail,
                budget=TimeBudget(query_timeout_seconds=0.0),
                retry=RetryPolicy(max_retries=2, backoff_base_seconds=0.001),
                endpoint="ep",
            )
        assert "budget exhausted" in str(excinfo.value)
        # zero budget: first failure already exceeds the deadline -> 1 call
        assert len(calls) == 1

    def test_budget_exhaustion_after_full_retries(self):
        from ashare_state.providers.errors import ProviderNetworkError

        calls = []

        def always_fail():
            calls.append(1)
            raise ProviderNetworkError("still down")

        with pytest.raises(Exception, match="budget exhausted"):
            run_with_budget(
                always_fail,
                budget=TimeBudget(query_timeout_seconds=30.0),
                retry=RetryPolicy(max_retries=2, backoff_base_seconds=0.001),
                endpoint="ep",
            )
        assert len(calls) == 3  # 1 + 2 retries, then max_retries reached

    def test_raw_exception_never_retries(self):
        """Audit P0-03: an unclassified SDK error must surface immediately
        with its true class - never masked by budget-exhaustion timeout."""
        calls = []

        def boom():
            calls.append(1)
            raise TypeError("'NoneType' object is not subscriptable")

        with pytest.raises(TypeError):
            run_with_budget(
                boom,
                budget=TimeBudget(),
                retry=RetryPolicy(max_retries=5, backoff_base_seconds=0.001),
                endpoint="ep",
            )
        assert len(calls) == 1

    def test_permission_error_not_retried(self):
        """Audit P0-03: permission denial - 1 call, no retry, not a timeout."""
        from ashare_state.providers.errors import ProviderPermissionError

        calls = []

        def denied():
            calls.append(1)
            raise ProviderPermissionError("entitlement missing")

        with pytest.raises(ProviderPermissionError):
            run_with_budget(
                denied,
                budget=TimeBudget(),
                retry=RetryPolicy(max_retries=5, backoff_base_seconds=0.001),
                endpoint="ep",
            )
        assert len(calls) == 1

    def test_auth_error_not_retried(self):
        from ashare_state.providers.errors import ProviderAuthError

        calls = []

        def denied():
            calls.append(1)
            raise ProviderAuthError("bad credentials")

        with pytest.raises(ProviderAuthError):
            run_with_budget(
                denied,
                budget=TimeBudget(),
                retry=RetryPolicy(max_retries=5, backoff_base_seconds=0.001),
                endpoint="ep",
            )
        assert len(calls) == 1

    def test_network_error_retries_per_policy(self):
        from ashare_state.providers.errors import ProviderNetworkError

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise ProviderNetworkError("connection reset")
            return "ok"

        assert (
            run_with_budget(
                flaky,
                budget=TimeBudget(),
                retry=RetryPolicy(max_retries=3, backoff_base_seconds=0.001),
                endpoint="ep",
            )
            == "ok"
        )
        assert len(calls) == 3

    def test_blocking_callable_exceeding_budget_is_recorded_not_cancelled(self):
        """Audit P0-03: honest semantics - budget does NOT cancel a blocking
        native call; the fn runs to completion and the elapsed time is
        simply beyond the budget (documented, tested as-is)."""
        result = run_with_budget(
            lambda: "late-but-done",
            budget=TimeBudget(query_timeout_seconds=0.0),
            retry=RetryPolicy(),
            endpoint="ep",
        )
        assert result == "late-but-done"

    def test_success_passthrough(self):
        assert (
            run_with_budget(
                lambda: "ok",
                budget=TimeBudget(),
                retry=RetryPolicy(),
                endpoint="ep",
            )
            == "ok"
        )

    def test_non_retryable_raises_immediately(self):
        calls = []

        def boom():
            calls.append(1)
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            run_with_budget(
                boom,
                budget=TimeBudget(),
                retry=RetryPolicy(max_retries=5, backoff_base_seconds=0.001),
                endpoint="ep",
            )
        assert len(calls) == 1


class TestSdkLoaderAbsent:
    def test_load_sdk_absent_raises_typed(self, monkeypatch):
        import ashare_state.providers.amazingdata.sdk_loader as loader

        monkeypatch.setattr(loader, "SDK_MODULE", "definitely_not_installed_xyz")
        with pytest.raises(ProviderUnavailableError):
            loader.load_sdk()

    def test_probe_identity_offline_tolerates_absence(self, monkeypatch):
        import ashare_state.providers.amazingdata.sdk_loader as loader

        monkeypatch.setattr(loader, "SDK_MODULE", "definitely_not_installed_xyz")
        assert loader.probe_identity(require_sdk=False) is None
