# Issue #90 — history status key and routing semantic closure

**Disposition: BLOCKED (`STILL_UNRESOLVED`).** This record closes the code/testable boundary work only. It does not approve the provider capability, authorize history acquisition, or meet the issue's PASS gate.

As-of: 2026-09-24  
Base: `main@88eb9f15d8c8b8ec3b77d8919273a8f542b445ed`

## Decision

The eight rows reported without both `TRADE_DATE` and `MARKET_CODE` remain unclassifiable as either `PROVEN_NON_FACT` or `PROVEN_KEYABLE`. Their status/limit fields are evidence that the payload contains values, not proof that the rows are observations, summaries, or safe to discard.

The only defensible classification is `STILL_UNRESOLVED`. The runtime continues to reject rows without exact identity/date and now also rejects duplicate canonical `(provider_symbol, trade_date)` keys. There is no fallback, row-order inference, request-argument copying, imputation, or dropping.

## Evidence inspected

### Retained-artifact recovery check (2026-09-24)

The frozen receipt identifies request `3692c492-c5fc-431e-a8ec-6e7dcd69d0d0` and eight logical artifact URIs, but does not record the resolved absolute raw-data root or whether the run overrode `--raw-root`. The probe script's default is `data/spike/capability-closure-20260912/raw`; that directory is absent from the current checkout. A targeted recursive search for the exact filenames below was run in the active Codex workspace, the current Windows user-profile tree, and the `D:\` volume. No matching artifacts were found. This establishes unavailability in the searched environment, not loss or absence in any external retained store.

Because the files were unavailable, no Parquet content was read: no local content hash was verified, and anomaly count, source-row ordinal/position, documented status/limit null mask, and deterministic row fingerprint are **unavailable**, not zero or inferred. This local search does not establish that the artifacts are absent from external storage.

| Symbol | Expected artifact | Receipt SHA-256 | Local result |
|---|---|---|---|
| 002058.SZ | `002058_SZ.parquet` | `21b47f8785b3e23939c243764882de78a79e94d3fdf7a5b031dbc94bcd235a50` | NOT FOUND; hash and row summary unavailable |
| 002217.SZ | `002217_SZ.parquet` | `d2af1a3d3bf0f6e1da87ed7fdadfed43c2b18574fab1969b4eb704fa119d2f82` | NOT FOUND; hash and row summary unavailable |
| 002313.SZ | `002313_SZ.parquet` | `f7ac1a9475f044ee3cf1c7b33067a05b9f765331638b0180f80eb30f50c5b13e` | NOT FOUND; hash and row summary unavailable |
| 002366.SZ | `002366_SZ.parquet` | `129491e0602fa25887c1a8e3ac1193750bb50aca55fef49c764474e13649e3d1` | NOT FOUND; hash and row summary unavailable |
| 600382.SH | `600382_SH.parquet` | `d990fec880a04da5e6c6168b623eee0cb0b37de1afe8f1b0fd227e012a502c37` | NOT FOUND; hash and row summary unavailable |
| 688500.SH | `688500_SH.parquet` | `affdc7dd39d1d5339bfcf081f4b2d95b4dd9c87bb20633f292b7824908164392` | NOT FOUND; hash and row summary unavailable |
| 605499.SH | `605499_SH.parquet` | `107995d14f605eb8b7239ddbf378641a23adf06e1003aa5c7c4a2550dd15081f` | NOT FOUND; hash and row summary unavailable |
| 603887.SH | `603887_SH.parquet` | `7fd68baa8be33e1a3cb19cf15d86a10370852d5799e474fe00caaa010b48808f` | NOT FOUND; hash and row summary unavailable |

At the time of the retained-artifact search no Provider request was made. The scheduler later explicitly authorized the two bounded diagnostics below; their results supersede only that historical statement, not the fail-closed semantic conclusion.

### Scheduler-authorized live semantic diagnostics (2026-09-24)

Both requests used the existing provider facade and native response, before Canonical adaptation. Each was one provider attempt (`max_retries=0`); authentication succeeded with SDK 1.1.9. Only sanitized counts, requested-symbol table binding, null masks, positions, and SHA-256 row fingerprints were emitted. No raw payload was persisted.

1. **Exact historical request replay:** the same eight symbols listed below; `begin_date=19900101`, `end_date=20991231`, `is_local=False`. Provider status `OK`; 8 keyed tables, 20,710 rows total. Seven rows lacked both `TRADE_DATE` and `MARKET_CODE` (7 missing each); all seven were the final row of their returned symbol table. The response table key exactly matched its requested symbol in all eight tables.
2. **One past-only boundary comparison:** same eight symbols, same start and `is_local=False`, with only the end changed to `20260831` (no future-bearing date bound). Provider status `OK`; 8 keyed tables, 20,566 rows total. The same seven double-missing rows reappeared as each table's final row. Their per-symbol row fingerprints exactly matched the exact-replay fingerprints below. Thus a 2099 future upper bound is **not necessary** for the anomaly; this does not distinguish long-range/pagination behavior from a historical structural row or establish row meaning.

| Requested symbol | Exact replay rows / anomalous row ordinal | Past-only rows / anomalous row ordinal | Row SHA-256 (same in both calls) |
|---|---:|---:|---|
| 002058.SZ | 3,097 / 3,096 | 3,079 / 3,078 | `d5645147d15635ff8b6105def8b343865a0dd77ea280ddb002b0067f25a3eb31` |
| 002217.SZ | 3,097 / 3,096 | 3,079 / 3,078 | `7a87baca774b8f68a384661175d125a6f630429531b8f44d8ab6b5d75915c596` |
| 002313.SZ | 3,097 / 3,096 | 3,079 / 3,078 | `d5645147d15635ff8b6105def8b343865a0dd77ea280ddb002b0067f25a3eb31` |
| 002366.SZ | 3,097 / 3,096 | 3,079 / 3,078 | `d5645147d15635ff8b6105def8b343865a0dd77ea280ddb002b0067f25a3eb31` |
| 600382.SH | 3,097 / 3,096 | 3,079 / 3,078 | `d5645147d15635ff8b6105def8b343865a0dd77ea280ddb002b0067f25a3eb31` |
| 688500.SH | 1,505 / 1,504 | 1,487 / 1,486 | `89ac63d4edf5130225b92cdcc68e9c0e5b204547c0cfd8f463debb1063f4f285` |
| 605499.SH | 1,296 / none | 1,278 / none | — |
| 603887.SH | 2,424 / 2,423 | 2,406 / 2,405 | `d5645147d15635ff8b6105def8b343865a0dd77ea280ddb002b0067f25a3eb31` |

For each anomalous row, the non-null mask was `IS_ST_SEC`, `IS_SUSP_SEC`, `IS_WD_SEC`, `IS_XR_SEC`, `PRICE_HIGH_LMT_RATE`, and `PRICE_LOW_LMT_RATE`; `HIGH_LIMITED` and `LOW_LIMITED` were null. These are presence bits only; no values were emitted. Row ordinals are zero-based. The repeated table-tail position and masks generate a structural hypothesis, but are not an authoritative Provider definition. Although the response table key identifies the requested symbol, the row itself still has no trade date, so it cannot form `(security_id, trade_date)`.

**Conclusion remains `STILL_UNRESOLVED`.** Do not drop or key-fill these rows and do not weaken the adapter. The one allowed boundary comparison is complete; no further probing is justified absent a Provider/SDK contract. The exact-replay anomaly branch applied, so the conditional 2020-01 monthly check for a non-reproduction was not run. No history acquisition, BSE activation, capability promotion, or Formal B1–B7 occurred. The remaining unblock is a written AmazingData/SDK explanation that classifies this exact returned-row shape; otherwise keep Issue #90 blocked.

1. The issue's frozen receipt and scrubbed records:
   - `docs/provider_verification/capability_closure_20260911.json` records the 8-symbol, 1990-01-01–2099-12-31 response (20,638 rows), aggregate missing-date count, per-symbol table row counts, hashes, and raw artifact URIs.
   - The receipt does **not** preserve the affected row bodies, their dates/field values, or which exact symbols contain the eight rows. It stores logical URIs rather than a resolved filesystem root. The probe script defaults `--raw-root` to `data/spike/capability-closure-20260912/raw`, but the receipt does not record whether that default or an override was used. The expected files are unavailable in the searched local environment; GitHub cannot provide ignored local artifacts.
   - `docs/provider_verification/remaining_capability_truth_20260912.json` independently restates the 8/20,638 count and `STILL_UNRESOLVED` status.
2. The local AmazingData 1.1.9 SDK manual, section 3.5.2.10 (`get_history_stock_status`, PDF pages 17–18), lists `code_list`, `local_path`, `is_local`, `begin_date`, and `end_date`, plus returned status/limit columns. It does not define the semantics of rows missing both keys, a maximum batch size, response-to-request one-to-one binding, or the meaning of an empty response. No semantic docstring/contract was present in the inspected SDK surface.
3. Existing facade and adapter:
   - `get_history_stock_status_exchange(start_date, end_date, code_list)` forwards `begin_date=start_date`, `end_date=end_date`, `is_local=False`, and the caller's symbol list. It does not split batches or remap codes.
   - `canonical_status_view()` already fails closed when identity or date is missing. The response table name may be preserved as an observed symbol key by the existing adapter, but that cannot supply a missing trade date.
   - `month_completeness._status_rows()` already treats empty applicable coverage as unresolved and duplicate dates as structural errors.

The live calls above reproduced the shape but did not establish semantics. The retained raw artifacts remain unavailable, and no rule may be inferred from row order, null masks, or fingerprints.

## Frozen minimum routing boundary

| Item | Supported boundary | Limitation / rule for a later acquisition |
|---|---|---|
| Symbol argument | `code_list: list[str]`; SH/SZ exchange-qualified codes are forwarded verbatim. | No automatic symbol remapping. The current facade does not claim an SDK maximum batch size. |
| Date arguments | Facade accepts integer `start_date`/`end_date` and forwards them as SDK `begin_date`/`end_date`. | The manual does not specify whether bounds are inclusive or exclusive. Pass YYYYMMDD integer bounds, validate returned dates against the requested window, and do not claim inclusion semantics until confirmed. |
| Remote/local mode | The facade explicitly sends `is_local=False`. | The request envelope records the effective parameters. |
| Batching | A two-symbol mixed SH/SZ call is covered as a single pass-through facade call; the facade does not rechunk it. | This proves facade pass-through only. SDK maximum and multi-symbol row-binding guarantee remain undocumented; no production batch size or one-symbol strategy is approved. A one-symbol call may be used only as a temporary minimal semantic probe if recovered row-specific evidence identifies a concrete target, and must not be extrapolated to the 78-month production build. |
| Row-to-request binding | A provider-returned table key may be preserved when present; each accepted status row still needs a valid trade date and exactly one canonical natural key. | Never fill a row from the request list/order. No evidence establishes a general one-to-one request/response relationship for unkeyed rows. |
| Empty response | An empty payload/table is preserved as empty. | It means “no status observation received”; it does not prove no event, no applicable session, or a successful completeness check. Applicable pairs remain unresolved unless independently reconciled. |
| BSE | Existing routing evidence uses current code `920185.BJ`; historical old/new-code evidence remains separate. The facade passes its input unchanged. | No BSE history activation, BJ remapping, or authoritative-universe expansion under Issue #90. |

The SH/SZ facade contract above is intentionally a minimum request-mechanics contract, not a semantic approval of the returned status fields.

## Code and regression coverage

The issue branch adds the minimum safety/test changes:

- `canonical_status_view()` rejects duplicate normalized `(provider_symbol, trade_date)` keys with `ProviderRowShapeError`; it does not discard or rewrite raw rows.
- `tests/unit/test_issue90_status_key_contract.py` covers:
  - keyed SH and SZ rows;
  - both-keys-missing and each one-sided-missing shape;
  - empty response preservation;
  - duplicate natural keys, including equivalent date spellings;
  - the mixed SH/SZ pass-through call, exact date-argument mapping, `is_local=False`, and no rechunking;
  - the existing BSE current-code routing fixture (`920185.BJ`) and empty-table preservation.
- No Golden/H1, migration/schema, provider configuration, raw evidence, or acquisition artifacts are changed.

## Acceptance status and next boundary

| Acceptance item | Status |
|---|---|
| Classify all eight rows as non-fact or exactly keyable | **BLOCKED** — retained evidence and SDK contract are insufficient. |
| Exact key for each admitted row | Enforced at the adapter boundary; no unkeyed row is admitted. |
| Required shapes and routing regression tests | **PASS** — merged PR #91; exact-head CI #773 passed on Windows and Ubuntu / Python 3.14. |
| Minimum SH/SZ request mechanics | Documented and mock-tested; provider batch ceiling and semantic row binding remain undocumented. |
| No BSE/corporate-action/full-history/Formal expansion | Satisfied; none was run or activated. |
| Ruff, format, mypy, focused/full pytest and Windows/Ubuntu Python 3.14 CI | **PASS** at PR #91 exact head; see CI run #773. |
| Short semantic-closure record | This file; disposition is BLOCKED, not PASS. |

To unblock the semantic issue, obtain a written AmazingData/SDK contract that classifies this exact returned-row shape. The bounded replay and one past-only comparison both reproduced identical row fingerprints, but raw shape alone is not enough to prove a row is non-fact; without authoritative explanation the endpoint must keep failing closed for these rows and cannot yet feed complete canonical status/limit facts.

**No 78-month acquisition/backfill is authorized by this record.** After semantic closure only, the scheduler must open a separate acquisition issue for SH/SZ `security_status + limit_price` over 2020-01 through 2026-06. BSE remains deferred.

## Source paths

- Prior observation and SDK-surface receipts: `docs/provider_verification/capability_closure_20260911.md`, `docs/provider_verification/capability_closure_20260911.json`, and `docs/provider_verification/remaining_capability_truth_20260912.json`.
- Facade: `src/ashare_state/providers/amazingdata/provider.py`.
- Status adapter: `src/ashare_state/spike/row_adapter.py`.
- Empty/duplicate completeness boundary: `src/ashare_state/providers/amazingdata/month_completeness.py`.
- BSE route fixture: `scripts/spike/capability_closure_probe.py` and `tests/unit/test_remaining_capability_truth.py`.
