# Issue #85 — Python runtime simplification

Date: 2026-09-24
Status: implementation prepared; exact-head CI and scheduler/Owner acceptance remain required.

## Decision and evidence

Issue #85 asks whether a real deployment, provider SDK, operator environment, or supported consumer still requires Python 3.12. The repository's controlled Windows AmazingData/TGW runtime was verified as Python 3.14.6 (`docs/provider_verification/amazingdata.md`); `.python-version` and the operator install runbook also select 3.14. No concrete 3.12 consumer or provider constraint was identified in the issue and current repository evidence.

Decision: Windows Python 3.14.x is the sole supported/reference application runtime. Ubuntu Python 3.14 remains a required CI-only cross-platform check, not a supported deployment target. This is a controlled application policy, not a claim that the package is a general-purpose library supporting all Python 3.14 patch/platform combinations.

## Bounded changes

- Remove Windows Python 3.12 from the required full CI matrix; keep required Windows 3.14 and Ubuntu 3.14 legs.
- Set `requires-python` to `>=3.14,<3.15`; set Ruff and mypy targets to Python 3.14; regenerate `uv.lock`.
- Align README, install runbook, provider doctor runbook, current execution plan, and the CI-matrix regression assertion.
- Mark the obsolete local Python 3.12 installation risk closed, with the qualification that the underlying uv issue was avoided by policy rather than repaired.
- Ruff 0.16.4 targets Python 3.14's PEP 758 exception syntax and requires mechanical formatting in 19 Python files (the exception syntax in 18 files and line wrapping in the CI-matrix regression test) for the repository-wide formatter gate. These are format-only changes; no control flow or data behavior is intended to change.

Historical CI reports and historical task records remain unchanged. No provider calls, SDK/credential access, Formal or Production run, new compatibility framework, or data-domain work is included.

## Validation status (2026-09-24)

Local validation on Python 3.14.6:

- `uv run pytest -q`: exit code 0; full suite reached 100% with no failures.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS; all 248 Python files formatted.
- `uv run mypy`: PASS; 112 source files.
- `uv lock --check`: PASS; 42 packages resolved.
- `uv pip check`: PASS; 57 installed packages compatible.
- `git diff --check`: PASS.

Still required before Issue #85 can close:

- required exact-head GitHub CI green on Windows 3.14 and Ubuntu 3.14;
- scheduler/Owner acceptance through the normal PR workflow.

The GitHub PR's latest-head checks are the live CI source of truth. Do not infer acceptance for Issue #86 or any new data-domain work from this runtime cleanup.
