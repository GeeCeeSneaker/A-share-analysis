"""Focused positive-allowlist and production-identity configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ashare_state.providers.amazingdata import production_identity as pi
from ashare_state.providers.amazingdata.session import AccountProfile
from ashare_state.spike import RunKind
from ashare_state.spike.runner import ProductionAccountGateError, new_run


def _profile(*, host: str = "formal-host", username: str = "operator") -> AccountProfile:
    return AccountProfile.from_scrubbed(
        {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
        host=host,
        username=username,
    )


def _write_config(
    path: Path,
    profile_id: str,
    confirmed_at: str = "2026-09-05T10:00:00+08:00",
    confirmed_by: str = "Owner",
) -> None:
    path.write_text(
        "\n".join(
            [
                f'production_account_profile_id: "{profile_id}"',
                f'confirmed_at: "{confirmed_at}"',
                f'confirmed_by: "{confirmed_by}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _use_config(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(pi, "PRODUCTION_ACCOUNT_CONFIG", path)


@pytest.mark.integration
class TestProductionIdentityConfiguration:
    def test_exact_live_scrubbed_profile_maps_to_production(self, tmp_path, monkeypatch):
        profile = _profile()
        config = tmp_path / "production_account.yaml"
        _write_config(config, profile.account_profile_id)
        _use_config(monkeypatch, config)

        kind, reason = pi.production_account_status(profile)

        assert kind is pi.AccountKind.PRODUCTION
        assert "exact match" in reason

    def test_different_unknown_account_is_refused(self, tmp_path, monkeypatch):
        frozen = _profile(host="formal-host", username="operator")
        other = _profile(host="different-host", username="other-operator")
        config = tmp_path / "production_account.yaml"
        _write_config(config, frozen.account_profile_id)
        _use_config(monkeypatch, config)

        kind, reason = pi.production_account_status(other)

        assert kind is pi.AccountKind.UNKNOWN
        assert "not the frozen production identity" in reason

    def test_trial_profile_is_refused(self, tmp_path, monkeypatch):
        production = _profile()
        trial = AccountProfile.from_scrubbed(
            {"PermissionCode": "3|4|32|33", "SubscribeLimitNum": 100, "TotalWeekFlow": 10},
            host="formal-host",
            username="operator",
        )
        config = tmp_path / "production_account.yaml"
        _write_config(config, production.account_profile_id)
        _use_config(monkeypatch, config)

        kind, reason = pi.production_account_status(trial)

        assert kind is pi.AccountKind.UNKNOWN
        assert "trial profile" in reason

    def test_unparsed_profile_is_refused(self, tmp_path, monkeypatch):
        production = _profile()
        unparsed = AccountProfile(auth_ok=True, profile_parsed=False)
        config = tmp_path / "production_account.yaml"
        _write_config(config, production.account_profile_id)
        _use_config(monkeypatch, config)

        kind, reason = pi.production_account_status(unparsed)

        assert kind is pi.AccountKind.UNKNOWN
        assert "not parsed" in reason

    def test_missing_permission_code_is_refused(self, tmp_path, monkeypatch):
        production = _profile()
        missing_permission = AccountProfile.from_scrubbed(
            {"SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            host="formal-host",
            username="operator",
        )
        config = tmp_path / "production_account.yaml"
        _write_config(config, production.account_profile_id)
        _use_config(monkeypatch, config)

        kind, reason = pi.production_account_status(missing_permission)

        assert kind is pi.AccountKind.UNKNOWN
        assert "PermissionCode" in reason

    @pytest.mark.parametrize(
        "config_text",
        [
            'production_account_profile_id: ""\nconfirmed_at: ""\nconfirmed_by: ""\n',
            'production_account_profile_id: "UNKNOWN_abcdef123456"\n'
            'confirmed_at: ""\n'
            'confirmed_by: "Owner"\n',
            'production_account_profile_id: "UNKNOWN_abcdef123456"\n'
            'confirmed_at: "2026-09-05"\n'
            'confirmed_by: "Owner"\n',
            'production_account_profile_id: "TRIAL_SIMULATION_abcdef123456"\n'
            'confirmed_at: "2026-09-05T10:00:00+08:00"\n'
            'confirmed_by: "Owner"\n',
        ],
    )
    def test_empty_or_unconfirmed_config_has_no_identity(self, tmp_path, config_text):
        config = tmp_path / "production_account.yaml"
        config.write_text(config_text, encoding="utf-8")

        assert pi.load_frozen_production_identity(config) is None

    @pytest.mark.parametrize(
        "config_text",
        [
            "production_account_profile_id: [unterminated",
            "- not a mapping\n",
            "production_account_profile_id: raw-username\n"
            'confirmed_at: "2026-09-05T10:00:00+08:00"\n'
            'confirmed_by: "Owner"\n',
            'production_account_profile_id: "UNKNOWN_abcdef123456"\n'
            'confirmed_at: "2026-09-05T10:00:00+08:00"\n'
            "confirmed_by: 123\n",
            'production_account_profile_id: "UNKNOWN_abcdef123456"\n'
            'confirmed_at: "2026-09-05T10:00:00+08:00"\n'
            'confirmed_by: "password"\n',
            'production_account_profile_id: "UNKNOWN_abcdef123456"\n'
            'confirmed_at: "2026-09-05T10:00:00+08:00"\n'
            'confirmed_by: "Owner"\n'
            'extra_field: "sentinel"\n',
        ],
    )
    def test_malformed_or_secret_bearing_config_fails_closed(self, tmp_path, config_text):
        config = tmp_path / "production_account.yaml"
        config.write_text(config_text, encoding="utf-8")

        assert pi.load_frozen_production_identity(config) is None

    def test_run_kind_production_alone_never_upgrades_identity(self, tmp_path, monkeypatch):
        config = tmp_path / "production_account.yaml"
        config.write_text(
            'production_account_profile_id: ""\nconfirmed_at: ""\nconfirmed_by: ""\n',
            encoding="utf-8",
        )
        _use_config(monkeypatch, config)

        with pytest.raises(ProductionAccountGateError, match="positive production identity"):
            new_run(
                run_kind=RunKind.PRODUCTION,
                spike_root=tmp_path / "spike",
                account_profile=_profile(),
            )
        assert not (tmp_path / "spike").exists()

    @pytest.mark.parametrize(
        ("profile_id", "expected"),
        [
            ("UNKNOWN_abcdef123456", True),
            ("TRIAL_SIMULATION_abcdef123456", True),
            ("ACCOUNT_abcdef123456", False),
            ("PRODUCTION_abcdef123456", False),
            ("OTHER_abcdef123456", False),
            ("FAKE_abcdef123456", False),
            ("UNKNOWN", False),
            ("UNKNOWN_abcdef", False),
            ("UNKNOWN_abcdef12345", False),
            ("UNKNOWN_abcdef1234567", False),
            ("UNKNOWN_" + "a" * 64, False),
            ("UNKNOWN_ABCDEF123456", False),
            (" UNKNOWN_abcdef123456", False),
            ("UNKNOWN_abcdef123456 ", False),
            ("UNKNOWN_has-space", False),
            ("raw-user", False),
        ],
    )
    def test_profile_id_shape_matches_current_generator_contract(self, profile_id, expected):
        assert pi.is_generated_scrubbed_profile_id(profile_id) is expected
        assert pi.is_scrubbed_profile_id(profile_id) is expected

    @pytest.mark.parametrize(
        ("profile_id", "expected"),
        [
            ("UNKNOWN_abcdef123456", True),
            ("TRIAL_SIMULATION_abcdef123456", False),
        ],
    )
    def test_only_non_trial_generated_id_is_freezable(self, profile_id, expected):
        assert pi.is_freezable_production_candidate_id(profile_id) is expected

    @pytest.mark.parametrize(
        "profile_id",
        [
            "ACCOUNT_abcdef123456",
            "PRODUCTION_abcdef123456",
            "OTHER_abcdef123456",
            "FAKE_abcdef123456",
            "TRIAL_SIMULATION_abcdef123456",
            "UNKNOWN_abcdef",
            "UNKNOWN_abcdef12345",
            "UNKNOWN_abcdef1234567",
            "UNKNOWN_" + "a" * 64,
            "UNKNOWN_ABCDEF123456",
            " UNKNOWN_abcdef123456",
            "UNKNOWN_abcdef123456 ",
        ],
    )
    def test_config_rejects_non_freezable_or_wrong_profile_ids(self, tmp_path, profile_id):
        config = tmp_path / "production_account.yaml"
        _write_config(config, profile_id)

        assert pi.load_frozen_production_identity(config) is None

    def test_missing_config_is_fail_closed(self, tmp_path):
        assert pi.load_frozen_production_identity(tmp_path / "does-not-exist.yaml") is None
