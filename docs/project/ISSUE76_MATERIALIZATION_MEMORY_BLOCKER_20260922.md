# Issue #76 materialization memory blocker — 2026-09-22

Status: **STOP(BLOCKED) — no final PASS**

This report records the local verification outcome after the 78-month retained-evidence run reached the materialization boundary. It contains no credentials, session tokens, provider payloads, account identifiers, or raw data.

## Confirmed facts

- The retained local evidence contains 78/78 monthly partitions for 2020-01 through 2026-06.
- The first full run completed capture/replay, normalization, canonical projection, snapshot, readmodel, coverage finalization, and the first materialization publication. The run stopped before the changed-content conflict assertion because the local ignored runner searched for the literal `"ENABLED"`, while the typed contract value is `"RESEARCH_ENABLED"`.
- The local runner comparison was corrected to use `ResearchEligibility.ENABLED.value`. This runner is under ignored `data/spike/` and is intentionally not a tracked production artifact.
- The Windows native stdout/stderr capture boundary was hardened so native SDK writes through `GetStdHandle/WriteFile` are captured. CI #690 passed the complete test matrix for that change.
- Snapshot verification was reduced in peak memory by:
  - releasing the source canonical rows after deterministic projection;
  - replacing full-dataset JSON-list sorting with stable-order, row-at-a-time comparison;
  - releasing each projected domain after verification.
  GitHub commit: `1d55bea8120d336e40840071084b4c11de409dbf`. CI #694 passed Ruff, mypy, unit/integration tests, and the SDK-absence check.
- The final local state after the controlled stops is `STOP(BLOCKED)`, phase `TARGETED_MATERIALIZATION_PREP_MEMORY_GUARD`. No local raw, normalized, snapshot, readmodel, or materialized artifact was deleted or overwritten.

## Memory findings

The machine has approximately 64 GB RAM. The following measurements are from the local Python process:

1. The original readmodel rebuild reached approximately 46.7 GB while `verify_snapshot` retained the canonical source rows, projected rows, physical rows, and full sorted JSON comparison lists. It was safely interrupted.
2. After the snapshot-verifier optimization, the first narrowed attempt used `ResearchPanelBuilder.prepare_verified_projection` and reached approximately 46.5 GB. The remaining duplication was the readmodel source rows plus the newly constructed projected rows in `ResearchPanelBuilder._project_rows`. It was safely interrupted.
3. A second narrowed attempt first verified the existing readmodel and then intended to load the 78 materialized Parquet partitions directly. It was stopped at approximately 38.5 GB while the existing readmodel logical verification was still in progress, before a final materialization PASS could be recorded.

These are controlled safety stops, not provider failures and not authentication failures.

## Current evidence boundary

The existing materialization directory contains a manifest and 78 research-enabled partition artifacts. Its recorded writer lock, dependency lock, build fingerprint, source snapshot identity, and coverage descriptor/evidence counts match the current local code/environment. This proves that a prior materialization publication exists, but it does **not** prove that the latest runner completed its final changed-content conflict gate. The repository must therefore continue to report the run as blocked.

## Remaining engineering blockers

1. `DuckDBReadModel._validate_logical_seal` fetches the whole table, builds a second list of dictionaries, and computes a full sorted semantic list. This is not bounded for multi-million-row tables.
2. `ResearchPanelBuilder.prepare_verified_projection` fetches all daily bars and constructs a second full projected list before returning the typed projection.
3. The ignored spike runner has no supported materialization-only/resume mode that consumes an already verified snapshot/readmodel/materialization identity without replaying all 78 months.
4. The runner's final state/summary contract should distinguish:
   - a prior published materialization;
   - idempotent replay verified;
   - changed-content conflict verified;
   - full end-to-end run PASS.
   They must not be collapsed into one status.

## Required next work before claiming PASS

- Implement bounded-memory readmodel semantic verification, preferably chunked/external-sort or an equivalent exact seal-preserving algorithm. Do not replace the semantic check with a row-count-only check.
- Add a bounded projection/materialization path that releases source rows before building projected rows, or processes partitions incrementally.
- Add a tracked, documented `materialization-only` validation command with explicit provenance checks and a hard memory budget.
- Add regression tests for the large-snapshot memory path and for the final state transition only after both idempotent replay and changed-content conflict rejection pass.
- Re-run the final local gate only after the above changes. Until then, the project manager should treat the 78-month run as **blocked/incomplete**, despite the existing 78-artifact directory.

## Local-only execution references

The local run root is ignored and must remain untracked:

`data/spike/issue76_history_build_20260916/`

The sensitive SDK environment remains local-only. No credentials or provider session material may be added to GitHub.

## M1 follow-up — bounded ReadModel gate still blocked (2026-09-22)

The M1 implementation was tested once against the existing 78-month snapshot/readmodel using a read-only child process and a hard 15 GiB RSS stop threshold. An external process check observed the verifier at approximately **22.268 GiB working set**, above the PM initial acceptance budget of <16 GiB. The child was stopped immediately; no second measurement or unchanged-code retry was made.

Post-stop checks found:

- execution_state.json was unchanged;
- the temporary .readmodel-verify workspace was absent after cleanup;
- no ledger, raw evidence, normalized snapshot/readmodel, or materialization artifact was intentionally written, deleted, or overwritten by this measurement;
- M1 is therefore **not accepted**. M2 projection/materialization and M3 materialization-only/resume work remain paused.

The bounded hash/seal-only code and fixture QA remain useful, but they are not sufficient to claim a bounded 78-month gate. The remaining high-memory allocation boundary must be isolated and reduced before any further large-window run. This is the final execution attempt for the current checkpoint.

## M1 code remediation after the RSS stop — 2026-09-22

No new 78-month measurement was attempted after the 0.8 RSS failure. The remaining read-in allocation boundary was reduced in code:

- canonical selected.parquet now has a hash/schema/row-count verified batch source backed by Arrow Parquet batches;
- seal-only snapshot verification streams physical Parquet batches and uses bounded JSONL external-sort chunks for the canonical projection, preserving the existing exact row, PIT, key, schema, duplicate-key, and seal checks;
- the legacy retain-domain-rows hand-off remains available for callers that explicitly need in-memory rows;
- regression coverage rejects a full-frame read on the seal-only path.

Code commits are 1339f3e83304324d0815cbe0856fbf5a2213b394, f3c4de311cf3da5bf7968dc9e05306b0ec27630f, and fc03bd1a1b32bb4bebe2c0f196a4b40cbccbfe92. Ruff, mypy, Snapshot/ReadModel integration tests, and the full offline pytest run passed with exit code 0.

This is a code-level remediation only. It does not establish that the real 78-month RSS is below the 16 GiB acceptance budget. M1 remains STOP(BLOCKED); M2 projection/materialization, M3 materialization-only/resume, and final publication acceptance remain paused pending an explicit PM/Owner decision for one new bounded RSS measurement.

CI follow-up — 2026-09-22

After the EOF normalization, CI run #711 passed all required jobs: Ubuntu 3.14, Windows 3.14, and Windows 3.12. This confirms repository lint, type checks, and offline test gates for the change; it does not change the M1 RSS result or authorize a new large-window measurement.

## M1.1 sealed snapshot hand-off remediation — 2026-09-22

The PM review identified that the previous seal-only mode still entered the snapshot verifier's bounded canonical projection path from ReadModel rebuild/open. That reduced Python retention but did not remove the dominant recursive canonical allocation.

The tracked remediation now provides one explicit `consume_snapshot_seal` hand-off for downstream ReadModel use. It verifies the snapshot ledger/manifest identity, cross-binds only the canonical manifest seal, streams each snapshot artifact hash, checks Parquet schema and metadata row count, validates semantic seal shape, and recomputes the artifact-set, snapshot-semantic, and total-row seals. It does not call `load_canonical_projection`, `open_canonical_projection_source`, `project_canonical_snapshot`, or full-table `read_parquet`. The existing `verify_snapshot` deep-audit path remains available and its projection/PIT/key checks are unchanged.

ReadModel rebuild and verified-open now use the sealed hand-off, and regression tests cover the no-projection/no-full-frame boundary, snapshot artifact tampering, canonical manifest/ledger drift, and both rebuild/open consumers. Local Snapshot/ReadModel integration tests, Ruff, and mypy pass.

This is still a code-only remediation. No new 78-month RSS measurement was attempted after the prior ~22.268 GiB stop; M1 remains STOP(BLOCKED), and M2/M3/final publication remain paused pending an explicit PM/Owner decision for one bounded measurement.

CI follow-up — 2026-09-22

CI run #716 passed all required jobs: Ubuntu 3.14, Windows 3.14, and Windows 3.12. GT-H3B was skipped by scope. This confirms the repository gates for M1.1; it does not change the M1 RSS result or authorize a new large-window measurement.

## M1.2 authorized gate attempt — retained artifact provenance blocked before RSS measurement (2026-09-22)

PM review at exact head `1e656022a3702ed5ae4f51a42e1959257b8badce` authorized one M1-only rerun after the M1.1 sealed snapshot hand-off remediation. The bounded local attempt was executed once against the retained 78-month ReadModel and did not access the provider layer or credentials.

Observed result:

- The child entered `M1_READMODEL_VERIFY_START`, then stopped at the existing snapshot seal boundary before any ReadModel semantic scan or meaningful RSS measurement.
- `consume_snapshot_seal` rejected the retained snapshot because its persisted `snapshot_builder_code_fingerprint` differs from the current builder fingerprint. This is the intended fail-closed provenance check; no compatibility bypass was used.
- The process exited with code `1` after about `4.1` seconds. The observed working set was only about `0.005` GiB, but this is **not** an M1 memory result because the verifier never reached the memory-intensive ReadModel check.
- The retained execution state hash was unchanged, the temporary `.readmodel-verify` directory was absent after exit, and no ledger, raw evidence, normalized data, snapshot/ReadModel, or materialization artifact was intentionally written, deleted, or overwritten.
- Provider calls: `0`. No account, credential, session token, network endpoint, or provider payload was read or emitted.

M1 therefore remains **STOP(BLOCKED) and unmeasured**. M2/M3 were not started. The previous approximately 22.268 GiB result remains the only valid memory observation for the prior implementation; it is not a measurement of M1.1 and cannot be replaced by this provenance failure.

Required next decision:

1. Do not weaken or bypass the snapshot builder fingerprint gate.
2. Before another M1 RSS attempt, provide or explicitly authorize creation of a current-code-compatible retained snapshot/ReadModel from the already sealed local canonical evidence, without provider capture. That rebuild is a separate operation and was not performed under the current M1-only authorization.
3. After a compatible retained artifact exists, run exactly one bounded M1 measurement with the existing 15 GiB hard stop and <16 GiB acceptance rule. Until then, keep M2/M3 and final publication paused.


## Post-#80 PASS — retained-evidence C1 audit blocked (2026-09-23)

Status: **STOP(BLOCKED) before the offline PIT/identity/lifecycle sample audit; provider_calls=0.**

### Confirmed facts

- Issue #80 implementation is complete at PR #81 head `21ec85bdaafeb40fb0c5a088d708970b1b5ee8ce`. Exact-head CI run [35834078040](https://github.com/GeeCeeSneaker/A-share-analysis/actions/runs/35834078040) passed all three required jobs (Ubuntu/Python 3.14, Windows/Python 3.12, Windows/Python 3.14), including full pytest, Ruff, mypy, and the SDK-absence check. PR #81 is ready for review and is not merged.
- The latest #76 scheduler direction is to resume only with `provider_calls=0`, first auditing representative retained evidence against PIT/availability, identity, and lifecycle semantics.
- The documented ignored local run root, `data/spike/issue76_history_build_20260916/`, is absent from the currently accessible #76 worktree. The earlier alternate local path referenced in historical execution notes is also unavailable in this environment. This establishes only that the artifacts are not available at those checked paths; it does **not** establish that they were deleted or do not exist elsewhere.
- Tracked evidence is not sufficient to perform the audit: `docs/provider_verification/cr7_issue76_history_build_20260916.json` reports a 2026-09-20 capture stop at 68/78, while this later 2026-09-22 blocker report records 78 retained monthly partitions and a prior materialization publication. Neither tracked summary contains the raw per-month evidence and exact local state needed to independently reconcile that difference or verify migrated logical facts.
- No provider call was made. No retained raw, normalized, Canonical, Snapshot, ReadModel, or materialization artifact was read, changed, deleted, or uploaded during this checkpoint.

### Required project-manager action

Restore/mount the exact existing ignored run root into an accessible local workspace, or identify its correct current path and provide access to that local storage. Preserve the artifacts in place. Before any migration, verify the execution-state and manifest hashes against the retained files and reconcile the 68/78 versus 78/78 summary discrepancy.

After access is restored, perform the offline representative audit specified in `docs/architecture/ARCHITECTURE_OPTIMIZATION_PLAN_20260923.md §7.1`: 2020-01, 2024-01, 2026-01, the 2025-02 approved identity-transition month, and retained suspension/list/delist edge cases (including 2020-02 and 2023-01 where present). Compare event/market-availability time with provider retrieval time; validate stable UUID identity and approved symbol intervals; verify LISTDATE/DELISTDATE and the narrow suspension interval; record only sanitized hashes/counts. Do not reacquire data or proceed to bulk migration until that audit passes.

## 2026-09-23 follow-up — retained run roots found

This supersedes the earlier statement that the retained run root was unavailable at all checked local paths. A bounded follow-up search found the existing `data/spike/issue76_history_build_20260916/` root in two alternate local worktrees: `issue73-remediate-stage-b-20260916` and `issue76-identity-fix-20260920`.

Metadata-only inspection confirmed `runner.py`, `execution_state.json`, and `execution_summary.json` at both roots. A recursive inventory of the first root counted 342,735 files (339,108 Parquet and 3,621 JSON), totaling 6,591,572,231 bytes. No raw payload contents or execution-state values were opened; this count does not prove that all 78 monthly captures are complete or that either copy is internally consistent. The two roots must be reconciled by state/manifest hashes before selecting one. No files were copied, changed, or deleted. No matching runner process was active and `provider_calls=0`; the conditional request to reacquire data does not apply because retained roots were found.

PR #81 logical-daily semantics remediation is now at exact head `13f25f0e9c46fe78f34a392f032a8b0d4e030ce0`; exact-head CI run 35846313200 passed all three required jobs. **This is CI PASS, not final PM PASS.** Issue #76 remains paused under the #80 architecture gate. After PM records final #80 PASS, reconcile the two retained roots, then run the specified representative PIT/identity/lifecycle audit before any migration. Do not use the Formal B1-B7/Production runner.
