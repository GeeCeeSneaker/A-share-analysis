# ADR-025: Deterministic Feature Layer / PIT / Window / Missingness Contract

## Status

- **Status**: PROPOSED（2026-09-03，CR-5 implementation；Reviewer closure pending）
- **Deciders**: Project Owner / Development Executor；Design / Audit Review（裁决 pending）
- **Date**: 2026-09-03
- **Work Requirement**: \`docs/design/A-share-analysis_CR-5_DeterministicFeatureLayer及PITFeatureSnapshot开发工作要求_20260903.md\`
- **Upstream**: ADR-024 ACCEPTED / CR-4 VERIFIED-CLOSED-FREEZE after PR #1 merge
- **Production**: P0-M-1B remains independently BLOCKED

## Context

CR-4 supplies an immutable Snapshot and a DuckDB ReadModel whose snapshot
provenance is verified before opening. CR-5 is the first derived research
fact layer. It must make formulas, windows, missingness, availability time,
lineage, identity, publication, and replay independently auditable without
introducing State, strategy, scoring, backtest, portfolio, or trading
semantics.

This ADR is intentionally limited to the V1 base feature set
\`market-state-base-v1\`. It does not make an adjusted-price claim and does
not claim that an observed bar universe is the whole A-share universe.

## Decisions

### 1. Explicit snapshot identity

The public build entry point is:

\`FeatureBuilder.build(snapshot_id, feature_set_id)\`

There is no latest, best, fallback, multi-snapshot fusion, or hidden
ReadModel rebuild. The caller chooses the world explicitly. The builder first
uses \`DuckDBReadModel.open_read_only(snapshot_id)\`; a missing or damaged
ReadModel fails closed. Snapshot verification is used only for verified
provenance metadata (manifest hash, semantic hash, canonical run, and
as_of), never as an alternate feature-value source.

### 2. Verified ReadModel is the only value boundary

Feature rows are retrieved with an explicit column list and
\`ORDER BY security_id, trade_date, canonical_key\` from the verified
\`rm_daily_bar\` table. The Feature package imports no Provider,
normalization, RawWriter, canonicalizer source-selection, or future strategy
layer. It does not read Snapshot Parquet directly. Orchestration may rebuild a
ReadModel explicitly before calling the builder, but the builder has no such
side effect.

### 3. Static versioned registry

\`src/ashare_state/features/registry.py\` defines the immutable V1 Registry.
The caller supplies only \`snapshot_id\` and \`feature_set_id\`; formula,
window, fill, tolerance, and adjustment parameters cannot be injected.
Registry identity is the SHA-256 of its canonical JSON declaration. A formula
or window change requires a Registry version/hash change, a new feature
identity, an ADR amendment, and fixtures.

### 4. V1 supported semantics

The V1 set contains:

- same-row raw-price features: \`raw_return_1\`,
  \`gap_open_raw\`, \`intraday_return_raw\`, and
  \`amplitude_preclose_raw\`;
- observed-bar features with fixed 5/20/60 lengths:
  \`ma_close_obs_N\`, \`close_to_ma_obs_N\`, and
  \`return_lag_obs_N\`;
- \`amount_to_mean_obs_20\` over the last 20 non-null observed amounts,
  including the current amount;
- \`vol_raw_return_obs_20\` as population standard deviation over the exact
  last 20 valid raw returns;
- observed-universe daily breadth and amount totals.

All raw-price features declare
\`price_basis = UNADJUSTED_CANONICAL\`. Rolling features declare
\`window_basis = OBSERVED_SECURITY_BARS\` because no verified
security-to-exchange-session calendar association exists in the CR-4
ReadModel. A date gap is therefore not forward-filled and does not become a
session claim.

The breadth denominator is
\`OBSERVED_DAILY_BAR_UNIVERSE\`: the securities with a daily-bar row on that
date. It is not \`ALL_A_SHARES\` or \`ALL_LISTED_SECURITIES\`.

### 5. Adjusted and ungoverned semantics remain blocked

The presence of \`adj_factor\`, \`backward_factor\`, or \`factor_type\` in the
frozen Snapshot is not evidence of a verified adjustment formula. Adjusted
OHLC, adjusted/total return, corporate-action-neutralized return, strict
market-session windows, limit-hit inference, industry/index semantics,
ungoverned cross-sectional z-scores, and all State/strategy outputs are
blocked until their evidence, formula, and ADR exist.

### 6. Missingness and numerical safety

No correctness artifact uses fillna, sentinel values, forward/backfill, copied
suspension prices, shortened windows, or silent row drops. A missing or
unsafe value is null and receives a deterministic typed finding:

\`INSUFFICIENT_HISTORY\`, \`INPUT_NULL\`,
\`UNSAFE_DENOMINATOR\`, \`NON_FINITE_RESULT\`, or
\`OPTIONAL_INPUT_MISSING\`.

A denominator must be finite and greater than zero. NaN and positive or
negative infinity never enter a correctness artifact. Partial observed sums
may use the valid observed members only when the omission is explicitly
recorded as \`OPTIONAL_INPUT_MISSING\`; an empty aggregate is null.

### 7. PIT and lineage

\`trade_date\` is the market fact date, not the knowledge date. Each security
feature row carries \`feature_available_at\`, computed as the maximum
\`available_at\` of the actual upstream rows examined for that row, and
\`input_lineage_hash\`, computed from ordered tuples of domain,
canonical_key, source row identity hash, and available_at. Rolling inputs
include the whole actual window. Market rows derive their lineage from the
participating security feature lineage set and use the maximum participating
availability time.

Every feature available time must be no later than Snapshot \`as_of\`.
Only observations at or before target \`trade_date\` enter a row's windows;
later rows in the same Snapshot cannot change an earlier row.

### 8. Deterministic identity

\`feature_base_hash\` is the SHA-256 of canonical JSON primitives:

- snapshot_id, snapshot manifest hash, snapshot semantic hash, snapshot as_of;
- ReadModel contract version and builder code fingerprint;
- feature set id/version, Registry version/hash;
- feature contract version; and
- Feature builder code fingerprint.

\`feature_run_id = UUID5(FEATURE_NAMESPACE, feature_base_hash)\`. No wall-clock,
random UUID, database insertion order, host timezone, or thread scheduling
enters correctness identity.

### 9. Correctness artifacts and recoverable publication

The exact V1 artifact set is:

\`feature/contract=feature-v1/snapshot=<snapshot_id>/run=<feature_run_id>/\`

with \`security_daily_features.parquet\`,
\`market_daily_features.parquet\`, \`feature_findings.parquet\`, and
\`manifest.json\`. Artifacts are written before the manifest, and the
manifest before the ledger row. Correctness bytes contain no wall-clock audit
timestamps.

A deterministic path is immutable: missing bytes are written, exact bytes
are no-ops, and different bytes or a non-file residue are hard conflicts.
A ledger failure leaves exact residue that an identical retry can recover.
There is no deletion or random suffix recovery.

V1 does not introduce a Feature ReadModel. The Parquet artifacts and their
manifest are the correctness truth; the public verifier parses the exact
hash-verified bytes and rebuilds expected rows from the verified ReadModel.

### 10. Builder and verifier share computation

\`compute_feature_set(...)\` is the only formula implementation. Builder and
\`verify_feature_run_for_consumption\` both call it. The verifier checks the
ledger, deterministic manifest and identity, current Registry and builder
fingerprint, upstream Snapshot, verified-open ReadModel, exact artifact set,
physical content/schema/row-count/semantic seals, findings, PIT invariants,
and exact replayed rows.

### 11. Alternatives rejected or deferred

- **Dynamic caller formulas/windows**: rejected because the caller would
  become an unversioned source of research truth and identity could be
  silently re-bound.
- **Ad-hoc pandas/SQL rolling**: deferred because planner/parallel reduction
  order is not the V1 correctness contract; ordered Python \`math.fsum\` and
  population variance are easier to replay exactly.
- **Direct Snapshot query**: rejected because it bypasses the verified
  ReadModel boundary and duplicates read/projection semantics.
- **Immediate adjusted prices**: rejected because factor orientation, base
  date, forward/backward semantics, corporate-action coverage, and provider
  revision behavior are not verified by field presence.
- **Multi-snapshot feature fusion**: rejected because one feature run must
  represent one immutable knowledge world; fusion requires a new temporal
  contract.
- **Feature ReadModel in V1**: deferred because it would add a second
  correctness layer without a State consumer requirement.

## Implementation mapping

- Registry: \`src/ashare_state/features/registry.py\`
- Formula truth: \`features/formulas.py\` and \`features/engine.py\`
- Builder/publicization: \`features/builder.py\`
- Public replay verifier: \`features/verifier.py\`
- Identity/findings: \`features/models.py\`
- Ledger: \`migrations/023_feature_build.sql\`
- Contract tests: \`tests/integration/test_features.py\`

## Review and exit

Implementation status is DONE only for the submitted CR-5 scope; review status
is PENDING_REVIEW until the three-platform CI matrix and reviewer closure
succeed. CR-5 must not emit State, score, signal, strategy, backtest,
portfolio, or trading outputs. On closure, this ADR may be marked ACCEPTED;
until then it remains PROPOSED.
