# Issue #76 — 78-month retained-history execution (2026-09-24)

## Disposition

**Offline data-plane execution PASS: 78/78 months and the archive Snapshot/reader/replay gates passed.** Exact-head GitHub CI and final Owner/PM acceptance remain pending; PR #77 stays Draft and this is not a merge/production authorization.

The execution followed Issue #76's month-bounded path and the C1 rule approved in Issue #76 comment [#5795151285](https://github.com/GeeCeeSneaker/A-share-analysis/issues/76#issuecomment-5795151285). The 2022-09 retained-identity remediation stayed within the one narrow path authorized in [comment #5803824753](https://github.com/GeeCeeSneaker/A-share-analysis/issues/76#issuecomment-5803824753).

## 78 monthly Canonical results

| Gate | Result |
|---|---:|
| Window | 2020-01 through 2026-06, inclusive |
| Month-bounded Canonical partitions | 78/78 PASS |
| Daily-bar rows | 7,442,987 |
| Monthly selected/decision/returned equality | 78/78 |
| Unresolved / missing / extra / structural errors | 0 / 0 / 0 / 0 in every month |
| Exact Canonical replay | 78/78 PASS |
| Provider calls by this offline migration process | 0 |
| Canonical migration peak RSS | 1,651,478,528 bytes (1,574.97 MiB) |

Each month was processed sequentially from its exact retained monthly input set. Historical capture metadata may record calls made during the earlier authorized acquisition; those are not calls made by this migration or archive-publication process. Every month used retained replay evidence. The compact per-month receipt, coverage-basis, source-snapshot, Canonical manifest, partition seal, counts, source-vintage, and replay fields are in [`ISSUE76_78_MONTH_EXECUTION_SUMMARY_20260924.json`](ISSUE76_78_MONTH_EXECUTION_SUMMARY_20260924.json).

## Resolved 2022-09 identity gap

The retained 2022-09 `stock_basic` raw response had 3,159 rows and ended before the exact 1,669-symbol blocker tail. Raw and normalized rows agreed; this was not an internal normalizer drop. Read-only comparison across all retained AmazingData `stock_basic` captures found exactly one consistent `LISTDATE` per affected symbol, with raw and normalized facts agreeing and no cross-vintage conflicts.

The selected, already-retained Owner-approved source was the 2023-02 `stock_basic` request. Only the 1,669 exact target `(provider_symbol, LISTDATE)` pairs entered identity minting; mutable fields were excluded. Every LISTDATE was no later than the first retained target daily bar. The source request's real retrieval/source-vintage time remains explicit; no claim is made that it was the vendor's contemporaneous 2022 publication.

| Seal | Value |
|---|---|
| Target month / result | 2022-09 / PASS, 100,844 rows and decisions; unresolved 0 |
| Supplemental fact count / fact-set SHA-256 | 1,669 / `5c30ab57cf47c9d72d47174f51f40869667788f995416b0e8f12e7ef8139eeb7` |
| Retained request / normalization run | `e0979f16-5c56-4fc9-bd66-1b934e30e771` / `e478b724-8040-52f2-99a2-d7c0de7b8f9c` |
| Raw payload SHA-256 / CR-2 raw-evidence hash | `403e2d0444e6127d1ad97acc3060ad38bdaf2c0cc112997ab4424285749d13eb` / `79ebc807ac89b723ca948b13ae009f9028847476b73894f7dd67bf50b7f4cc8b` |
| Normalized manifest SHA-256 / output SHA-256 | `228110892e8d8976cd7f6ee6e284b2344ab8ba791df82a2ddb0840932f30c660` / `65d8aceddcd10242f92cf85c947c8df5d7b21df97bc6f6c426ee7d6f136770d2` |
| True source-vintage timestamp | `2026-09-18T00:44:51.537152+00:00` |
| 2022-09 retained source-snapshot cutoff | `2026-09-21T11:47:33.839751+00:00` |
| 2022-09 Canonical run | `d2c0a604-f0eb-5d7e-8f5e-b0ef059d565d` |

The failed 66,000-row 2022-09 attempt in the prior derived migration root was preserved. A new isolated output root was used because the prior BLOCKED Canonical run had already sealed a different partial partition and the immutable partition writer correctly refused in-place logical-fact replacement. The retained source root was not modified.

## Archive Snapshot and ordinary reader

| Gate | Result |
|---|---|
| Snapshot contract / ID | `snapshot-daily-v3` / `49ae51fe-1394-502a-88bc-5c3b4fb2d487` |
| Snapshot manifest SHA-256 | `327d5bfcb61004136a8a4ad4015c9fb0f9be6a23da6f6adee7de16f848d527f3` |
| Canonical source count / source-set hash | 78 / `e5d2babbe3013db44c7d837ebd08af8fba3693a25e8b181ae753f62aaa307601` |
| Snapshot partitions / rows | 78 / 7,442,987 |
| Deep verification / exact Snapshot replay | PASS / PASS |
| Ordinary `rm_daily_bar` relation | External DuckDB `VIEW` |
| Ordinary reader coverage | 78 months, 78 Canonical source runs; exact per-month row-count match |
| Reader date range | 2020-01-02 through 2026-06-30 |
| Snapshot fact Parquet copy | No |
| Archive Snapshot/ReadModel peak RSS | 927,584,256 bytes (884.61 MiB) |
| Provider calls by this publication process | 0 |

The rule `DAILY_BAR_EVENT_ELIGIBILITY_V1` is the approved session-close event-eligibility convention, not a historical provider-publication-time assertion. `source_vintage_as_of` remains independently sealed and in this archive is `2026-09-21T11:12:09.149827+00:00`.

## QA and remaining acceptance

- Full local `pytest -q`: exit code 0.
- Ruff check and format check for the changed execution/identity/event/data-plane files: PASS.
- Mypy: `Success: no issues found in 111 source files`.
- Explicit changed-closed-month fail-closed test: PASS.
- Explicit Snapshot exact-idempotent replay and conflicting-residue rejection tests: 2 PASS.
- Supplemental identity projection tests: 4 PASS, including mutable-field exclusion and missing/duplicate/conflicting fact rejection.

The migration output, copied normalized evidence, Canonical/ReadModel Parquet, and DuckDB ledgers remain in the ignored local `data/spike/issue76_c1_migration_listdate_20260923/` directory and are not included in this report or proposed Git commit. No credentials, network endpoints, raw provider payload, or bulk OHLCV facts are committed.

**Publication and CI checkpoint (2026-09-24 UTC):** evidence commit `f469faef1d4f2fa476e784f47823d0b74feae330` triggered CI #750; Ruff lint passed, but Ruff format failed only on the migration runner and identity test, so Mypy/pytest were skipped. Formatting-only follow-up `195e0d2806f0ef0837f25fed1c0f628a97aa4c5d` removed the extra trailing blank lines. Exact-head CI #751 for that follow-up passed all three matrices (Ubuntu 3.14, Windows 3.12/3.14), including Ruff lint/format, Mypy, full pytest, and SDK-absence checks; controlled GT-H3B run #257 was skipped by scope. Final Owner/PM acceptance remains pending. Keep PR #77 Draft.

