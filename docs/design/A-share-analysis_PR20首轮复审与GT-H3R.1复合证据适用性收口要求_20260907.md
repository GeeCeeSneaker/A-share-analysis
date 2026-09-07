# A-share-analysis PR #20 首轮复审与 GT-H3R.1 复合证据适用性收口要求

> 日期：2026-09-07  
> 状态：**GT-H3R MECHANICS / CARRY-FORWARD VERIFIED；GT-H3R.1 EVIDENCE-APPLICABILITY CLOSURE REQUIRED；DO NOT MERGE**

## 1. 本轮权威基线

- current main before this management commit: `277ef6fabac265eb70081231923b9a4a8487417f`
- PR: `#20` — `fix: remediate GT-H3 rejected golden cases`
- reviewed head: `e0f2abc6379f880614febbd33f0325396bc49cb3`
- GitHub test-merge: `5def7d358e11bdacddd1886fe1ae64e8fbaad1e3`
- test-merge composition: `main@277ef6fabac265eb70081231923b9a4a8487417f + PR head@e0f2abc6379f880614febbd33f0325396bc49cb3`
- final CI reviewed: run `34101070518` / #350 — Windows py3.14, Windows py3.12, Ubuntu py3.14 all SUCCESS
- Reviewer review: `5130031817`

## 2. 已验证关闭 / 必须保留

以下内容本轮视为 **PASS / KEEP**，除非后续修复直接触碰其契约，否则不要重复重做：

1. v4 source binding 保持不可变：
   - `v4-candidate-20260906`
   - SHA256 `8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`
2. v5 candidate：
   - `v5-candidate-20260907`
   - SHA256 `5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c`
   - 125 rows / `COMPILED 125/125`
3. v4→v5 rebuild scope exact：`KEEP 113 / REPLACE 12 / DROP 0 / ADD 0`。
4. `review_identity_hash_for_doc()` 的设计正确：仅排除 `truth_version`，仍绑定 `golden_case_id`、symbol、trade date、expected fields、truth source、source ref、artifact hash 及 v4+ structural event fields。
5. carry-forward：
   - 113 个 prior `APPROVE`：same case ID + same version-neutral review identity hash → `carry_forward_eligible=true`
   - 12 个 prior `REJECT`：全部 `carry_forward_eligible=false`
6. 10 个 evidence-only case 没有修改 expected semantics；2 个 fact-correction case 严格按 Reviewer 裁决更正并 rekey。
7. v5 non-review gates：
   - `review_readiness_gate == []`
   - `quantity_gate == []`
   - `event_coverage_gate == []`
   - `production_formal_gate()` 仅剩 human-review blocker
8. 未运行 `review.py`，未产生 REVIEWED Golden、evidence-byte publication、reviewed ACTIVE pointer、Production B1-B7、Data Sufficiency、Provider verdict 或 backfill。

## 3. 新阻塞：GT-H3R.1 P0-01 — 复合事实的证据适用性不完整

当前 12-case delta review table 对部分 case 只列出一个**制度规则 artifact**，但 Human Reviewer 被要求同时判断：

- 规则本身是什么；以及
- 指定证券在指定日期是否确实处于该规则适用状态。

一个规则文件通常只能证明第一层，不能自动证明第二层。如果现在直接进入第二次 Human Review，很容易再次出现“规则正确，但该材料没有证明这个证券/日期”的 REJECT；更严重的是，GT-H3B 当前单 artifact/hash 的 seal 语义会把一个 artifact 夸大成整个复合事实的完整证据。

本阻塞只影响 **5 个当前整改 case**。不得因此重开 113 个已 carry-forward 的 APPROVE，也不得借机修改现有 v5 Golden semantics。

### 3.1 AG-027 — 688981 2020-07-23 STAR 20% 边界

Case：`GT-LIMIT-STAR20-688981-20200723`

当前 STAR rule artifact 能证明：科创板前五个上市交易日不设涨跌幅限制、之后进入 20% 制度。

但还必须有独立官方材料证明：`688981` 自 **2020-07-16** 起上市交易，从而 `2020-07-23` 是第 6 个交易日。

已定位可用的 SSE 官方上市公告：

`https://www.sse.com.cn/disclosure/announcement/listing/c/c_20200713_5152912.shtml`

Human Review 对该 case 必须同时核：

1. STAR rule；
2. 688981 listing-date announcement。

### 3.2 AG-029 — 两个主板 IPO +44%/-36% case

Cases：

- `GT-LIMIT-IPO44-601995`
- `GT-LIMIT-IPO44-605499`

当前 2014 SSE 新股上市初期监管通知能证明 144%/64% 制度规则，但它本身不证明每个 issuer 的实际首个交易日。

因此每个 case 还必须绑定一份 official applicability artifact：

- `605499`：可使用 SSE 官方上市交易公告：
  `https://www.sse.com.cn/disclosure/announcement/listing/ipo/c/c_20210526_81718214.shtml`
  明确证券代码 605499，并自 2021-05-27 起上市交易。
- `601995`：开发方必须定位并记录 exact SSE official listing announcement；若原上市公告无法稳定解析，可使用能够明确写出 `601995` 于 `2020-11-02` 上市的其他 SSE official artifact，但必须说明其为 retrospective/supporting official evidence，不得使用媒体、Provider 输出或搜索摘要作为 seal truth。

Human Review 必须同时核：IPO regime rule + issuer listing-date applicability artifact。

### 3.3 AG-025 — 600518 两个 2019 ST5 case

Cases：

- `GT-LIMIT-ST5-600518-20190603`
- `GT-LIMIT-ST5-600518-20191028`

当前 SSE 风险警示板规则 Article 7 能证明“风险警示股票适用 5%”，但它本身不证明 600518 在两个 observation date 确实处于 ST/风险警示状态。

需要补充 official applicability evidence。已确认 SSE 2019-06-03 指数调整公告直接列出 `600518 | ST康美`，可作为 2019-06-03 的官方状态佐证：

`https://www.sse.com.cn/market/sseindex/diclosure/c/c_20190531_4830732.shtml`

对 2019-10-28 必须再提供能够覆盖该日期的 official status artifact；若一份 SSE official artifact 明确记录 600518 自 2019-05-17 起实施其他风险警示并持续为 ST，可同时服务两个 case，但 Human Reviewer 必须实际检查该材料。

## 4. 最小实现要求：只扩展 delta review sidecar/table

不要为此设计通用“证据图谱”。本阶段只需要一个低复杂度、fail-closed 的 Human Review 辅助合同。

建议在 `docs/golden/gt_h3/remediation/` 的 delta bundle/index/table 中为每个 case 支持：

```text
required_official_sources:
  - role: RULE
    official_source_ref: ...
  - role: APPLICABILITY
    official_source_ref: ...
```

字段名可以不同，但语义必须明确：

- 一个 case 可以要求 1..N 份 exact official source；
- Human Reviewer 必须检查该 case 的全部 required source；
- 缺少 RULE 或 APPLICABILITY 中任一必要维度时，复审表必须 fail closed，不得显示为“ready for human review”；
- AG-027、AG-029×2、AG-025×2 必须有复合证据；
- 其他 7 个 delta case 保持现状，除非确实发现新的来源错误。

新增聚焦测试，至少保证：

1. 上述 5 个 case 不能退回 rule-only evidence；
2. 12-case delta case 集合仍精确等于本轮 12 个整改 case；
3. 113 carry-forward 集合/identity hash 完全不变；
4. v5 Golden semantics/hash scope 不因 review-sidecar 补证据而变化；
5. 不允许把 Provider 数据、AI 摘要、搜索摘要当作 required official source。

## 5. GT-H3B 的后续证据 seal 边界

本轮不要求实现 GT-H3B，但必须在设计上留下真实边界：

- 如果一个复合 case 需要多份 official artifact 才能证明完整 assertion，最终 seal 必须能真实绑定这些 artifact bytes/hash；
- 不得把多个事实压缩成一个并不能证明全部事实的 artifact；
- 若未来能找到一份 official artifact 同时证明 rule + applicability，可退化为单 artifact；
- 当前 `review.py` 单 artifact/case 的合同是否要做最小 evidence-set 扩展，留到 12/12 Human Re-review 通过后的 GT-H3B 设计审查决定，本 PR 不实现。

## 6. PR 文档修正

PR #20 body 当前 v4 hash 误写为：

`...d1b9b9`

正确 authoritative hash 为：

`8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`

必须修正，避免审计记录出现两个 source binding。

## 7. GT-H3R.1 re-review exit gate

在 Reviewer 再次授权 merge 前必须全部满足：

```text
[ ] PR remains v5 candidate / COMPILED 125/125 / NOT SEALED
[ ] 113 prior APPROVE carry-forward remains exact and unchanged
[ ] exactly 12 prior REJECT remain delta Human Review scope
[ ] current v5 Golden semantics unchanged from reviewed head except no-op regeneration if required
[ ] AG-027 has STAR rule + 688981 exact official listing-date applicability evidence
[ ] AG-029 601995 has IPO rule + exact official listing-date applicability evidence
[ ] AG-029 605499 has IPO rule + exact official listing-date applicability evidence
[ ] AG-025 two 600518 cases have ST5 rule + official status/applicability evidence covering each observation date
[ ] focused fail-closed composite-evidence tests pass
[ ] Human review result fields remain blank; no agent auto-approval
[ ] PR body v4 source hash typo corrected
[ ] review_readiness_gate == []
[ ] quantity_gate == []
[ ] event_coverage_gate == []
[ ] production_formal_gate has only human-review blocker
[ ] no review.py / REVIEWED / GT-H3B / Production / Data Sufficiency / Provider verdict / backfill
[ ] final PR head + current-main GitHub test-merge verified
[ ] Windows py3.14 / Windows py3.12 / Ubuntu py3.14 final CI SUCCESS
```

After this closure, PR #20 may be merged and the **same 12-case** Human Re-review can begin. No 113-case repeated review is required.