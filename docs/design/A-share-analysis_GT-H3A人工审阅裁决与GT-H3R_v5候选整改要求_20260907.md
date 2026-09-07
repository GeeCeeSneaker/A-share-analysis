# A-share-analysis GT-H3A 人工审阅裁决与 GT-H3R v5 候选整改要求

> 日期：2026-09-07  
> 状态：**GT-H3A HUMAN REVIEW COMPLETED WITH REJECTIONS / GT-H3R AUTHORIZED / NOT SEALED**

## 1. 权威基线

- GT-H2 merged candidate baseline: `v4-candidate-20260906`
- v4 dataset SHA256: `8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`
- GT-H3A PR: `#19`
- GT-H3A final head: `4198b21f78a87ab9a21ed9cc8fb07822bae25492`
- GT-H3A test-merge: `b0ca9a3230d18593036e58c3b4e8ffc3966435ab` = `main@9979a0545531010b6b71fefe1f5d465aab349991 + PR#19 head`
- GT-H3A final CI: run `34088606735` / #345, Ubuntu 3.14 + Windows 3.12 + Windows 3.14 all SUCCESS
- GT-H3A Reviewer adjudication: review `5128750265`
- GT-H3A merge commit: `09bdfc9811ab03480490c38d223752e3e795804d`

GT-H3A recorded a structurally complete real-human result over all 125 v4 cases:

- `APPROVE`: 113
- `REJECT`: 12
- duplicate case IDs: 0
- missing case IDs: 0
- ACTIVE remained `COMPILED 125/125`
- no evidence bytes/hash publication
- no `review.py`
- no reviewed dataset
- no ACTIVE pointer advance

**Management verdict:** PR #19 is accepted only as an immutable Human Review / audit record. The v4 candidate is **NOT QUALIFIED FOR SEAL**.

---

## 2. 12 个 REJECT 的项目管理裁决

The 12 rejects are not one homogeneous class. Treating all of them as candidate-fact failures would waste the 113 accepted reviews; treating all of them as source-only failures would be factually wrong.

### 2.1 Evidence-only defects — 10 cases

The Golden expected semantics remain valid. Replace the incorrect/dead official locator with an exact official artifact and send only these corrected rows back to Human Review.

#### AG-054 — ChiNext 20% regime — 5 cases

Affected:

- `GT-LIMIT-CN20-300015`
- `GT-LIMIT-CN20-300059`
- `GT-LIMIT-CN20-300124`
- `GT-LIMIT-CN20-300274`
- `GT-LIMIT-CN20-300750`

Human reject reason: the current locator is only the publication notice page and does not itself expose the 20% clause.

Reviewer verification: the official SZSE attachment **《深圳证券交易所创业板交易特别规定》** explicitly states in §2.1 that ChiNext stock auction trading has a 20% price limit, and IPO stocks have no price limit for the first five trading days.

Preferred exact official artifact:

`https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf`

Required action: **source/artifact replacement only**. Do not alter provider symbol, trade date, event class, event id, expected fields, or truth semantics.

#### AG-025 — SSE main-board ST 5% regime — 2 cases

Affected:

- `GT-LIMIT-ST5-600518-20190603`
- `GT-LIMIT-ST5-600518-20191028`

Human reject reason: the existing locator points to an unrelated 0.01-yuan minimum-price-unit notice and does not prove the 5% limit.

Reviewer verification: the official SSE **《上海证券交易所风险警示板股票交易暂行办法》** (effective 2013-01-01) states in Article 7 that risk-warning stock price limits are 5%, which covers both 2019 observation dates.

Preferred exact official artifact:

`https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml`

Required action: **source/artifact replacement only**. No Golden semantic change.

#### AG-029 — pre-2023 SSE IPO first-day +44%/-36% — 2 cases

Affected:

- `GT-LIMIT-IPO44-601995`
- `GT-LIMIT-IPO44-605499`

Human reject reason: current locator resolves to an old generic trading rule saying IPO first day is generally exempt from ordinary daily price limits and does not prove the special 44%/-36% first-day control.

Reviewer verification: SSE's 2014 **《关于新股上市初期交易监管有关事项的通知》** states that on IPO day the call-auction valid range is 80%-120% of issue price and continuous-auction valid declarations may not exceed 144% or fall below 64% of issue price. This is the correct source contract for the existing +44%/-36% semantics.

Preferred exact official artifact:

`https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml`

Required action: **source/artifact replacement only**. Do not change `PRICE_HIGH_LMT_RATE=0.44` / `PRICE_LOW_LMT_RATE=0.36` unless a separate candidate-level semantic review finds another problem.

#### AG-064 — 002022 ST effective 2022-05-06 — 1 case

Affected:

- `GT-H2-ST-ST_ADD-002022-20220506`

Human reject reason: current source URL returns HTTP 404.

Reviewer verification: official SZSE disclosures independently confirm that the company disclosed the risk-warning announcement on 2022-04-30 and that stock trading was placed under delisting/other risk warning from 2022-05-06.

Required action:

1. Prefer a contemporaneous official 2022 exchange/CNINFO disclosure that directly states the 2022-05-06 effective date.
2. If the original file cannot be resolved, an exact official later disclosure that explicitly states the historical effective date is an acceptable fallback, but the packet must label it as retrospective official evidence rather than the original announcement.
3. Do not change event date/subtype/expected fields merely because the old URL died.

### 2.2 Candidate-fact defects — 2 cases

These cannot be fixed by swapping URLs. They must become new v5 candidate semantics before re-review.

#### AG-027 — `GT-LIMIT-STARNO-20200723`

Current claim: 688981.SH on 2020-07-23 is still inside the first five listing days and therefore has no price limit.

Reviewer verification:

- SSE official listing announcement: 688981 began trading on **2020-07-16**.
- Trading days 1-5 were 2020-07-16, 07-17, 07-20, 07-21, 07-22.
- Therefore **2020-07-23 is trading day 6** and the no-limit claim is false.

Preferred remediation: preserve this row as a useful boundary test instead of dropping/filling it.

Convert it into the first constrained-day STAR 20% boundary case, consistent with the existing `REGIME-STAR-20` contract. Recommended semantics:

- provider symbol: `688981.SH`
- trade date: `20200723`
- event class: `LIMIT_REGIME`
- event id: `REGIME-STAR-20`
- expected high-limit rate: `0.2` using the existing STAR20 field contract
- truth claim: first trading day after the five no-limit listing days / STAR 20% regime
- case ID should be rekeyed to reflect the new semantics and date rather than retaining a misleading `STARNO` identity.

The existing valid 2020-07-22 no-limit case should remain unchanged. Together, 2020-07-22 (day 5, no limit) + 2020-07-23 (day 6, 20%) form a valuable regime-boundary pair.

#### AG-096 — `GT-H2-ST-ST_ADD-300965-20240429`

Current structural effective date: `20240429`.

Reviewer verification: official disclosure states 300965 stock was placed under delisting risk warning **from 2024-04-26**. The v4 structural date is therefore wrong.

Required v5 correction:

- event effective date: `20240426`
- trade date: `20240426` under the current single event-day observation convention
- event subtype: unchanged (`ST_ADD`)
- expected `IS_ST_SEC=true`: unchanged
- rekey case ID to the corrected date
- use the contemporaneous official 2024 disclosure where possible, not a 2025 retrospective document.

Preferred contemporaneous official disclosure locator discovered during Reviewer verification:

`https://static.cninfo.com.cn/finalpage/2024-04-25/1219804789.PDF`

---

## 3. v4 must remain immutable; create v5 candidate

Do **not** edit `golden_cases_v4.jsonl`, `truth_manifest_v4.json`, or any prior version file.

GT-H3R must create a new immutable candidate version (expected `v5-candidate-*`) from the exact v4 source binding.

Source binding:

```text
truth_version = v4-candidate-20260906
dataset_hash  = 8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b
case_count    = 125
```

Use the existing governed candidate/rebuild path if it supports v4 -> v5 cleanly. If a minimal extension is required, add focused tests; do not create an alternate ad-hoc writer.

### Exact change-scope contract

The new candidate must remain 125 rows.

- 113 previously APPROVE rows: **semantic identity frozen**.
- 10 evidence-only rejected rows: only source/evidence metadata may change.
- 2 candidate-fact rejected rows: only the adjudicated semantic corrections above may change.
- No filler cases.
- No opportunistic cleanup of unrelated v4 rows in the same PR.

---

## 4. Preserve 113 prior human approvals by semantic-hash carry-forward

Do **not** ask the Human Reviewer to repeat 113 unchanged reviews.

Create a machine-verifiable carry-forward ledger, suggested path:

`docs/golden/gt_h3/remediation/v4_to_v5_human_review_carry_forward.jsonl`

For every v4 case, include at least:

- old_case_id
- new_case_id
- old_case_semantic_hash
- new_case_semantic_hash
- prior_decision
- prior_reviewed_by
- prior_reviewed_at
- carry_forward_eligible
- reason

### Carry-forward gate

Exactly 113 rows must satisfy all of:

```text
prior_decision == APPROVE
old_case_id == new_case_id
old_case_semantic_hash == new_case_semantic_hash
carry_forward_eligible == true
```

Exactly the 12 prior REJECT rows must have `carry_forward_eligible == false`.

Any unexpected semantic-hash change outside those 12 cases is a **P0 FAIL** and blocks the PR.

This ledger records Human Review decision continuity only. It must not write `REVIEWED` into the Golden dataset and is not a substitute for final evidence-byte binding.

---

## 5. GT-H3R human re-review scope: only 12 corrected cases

After v5 candidate construction and Reviewer technical closure, regenerate a delta Human Review packet/table containing the 12 corrected rows only.

The Human Reviewer must re-open the corrected exact official artifacts and provide APPROVE/REJECT for all 12.

Do not automatically convert previous REJECT to APPROVE.

When all 12 are approved, construct a combined logical authorization set:

- 113 carried-forward prior APPROVE decisions, proven unchanged by semantic hashes
- 12 new APPROVE decisions on v5

Only then may the real Human Reviewer issue the final complete authorization statement for the v5 125-case set.

---

## 6. Human marker / ambiguous `50` / workbook formula

The v4 workbook contains `review_note = "50"` on 113 APPROVE rows. This value has no defined Golden semantic meaning.

Do not infer its meaning and do not propagate it into final reviewed provenance as if it were a rule/page/fact.

Before GT-H3B, the real Human Reviewer must explicitly confirm that:

1. the 113 v4 APPROVE decisions were intentional;
2. the value `50` is non-semantic / accidental / safe to normalize to blank unless the reviewer supplies a defined meaning;
3. the human marker to use for final review provenance is explicitly identified.

A concise PR comment is sufficient; no 113-row re-review is required if the carry-forward gate passes.

The workbook `#NAME?` summary-formula issue is a **P2 review-UI defect**, not a Golden Truth blocker because direct row counting already establishes 113/12. Fix the generated workbook formulas for the 12-case re-review table so the next human-facing file does not display broken summary formulas.

---

## 7. GT-H3R exit gates before Reviewer merge authorization

The remediation PR must remain open/unmerged until all are true:

```text
ACTIVE truth version                 == v5 candidate
ACTIVE case count                    == 125
review_summary                       == COMPILED 125/125
review_readiness_gate                == []
quantity_gate                        == []
event_coverage_gate                  == []
production_formal_gate problems      == only human-review blocker

v4 version files                     byte-identical / immutable
113 approved rows                    exact semantic-hash carry-forward
12 rejected rows                     carry-forward false
10 evidence-only rows                expected semantics unchanged
2 fact-error rows                    corrected exactly per Reviewer verdict
human re-review delta                exactly 12 cases
review.py                            NOT RUN
reviewed dataset                     NOT CREATED
ACTIVE reviewed pointer              NOT CREATED
```

PR body must include:

- source main SHA
- v4 source truth version/hash
- v5 dataset hash
- exact 12-case change table
- 113 carry-forward count and hash proof
- 12 non-carry-forward count
- v5 counts/gates
- no seal / no Production statement
- final required three-platform CI run ID

Required CI on final head/test-merge:

- Windows latest / Python 3.14
- Windows latest / Python 3.12
- Ubuntu latest / Python 3.14
- Ruff
- format check
- mypy
- full pytest
- Spike dry-run/framework gates
- SDK-absent
- DEVLOG gate
- Management gate

Because PR CI runs against GitHub's generated merge ref, Reviewer must verify the actual test-merge SHA is composed from the current main + final PR head.

---

## 8. PR scope / naming

Use a separate remediation PR. Suggested title:

`fix: remediate GT-H3 rejected golden cases`

Do not reuse PR #19 for Golden corrections. PR #19 is now the immutable record of the first Human Review pass.

The remediation PR may include only:

- v5 candidate/version manifest/ACTIVE candidate pointer
- exact 12-case source/semantic corrections
- carry-forward ledger
- regenerated GT-H3 remediation bundle / 12-case review table
- focused tests
- DEVLOG / Development Management

It must not include:

- `review.py` execution
- final REVIEWED seal
- Production B1-B7
- Data Sufficiency verdict
- Provider capability approval
- historical backfill
- strategy/backtest/trading work
- credentials/tokens/endpoints/raw SDK output/proprietary SDK

---

## 9. GT-H3B remains blocked

GT-H3B is authorized only after:

1. v5 remediation PR is independently Reviewer-verified and merged;
2. the Human Reviewer approves all 12 corrected rows;
3. the 113 carry-forward gate passes;
4. the Human Reviewer explicitly authorizes the complete v5 125/125 set and provides the final human marker;
5. the ambiguous `50` note is explicitly neutralized/defined.

Only then may GT-H3B retrieve/bind exact evidence bytes and construct the full 125-row executable review manifest (`case`, `artifact`, `kind`, `note` only), followed by one atomic `review.py` N/N seal.

Until all five conditions are satisfied:

```text
GT-H3B                      BLOCKED
review.py                   BLOCKED
Formal Production B1-B7     BLOCKED
Data Sufficiency            BLOCKED
Provider capability verdict BLOCKED
2020+ backfill              BLOCKED
```
