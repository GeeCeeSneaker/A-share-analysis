# A-share-analysis：CR-6 首批终审与 CR-6.4 Final Adversarial / Contract Honesty 收口要求

> Date: 2026-09-04  
> Reviewed PR: #6 `codex/cr-6-state-layer-clean-20260904`  
> Reviewed developer HEAD: `028cbef14036f25dc25ad0419acff5d3fa620dc0`  
> Reviewer upstream baseline before this review: `288ce150408f6fca35826d3734ea84ed064b4c7f`  
> Current main after parallel AmazingData contract merge: `2dc63e803af908baa3424d576b17d8b07751e05f`  
> Latest reviewed CI: run `33831970825` / run 207 — SUCCESS on Windows 3.12, Windows 3.14, Ubuntu 3.14; Ruff/format/mypy/full pytest/Spike/SDK-absent green; Windows 3.14 governance gates green.

## 1. Reviewer verdict

CR-6 implementation architecture is **PASS / KEEP**. Do not redesign the four V1 State dimensions, identity model, artifact layout, migration 024, or public replay architecture.

Formal status:

```text
CR-6.0 governance/bootstrap            PASS / KEEP
CR-6.1 Registry + deterministic engine PASS / KEEP
CR-6.2 identity/artifact/ledger/replay PASS / KEEP
CR-6.3 scope guards + 3-leg CI         PASS / KEEP
CR-6 overall                           DONE / REOPENED
CR-6.4 Final Adversarial + Contract Honesty START / ACTIVE
ADR-026                                PROPOSED / PENDING_REVIEW
PR #6                                  DO NOT MERGE YET
Strategy / Experiment                  BLOCKED_BY_CR-6.4
```

This reopening is narrow. It exists because closure evidence and ADR wording currently overstate what is mechanically proved; it is not a request for a new State design.

## 2. P0-01 — Mandatory 1..64 mapping is not yet honest/complete

ADR-026 currently says tests 1–10 + 45–60 were implemented and that a complete 1–64 implementation mapping exists. The physical test suite does not yet provide focused proof for all of those claims.

Current `tests/integration/test_state_persistence.py` materially proves:

- healthy build + public replay + identical retry;
- one artifact content-tamper refusal;
- generic upstream Feature-verifier failure -> zero State publish.

That is useful, but it is not equivalent to the mandatory recovery/rebind matrix in the CR-6 work requirement.

Before closure, append an explicit **Mandatory Test Mapping 1..64** table to the original CR-6 work requirement or ADR-026. Every number must map to a concrete test/parameterized case and, where reused from frozen upstream Feature tests, name the exact upstream test plus the State propagation test.

At minimum add focused State proof for the currently under-evidenced items:

```text
10  two distinct feature_run_id -> distinct State identity/path
38  evidence value tamper + rebound State outer seals -> rejected by Feature replay
42  adding a later Feature market row cannot alter an earlier State row
44  host timezone does not change State identity/correctness bytes
46  State Registry hash change -> State identity change
47  State builder fingerprint change -> State identity change
49  manifest LAST structural/failure proof
50  ledger commit failure -> exact deterministic retry recovers
51  partial identical residue -> fills only missing bytes and closes
52  conflicting residue -> hard fail, no overwrite/new identity
54  schema/rowcount/semantic pair-rebind -> physical recompute rejects
55  State business value + all State outer seals rebound -> independent Feature replay rejects
56  finding value + all State outer seals rebound -> deterministic replay rejects
```

Items 2–7 may map to frozen Feature-verifier adversarial tests **only if** the mapping also cites a StateBuilder test proving any public Feature-verifier failure causes zero State artifact/ledger success. Do not duplicate the entire CR-5 verifier suite merely for test count.

Parameterization is encouraged. The requirement is proof coverage, not 64 separate functions.

## 3. P0-02 — ADR-026 fatal invariant semantics and runtime currently disagree

ADR-026 Decision 9 states that a daily count invariant mismatch fails closed with `STATE_INPUT_INVARIANT_VIOLATION`. The runtime currently raises a generic `StateEngineError` immediately; no such finding is produced. At the same time `FINDING_CLASSES` advertises `STATE_INPUT_INVARIANT_VIOLATION` and `STATE_RULE_UNAVAILABLE`, although successful deterministic replay does not emit either class.

This must be made contract-honest before ADR acceptance.

Preferred Amendment A:

```text
Recoverable/representable insufficiency inside a successful State world:
  STATE_INPUT_NULL
  STATE_INPUT_EMPTY_DENOMINATOR
  -> State row retained, dimension UNKNOWN, persisted state_findings allowed.

Fatal world/contract contradiction:
  STATE_INPUT_INVARIANT_VIOLATION
  STATE_RULE_UNAVAILABLE
  -> typed fatal State error code / exception, NO successful State publication.
```

Implementation may use a typed exception class or a machine-readable error code carried by `StateEngineError`, but tests must assert the exact fatal classification. If this model is adopted, separate persisted finding classes from fatal error codes in schema/ADR so the public artifact contract does not claim values that can never occur in a successful replay.

Alternative: if the developer chooses to persist invariant/rule-unavailable findings, define a coherent failed-run evidence contract first. Do not publish a SUCCESS State artifact merely to preserve a fatal contradiction finding.

Mandatory focused tests:

1. count invariant mismatch -> exact fatal classification, zero State artifacts, zero SUCCESS ledger;
2. Registry rule unavailable -> exact fatal classification before artifact write;
3. public verifier cannot accept an injected persisted finding class that the deterministic successful engine cannot produce.

## 4. P0-03 — PR #6 must absorb the current protected-main baseline before final closure

PR #6 diverged from `main` at `4ac274747e86d5f386560ceabbffa3273ca9d14b`. Current `main` is now `2dc63e803af908baa3424d576b17d8b07751e05f` and contains two governance facts that CR-6 final CI must include:

1. public-repository protection files from PR #7, including `.github/CODEOWNERS = * @GeeCeeSneaker`;
2. AmazingData production-validation + 2020-01-01 history-boundary contracts from PR #5.

Required action:

- normal merge current `main` into the CR-6 branch; no force-push/history rewrite;
- preserve public governance files exactly unless a separately reviewed security change is necessary;
- preserve the 2020+ provider-validation contracts; CR-6 must not modify provider capability truth;
- run a fresh full 3-leg CI on the post-merge CR-6 final HEAD.

The pre-sync run 207 remains valid evidence for the reviewed CR-6 tree, but it is not the final merge-gate evidence after mainline synchronization.

## 5. P1-01 — PR / governance wording is stale

PR #6 body still says the PR stops at CR-6.1 and that Builder/artifacts/migration/verifier remain CR-6.2 work. The actual branch already contains CR-6.2 and CR-6.3.

Update the PR description and governance docs to state the real scope. Keep:

```text
ADR-026 PROPOSED / PENDING_REVIEW
CR-6 DONE / PENDING_REVIEW (or REOPENED under this reviewer decision)
```

Do not self-mark ADR-026 ACCEPTED or CR-6 CLOSED/FREEZE before Reviewer final closure.

## 6. Frozen scope during CR-6.4

Allowed changes only:

- `src/ashare_state/state/*` as needed for fatal-classification honesty;
- `tests/integration/test_state*.py`;
- ADR-026 Amendment A + concrete 1..64 mapping;
- CR-6 work requirement mapping append;
- DEVLOG append-only;
- DEVELOPMENT_MANAGEMENT sync;
- normal merge of current main into branch.

Do not add:

```text
new State dimensions
bull/bear / risk-on/risk-off / ice-point labels
sentiment score / rank / confidence
industry/theme/rotation state
Stress/RAD state
future return / probability
strategy / experiment / backtest / portfolio
new Provider/Canonical/Feature semantics
pre-2020 default history
production trading
```

Migration 024 should not be rewritten unless a genuine persistence-schema defect is found. If a schema change becomes unavoidable after 024 is already treated as shipped history, use 025 rather than mutating historical migration semantics.

## 7. CR-6.4 exit gate

All must hold:

```text
[ ] ADR-026 fatal-vs-persisted finding semantics match runtime exactly
[ ] exact fatal invariant classification + zero publish test green
[ ] exact rule-unavailable fatal classification test green
[ ] explicit 1..64 mapping exists with concrete test names/evidence
[ ] mandatory 10/38/42/44/46/47/49/50/51/52/54/55/56 focused evidence green
[ ] upstream failure mapping for 2..7 is explicit and honest
[ ] immutable recovery/rebind adversarial tests green
[ ] migration 024 from-zero / 023->024 / idempotent / tamper green
[ ] CR-6 scope guards remain green
[ ] current main merged normally into PR #6 branch
[ ] CODEOWNERS/public-security governance preserved
[ ] AmazingData 2020+ validation contracts preserved
[ ] PR #6 body reflects CR-6.0..6.4 actual scope
[ ] latest final HEAD 3-platform CI green
[ ] Windows 3.14 DEVLOG + Management gates green
[ ] no new P0
```

Then Reviewer may execute:

```text
CR-6.4 -> VERIFIED / CLOSED / FREEZE
CR-6   -> VERIFIED / CLOSED / FREEZE
ADR-026 -> ACCEPTED
PR #6 -> APPROVED_TO_MERGE
Strategy/Experiment planning may start only after main merge.
```

## 8. Parallel AmazingData track

PR #5 has now been merged to main as `2dc63e803af908baa3424d576b17d8b07751e05f`. This only starts the production-account validation/data-sufficiency workstream; it does not approve any provider capability.

Next provider evidence still required:

- scrubbed production account identity freeze;
- replace the obsolete pre-2020 history gate with the 2020-01-01+ contract before production Spike;
- B1..B7 single production run;
- Core/optional verdicts and evidence closure;
- Data Sufficiency Matrix, including index constituent/weight, industry daily/weight/taxonomy, equity/free-float, margin, and financial PIT/revision semantics.

CR-6.4 and AmazingData validation may proceed in parallel.

## 9. Current Implementation Evidence（2026-09-04）

本文件保留为 Reviewer 的收口要求和退出门，不把要求文档改写成自批准结论。当前实现侧已经补齐：

- CR-6.4 的 fatal-vs-persisted finding runtime contract、zero-publication boundary、recovery/rebind adversarial tests；
- CR-6 mandatory 1–64 concrete mapping；
- 2020+ provider history contract：`history_start_2020` / `history_coverage_2020_v1`，B5 起点 `20200101`，对应单元/集成 wiring tests；
- PR #6 body、ADR-026、CR-6 work requirement、Provider/Spike/2020+ documents 和治理记录的同步。

当前仍不能关闭的项目：

1. ADR-026 的 Reviewer acceptance、CR-6.4/CR-6 的 VERIFIED/CLOSED/FREEZE 以及 PR #6 的 APPROVED_TO_MERGE；
2. AmazingData 正式账号 identity/entitlement、CLOSED PRODUCTION B1-B7、Golden、Data Sufficiency Matrix 和 Provider approval；
3. 以上外部事实或人工决策不能由开发提交伪造。PR #6 继续 OPEN / NOT MERGED，Strategy/Experiment 继续 BLOCKED_BY_CR-6.4，Production 继续 independently BLOCKED。

