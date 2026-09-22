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

