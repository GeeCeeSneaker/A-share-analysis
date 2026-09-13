# Current Execution Plan

> 本文件是项目**当前执行控制面**。它回答开发人员最重要的四个问题：现在做到哪里、唯一主线任务是什么、做到什么算完成、完成后下一步由谁决定。
>
> 历史决策和详细审计记录继续保留在 `docs/project/DEVELOPMENT_MANAGEMENT.md`、`docs/DEVLOG.md`、Issues 和 PR reviews 中；开发人员日常接任务优先读取本文件和这里引用的当前 Issue。

## 1. 项目管理责任

从 2026-09-13 起，项目按以下职责运行：

- **项目经理 / 审计负责人**：负责读取最新 `main`、Issue、PR、CI 和开发证据；决定当前唯一主线；审阅 exact head；给出 `PASS / REMEDIATE / STOP`；并在每次进展审阅后更新本文件与对应 Issue 的下一任务、验收标准、依赖和禁止项。
- **开发执行者（Codex / Agent / 本地开发人员）**：只执行当前已授权任务，不自行扩大范围；完成后提交 branch/PR、测试与证据，并等待下一次调度。
- **项目 Owner**：保留最终方向调整和例外授权权力。

原则：**审阅结束不能以“等待下一步”为终点。每次审阅必须产生明确下一动作；若 PASS，则立即进入下一任务；若 REMEDIATE，则给出可执行整改清单；若 STOP/BLOCKED，则给出解除阻断所需证据。**

## 2. 仓库操作原则

- 本地 clone / worktree 是日常仓库内容操作的首选路径；GitHub Connector/API 主要用于 Issue、PR、review、Actions/CI 等控制面操作或本地不可用时的回退。
- 任何远端写入、review 接受或 merge 前必须核对 exact base/head SHA。
- 如果本地 Git 与 Connector/API 视图不一致，停止写入和合并，先完成同步与解释。
- 通过 Connector 回退产生的仓库内容提交，开发人员下次接单前必须在本地 `fetch` 后核对并同步。

## 3. 当前主线状态

**阶段**：Phase 0 / CR-7 historical research data foundation

**当前 `main` 基线**：

`d2fa53371937d59ea0a118b79df1554d518f575f`

该基线已合并 PR #53，具备：

- 非发布型 verified projection；
- coverage-basis typed/fail-closed 验证；
- `TEST_FIXTURE_ONLY` 与 `AUTHORITATIVE_UPSTREAM` 证据类别隔离；
- 78 月 inventory；
- staging / verification / atomic publication；
- idempotent replay / identity conflict rejection；
- ordinary historical reader 对 PARTIAL / UNRESOLVED / fixture-only 的 fail-closed gate。

**重要事实**：当前只完成了可信历史物化框架，尚未证明 2020-01 至 2026-06 的真实市场历史覆盖，也尚未完成全 78 月真实历史物化。

## 4. 当前唯一 P0 开发任务

**Issue #55 — `P0: CR-7 authoritative historical evidence and bounded real-source preflight`**

目标：从 merged offline framework 推进到首个真实、可审计、非 fixture 的 `AUTHORITATIVE_UPSTREAM` coverage evidence，并用真实上游证据验证 materializer 的 fail-closed 路径。

开发人员必须从 clean local worktree 同步到：

`main@d2fa53371937d59ea0a118b79df1554d518f575f`

然后建立独立分支执行 Issue #55。

### 4.1 必须完成

1. 实现最窄的 authoritative coverage-evidence adapter，复用现有 typed coverage-basis contract，不另造旁路。
2. completeness method 必须由真实上游 inventory/range statement 或等价可审计来源支撑；连续日期、row count、snapshot bytes 本身都不能证明 COMPLETE。
3. coverage basis 必须绑定 source snapshot/domain、日期闭区间、source-selection fingerprint、artifact bytes/hash、PIT/available-at 证据。
4. ordinary reader 继续只允许 committed + verified `AUTHORITATIVE_UPSTREAM` + `OBSERVED_DAILY_BAR_COVERAGE`。
5. 增加对 missing/stale/wrong-scope/tampered basis、fixture escalation、PARTIAL/UNRESOLVED、replay/conflict 的对抗测试。

### 4.2 三个月代表性真实源预检

实现和本地质量门禁通过后，仅执行以下三个月：

- Development：2020-01
- Validation A：2024-01
- Holdout：2026-01

目的不是形成研究数据集，而是尽早证明 authoritative evidence path 在三个 split 都真实可行。

如果任何一个月无法证明 authoritative completeness：**立即 fail closed**，记录缺口并返回审阅；禁止用 fixture、row count、月份连续性或人为声明升级为 COMPLETE。

### 4.3 明确禁止

本任务不授权：

- 第三次 Formal B1-B7；
- Production `--resume` / `--verdict`；
- 全 78 月 broad backfill；
- universe sweep；
- BSE mapping 激活；
- index 激活；
- CR-5/R2 feature export；
- Golden/H1/global baseline 改动；
- 策略实现或参数优化；
- 任何密钥、凭证、私有 endpoint、专有 SDK/runtime、无限制 raw Provider payload 入库。

## 5. 当前任务验收标准

开发 PR 进入最终审阅前必须同时满足：

- exact base/head SHA 可复核；
- focused tests 通过；
- 全量项目质量门禁通过；
- CI 对 exact head 绿色；
- fixture evidence 无法解锁普通 historical reader；
- 三个月真实源预检全部可复现成功，或明确 fail-closed 到具体 upstream completeness blocker；
- 没有 scope creep。

## 6. 审阅后的调度规则

### 若 Issue #55 / 对应 PR PASS

项目经理立即决定并记录以下二选一：

A. authoritative evidence path 完整可靠 → 授权完整 78 月 historical materialization；

B. path 本身可靠，但某个 source/completeness 边界仍不足 → 先发一个最窄 source-evidence remediation 任务，不允许开发人员自行绕过。

### 若 REMEDIATE

项目经理必须在 PR review + Issue 中写出：

- exact head；
- 阻断项及优先级；
- 每项整改的文件/模块边界；
- 必测回归；
- 不允许顺手修改的范围；
- 完成后返回哪一个 gate。

### 若 BLOCKED

项目经理必须明确：

- blocker 是代码、上游语义、账号能力、来源完整性还是治理问题；
- 解除 blocker 所需最小证据；
- 哪些并行工作可以继续、哪些必须冻结。

## 7. 后续路线（非当前授权）

只有当前 P0 完成后，才按顺序考虑：

1. 完整 78 月 2020-01 至 2026-06 authoritative historical materialization；
2. 全量 coverage / artifact lineage / replay / corruption E2E 验证；
3. 数据基座 Freeze Gate；
4. CR-5/R2 与研究特征层；
5. `Quantitative-Strategy-Research` 等策略项目正式将本仓库作为首选数据基座。

策略研究不得反过来驱动数据口径；参数优化不得用于弥补数据或交易逻辑缺陷。

## 8. 开发人员交接格式

开发人员完成当前任务时，PR/Issue 至少报告：

- base SHA / head SHA；
- 实际修改范围；
- 本地 focused/full QA；
- CI run；
- 三个月 preflight 结果；
- evidence/receipt 路径；
- blockers / unresolved；
- 明确声明未执行的禁止项；
- 建议的下一步，但**下一任务由项目经理审阅后最终调度**。

---

**Last scheduler update**：2026-09-13

**Current task**：Issue #55

**Current main baseline**：`d2fa53371937d59ea0a118b79df1554d518f575f`
