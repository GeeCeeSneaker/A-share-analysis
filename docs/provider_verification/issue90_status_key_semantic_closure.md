# Issue #90 — history status key and routing semantic closure

**Disposition: BLOCKED (`STILL_UNRESOLVED`).** This record closes the code/testable boundary work only. It does not approve the provider capability, authorize history acquisition, or meet the issue's PASS gate.

As-of: 2026-09-24  
Base: `main@409105925405e987d72636829a7ad144b46bf17c`

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

No Provider call was made. With no exact row or target symbol/date available, a narrower request would still be guesswork and cannot distinguish `PROVEN_NON_FACT` from `PROVEN_KEYABLE`. Keep the issue `STILL_UNRESOLVED`; the next unblock is either (a) mount/provide access to the existing retained-data root in this execution environment, or (b) obtain a written Provider/SDK semantic explanation. Do not replay the 1990–2099 request or broaden the search/query to manufacture evidence.

1. The issue's frozen receipt and scrubbed records:
   - `docs/provider_verification/capability_closure_20260911.json` records the 8-symbol, 1990-01-01–2099-12-31 response (20,638 rows), aggregate missing-date count, per-symbol table row counts, hashes, and raw artifact URIs.
   - The receipt does **not** preserve the affected row bodies, their dates/field values, or which exact symbols contain the eight rows. It stores logical URIs rather than a resolved filesystem root. The probe script defaults `--raw-root` to `data/spike/capability-closure-20260912/raw`, but the receipt does not record whether that default or an override was used. The expected files are unavailable in the searched local environment; GitHub cannot provide ignored local artifacts.
   - `docs/provider_verification/remaining_capability_truth_20260912.json` independently restates the 8/20,638 count and `STILL_UNRESOLVED` status.
2. The local AmazingData 1.1.9 SDK manual, section 3.5.2.10 (`get_history_stock_status`, PDF pages 17–18), lists `code_list`, `local_path`, `is_local`, `begin_date`, and `end_date`, plus returned status/limit columns. It does not define the semantics of rows missing both keys, a maximum batch size, response-to-request one-to-one binding, or the meaning of an empty response. No semantic docstring/contract was present in the inspected SDK surface.
3. Existing facade and adapter:
   - `get_history_stock_status_exchange(start_date, end_date, code_list)` forwards `begin_date=start_date`, `end_date=end_date`, `is_local=False`, and the caller's symbol list. It does not split batches or remap codes.
   - `canonical_status_view()` already fails closed when identity or date is missing. The response table name may be preserved as an observed symbol key by the existing adapter, but that cannot supply a missing trade date.
   - `month_completeness._status_rows()` already treats empty applicable coverage as unresolved and duplicate dates as structural errors.

A new Provider call would not close this gap: the receipt does not identify a target symbol/date for the affected rows, and recreating the 20,638-row century-window observation would only reproduce shape—not prove its meaning. No Provider request was made for this issue.

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
| Required shapes and routing regression tests | Added on this branch; CI must pass at the exact PR head. |
| Minimum SH/SZ request mechanics | Documented and mock-tested; provider batch ceiling and semantic row binding remain undocumented. |
| No BSE/corporate-action/full-history/Formal expansion | Satisfied; none was run or activated. |
| Ruff, format, mypy, focused/full pytest and Windows/Ubuntu Python 3.14 CI | Required merge gate; use the exact final PR head's run status. |
| Short semantic-closure record | This file; disposition is BLOCKED, not PASS. |

To unblock the semantic issue, obtain a written Provider/SDK contract that classifies these missing-key rows, or recover the exact ignored raw artifacts and use them to design a genuinely targeted reproducible check. Raw shape alone is not enough to prove a row is non-fact; if it remains ambiguous after that, the provider must explain its meaning or the endpoint cannot feed canonical status/limit facts.

**No 78-month acquisition/backfill is authorized by this record.** After semantic closure only, the scheduler must open a separate acquisition issue for SH/SZ `security_status + limit_price` over 2020-01 through 2026-06. BSE remains deferred.

## Source paths

- Prior observation and SDK-surface receipts: `docs/provider_verification/capability_closure_20260911.md`, `docs/provider_verification/capability_closure_20260911.json`, and `docs/provider_verification/remaining_capability_truth_20260912.json`.
- Facade: `src/ashare_state/providers/amazingdata/provider.py`.
- Status adapter: `src/ashare_state/spike/row_adapter.py`.
- Empty/duplicate completeness boundary: `src/ashare_state/providers/amazingdata/month_completeness.py`.
- BSE route fixture: `scripts/spike/capability_closure_probe.py` and `tests/unit/test_remaining_capability_truth.py`.
