# A-share-analysis PR #15 关闭与 Golden Truth 重建工作要求

> Date: 2026-09-06  
> Previous authoritative baseline: `b1f85de4b35eb3480534f93bbdcd9f91a52f3830`  
> PR #15 reviewed head: `15d9228d93d228278f2af2b418ba96196f189293`  
> PR #15 Reviewer review: `5123342457`  
> PR #15 CI: GitHub Actions `33974727373` / run 310 SUCCESS  
> PR #15 merge: `877756477a8f6b0854a6da5f54e4779eb8717295`  
> Status: **PRE-RUN BLOCKER VERIFIED / GOLDEN TRUTH REMEDIATION REQUIRED / FORMAL PRODUCTION STILL BLOCKED**

## 1. Reviewer closure

PR #15 is accepted as a truthful fail-closed blocker record.

The authorized command:

```text
uv run python scripts/spike/spike_runner.py --production --date 20260904
```

passed the frozen production-identity check but was refused by the Golden Truth formal gate before a `SpikeRun` was created. Therefore:

```text
run_id                         DOES NOT EXIST
Formal B1-B7                   NOT EXECUTED
formal verdict                 NOT COMPUTED
Provider capability decision   BLOCKED
Data Sufficiency Matrix        BLOCKED
2020+ backfill                 BLOCKED
```

This is the correct lifecycle semantics. Do not reclassify the attempt as FAILED/ABORTED/CLOSED and do not manufacture a run identifier.

## 2. Why this is not a simple “sample-count fill” task

Current ACTIVE Golden v3 is a candidate compilation, not a reviewed truth asset:

- 123 cases are still `COMPILED`;
- the original set intentionally used repeated state-observation dates around a small number of real events;
- row-count minimums and distinct-event minimums are separate contracts;
- Production requires every ACTIVE Golden case to be human reviewed with resolvable/hash-verified official evidence.

The thresholds are intentional governance gates and must not be weakened merely to unblock Production:

```text
golden_st_transition rows          >= 50
structural ST_TRANSITION events    >= 50
ST ADD family                       > 0
ST REMOVE family                    > 0

golden_delisted rows               >= 20
structural DELIST events            >= 20
distinct delisted securities        >= 20

all ACTIVE Golden cases             REVIEWED
all REVIEWED source artifacts       resolvable + SHA256 exact
```

Do not satisfy these gates by duplicating observation dates, changing free-form `event_id`, or copying the same event into multiple aliases.

## 3. New P0 findings discovered during PR #15 review

### GT-P0-01 — structural event identity still has a legacy fallback

Current formal identity helpers use:

```text
ST:     (provider_symbol, event_effective_date OR trade_date, event_subtype)
DELIST: (provider_symbol, event_effective_date OR trade_date)
```

Legacy v3 cases often do not carry `event_effective_date`. As a result, repeated observation dates for one real event can appear as multiple “structural” events. This did not make the current gate pass, but it is not an acceptable basis for the next Golden version.

**Required correction:** any ST_TRANSITION or DELIST case eligible for a future Formal Production gate must have an explicit, non-empty, validated `event_effective_date`. Formal distinct-event counting must never fall back to observation `trade_date`.

Legacy immutable candidate versions may remain loadable for diagnostics/history, but they must remain fail-closed for Formal Production when structural event identity is incomplete.

### GT-P0-02 — current candidate/review workflow cannot safely repair legacy structural truth

`scripts/golden/candidate.py` currently adds candidates but does not provide a governed path to drop/replace structurally incorrect legacy candidate rows. `scripts/golden/review.py` can bind an artifact and optionally change `expected_fields`, but cannot repair event identity fields such as effective date/subtype, nor should review silently invent them.

Therefore it is unsafe to simply append new cases to v3 and then review everything.

A new append-only candidate rebuild path is required before corpus work begins.

### GT-P1-03 — manifest “distinct event” statistics must match formal structural semantics

Current version builders summarize `distinct_events` from free-form `event_id`, while the Formal gate intentionally uses structural identities. New manifests must not present a statistic whose meaning differs from the gate.

For new Golden versions, expose/recompute structural counts from the same identity functions used by the formal gate (or rename legacy event-id statistics so the distinction is explicit). The Formal gate must continue recomputing truth from dataset rows rather than trusting manifest claims.

## 4. Work package GT-H1 — Golden Truth contract/tooling closure (START NOW)

This is the only code change authorized before corpus collection/review.

### 4.1 Strict event identity

Implement one authoritative structural identity contract:

```text
ST_TRANSITION:
(provider_symbol, event_effective_date, event_subtype)

DELIST:
(provider_symbol, event_effective_date)
```

Requirements:

1. `event_effective_date` is mandatory for ST_TRANSITION and DELIST in any dataset that can pass `production_formal_gate()`;
2. empty/malformed effective date is a formal-gate blocker;
3. no `trade_date` fallback is permitted for distinct-event qualification;
4. observation `trade_date` remains a separate fact used to test provider state on a date; it must not redefine the real event date;
5. ST subtype remains one of the existing strict ADD/REMOVE families.

### 4.2 Candidate/review validation

Update candidate validation so both ST_TRANSITION and DELIST candidates require explicit effective dates.

Update review validation so a structurally incomplete event case cannot be promoted from COMPILED to REVIEWED even if an artifact is supplied.

While touching this contract, reconcile the candidate event-class allowlist with the runtime typed corporate-action validator. If `RIGHT_ISSUE_EX_DATE` is a supported runtime Golden truth class, candidate tooling must support it with tests; otherwise document and test the intentional dividend-only limitation rather than leaving the two contracts inconsistent.

### 4.3 Append-only clean rebuild workflow

Add a governed rebuild command/tool for the current all-COMPILED candidate lineage. It must create a NEW version and never mutate v1/v2/v3.

Minimum properties:

- input binds exact source `truth_version` + dataset hash;
- explicit operations: KEEP / REPLACE / DROP / ADD (or an equivalent declarative model);
- all replacements/additions remain `COMPILED`;
- no developer/automation action may mark a row REVIEWED;
- validate every output case before any filesystem mutation;
- duplicate case IDs and duplicate structural event aliases fail closed;
- old version files remain immutable;
- new version file + manifest are create-only;
- ACTIVE pointer changes only after the new candidate dataset self-validates;
- a failed build leaves no half-published ACTIVE state.

The rebuild path exists to correct candidate truth, not to rewrite reviewed history.

### 4.4 Manifest honesty

For every newly produced candidate/reviewed version, recompute and expose at least:

- row counts by `case_type`;
- review summary;
- structural ST event count;
- ST ADD count;
- ST REMOVE count;
- structural DELIST event count;
- distinct DELIST security count.

Tests must prove manifest values match the same row-level structural calculation used by the Formal gate.

### 4.5 Required adversarial tests

At minimum:

1. one ST event sampled on 10 dates counts as **one** structural event;
2. one delisted security sampled on 10 post-delist dates counts as **one** DELIST event;
3. missing `event_effective_date` cannot pass Formal Production;
4. free-form `event_id` changes cannot inflate structural counts;
5. ST ADD-only corpus fails REMOVE coverage;
6. review workflow refuses structurally incomplete candidate rows;
7. rebuild can drop/replace a legacy COMPILED row without mutating the old version;
8. rebuild failure has zero ACTIVE-pointer side effects;
9. new manifest structural statistics exactly equal dataset recomputation;
10. existing run-bound immutable Golden replay behavior remains unchanged.

Full three-leg required CI must be green before GT-H1 can close.

## 5. Work package GT-H2 — reviewed Golden corpus reconstruction (BLOCKED BY GT-H1)

Do not start by mass-marking the existing 123 entries REVIEWED.

After GT-H1 is reviewed/merged, build a clean candidate version from independently supportable facts.

### 5.1 Source policy

Preferred truth sources:

- SSE / SZSE / BSE official announcements and rule pages;
- CSRC official documents;
- issuer/company announcements published through official exchange channels;
- official index/rule methodology when relevant.

AI-generated prose, search snippets, provider output, or an unresolvable URL string are not final truth evidence.

Every REVIEWED case must bind actual artifact bytes in the existing content-addressed evidence store; the workflow computes SHA256 from bytes. Hand-typed hashes are prohibited.

### 5.2 Domain coverage

#### ST transitions

Gate minimum: **50 distinct structural transitions**.

Collection should include both ADD and REMOVE families and span more than one board/exchange where official evidence permits. Repeated observation dates may remain useful validation cases, but they do not count as new transitions.

Prefer 2020-01-01 onward facts to match the platform history contract. Use pre-2020 facts only when a rule transition affecting the 2020+ platform cannot be tested honestly without them; no pre-2020 backfill is authorized.

#### Delisting

Gate minimum: **20 distinct delisted securities**, each with the exact delisting effective date supported by official evidence.

Do not turn multiple post-delist query dates for the same symbol into multiple events.

#### Limit regime

At least 30 REVIEWED cases covering the platform-relevant 2020+ regime matrix: main board, ST, ChiNext reform boundary, STAR, BSE, IPO/no-limit semantics where applicable.

Rulebook evidence may support multiple cases only when the artifact actually proves the exact rule used by each case.

#### Corporate action

At least 20 REVIEWED cases with exact ex-date/event-type truth and evidence appropriate to the typed validator. Where runtime supports both dividend and right-issue streams, include both rather than silently validating only one endpoint family.

#### BJ mapping / negative samples

Retain independently supportable BJ mapping and useful negative samples, but do not count negative samples as ST transition events.

### 5.3 Review packet before sealing

Developer/automation prepares a human-review packet; it does **not** self-approve it.

For each proposed case include:

- golden_case_id;
- case_type;
- symbol;
- observation trade_date;
- event class/subtype/effective date when applicable;
- expected fields;
- official source type;
- content-addressed artifact ref + hash;
- concise claim that the artifact is meant to prove;
- whether the artifact is reused by other cases and why that reuse is valid.

Human reviewer/Owner must make the actual review decision. `reviewed_by` must correspond to a genuine human review record; a development agent must not write `project-owner` or another human marker merely to satisfy the gate.

Where many cases share one official source, the packet may group them by artifact for efficient human review, but the final dataset still needs case-level provenance and every case must pass the formal review gate.

## 6. Work package GT-H3 — reviewed version seal and pre-Production qualification

After human decisions are complete:

1. batch-run the governed review/seal workflow;
2. produce a new immutable REVIEWED Golden version;
3. re-open it through `GoldenTruthStore`;
4. run `production_formal_gate()` against that exact dataset and require **zero problems**;
5. verify source artifacts resolve and hashes match for every REVIEWED case;
6. verify ACTIVE manifest and dataset hash exactly match;
7. run focused Golden tests + full three-leg CI;
8. open a focused Golden qualification PR;
9. wait for independent Reviewer closure and merge.

Only after GT-H3 merges may one new Formal Production B1-B7 attempt be authorized.

## 7. Formal Production remains frozen

Until GT-H1/H2/H3 are closed:

```text
new Production B1-B7 attempt       NOT AUTHORIZED
Production --resume                NOT APPLICABLE (no run_id exists)
formal verdict                     BLOCKED
Data Sufficiency Matrix            BLOCKED
Provider GO/CONDITIONAL GO/NO-GO   BLOCKED
2020+ backfill                     BLOCKED
strategy/backtest/trading          OUT OF SCOPE
```

Do not change the frozen production identity. Do not weaken Golden thresholds. Do not use Trial/dry-run/doctor/T1 evidence as a substitute.

## 8. Immediate developer task

**Implement GT-H1 only.**

Recommended PR title:

```text
fix: close Golden structural truth and rebuild-contract gaps
```

Required scope:

- strict ST/DELIST effective-date structural identity;
- candidate/review strict validation;
- append-only clean candidate rebuild path;
- structural manifest statistics;
- focused adversarial tests;
- DEVLOG / DEVELOPMENT_MANAGEMENT / Golden runbook truth sync;
- full three-platform required CI.

Do not add dozens of new Golden facts in the same PR. Tool/contract correctness must be independently reviewed before corpus construction begins.
