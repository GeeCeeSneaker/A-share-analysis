# Issue #84 — TGW credential-store acceptance checkpoint

**Status:** controlled Windows credential-store and fresh-process T1 acceptance passed. Exact-head GitHub CI run #761 passed on head `07be642d81598f9873cf2def4e97c82a08910bcc`. PR #87 is Ready for review, not merged. GitHub PR checks are the live source of truth after any later head update; the latest head must be green before merge. Independent review is pending; Issue #84 remains open. This is not authorization for Production B1–B7.

## Implementation and controlled T1

- Code-bearing commit: `78afd93e291a162348bdcd613ef55ebc2ee98a4e`; PR: [#87](https://github.com/GeeCeeSneaker/A-share-analysis/pull/87), Ready for review, not merged; base: `main@b75636c57caffd0dbdc9d5a2c40988734daa2c34`.
- The one-time hidden bootstrap stores the password with `keyring.backends.Windows.WinVaultKeyring` in the current Windows user's Credential Manager. A presence-only lookup confirmed the entry without displaying or copying its value.
- After the bootstrap process exited, a separate new process ran `production_account_bootstrap.py` with the process-level `TGW_PASSWORD` override removed. Exit code was 0; runtime verdict `RUNTIME_ACTUAL_LOAD_VERIFIED`; network `REACHABLE`; authentication `YES`; query readiness `YES`; SDK stderr observed `false`.
- The scrubbed T1 status is `FROZEN_IDENTITY_MATCH_REQUIRES_REVIEW`. This is an authenticated/query-ready result, not final identity approval. The generated report remains only at the ignored local path `data/spike/results/production_account_bootstrap.json` and is not committed.

## Local verification

- Focused credential, T1, runner, and trust-boundary tests passed.
- Full repository pytest: **1930 passed, 9 skipped**.
- Ruff lint, Ruff format, Mypy (**112 source files**), and `git diff --check` passed.
- The retained local SDK wheels were installed offline (`AmazingData 1.1.9`, `tgw 1.0.9.2`); `uv pip check` reported all 57 installed packages compatible.
- GitHub exact-head CI run [#760](https://github.com/GeeCeeSneaker/A-share-analysis/actions/runs/35963089000) passed on `7dd416e0187ad07b0125905ab20194f619de5079`: Ubuntu/Python 3.14, Windows/Python 3.12, and Windows/Python 3.14 required jobs all succeeded. Because this record is being corrected in a later commit, the PR's resulting latest head still requires a fresh green check.
- `.env` remains gitignored and was not staged. It contains only local non-secret settings; no SDK wheel, local T1 report, account identifier, endpoint, password, token, or raw Provider output is included in Git.

## Remaining gates and limits

- Obtain independent review before declaring Issue #84 complete. Before any merge, verify green GitHub checks for the then-current PR #87 head; GitHub's PR checks are authoritative after subsequent head updates. Issue #39 Production remains unauthorized until review passes.
- No Production B1–B7 run, historical data reacquisition, or retained-data mutation was performed.
