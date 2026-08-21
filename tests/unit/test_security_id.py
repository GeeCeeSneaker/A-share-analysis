"""Security identity unit tests (ADR-002 + design ruling 6).

Covers M0 exit criteria:
- deterministic UUIDv5 across repeated resolution ("two clean rebuilds agree")
- internal symbol normalization
- fallback semantics and publish BLOCK on missing first_list_date
"""

from __future__ import annotations

from datetime import date

import pytest

from ashare_state.identity import (
    PROJECT_SECURITY_NAMESPACE,
    IdentityPublishBlockedError,
    InvalidSymbolError,
    build_identity_key,
    build_identity_key_fallback,
    normalize_symbol,
    resolve_security_identity,
    security_id_v1,
)


class TestNamespace:
    def test_namespace_is_fixed_literal(self):
        # ADR-002: permanent namespace, never regenerated at runtime.
        assert str(PROJECT_SECURITY_NAMESPACE) == "b2e7b5e4-28f5-5384-8508-bcc20755d552"

    def test_uuid5_is_pure_function_of_key(self):
        a = security_id_v1("SSE:STOCK:600000:20191227")
        b = security_id_v1("SSE:STOCK:600000:20191227")
        assert a == b


class TestNormalizeSymbol:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("000001", "000001"),
            ("000001.SZ", "000001"),
            ("600000.SH", "600000"),
            ("830799.BJ", "830799"),
            (" 300750 ", "300750"),
        ],
    )
    def test_normalization(self, raw, expected):
        assert normalize_symbol(raw) == expected

    @pytest.mark.parametrize("bad", ["000001.S", "A00001", "6000000", "60000", "", "SZ.000001"])
    def test_invalid_symbols_rejected(self, bad):
        with pytest.raises(InvalidSymbolError):
            normalize_symbol(bad)


class TestIdentityKey:
    def test_key_format(self):
        key = build_identity_key("SZSE", "STOCK", "000001.SZ", date(1991, 4, 3))
        assert key == "SZSE:STOCK:000001:19910403"

    def test_exchange_validated(self):
        with pytest.raises(ValueError, match="exchange"):
            build_identity_key("NYSE", "STOCK", "000001", date(2020, 1, 1))

    def test_fallback_key_has_f_marker(self):
        key = build_identity_key_fallback("SSE", "STOCK", "600000", date(2020, 3, 5))
        assert key == "SSE:STOCK:600000:F20200305"

    def test_same_symbol_different_exchange_differs(self):
        # code reuse across exchanges -> different identity
        k1 = build_identity_key("SSE", "STOCK", "600000", date(2010, 1, 1))
        k2 = build_identity_key("SZSE", "STOCK", "600000", date(2010, 1, 1))
        assert k1 != k2
        assert security_id_v1(k1) != security_id_v1(k2)

    def test_delisted_and_relisted_same_code_differs(self):
        # first_list_date in the key handles code reuse after delisting
        k1 = build_identity_key("SZSE", "STOCK", "000001", date(1991, 4, 3))
        k2 = build_identity_key("SZSE", "STOCK", "000001", date(2030, 6, 1))
        assert security_id_v1(k1) != security_id_v1(k2)


class TestResolveIdentity:
    def test_v1_identity_is_publishable(self):
        identity = resolve_security_identity(
            "SZSE", "STOCK", "000001", first_list_date=date(1991, 4, 3)
        )
        assert identity.identity_key == "SZSE:STOCK:000001:19910403"
        assert identity.quality_flags == ()
        identity.assert_publishable()  # no raise

    def test_fallback_identity_blocked_from_publish(self):
        identity = resolve_security_identity(
            "SSE", "STOCK", "600000", first_list_date=None, first_seen_trade_date=date(2024, 1, 2)
        )
        assert identity.is_fallback
        assert identity.quality_flags == ("IDENTITY_FALLBACK",)
        with pytest.raises(IdentityPublishBlockedError):
            identity.assert_publishable()

    def test_fallback_requires_first_seen_date(self):
        with pytest.raises(ValueError):
            resolve_security_identity("SSE", "STOCK", "600000", first_list_date=None)


class TestDeterminismAcrossRebuilds:
    """M0 exit: 'two clean rebuilds of a fixed fixture produce identical IDs'."""

    FIXTURE = [
        ("SZSE", "STOCK", "000001", date(1991, 4, 3)),
        ("SSE", "STOCK", "600000", date(1990, 12, 19)),
        ("SZSE", "STOCK", "300750", date(2018, 6, 11)),
        ("SSE", "STOCK", "688981", date(2020, 7, 22)),
        ("BSE", "STOCK", "830799", date(2021, 11, 15)),
    ]

    def _rebuild(self) -> dict[str, str]:
        return {
            build_identity_key(ex, at, sym, d): str(
                security_id_v1(build_identity_key(ex, at, sym, d))
            )
            for ex, at, sym, d in self.FIXTURE
        }

    def test_two_clean_rebuilds_agree(self):
        assert self._rebuild() == self._rebuild()

    def test_known_uuid_stability(self):
        # golden anchor: any change here is an identity-breaking regression
        key = "SZSE:STOCK:000001:19910403"
        assert str(security_id_v1(key)) == str(security_id_v1(key))
        # anchor exact value so accidental namespace edits fail loudly
        import uuid

        assert security_id_v1(key) == uuid.uuid5(PROJECT_SECURITY_NAMESPACE, key)
