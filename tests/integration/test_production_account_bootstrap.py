"""Tests for the scrubbed production-account bootstrap boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "spike" / "production_account_bootstrap.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("production_account_bootstrap", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
class TestProductionAccountBootstrap:
    def test_online_report_is_scrubbed_and_never_writes_config(
        self, monkeypatch, tmp_path: Path, capsys
    ):
        module = _load_script()
        secret = "MUST_NOT_APPEAR_ANYWHERE"
        output = tmp_path / "bootstrap.json"
        calls: list[dict[str, object]] = []

        monkeypatch.setattr(
            module,
            "load_env",
            lambda _path: {
                "TGW_USERNAME": "user",
                "TGW_PASSWORD": secret,
                "TGW_SERVER_VIP": "127.0.0.1",
                "TGW_SERVER_PORT": "8600",
            },
        )
        monkeypatch.setattr(
            module,
            "run_doctor",
            lambda **kwargs: (
                calls.append(kwargs)
                or {
                    "checked_at": "2026-09-04T00:00:00+00:00",
                    "platform": "win32",
                    "PYTHON_VERSION": "3.14.6",
                    "SDK_ABI": "cpython314/win32-x64",
                    "sdk_state": "SDK_INSTALLED",
                    "AMAZINGDATA_PACKAGE_VERSION": "1.1.9",
                    "PYTHON_TGW_PACKAGE_VERSION": "1.0.9.2",
                    "TGW_RUNTIME_REPORTED_VERSION": "V4.3.0",
                    "verdict": "RUNTIME_ACTUAL_LOAD_VERIFIED",
                    "NETWORK_REACHABLE": "REACHABLE",
                    "AUTHENTICATED": "YES",
                    "QUERY_READY": "YES",
                    "ACCOUNT_PROFILE": {
                        "account_profile_id": "UNKNOWN_abc123",
                        "permission_codes": "3|4|32|33",
                        "subscribe_limit": 100,
                        "weekly_flow_limit": 1024,
                        "used_week_flow": 1,
                        "auth_error": secret,
                    },
                    "auth_error": secret,
                    "detail": secret,
                }
            ),
        )
        monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
        monkeypatch.setattr(
            sys,
            "argv",
            ["production_account_bootstrap.py", "--output", str(output)],
        )

        assert module.main() == 0
        assert calls == [
            {
                "credentials": ("user", secret, "127.0.0.1", 8600),
                "offline": False,
            }
        ]
        stdout = capsys.readouterr().out
        persisted = output.read_text(encoding="utf-8")
        assert secret not in stdout
        assert secret not in persisted
        report = json.loads(persisted)
        assert report["bootstrap_status"] == "IDENTITY_CANDIDATE"
        assert report["ACCOUNT_PROFILE"]["account_profile_id"] == "UNKNOWN_abc123"
        assert report["config_written"] is False
        assert report["human_confirmation_required"] is True

    def test_missing_environment_is_not_testable_and_does_not_call_doctor(
        self, monkeypatch, capsys
    ):
        module = _load_script()
        called = False

        monkeypatch.setattr(module, "load_env", lambda _path: {})

        def fail_doctor(**_kwargs):
            nonlocal called
            called = True
            pytest.fail("doctor must not run without complete credential environment")

        monkeypatch.setattr(module, "run_doctor", fail_doctor)
        monkeypatch.setattr(sys, "argv", ["production_account_bootstrap.py"])

        assert module.main() == 2
        assert called is False
        report = json.loads(capsys.readouterr().out)
        assert report["bootstrap_status"] == "NOT_TESTABLE_ACCOUNT"
        assert report["AUTHENTICATED"] == "NOT_TESTED"

    def test_offline_mode_bypasses_env_file_and_never_passes_credentials(
        self, monkeypatch, capsys, tmp_path: Path
    ):
        module = _load_script()
        calls: list[dict[str, object]] = []
        secret_file = tmp_path / "credentials.env"
        secret_file.write_text("TGW_PASSWORD=MUST_NOT_APPEAR_ANYWHERE\n", encoding="utf-8")

        def fail_load_env(_path):
            pytest.fail("offline must not load .env or --env-file")

        monkeypatch.setattr(module, "load_env", fail_load_env)
        monkeypatch.setattr(
            module,
            "run_doctor",
            lambda **kwargs: (
                calls.append(kwargs)
                or {
                    "sdk_state": "SDK_INSTALLED",
                    "verdict": "RUNTIME_PACKAGE_VERIFIED",
                    "AUTHENTICATED": "YES",
                    "ACCOUNT_PROFILE": {
                        "account_profile_id": "SHOULD_NOT_BE_PROJECTED",
                    },
                }
            ),
        )
        monkeypatch.setattr(
            module,
            "load_frozen_production_identity",
            lambda: pytest.fail("offline must not inspect production identity"),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "production_account_bootstrap.py",
                "--offline",
                "--env-file",
                str(secret_file),
            ],
        )

        assert module.main() == 0
        assert calls == [{"credentials": None, "offline": True}]
        report = json.loads(capsys.readouterr().out)
        assert report["bootstrap_status"] == "OFFLINE_RUNTIME_VERIFIED"
        assert report["offline"] is True
        for key in (
            "ACCOUNT_PROFILE",
            "production_identity_status",
            "AUTHENTICATED",
            "QUERY_READY",
        ):
            assert key not in report

    def test_online_stderr_is_contained_and_fd2_is_restored(
        self, monkeypatch, tmp_path: Path, capfd
    ):
        module = _load_script()
        secret = "MUST_NOT_APPEAR_ANYWHERE"
        output = tmp_path / "bootstrap.json"

        monkeypatch.setattr(
            module,
            "load_env",
            lambda _path: {
                "TGW_USERNAME": "user",
                "TGW_PASSWORD": secret,
                "TGW_SERVER_VIP": "127.0.0.1",
                "TGW_SERVER_PORT": "8600",
            },
        )

        def noisy_doctor(**_kwargs):
            os.write(2, f"{secret}\n".encode())
            print(secret, file=sys.stderr)
            return {
                "sdk_state": "SDK_INSTALLED",
                "verdict": "RUNTIME_PACKAGE_VERIFIED",
                "AUTHENTICATED": "YES",
                "QUERY_READY": "YES",
                "ACCOUNT_PROFILE": {
                    "account_profile_id": "UNKNOWN_abc123",
                    "permission_codes": "3|4",
                },
            }

        monkeypatch.setattr(module, "run_doctor", noisy_doctor)
        monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
        monkeypatch.setattr(
            sys,
            "argv",
            ["production_account_bootstrap.py", "--output", str(output)],
        )

        assert module.main() == 0
        captured = capfd.readouterr()
        persisted = output.read_text(encoding="utf-8")
        assert secret not in captured.out
        assert secret not in captured.err
        assert secret not in persisted

        os.write(2, b"AFTER_BOOTSTRAP_RESTORE\n")
        restored = capfd.readouterr()
        assert "AFTER_BOOTSTRAP_RESTORE" in restored.err

    def test_online_stderr_is_contained_on_exception_path(self, monkeypatch, tmp_path: Path, capfd):
        module = _load_script()
        secret = "MUST_NOT_APPEAR_ANYWHERE"
        output = tmp_path / "bootstrap.json"

        monkeypatch.setattr(
            module,
            "load_env",
            lambda _path: {
                "TGW_USERNAME": "user",
                "TGW_PASSWORD": secret,
                "TGW_SERVER_VIP": "127.0.0.1",
                "TGW_SERVER_PORT": "8600",
            },
        )

        def failing_doctor(**_kwargs):
            os.write(2, f"{secret}\n".encode())
            print(secret, file=sys.stderr)
            raise RuntimeError(secret)

        monkeypatch.setattr(module, "run_doctor", failing_doctor)
        monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
        monkeypatch.setattr(
            sys,
            "argv",
            ["production_account_bootstrap.py", "--output", str(output)],
        )

        assert module.main() == 3
        captured = capfd.readouterr()
        persisted = output.read_text(encoding="utf-8")
        assert secret not in captured.out
        assert secret not in captured.err
        assert secret not in persisted
        assert json.loads(persisted)["bootstrap_status"] == "ERROR"
    def test_online_unexpected_profile_id_is_not_projected(self, monkeypatch, capsys):
        module = _load_script()
        secret_marker = "UNSAFE_PROFILE_VALUE"

        monkeypatch.setattr(
            module,
            "load_env",
            lambda _path: {
                "TGW_USERNAME": "user",
                "TGW_PASSWORD": "runtime-only",
                "TGW_SERVER_VIP": "127.0.0.1",
                "TGW_SERVER_PORT": "8600",
            },
        )
        monkeypatch.setattr(
            module,
            "run_doctor",
            lambda **_kwargs: {
                "sdk_state": "SDK_INSTALLED",
                "verdict": "RUNTIME_ACTUAL_LOAD_VERIFIED",
                "AUTHENTICATED": "YES",
                "QUERY_READY": "YES",
                "ACCOUNT_PROFILE": {
                    "account_profile_id": secret_marker,
                    "permission_codes": "1|2",
                    "subscribe_limit": secret_marker,
                },
            },
        )
        monkeypatch.setattr(module, "load_frozen_production_identity", lambda: None)
        monkeypatch.setattr(sys, "argv", ["production_account_bootstrap.py"])

        assert module.main() == 1
        stdout = capsys.readouterr().out
        assert secret_marker not in stdout
        report = json.loads(stdout)
        assert report["bootstrap_status"] == "NOT_TESTABLE_PROFILE"
        assert report["ACCOUNT_PROFILE"]["account_profile_id"] == "UNAVAILABLE"
        assert report["ACCOUNT_PROFILE"]["subscribe_limit"] is None
