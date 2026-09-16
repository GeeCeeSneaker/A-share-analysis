# CR-7 Issue #73 Stage B execution — 2026-09-16

> Status: **BOTH REPRESENTATIVE MONTHS STOP(BLOCKED) / EVIDENCE READY FOR DRAFT PR AND PM REVIEW**

## Scope and execution controls

Executed only the two months authorized by [Issue #73](https://github.com/GeeCeeSneaker/A-share-analysis/issues/73): `2020-01` (Development) and `2026-01` (Holdout). Each month used its own local attempt directory and DuckDB ledger. No state, raw capture, projection, or result was carried between months; the earlier Stage B raw data was not reused.

The account precheck succeeded. The official account was used only in local process memory; no credential, account/profile identifier, IP, port, SDK/runtime, raw payload, database, or materialized artifact is included in this report or Git. Code head was `f8a750b96f6d6fca4bc1996ba592a4d5dcfa4b48`.

| Month | Source input and verified projection | Completeness | Terminal result |
|---|---|---|---|
| 2020-01 Development | Canonical/Snapshot/ReadModel/projection: 59,930 rows; zero Canonical findings | 59,930 required and returned; 5 unresolved pairs | `STOP(BLOCKED)` before receipt |
| 2026-01 Holdout | Canonical/Snapshot/ReadModel/projection: 103,454 rows; zero Canonical findings | 103,454 required and returned; no missing, extra, unresolved, or structural errors | `STOP(BLOCKED)` at receipt construction: provider retrieval occurred 381.534241 seconds after projection PIT |

Machine-readable counts, IDs, hashes, rule versions, and blocker details are in the adjacent [JSON evidence](cr7_issue73_stage_b_execution_20260916.json).

## 2020-01 — Development

Source inputs normalized without quarantines: calendar `8,726/8,726`; monthly historical code list `3,769/3,769`; `stock_basic` `3,768/3,768`; daily bars `59,930/59,930`. The `stock_basic` count is one below the monthly code-list count; this is recorded as an observed difference, not asserted to cause the completeness blocker. Canonical selected all `59,930` rows with `0` findings. Snapshot, ReadModel, and `prepare_verified_projection()` succeeded; the projection spans `2020-01-02` through `2020-01-23` and is bound to the Development split.

The authoritative capture retained 38 metadata records: calendar 1, monthly plus exact-session code-list 17, historical status 1, daily kline 1, and exact-session snapshot 18. All 16 exact-session code-list requests matched the source calendar. Month completeness then returned:

- 3,769 securities × 16 sessions; required and returned bar-pair sets both contain 59,930 pairs and have the same hash.
- Missing `0`, extra `0`, structural errors `0`; `POSITIVE_TRADE_COUNT_ACTIVE=16`, `SUSPENSION_NON_TRADING=181`, `NOT_APPLICABLE_SESSION=188`, `UNRESOLVED=5`.
- The evaluator persists aggregate classification counts and required/returned set hashes, not the identities of unresolved pairs. Accordingly, this public evidence records the exact blocked count and month scope without inventing pair identities.

The five unresolved applicable security-session pairs fail the existing fail-closed rule. They were not converted to suspended/non-trading or silently removed. No authoritative receipt/catalog, coverage basis, bounded materialization, ordinary-reader proof, idempotency proof, or conflict proof was issued or started.

## 2026-01 — Holdout

Source inputs normalized without quarantines: calendar `8,726/8,726`; monthly historical code list `5,186/5,186`; `stock_basic` `5,186/5,186`; daily bars `103,454/103,454`. Canonical selected all `103,454` rows with `0` findings. Snapshot, ReadModel, and verified projection succeeded for the Holdout split, covering `2026-01-05` through `2026-01-30`.

The authoritative capture retained 24 metadata records: calendar 1, monthly plus exact-session code-list 21, historical status 1, daily kline 1. All 20 exact-session code-list requests were unique and matched the source calendar. Completeness **passed**: required and returned sets both contain 103,454 pairs with identical hashes; missing, extra, unresolved, and structural errors are all `0`; suspended/non-trading `215`, not applicable `51`.

Receipt construction then failed the existing PIT validator. The verified projection has `source_snapshot_as_of=2026-09-16T00:07:55.8489-07:00`; the latest retained provider response has `received_at=2026-09-16T00:14:17.383141-07:00` (request at `00:13:32.548373-07:00`). Thus the latest retrieval is **381.534241 seconds later** than the projection PIT. Current receipt validation explicitly requires `retrieved_at_utc <= pit_as_of`; the sanitized runner records exception class `CoverageBasisError` but not the exception message. The root condition is confirmed from the retained timestamps and that validator. This is a PIT/lifecycle blocker, not an account, schema, completeness, or data-volume failure.

No future-dated PIT, weakened validator, or synthetic receipt was used. No receipt/capture catalog, coverage basis, bounded materialization, ordinary-reader proof, idempotency proof, or conflict proof was issued or started.

## Review decisions required

1. **2020-01:** identify provider-owned status evidence, or an already-reviewed narrow rule, that can resolve the five applicable pairs. Until that evidence/rule is approved and the same bounded month is re-evaluated, preserve `STOP(BLOCKED)`.
2. **2026-01:** decide and authorize a PIT-consistent lifecycle that binds the retained provider evidence to a verified projection whose PIT is not earlier than retrieval, or explicitly revise the contract. Do not set a fabricated future `source_snapshot_as_of` and do not weaken the current `retrieved_at_utc <= pit_as_of` invariant.

These decisions do not authorize any additional month, backfill, Production/B1-B7, BSE/index, CR-5/R2, Golden/H1, baseline, or strategy work. The 78-month backfill remains unauthorized pending independent PM review of this Draft PR.

## Verification and retained data

The full offline suite passed on the unchanged code head before this evidence-only documentation update: `uv run --locked --offline pytest -o addopts= -q` → **1,857 passed, 3 skipped**. Exact-head PR CI remains required. This change adds evidence/docs only; no product code or test logic was changed.

All raw provider responses, local ledgers, source-input artifacts, and the one-off runner remain in ignored local storage. Only the adjacent sanitized JSON and this review report are intended for Git.
