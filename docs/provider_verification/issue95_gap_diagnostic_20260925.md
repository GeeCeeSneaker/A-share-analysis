# Issue #95 recurring status gaps — diagnostic checkpoint (2026-09-25)

## Disposition

The approved 78-month acquisition remains **ACTIVE but publication-blocked**. The isolated run was interrupted after the scheduler-directed pause; no evidence was discarded and no Canonical run was created. The 62 completed months with gaps remain unresolved. Five later months passed their month capture checks, August 2025 is partial, and the final ten months were not started.

No denominator or retry change is justified by the current evidence. Do not treat absence from the exact-session universe or absence of a daily bar as proof of non-applicability. A successful-but-empty status response is still unresolved for an applicable expected pair.

## Run reconciliation

The local isolated run `run_20260925T065004Z_66850919` made 3,271 Provider calls and ended `INTERRUPTED`. It records:

| Month result | Count | Detail |
|---|---:|---|
| `BLOCKED_COMPLETENESS` | 62 | 2020-01 through 2025-02; 1,563 unresolved pairs in each requested domain |
| `PASS` | 5 | 2025-03 through 2025-07 |
| Partial capture | 1 | 2025-08: 83,990 / 108,198 expected pairs returned |
| Not started | 10 | 2025-09 through 2026-06 |

Independent local reconciliation matched expected, returned, and missing-pair counts to the retained monthly manifest for all 62 blocked months (62/62; 0 count mismatches). Across those months: duplicate pairs = 0, unexplained extras = 0, structural errors = 0, and missing historical listing dates = 0. The Canonical reference is null; no data was published.

The sanitized source artifacts remain in ignored local storage and are not included in Git. Audit anchors for the local execution manifest and report are recorded in the JSON companion; no account data, server address, credentials, ticker-level rows, or raw Provider payloads are included here.

## Cross-tab of all 1,563 unresolved pairs

| Dimension | Result |
|---|---:|
| Exact-session universe member / absent | 1,238 / 325 |
| Exchange: SZ / SH | 1,470 / 93 |
| Board: ChiNext / SZ main / SH main | 1,324 / 146 / 93 |
| More than 250 exchange sessions after listing | 1,563 |
| Within 20 sessions of listing / delisting | 0 / 0 |
| Known delisting more than 20 sessions away / no known delisting date | 249 / 1,314 |

Thus, neither listing/delisting boundaries nor exact-session membership alone explain the repeated gap. In particular, 1,238 unresolved pairs are present in the exact-session universe. The 325 absent pairs remain unresolved rather than being dropped from the denominator.

## Three sentinel months and adjacent returned-day flags

The stratified early/middle/recent months include both a high-gap and a low-gap month. Their unresolved counts are 105 (2020-07), 38 (2022-08), and 18 (2025-02), totaling 161. Recomputed expected/returned/missing counts matched each month manifest. Among these 161 missing pairs, 54 were exact-session members and 107 were absent; all were more than 250 exchange sessions past listing, and none was within 20 sessions of a known delisting date (82 had a known delisting date more than 20 sessions away; 79 had no known date).

For those 161 pairs, nearest returned status rows were checked within the month and, at month edges, the adjacent captured month:

- A preceding returned row existed for 82 pairs. Its provider `IS_SUSP_SEC` value was `1` in all 82; `IS_ST_SEC` was `1` in 64 and `0` in 18.
- A following returned row existed for 15 pairs. Its `IS_ST_SEC` value was `1` and `IS_SUSP_SEC` was `0` in all 15.
- No preceding row was found for 79 pairs; no following row was found for 146 pairs.

These are observed provider field values, not an interpretation that a flagged row makes the missing date non-applicable. They do show that missing dates occur in more than one returned-history pattern; no universal denominator exclusion follows.

## Targeted source checks

- Seven one-symbol/same-day status probes at sampled missing pairs returned `exchange_status=OK` with zero rows. Three of seven adjacent-day status controls returned a row. Repeating the same missing-day request at a smaller request size therefore did not repair the sampled gaps.
- Five bounded daily-bar checks were made for sampled missing pairs: two returned an exact security/date bar and three returned no bar. Of two adjacent-day controls, one returned an exact bar. The two same-day bars prove trading activity for those sampled pairs despite the empty status response; the three no-bar cases remain unresolved and are not reclassified as non-applicable.

## Root-cause classification and next action

**Confirmed:** the gap is not explained by a local normalization/key loss in the reconciled 62-month outputs; sampled single-security status re-requests still returned empty; at least two sampled missing pairs have an exact same-day daily bar.

**Not yet confirmed:** whether the AmazingData status endpoint has a documented applicability boundary for these rows, or silently omits otherwise-applicable historical status facts. The samples support an upstream coverage/applicability issue, but do not establish a contract rule that can safely change the denominator.

Keep Issue #95 open and Canonical publication blocked. The next useful input is authoritative Provider/Owner evidence defining status-table coverage for these empty cases, or a corrected response under the same approved endpoint. Once a minimal rule is evidenced, rerun the three sentinel months; resume the remaining window only if unresolved applicable pairs reach zero. Do not restart the broad run or infer status/limit values before that evidence exists.
