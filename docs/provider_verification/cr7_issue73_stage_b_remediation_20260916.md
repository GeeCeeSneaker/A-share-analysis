# Issue #73 Stage B remediation — 2026-09-16

## Scope and disposition

Baseline: `main@22c42a72e222d9b6f6519095fb641a4adb190e12` (PR #74 merge).
Only `2026-01` Holdout and `2020-01` Development were processed. No other month,
78-month backfill, Formal B1-B7/Production, BSE/index, CR-5/R2, Golden/H1,
global baseline, or strategy work was started.

Disposition: **2026-01 PASS / 2020-01 STOP(BLOCKED) / READY FOR PM REVIEW**.
Both months reached the Issue #73 per-month acceptance outcome. The 2020 semantic
blocker remains explicit; this is not an overall Stage B PASS and does not
authorize backfill or Production.

## 2026-01 — lifecycle remediation and full bounded closure

The existing authoritative-history boundary now exposes a typed capture/finalize
split:

1. `capture_month()` makes the bounded provider calls, anchors exchanges, and
   evaluates completeness without issuing a receipt.
2. The caller builds/refreshes the normal verified projection after capture.
3. `finalize_capture()` accepts the original raw root, typed capture, accepted
   completeness, and verified projection; it issues and replays a receipt from
   those same retained exchanges without calling the provider again.

The receipt validator and `retrieved_at_utc <= pit_as_of` invariant are
unchanged. Focused tests cover later-PIT finalization, zero provider calls during
finalization, early-PIT rejection, raw-root binding, retained-evidence tamper
detection, and incomplete-capture rejection.

### Execution evidence

- Source input normalization: calendar `8,727/8,727`; monthly historical code
  list `5,186/5,186`; stock basic `5,186/5,186`; daily bars
  `103,454/103,454`; quarantined rows `0`. Canonical selected `103,454` rows
  with `0` findings; verified projection contains `103,454` Holdout rows.
- Retained authoritative capture: 24 metadata records, including 20 unique
  exact-session hist-code-list requests; calendar/request scope checks passed.
- Completeness: required/returned pair sets both `103,454` with identical
  hashes; missing `0`, extra `0`, unresolved `0`, structural errors `0`.
  Classifications: `SUSPENSION_NON_TRADING=215`,
  `NOT_APPLICABLE_SESSION=51`.
- The last capture retrieval was `2026-09-16T11:32:54.572962+00:00`; the
  post-capture verified projection PIT was
  `2026-09-16T11:33:14.158803+00:00`. The real projection PIT is later than
  retrieval; no timestamp was fabricated and the validator was not relaxed.
- Receipt: `amazingdata-history-receipt-0b020510ae62ce051f58f429303be681`,
  receipt hash `67a09173b0a2530c55c836df370fd7c55cf1d485e0aa0ffd3f027062b427e5e3`;
  retained capture replay `PASS`. Receipt binds source snapshot
  `80af5da1-c99f-583d-a455-d756d9d6058d` and manifest hash
  `95d1fdb6932619543deb49f1ce464ad644e1d79348f58e4a80ddf9abcf6ada26`.
- Authoritative coverage `PASS`: basis
  `amazingdata-basis-holdout:2026-01-amazingdata-history-receipt-0b020510ae62ce051f58f429303be681`,
  artifact hash `618814ff83bead921a3fe5898d80411ddb4cf0e84b3712d56cb4638b65d13df5`.
- Bounded materialization `PASS` for one Holdout `2026-01` partition:
  materialization ID `rhm-1f783f7f2cdd867077c0bf1393a70f6f7c5c4f054a046bd7604b13235c5f7fa9`,
  manifest hash `5079bc490be5e0e275f11ee963e33984ccf11dec4d3ba7dc92e98231f2b8ed3c`.
  Ordinary reader loaded `103,454` rows for `2026-01-05` through `2026-01-30`;
  idempotent replay was `true`; changing content was rejected with
  `MaterializationConflictError`.

The first live run completed acquisition, post-capture projection, receipt
issuance, and retained replay, then the ignored one-off runner stopped at its
completeness gate because it referenced an undefined local variable instead of
the computed capture summary. The local harness reference was corrected and the
downstream chain was continued from that attempt's already-retained capture and
projection. The re-finalized receipt ID/hash matched the existing receipt and
the continuation made **zero provider requests**. This was a harness defect,
not a product-data or PIT failure.

## 2020-01 — exact five-pair historical-status recheck

The retained capture recomputation had identified these exact applicable
unresolved pairs. The targeted remediation then made one exact
`get_history_stock_status(start_date=session, end_date=session, code_list=[symbol])`
request for each; it made no calendar, universe, snapshot, or daily-bar probe.

| Provider symbol | Session | Prior retained status member | Prior exact snapshot fallback | Daily bar | New exact status response |
|---|---|---|---|---|---|
| `002971.SZ` | 2020-01-02 | Schema-valid, 9 rows; target session missing | Not queried | Absent | `OK`, 0 rows/0 columns, `ZERO_COLUMN_EMPTY`; no usable fact |
| `300813.SZ` | 2020-01-03 | Schema-valid, 8 rows; target session missing | Not queried | Absent | `OK`, 0 rows/0 columns, `ZERO_COLUMN_EMPTY`; no usable fact |
| `300815.SZ` | 2020-01-14 | Schema-valid, 1 row; target session missing | Not queried | Absent | `OK`, 0 rows/0 columns, `ZERO_COLUMN_EMPTY`; no usable fact |
| `002975.SZ` | 2020-01-16 | Zero-column empty | Queried previously; null/missing | Absent | `OK`, 0 rows/0 columns, `ZERO_COLUMN_EMPTY`; no usable fact |
| `300816.SZ` | 2020-01-17 | Zero-column empty | Queried previously; null/missing | Absent | `OK`, 0 rows/0 columns, `ZERO_COLUMN_EMPTY`; no usable fact |

All five requests had exact symbol/session scope and matching payload keys. The
new usable exact-session `IS_SUSP_SEC` fact count is `0`; all five pairs remain
`UNRESOLVED`, so `2020-01` remains `STOP(BLOCKED)` at `EXACT_STATUS_EVIDENCE`.
No suspension, zero-trade, or non-applicability conclusion was inferred from
empty status members, prior null/missing snapshots, or absent daily bars. No
receipt, coverage basis, or materialization was created for this month.

### PM/Owner review requested

For exactly the five pairs above, decide whether to provide/authorize a minimal
provider-owned exact-session status source/rule or to preserve the blocker until
such evidence is available. Any approved rule must consume an actual fact through
the existing semantics; do not infer state from missing rows/bars, request order,
adjacent dates, or an empty snapshot. No alternate source or broader probe is
authorized by this evidence.

## Local verification

- `tests/unit/test_cr7_historical_materialization.py`: **32 passed**.
- Full offline suite `uv run --locked --offline pytest -o addopts= -q`:
  **1,861 passed, 3 skipped**.
- `ruff check src tests`: **passed**.
- `ruff format --check src tests`: **216 files already formatted**.
- `mypy src/ashare_state`: **108 source files, no issues**.
- Exact-head CI is dynamic and must be checked on the Draft PR; this report does
  not cache its state.

No account values, account/profile identifiers, private addresses, ports,
SDK/runtime versions, raw provider payloads, local database paths, or
materialized artifacts are included in this report or its JSON. Local raw data,
DuckDB, and materialized files remain ignored.
