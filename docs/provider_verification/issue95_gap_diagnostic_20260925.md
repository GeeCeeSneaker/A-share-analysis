# Issue #95 — upstream coverage and Canonical execution checkpoint

## Current disposition — 2026-09-26

Issue #95 remains **ACTIVE / blocked before PASS review**. All 78 monthly captures and coverage reconciliations are retained and pass their structural checks. The remaining blocker is the one-time Canonical build: both the initial run and one narrow-memory-remediated rerun reached the configured 16 GiB RSS guard. No further Canonical attempt is authorized by the current checkpoint.

| Coverage state | Months | Scope |
|---|---:|---|
| `COMPLETE` | 16 | 2025-03 through 2026-06 |
| `PARTIAL_UPSTREAM_COVERAGE` | 62 | 2020-01 through 2025-02 |

Per requested domain, expected pairs = **7,461,248**, returned pairs = **7,459,685**, and missing pairs = **1,563**. The same missing `(security_id, trade_date)` pairs apply to `security_status` and `limit_price`; missing facts remain unknown and are not synthesized. Structural errors, duplicate keys, and unexplained extras are zero.

The retained run contains 3,593 Provider calls and 1,927 monthly normalization runs. Current-mapper offline replay is verified across the retained months and identity inputs; Provider calls during that replay were zero. Coverage receipts, missing-key-set hashes/counts, uniqueness, and `expected = returned + missing` reconciliations pass. Exact key files and raw Provider evidence remain in ignored local storage; none are committed.

## Canonical and memory outcome

The approved 16 GiB RSS guard was crossed twice. Both attempts used only the retained run and made **zero Provider calls**. The first attempt, before the narrow memory fix, was terminated by a monitor at its first post-threshold sample of **17,543.2 MiB**. It emitted no `SNAPSHOT_INPUT_MATERIALIZATION` checkpoint, so the exact point of allocation is unknown.

After that guard hit, a narrow change was made to the existing Canonical path without changing its persistent contract or seals:

- retain hash-verified normalized Parquet bytes in a disk-spilling snapshot buffer instead of freezing all rows into Python tuples;
- use slotted candidates, a candidate generator, in-place ordering/grouping, and promptly convert per-domain selected/decision rows to Polars frames;
- avoid duplicate Python schema-alignment and selected-file row copies;
- compute semantic hashes using bounded external sorting, and verify selected/decision Parquet rows without `.to_dicts()` expansion.

The sole post-fix Canonical-only attempt reached the snapshot/input-materialization checkpoint at **446.2 MiB**, showing that phase is now bounded in this run. During domain selection, RSS then rose rapidly. A 100 ms process monitor recorded **15,370.5 MiB** below the limit, then its first above-limit reading was **16,392.7 MiB** (limit: 16,384 MiB) and immediately terminated the runner. The exact instantaneous peak is unknown. No domain-selection completion, artifact-write, verifier, or exact-replay checkpoint was reached. This establishes that the memory change improved snapshot materialization but did **not** make the full Canonical build fit the approved guard. No third attempt should be started without a new project-manager decision on the next bounded remediation or available resource envelope.

Read-only verification after termination found one pre-existing Canonical ledger row: `c5b93927-405b-5a18-b5f3-d70968e940b1`, status `BLOCKED`, selected rows 0, decisions 0, findings 3,560. Its four artifacts are the earlier blocked run, not a successful result and not artifacts from the post-fix attempt. No new ledger row or successful selected artifact was produced; exact replay remains **NOT RUN**.

The retained `execution_manifest.json` still says `RUNNING`, `canonical=null`, attempt 3, with the two recorded checkpoints (`BEFORE_CANONICAL` 105.0 MiB; `SNAPSHOT_INPUT_MATERIALIZATION` 446.2 MiB). It was not rewritten after external termination. Current manifest SHA-256: `680ad8286cca4529411f5498873d78d0bc102157c147c326f2dd778e1e04adf7`. The 78-month coverage receipt SHA-256 is unchanged: `962554a3df0f63d9f23f8d5b45b525f4e3beb6bb4ac861740788fa053a871d46`. `report.json` still describes the earlier blocked run; do not treat it as the outcome of attempt 3. Local raw evidence, manifest, report, and DuckDB files are preserved; no lock/WAL cleanup or write-mode recovery was attempted.

The exact selection-phase allocation source was not profiled. Code inspection confirms that the run was in the broad candidate/selection phase when it crossed the guard; attributing the growth to any one collection remains an inference, not a profiler finding.

## Historical upstream-gap diagnostic

Exact-session membership alone does not explain the gaps: 1,238 missing pairs were present in the exact-session universe and 325 were absent. The gaps were 1,470 SZ and 93 SH; all were more than 250 sessions after listing, and none was within 20 sessions of a known delisting date. Seven one-symbol/same-day status probes returned successful zero-row responses; three of seven adjacent-day controls returned rows. Of five bounded daily-bar checks, two had an exact same-day bar and three had no bar. This supports a reproducible upstream coverage/applicability limitation, not a safe denominator exclusion rule.

Zero upstream missing pairs are **not** required for PASS. Known, structurally verified rows may be Canonicalized; absent status/limit values must stay unresolved/NULL. Status-dependent research must exclude or explicitly flag those observations; daily-bar-only research is not blocked.

## Security and QA

An SDK-generated session field appeared in an earlier terminal stream before process-wide output quarantine was installed. Its value is intentionally omitted and was not committed. Process-level stdout/stderr quarantine is implemented and covered by a subprocess regression test. Treat the prior provider session as exposed and rotate/revoke it after this task. Neither Canonical-only attempt used credentials or called the Provider.

After the narrow memory change, Python 3.14.7 validation passed: **212** focused Canonical/status/output-quarantine tests, Ruff lint, Ruff format check, `compileall`, and `git diff --check`. The full repository suite was not run for this delta. GitHub Actions run #804 passed on Windows/Ubuntu Python 3.14 for the earlier PR head `047dea9d7538e2d12a3f78dce2e0c2d47335d914`; exact-head CI for this memory remediation and diagnostic update is pending push.

This does not satisfy Issue #95 acceptance. The next required action is a project-manager decision on whether to approve an additional bounded selection-memory design or provide a larger execution resource envelope. Preserve the 78-month retained evidence; do not re-fetch it for this blocker.
