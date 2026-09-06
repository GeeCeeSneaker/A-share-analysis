# A-share-analysis GT-H2 关闭与 GT-H3 Human Review 原子封印执行要求

> Date: 2026-09-06  
> Authoritative baseline: `cbe5916cbe9cbe006ad3cc47500c3291c059d848`  
> PR #18 final reviewed head: `c5711f8fc8f1646f02535bee974204daa240a44e`  
> Reviewer closure: `5125393678`  
> Required CI: run 338 / `34033318684` — Windows 3.14 / Windows 3.12 / Ubuntu 3.14 SUCCESS  
> Status: **GT-H2 CLOSED; GT-H3 HUMAN REVIEW PREPARATION AUTHORIZED; PRODUCTION STILL BLOCKED**

## 1. GT-H2 final closure

GT-H2 clean Golden candidate is now closed and merged.

Current ACTIVE Golden contract:

- `truth_version = v4-candidate-20260906`
- `manifest_schema = 2`
- dataset: `golden_cases_v4.jsonl`
- dataset SHA256: `8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`
- case count: `125`
- review summary: `COMPILED 125 / REVIEWED 0`
- ST: `50` rows / `50` structural events
- DELIST: `20` rows / `20` structural events / `20` securities
- LIMIT: `30`
- CORPORATE ACTION: `25` (`20` dividend + `5` right issue)
- `golden_bj_mapping`: intentionally `0`; BJ old/new-code migration and 920-segment capability are deferred until a separate executable Provider capability/Data Sufficiency contract exists.

The following prior closures are frozen and must not be reopened without new evidence:

- GT-H1 / H1.1 / H1.2 structural identity, clean rebuild and atomic full-corpus review publication;
- GT-H2.1 exact official locators, source quality, ST representativeness, 2020+ right-issue coverage;
- GT-H2.2 STAR20 vs ST5 exact semantic evidence mapping;
- GT-H2.2.1 BJ external-artifact honesty.

## 2. GT-H3 objective

GT-H3 has one purpose only:

> Convert the clean `COMPILED 125/125` candidate into one immutable, content-addressed, fully human-reviewed Golden version via a single atomic `125/125` seal.

GT-H3 is **not** a new corpus-construction phase. It must not use Human Review as a back door to alter Golden facts.

At GT-H3 exit:

```text
ACTIVE                  = reviewed immutable version
review_summary          = REVIEWED 125/125
COMPILED                = 0
quantity_gate           = []
event_coverage_gate     = []
review_gate             = []
production_formal_gate  = []
all evidence refs       = resolvable + exact hash match
```

Even after these conditions are met, Formal Production B1-B7 remains blocked until the GT-H3 PR passes final CI, receives independent Reviewer closure, and is merged.

## 3. Non-negotiable review boundary

### 3.1 Human identity only

`reviewed_by` is a genuine human-review provenance field.

Developer agents, Codex, scripts, bots and the project Reviewer AI may prepare evidence and perform consistency checks, but **must not self-assert Human Review**.

A real Owner/Reviewer must explicitly authorize the full review decision before `review.py` is allowed to publish the reviewed ACTIVE version.

### 3.2 No partial ACTIVE review

The GT-H1.2 contract remains frozen:

- no `1/125`, `N-1/125` or staged partial ACTIVE publication;
- submitted review case IDs must equal ACTIVE case IDs exactly once;
- duplicate, missing or foreign IDs fail before durable publication;
- one seal converts all 125 rows together.

Human inspection may be performed incrementally, but publication is atomic `125/125`.

### 3.3 Review must not mutate Golden truth

For GT-H3, the review manifest must **not use `expect_fields` to change `expected_fields`**.

If Human Review finds any of the following wrong:

- symbol;
- trade date;
- event effective date;
- event subtype/class;
- expected fields;
- source claim;
- source locator;
- artifact does not prove the case;

then the case is **REJECTED**, GT-H3 seal stops, and the candidate must return to a governed candidate-correction path. Do not repair truth inside `review.py`.

## 4. GT-H3A — review bundle preparation

Use one GT-H3 PR with two checkpoints rather than creating unnecessary parallel workflows.

First checkpoint is **GT-H3A PREPARED / NOT SEALED**.

Developer shall prepare a review bundle derived from the merged 125-row ACTIVE candidate and `docs/golden/gt_h2/review_packet_index.jsonl`.

Required tracked outputs:

```text
docs/golden/gt_h3/GT_H3_REVIEW_BUNDLE.md
docs/golden/gt_h3/review_bundle_index.jsonl
docs/golden/gt_h3/review_decision_template.jsonl
```

The bundle index is artifact-group oriented to reduce Human Review burden. Multiple cases may share the same official rule or announcement artifact.

Each artifact group must record at least:

```text
artifact_group_id
official_source_name
official_source_ref
artifact_kind_candidate
case_ids[]
case_count
claim_summary
case-specific expected semantics summary
retrieval status
retrieval/final URL when redirects occur
proposed local artifact filename
preflight SHA256 of retrieved bytes
```

The preflight SHA256 is only a preparation aid. The authoritative review hash remains the hash recomputed by `review.py` from the actual bytes used during the seal.

## 5. Evidence-byte acquisition rules

For every unique official source artifact:

1. Retrieve the exact official artifact referenced by the candidate.
2. Preserve original bytes whenever available.
3. For official PDF, use the original PDF bytes.
4. For official HTML, preserve the raw retrieved official response/body as the review artifact; do not replace it with copied text or a browser-generated PDF unless the original source itself is only available that way and the reason is documented.
5. Record redirects/final URL without silently changing the Golden source claim.
6. Do not use screenshots, summaries, AI prose, search-result pages, media mirrors or Provider output as substitutes for the official evidence artifact.
7. The same exact artifact may be reused across multiple cases; content-addressing will deduplicate identical bytes.
8. If a source cannot be retrieved, has materially changed, or does not prove the case, mark that case/group `BLOCKED` and do not run the seal.

Developer may keep retrieval inputs in a local untracked working directory. Do not duplicate large source binaries into a temporary tracked staging tree merely for workflow convenience; final durable bytes belong in the content-addressed Golden evidence store created by `review.py`.

## 6. Human Review decision contract

Human Review should operate primarily by unique artifact group, but approval must remain traceable to every case.

For each artifact group the Human Reviewer verifies:

- official issuer/exchange identity;
- correct document/rule version;
- source applies to the case date and market/board;
- case symbol/date identity;
- expected semantic assertion;
- for ST/DELIST, exact effective date and subtype;
- for dividend/right issue, exact ex-date/event type;
- for limit rules, exact applicable regime and rate/no-limit semantics;
- no stronger claim is being inferred than the artifact actually proves.

Permitted human decisions:

```text
APPROVE
REJECT
```

No agent may manufacture the decision.

Grouped approval is permitted when one artifact genuinely proves multiple cases, but `review_decision_template.jsonl` must still contain one case-level row for all 125 cases, including a concise review note and the artifact group used.

Before sealing, there must be an explicit Owner/Human Reviewer statement authorizing the complete `125/125` review set and identifying the human reviewer marker to be written as `reviewed_by`.

## 7. GT-H3B — atomic seal execution

Only after explicit Human approval of the complete review set may the developer construct the executable review manifest.

The executable manifest must be a JSON list with exactly 125 entries and only the existing `review.py` contract fields needed for GT-H3:

```json
{
  "case": "<golden_case_id>",
  "artifact": "<local path to exact reviewed artifact bytes>",
  "kind": "<allowed artifact kind>",
  "note": "<human review note>"
}
```

Do not include `expect_fields` in the GT-H3 seal manifest.

Execute only the existing atomic path:

```bash
uv run python scripts/golden/review.py \
  --manifest <review-batch.json> \
  --reviewer <genuine-human-reviewer-id>
```

Expected publication semantics:

- all artifacts staged and validated before durable publication;
- real bytes hashed by the workflow;
- content-addressed evidence under `data/golden/provider/amazingdata/evidence/sha256/`;
- all 125 cases become REVIEWED in memory before any ACTIVE publication;
- new reviewed dataset/manifest are create-only;
- ACTIVE pointer moves last and atomically;
- any missing/duplicate/foreign case, invalid artifact kind, missing artifact, changed artifact bytes, hash mismatch, semantic self-validation failure or version collision fails closed.

Do not modify `review.py` in the seal commit merely to make the batch pass. If tooling has a genuine defect, stop and fix/review the tooling separately before Human seal publication.

## 8. Seal-output verification

After the seal, before commit/PR handoff, verify all of the following:

```text
[ ] ACTIVE truth version is the newly reviewed version
[ ] ACTIVE dataset hash matches exact reviewed dataset bytes
[ ] review_summary == {"REVIEWED": 125}
[ ] no case remains COMPILED
[ ] every reviewed_by equals the authorized human marker
[ ] every reviewed_at is populated
[ ] every review_note is populated or intentionally concise
[ ] every source_artifact_ref resolves under evidence/sha256
[ ] every source_artifact_hash equals the referenced artifact bytes
[ ] every source_artifact_kind is allowlisted
[ ] every source_retrieved_at is populated
[ ] all case semantic hashes self-validate
[ ] manifest schema-2 statistics equal recomputation
[ ] quantity_gate == []
[ ] event_coverage_gate == []
[ ] review_gate == []
[ ] production_formal_gate == []
[ ] old v1-v4 datasets/manifests remain immutable
[ ] run-bound historical Golden replay remains unchanged
```

Add adversarial tests where not already covered for at least:

- missing artifact;
- artifact changed between stage and commit;
- wrong artifact kind;
- partial 124/125 batch;
- duplicate case;
- foreign case;
- attempted `expect_fields` mutation in the GT-H3 wrapper/preparation path;
- tampered sealed evidence after review => Formal fail closed;
- reviewed manifest stats mismatch => loader fail closed;
- old v4 bound replay unchanged after ACTIVE advances.

## 9. GT-H3 PR governance

Use one GT-H3 branch/PR with two explicit checkpoints:

### Checkpoint A — PREPARED / NOT SEALED

PR contains the review bundle/index/template and preparation tooling/tests only.

Required state:

```text
ACTIVE = v4 candidate
COMPILED 125/125
REVIEWED 0/125
no evidence seal
```

Developer posts the bundle for Human Review and waits for explicit human approval. This is the only point where human action is required.

### Checkpoint B — HUMAN APPROVED / SEALED

After the explicit human decision, the same PR may receive the atomic seal commit containing:

- content-addressed evidence bytes;
- reviewed dataset;
- reviewed versioned manifest;
- ACTIVE reviewed manifest;
- case-level review provenance;
- updated GT-H3 report / DEVLOG / development-management state;
- focused and full regression evidence.

Then run required CI on the final head:

```text
Windows Python 3.14
Windows Python 3.12
Ubuntu Python 3.14
Ruff lint + format
mypy
full pytest
Spike gates
SDK-absent gate
DEVLOG gate
Management-doc gate
```

No merge before independent Reviewer closure.

## 10. Scope explicitly still blocked

Until GT-H3 final Reviewer closure and merge:

```text
Formal Production B1-B7       BLOCKED
Production verdict            BLOCKED
Data Sufficiency Matrix       BLOCKED
Provider capability approval  BLOCKED
2020+ historical backfill     BLOCKED
strategy/backtest integration BLOCKED
```

After GT-H3 is merged, the next action is **one** controlled Formal Production B1-B7 attempt on the latest complete Provider trading day. GT-H3 itself must not contain or trigger that Production run.

## 11. Current project state

```text
AUDIT-H1                      CLOSED
T1 / T2 / T3 identity        VERIFIED / FROZEN
GT-H1 / H1.1 / H1.2          CLOSED
GT-H2 / H2.1 / H2.2 / H2.2.1 CLOSED
GT-H3 Human Review            AUTHORIZED / CURRENT TASK
Formal Production B1-B7       BLOCKED
Data Sufficiency              BLOCKED
Provider capability decision  BLOCKED
2020+ backfill                BLOCKED
```
