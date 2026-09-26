from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.spike.issue95_status_limit_build import Issue95Build


def test_runner_quarantines_delayed_native_stdout_but_keeps_safe_progress() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    code = """
import os
from scripts.spike.issue95_status_limit_build import (
    _emit,
    _quarantine_untrusted_sdk_output,
)
with _quarantine_untrusted_sdk_output():
    os.write(1, b'UNTRUSTED_SDK_MARKER\\n')
    _emit('SAFE_PROGRESS_MARKER')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        cwd=repo_root,
        text=True,
        timeout=20,
    )

    assert "SAFE_PROGRESS_MARKER" in result.stdout
    assert "UNTRUSTED_SDK_MARKER" not in result.stdout
    assert "UNTRUSTED_SDK_MARKER" not in result.stderr


def test_resume_restores_the_recorded_provider_batch_size(tmp_path: Path) -> None:
    build = Issue95Build(
        run_root=tmp_path,
        max_status_batch_size=1000,
        conn=None,
        provider=None,
        initial_state={
            "run_id": "test-run",
            "receipts": {"provider_call_count": 1},
            "status_batch_size_probe": {"selected_size": 1000},
            "request_policy": {"status_batch_size_selected": 1000},
        },
    )

    assert build.status_batch_size == 1000
