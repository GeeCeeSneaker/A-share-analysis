"""Secret masking tests (M0 exit: secrets never enter logs)."""

from __future__ import annotations

import logging

from ashare_state.logging_setup import SecretMaskingFilter, mask_secret, setup_logging


class TestSecretMaskingFilter:
    def _capture(self, msg: str) -> str:
        logger = logging.getLogger("test.masking")
        for h in list(logger.handlers):
            logger.removeHandler(h)
        handler = logging.StreamHandler()
        handler.addFilter(SecretMaskingFilter())
        logger.addHandler(handler)

        import io

        buf = io.StringIO()
        handler.stream = buf
        logger.setLevel(logging.INFO)
        logger.info(msg)
        return buf.getvalue()

    def test_inline_key_value_masked(self):
        out = self._capture("login password=hunter2 failed")
        assert "hunter2" not in out
        assert "***MASKED***" in out

    def test_token_masked(self):
        out = self._capture("request token=abc123 sent")
        assert "abc123" not in out

    def test_non_sensitive_value_kept(self):
        out = self._capture("provider=amazingdata dataset=daily rows=100")
        assert "amazingdata" in out
        assert "daily" in out

    def test_username_masked(self):
        out = self._capture("connecting username=broker_user now")
        assert "broker_user" not in out

    def test_plain_message_untouched(self):
        out = self._capture("migration 001 applied")
        assert "migration 001 applied" in out

    def test_mask_secret_utility(self):
        assert mask_secret("s3cret") == "***MASKED***"
        assert mask_secret("") == ""


class TestSetupLogging:
    def test_setup_installs_filter(self):
        setup_logging()
        root = logging.getLogger()
        assert any(isinstance(f, SecretMaskingFilter) for h in root.handlers for f in h.filters)
