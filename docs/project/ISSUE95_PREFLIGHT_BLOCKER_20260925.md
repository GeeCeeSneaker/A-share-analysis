# Issue #95 preflight blocker — missing governed daily-bar base (2026-09-25)

## Disposition

**STOP / BLOCKED before Provider capture.** No Issue #95 status/limit Provider request has been made. The project checkout does not contain the retained inputs required to build the issue's governed security/session denominator or Canonical identity bridge.

## What was checked

- The local Issue #90 worktree was clean and fast-forwarded to the verified GitHub `main` merge commit `6907f91d303258bd9a50fc0a27627402e2e2cdbb`.
- Its configured data root is the repository-local `data/`. That directory contains the Golden test data only; `data/spike/` is absent. No retained status/limit captures, receipts, normalization outputs, Canonical results, or Issue #76 daily-bar/identity artifacts were found in this checkout.
- The Issue #76 execution report confirms the 78-month daily-bar Parquet/ledgers were local ignored artifacts and were intentionally not committed to GitHub. GitHub therefore cannot supply the missing bulk facts.
- The SDK/runtime and existing status/limit DTO, normalization, and Canonical contracts were inspected offline. This does not substitute for the missing per-security/date identity and session denominator.

## Why capture cannot safely start

Issue #95 requires reconciliation against the previously accepted 2020-01..2026-06 daily-bar universe, identity history, and exchange sessions. With those local artifacts absent, the task cannot establish which security/date pairs are expected, map provider symbols to governed `security_id` values, or distinguish an applicable empty response from a non-applicable one.

Issue #95 authorizes new capture from `InfoData.get_history_stock_status` only. Re-fetching daily bars, historical code lists, or calendars would add Provider surfaces beyond that task's authorized request scope. Using a current-only symbol list, inferring identities, or treating empty responses as negative facts would violate its fail-closed rules.

## Required management action

Choose one before any Issue #95 Provider request:

1. Mount/provide the already accepted Issue #76 daily-bar, identity, and session artifacts at an accessible local path, with their original manifests/seals intact; or
2. Explicitly authorize a separately tracked recovery of those base artifacts under the Issue #76 constraints, including its bounded month-by-month execution and resource limits.

After the approved base inputs are available, resume Issue #95 with its read-only verification, safe batch selection, and month-bounded SH/SZ capture. Do not request or record any password, endpoint, account identifier, token, or raw private payload in GitHub.

## Evidence references

- [Issue #95 acquisition scope](https://github.com/GeeCeeSneaker/A-share-analysis/issues/95)
- [Issue #76 retained-history execution report](ISSUE76_78_MONTH_EXECUTION_20260924.md)
- [Current Issue #90 semantic closure record](../provider_verification/issue90_status_key_semantic_closure.md)
