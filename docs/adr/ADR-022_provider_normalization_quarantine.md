# ADR-022: Provider Normalization and Quarantine（提供方归一化与隔离）

- **Status**: PROPOSED（2026-08-31，CR-2 批次交付 + CR-2.1 Amendment A 收口 + 2026-09-01 CR-2.2 Amendment B 收口 + 2026-09-01 CR-2.3 Amendment C 收口 + 2026-09-01 CR-2.4 Amendment D wiring 收口；Reviewer 复审裁决待定——本 ADR 在复审前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-08-31（CR-2）/ 2026-08-31（Amendment A，CR-2.1）/ 2026-09-01（Amendment B，CR-2.2）/ 2026-09-01（Amendment C，CR-2.3）/ 2026-09-01（Amendment D，CR-2.4）
- **Work Requirement**: `docs/design/A-share-analysis_R4-B2.3复审结论与CR-2_ProviderNormalizedQuarantine开发工作要求_20260831.md` + `docs/design/A-share-analysis_CR-2复审与CR-2.1最终SurfaceIdentity及CommitClosure收口要求_20260831.md` + `docs/design/A-share-analysis_CR-2.1复审与CR-2.2最终ReplayProvenanceSeal收口要求_20260901.md` + `docs/design/A-share-analysis_CR-2.2复审与CR-2.3最终RawTrustAnchor及OutputSeal收口要求_20260901.md` + `docs/design/A-share-analysis_CR-2.3复审与CR-2.4最终AnchoredIngestionBoundary收口要求_20260901.md`
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
对抗测试）+ DM-CR-20260831-064（CR-2.1 收口 amendment）+
DM-20260901-065（CR-2.2 Replay Provenance Seal amendment）+
DM-20260901-066（CR-2.3 Raw Trust Anchor + Operation Spec + Output Seal
amendment）+ DM-20260901-067（CR-2.4 Anchored Ingestion Boundary wiring
amendment）。相关：§44 CR-2 acceptance 对照。

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

---

# 7. Amendment B：CR-2.2 Replay Provenance Seal（2026-09-01，audit "CR-2.1复审与CR-2.2最终ReplayProvenanceSeal收口要求"）

CR-2.1 复审（2026-09-01 10:15 +08:00，Reviewed HEAD `70bb101`）裁决
**REOPENED**：CR-2.1 的收口方向保留，但 surface provenance、conflict
permanence、seal 消费三处 correctness identity 缺口由 CR-2.2 收口。
**本 amendment 修订 Amendment A 中被复审推翻的表述；原文保留在上文，
以本节为准。**

## 7.1 P0-01 Surface 真正 system-derived（修订 §6.1 的可选参数）

§6.1 中 `call_exchange(normalization_surface=...)` 的可选 caller 参数
**撤销**（audit §2：具备该参数意味着 call path 在 low level 可自由
声明 correctness 身份——例如带 daily_bar capability 却传出 index_daily
surface 的 envelope；与 B1/B2 "caller-declared identity is not
system-derived" 的裁决冲突）。CR-2.2 起：

```text
surface_identity = str(require_capability or "")   # capability 契约派生
```

- `call_exchange` 签名不再含 normalization_surface 参数（结构测试断言）；
  provider.py 中任何 `_call_or_exchange` 调用点不再携带该 kwarg；
- `query_kline_exchange`（require_capability=daily_bar）与
  `query_index_kline_exchange`（require_capability=index_daily）仅通过
  capability 区分——registry 的 normalization_surface 值本就等于
  capability 名（§6.1 的 18 条映射不变，无需数据迁移）；
- 由此同时修复"签名可选参数使 surface 归属从定义性降级为约定性"的问题。

## 7.2 P0-02 Raw Evidence Binding 冲突不可洗白 + 全历史 exact replay（修订 §6.3）

§6.3 的 latest-run hash equality 检查有两个缺陷（audit §3）：
conflict BLOCK 记录会把新 hash 写成下一次可接受 baseline（第二次运行
H2 就不再触发 hash conflict，closure 通过后可产出 SUCCESS）；
latest-run 比较会掩盖历史 exact match。CR-2.2 起：

**Binding（audit §3.4 Option A）**：

```text
baseline = DISTINCT raw_evidence_hash of the request's runs
           WHERE NOT evidence_conflict
current hash NOT IN baseline (and baseline non-empty)
  -> INCIDENT HARD BLOCK：conflict run 记录（evidence_conflict = TRUE，
     migration 016 新列），不改变 baseline；第二次/第三次运行同样 BLOCK
     （conflict run 自身按 exact key 幂等 replay，一 ledger 行）
修复回原始 bytes -> 原 run 照常 exact replay（baseline 未被污染）
```

**Exact replay lookup（audit §3.3）**：

```text
run_id = uuid5(namespace, idempotency_key)   # deterministic
存在 ledger -> _require_verified_replay（closure 复验后幂等返回）
不存在      -> 新 run
```

不再依赖 latest-run（ORDER BY started_at DESC LIMIT 1）比较：mapper
A -> B -> A rollback 后 replay 的是历史 A run（非 B 的重复、无
duplicate-PK 错误）；contract A -> B -> A 同理。全部 blocked 分支
（含 multi-table / accounting violation）统一走 exact lookup。

## 7.3 P0-03 Full Seal 消费（修订 §6.4 的 seal 边界）

- **Full mapper hash 进入 identity**（audit §4.1）：`_supported_key` /
  `_blocked_key` 混入 **完整** `MAPPER_CODE_FINGERPRINT`（64 hex）——
  显示串（`mapper_identity` 尾部 `#fp[:16]`）可缩短，correctness hash
  input 不得缩短；前 16 位相同的两个 fingerprint 产生不同 run identity
  （测试覆盖）。
- **Typed `NormalizationRunSeal`**（audit §4.5）：dataclass 承载 ledger
  侧 seal（run_id / provider / normalization_surface / provider_dataset /
  endpoint / raw_request_id / raw_evidence_hash / contract_version /
  mapper_identity / **mapper_code_hash(full)** / status / input_count /
  normalized_count / quarantined_count / quarantine_set_hash），
  `from_ledger()` 构造、`current_provenance_problems()`（ledger ==
  当前 contract + 当前 full fingerprint，defense in depth）、
  `manifest_binding_problems(manifest)`（manifest 全语义字段 == ledger
  seal + quarantine 三方绑定 manifest == ledger）。
- **Manifest policy typed 化**（audit §4.3）：SUCCESS/PARTIAL run 的
  manifest 为 REQUIRED（ledger status 翻转伪造不出 manifest-free 的
  healthy replay）；BLOCKED run 仅在物化了 empty-output evidence
  （row scope）时携带 manifest——携带即验证。
- **schema_hash 重算**（audit §4.4）：replay 时从物理 parquet 重算
  `sha256(str(frame.schema))` 与 manifest 比对——rebind 攻击（换
  parquet + 更新 content_hash）仍被 schema seal 拦截。
- **Rebind tamper 矩阵**（audit §4.6，10 项）：manifest
  surface/status/counts/quarantine_set_hash/mapper_code_hash 篡改 +
  重算外层 hash + UPDATE ledger hash -> DAMAGED；ledger
  status/quarantine seal/mapper_code_hash 篡改 -> DAMAGED；
  output schema 换绑 -> DAMAGED。

## 7.4 CR-2.2 对抗测试（17 项新增）

`tests/integration/test_provider_normalization.py`（84 项 = CR-2/2.1
67 项回归 + 17 新增）+ migration 16 链 from-zero/upgrade/tamper；
audit §2.4/§3.5/§4.6 清单全对应。总体 955/0。

## 7.5 Scope 边界

CR-2.2 仍不引入 CR-3 语义（AvailabilityPolicy / SourcePolicy /
Canonicalizer / SnapshotBuilder）；schema 变更仅 migration 016
（`evidence_conflict BOOLEAN DEFAULT FALSE`，未改 014/015）。

---

# 8. Amendment C：CR-2.3 Raw Trust Anchor + Operation Spec + Output Seal（2026-09-01，audit "CR-2.2复审与CR-2.3最终RawTrustAnchor及OutputSeal收口要求"）

CR-2.2 复审（2026-09-01 10:45 +08:00，Reviewed HEAD `a4a23cd`）裁决
**REOPENED**：exact replay / full fingerprint / schema verify 等 FREEZE，
但从"谁是 trust root"审查仍发现 3 个 P0。**本 amendment 修订
Amendment B 中被复审推翻的表述；原文保留在上文，以本节为准。**

## 8.1 P0-01 Provider-Owned Operation Spec（修订 §7.1 的 capability 派生）

§7.1 中 `surface_identity = str(require_capability or "")` 仍是
caller-declared——公开 `call_exchange(..., require_capability=...)` 允许普通
caller 自由选择 capability，等于把自报入口从 surface 字段换成了
capability 字段（audit §2.1：endpoint/dataset/fn 与 capability 可以不一致，
如 daily_bar capability + index surface 的组合语义未封死）。CR-2.3 起：

```text
ProviderOperationSpec(operation_id, capability, endpoint,
                      provider_dataset, normalization_surface)
  private STATIC 常量（operations.py，15 个 - 每个 facade wrapper 一个）
public typed wrapper -> 静态 spec 常量 -> private _execute_exchange(spec, fn,
  params)（endpoint/dataset/capability/surface/operation_id 全部由 spec 派生）
```

- `call_exchange` / `_call_or_exchange` **撤销**（公开面不再存在 generic
  exchange callable）；executor 私有且签名仅 `(spec, fn, params)`；
- `query_kline_exchange` -> `DAILY_BAR_KLINE` spec，
  `query_index_kline_exchange` -> `INDEX_DAILY_KLINE` spec（AST 测试断言
  绑定）；
- RawEnvelope / raw meta 新增 `operation_id`（spec 派生，持久化并进入
  anchor 交叉绑定）；
- 结构守卫：15 个 operation spec 与 `SDK_METHOD_CLASSIFICATIONS`
  （capability, endpoint）及 normalization registry（surface, dataset,
  endpoint）**双向 exact 核对**；3 个 NOT_APPLICABLE optional surface 无
  spec（pipeline 从不 exchange）；
- 公开方法签名检查：任何 public 方法不含 endpoint / dataset /
  require_capability / capability / normalization_surface / spec 参数。

## 8.2 P0-02 Raw Evidence Trust Anchor（修订 §7.2 的 baseline 信任根）

§7.2 的 baseline（normalization run history）不是 ingestion-time
trust root：CR-2 第一次消费某 raw 时只是现场 hash 当前 meta 作为初始
baseline——`verify_meta_closure()` 只证明 payload 与 meta 声明一致，不证明
meta 自身仍是 RawWriter 落盘原字节（audit §3.1：首消费前单独改 meta 的
surface/endpoint/params/account 等非 payload-hash 字段可逃过 closure 成为
"初始真相"；§3.2：016 legacy 行默认 evidence_conflict=FALSE 也无法安全
识别 015-era 的 laundering history）。CR-2.3 起（audit §3.3 Option：anchor
ledger）：

```text
migration 017: meta_raw_evidence_anchor
  (provider, provider_dataset, request_id) PK / evidence_uri / evidence_hash
  / endpoint / operation_id / normalization_surface / payload_kind /
  ingest_run_id / created_at
governed ingestion flow: RawWriter commit meta LAST -> reread persisted
  bytes -> sha256 -> record anchor（record_raw_evidence_anchor：同 bytes
  幂等；异 bytes hard fail RawAnchorError - anchor 永不 re-baseline）
NormalizationRunner（在任何 meta 解析/路由/映射之前）:
  anchor 缺失（legacy pre-017 raw）-> RAW_ANCHOR_MISSING BLOCKED
    （fail closed；governed repair = re-ingest；绝不 auto-grandfather）
  current hash != anchor.evidence_hash -> RAW_ANCHOR_MISMATCH
    INCIDENT HARD BLOCK（evidence_conflict=TRUE 仅诊断；anchor 即信任根 -
    重复运行永续 BLOCK；修复回原 bytes -> 原 run exact replay）
```

- `evidence_conflict`（016）**降级为诊断/audit 属性**：correctness trust
  root 是 anchor ledger，不是 normalization run history；旧 baseline
  DISTINCT-hash 查询删除；
- 015-era legacy history（H1 SUCCESS + H2 conflict，均无 anchor）升级后
  **H2 绝不被信任**：无 anchor -> 永续 fail closed；migration 不做任何
  auto-anchor（多 hash / conflict history 只能人工或重新取数）；
- anchor 记录本身：同 request 异 bytes -> `RawAnchorError`（hard fail，
  anchor 不可 re-baseline）。

## 8.3 P0-03 Expected Output Exact Set + Semantic Value Seal（修订 §7.3 的 seal 边界）

§7.3 的 seal 未封住 expected output set 与 normalized values（audit
§4.1/§4.2）：从 manifest 删除一个 output 再重绑双 hash，verifier 只遍历
"剩下的 outputs"；parquet 值整体换成同 schema/row_count 的另一份并重绑
content/manifest hash，没有 ledger-bound semantic hash 证明值未替换。
CR-2.3 起（migration 017 两列）：

```text
normalized_output_set_hash = hash(sorted(output_name, canonical uri,
  content_hash, schema_hash, row_count))
  三方消费: ledger == manifest.output_set_hash == replay-time 物理重算
normalized_semantic_hash = 全输出表 sorted canonical JSON hash
  三方消费: ledger == manifest.semantic_hash == replay-time 物理重算
expected exact set: manifest output_name set == CURRENT registry
  spec.output_names（no missing / no extra / no duplicate）
URI deterministic binding: 每 output uri == ledger 身份重算的
  base_path + output_name（不接受 manifest 任意 logical URI）
```

- 物化语义升级：materialized output set **恰好等于** spec.output_names
  （空表也物化为空 parquet——空表本身是"零产出、无 sentinel"证据）；
- `NormalizationRunSeal` 扩展 `raw_evidence_uri / raw_payload_kind /
  normalized_output_set_hash / normalized_semantic_hash`；manifest 新增
  `raw_payload_kind / output_set_hash` 字段；
- pre-CR-2.3 ledger 行缺两 seal -> replay 不作 healthy（要求重跑当前
  contract）。

## 8.4 CR-2.3 对抗测试（+20 项）

`tests/integration/test_provider_normalization.py`（104 项 = CR-2/2.1/2.2
84 项回归 + 20 新增）+ migration 17 链（from-zero + 001..016->017 upgrade +
idempotent + tamper probe 018）；audit §6 A/B/C/D 矩阵全对应。总体 975/0。

## 8.5 Scope 边界

CR-2.3 仍不引入 CR-3 语义；schema 变更仅 migration 017（anchor 表 + 两
seal 列，未改 014/015/016）。通过后 CR-2.x 全链 CLOSED / FREEZE，ADR-022
ACCEPTED，CR-3 START——**不再扩张 CR-2 scope**。

---

# 9. Amendment D：CR-2.4 Anchored Raw Ingestion Boundary（2026-09-01，audit "CR-2.3复审与CR-2.4最终AnchoredIngestionBoundary收口要求"）

CR-2.3 复审（2026-09-01 14:26 +08:00，Reviewed HEAD `81d6b8d`）裁决
**REOPENED**：operation spec / anchor schema+runner verification /
output-set+semantic seal 三块 **PASS / FREEZE**，但 anchor enrollment
未形成 production-owned boundary（enrollment 机制存在，正式写入链未接线；
测试靠 helper 手工模拟 governed flow；recorder 只 hash "调用时看到的
meta"，write→enroll 之间存在 TOCTOU / late-enrollment blessing 窗口）。
**本 amendment 只补 wiring；上文已冻结语义不变。**

## 9.1 AnchoredRawEvidenceWriter（audit §3.1）

```text
AnchoredRawEvidenceWriter(conn, raw_root, *, ingest_run_id)
  write_exchange(exchange) -> RawWriteResult      # the ONE boundary
    1. RawWriter.write(exchange)                  # file commit (meta LAST)
    2. reread persisted meta bytes - VERIFY-ONLY
       require sha256(reread) == RawWriteResult.evidence_hash
       (write -> enroll 之间的 TOCTOU 换字节 -> 整体 HARD FAIL，H2 永不 enroll)
    3. identity cross-binding: meta 的 request_id/provider/provider_dataset/
       endpoint/normalization_surface/operation_id == exchange envelope
       （伪造 meta 身份字段 -> BLOCK）；uri cross-binding（evidence_uri ==
       meta_uri == canonical request-addressed uri）
    4. enroll immutable anchor（keyed to the COMMIT identity）
    5. return RawWriteResult                      # ingest 至此才算完成
```

关键：anchor expected hash 的来源是**本次 RawWriter commit 的 output
identity**；最终 reread 是 verify-only，不能在没有 cross-binding 的情况
下自行定义首次真值。

## 9.2 全部 production evidence 写入切到 anchored boundary（audit §3.2）

- `ProbeContext.__init__` 新增必需 `conn` 参数；`raw_writer` 变为
  `AnchoredRawEvidenceWriter`（`evidence_from_exchange` /
  `failure_evidence` → 同一 `write_exchange`——SUCCESS 与 ERROR exchange
  均自动 anchor）；
- `run_dry_run` 打开 in-memory migrated DB（repo migrations 全链）供
  ProbeContext——框架自检走与 production 完全相同的 anchored 写路径；
- 结构守卫（AST）：`src/ashare_state` 中 RawWriter 的
  write/write_success/write_failure 调用点只允许出现在 raw_writer.py
  （定义本身）与 raw_anchor.py（anchored boundary 内部）；reader
  （`RawWriter.read`）不受限（normalization runner 只读消费）。

## 9.3 Enrollment 可恢复但不可 rebaseline（audit §3.3）

- anchor INSERT 注入失败 → write_exchange 抛出 → **本次 governed ingest
  失败**（evidence 不 ready）；Raw bytes（H1）在盘、无 anchor →
  Normalization RAW_ANCHOR_MISSING fail closed；
- exact retry 同一 exchange：RawWriter idempotent（same bytes ignoring
  ingested_at → no-op → evidence_hash 从磁盘首 commit bytes 计算 = H1）→
  enrollment 成功 → **一个 immutable anchor、单一 evidence identity**；
- 已有 anchor H1：same H1 idempotent / H2 hard conflict（RawWriter 不可变
  写先行拦截 + anchor CONFLICT 双保险）；anchor 永不 rebaseline。

## 9.4 Enrollment API 收口（audit §3.4）

- 公开 `record_raw_evidence_anchor`（"看现场 bytes 建首次 anchor"）**撤销**；
  enrollment primitive 私有化为 `_enroll_anchor(conn, raw_root, *,
  provider, provider_dataset, request_id, evidence_hash, ...)`——
  `evidence_hash` 是必填的**调用方声明 commit identity**，函数内部
  verify-only 比对磁盘（不再自行 hash 现场 bytes 定义真值）；
- 模块公开面：`AnchoredRawEvidenceWriter` /
  `persist_exchange_with_anchor`（便捷一次性）/ `lookup_raw_evidence_anchor`
  （只读）/ `RawEvidenceAnchor` / `RawAnchorError`；
- tests 制造 legacy/unanchored 或 governed-reingest 夹具时直接使用私有
  primitive（tests-only，B2 scanner static registry 同一裁决口径）。

## 9.5 CR-2.4 对抗测试（+10 项）

`tests/integration/test_provider_normalization.py`（114 项 = CR-2/2.1/2.2/
2.3 104 项回归 + 10 新增：ProbeContext SUCCESS/ERROR anchor 2 / 结构守卫
1 / TOCTOU 1 / enrollment 失败恢复 1 / same-H1 idempotent 1 / H2 hard
conflict 1 / anchored→runner SUCCESS 1 / identity cross-binding 1 / API
收口 1）；audit §4 17 项矩阵全对应。总体 985/0。

## 9.6 Scope 边界

无 schema 变更（复用 migration 017 anchor 表）；不重写 operation spec /
runner anchor lookup / output-set semantic seal；CR-3 语义零引入。
