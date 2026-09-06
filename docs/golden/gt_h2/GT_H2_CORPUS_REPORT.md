# GT-H2 Clean Golden Corpus Candidate Report

- Target truth version: `v4-candidate-20260906`
- ACTIVE dataset: `golden_cases_v4.jsonl`
- ACTIVE dataset SHA256: `9ccf0a69774616fcfecdc9fae67f9c6eb13a18ceaf1ae646cff6e32ab854f34a`
- Source ACTIVE: `v3-candidate-20260822` / `golden_cases_v3.jsonl` / `ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e`
- Scope: candidate corpus construction only. This report does not claim human review, Production B1-B7, Data Sufficiency, provider entitlement, 2020+ backfill, strategy, backtest, or trading readiness.

## Rebuild decision

The plan contains `198` explicit operations: `KEEP=0`, `REPLACE=53`, `DROP=70`, `ADD=75`.
Every old v3 row is addressed exactly once. Structural/negative rows dropped by class: `{'DELIST': 20, 'NEGATIVE_SAMPLE': 40, 'ST_TRANSITION': 10}`.
All old v1/v2/v3 files remain immutable inputs; the plan does not edit or rewrite them. The old non-structural rows are REPLACE operations so their case identities remain traceable while official rule/disclosure locators are made explicit.

## Candidate counts and structural gates

- Case count: `128`
- Counts by type: `{'golden_bj_mapping': 3, 'golden_corporate_action': 25, 'golden_delisted': 20, 'golden_limit_regime': 30, 'golden_st_transition': 50}`
- Registry additions by event class: `{'DELIST': 20, 'RIGHT_ISSUE_EX_DATE': 5, 'ST_TRANSITION': 50}`
- Distinct ST structural events: `50`; ADD `38`; REMOVE `12`.
- Distinct DELIST structural events: `20`; securities `20`.
- No structural identity uses `trade_date` as an implicit effective date. For the new single-observation cases, equality is intentional and stated in the packet date semantics/checklist.

### ST distribution

`{"board": {"CHINEXT": 15, "MAIN": 34, "STAR": 1}, "exchange": {"SSE": 4, "SZSE": 46}, "subtype": {"STAR_ST_ADD": 1, "ST_ADD": 37, "ST_REMOVE": 12}, "year": {"2020": 7, "2021": 7, "2022": 13, "2023": 6, "2024": 15, "2025": 2}}`

### DELIST distribution

`{"board": {"CHINEXT": 3, "MAIN": 17}, "exchange": {"SSE": 12, "SZSE": 8}, "subtype": {"": 20}, "year": {"2020": 1, "2021": 1, "2022": 5, "2023": 4, "2024": 2, "2025": 6, "2026": 1}}`

## Review packet

- Packet path: `docs/golden/gt_h2/review_packet_index.jsonl`
- Packet rows: `128`; unique IDs: `128`; dataset rows: `128`.
- Exact coverage check: PASS — every candidate case appears exactly once, with event fields, expected fields, official source name/ref, candidate artifact kind, fact_proved flag, and a human checklist.
- `fact_proved` is an Agent source-inspection flag only. It is not a human review seal and does not populate `source_artifact_ref`, `source_artifact_hash`, `reviewed_by`, or `reviewed_at`.
- No raw bulk web pages or PDFs are committed; the packet stores official references only.

## Local gate evidence

- `GoldenTruthStore.load`: PASS (`v4-candidate-20260906`, schema `2`).
- `review_readiness_gate`: `PASS`
- `production_formal_gate`: expected candidate result contains only the human-review blocker: `['golden truth not fully human-reviewed (REVIEWED 0/128; audit section 39 requires every golden entry reviewed before P0-M-1B)']`
- The candidate publisher and this utility never invoke `scripts/golden/review.py` final sealing. The only intended formal blocker after candidate construction is human review plus exact artifact binding.

## Immutable lineage evidence

The following hashes use repository-canonical text bytes (LF; JSON manifests ignore one local terminal LF) and must remain unchanged:

| File | SHA256 |
| --- | --- |
| `golden_cases_v1.jsonl` | `b19b807612ca20436aeb766ba216ff47880c9ed6bd5843e446e547841612c1c8` |
| `golden_cases_v2.jsonl` | `d36c1845c0780a3a063919062c3a55aa2227e98152a1993319a0f1cf4b3c1631` |
| `golden_cases_v3.jsonl` | `ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e` |
| `truth_manifest_v2.json` | `902eee047d73b578a3de28fd0e9f610a52dadf5f836ae9b5b6eef21195f8ca80` |
| `truth_manifest_v3.json` | `9f77fc6e6487f7ffa97b3d56647ad9008ca9ebd06f3788f73a63f492028e1937` |

## Human review hand-off

1. Verify each official source locator and bind the exact downloaded artifact under the evidence store.
2. Check symbol, board/exchange, date semantics, subtype/action type, and expected fields against the artifact.
3. Run the repository review workflow to create the reviewed version only after all cases pass; do not treat this candidate report or `fact_proved` as REVIEWED evidence.
4. Keep CR-5/CR-6, Production B1-B7, Data Sufficiency, provider decisions, credentials/tokens, and raw SDK/profile material outside this corpus PR.
