# ADR-022: Provider Normalization and Quarantine（提供方归一化与隔离）

- **Status**: PROPOSED（2026-08-31，CR-2 批次交付 + CR-2.1 Amendment A 收口；Reviewer 复审裁决待定——本 ADR 在复审前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-08-31（CR-2）/ 2026-08-31（Amendment A，CR-2.1）
- **Work Requirement**: `docs/design/A-share-analysis_R4-B2.3复审结论与CR-2_ProviderNormalizedQuarantine开发工作要求_20260831.md` + `docs/design/A-share-analysis_CR-2复审与CR-2.1最终SurfaceIdentity及CommitClosure收口要求_20260831.md`
- **Related**: [ADR-021](ADR-021_publish_validation_exactness.md)（其 B1/B2 的 boundary/registry/seal 模式被本 ADR 复用于数据层）；CR-1（RawWriter exact evidence，输入侧）

## 1. Context（audit 20260831 §3-§4）

CR-1 + R4-A2.x 已提供 exact persisted `ProviderExchange → RawWriter → Raw
immutable evidence`；`mapper.py` 对 required field 执行严格解析
（`MappingValidationError` 明确写着 "row quarantined by the caller"）；
`dto.py` 明确 Provider-Normalized 是 provider-faithful 层。但"caller 实际
如何从 Raw evidence deterministic 地执行 mapper、如何持久化 normalized
结果、如何落 Quarantine、如何保证没有 silent drop"尚未形成正式
runtime——CR-2 关闭这一缺口。

## 2. Decision

### 2.1 Raw Evidence 是唯一正式输入（CR2-P0-01）

`NormalizationRunner.run(provider, provider_dataset, request_id)` 只消费
**已持久化的 raw evidence**：定位 `.meta.json` → `verify_meta_closure`
（复用现有 closure 校验）→ `RawWriter.read(verify=True)`（复用现有
verified reader）→ mapper。runner 全程无 provider/SDK 访问（结构性测试
断言无 provider-module import）。失败 exchange（ERROR meta、无业务
payload）不是 mapping failure：记录 `SOURCE_EXCHANGE_FAILED` BLOCKED run，
保留原 failure evidence，不进 normalized 主输出。

### 2.2 Typed Dataset Normalization Registry（CR2-P0-02）

`ashare_state.normalization.registry`：STATIC production-owned 注册表，
keyed by `(provider_dataset, endpoint)`——exact routing，无模糊匹配。
每个 surface 显式分类（SUPPORTED_NORMALIZATION / BLOCKED_PENDING_MAPPER /
NOT_APPLICABLE）；结构守卫测试 AST 抽取 provider 全部 14 个
(dataset, endpoint) 对并要求注册表 exact 覆盖——新增 surface 无分类
决策即测试红。

当前分类：9 个 SUPPORTED（trade_calendar=WHOLE_PAYLOAD；code_list /
hist_code_list / stock_basic / daily_bar / history_stock_status(三输出) /
adj_factor / backward_factor / equity_structure / industry_constituent
=ROW）；5 个 BLOCKED_PENDING_MAPPER（dividend / right_issue /
bj_code_mapping / industry_base_info——mapper 未具备足够已验证字段语
义，fail closed 不 silent skip）。caller 不能注入 mapper/evaluator。

### 2.3 First-Class Immutable 持久化输出（CR2-P0-03）

normalized 输出不是内存 DTO list：每 run 落
`normalized/provider=<P>/dataset=<D>/raw_request=<rid>/contract=<cr2-v1>/`
下——每输出表一个 parquet（canonical 排序：按全部列排序，消除输入行
序影响）+ `manifest.json`（绑定 raw evidence uri/hash/request/table、
contract 版本、mapper identity、输出表 uri/content_hash/schema_hash/
row_count、semantic_hash、counts、status）。ledger 表
`meta_provider_normalization_run`（migration 014）记录同一绑定的
lineage/summary。URI 构造经 frozen logical-URI confinement（组件校验
+ `physical_from_logical_uri`）；artifact 不可变（同 bytes 幂等 no-op，
异 bytes conflict BLOCK）。

### 2.4 No-Silent-Drop Accounting（CR2-P0-04）

ROW scope：runtime 机器强制
`input_row_count == mapped_row_count + quarantined_row_count`——违反即
BLOCKED run（NORMALIZATION_INTERNAL_ERROR）。mapper 非
MappingValidationError 异常**不被吞掉**：记为
NORMALIZATION_INTERNAL_ERROR quarantine（带 row locator）并使 run
BLOCKED。WHOLE_PAYLOAD scope（trade_calendar）：任一非法元素 → 零
normalized 输出 + 一条 WHOLE_PAYLOAD quarantine + BLOCKED——不产出
"看似完整"的过滤日历。

### 2.5 Quarantine 是 First-Class Evidence（CR2-P0-05/06）

`meta_provider_quarantine`（migration 014，append-only）：quarantine_id /
run 绑定 / provider+dataset / raw request_id / raw evidence uri+hash /
raw table name / **raw_row_ordinal**（ROW scope）/ source_key（自然键，
best-effort，不替代 locator）/ scope / error_class / error_message /
scrubbed structured error context（credential-shaped key 递归 REDACT）/
mapper identity / contract 版本 / created_at。multi-table payload 严格按
meta 声明的 table identity 路由（spec.source_table；无路由声明 →
PAYLOAD_SHAPE_UNSUPPORTED BLOCK，不取第一个 table）。

### 2.6 Determinism / Idempotency（CR2-P0-07）

- run_id = uuid5(namespace, idempotency_key)，key = sha256(raw evidence
  hash + contract version + mapper identity)——同输入重放得同 run id；
- idempotent replay：同 (provider, dataset, request) 且 evidence hash 与
  idempotency key 匹配既有 run → 直接返回既有结果（零重复 ledger /
  quarantine 行）；
- semantic_hash：全部输出表的 sorted canonical JSON hash——重放比较忽略
  墙钟与 parquet 级元数据；行序无关（输入 reversed 的两个请求 semantic
  hash 相等，测试覆盖）；
- 同 request id 出现**不同** raw evidence bytes → RAW_EVIDENCE_INVALID
  BLOCKED run（immutable raw store 本应阻止；若发生即外部篡改信号）。

### 2.7 错误分类与状态机（CR2-P0-08/10）

error_class 五类（RAW_EVIDENCE_INVALID / SOURCE_EXCHANGE_FAILED /
PAYLOAD_SHAPE_UNSUPPORTED / MAPPING_VALIDATION_FAILED /
NORMALIZATION_INTERNAL_ERROR）——provider error 与 mapping error 永不混
淆。run status：SUCCESS（全过零 quarantine）/ PARTIAL（row quarantine
且 registry 允许）/ BLOCKED（whole-payload quarantine / unsupported /
raw invalid / exchange failed / internal error / partial 不允许）。
PARTIAL 是否允许由 registry 逐 surface 声明，caller 不能临时决定。

### 2.8 Provider-Faithful（CR2-P0-09）

注册的 mapper 就是既有 provider-faithful mappers：provider literals /
provider units / 未验证标记（GALAXY_UNVERIFIED / UNVERIFIED）原样通过
（测试断言 taxonomy_owner==GALAXY_UNVERIFIED、volume 保持 provider 数
值、symbol 保持后缀格式）。history_stock_status 按任务书 1.3 路由到
三输出（全字段镜像 + limit-price projection + CA-flag projection，
event_type="STATUS_FLAG_PROJECTION" 诚实标注投影来源）。

## 3. Alternatives Considered

**Q：为什么不直接在 RawWriter 写入时同步 mapper（pipeline 内联）？**
归一化是独立的数据层转换，有自己的 contract 版本 / 重放语义 / quarantine
生命周期；与 evidence 持久化耦合会让"修 mapper 后重新归一化"不可能
（raw 是 immutable 的）。分层使 CR-3 可以在不变的 raw 之上按新 contract
重跑。

**Q：为什么 quarantine 落 DB 表而不是 parquet/log？**
quarantine 记录需要按 run / request / locator 可查询（CR-3 消费检查、
人工审计）；JSONL/parquet 缺少索引与 append-only 约束的执行面。ledger
表（meta_provider_quarantine）+ run manifest 双锚定；normalized 主输出
仍是 parquet（行数据不塞 metadata 表）。

**Q：为什么 run_id 用确定性 uuid5 而不是随机？**
P0-07 要求同输入重放不产生不可区分的重复记录——确定性 id 使 replay
天然命中既有 run 行（幂等 no-op），无需先查后插的竞态窗口。

**Q：semantic_hash 为什么不直接用 parquet bytes hash？**
parquet 编码可能含环境级元数据（writer 版本），跨机器/版本字节可能不
稳定；语义等价性（行集 + 值）用 canonical JSON 排序 hash 才是确定性的。
artifact content hash 仍记录用于完整性，但 replay 语义比较用
semantic_hash。

**Q：为什么 corporate_action / bj_mapping / industry_base_info 是
BLOCKED_PENDING_MAPPER 而不是"尽力解析"？**
工作要求 §5 明确：mapper 未具备足够已验证字段语义时必须显式
BLOCKED，不得伪造完成。"尽力解析"半验证字段正是 sentinel 风险的来
源；fail closed + 显式分类让缺口可审计、可排期。

## 4. Consequences

- **正向**：raw → normalized 的转换成为可重放、可审计、fail-closed 的
  正式 runtime；坏数据可精确定位到 raw request/table/row；silent drop
  与 sentinel 在结构上不可能；CR-3 只需消费 manifest 绑定的 normalized
  artifacts。
- **代价**：每 run 逐行 mapper（无批量优化——当前规模可接受）；registry
  新增 surface 需同步分类决策（结构守卫强制）；BLOCKED_PENDING_MAPPER
  的 surface（dividend / right_issue / bj_mapping / base_info）在 mapper
  就绪前不可归一化（诚实状态，不是回归）。
- **残余边界（如实记录）**：mapper 本身的字段语义正确性（如 provider
  单位换算）属 B5/B6/B7 验证域，CR-2 只保证"忠实转换 + 坏记录隔离"，
  不预支语义验证结论。

## 5. DM 登记

管理总册 §61：DM-CR-20260831-063（registry + runner + migration 014 +
对抗测试）+ DM-CR-20260831-064（CR-2.1 收口 amendment）。相关：§44 CR-2
acceptance 对照。

---

# 6. Amendment A：CR-2.1 Final Closure（2026-08-31，audit "CR-2复审与CR-2.1最终SurfaceIdentity及CommitClosure收口要求"）

CR-2 复审裁决 **REOPENED**：核心框架 FREEZE（§1-§5 不变），但 4 个 P0
correctness 缺口由 CR-2.1 收口。**本 amendment 修订 §2 中被复审推翻的表述；
被修订原文保留在上文，以本节为准。**

## 6.1 P0-01 Surface Identity（修订 §2.2 的二元 key）

§2.2 的 `(provider_dataset, endpoint)` 二元 key 不足以区分共享同一
endpoint+dataset 的**不同业务 surface**（stock daily_bar 与 index daily_bar
均走 `MarketData.query_kline` + `provider_dataset=daily_bar`）。CR-2.1 起：

- registry key 为 typed 四元组 `(provider, normalization_surface,
  provider_dataset, endpoint)`；
- `normalization_surface` 是 **system-derived 持久化身份**：provider facade
  在 `call_exchange` 上派生（默认取 capability 身份），由 RawWriter 写入
  raw meta（向后兼容字段，legacy 无此字段不破坏）；**禁止**从 request 参数
  / symbol 前缀推断；
- `query_kline_exchange`（surface=daily_bar → DailyBarDTO）与
  `query_index_kline_exchange`（surface=index_daily → IndexDailyDTO）是两个
  显式 production wrapper；
- legacy raw evidence 在**歧义** pair 上缺 surface 字段 →
  `PAYLOAD_SURFACE_AMBIGUOUS` BLOCKED（fail closed，不猜）；非歧义 pair 仍
  可路由（向后兼容）；
- 新错误类 `PAYLOAD_SURFACE_AMBIGUOUS` 加入 §2.7 分类表（六类）；
- Coverage guard 升级：provider facade AST surfaces **与**
  `SDK_METHOD_CLASSIFICATIONS` 交叉核对——每个 capability/SDK surface 必须
  显式属于 SUPPORTED / BLOCKED_PENDING_MAPPER / NOT_APPLICABLE 三类之一；
  optional 未消费 surface（`InfoData.get_index_daily` / `get_industry_weight`
  / `get_industry_daily`）声明 NOT_APPLICABLE，不从 structural truth 消失。

**P1-02 count 更正（runtime exact-set 统计，不再手写）**：registry 共 18 条
——11 SUPPORTED（含 index_daily@query_kline 新增）/ 4 BLOCKED_PENDING_MAPPER
/ 3 NOT_APPLICABLE。§2.2 原文的 "9/5" 与实际不符（该批实际为 10/4），以
本 runtime 统计为准。

## 6.2 P0-02 Immutable Registry（修订 §2.2 的公开 dict）

`DATASET_NORMALIZATION_REGISTRY` 公开可变 dict **撤销**。CR-2.1 起 registry
是 module-private 不可变 tuple（`_REGISTRY_SPECS`）+ private exact index
（`_REGISTRY_INDEX`），公开面只有只读函数 `lookup_spec` / `specs_for` /
`registry_specs`（返回不可变 tuple snapshot）。`NormalizationRunner` 的
构造器与 `run()` 均不接受 spec/mapper/registry/surface 参数（签名结构测试
断言）。tests-only 注入仅经 monkeypatch 私有 module state（与 B2 scanner
static registry 同一裁决口径：正常 production callable / exported mutable
object 不是注入路径）。

## 6.3 P0-03 One Exact Replay Policy（修订 §2.6）

§2.6 的幂等只覆盖 supported happy path。CR-2.1 起 **SUCCESS / PARTIAL /
BLOCKED 全部**走同一 exact replay policy：

```text
same exact input identity（evidence hash + contract + mapper identity）
-> 重验既有 run closure（manifest bytes == ledger hash / outputs
   bytes+row_count == manifest / quarantine exact set seal == ledger）
-> intact => idempotent return（零重复行/文件）
-> damaged/tampered/missing => NormalizationRunnerError fail closed
   （repair required，绝不 false healthy replay）
```

- mapper code identity 进入 exact run identity：**system-derived**
  `MAPPER_CODE_FINGERPRINT` = SHA-256 over governed mapper + DTO module
  sources（行尾归一，跨 OS 确定性）——mapper 实现变更产生**新 run
  identity**（历史保留不覆盖），不依赖开发者记得 bump version 字符串；
  原 `code_commit` caller 自报参数撤销（不再进入 API）；
- CR-2 legacy ledger 行缺 `quarantine_set_hash` seal → 永不 replay 识别为
  healthy（要求按当前 contract 重跑）；
- contract 版本 bump 为 `cr2.1-v1`（registry 语义变更——typed surface key
  / index routing / NOT_APPLICABLE——保证 CR-2 旧 run 不被静默重用）。

## 6.4 P0-04 Atomic + Recoverable Commit Closure（修订 §2.3/§2.5）

写入协议（对齐 RawWriter 已验证模式）：

```text
1. derive exact deterministic run identity（含 mapper code fingerprint）
2. 写输出 parquet（ROW scope 全输出表物化——全坏行时空 parquet 即
   "零产出、无 sentinel"证据；WHOLE_PAYLOAD 坏则零输出）
3. manifest.json 最后落盘（file-side anchor）——correctness bytes
   不含墙钟（无 started_at/completed_at）与 caller 自报 provenance，
   exact retry 字节不变（同 bytes 不可变写为 no-op）
4. BEGIN DuckDB TRANSACTION：
     dup run 冲突检查 -> INSERT run ledger -> INSERT 全部 quarantine
     -> 持久化行数 == 声明数断言
   COMMIT（任一失败 ROLLBACK 整体回退）
5. DB 失败后 exact retry：文件侧确定性 anchor 幂等 no-op -> ledger
   reconciliation 完成（无 orphan manifest / 无半提交 quarantine）
```

- artifact 路径加入 `run=<run_id>` 段：mapper/contract 变更产生新 run 的
  新路径，不与历史 run 文件冲突；
- **quarantine exact-set seal**：`quarantine_set_hash` = canonical hash
  over sorted semantic records（无墙钟/随机 id），同时绑定 run manifest 与
  ledger（migration 015 三列：`normalization_surface` / `mapper_code_hash`
  / `quarantine_set_hash`；legacy NULL = 不做 healthy replay）；后续
  UPDATE/DELETE/缺行由 replay 复验发现；
- 状态机细化：`mapped == 0 且有 quarantine` → BLOCKED（PARTIAL 语义 =
  **有好行保留**；零保留不是 partial）；mapper internal error 行按行级
  隔离（error class 区分），状态按保留规则判定。

## 6.5 CR-2.1 对抗测试（67 项全量，含 CR-2 38 项回归）

audit §7 清单 19 项全对应：surface 双路由不碰撞 / legacy 歧义 fail
closed / 覆盖守卫交叉核对（facade AST + SDK classifications ==
registry exact set，18 条）/ 无公开可变 registry + API 签名无注入面 /
BLOCKED 幂等 / SOURCE_EXCHANGE_FAILED 幂等 / PARTIAL 幂等同 seal /
输出篡改+删除 rerun fail closed / manifest 篡改+删除 rerun fail closed /
quarantine 删行+改行 rerun fail closed / 注入 ledger INSERT 失败 exact
retry 恢复 / 注入 quarantine INSERT 失败回滚恢复 / 多输出写失败无假
anchor / mapper code identity 变更新 run / 双干净环境同 manifest identity
/ happy path 回归（no-sentinel / locator / calendar / provider-faithful /
no-silent-drop / URI confinement）/ migration from-zero + upgrade（15 链，
001..014 先应用再补 015 仅应用尾部）/ 全 CI 矩阵 / 冻结回归零破坏。

## 6.6 Scope 边界（复审 §8 重申）

CR-2.1 仅做 Raw -> Provider-Normalized + Quarantine correctness closure；
**未引入** AvailabilityPolicy / SourcePolicy reconciliation /
cross-provider Canonical selection / SnapshotBuilder / Feature / State
（CR-3 语义零泄漏，测试断言）。
