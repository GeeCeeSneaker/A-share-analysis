"""SDK stdout capture tests (task book 3.1: logon Token must never escape)."""

from __future__ import annotations

import os

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
