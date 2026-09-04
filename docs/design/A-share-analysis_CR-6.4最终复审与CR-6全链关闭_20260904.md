# A-share-analysis：CR-6.4 最终复审与 CR-6 全链关闭裁决

> Date: 2026-09-04  
> Reviewed PR: #6 `codex/cr-6-state-layer-clean-20260904`  
> Reviewer baseline: `32db5066212f3d091a2090eb6a779242ba0432e4`  
> Reviewed developer HEAD: `04092d04694c4a039576f67b37bf4c256aa1e14b`  
> Base main: `2dc63e803af908baa3424d576b17d8b07751e05f`  
> Post-main-sync merge commit in branch: `bdb112213dc64325ccc3931a1c0617ae448ef93d`  
> Final merge-gate CI: GitHub Actions `33854677630` / run 239 — Windows 3.12, Windows 3.14, Ubuntu 3.14 SUCCESS; each leg 1408 passed; Ruff / format / mypy / full pytest / Spike / SDK-absent green; Windows 3.14 DEVLOG + Management gates green.

## 1. Reviewer final verdict

CR-6.4 has closed every blocker from the prior review. The implementation is approved without redesign.

Formal decision:

```text
CR-6.0 Governance / ADR bootstrap              VERIFIED / CLOSED / FREEZE
CR-6.1 Registry + deterministic State engine  VERIFIED / CLOSED / FREEZE
CR-6.2 Identity / Artifact / Ledger / Replay  VERIFIED / CLOSED / FREEZE
CR-6.3 Scope guards + cross-platform CI       VERIFIED / CLOSED / FREEZE
CR-6.4 Final Adversarial / Contract Honesty   VERIFIED / CLOSED / FREEZE
CR-6 overall                                  VERIFIED / CLOSED / FREEZE
ADR-026                                       ACCEPTED by Reviewer
PR #6                                         APPROVED_TO_MERGE
```

ADR-026 acceptance and CR-6 freeze become mainline-effective when this reviewed PR is merged. The next atomic governance synchronization commit must update the ADR header/index and project management status to the Reviewer decision before any later State/Research implementation changes; this post-review metadata sync must not reopen CR-6 semantics.

## 2. CR-6.4 blocker closure

### 2.1 Mandatory 1..64 mapping — CLOSED

The original CR-6 work requirement now maps every mandatory item 1..64 to a concrete test or parameterized case. The previously under-evidenced State cases are now mechanically covered, including:

- distinct `feature_run_id` -> distinct State identity/path;
- evidence rebind + outer seal rebind rejection;
- later Feature rows cannot mutate earlier State rows;
- host-timezone independence;
- Registry hash / Builder fingerprint identity boundaries;
- manifest-last failure behavior;
- ledger-failure exact retry recovery;
- partial identical residue recovery;
- conflicting residue refusal;
- schema / row-count / semantic physical recompute;
- State business-value all-seal rebind refusal;
- finding all-seal rebind refusal.

Items 2..7 correctly use the frozen upstream Feature adversarial suite plus an explicit StateBuilder propagation matrix proving every Feature-verifier failure yields zero State publication. The Reviewer accepts this reuse; duplicating the complete CR-5 verifier suite inside State would add noise, not assurance.

### 2.2 Fatal-vs-persisted truth — CLOSED

The State contract is now internally consistent:

```text
Persisted successful-world findings:
  STATE_INPUT_NULL
  STATE_INPUT_EMPTY_DENOMINATOR

Fatal contract/world errors:
  STATE_INPUT_INVARIANT_VIOLATION
  STATE_RULE_UNAVAILABLE
```

Fatal conditions carry an exact machine-readable `error_code`, occur before artifact publication, and cannot produce a SUCCESS ledger row. The public verifier rejects a fatal code forged into `state_findings`.

This is the accepted ADR-026 Amendment A behavior.

### 2.3 Current-main synchronization — CLOSED

The branch normally merged current main through two-parent merge commit `bdb112213dc64325ccc3931a1c0617ae448ef93d`; no force push or history rewrite was used. Public-repository governance and the Owner-approved 2020+ AmazingData validation contracts are therefore included in the final PR merge world.

The final CI run 239 tested the PR merge ref built from developer HEAD `04092d04694c4a039576f67b37bf4c256aa1e14b` against base main `2dc63e803af908baa3424d576b17d8b07751e05f`, so this is valid post-main-sync merge-gate evidence.

## 3. Frozen CR-6 V1 mechanisms

The following become frozen CR-6 V1 behavior:

1. **One explicit Verified Feature Run only** — `StateBuilder.build(feature_run_id, state_set_id)`; no latest/best/current, fallback, or multi-run fusion.
2. **Public Feature verifier only** — State never directly consumes Provider / Raw / Canonical / Snapshot / DuckDB ReadModel and never recomputes Feature formulas.
3. **Static State Registry as execution truth** — exact declaration/order/dependency/rule/threshold/missingness/availability/output enum and typed-handler checks before computation.
4. **Four descriptive V1 states only** — return center, daily participation, trend participation, market structure.
5. **No predictive semantics** — no bull/bear forecast, future return, probability, signal, score, rank, strategy, position, portfolio or execution meaning.
6. **Direct semantic thresholds only** — sign boundary 0, majority boundary 0.5, exact advance/decline count dominance; no backtest-selected threshold.
7. **Exact evidence projection** from one Verified Feature market row.
8. **PIT correctness** — `state_available_at = source feature_available_at` for V1.
9. **Deterministic lineage** binding Feature lineage, exact evidence, availability and State Registry/rules.
10. **Deterministic State identity** — SHA-256 canonical primitives + UUID5; Registry/code/Feature-world changes mint a new identity.
11. **Exact immutable artifact set** — `market_daily_state.parquet`, `state_findings.parquet`, `manifest.json` last.
12. **Recoverable publication** — missing write, identical no-op, conflicting hard fail; ledger failure is exact-retry recoverable.
13. **Migration 024** `meta_state_build`, with from-zero / 023->024 / idempotent / tamper gates.
14. **Public deterministic State verifier** — current Registry/fingerprint, UUID identity, upstream Feature verifier, exact bytes/schema/counts/seals, evidence equality, State/finding replay and aggregate seals.
15. **Static scope guards** — no cross-layer fact imports, duplicated Feature implementation, Strategy/Experiment/ForwardLabel/Backtest imports or future columns.

Any future change to these semantics requires a new governed State contract/version and ADR amendment/new ADR; it must not silently mutate `state-v1`.

## 4. 2020+ Provider history contract review

The repository-side 2020+ synchronization included in PR #6 is **VERIFIED / KEEP as a contract implementation**, not a Provider capability approval:

```text
history_start_2020
history_coverage_2020_v1
required earliest = 2020-01-01
B5 regular platform history probe begins at 2020-01-01
pre-2020 regular pull/backfill is not required
```

This matches the Owner decision. It does not claim actual 2020+ completeness until a formal Production Spike proves it.

## 5. AmazingData formal-account track remains independently BLOCKED

The separate local controlled environment has useful **connectivity/API smoke evidence**: official `AmazingData==1.1.9` / `tgw==1.0.9.2` imported, login succeeded and targeted small-window calls returned structured results. This is accepted only as L1 connectivity / SDK-smoke evidence.

It is explicitly **not** sufficient for:

- frozen production account identity;
- entitlement truth;
- formal run-scoped B1..B7 evidence;
- Golden truth closure;
- 2020+ history completeness;
- Data Sufficiency Matrix closure;
- Provider GO / capability approval.

`configs/production_account.yaml` still has empty `production_account_profile_id`, `confirmed_at`, and `confirmed_by`, so production truth remains fail-closed.

### Provider documentation P1 correction

`docs/provider_verification/amazingdata.md` now contains a time-state inconsistency: §1.3 correctly records a successful formal-account local SDK smoke while older §2 / §3.1 wording still says the "current account" is the trial/simulation account. This is not a CR-6 blocker, but the next Provider-governance commit must reconcile the authoritative wording to the exact current truth:

```text
trial account = historical evidence only
formal account credentials/connectivity = available and smoke-tested locally
formal production profile identity = NOT YET FROZEN
formal B1..B7 Production run = NOT YET EXECUTED
Provider capability approval = BLOCKED
```

Do not replace this with a generic "formal account verified" statement.

## 6. Governance note

The CR-6 branch introduced explicit SHA-scoped CI grandfather exceptions because path-by-path GitHub contents writes split code/contract and governance documentation across commits. Reviewer accepts these as a one-time historical exception because they are exact-SHA scoped, disclosed, non-reusable and final CI proves future enforcement remains active.

This is **not precedent** for future development. Future multi-file code/contract changes must use an atomic commit mechanism or otherwise satisfy DEVLOG / Management requirements in the same commit. Do not extend the grandfather lists for ordinary development convenience.

Minor P2: the DEVLOG-gate CI comment says "following four" while its explicit grandfather list contains five SHAs. Correct the comment at the next CI-governance touch; do not create a functional CR-6 reopening solely for that wording.

## 7. Next work after merge

Immediate next work in `A-share-analysis` is the already-approved AmazingData Production Validation / Data Sufficiency track, not new State semantics.

Required sequence:

1. freeze scrubbed production account identity and actual entitlements;
2. run one governed CLOSED PRODUCTION B1..B7 run through the formal pipeline;
3. prove Core 8 + Optional 4 using persisted anchored evidence and formal gates;
4. close 2020-01-01 -> latest-complete-trading-day historical coverage;
5. complete the extended Data Sufficiency Matrix, especially index constituents/weights, industry taxonomy/constituents/daily/weights, equity/free-float, margin, and financial PIT/revision semantics;
6. only then issue Provider verdict and capability approvals.

Strategy / Experiment planning may start after PR #6 is merged, but no Strategy implementation should be added to this data-platform repository without a separate approved work contract. Strategy research remains governed in its dedicated research repository/workflow.

## 8. Owner-facing closure

CR-6 has reached the intended boundary: the platform can now transform one verified Feature knowledge world into a deterministic, auditable, PIT-correct, immutable and replayable descriptive market-state world without pretending to predict returns or issue trading instructions.

The remaining major platform uncertainty is no longer State engineering. It is the real production-data foundation: formal AmazingData account identity, 2020+ completeness and semantics, Golden evidence, and the Data Sufficiency Matrix.
