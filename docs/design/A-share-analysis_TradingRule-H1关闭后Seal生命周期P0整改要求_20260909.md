# A-share-analysis · Trading Rule H1 关闭后 Seal 生命周期 P0 整改要求

日期：2026-09-09（Asia/Shanghai）

## 1. 状态与目的

Trading Rule H1R 的规则真值候选、边界测试和 `RULE_EVIDENCE_BUNDLE.v1` 已完成独立 Reviewer 审查，并通过 PR #32 合并。

- PR #32 final head：`2dc2322bdebc2f60df584ea93afc61908b90fdc9`
- Reviewer final review：`5149902349`
- PR #32 merge commit：`398b37339654784a35efd98a5fe129295ce8c9f1`
- H1 candidate：`configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml`
- candidate 状态：`COMPILED` / non-ACTIVE / 14 rules
- Golden v7：保持 `REVIEWED 125/125`，不重新打开
- Formal Production B1-B7：仍未启动；无 production `run_id`；正式 attempt 未消耗

本文件只解决 PR #32 合并后发现的一个 **P0 生命周期状态迁移缺口**。不得借此重新设计 Trading Rule truth、重新讨论 14 条规则，或引入通用发布状态机。

## 2. P0-TR-H1-SEAL-01 · non-ACTIVE candidate 无法被现有 review.py 合法封印

当前 `scripts/rules/review.py` 的 review workflow 以 ACTIVE 为唯一 parent/source：

1. 调用 `load_active_rules(rules_root)`；
2. 要求 `--from-version` 与当前 ACTIVE 一致；
3. 要求 `--rules` 精确等于 ACTIVE dataset file；
4. 要求 ACTIVE dataset 本身为 `COMPILED`；
5. 然后才生成 NEW `REVIEWED` version 并切 ACTIVE。

而 H1 的治理设计明确要求：

- `v20260909-h1-compiled` 在独立 Reviewer 接受前一直保持 non-ACTIVE；
- 旧 ACTIVE `v20260824-compiled` 不得被手工覆盖；
- COMPILED candidate 不应先暴露为生产 ACTIVE 再 review；
- publication 必须在 evidence + REVIEWED output 全部验证通过后，最后一次原子推进 ACTIVE。

因此当前存在矛盾：

```text
合法 candidate = non-ACTIVE COMPILED
现有 review.py = 只能 review ACTIVE COMPILED
```

不能用以下方式绕过：

- 手工编辑 `configs/trading_rules/rule_manifest.json`；
- 临时把 H1 candidate 设为 ACTIVE COMPILED 后再运行 review；
- 复制 candidate 内容覆盖旧 ACTIVE version；
- 放宽 ACTIVE / lineage / review gate；
- 在正式 evidence materialization 后再临时修工具。

## 3. 最小正确方案

在现有 `scripts/rules/review.py` 中增加一个**显式 non-ACTIVE candidate seal 路径**，名称可由实现决定，例如 `--candidate` / `--candidate-version`，但语义必须固定如下。

### 3.1 输入

生产 H1 seal 至少显式绑定：

- `expected current ACTIVE parent`：当前预期为 `v20260824-compiled`；
- `candidate rules path/version`：当前预期为 `v20260909-h1-compiled`；
- candidate expected dataset identity/hash；
- NEW reviewed version id；
- `RULE_EVIDENCE_BUNDLE.v1` input；
- reviewer marker：`project-owner`。

不得仅凭一个可变路径或“当前目录里最新 candidate”自动选择待封印对象。

### 3.2 单写者锁内的受控顺序

现有 single-writer lock 必须覆盖从 parent/candidate 读取到 ACTIVE commit 的整个过程。

锁内顺序：

1. **验证当前 ACTIVE parent**
   - `load_active_rules()` 完整通过；
   - current ACTIVE == expected parent；
   - parent bytes/hash/manifest coherence 正确；
   - parent 不被修改。

2. **独立验证 non-ACTIVE candidate**
   - candidate 必须位于 `configs/trading_rules/versions/<single-safe-component>/...`；
   - candidate version directory 已存在、不可变、不得是 staging path；
   - candidate 不是 current ACTIVE；
   - candidate `review_status=COMPILED`；
   - candidate rule set / dataset version / evidence contract 可完整加载；
   - candidate bytes 必须匹配调用方冻结的 expected candidate hash/identity；
   - candidate 读取一次形成 in-memory snapshot，后续 transform 与 hash 必须使用同一 snapshot bytes。

3. **准备真实 evidence**
   - 按 candidate `source_ref` 的 required URL set exact coverage 构造 `RULE_EVIDENCE_BUNDLE.v1`；
   - 14/14 rule_id exactly once；
   - missing / extra / duplicate URL fail closed；
   - official host / kind / role / raw SHA256 / byte size / content-address / path confinement 全部复用 PR #32 已合并合同。

4. **构造 NEW REVIEWED copy**
   - 从 candidate snapshot bytes 变换；
   - candidate 本身保持 immutable COMPILED；
   - NEW reviewed version create-only；
   - reviewer 使用 `project-owner`；
   - bundle ref/hash 写入 REVIEWED provenance。

5. **staging 全校验**
   - stage raw evidence、bundle、NEW reviewed version；
   - 对 staged REVIEWED book 运行完整 `trading_rule_review_gate(..., require_evidence_bundle=True)`；
   - 重新核 dataset hash / rule count / candidate→reviewed identity；
   - 任意失败都必须清理本次新建 staging/output，保持旧 ACTIVE 不变。

6. **发布**
   - 先 publish NEW immutable REVIEWED version；
   - 最后才 atomic replace ACTIVE manifest；
   - ACTIVE 必须从 expected old parent **直接**跳到 NEW REVIEWED version；
   - `v20260909-h1-compiled` 从始至终不得成为 ACTIVE。

7. **post-commit verification**
   - 重新 `load_active_rules()`；
   - ACTIVE == NEW reviewed version；
   - `review_status=REVIEWED`；
   - 14-rule bundle gate == []；
   - evidence/raw hashes 可重算；
   - candidate 与旧 parent bytes 未改变。

## 4. 不要做成通用状态机

本整改只需要补齐一条清晰状态迁移：

```text
ACTIVE old COMPILED parent
        +
non-ACTIVE reviewed/accepted COMPILED candidate
        +
complete real evidence
        ↓
NEW immutable REVIEWED version
        ↓
ACTIVE last -> NEW REVIEWED
```

不需要：

- 通用发布编排框架；
- 任意版本之间的自由 promotion；
- 多阶段 approval 状态机；
- 新数据库；
- 新服务；
- claim/evidence graph。

原 legacy “ACTIVE COMPILED -> REVIEWED” review 模式如已有测试/兼容需求可保留，但 **H1 正式 production path 必须走 explicit non-ACTIVE candidate + expected ACTIVE parent**。

## 5. 必须新增的对抗测试

至少覆盖：

1. happy path：candidate non-ACTIVE + expected old parent + complete evidence -> ACTIVE 直接成为 NEW REVIEWED；candidate 从未成为 ACTIVE；
2. wrong expected parent -> 在任何 output mutation 前 fail；
3. candidate path 不在 `versions/`、包含 traversal/symlink escape -> fail；
4. candidate 已为 REVIEWED -> fail；
5. candidate bytes/hash 与冻结 identity 不一致 -> fail；
6. candidate 在 snapshot 后被篡改 -> 不得把第二次读取的新 bytes 封入 reviewed output；
7. current ACTIVE 在调用前已移动 -> fail；
8. 并发 reviewer -> single-writer lock 阻止 stale-parent transition；
9. evidence bundle missing/extra/duplicate/wrong-hash/tamper -> fail，ACTIVE 不变；
10. staged reviewed gate fail -> 不留下 NEW reviewed version、bundle/raw orphan 或 ACTIVE 变化；
11. ACTIVE manifest atomic write failure -> rollback/cleanup 保持 old ACTIVE 可加载；
12. post-commit load/gate 能证明最终 ACTIVE 为 NEW REVIEWED 且 bundle 完整；
13. old `v20260824-compiled` 与 H1 `v20260909-h1-compiled` bytes 保持 immutable。

## 6. 真实 evidence 与 seal 的授权边界

在本 P0 生命周期 fix 被独立 Reviewer 审查并合并前：

- **不要**开始正式 14-rule evidence materialization；
- **不要**运行 H1 REVIEWED seal；
- **不要**切 ACTIVE；
- **不要**重试 Formal Production。

生命周期 fix 合并后，直接进入受控真实执行：

1. 从届时 current main 建立 clean execution checkout；
2. 获取 candidate required source set 的真实第一方原始 HTML/PDF bytes；
3. 对所有 14 rule_id 构造 exact-coverage evidence bundle；
4. 使用 hardened candidate-seal path，一次性生成 NEW REVIEWED version；
5. reviewer marker 使用 `project-owner`；不再要求 Owner 手工逐条填 14 行表；
6. 建独立 evidence/seal PR，由独立 Reviewer 复核最终 bytes/hash/bundle/ACTIVE transition；
7. 只有该 PR 关闭并合并后才重新执行 Formal Production B1-B7。

用户此前已明确不希望重复人工逐条复核；本轮规则事实已完成多轮独立 Reviewer 复核。质量控制依赖：first-party source exact set + raw bytes + SHA256 + deterministic bundle + independent Reviewer，而不是新增形式化人工签字。

## 7. 当前阶段状态

```text
Golden v7 / GT-H3B               CLOSED / ACTIVE / REVIEWED 125/125
Trading Rule H1R truth           CLOSED
PR #32 candidate + contract      MERGED
H1 Seal lifecycle P0             OPEN / CURRENT TASK
H1 publishable evidence materialization BLOCKED (reviewer intake raw bytes are present)
H1 REVIEWED seal                 BLOCKED
Trading Rule ACTIVE              old COMPILED remains
Formal Production B1-B7          PROHIBITED UNTIL H1 REVIEWED PR IS INDEPENDENTLY CLOSED / NOT STARTED
Formal attempt                    NOT CONSUMED
Provider verdict                  PENDING
Data Sufficiency                  BLOCKED
2020+ backfill                    BLOCKED
```
