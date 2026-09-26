"""SDK stdout capture tests (task book 3.1: logon Token must never escape)."""

from __future__ import annotations

import os
import sys

from ashare_state.providers.amazingdata.stdout_capture import (
    CapturedStdout,
    parse_logon_profile,
    scrub_dict,
    sdk_stdout_into,
)


class TestCapture:
    def test_python_print_captured(self, capsys):
        # pytest replaces fd 1 with its own pipe: disable its capture so the
        # print below flows through the REAL fd 1 (which we then redirect).
        with capsys.disabled():
            holder = CapturedStdout()
            with sdk_stdout_into(holder):
                print("hello from python")
            import os as _os

            _os.write(1, b"\n")  # newline hygiene after raw prints
        assert "hello from python" in holder.text

    def test_fd_level_write_captured(self):
        """Native-code style write via os.write to fd 1."""
        holder = CapturedStdout()
        with sdk_stdout_into(holder):
            os.write(1, b"native fd write\n")
        assert "native fd write" in holder.text

    def test_windows_standard_handle_write_captured(self):
        """A Windows native-handle write must not escape to the terminal."""
        if sys.platform != "win32":
            return
        import ctypes

        holder = CapturedStdout()
        with sdk_stdout_into(holder):
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_std_handle = kernel32.GetStdHandle
            get_std_handle.argtypes = [ctypes.c_uint32]
            get_std_handle.restype = ctypes.c_void_p
            write_file = kernel32.WriteFile
            write_file.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p,
            ]
            write_file.restype = ctypes.c_int
            payload = b"native Windows handle write\n"
            written = ctypes.c_uint32()
            assert write_file(
                get_std_handle(ctypes.c_uint32(-11 & 0xFFFFFFFF).value),
                payload,
                len(payload),
                ctypes.byref(written),
                None,
            )
            assert written.value == len(payload)
        assert "native Windows handle write" in holder.text

    def test_stdout_restored_after_block(self):
        holder = CapturedStdout()
        with sdk_stdout_into(holder):
            print("inner")
        print("outer-visible")  # must reach the real stdout again
        assert not getattr(__import__("sys").stdout, "_sdk_capture_active", False)

    def test_nested_capture_reentrant(self):
        with _disabled_capsys():
            outer = CapturedStdout()
            with sdk_stdout_into(outer):
                os.write(1, b"outer-1\n")
                inner = CapturedStdout()
                with sdk_stdout_into(inner):
                    os.write(1, b"inner-1\n")
                os.write(1, b"outer-2\n")
            # inner text landed in the OUTER capture (single redirect active)
            assert "outer-1" in outer.text
            assert "inner-1" in outer.text
            assert "outer-2" in outer.text


def _disabled_capsys():
    """No-op context: fd-level writes need no pytest capture juggling."""
    import contextlib

    return contextlib.nullcontext()


class TestParseLogonProfile:
    def test_token_scrubbed(self):
        captured = (
            "TGW Logon information:  :\n"
            'logon json :  {"Id":0,"SubscribeLimitNum":100,"Token":"SECRET-UUID-123",'
            '"PermissionCode":"3|4|32|33","TotalWeekFlow":10}\n'
            "login success"
        )
        profile = parse_logon_profile(captured)
        assert profile is not None
        assert profile["Token"] == "***MASKED***"
        assert "SECRET-UUID-123" not in str(profile)
        assert profile["PermissionCode"] == "3|4|32|33"

    def test_missing_pattern_returns_none(self):
        assert parse_logon_profile("no json here") is None

    def test_malformed_json_returns_none(self):
        assert parse_logon_profile("logon json :  {broken") is None

    def test_scrub_dict_nested(self):
        payload = {
            "Token": "abc",
            "CustomPermission": {"L1Permission": [], "inner_token": "x"},
            "PermissionCode": "ok",
        }
        scrubbed = scrub_dict(payload)
        assert scrubbed["Token"] == "***MASKED***"
        assert scrubbed["CustomPermission"]["inner_token"] == "***MASKED***"
        assert scrubbed["PermissionCode"] == "ok"


def test_session_login_and_logout_contain_native_sdk_output(monkeypatch, capfd):
    from ashare_state.providers.amazingdata import sdk_loader
    from ashare_state.providers.amazingdata.session import AmazingDataSession

    private_token = "test-only-private-token"

    class FakeSDK:
        def login(self, **_kwargs):
            os.write(1, b"TGW Logon information:\n")
            os.write(
                1,
                (
                    'logon json : {"PermissionCode":"1|2","TotalWeekFlow":500,'
                    f'"Token":"{private_token}"}}\n'
                ).encode(),
            )
            os.write(2, f"private sdk diagnostic {private_token}\n".encode())

        def logout(self):
            os.write(1, f"logout token={private_token}\n".encode())
            os.write(2, f"logout diagnostic {private_token}\n".encode())

    monkeypatch.setattr(sdk_loader, "load_sdk", lambda: FakeSDK())
    session = AmazingDataSession("TESTUSER", "TESTPASSWORD", "test-host", 8600)

    profile = session.login()
    session.logout()

    captured = capfd.readouterr()
    assert private_token not in captured.out + captured.err
    assert profile.raw_profile["Token"] == "***MASKED***"
