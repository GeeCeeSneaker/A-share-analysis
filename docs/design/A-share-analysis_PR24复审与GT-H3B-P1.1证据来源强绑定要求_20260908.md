# A-share-analysis · PR #24 复审与 GT-H3B-P1.1 证据来源强绑定要求（2026-09-08）

## Reviewer 结论

PR #24 当前 final head `bc2a92b459728f14c2186982c1b3e4103b9c2e71` 基于 `main@a5d224fbe696c4dd2981672995f31cf6ab9e9bdb`，GitHub test-merge 为 `a311fafeac84e3fa9e0657718c33a5963799e7eb`。Reviewer checkpoint 为 `5136884160`。

### 已关闭：GT-H3B-P0 safe promotion implementation

`promote-existing` 的边界与 fail-closed 设计通过：固定核验 v4/v5/v6 immutable bytes、Golden loader、manifest statistics、v5→v6 plan 字节级重建、110/15 review identity、50/50 ST transition audit，最后才原子推进 ACTIVE；错误 ACTIVE、tampered bytes、plan/carry/audit drift、duplicate ST identity、pointer write failure 均阻断。

P0 仅是实现通过；PR #24 合并前不得执行真实 promotion。

### 已通过的 P1 机制

- batch manifest 禁止 `expect_fields`；
- `EVIDENCE_BUNDLE` 为确定性、create-only 的原始 bytes 容器；
- bundle member hash/size 重算、source list 声明一致性、禁止嵌套/路径穿越/加密等机制有效；
- review publication 在 ACTIVE 未改变时可回滚本次新建且 bytes 未被外部改动的 evidence/version 文件；
- 两个新增 CI grandfathered SHA 已独立核验：`3c66d1118835266bd7d608b6af460bf91a03c57c` 是 review rollback 实现，`d07d9628cb69b60f4d951033b12d0bc5dc00e8e5` 仅是 Ruff formatting。接受本次一次性历史豁免，后续不得继续扩展 grandfather list。

## P0 blocker：GT-H3B-P1.1 case → official-source trust binding

当前 P1 只能证明：

```text
artifact bytes
  ↕
bundle manifest / hash
  ↕
review manifest declaration
```

但还没有机器证明：

```text
review manifest declaration
  ↕
这个 Golden case 已经授权的官方来源合同
```

具体缺口：

1. 当前 `source_ref` 仅校验为 HTTP(S)，任意 host 都可通过；“official URL”只是描述，不是代码约束。
2. composite case 的 `bundle_sources` 来自同一份待信任的 review manifest；包内自洽不能证明来源适用于该 case。
3. ordinary 非 bundle case 的 review manifest 当前没有 source locator 绑定；理论上同一任意本地文件可以被分配给多个无关 case 并完成 REVIEWED seal。
4. Owner 已明确不再进行另一轮逐案人工复核，因此该信任边界不能继续依赖操作员“填对 manifest”。

## 最小整改方案

不要建设通用证据图谱，也不要把网络下载放进 `review.py`。只增加一个窄范围、版本化的 evidence-source contract。

### 1. 冻结 v6 125-case evidence source contract

新增机器可读文件，例如：

`docs/golden/gt_h3/gt_h3b/v6_case_evidence_source_contract.jsonl`

必须：

- exact 125 个 `golden_case_id`，无缺失、无重复、无 foreign case；
- 每个 case 明确 `source_ref`/`artifact_kind`，若一个 case 需要多份证据则明确有序列表或确定性 set 语义；
- 来源只能从已经完成的 Golden/GT-H3/GT-H3R/GT-H3R2 官方证据元数据派生，seal 阶段不得临时创造新事实；
- 15 个 GT-H3R2 新 ST case 使用 v6/rebuild 中已经独立审阅的精确 CNINFO locator；
- 5 个 composite case 保留已裁决的 RULE + APPLICABILITY 双来源及其 kind，不得在 seal 时退化为单证据。

### 2. official-host allowlist

沿用 GT-H2/GT-H3 已采用的官方来源治理，只允许 SSE / SZSE / BSE / CNINFO 官方 host，以及仓库已显式治理的官方静态/披露别名。

- 任意普通 HTTP(S) host 不等于官方来源；
- alias 必须显式列出，不使用宽泛域名匹配；
- `official.example` 等测试地址只能用于 unit-level bundle parser 测试，不能通过 production evidence-source-contract 校验。

### 3. review.py 必须做 case-bound source comparison

在任何 artifact staging 前：

- ordinary case 的 batch manifest 必须声明 source locator + kind；
- composite bundle 必须声明完整 source list；
- review.py 读取冻结 source contract，并按 `golden_case_id` 做精确匹配；
- bundle 内部 source list 仍需与 batch manifest 一致；
- 因此形成：

```text
Golden case
 → frozen source contract
 → batch manifest declaration
 → bundle manifest（若适用）
 → raw bytes + computed SHA256
```

其中任一环节不一致均 fail closed。

### 4. 必须增加的对抗测试

至少覆盖：

- arbitrary HTTP(S) host → FAIL；
- case A 的官方来源用于 case B → FAIL；
- ordinary artifact 缺 source binding → FAIL；
- composite 缺 RULE 或 APPLICABILITY → FAIL；
- composite source swapped / extra / drift → FAIL（若采用 set 语义则按确定性规范测试）；
- source contract 124/125、duplicate、foreign case → FAIL；
- exact 125-case contract + exact evidence declaration → PASS。

### 5. 保持现有边界

- `expect_fields` 继续禁止；
- 不在 `review.py` 中加入 live network fetch；
- 本 PR 不获取真实 125 evidence bytes，不运行真实 seal；
- 本 PR 合并前不执行 `promote-existing`；
- 不修改 v4/v5/v6 versioned Golden bytes。

## PR #24 下一次退出门

完成 P1.1 后：

1. PR branch 同步本管理提交后的 current main；
2. P0 promotion tests 继续全过；
3. P1/P1.1 source-binding tests 全过；
4. Windows 3.14 / Windows 3.12 / Ubuntu 3.14 final-head/current-main CI 全过；
5. PR body 明确 `P0 implementation verified / P1.1 source binding closed / real evidence not yet materialized / no seal`；
6. 独立 Reviewer 对新 final head + generated test-merge 再做 closure；
7. 只有 Reviewer merge authorization 后才合并 PR #24。

## 合并后的执行顺序

```text
PR #24 tooling merged
 → controlled promote-existing: v5 ACTIVE → exact v6 ACTIVE
 → verify ACTIVE v6 + all gates
 → materialize exact 125 official raw evidence bytes
 → build case-bound 125-entry review manifest
 → one atomic review.py seal --reviewer project-owner
 → REVIEWED 125/125 + evidence hash verification
 → GT-H3B final Reviewer closure / merge
 → one controlled Formal Production B1-B7
```

在 GT-H3B reviewed Golden 最终合并前，Formal Production、Data Sufficiency、Provider verdict、2020+ backfill 继续 BLOCKED。
