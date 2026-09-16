# Issue #73 Stage B remediation — 2026-09-16

## Scope and disposition

Baseline: `main@22c42a72e222d9b6f6519095fb641a4adb190e12` (PR #74 merge).
Only `2020-01` Development and `2026-01` Holdout were processed.

Disposition: **both representative months PASS; evidence ready for PM review**.
This is not authorization for any other month, 78-month backfill, Production, or
a later project phase.

The post-change full closure was replayed offline from previously retained,
ingestion-time hash-anchored AmazingData exchanges. It made **zero SDK/provider
network calls**. The replay re-evaluated completeness under the current code,
created new bounded retained captures/receipts in isolated local outputs, and
completed coverage, materialization, reader, idempotency, and conflict checks.
It is not a claim of a new online vendor re-fetch. Raw inputs, local ledgers, and
materialized artifacts remain ignored/local and are not part of this report.

## Minimal code changes

- Reuse the existing verified AmazingData security-master / normalized
  `stock_basic.LISTDATE`; no new market-data source and no hard-coded IPO dates.
- For exact-session code-list membership, `session < LISTDATE` is
  `NOT_APPLICABLE_SESSION`, not suspension. `session >= LISTDATE` remains under
  existing status/bar semantics. Missing or malformed LISTDATE does not resolve
  an otherwise unresolved pair.
- Bump the existing completeness/applicability rule versions to v3. Only dates
  used to exclude pre-listing pairs are included in the existing serialized,
  receipt-bound completeness evaluation; no separate persistent hash dimension
  was introduced.
- `finalize_capture()` now rejects a verified projection whose daily-row count,
  month date scope, or research split differs from the retained capture. It
  continues to bind the original raw root, verify retained bytes/tamper evidence,
  and enforce `retrieved_at_utc <= pit_as_of`. The mismatch regression test proves
  finalization makes no provider calls.

## 2020-01 — Development PASS

The five previously unresolved pairs are pre-listing according to the existing
verified provider identity input:

| Provider symbol | Session | AmazingData LISTDATE | Classification |
|---|---|---|---|
| `002971.SZ` | 2020-01-02 | 2020-01-13 | `NOT_APPLICABLE_SESSION` |
| `300813.SZ` | 2020-01-03 | 2020-01-14 | `NOT_APPLICABLE_SESSION` |
| `300815.SZ` | 2020-01-14 | 2020-01-23 | `NOT_APPLICABLE_SESSION` |
| `002975.SZ` | 2020-01-16 | 2020-02-05 | `NOT_APPLICABLE_SESSION` |
| `300816.SZ` | 2020-01-17 | 2020-02-10 | `NOT_APPLICABLE_SESSION` |

- Required/returned pairs: `59,930 / 59,930`; missing, extra, unresolved, and
  structural errors: `0`.
- The existing raw capture had 38 anchored metadata records. Under LISTDATE
  semantics, the replay needed 36 retained typed-facade responses; the two old
  pre-listing snapshot probes were not repeated. Provider SDK/network requests:
  `0`.
- Capture retrieval time: `2026-09-16T06:52:27.237165Z`; verified projection
  PIT: `2026-09-16T14:55:53.292594Z` (after retrieval).
- Receipt `amazingdata-history-receipt-d169ebb9116fc485a309c706b5e56597` and
  retained-capture replay: `PASS`. Authoritative coverage and one bounded
  Development materialization: `PASS`.
- Ordinary reader returned `59,930` rows; idempotent replay: `PASS`; changed
  content was rejected: `PASS` (`MaterializationConflictError`).
- Materialization ID:
  `rhm-23e5d7f7c5733acdeb2acbdbd108d41018f4fb297d201771384a0f61cc927b0a`.

## 2026-01 — Holdout PASS

- Required/returned pairs: `103,454 / 103,454`; missing, extra, unresolved, and
  structural errors: `0`. Classifications: `SUSPENSION_NON_TRADING=215`,
  `NOT_APPLICABLE_SESSION=51`.
- All 24 retained exchange records were hash-verified and replayed through the
  typed facade. Provider SDK/network requests: `0`.
- Capture retrieval time: `2026-09-16T11:32:54.572962Z`; verified projection
  PIT: `2026-09-16T15:03:17.173680Z` (after retrieval).
- Receipt `amazingdata-history-receipt-1a9856933452b5b67a58a830b17a8ab0` and
  retained-capture replay: `PASS`. Authoritative coverage and one bounded
  Holdout materialization: `PASS`.
- Ordinary reader returned `103,454` rows; idempotent replay: `PASS`; changed
  content was rejected: `PASS` (`MaterializationConflictError`).
- Materialization ID:
  `rhm-07ae2edc9af328710d9191728cbb3ee7efa57447a22b49094d3fb91e26db35a0`.

## Local verification and PM review

- Focused Issue #73 regression tests: `61 passed`.
- Full offline test suite: `1,868 passed, 3 skipped`.
- `ruff check src tests`: passed; `ruff format --check src tests`: 216 files
  already formatted.
- `mypy src/ashare_state`: 108 source files, no issues.
- Exact-head GitHub CI is dynamic and must be checked on Draft PR #75; it is not
  cached here.

PM review requested for the two-month evidence, provider-owned LISTDATE
applicability semantics, and finalization mismatch guard. No follow-on work is
authorized until separately decided. In particular: no other month, 78-month
backfill, Formal B1-B7/Production, BSE/index, CR-5/R2, Golden/H1, global
baseline, or strategy/portfolio work.

No credentials, profile/account identifiers, IP/port values, SDK/runtime
details, raw payloads, local database paths, or materialized files are included.
