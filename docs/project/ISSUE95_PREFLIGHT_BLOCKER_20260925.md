# Issue #95 preflight blocker — missing governed daily-bar base (2026-09-25)

## Disposition

**STOP / BLOCKED before Provider capture.** No Issue #95 status/limit Provider request has been made. The accessible project workspaces do not contain the retained inputs required to build the issue's governed security/session denominator or Canonical identity bridge.

## What was checked

- The local Issue #90 worktree was clean and fast-forwarded to the verified GitHub `main` merge commit `6907f91d303258bd9a50fc0a27627402e2e2cdbb`.
- Its configured data root is repository-local `data/`. That directory contains Golden test data only; `data/spike/` is absent. No retained status/limit captures, receipts, normalization outputs, Canonical results, or Issue #76 daily-bar/identity artifacts were found.
- Issue #76 records the ignored retained root as `data/spike/issue76_history_build_20260916/`; its later execution report also identifies `data/spike/issue76_c1_migration_listdate_20260923/`. Neither path exists in the accessible Issue #90 worktree. The expected sibling Issue #76 worktree is also absent; the only mounted sibling worktrees are Issue #82 and Issue #90. A separate older Issue #76 audit checkout was inspected and contains source files but no `data/spike/`.
- GitHub's `issue76/history-build-20260916` and `issue80/daily-bar-20260923` trees contain no Parquet/database fact files. The corresponding retained-history CI runs (#752, #742; plus the skipped controlled run #258) expose no downloadable Actions artifacts. The bulk evidence was explicitly kept out of GitHub.
- The SDK/runtime and existing status/limit DTO, normalization, and Canonical contracts were inspected offline. This does not substitute for the missing per-security/date identity and session denominator.

## Why capture cannot safely start

Issue #95 requires reconciliation against the previously accepted 2020-01..2026-06 daily-bar universe, identity history, and exchange sessions. Without those local artifacts, the task cannot establish which security/date pairs are expected, map provider symbols to governed `security_id` values, or distinguish an applicable empty response from a non-applicable one.

Issue #95 authorizes new capture from `InfoData.get_history_stock_status` only. Re-fetching daily bars, historical code lists, or calendars would exceed this issue's request scope. In addition, the latest Issue #76 scheduler checkpoint requires `provider_calls=0` and no reacquisition while the existing retained roots are reconciled. That current control-plane decision supersedes any assumption that missing local files may simply be fetched again.

Using a current-only symbol list, inferring identities, or treating empty responses as negative facts would violate the fail-closed rules.

## Required management action

Before any Issue #95 Provider request:

1. Restore/mount the **existing** Issue #76 retained run root(s) at an accessible local path with original manifests/seals intact; then reconcile the roots read-only as required by Issue #76.
2. If the existing roots cannot be recovered, the Owner/PM must explicitly supersede the current Issue #76 no-reacquisition checkpoint in a separately tracked governance task before any fresh base-data acquisition. No such superseding authorization is currently recorded.

After the existing base inputs are accessible and pass their original seal/replay checks, resume Issue #95 with its read-only verification, safe batch selection, and month-bounded SH/SZ capture. Do not request or record any password, endpoint, account identifier, token, or raw private payload in GitHub.

## Evidence references

- [Issue #95 acquisition scope](https://github.com/GeeCeeSneaker/A-share-analysis/issues/95)
- [Issue #76 retained-history execution report](ISSUE76_78_MONTH_EXECUTION_20260924.md)
- [Issue #76 no-reacquisition scheduler checkpoint](https://github.com/GeeCeeSneaker/A-share-analysis/issues/76#issuecomment-5795658415)
- [Issue #76 retained-identity STOP checkpoint](https://github.com/GeeCeeSneaker/A-share-analysis/issues/76#issuecomment-5803824753)
- [Current Issue #90 semantic closure record](../provider_verification/issue90_status_key_semantic_closure.md)
