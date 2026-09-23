# Issue #76 — 2022-09 governed-identity blocker (2026-09-23)

## Disposition

**STOP(BLOCKED) at 2022-09.** The C1 event-eligibility contract was approved by the PM/Owner in Issue #76 comment [#5795151285](https://github.com/GeeCeeSneaker/A-share-analysis/issues/76#issuecomment-5795151285). Its approved offline, month-bounded migration was started without provider calls. The first new blocker is not a daily-bar coverage or C1 event-time failure: 34,844 returned daily-bar pairs cannot be assigned a governed `security_id` under the existing fail-closed identity policy.

Do not skip these pairs, infer identities from a code prefix, borrow identity dates from another month, or silently weaken the identity contract. Wait for an Owner/PM decision backed by authoritative listing-date facts or a specifically authorized identity source/policy.

## Verified migration checkpoint

- Sequential Canonical migration passed **32/78 months**, 2020-01 through 2022-08, with **2,758,510** selected rows. Every completed month has exact selected/decision coverage and `provider_calls=0` for this offline migration process.
- The next month, 2022-09, has retained capture/coverage PASS: 100,844 returned daily-bar rows, 4,828 provider symbols, and 21 trading sessions. No provider request was made to investigate this stop.
- Canonical run `c608860c-59b3-5c0f-9428-b4a6a177cc8c` ended `BLOCKED`: 66,000 selected rows and one blocking `IDENTITY_MISSING` finding. The ledger detail records `count=34844` and `identity_missing_max=0`; in other words, none of those rows was allowed through on a bare-symbol fallback.
- The migration runner stopped at that first failed month. No later month was migrated. A 78-month archive Snapshot/ReadModel publication, full-reader gate, final idempotent replay, and changed-content-conflict gate are therefore **not complete**.

## Reproducible identity diagnosis

Using the exact three retained, hash-verified normalized outputs for 2022-09, the current production `IdentityBridge` was re-run offline against the actual daily-bar `(provider_symbol, trade_date)` pairs and the monthly `hist_code_list` plus `stock_basic` rows. This independently reproduces all 34,844 missing pairs:

- The pairs belong to **1,669** provider symbols.
- For every affected symbol, a `hist_code_list` row exists but its `list_date` is null; there is no corresponding `stock_basic` row in this month's retained input set.
- With no valid listing date, the current bridge correctly refuses to mint a governed identity. The returned market bars are present; their identity is unresolved.
- The file [`ISSUE76_2022-09_IDENTITY_MISSING_PAIRS.csv`](ISSUE76_2022-09_IDENTITY_MISSING_PAIRS.csv) is a derived diagnostic index, not provider payload. It lists each affected symbol and a bitmask of its exact missing sessions (1,669 symbol rows; 34,844 symbol/date pairs). It contains no prices, volumes, credentials, raw payloads, or database files. In `missing_session_mask_hex`, bit 0 is the first date below, bit 1 the second, and so on; a set bit means that symbol/date pair is unresolved:

  `2022-09-01, 2022-09-02, 2022-09-05, 2022-09-06, 2022-09-07, 2022-09-08, 2022-09-09, 2022-09-13, 2022-09-14, 2022-09-15, 2022-09-16, 2022-09-19, 2022-09-20, 2022-09-21, 2022-09-22, 2022-09-23, 2022-09-26, 2022-09-27, 2022-09-28, 2022-09-29, 2022-09-30`.

Input lineage (request IDs are included only to identify the already-retained local evidence; no credentials or network addresses):

| Dataset | Rows | Retained request ID | Normalized manifest SHA-256 | Main Parquet SHA-256 |
|---|---:|---|---|---|
| `daily_bar` | 100,844 | `1a0bacac-5326-4a37-8edc-9b91bffe6174` | `2be2289adabd0ca49cc02fbe670288dff354950e4bf50ff80058f2ff99f5c9aa` | `e66dc91394b7d5cccc037152af73db95449bdb2797b72773e7821c7f3ec1d64b` |
| `hist_code_list` | 4,829 | `51fe8f9a-e4fd-4fd6-85fe-6c89dac2b958` | `0a4b35df23d04cbc194a729155f84c9c4ccee2be4e2150ce09d630f5b97d3a11` | `584dbfaa47dc6b70fb3e22f7076b582dc6b2b428791221945a277ed2f01809bb` |
| `stock_basic` | 3,159 | `49f16401-d5c1-4484-b7d8-be20d19062fa` | `4b5a2b02dfe35e582d7fd3da83452e09c31850900d779f06bf2d30bd7f799f71` | `d05927e839d143010fd0ffc6b264eb4b1bde407ff0fd434a27efb785b0ec8e94` |

The normalized manifests and output bytes were verified against their recorded hashes before diagnosis. The CSV SHA-256 is `e21963940a2f6e7bd44a941a100419626ec681c4f0a418f442b77d3bc42a1e56`.

## Required next decision

The project manager/Owner must choose and document one of these before migration resumes:

1. Supply/authorize authoritative listing-date identity facts for the exact affected symbols, with provenance and an explicit PIT rule; or
2. Identify and authorize a specific authoritative identity source and its bounded use for this migration; or
3. Keep the current identity contract and formally record that the 2022-09 migration cannot proceed from the retained evidence.

Do not resume the month loop until a decision is recorded. Preserve the existing 32 passing monthly outputs and retained source root; do not re-fetch provider data or mutate either retained root. After a decision, re-run only the bounded 2022-09 offline month first, require exact identity/coverage PASS, and then continue sequentially.

## Scope separation

This blocker is independent of the approved `DAILY_BAR_EVENT_ELIGIBILITY_V1` rule and does not invalidate the 32 completed months. It also differs from the previously documented memory guard: this run stopped on a reproducible identity finding before any archive Snapshot publication. Local regression tests for the C1 and archive-Snapshot changes passed, but passing unit/integration tests do not close the 78-month migration or its final acceptance gates.
