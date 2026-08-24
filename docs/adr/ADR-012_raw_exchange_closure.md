# ADR-012: Raw Exchange Closure + Trading Rule Binding（R4-A2.4 / CR-1.2 修订）

- 状态：ACCEPTED
- 日期：2026-08-24
- 依据：审计 R4-A2.3/CR-1.1 复审（裁决 REOPENED）→ R4-A2.4 / CR-1.2 开发工作要求（P0-01..P0-06 + P1）
- 关系：**amendment to ADR-010 / ADR-011**（不推翻，只收紧/补充）
- 登记变更：DM-CR-20260824-008 / 009 / 010 / 011（管理总册 §61）

## 1. Raw Exchange Closure（CR-1.2，amendment to ADR-010）

ADR-010 确立了 `exchange → RawWriter → evidence` 链。本修订把证据单元从
"payload 文件"升级为"**exchange（payload + meta）**"，闭合是双向的：

### 1.1 Meta-anchored evidence（§3.1/3.2）

- `RawWriteResult` 拆分为 `payload_artifacts[]`（uri/content_hash/schema_hash/
  row_count 每件独立）+ `meta_artifact`（uri/content_hash）；
- SpikeCase 绑定的 evidence **恒为该 exchange 的 .meta.json**（单表成功不再绑
  裸 parquet）：meta 声明每个 payload 的 hash → 删除/篡改**任一侧**都破坏闭合；
  ADR-010 时代的 `evidence_uri=parquet` 语义被本修订取代；
- bundle entry 同步列出 payload_artifacts + meta_ref/meta_hash；
  `verify_evidence_closure` 对 bundle → 每 exchange meta → 每 payload **递归
  双向复验**（bundle hash → entry hash → meta hash → payload bytes hash）。

### 1.2 Request 完整可重建（§3.3）

- meta 持久化**完整脱敏后的 request_params**（非仅 hash）：code_list 落盘，
  请求可重建；等长不同 symbols 请求 hash 不同（实测覆盖）；
- meta 记录 `ingested_at` + `ingest_run_id`（RawWriter 构造注入 run id）——
  每 meta 可追溯到其 ingest run。

### 1.3 多文件提交原子性（P1-01）

多表提交：staging 目录写全部 payload → 逐文件 `os.replace` → **meta 最后落盘**
（meta 是闭合锚）。中断的提交不可能留下 meta-anchored 的残缺集；失败清理
staging。表名净化后冲突 BLOCK（P1-02，绝不覆盖）；`read(verify=True)` 读前
复验全部声明 hash（P1-03）。

### 1.4 Exchange 完整性（§2）

隐藏日历前置**显式化（Option A）**：kline 前必须先持久化 calendar exchange，
再把窗口 trading_days 显式传入 kline 调用（RealTarget.query_kline_exchange
增加 `trading_days` 参数）；日历前置失败 → 失败 meta 落盘 + kline **不发射**
（绝不伪造成功）。B3/B7 的 code_list/calendar 前置同为持久化 exchange。
AST 静态测试禁止 probes/golden_router 调用 payload-only 方法面。

## 2. Trading Rule Run Binding + Review Gate（amendment to ADR-011）

### 2.1 Run 绑定（P0-03）

- SpikeRun 新增 `trading_rule_file/version/hash/review_status`（TRIAL/PRODUCTION
  创建时绑定；`compute_config_hash` 递归覆盖 `configs/**`，嵌套规则文件进入
  配置指纹）；
- RUNNING/RESUME/VERDICT/REPLAY 一律通过 `load_bound_rule_book`（文件 + bytes
  hash + version 三重校验）解析规则；工作树推进/篡改永不泄漏进历史 run；
- `ProbeContext.rule_book` 为 run-bound book，`route_all` 将其传入
  limit/BJ 验证器（`book=` 参数）。

### 2.2 Review Gate（P0-04）

- 规则数据集与 golden truth 同生命周期纪律：COMPILED（候选，仅 dry-run/trial）
  → REVIEWED（人工复核，进入 PRODUCTION 的前提）；
- REVIEWED 要求完整 provenance（reviewed_by/at + source_artifact_ref/hash/
  kind（allowlist）/retrieved_at），gate 复验 artifact bytes hash；
- `new_run(PRODUCTION)` 与 `compute_verdict(PRODUCTION)` 都执行该 gate
  （fail-fast + verdict 复核）；
- `scripts/rules/review.py`：reviewer 提供官方 artifact → 工具自算 SHA-256 并
  写入 REVIEWED 副本（复本自验证通过才算成功）；重复 review 拒绝。

### 2.3 st_state 严格解析（P1-04）

`_parse_st_state`：bool/true/false/any 之外一律 ValueError——`bool("false")==True`
的 truthiness 解析会静默反转规则，被禁止。

## 3. Corporate Action Event SoR（P0-05，C1 实现 closure）

CA 证据组合增加**事件事实源**（provider dividend/right-issue records）：

- 仅 adj 变动（无事件记录）→ `VALIDATED_FAIL(EVENT_SOURCE_MISSING)`
  ——adj 流本身不是充分事件源；
- 事件记录存在但 EX_DATE ≠ T → `EVENT_DATE_MISMATCH`；
- event + adj + kline T-1/T/T+1 一致 → PASS；事件日停牌 → `NOT_TESTABLE_TIME`；
- FakeTarget 提供 get_dividend_exchange（事件端点进 dry-run 覆盖）；
  CA 域 fetch 集合 = calendar + status + **dividend** + adj + kline。

## 4. 测试与验证

- 461 tests / 0 failed（420 → 461，+41）；ruff / mypy 全绿；
- dry-run 冒烟：33 exchanges 全部 meta-anchored + 5 bundles，整 run 双向
  闭合零问题；B4 123 cases 全路由（事件源缺失的 CA cases FAIL 诚实暴露）。

## 后果

- 证据链的可审计单元从"文件"变为"exchange"；审计可从任意 case 追溯：
  bundle → 每 exchange meta（完整请求参数 + run 绑定）→ 每 payload bytes；
- 制度规则集成为与 golden truth 同级的受治理数据集（版本化 + 绑定 + 审阅）；
- P0-M-1B Entry Gate 新增：Trading Rule REVIEWED + raw exchange closure。
