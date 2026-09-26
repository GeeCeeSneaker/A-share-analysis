# Issue #95 — upstream coverage and execution checkpoint

## Current disposition — 2026-09-26

Issue #95 remains **ACTIVE / not ready for independent PASS review**. The 78-month month-bounded capture and coverage reconciliation completed, but the Canonical run and exact replay did not. The isolated runner was stopped during the Canonical stage when memory rose rapidly; no second bulk attempt was made.

| Coverage state | Months | Scope |
|---|---:|---|
| `COMPLETE` | 16 | 2025-03 through 2026-06 |
| `PARTIAL_UPSTREAM_COVERAGE` | 62 | 2020-01 through 2025-02 |

Per requested domain, expected pairs = **7,461,248**, returned pairs = **7,459,685**, and missing pairs = **1,563**. These are the same `(security_id, trade_date)` gaps in `security_status` and `limit_price`; missing facts remain unknown and are not synthesized. All monthly structural-error, duplicate-key, and unexplained-extra counts are zero.

The run manifest records 3,593 Provider calls, 1,927 monthly normalization runs, and `current_mapper_replay_verified=true` (68 months reused and 10 reconstructed through the current mapper). Its coverage receipt contains all 78 months. Read-only validation confirmed the receipt hash, every missing-key-set hash and count, uniqueness of missing keys, and `expected = returned + missing` for all months. Exact key files and raw Provider evidence remain in ignored local storage; none are committed.

## Canonical and memory outcome

No Canonical result was accepted: the run manifest has `canonical=null`, and a read-only query of the isolated ledger found zero committed Canonical run records. No selected-artifact manifest or exact Canonical replay was produced. The current runner manifest was last saved as `RUNNING`; the local `report.json` is stale from an earlier attempt and does not describe this checkpoint. Both are preserved as-is with the isolated run evidence.

During the Canonical phase, process RSS rose from approximately **8.25 GiB to 9.91 GiB in 10 seconds**. The configured 16 GiB guard was not reached; available host memory at the final sample was about 32.74 GiB. Because RSS was rising sharply and the existing path could continue materializing the full selected row set, the process was interrupted once at the operator's memory stop condition. This is not a Provider or data-quality failure, and no retry was started.

Code inspection found that the existing Canonical path materializes candidates and selected rows in Python lists, constructs an in-memory Parquet buffer, and the consumption verifier converts the selected Parquet frame to Python dictionaries. These are confirmed implementation characteristics and a plausible explanation for the growth; no profiler or stack snapshot was collected, so the precise allocation source is **not proven**. The required follow-up is a bounded/streaming Canonical build and verification path that preserves current row-selection, seal, and exact-replay semantics. Do not resume the 78-month run until the project manager has reviewed that memory remediation, consistent with the no-repeat instruction.

The process was interrupted before it could write a terminal report. The last manifest hash is `cd220333eac51c4b73f46e2c9c29f1d62504281f8009472ec4474a0582d16ab1`; the 78-record coverage receipt hash is `962554a3df0f63d9f23f8d5b45b525f4e3beb6bb4ac861740788fa053a871d46`. The DuckDB WAL/owner-lock sidecars are retained; no cleanup or write-mode recovery was attempted.

## Historical upstream-gap diagnostic

The earlier 62-month diagnosis remains relevant. Exact-session membership alone does not explain the gaps: 1,238 missing pairs were present in the exact-session universe and 325 absent. The gaps were 1,470 SZ and 93 SH; all were more than 250 sessions after listing, and none was within 20 sessions of a known delisting date. Seven one-symbol/same-day status probes returned successful zero-row responses; three of seven adjacent-day controls returned rows. Of five bounded daily-bar checks, two had an exact same-day bar and three had no bar. This supports a reproducible upstream coverage/applicability limitation, not a safe denominator exclusion rule.

Per the latest Issue #95 decision, zero upstream missing pairs are **not** required for PASS. The verified returned facts may be Canonicalized; absent status/limit values must remain unresolved/NULL. Status-dependent research must exclude or explicitly flag those observations; daily-bar-only research is not blocked. No Provider explanation or broad re-pull is required.

## Security and QA

One SDK-generated session field appeared in an earlier terminal stream before process-wide output quarantine was installed. Its value is intentionally omitted and was not committed. Process-level stdout/stderr quarantine now keeps only safe progress output visible; a subprocess regression test confirms native file-descriptor writes are suppressed. Treat the prior provider session as exposed and rotate/revoke the affected credential/session after this task.

Local Python 3.14.7 checks on the current code changes: Ruff lint passed, Ruff format check passed, and the focused Canonical/status/output-quarantine suite passed (**13 tests**). Full-repository tests and exact-head GitHub CI have not been run for this final local head. Do not claim overall acceptance or review readiness until the memory-bounded Canonical path, exact replay, and required CI are complete.
