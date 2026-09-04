# ADR-026: Deterministic Market State Interpretation Contract

## Status

- **Status**: PROPOSED / PENDING_REVIEW（2026-09-04，CR-6.0 governance bootstrap）
- **Deciders**: Project Owner / Development Executor；Design / Audit Review（pending）
- **Work Requirement**: docs/design/A-share-analysis_CR-6_DeterministicMarketStateLayer开发工作要求_20260904.md
- **Upstream**: ADR-025 ACCEPTED / VERIFIED；CR-5 VERIFIED / CLOSED / FREEZE after PR #3 merge
- **Scope**: descriptive, deterministic market State V1 only；Research / Strategy / Production remain out of scope

## Context

CR-5 produces a verified, point-in-time feature world. CR-6 is the first layer that may interpret those features into named market states, but interpretation is not a prediction and is not a trading instruction. A State result must therefore be explainable from the exact Feature row that was consumed, deterministic under replay, and honest about missing evidence.

The frozen sequence is:

~~~text
Raw / Observation -> Canonical Fact -> Feature -> State -> Strategy Research
~~~

This ADR governs the CR-6 V1 state set. It does not amend the Frozen Baseline V1.3.2, reopen ADR-025, or make any claim about the complete A-share market when the Feature universe is only the observed daily-bar universe.

## Decisions

### 1. One explicit Verified Feature Run is the only upstream

The public entry point is:

~~~python
StateBuilder.build(feature_run_id: str, state_set_id: str) -> StateBuildResult
~~~

The caller must provide both identifiers. There is no build_latest, build_best, build_current, implicit feature_run_id, fallback, or multi-feature-run fusion.

StateBuilder must call the public:

~~~python
verify_feature_run_for_consumption(feature_run_id)
~~~

and consume only the returned VerifiedFeatureRun market rows and provenance. It must not query meta_feature_build directly to bypass the verifier, open Feature Parquet directly, read Raw, Provider-Normalized, Canonical, Snapshot, or DuckDB ReadModel inputs, or reimplement a Feature formula.

If the Feature verifier fails, the State builder publishes no State artifact and no ledger SUCCESS row.

### 2. State is interpretation, not prediction or strategy

State V1 describes the structure observed in one verified Feature world at the Feature row's trade_date. A state name such as POSITIVE_CENTER means that the current evidence satisfies the declared sign rule; it does not mean that the next return is positive.

The State package must not import or use future returns, forward labels, backtests, experiments, strategies, portfolios, execution, trading, or PnL. No output may be called a signal, recommendation, position, bull/bear forecast, or probability.

### 3. V1 does not produce a total sentiment score

The four dimensions remain separate typed state values. Market structure is an exact rule composition of those dimensions, not a weighted score. There is no score, rank, confidence weight, or aggregate sentiment number.

Keeping evidence columns beside state columns is the explanation mechanism. It avoids losing the continuous Feature facts behind a categorical label and makes a later research study independent from the State correctness layer.

### 4. V1 consumes only Feature facts that already exist and are verified

The current CR-5 market Feature contract is the complete V1 input boundary:

~~~text
valid_raw_return_count
advancer_count
decliner_count
unchanged_count
advancer_ratio_observed
mean_raw_return_observed
median_raw_return_observed
valid_ma20_count
pct_above_ma20_observed
valid_mom20_count
pct_positive_mom20_observed
~~~

State V1 does not add adjusted prices, strict trading-session windows, ALL_A_SHARES denominators, industry/theme/rotation facts, stress facts, or any replacement Feature formula. If a future State needs a fact that is not in VerifiedFeatureRun, the Feature contract must be extended and independently verified first.

### 5. Static State Registry is the only rule/dependency/threshold truth

ADR-026 requires a versioned static registry with one StateSpec per supported state. Each StateSpec declares exactly:

~~~text
state_name
output_enum
required_feature_inputs
rule_id
threshold_policy
missingness_policy
availability_rule
interpretation
non_predictive_statement
eligibility
~~~

The registry has one canonical state_set_id, state_set_version, registry version, and canonical hash. A caller cannot supply thresholds, weights, formulas, missingness, availability, output enums, or extra state names.

compile_state_execution_plan(state_set) must validate exact state set identity, order, declarations, dependencies, rule IDs, threshold policies, missingness, availability, output enums, eligibility, and one typed handler per SUPPORTED declaration before any row is computed. A registry declaration without a handler fails closed.

### 6. Thresholds are direct mathematical boundaries, never backtest choices

V1 uses only thresholds with a direct semantic explanation:

~~~text
mean > 0 and median > 0       -> positive center
mean < 0 and median < 0        -> negative center
advancers > decliners          -> advance dominant
decliners > advancers          -> decline dominant
ratio > 0.5 / ratio < 0.5      -> majority direction
~~~

Equality at zero or 0.5 is handled explicitly by MIXED or BALANCED rules. No threshold may be chosen because it improved a future return, Sharpe, win rate, or any other historical performance measure.

### 7. Evidence projection is exact and independently cross-bound

The State artifact projects the exact values from the source market Feature row into evidence_observed_* columns. The verifier must compare every evidence value with the exact source Feature row using typed comparison; a rebinding of both the State business value and its outer seals must still fail because the public Feature verifier and State replay are executed independently.

The projected evidence does not become a second Feature owner. The Feature verifier remains the source of Feature truth.

### 8. PIT and lineage are preserved

For V1, every State dimension consumes one Feature market row. Therefore state_available_at equals source Feature feature_available_at, and never trade_date merely because it is convenient.

Each State row carries the source Feature input lineage hash. It also carries a new input_lineage_hash bound to source_feature_run_id, trade_date, source Feature availability, source Feature lineage, exact evidence feature names and typed values, the State registry version/hash, and the exact rule IDs. Changing selected evidence or registry/code identity changes State lineage and/or State identity. A future multi-row rule must use the maximum availability of all actual inputs.

### 9. UNKNOWN and findings are typed, deterministic, and lossless

For every Feature market row, State emits exactly one State row. Missing or insufficient evidence yields UNKNOWN rather than dropping the date, filling from another date, or silently substituting another input.

The permitted finding classes are STATE_INPUT_NULL, STATE_INPUT_EMPTY_DENOMINATOR, STATE_INPUT_INVARIANT_VIOLATION, and STATE_RULE_UNAVAILABLE. A normal mixed result is a valid MIXED state, not a finding. Finding detail_json contains deterministic canonical JSON only; no wall-clock field is part of correctness.

For the daily participation dimension, the counts must satisfy advancer_count + decliner_count + unchanged_count == valid_raw_return_count. A mismatch fails closed with STATE_INPUT_INVARIANT_VIOLATION and produces no successful State publication; it is not silently repaired.

### 10. Identity, artifact, manifest, and ledger are deterministic and recoverable

State identity uses the canonical primitives:

~~~text
feature_run_id
feature_manifest_hash
feature_semantic_hash
feature_set_id
feature_registry_hash
state_set_id
state_set_version
state_registry_version
state_registry_hash
state_contract_version
state_builder_code_fingerprint
~~~

state_base_hash is SHA-256 of canonical JSON primitives, and state_run_id is UUID5 under a fixed State namespace. Correctness bytes do not contain wall-clock timestamps, host timezone, database insertion order, or random IDs.

V1 artifact set is exactly:

~~~text
state/contract=state-v1/
  feature_run=<feature_run_id>/
  run=<state_run_id>/
    market_daily_state.parquet
    state_findings.parquet
    manifest.json
~~~

Each artifact has a URI, content hash, schema hash, row count, and semantic hash. The manifest is written last and the ledger transaction is committed after artifacts and manifest. Immutable publication accepts an identical residue as a no-op, fills a missing identical residue, and hard-fails on conflicting bytes. A ledger failure is recoverable by exact deterministic retry without overwriting committed bytes or generating a new random identity.

Because the State ledger is durable, CR-6.2 will add migration 024. Migrations 001-023 remain frozen, and migration 024 must pass from-zero, 023-to-024, idempotency, and checksum/tamper gates.

### 11. Public State verifier replays the Feature world and State rules

The public API is:

~~~python
verify_state_run_for_consumption(state_run_id) -> VerifiedStateRun
~~~

It must verify the ledger SUCCESS row, deterministic manifest URI, ledger/manifest field equality, current State Registry and builder fingerprint, physical state identity and UUID5, the public Feature verifier result and provenance, exact artifacts and seals, typed schema/order/key/enum/nullability, evidence equality, deterministic State replay, finding replay, physical counts, and aggregate hashes.

Builder and verifier must use the same deterministic compute_state_set execution function or equivalent shared plan. They must not contain two independent rule implementations.

### 12. Unsupported semantics remain explicitly blocked

CR-6 V1 does not infer industry/theme/rotation, adjusted-return trend, strict-session trend, total-market breadth, board/ST/limit semantics, volatility or Stress/RAD states, risk appetite, style regime, single-mainline, fast rotation, high divergence, bull/bear labels, future return, probability, signal, strategy, backtest, portfolio, execution, or production behavior.

These meanings require new verified Feature facts, a new Feature Registry version and closure evidence, and then a separately governed State Registry version. The State layer must not cross layers to manufacture them.

### 13. Alternatives and trade-offs

Rejected alternatives:

1. One global sentiment score: opaque, lossy, encourages false precision, and mixes independent dimensions.
2. Hand-tuned thresholds such as 0.63 or 0.72: untraceable without an explicit mathematical boundary and vulnerable to performance leakage.
3. Data-driven clustering: changes the task from deterministic interpretation to research/model fitting and introduces training-world/version concerns.
4. Direct Feature queries without a State artifact: loses immutable evidence, identity, recovery, and replay boundaries.
5. Multi-feature-run fusion: makes one State result depend on an implicit or mixed knowledge world and breaks one-run identity.
6. Predictive regime labels: leak future semantics into a descriptive layer and would be a separate research contract.

The trade-off is deliberately narrow coverage. V1 may return UNKNOWN or MIXED instead of pretending to explain facts that the current verified Feature world does not contain.

## V1 State Set and exact rules

The initial State Registry must expose only these four dimensions in this exact order:

~~~text
return_center_state
daily_participation_state
trend_participation_state
market_structure_state
~~~

Rules are frozen by the CR-6 work requirement:

- return_center_state consumes mean_raw_return_observed and median_raw_return_observed. Both positive gives POSITIVE_CENTER; both negative gives NEGATIVE_CENTER; otherwise MIXED_CENTER; null gives UNKNOWN with STATE_INPUT_NULL.
- daily_participation_state first checks the count invariant. With a positive valid_raw_return_count, advancer_count greater than decliner_count gives ADVANCE_DOMINANT, the reverse gives DECLINE_DOMINANT, equality gives BALANCED. Empty/invalid evidence is UNKNOWN or a typed invariant failure.
- trend_participation_state consumes valid_ma20_count, pct_above_ma20_observed, valid_mom20_count, and pct_positive_mom20_observed. Both ratios above 0.5 gives BROAD_POSITIVE; both below 0.5 gives BROAD_NEGATIVE; equality or split directions gives MIXED; null or zero-valid denominators gives UNKNOWN.
- market_structure_state consumes the first three typed dimensions. Any UNKNOWN gives UNKNOWN. All positive dimensions give BROAD_ADVANCE; all negative dimensions give BROAD_DECLINE; positive or negative center without full participation confirmation gives the corresponding MIXED_PARTICIPATION; a mixed center gives MIXED.

No rule may rename these states into a forecast, and no caller may alter the thresholds or add a dimension.

## Implementation mapping

CR-6.0 created this ADR and typed skeletons without runtime rule logic.

CR-6.1 implemented the State Registry, exact execution compiler, shared deterministic engine, four dimensions, and tests 11–44.

CR-6.2 implemented deterministic identity, immutable artifacts, migration 024, recoverable publication, the ledger, the public verifier, and tests 1–10 plus 45–60. GitHub Actions run `33829733713` (run 202) verified the clean PR #6 head with Ubuntu 3.14, Windows 3.12, and Windows 3.14; each leg passed 1368 tests plus Ruff, formatter, mypy, Spike, SDK-absent, and applicable governance gates.

CR-6.3 now adds the AST-based static scope guards for groups 61–63 and records the full-closure evidence path. Its new CI validation is pending; Reviewer closure remains pending until the complete 1–64 mapping and three-leg evidence are reviewed.

The first implementation batch must update DEVLOG and DEVELOPMENT_MANAGEMENT in the same logical governance batch. Historical DEVLOG entries remain append-only.

## Review and exit

This ADR is PROPOSED / PENDING_REVIEW until the Reviewer verifies that the decisions above match the CR-6 work requirement and the implementation passes the corresponding replay and scope gates. Acceptance of this ADR does not authorize prediction, strategy, or production trading.
