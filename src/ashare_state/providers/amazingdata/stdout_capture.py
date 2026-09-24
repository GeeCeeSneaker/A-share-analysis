"""OS-level stdout capture around SDK calls (task book section 3.1).

The AmazingData SDK prints logon JSON (containing the session Token!) to
fd 1 via native code - contextlib.redirect_stdout does NOT intercept that.
We redirect the actual file descriptor into a temp file, then parse the
captured text with mandatory secret scrubbing before public evidence is stored.
TemporaryFile is local ephemeral capture, automatically closed/cleaned; raw
capture must never enter repository files or persistent project evidence.

Rules:
- Only the scrubbed parsed profile may become public evidence; holders are raw.
- stderr (SDK logs, MinLogLevel>=1) is contained by sdk_stderr_into during
  credential-bearing diagnostics; raw text is never emitted as public evidence.
- Capture is re-entrant safe (nested uses reuse the outer redirect).
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_SENSITIVE_KEYS = ("token", "password", "username", "session", "credential")
_MASK = "***MASKED***"

_CAPTURE_FLAG = "_sdk_capture_active"
_STDERR_CAPTURE_FLAG = "_sdk_stderr_capture_active"

# Audit P1-12: fd-level stdout redirection is PROCESS-WIDE; concurrent
# provider threads must be serialized or captures interleave / restore
# in the wrong order (Token capture could leak).
_GLOBAL_SDK_STDOUT_LOCK = threading.RLock()


@contextmanager
def _windows_std_handle_into(target_fd: int, std_handle: int) -> Iterator[None]:
    """Redirect a Windows process standard handle to ``target_fd``.

    ``os.dup2`` protects Python and CRT writes, but a native SDK can call
    ``GetStdHandle``/``WriteFile`` directly. Those writes bypass CRT fd 1/2
    and otherwise remain visible in the user's terminal. Keep this boundary
    Windows-only so the portable fd capture remains unchanged elsewhere.
    """
    if sys.platform != "win32":
        yield
        return

    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_std_handle = kernel32.GetStdHandle
    get_std_handle.argtypes = [ctypes.c_uint32]
    get_std_handle.restype = ctypes.c_void_p
    set_std_handle = kernel32.SetStdHandle
    set_std_handle.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    set_std_handle.restype = ctypes.c_int

    handle_id = ctypes.c_uint32(std_handle & 0xFFFFFFFF).value
    previous = get_std_handle(handle_id)
    target = ctypes.c_void_p(msvcrt.get_osfhandle(target_fd))
    if not set_std_handle(handle_id, target):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not set_std_handle(handle_id, previous):
            raise ctypes.WinError(ctypes.get_last_error())


def _set_capture_flag(obj: object, value: bool, flag: str = _CAPTURE_FLAG) -> None:
    setattr(obj, flag, value)


def _has_capture_flag(obj: object, flag: str = _CAPTURE_FLAG) -> bool:
    return bool(getattr(obj, flag, False))


def scrub_dict(payload: dict) -> dict:
    out: dict = {}
    for k, v in payload.items():
        if any(s in str(k).lower() for s in _SENSITIVE_KEYS):
            out[k] = _MASK
        else:
            out[k] = scrub_value(v)
    return out


def scrub_value(value: Any) -> Any:
    """Scrub sensitive keys recursively without dropping container structure."""
    if isinstance(value, dict):
        return scrub_dict(value)
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_value(item) for item in value)
    return value


class CapturedStdout:
    """Container so the context manager can hand back the text afterwards."""

    def __init__(self) -> None:
        self.text = ""


class CapturedStderr:
    """Container for scrubbed observations of contained stderr output."""

    def __init__(self) -> None:
        self.text = ""


@contextmanager
def sdk_stdout_into(holder: CapturedStdout, *, independent: bool = False) -> Iterator[None]:
    """Redirect fd 1 to a temp file for the duration; text lands in holder.

    Native printf goes to fd 1 - we dup the original, swap in a temp file,
    and restore afterwards in finally (crash-safe at the os level).

    Audit P1-12: the whole capture region is serialized by a global RLock -
    concurrent provider threads cannot interleave fd swaps. An independent
    nested login capture retains its own profile while outer diagnostics
    suppress unrelated output; the original capture marker is restored.
    """
    if sys.platform not in ("win32", "linux"):
        raise RuntimeError("SDK output capture unsupported platform")
    with _GLOBAL_SDK_STDOUT_LOCK:
        if _has_capture_flag(sys.stdout) and not independent:
            # re-entrancy: outer capture already active; SDK text still lands
            # in the OUTER temp file, nothing to restore here.
            yield
            return

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as tmp:
            sys.stdout.flush()
            saved_fd = os.dup(1)
            marker = sys.stdout
            previous_active = _has_capture_flag(marker)
            _set_capture_flag(marker, True)
            try:
                os.dup2(tmp.fileno(), 1)
                with (
                    _windows_std_handle_into(tmp.fileno(), -11),
                    contextlib.redirect_stdout(tmp),
                ):
                    _set_capture_flag(tmp, True)
                    try:
                        yield
                    finally:
                        tmp.flush()
            finally:
                _set_capture_flag(marker, previous_active)
                # flush must not mask fd restore
                with contextlib.suppress(Exception):
                    sys.stdout.flush()
                os.dup2(saved_fd, 1)
                os.close(saved_fd)
                tmp.seek(0)
                holder.text = tmp.read()


@contextmanager
def sdk_stderr_into(holder: CapturedStderr) -> Iterator[None]:
    """Contain OS fd 2 and Python-level stderr for a provider call.

    Native writes use fd 2 while Python writes normally use sys.stderr.
    Both are contained, and only the caller's scrubbed observation may leave
    this context.
    """
    if sys.platform not in ("win32", "linux"):
        raise RuntimeError("SDK output capture unsupported platform")
    with _GLOBAL_SDK_STDOUT_LOCK:
        if _has_capture_flag(sys.stderr, _STDERR_CAPTURE_FLAG):
            # Re-entrant calls reuse the outer fd 2/Python stderr boundary.
            yield
            return

        with tempfile.TemporaryFile(mode="w+b") as tmp, io.StringIO() as python_stderr:
            sys.stderr.flush()
            saved_fd = os.dup(2)
            marker = sys.stderr
            _set_capture_flag(marker, True, _STDERR_CAPTURE_FLAG)
            try:
                os.dup2(tmp.fileno(), 2)
                with (
                    _windows_std_handle_into(tmp.fileno(), -12),
                    contextlib.redirect_stderr(python_stderr),
                ):
                    _set_capture_flag(sys.stderr, True, _STDERR_CAPTURE_FLAG)
                    try:
                        yield
                    finally:
                        _set_capture_flag(sys.stderr, False, _STDERR_CAPTURE_FLAG)
            finally:
                _set_capture_flag(marker, False, _STDERR_CAPTURE_FLAG)
                with contextlib.suppress(Exception):
                    sys.stderr.flush()
                os.dup2(saved_fd, 2)
                os.close(saved_fd)
                tmp.seek(0)
                native_text = tmp.read().decode("utf-8", errors="replace")
                holder.text = native_text + python_stderr.getvalue()


_LOGON_JSON_RE = re.compile(r"logon json\s*:\s*(\{.*\})", re.DOTALL)


def parse_logon_profile(captured_text: str) -> dict | None:
    """Extract + scrub the logon json the SDK prints on login.

    Returns the profile WITHOUT the token; returns None when the pattern
    is absent (e.g. login failed or SDK version changed).
    """
    match = _LOGON_JSON_RE.search(captured_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return scrub_dict(payload)
