"""Tests for the single TGW password source and Windows vault boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from ashare_state.providers.amazingdata import credentials


def test_env_file_password_is_ignored_and_process_values_win(tmp_path: Path):
    secret = "DO_NOT_LOAD_FROM_ENV_FILE"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"TGW_USERNAME=file-user\nTGW_PASSWORD={secret}\nTGW_SERVER_PORT=8000\n",
        encoding="utf-8",
    )

    settings = credentials.load_tgw_environment(
        env_file,
        environ={"TGW_USERNAME": "process-user", "TGW_SERVER_VIP": "process-host"},
    )

    assert settings == {
        "TGW_USERNAME": "process-user",
        "TGW_SERVER_VIP": "process-host",
        "TGW_SERVER_PORT": "8000",
    }
    assert secret not in repr(settings)


def test_process_password_override_does_not_touch_vault(monkeypatch):
    secret = "PROCESS_ONLY_TEST_SECRET"
    monkeypatch.setattr(
        credentials,
        "_windows_credential_store",
        lambda: pytest.fail("process override must not read the vault"),
    )

    resolved = credentials.resolve_tgw_credentials(
        {
            "TGW_USERNAME": "test-user",
            "TGW_PASSWORD": secret,
            "TGW_SERVER_VIP": "test-host",
            "TGW_SERVER_PORT": "8600",
        }
    )

    assert resolved == ("test-user", secret, "test-host", 8600)


def test_resolves_password_from_os_store(monkeypatch):
    class FakeStore:
        def get_password(self, service: str, username: str) -> str:
            assert service == credentials.TGW_VAULT_SERVICE
            assert username == "test-user"
            return "vault-only-test-secret"

    monkeypatch.setattr(credentials, "_windows_credential_store", lambda: FakeStore())

    assert credentials.resolve_tgw_credentials(
        {
            "TGW_USERNAME": "test-user",
            "TGW_SERVER_VIP": "test-host",
            "TGW_SERVER_PORT": "8600",
        }
    ) == ("test-user", "vault-only-test-secret", "test-host", 8600)


def test_missing_or_inaccessible_vault_fails_closed_with_safe_action(monkeypatch):
    secret = "VAULT_EXCEPTION_SECRET_MARKER"

    class MissingStore:
        def get_password(self, _service: str, _username: str) -> None:
            return None

    monkeypatch.setattr(credentials, "_windows_credential_store", lambda: MissingStore())
    with pytest.raises(credentials.TgwCredentialsError) as missing:
        credentials.resolve_tgw_credentials(
            {
                "TGW_USERNAME": "test-user",
                "TGW_SERVER_VIP": "test-host",
                "TGW_SERVER_PORT": "8600",
            }
        )
    assert credentials.STORE_CREDENTIAL_COMMAND in str(missing.value)

    def raise_backend():
        raise RuntimeError(secret)

    monkeypatch.setattr(credentials, "_windows_credential_store", raise_backend)
    with pytest.raises(credentials.TgwCredentialsError) as inaccessible:
        credentials.resolve_tgw_credentials(
            {
                "TGW_USERNAME": "test-user",
                "TGW_SERVER_VIP": "test-host",
                "TGW_SERVER_PORT": "8600",
            }
        )
    assert secret not in str(inaccessible.value)
    assert credentials.STORE_CREDENTIAL_COMMAND in str(inaccessible.value)


def test_store_prompts_once_and_never_returns_or_prints_the_password(monkeypatch, capsys):
    secret = "PROMPT_ONLY_TEST_SECRET"
    prompts: list[str] = []
    writes: list[tuple[str, str, str]] = []

    class FakeStore:
        def set_password(self, service: str, username: str, password: str) -> None:
            writes.append((service, username, password))

    def prompt(message: str) -> str:
        prompts.append(message)
        return secret

    monkeypatch.setattr(credentials, "_windows_credential_store", lambda: FakeStore())
    result = credentials.store_tgw_password("test-user", prompt=prompt)

    assert result is None
    assert len(prompts) == 1
    assert writes == [(credentials.TGW_VAULT_SERVICE, "test-user", secret)]
    assert secret not in capsys.readouterr().out


def test_store_failure_does_not_expose_backend_error(monkeypatch):
    secret = "SET_BACKEND_SECRET_MARKER"

    class BrokenStore:
        def set_password(self, _service: str, _username: str, _password: str) -> None:
            raise RuntimeError(secret)

    monkeypatch.setattr(credentials, "_windows_credential_store", lambda: BrokenStore())
    with pytest.raises(credentials.TgwCredentialsError) as raised:
        credentials.store_tgw_password("test-user", prompt=lambda _message: "test-secret")
    assert secret not in str(raised.value)
