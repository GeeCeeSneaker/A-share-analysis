# A-share-analysis GT-H3R 关闭与 12 条 Human Re-review 执行要求

> 日期：2026-09-07  
> 状态：**GT-H3R / GT-H3R.1 CLOSED；12-CASE REAL HUMAN RE-REVIEW AUTHORIZED；GT-H3B NOT AUTHORIZED**

## 1. 权威关闭基线

- PR：`#20 fix: remediate GT-H3 rejected golden cases`
- final head：`4fb60f1cbb5a23f71bcbbfffbc72d488fd2a157d`
- Reviewer final closure：`5130860878`
- pre-merge main：`669759adf34bece4c9e41c7be2ce2e9f858e5277`
- GitHub generated test-merge：`11cf4e4b811b0a5c90042087a544216863b4e1e1`
- test-merge composition：`main@669759ad... + PR head@4fb60f1c...`
- required CI：run `34109324402` / #358
- CI：Windows py3.14 / Windows py3.12 / Ubuntu py3.14 全部 SUCCESS
- merge commit：`b03ada73bc15d5e1ea1a62a28962ba8204b5bd51`

v5 candidate baseline：

```text
truth_version = v5-candidate-20260907
dataset_hash  = 5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c
case_count    = 125
review_summary = COMPILED 125/125
```

v4 immutable Human Review source baseline remains：

```text
truth_version = v4-candidate-20260906
dataset_hash  = 8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b
Human result  = APPROVE 113 / REJECT 12
```

## 2. GT-H3R 已关闭的内容

以下合同已经 Reviewer 验证并冻结，不得在 12-case Human Re-review 阶段重新设计：

1. v4 version files 不可变；PR #19 GT-H3A audit snapshot 已恢复并保持原 blob。
2. v5 由 governed rebuild 路径生成，125 条全部保持 `COMPILED`。
3. 113 条 prior APPROVE 使用 version-neutral `review_identity_hash_for_doc()` 完成可验证 carry-forward；只有 `truth_version` 被排除，case ID、symbol、trade date、expected fields、truth source、source ref 与 v4+ structural identity 仍绑定。
4. 12 条 prior REJECT 全部 `carry_forward_eligible=false`，没有自动 APPROVE。
5. 10 条 evidence-only remediation 未改变 Golden expected semantics。
6. 两条 fact correction 已精确修正：
   - `GT-LIMIT-STARNO-20200723` → `GT-LIMIT-STAR20-688981-20200723`，2020-07-23 为 STAR 上市后第 6 个交易日、20% regime；
   - `GT-H2-ST-ST_ADD-300965-20240429` → `GT-H2-ST-ST_ADD-300965-20240426`，effective/trade date 为 2024-04-26。
7. 五个复合事实 case 已使用候选-only supporting-source sidecar，要求 Human 同时核验 RULE 与 APPLICABILITY；sidecar 不含 `fact_proved`、Human result、官方 bytes/hash。
8. non-review gates 均通过；Formal gate 仅剩 Human Review blocker。
9. `review.py`、REVIEWED dataset、reviewed ACTIVE pointer、GT-H3B、Production B1-B7、Data Sufficiency、Provider capability verdict、2020+ backfill 均未执行。

## 3. 当前唯一授权工作：真实 Human 复审 12 条

使用：

- `docs/golden/gt_h3/remediation/GT_H3R_V5_REVIEW_TABLE.md`
- `docs/golden/gt_h3/remediation/GT_H3R_V5_REVIEW_TABLE.xlsx`
- `docs/golden/gt_h3/remediation/GT_H3R_V5_SUPPORTING_OFFICIAL_SOURCES.jsonl`

Human Reviewer 必须逐条打开该 case 的**全部 required official sources**，不能用搜索摘要、Provider 输出、AI 总结或本项目自身判断替代官方原文。

12 条每条只能给：

```text
APPROVE
REJECT
```

`REJECT` 必须给出短原因。

五个 composite case 必须同时核 RULE + APPLICABILITY：

- `GT-LIMIT-ST5-600518-20190603`
- `GT-LIMIT-ST5-600518-20191028`
- `GT-LIMIT-STAR20-688981-20200723`
- `GT-LIMIT-IPO44-601995`
- `GT-LIMIT-IPO44-605499`

缺任一必要官方材料、链接不可解析、材料不能证明 required claim、日期/代码/规则适用关系不一致，必须 `REJECT`。

其余 7 条只按 sidecar 声明的 required official source 核验，不得扩展到无关事实。

## 4. 113 条 prior APPROVE 不重复人工复审

113 条不进入新的逐案人工工作量；其合法沿用条件已由 carry-forward ledger 机器验证。

在最终完整授权时，真实 Human Reviewer 只需额外明确声明：

1. v4 的 113 条 `APPROVE` 是本人/真实 Human 有意作出的审批决定；
2. 同意在 v5 中按已验证的 semantic/review-identity carry-forward 沿用；
3. legacy `review_note = "50"` 不具有 Golden semantic meaning，可规范化为空（如果 Human 有其他定义，必须明确说明）；
4. 给出最终 `human marker`，作为未来 reviewed provenance 的 `reviewed_by` 标识。

任何一条 carry-forward identity 后续发生变化，都必须自动失去沿用资格并重新 Human Review。

## 5. 12/12 复审后的决策

### 若任一 REJECT

- 不得 seal；
- 只把新的 REJECT case 返回 candidate governance；
- 已验证未变化的其他 Human APPROVE 不需要重审；
- 形成下一版 candidate 时仍必须使用明确 lineage + carry-forward contract。

### 若 12/12 全 APPROVE

仍**不能直接运行 `review.py`**。

必须先由真实 Human Reviewer 在 PR/comment 或等价的受审计记录中给出完整声明：

```text
12 corrected cases: APPROVE 12/12
113 carried-forward approvals: explicitly confirmed
legacy note "50": neutralized/defined
final human marker: <explicit value>
complete v5 logical authorization: 125/125
```

项目 Reviewer 核验该声明后，才进入 GT-H3B 设计与执行。

## 6. GT-H3B 后续边界

GT-H3B 的任务是 evidence-byte binding + one atomic N/N seal，不是再修改 Golden truth。

复合 case 最终 evidence binding 必须真实覆盖 Human 审过的所有 required official sources。优先采用低复杂度 deterministic per-case evidence bundle：

```text
case evidence bundle
  child manifest
    - exact official URL
    - artifact kind
    - child SHA256
  official artifact bytes 1..N
  bundle SHA256
```

再将 bundle 作为 content-addressed reviewed artifact 交给受治理 seal path。是否需要对 `review.py` 做最小 evidence-set 扩展，留到 GT-H3B 设计审查决定；当前 Human Re-review 阶段不得实现。

Human Review 不能通过 `expect_fields` 或任何 review input 修改 expected truth。

## 7. CI / Git 元数据治理规则修正

取消不可实现的“同一个 commit 必须在自身 DEVLOG 中写入自己的最终 test-merge/CI SHA”要求，因为任何补写都会产生新 head，使记录再次过期，形成自引用循环。

今后 gated PR 使用：

1. Git-tracked DEVLOG / Development Management：记录阶段、合同、待验证状态和已知基线；
2. PR body / handoff comment：记录 final head、current-main test-merge、final CI run；
3. Reviewer closure：独立确认这些 final metadata；
4. merge 后 main management record：固化最终 head/test-merge/CI/review/merge SHA。

这四层共同构成审计链，不要求同一 pre-merge commit 自证未来 CI 结果。

## 8. 当前状态

```text
GT-H3R / GT-H3R.1             CLOSED
PR #20                         MERGED
v5 candidate                    COMPILED 125/125
113 prior Human APPROVE         CARRY-FORWARD VERIFIED
12 corrected cases              REAL HUMAN RE-REVIEW AUTHORIZED
GT-H3B                          BLOCKED
review.py                       BLOCKED
Formal Production B1-B7         BLOCKED
Data Sufficiency                BLOCKED
Provider capability verdict     BLOCKED
2020+ backfill                  BLOCKED
```

下一次项目管理复核只处理：12-case Human Re-review 结果、113 carry-forward final confirmation、legacy `50` neutralization/definition 和 final human marker。不得重新打开已经关闭的 v5 remediation mechanics，除非发现明确回归或 Human 新 REJECT。