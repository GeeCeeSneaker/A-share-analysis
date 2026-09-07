# A-share-analysis PR #20 首轮复审与 GT-H3R.1 证据完整性及审计历史收口要求

> 日期：2026-09-07  
> 状态：**GT-H3R CORE MECHANICS PASS / GT-H3R.1 CHANGES REQUIRED / DO NOT MERGE / NOT SEALED**

## 1. 本轮权威基线

- main：`277ef6fabac265eb70081231923b9a4a8487417f`
- PR：`#20 fix: remediate GT-H3 rejected golden cases`
- reviewed head：`e0f2abc6379f880614febbd33f0325396bc49cb3`
- GitHub test-merge：`5def7d358e11bdacddd1886fe1ae64e8fbaad1e3`
- test-merge composition：`main@277ef6fabac265eb70081231923b9a4a8487417f + PR head@e0f2abc6379f880614febbd33f0325396bc49cb3`
- final CI run：`34101070518`
- CI：Windows 3.14 / Windows 3.12 / Ubuntu 3.14 全部 SUCCESS
- Reviewer review：`5130019385`

v4 frozen source：

```text
truth_version = v4-candidate-20260906
dataset_hash  = 8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b
case_count    = 125
```

PR #20 当前 v5：

```text
truth_version = v5-candidate-20260907
dataset_hash  = 5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c
case_count    = 125
review_summary = COMPILED 125/125
```

---

## 2. 已验证通过，必须保留

以下实现本轮 **PASS / KEEP**，后续不得无故重做：

1. v4 version files 保持不可变；v5 通过受治理 rebuild 路径生成。
2. v5 125 条全部保持 `COMPILED`，没有 `REVIEWED`、artifact hash、review provenance 或 seal。
3. `review_readiness_gate == []`、`quantity_gate == []`、`event_coverage_gate == []`；`production_formal_gate` 仅剩 `REVIEWED 0/125` human-review blocker。
4. 113 条 v4 `APPROVE` 的 carry-forward 设计成立：新增版本中立 `review_identity_hash_for_doc()`，只排除 `truth_version`，仍绑定 case ID、symbol、trade date、expected fields、truth source、source_ref 与结构事件身份；实际 eligible 必须且当前确为 113。
5. 12 条 v4 `REJECT` 全部 `carry_forward_eligible=false`，没有自动转 APPROVE。
6. AG-054 / AG-025 / AG-064 的来源整改方向正确；AG-027 与 AG-096 两条 candidate fact correction 与管理裁决一致。
7. 12 条 delta Human Review 表保持空白；v4 `review_note="50"` 没有传播进 v5 review provenance。
8. 当前没有执行 `review.py`、GT-H3B、Formal Production、Data Sufficiency、Provider capability decision、backfill、策略/回测/交易。

---

## 3. GT-H3R.1 P0-01 — 复合事实的证据闭环仍不完整

### 3.1 问题

PR #20 已把部分错误规则页换成正确规则页，但对 **“规则 + 某证券在某日期确实处于该制度状态”** 的复合事实，当前仍只有一个 rule artifact。

最明确的三个 case：

- `GT-LIMIT-IPO44-601995`
- `GT-LIMIT-IPO44-605499`
- `GT-LIMIT-STAR20-688981-20200723`

#### AG-029

当前唯一 source 是 SSE 2014 新股上市初期交易监管通知。它能够证明 144% / 64% 的制度规则，但不能单独证明：

- `601995.SH` 的首个交易日就是 `2020-11-02`；
- `605499.SH` 的首个交易日就是 `2021-05-27`。

然而当前 12 行 Human Review 表要求审阅人从这一份材料同时核对 symbol、trade date 与 44%/36% 语义。这会再次造成 artifact claim 超出 artifact 实际证明范围。

#### AG-027

当前 STAR rule 可以证明“前五个交易日不设涨跌幅、之后适用 20%”，但不能单独证明 `688981.SH` 的上市日是 `2020-07-16`，因此也不能单独推出 `2020-07-23` 是第 6 个交易日。

### 3.2 收口原则

继续执行已经冻结的真实性原则：

```text
Golden claim
= Human checklist
= official evidence actually proves
= final executable evidence binding
```

`fact_proved=true` 与 `CASE_SPECIFIC_OFFICIAL_ARTIFACT` 不得表示“规则页存在”而事实适用性需要审阅人另行搜索。

### 3.3 最小复杂度修复

**禁止**为此建设通用多 artifact 状态机。

对确实需要复合证明的少数 case：

1. 在 GT-H3R remediation metadata 中增加明确的 supporting official source 信息；至少覆盖 AG-029 x2、AG-027 x1。
2. Human Review 表明确拆成：
   - rule artifact：证明制度值；
   - case-specific artifact：证明证券身份 / 上市日 / 制度适用日期。
3. Human Reviewer 必须同时打开两类官方材料，不能让一份 rule page 被描述成“同时证明证券和日期”。
4. 为未来 GT-H3B 保持低复杂度：优先采用 **deterministic per-case evidence bundle**，将所需 exact official bytes 与一个子 manifest 放入一个受控 bundle，子 manifest 记录 child source URL / kind / SHA256；再作为一个 content-addressed artifact 走现有 `review.py` 路径。只有现有机制无法安全承载时才考虑扩展多 artifact schema。
5. bundle 自身不能生成或改变 Golden expected fields；只能打包 Human 已核验的证据。

建议 case-specific official locator：

- `605499.SH`：SSE 上市公告，证明 2021-05-27 上市；
- `688981.SH`：SSE 上市公告，证明 2020-07-16 上市；
- `601995.SH`：优先寻找 SSE 精确上市公告；若只能找到 SSE 官方统计/上市清单，也必须是稳定、可定位、明确含 601995 与 2020-11-02 的官方材料。

---

## 4. GT-H3R.1 P1-02 — PR #19 审计历史被回删

这是治理回退，必须修复。

PR #20 当前从 `docs/DEVLOG.md` 删除了已合并的：

- `2026-09-07 · GT-H3 human result received and analyzed`
- `2026-09-06 · GT-H3 review table CI formatting correction`
- `2026-09-06 · GT-H3 reviewer-friendly 125-case table`

同时从 `docs/project/DEVELOPMENT_MANAGEMENT.md` 删除了：

- `DM-20260907-001 · GT-H3 人工核验结果接收与项目管理复核`
- `DM-20260906-115 · GT-H3 审阅表测试格式修正`
- `DM-20260906-114 · GT-H3 人工审阅表可用性优化`

这与“PR #19 是不可变 Human Review audit record”的治理裁决冲突。

### Required

- 恢复上述历史记录；历史只能追加，不得因为进入 v5 就删除旧阶段记录。
- 新增 GT-H3R 条目应以 append/prepend 方式保留，而不是替换历史。
- 不得重写先前 review ID、human 113/12 结果、CI 或阶段状态。

### GT-H3A artifact snapshot

PR #19 的 generic GT-H3A 文件属于第一轮 v4 Human Review 审计上下文。除非文件被明确设计并测试为“mutable current pointer”，否则不要在 v5 remediation PR 中静默改写：

- `docs/golden/gt_h3/GT_H3_HUMAN_REVIEW_TABLE.md`
- `docs/golden/gt_h3/GT_H3_REVIEW_BUNDLE.md`
- `docs/golden/gt_h3/review_bundle_index.jsonl`
- `docs/golden/gt_h3/review_decision_template.jsonl`

首选方案：恢复 PR #19 版本，v5 的 12-case / supporting-evidence / carry-forward 材料全部留在：

`docs/golden/gt_h3/remediation/`

这样最简单，也最利于审计复现。

---

## 5. GT-H3R.1 P1-03 — final-head 管理记录过期

当前 PR head 的 DEVLOG / DEVELOPMENT_MANAGEMENT 仍记录中间态：

```text
head       = b431af578ce9210621d7da9eebc1dbae3817657e
test-merge = 74d73989a4f05ef43a1f5d6f8f1d26224fb162a6
CI         = 34100003654
```

本轮实际审阅基线是：

```text
head       = e0f2abc6379f880614febbd33f0325396bc49cb3
test-merge = 5def7d358e11bdacddd1886fe1ae64e8fbaad1e3
CI         = 34101070518
```

在下一轮修复后必须记录新的 **最终** head / test-merge / CI，不得继续引用中间提交。

---

## 6. GT-H3R.1 P1-04 — PR body v4 hash 写错

PR #20 body 当前把 frozen v4 hash 写成：

`8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b9`

多了一个尾部 `9`。

正确 frozen binding 是：

`8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`

PR body 必须修正。源数据绑定属于正式 exit gate，不能接受“文档小错误”。

---

## 7. GT-H3R.1 下一轮 exit gates

```text
[ ] v4 files byte-identical / immutable
[ ] v5 remains 125 COMPILED
[ ] 113 carry-forward eligible exactly; version-neutral identities unchanged
[ ] 12 prior REJECT remain carry-forward false
[ ] AG-054 / AG-025 / AG-064 source fixes retained
[ ] AG-027 / AG-096 fact corrections retained exactly
[ ] compound cases have complete rule + case-applicability official evidence
[ ] Human checklist no longer asks one generic rule page to prove symbol/date it does not contain
[ ] future evidence-byte binding has a low-complexity deterministic bundle contract for compound cases
[ ] PR #19 DEVLOG / DEVELOPMENT_MANAGEMENT audit history restored
[ ] v4 GT-H3A audit artifacts preserved; v5 remediation material version-scoped
[ ] PR body frozen v4 hash exact
[ ] review_readiness_gate == []
[ ] quantity_gate == []
[ ] event_coverage_gate == []
[ ] production_formal_gate has only REVIEWED 0/125 blocker
[ ] no review.py / REVIEWED dataset / reviewed ACTIVE pointer
[ ] no Production B1-B7 / Data Sufficiency / Provider decision / backfill
[ ] DEVLOG + DEVELOPMENT_MANAGEMENT synchronized to actual final head/test-merge/CI
[ ] GitHub generated test-merge = latest main + final PR head
[ ] Windows 3.14 / Windows 3.12 / Ubuntu 3.14 fresh final-head CI SUCCESS
```

---

## 8. 当前阶段裁决

```text
GT-H3R v5 core candidate mechanics       PASS / KEEP
113-review carry-forward contract         PASS / KEEP
12-reject delta scoping                   PASS / KEEP
GT-H3R.1 compound evidence completeness   OPEN / BLOCKER
GT-H3R.1 audit-history preservation       OPEN / BLOCKER
GT-H3R.1 final-head governance sync       OPEN
PR #20                                    DO NOT MERGE
GT-H3B / review.py                        BLOCKED
Formal Production B1-B7                   BLOCKED
Data Sufficiency                          BLOCKED
Provider capability verdict               BLOCKED
2020+ backfill                            BLOCKED
```

下一轮只处理本文件列出的 GT-H3R.1 收口项；已经验证通过的 113/12 carry-forward 和 v5 核心整改不得被无关重构重新打开。
