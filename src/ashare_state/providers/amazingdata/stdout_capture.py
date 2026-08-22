"""OS-level stdout capture around SDK calls (task book section 3.1).

The AmazingData SDK prints logon JSON (containing the session Token!) to
fd 1 via native code - contextlib.redirect_stdout does NOT intercept that.
We redirect the actual file descriptor into a temp file, then parse the
captured text with mandatory secret scrubbing before anything is stored.

Rules:
- Token values NEVER leave this module; the parsed profile is scrubbed.
- stderr (SDK logs, MinLogLevel>=1) is NOT captured: it stays on console.
- Capture is re-entrant safe (nested uses reuse the outer redirect).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_SENSITIVE_KEYS = ("token", "password", "username", "session", "credential")
_MASK = "***MASKED***"

_CAPTURE_FLAG = "_sdk_capture_active"

# Audit P1-12: fd-level stdout redirection is PROCESS-WIDE; concurrent
# provider threads must be serialized or captures interleave / restore
# in the wrong order (Token capture could leak).
_GLOBAL_SDK_STDOUT_LOCK = threading.RLock()


def _set_capture_flag(obj: object, value: bool) -> None:
    setattr(obj, _CAPTURE_FLAG, value)


def _has_capture_flag(obj: object) -> bool:
    return bool(getattr(obj, _CAPTURE_FLAG, False))


def scrub_dict(payload: dict) -> dict:
    out: dict = {}
    for k, v in payload.items():
        if any(s in str(k).lower() for s in _SENSITIVE_KEYS):
            out[k] = _MASK
        elif isinstance(v, dict):
            out[k] = scrub_dict(v)
        else:
            out[k] = v
    return out


class CapturedStdout:
    """Container so the context manager can hand back the text afterwards."""

    def __init__(self) -> None:
        self.text = ""


@contextmanager
def sdk_stdout_into(holder: CapturedStdout) -> Iterator[None]:
    """Redirect fd 1 to a temp file for the duration; text lands in holder.

    Native printf goes to fd 1 - we dup the original, swap in a temp file,
    and restore afterwards in finally (crash-safe at the os level).

    Audit P1-12: the whole capture region is serialized by a global RLock -
    concurrent provider threads cannot interleave fd swaps.
    """
    if sys.platform not in ("win32", "linux"):
        yield
        return
    with _GLOBAL_SDK_STDOUT_LOCK:
        if _has_capture_flag(sys.stdout):
            # re-entrancy: outer capture already active; SDK text still lands
            # in the OUTER temp file, nothing to restore here.
            yield
            return

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as tmp:
            sys.stdout.flush()
            saved_fd = os.dup(1)
            marker = sys.stdout
            _set_capture_flag(marker, True)
            try:
                os.dup2(tmp.fileno(), 1)
                yield
            finally:
                _set_capture_flag(marker, False)
                # flush must not mask fd restore
                with contextlib.suppress(Exception):
                    sys.stdout.flush()
                os.dup2(saved_fd, 1)
                os.close(saved_fd)
                tmp.seek(0)
                holder.text = tmp.read()


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
