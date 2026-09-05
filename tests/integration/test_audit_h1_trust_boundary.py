"""AUDIT-H1 adversarial trust-boundary tests; synthetic data, no live SDK."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from ashare_state.cli import app
from ashare_state.providers.amazingdata import doctor, sdk_loader
from ashare_state.providers.amazingdata.production_identity import FrozenProductionIdentity
from ashare_state.providers.amazingdata.safe_diagnostics import (
    parse_permission_codes,
    safe_diagnostic_projection,
)
from ashare_state.providers.amazingdata.session import AccountProfile, AmazingDataSession
from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStdout,
    scrub_dict,
    sdk_stdout_into,
)
from ashare_state.providers.errors import ProviderAuthError, ProviderError, ProviderUnavailableError

ROOT = Path(__file__).resolve().parents[2]
SECRET = "SYNTHETIC_H1_PRIVATE_SENTINEL"


def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "audit_h1_bootstrap", ROOT / "scripts/spike/production_account_bootstrap.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_report():
    return {
        "sdk_state": "SDK_INSTALLED",
        "verdict": "RUNTIME_ACTUAL_LOAD_VERIFIED",
        "AUTHENTICATED": "YES",
        "QUERY_READY": "YES",
        "ACCOUNT_PROFILE": {
            "account_profile_id": "UNKNOWN_abc123def456",
            "permission_codes": "1|2",
        },
    }


@pytest.mark.parametrize(
    "value",
    ["", " ", "\t\n", "||", ",; |\t", "1|x", "1.5", "-1", "1|²", "１", None, 12, True, []],
)
def test_permission_parser_and_session_reject_invalid(value):
    assert parse_permission_codes(value) == ()
    profile = AccountProfile.from_scrubbed({"PermissionCode": value})
    assert profile.entitlement_verified is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", ("0",)),
        ("01|2", ("01", "2")),
        (" 1,2;3\t4\n5 ", ("1", "2", "3", "4", "5")),
        ("1||2", ("1", "2")),
    ],
)
def test_permission_parser_accepts_numeric_tokens(value, expected):
    assert parse_permission_codes(value) == expected
    assert AccountProfile.from_scrubbed({"PermissionCode": value}).entitlement_verified


@pytest.mark.parametrize(
    "verdict",
    [
        "RUNTIME_PACKAGE_VERIFIED",
        "RUNTIME_PATH_AMBIGUOUS",
        "NOT_VERIFIED",
        "RUNTIME_VERSION_MISMATCH",
        None,
        SECRET,
    ],
)
def test_online_runtime_fail_closed(monkeypatch, verdict):
    module = bootstrap()
    monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
    raw = valid_report()
    raw["verdict"] = verdict
    result = module._safe_report(raw, offline=False)
    assert result["bootstrap_status"] == "NOT_TESTABLE_RUNTIME"
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    ("verdict", "status", "exit_code"),
    [
        ("RUNTIME_ACTUAL_LOAD_VERIFIED", "OFFLINE_RUNTIME_VERIFIED", 0),
        ("RUNTIME_PACKAGE_VERIFIED", "OFFLINE_PACKAGE_VERIFIED", 0),
        ("RUNTIME_PATH_AMBIGUOUS", "NOT_TESTABLE_RUNTIME", 2),
        ("NOT_VERIFIED", "NOT_TESTABLE_RUNTIME", 2),
    ],
)
def test_offline_strength_and_exit_code(monkeypatch, capsys, verdict, status, exit_code):
    module = bootstrap()
    raw = valid_report()
    raw["verdict"] = verdict
    monkeypatch.setattr(module, "run_doctor", lambda **kwargs: raw)
    monkeypatch.setattr(module, "load_env", lambda *args: pytest.fail("offline read credentials"))
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--offline"])
    assert module.main() == exit_code
    result = json.loads(capsys.readouterr().out)
    assert result["bootstrap_status"] == status
    assert "ACCOUNT_PROFILE" not in result


@pytest.mark.parametrize("codes", ["", " \t", "|||", ", ;", "1|invalid"])
def test_online_entitlement_fail_closed(monkeypatch, codes):
    module = bootstrap()
    monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
    raw = valid_report()
    raw["ACCOUNT_PROFILE"]["permission_codes"] = codes
    result = module._safe_report(raw, offline=False)
    assert result["bootstrap_status"] == "NOT_TESTABLE_ENTITLEMENT"
    assert not result["ACCOUNT_PROFILE"]["entitlement_verified"]


def test_existing_different_frozen_identity_is_not_a_new_candidate(monkeypatch):
    module = bootstrap()
    monkeypatch.setattr(
        module,
        "load_frozen_production_identity",
        lambda: FrozenProductionIdentity(
            account_profile_id="UNKNOWN_000000000001",
            confirmed_at="2026-09-05T00:00:00+00:00",
            confirmed_by="TEST",
        ),
    )
    assert module._safe_report(valid_report(), offline=False)["bootstrap_status"] == (
        "FROZEN_IDENTITY_MISMATCH"
    )


def test_nested_scrubber_preserves_structure_without_mutating_input():
    payload = {"items": [{"Token": SECRET}, ({"password": SECRET}, {"ok": 1})]}
    result = scrub_dict(payload)
    assert SECRET not in repr(result)
    assert isinstance(result["items"][1], tuple)
    assert result["items"][1][1]["ok"] == 1
    assert payload["items"][0]["Token"] == SECRET


def emit_private_output():
    os.write(1, (SECRET + "\n").encode())
    os.write(2, (SECRET + "\n").encode())
    print(SECRET)
    print(SECRET, file=sys.stderr)


@pytest.mark.parametrize("entry", ["bootstrap", "cli", "doctor"])
@pytest.mark.parametrize("fails", [False, True])
def test_all_diagnostic_entries_contain_output_and_errors(
    monkeypatch, tmp_path, capfd, entry, fails
):
    def noisy(**kwargs):
        emit_private_output()
        if fails:
            raise RuntimeError(SECRET)
        raw = valid_report()
        raw.update(
            {
                "auth_error": SECRET,
                "detail": SECRET,
                "PYTHON_VERSION": SECRET,
                "TGW_LOADED_DLL_PATH": SECRET,
                "SDK_ABI": SECRET,
                "checked_at": SECRET,
                "NETWORK_REACHABLE": SECRET,
                "platform": SECRET,
            }
        )
        raw["ACCOUNT_PROFILE"]["Token"] = SECRET
        return raw

    output = tmp_path / "diagnostic.json"
    if entry == "bootstrap":
        module = bootstrap()
        monkeypatch.setattr(module, "run_doctor", noisy)
        monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
        monkeypatch.setattr(
            module,
            "load_env",
            lambda path: {
                "TGW_USERNAME": "test-user",
                "TGW_PASSWORD": SECRET,
                "TGW_SERVER_VIP": "test-only-host",
                "TGW_SERVER_PORT": "0",
            },
        )
        monkeypatch.setattr(sys, "argv", ["bootstrap", "--output", str(output)])
        assert module.main() == (3 if fails else 0)
    elif entry == "cli":
        monkeypatch.setattr(doctor, "run_doctor", noisy)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["provider-doctor", "--output", str(output)])
        assert result.exit_code == 0
        assert SECRET not in result.output
        # stdout JSON and persisted JSON originate from the same projection.
        assert json.JSONDecoder().raw_decode(result.stdout)[0] == json.loads(output.read_text())
    else:
        monkeypatch.setattr(doctor, "_collect_doctor", noisy)
        report = doctor.run_doctor(credentials=None)
        assert SECRET not in json.dumps(report)
    captured = capfd.readouterr()
    assert SECRET not in captured.out + captured.err
    if output.exists():
        assert SECRET not in output.read_text()
    os.write(1, b"H1_FD1_RESTORED\n")
    os.write(2, b"H1_FD2_RESTORED\n")
    restored = capfd.readouterr()
    assert "H1_FD1_RESTORED" in restored.out
    assert "H1_FD2_RESTORED" in restored.err


@pytest.mark.parametrize(
    ("stage", "error"),
    [
        ("load", ProviderUnavailableError(SECRET)),
        ("load", RuntimeError(SECRET)),
        ("login", ProviderAuthError(SECRET, context={"raw": SECRET})),
        ("login", RuntimeError("password " + SECRET)),
        ("login", RuntimeError(SECRET)),
    ],
)
def test_session_failure_text_never_enters_lifecycle_or_public_exception(
    monkeypatch, capfd, stage, error
):
    class FakeSDK:
        def login(self, **kwargs):
            emit_private_output()
            raise error

    def loader():
        emit_private_output()
        if stage == "load":
            raise error
        return FakeSDK()

    monkeypatch.setattr(sdk_loader, "load_sdk", loader)
    session = AmazingDataSession("test-user", SECRET, "test-only-host", 0)
    with pytest.raises(ProviderError) as caught:
        session.login()
    assert SECRET not in str(caught.value)
    assert SECRET not in str(caught.value.context)
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in repr(session.lifecycle.history)
    captured = capfd.readouterr()
    assert SECRET not in captured.out + captured.err


@pytest.mark.parametrize("login_fails", [False, True])
def test_doctor_nested_login_retains_profile_but_not_private_output(
    monkeypatch, capfd, login_fails
):
    class FakeSDK:
        def login(self, **kwargs):
            emit_private_output()
            if login_fails:
                raise ProviderAuthError(SECRET)
            os.write(
                1,
                (
                    'logon json : {"PermissionCode":"1|2","TotalWeekFlow":500,'
                    '"Token":"' + SECRET + '"}\n'
                ).encode(),
            )

        def logout(self):
            emit_private_output()

        def BaseData(self):
            return self

        def get_code_list(self):
            emit_private_output()
            return ["TEST"]

    monkeypatch.setattr(sdk_loader, "load_sdk", lambda: FakeSDK())
    monkeypatch.setattr(
        doctor,
        "probe_identity",
        lambda **kwargs: SimpleNamespace(
            sdk_version="1.1.9",
            tgw_package_version="1.0.9.2",
            tgw_runtime_version="V4.3.0",
            abi_dir="win_py314_x64_package",
        ),
    )
    monkeypatch.setattr(doctor, "_network_probe", lambda *args: "REACHABLE")
    monkeypatch.setattr(doctor, "_loaded_tgw_modules", lambda: ["C:/site-packages/tgw/tgw.dll"])
    monkeypatch.setattr(doctor, "_dll_file_version", lambda path: None)
    report = doctor.run_doctor(credentials=("test-user", SECRET, "test-only-host", 0))
    assert report["AUTHENTICATED"] == ("NO" if login_fails else "YES")
    assert report["QUERY_READY"] == ("NOT_TESTED" if login_fails else "YES")
    assert report["verdict"] == "RUNTIME_ACTUAL_LOAD_VERIFIED"
    if login_fails:
        assert report["auth_error"] == "ProviderAuthError"
        assert report["ACCOUNT_PROFILE"]["account_profile_id"] == "UNAVAILABLE"
    else:
        assert report["ACCOUNT_PROFILE"]["account_profile_id"].startswith("UNKNOWN_")
        assert report["ACCOUNT_PROFILE"]["permission_codes"] == "1|2"
    assert SECRET not in json.dumps(report)
    captured = capfd.readouterr()
    assert SECRET not in captured.out + captured.err


def test_independent_nested_capture_restores_outer_marker():
    outer, inner = CapturedStdout(), CapturedStdout()
    with sdk_stdout_into(outer):
        print("OUTER_BEFORE")
        with sdk_stdout_into(inner, independent=True):
            print("INNER")
        assert getattr(sys.stdout, "_sdk_capture_active", False)
        print("OUTER_AFTER")
    assert "INNER" in inner.text
    assert "INNER" not in outer.text
    assert "OUTER_BEFORE" in outer.text and "OUTER_AFTER" in outer.text
    assert not getattr(sys.stdout, "_sdk_capture_active", False)


def test_projection_is_idempotent_and_drops_untrusted_fields():
    raw = valid_report()
    raw["arbitrary"] = {"Token": SECRET}
    safe = safe_diagnostic_projection(raw)
    assert safe_diagnostic_projection(safe) == safe
    assert SECRET not in json.dumps(safe)


def test_offline_cli_never_loads_credential_settings(monkeypatch):
    monkeypatch.setattr(
        "ashare_state.cli.Settings", lambda: pytest.fail("offline loaded credential settings")
    )

    def offline_doctor(**kwargs):
        assert kwargs == {"credentials": None, "offline": True}
        return valid_report()

    monkeypatch.setattr(doctor, "run_doctor", offline_doctor)
    result = CliRunner().invoke(app, ["provider-doctor", "--offline"])
    assert result.exit_code == 0
    assert "ACCOUNT_PROFILE" not in json.loads(result.stdout)


def test_known_runtime_release_suffix_is_preserved():
    raw = valid_report()
    raw["TGW_RUNTIME_REPORTED_VERSION"] = "V4.3.0.260626-rc2.0-YHZQ"
    assert safe_diagnostic_projection(raw)["TGW_RUNTIME_REPORTED_VERSION"] == (
        "V4.3.0.260626-rc2.0-YHZQ"
    )


def test_unsupported_capture_platform_refuses_before_sdk_call(monkeypatch):
    monkeypatch.setattr(sys, "platform", "unsupported")
    with (
        pytest.raises(RuntimeError, match="unsupported platform"),
        sdk_stdout_into(CapturedStdout()),
    ):
        pytest.fail("must not enter an uncontained SDK call")


def test_three_ci_legs_are_required_and_production_identity_is_empty():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["quality"]
    assert job.get("continue-on-error", False) is False
    matrix = job["strategy"]["matrix"]["include"]
    assert {(row["os"], row["python-version"]) for row in matrix} == {
        ("windows-latest", "3.14"),
        ("windows-latest", "3.12"),
        ("ubuntu-latest", "3.14"),
    }
    assert all(row["required"] is True for row in matrix)
    identity = yaml.safe_load((ROOT / "configs/production_account.yaml").read_text())
    assert all(
        not identity.get(key)
        for key in (
            "production_account_profile_id",
            "confirmed_at",
            "confirmed_by",
        )
    )
