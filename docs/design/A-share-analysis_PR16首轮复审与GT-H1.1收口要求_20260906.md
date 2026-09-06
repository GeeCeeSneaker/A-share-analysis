# A-share-analysis PR #16 首轮复审与 GT-H1.1 收口要求

> Date: 2026-09-06  
> Reviewer baseline: `main@8f2ccb52a5ed2a58ef916a16a9c7e756173b08fd`  
> PR #16 reviewed head: `7e853b71722a9bbc3be2d46ded3f7c8a4981a7eb`  
> Reviewer review: `5123610912`  
> CI evidence: GitHub Actions `34001815013` / run 314 — Windows 3.14, Windows 3.12, Ubuntu 3.14 all SUCCESS  
> Status: **GT-H1 DIRECTION KEEP / GT-H1.1 REOPENED / DO NOT MERGE**

## 1. Accepted work

PR #16 correctly moves the Golden contract toward:

- explicit `event_effective_date` for ST/DELIST;
- no `trade_date` fallback in Formal structural counting;
- v1-v3 legacy loadability with fail-closed Formal semantics;
- v4+ event-identity semantic sealing;
- schema-v2 manifest statistics recomputed from dataset rows;
- append-only rebuild with explicit KEEP/REPLACE/DROP/ADD;
- `build-version` implicit append disabled;
- candidate/review shared structural validation;
- no Golden corpus facts added and no Production rerun.

These directions are KEEP.

## 2. GT-H1.1 P0-01 — one event / multiple observation cases must remain legal

The approved model is:

```text
one real ST/DELIST event
    -> may have N validation cases at different trade_date values
    -> all N cases share one structural identity
    -> Formal event qualification counts exactly 1 event
```

Structural identity is for **deduplicated qualification**, not a row-level uniqueness key.

Current PR code conflicts with this contract: `candidate._validate_output_documents()` rejects two rows with the same structural identity as a duplicate alias, while the same PR's statistics test correctly shows repeated observations count as one event.

### Required correction

- keep `golden_case_id` unique;
- allow multiple cases to share the same ST identity `(provider_symbol, event_effective_date, event_subtype)`;
- allow multiple cases to share the same DELIST identity `(provider_symbol, event_effective_date)`;
- `trade_date` and free-form `event_id` must never inflate qualification counts;
- manifest/event gate must deduplicate structural identity with set semantics;
- remove runbook wording that says repeated structural identity itself is a rebuild error.

### Required test

Publish a clean v4 candidate containing multiple different case IDs / observation `trade_date` values for the same real event and prove:

```text
rows > 1
structural event count == 1
rebuild SUCCESS
schema-v2 manifest recomputation == runtime recomputation
```

Changing only `event_id` must still never increase the structural event count.

## 3. GT-H1.1 P0-02 — review must not run before clean candidate rebuild

The required lifecycle remains:

```text
legacy v3 candidate
    -> GT-H2 clean candidate rebuild
    -> structurally complete v4+ candidate
    -> Human Review
    -> reviewed/sealed version
```

Current composition permits a dead-end:

1. `review.py` can review a non-structural v3 case;
2. review publishes a new ACTIVE version containing that REVIEWED row while legacy ST/DELIST rows remain structurally incomplete;
3. `candidate.py rebuild` refuses any ACTIVE source containing REVIEWED rows;
4. the required clean rebuild is then blocked without manual ACTIVE pointer manipulation.

This is not acceptable.

### Required correction

Before `review.py` stages evidence or publishes any reviewed version, ACTIVE must satisfy a **clean-candidate readiness predicate** equivalent to:

- v4+ / manifest schema v2 contract;
- zero `invalid_structural_cases`;
- every ST/DELIST row has valid explicit effective date;
- candidate remains in a state that GT-H2 intended for review;
- no legacy structural incompleteness is carried into a reviewed ACTIVE lineage.

Do not solve this by allowing rebuild to silently erase REVIEWED provenance. The ordering gate belongs at the review entry boundary.

### Required tests

1. ACTIVE v3 + attempt to review a non-structural case -> refused before evidence/version/ACTIVE mutation.
2. Structurally incomplete v4 candidate -> review refused.
3. Structurally complete schema-v2 v4 candidate -> review allowed.
4. Refused review leaves:
   - ACTIVE bytes unchanged;
   - no new version files;
   - no new evidence artifacts.

## 4. Scope control

GT-H1.1 must not add real Golden facts or begin corpus construction.

Still blocked:

```text
GT-H2 clean Golden corpus facts      BLOCKED
Human factual review                 BLOCKED until GT-H1.1 merge
GT-H3 reviewed seal qualification    BLOCKED
Formal Production B1-B7 retry        BLOCKED
Data Sufficiency Matrix              BLOCKED
Provider capability decision         BLOCKED
2020+ backfill                       BLOCKED
```

Do not weaken 50 ST / 20 DELIST thresholds and do not use duplicated observation cases to satisfy them.

## 5. Re-review exit gate

```text
[ ] repeated observations for one structural event are legal
[ ] repeated observations count exactly one structural event
[ ] free-form event_id cannot inflate event count
[ ] event_effective_date remains mandatory for Formal ST/DELIST
[ ] v1-v3 remain immutable/loadable but Formal fail-closed
[ ] review refuses legacy/incomplete candidate before any mutation
[ ] clean v4+/schema-v2 candidate can enter review
[ ] failed review leaves ACTIVE/version/evidence unchanged
[ ] no Golden corpus facts added
[ ] no Production B1-B7 rerun
[ ] Windows 3.14 required CI PASS
[ ] Windows 3.12 required CI PASS
[ ] Ubuntu 3.14 required CI PASS
[ ] Ruff / format / mypy / full pytest / Spike / SDK-absent / governance gates PASS
```

Only after the final PR head satisfies this gate may GT-H1 be closed and GT-H2 corpus reconstruction be authorized.
