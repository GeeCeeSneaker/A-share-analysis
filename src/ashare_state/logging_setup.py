"""Structured logging with registered secret masking (V1.3.2 section 26.3).

Provider credentials must never reach logs. Masking is done at the logging
layer via a filter that rewrites record args whose key matches a registered
sensitive pattern.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_DEFAULT_SENSITIVE_PATTERNS = [
    r"password",
    r"passwd",
    r"token",
    r"secret",
    r"credential",
    r"api[-_]?key",
    r"username",
    r"user[-_]?id",
    r"session[-_]?key",
]

_MASK = "***MASKED***"


class SecretMaskingFilter(logging.Filter):
    """Masks values of sensitive keys appearing in log records.

    Handles:
    - dict payloads under record.extra / record.context
    - keyword-style "key=value" pairs inside the formatted message
    """

    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        super().__init__()
        patterns = _DEFAULT_SENSITIVE_PATTERNS + (extra_patterns or [])
        self._pattern = re.compile("|".join(patterns), flags=re.IGNORECASE)

    def _mask_value(self, key: Any, value: Any) -> Any:
        if isinstance(key, str) and self._pattern.search(key):
            return _MASK
        if isinstance(value, str):
            return self._mask_inline(value)
        return value

    def _mask_inline(self, text: str) -> str:
        # mask key=value / key: value pairs whose key looks sensitive
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if self._pattern.search(key):
                return f"{key}={_MASK}"
            return match.group(0)

        return re.sub(r"(\w[\w\-]*)=([^\s,;]+)", repl, text)

    def filter(self, record: logging.LogRecord) -> bool:
        # mask structured context dictionaries if present
        for attr in ("context", "extra"):
            payload = getattr(record, attr, None)
            if isinstance(payload, dict):
                masked_payload = {k: self._mask_value(k, v) for k, v in payload.items()}
                setattr(record, attr, masked_payload)
        # mask printf-style dict args directly
        args: Any = record.args
        if args and isinstance(args, dict):
            args = {k: self._mask_value(k, v) for k, v in args.items()}
            record.args = args
        # mask inline key=value in the plain message; when the message was
        # rewritten (audit P1-13) the leftover positional args can no longer
        # be interpolated safely -> pre-format now to avoid formatter errors
        if isinstance(record.msg, str):
            masked_msg = self._mask_inline(record.msg)
            if masked_msg != record.msg and args:
                try:
                    record.msg = masked_msg % args
                except (TypeError, ValueError):
                    record.msg = masked_msg
                record.args = None
            else:
                record.msg = masked_msg
        return True


def mask_secret(value: str) -> str:
    """Utility used when echoing config safely."""
    return _MASK if value else value


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging with secret masking installed globally."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # install masking filter on the handler so every record passes through it
    handler.addFilter(SecretMaskingFilter())
