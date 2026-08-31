# ADR-021: Publish Validation Exactness（发布验证精确性）

- **Status**: PROPOSED（2026-08-30，R4-B2 批次交付；Reviewer 复审裁决待定——本 ADR 在复审前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-08-30
- **Work Requirement**: `docs/design/A-share-analysis_R4-B1.2复审结论与R4-B2_PublishValidationExactness开发工作要求_20260830.md`
- **Related**: [ADR-020](ADR-020_endpoint_requirement_contract.md)（其 Approval Anti-Bypass Option A 模式被本 ADR 复用于 publish validation）；V1.3.2 §2.10/§6.44（publish 原子契约，FREEZE）

## 1. Context（audit 20260830 §2）

B1 解决了"capability 的必要 provider endpoint 是否被真实、精确、持久化地证明
可用"；B2 必须解决"什么证据足以把一个 feature artifact set 判定为真正可
发布，并保证 publish 消费的是 exact validated artifact"。

R4-B2 之前的结构缺陷（与 B1 早期 approval bypass 同构）：

```text
record_artifact_validation(feature_artifact_set_id, ...,
                           identity_fallback_count, blocking_dq_count)
  -> caller 直接提交两个计数写进 append-only ledger
  -> 函数自己不执行任何 artifact validation
publish_snapshot()
  -> 取 latest validation record
  -> counts == 0 即通过 publish validation gate
```

即 `caller self-declare "0 fallback / 0 blocking DQ" -> PASS-shaped
record -> publish eligible`。同时：

- gate 只有两个 aggregate count，无法证明"required checks 是否全部执行"；
- validation 只绑定 `feature_artifact_set_id` 字符串，不绑定
  artifact/component 的 exact identity（bytes/schema/row/manifest）；
- precheck 在 `BEGIN TRANSACTION` 之前完成，之后才开 publish 写事务
  （TOCTOU：precheck 与 commit 之间状态变化不会被发现）；
- `validated_at` 由 caller 侧写入，latest-head 选择可能被旧 PASS 规避。

已有正确基础（FREEZE 保留）：`meta_artifact_validation` append-only、
`meta_publish_snapshot.artifact_validation_id` 精确绑定、单事务原子
republish、at-most-one-PUBLISHED、exact replay readers。

## 2. Decision

### 2.1 B2-01：唯一正式 validation 执行边界（Option A 结构性关闭）

新模块 `pipeline/artifact_validation.py`。旧
`record_artifact_validation()` **从生产命名空间删除**（B2-01 第 5 条的
更强形式：不留内部 primitive，直接消灭）。`meta_artifact_validation` 的
INSERT 全仓库**唯一**出现在 `validate_artifact_for_publish` 函数体内
（AST 守卫强制，测试断言 `inserters == {("artifact_validation.py",
"validate_artifact_for_publish")}`，且其签名无 count/result/checks/
report 参数）。

counts 是 **validator 派生值**：新表 `meta_artifact_dq_finding`（migration
011，append-only）持久化 DQ **坏事实**（IDENTITY_FALLBACK /
BLOCKING_DQ 两类，finding_class 白名单校验）；validator 以
`SELECT count(*) ...` 派生两计数。caller 只能通过
`record_artifact_dq_finding` **追加坏事实**（使 publish 更难），结构上
不可能通过它制造 PASS。

沿 B1.2 Option A 的教训：不引入任何"verified object"/private helper 中间
层——ledger INSERT inline 在边界函数尾部，"到达写入点 = 通过全部 check"
是同一控制流内的事实。

### 2.2 B2-02：Typed Required Check Contract

`ArtifactValidationCheckId` 十类 required check（工作要求 §4 全集）：
ARTIFACT_MANIFEST_INTEGRITY / COMPONENT_EXISTENCE / COMPONENT_CONTENT_HASH /
COMPONENT_SCHEMA_HASH / COMPONENT_ROW_COUNT / FEATURE_FAMILY_COVERAGE /
FEATURE_SET_VERSION_MATCH / DATA_SNAPSHOT_BINDING / IDENTITY_FALLBACK_ZERO /
BLOCKING_DQ_ZERO。语义：

- status ∈ {PASS, FAIL, NOT_TESTABLE}；NOT_TESTABLE 即 blocking（不可证
  = 不可发布）；
- publish eligibility = required check set **完整**（集合相等，unknown
  check 不能替代）且全部 PASS——aggregate counts 只是报告摘要；
- 物理字节级重验：content_hash 逐文件 sha256；schema_hash 从 parquet
  实际 schema 生成 canonical "name TYPE" 文本（arrow→duckdb 类型映射）
  再 hash；row_count 从 parquet metadata 读取；
- FEATURE_FAMILY_COVERAGE：components 的 (feature_family,
  feature_family_version) distinct 集合 == meta_feature_set_member 的
  (feature_id, feature_version) 集合（为此 mock_e2e 的 component
  feature_family 对齐 member id——B2 允许的必要适配，物理 bytes 不变）；
- contract 本身有 identity（`validation_contract_hash()`：版本 + required
  check 集 + seal 字段 + count 源的 canonical JSON hash）——改 check 集
  即改 contract hash，旧 seal 不再匹配。

### 2.3 B2-03/B2-04：Exact Artifact Identity Seal + 持久化 Report

ledger 行（migration 011 新增 6 列）seal：

```text
artifact_manifest_hash      # 注册时 manifest 身份的快照
component_manifest_hash     # B2 公式：全 component 字段（file_uri/content/
                            # schema hash/row_count/family/version/layer/
                            # partition）排序 canonical JSON hash
validation_contract_hash    # check contract 身份
report_uri / report_hash    # 持久化 report 绑定
required_checks_hash        # check 结果集 hash
```

report 物理落盘 `data_root/validation/<artifact_validation_id>.json`
（write_file_atomic，immutable bytes），内容含全部 seal 字段 +
checks[]（含每项 status/detail）+ derived summary counts。ledger 的
`detail` 只是摘要（checks_hash 前缀），correctness identity 全在 report。

### 2.4 B2-05：Transaction 内 Final Recheck（Option A）

`publish_snapshot` 新增 required 参数 `data_root`。全部 precondition
read 仍在事务外（快速失败，语义不变），但 **publish-critical 的
validation 重验移入事务内**（`_b2_recheck`）：

1. deterministic latest-head：`validated_at DESC, artifact_validation_id
   DESC`（B2-06——newer FAIL 天然压过 old PASS；`validated_at` 由 validator
   系统时钟写入，caller 无法自报）；
2. legacy 行（无 report_uri/report_hash）→ BLOCK（需 revalidation）；
3. report bytes 读取 + sha256 == ledger report_hash；report 的
   artifact_validation_id / feature_artifact_set_id == ledger / target；
4. current registered artifact_manifest_hash == seal（改 artifact 行即
   BLOCK）；current registry 重算 component_manifest_hash == seal（增删改
   component 行即 BLOCK）；
5. report checks：required 集合完整且全 PASS；
6. counts（validator 派生）== 0；
7. **物理字节终验**：每个 component 文件存在且 sha256 == 注册
   content_hash（validate 后文件被替换/删除，即使 registry 未变，也
   BLOCK——任何 content/schema/row 改动都改变 bytes）。

任何一步失败 → 异常 → ROLLBACK → 旧 PUBLISHED 保留（既有原子 republish
契约 FREEZE）。supersede/insert/universe/run 更新/uniqueness guard 逻辑
零改动。

### 2.5 B2-06：Latest-Head Policy

机器明确（见 2.4 第 1 步）：排序键 deterministic；同一 artifact 上
newer FAIL 是 head → 旧 PASS 不可选；legacy 无 seal 行不可选；
revalidation 后的 newer PASS（同一 exact identity + 当前 contract）
可选。caller 无 API 传入历史 validation id——publish 只消费 head。

## 3. Alternatives Considered（工作要求 §12 五问）

**Q1：为什么 caller-supplied zero counts 不是系统 validation truth？**
因为它绕过了全部验证语义：调用者没有读 artifact registry、没有碰物理
bytes、没有执行任何 check——只是断言结果。这正是 B1 关闭的
"caller self-declare APPROVED" 的 publish 变体。系统 truth 必须是"对
actual artifact 执行了可复验的计算"的输出；计数的可信度来自派生它们的
check 链，而不是来自声明。

**Q2：validation 如何绑定 exact artifact/component bytes identity？**
四层绑定：注册 manifest hash（artifact set 行）+ B2 component manifest
hash（全字段重算公式）+ 逐组件物理 sha256/schema/row 重验（validation
时）+ 事务内 final recheck（publish 时重算 registry 双 hash + 重验物理
bytes + report bytes hash）。seal 快照了 validation 时点的身份；任何后续
变化（registry 或磁盘）在 publish 时 fail closed。

**Q3：为什么 required check coverage 不能只靠 aggregate counts？**
两个 count 无法区分"检查过且通过"与"根本没检查"。typed check set 把
"必须证明什么"显式化为合同：完整性（集合相等）+ 逐项状态 + contract
hash。缺失的 check（如 schema hash 未验）在 counts 上完全不可见——但
它恰是"artifact 被换过 schema"这类攻击的唯一防线。

**Q4：publish-critical checks 为什么必须在 transaction 内 final recheck？**
事务外的 read 与事务内的 write 之间存在 TOCTOU 窗口：precheck 读到的
validation/components/bytes 可能在 BEGIN 与 COMMIT 之间被替换，而
publish 会 commit 基于旧读数的结论。DuckDB 单写者模型下事务内重读即可
关闭该窗口（Option A），不需要不可伪造 seal 对象的 Option B 方案（B 计
复杂度更高且仍依赖"seal 不可伪造"这一命名约定之外的性质）。

**Q5：legacy validation records 如何处理，为什么不能自动 grandfather？**
migration 008/010 的历史行没有 seal（无 report_uri/report_hash，无
component manifest）——机器无法回答"那次 PASS 验证的字节是否就是现在
要发布的字节"。自动 grandfather 等于把"身份不可证"静默当作"身份相符"，
是 fail-open。正确语义：legacy 行不 publish-eligible，需经
`validate_artifact_for_publish` 重新验证（append-only ledger 保留全部
历史行，旧 publish 的 lineage 查询不受影响——它们绑定的旧
artifact_validation_id 仍可 resolve）。

**被拒绝的替代方案**：

- **保留 record_artifact_validation 作为内部 primitive + wrapper 验证**
  （工作要求 §3 第 5 条的温和形式）：B1.1 的"verified object + private
  boundary"教训——Python 下划线不是访问控制，任何独立 callable 都是
  潜在绕过面。直接消灭 + AST 守卫更简单且结构上完备。
- **Option B（不可伪造 PublishApprovalSeal + 事务内比对）**：seal 的
  "不可伪造"本身需要一条验证链来定义，等价于把 A 的检查搬进 seal 构
  造期；多一层间接无净收益。
- **DQ findings 直接在 validation 调用时传入**：回到 caller-supplied
  truth。持久化事实表（append-only 坏事实）是计数可信的最小结构；
  事实流的完备性治理属 feature pipeline / CR-3 范围（见 §5 残余风险）。

## 4. Consequences

- **正向**：publish-eligible 的 validation PASS 只能由 validator 对
  exact artifact（registry + 物理 bytes）计算产生；TOCTOU 关闭；
  tamper（report/registry/bytes 任一层）fail closed；legacy 不静默放行；
  B1 的 Option A 模式在第二个领域复用成功。
- **代价**：`publish_snapshot` 新增 required `data_root` 参数（调用方
  必须提供数据根——它本就该知道）；publish 时逐组件 sha256 重算
  （I/O 成本与 artifact 大小线性，publish 低频可接受）；mock_e2e 的
  component feature_family 对齐 member id（registry 行为适配，物理
  bytes 不变）；feature 构建链需要在发现 fallback/blocking DQ 时写
  `meta_artifact_dq_finding`（当前仅测试与 mock 链使用）。
- **残余风险（如实记录）**：DQ finding 事实流的**完备性**取决于 feature
  构建链是否诚实记录——validator 只能数已持久化的事实，不能发现被隐瞒
  的 finding。这属于 feature pipeline 的 DQ 治理链（CR-3/DQ 域），不在
  B2 的"validation 不能 self-declare"范围内。
- **schema migration**：011 从零初始化 + 升级路径均测试（from-zero 11
  个 migration、idempotent rerun、tamper/sequence 守卫）；未修改任何
  旧 migration 文件。

## 5. DM 登记

管理总册 §61：DM-CR-20260830-054（formal boundary + typed checks +
DQ fact 表）/ DM-CR-20260830-055（exact seal + persisted report）/
DM-CR-20260830-056（transaction 内 final recheck + latest-head policy）。

---

## Amendment 2026-08-30（R4-B2.1，audit 20260830 19:13）——Final Validation Truth / Seal Consumption / Transaction Closure

> **Reviewer Verdict**：R4-B2 复审 **REOPENED**（4 P0 + 1 P1；机制性建设 16 项 PASS / FREEZE）。本 amendment 修正原文与运行时真相不一致的三处 overclaim，并记录四个 P0 + 一个 P1 的收口。原文保留供审计追溯。

### E.1 Overclaim 修正（原文 §2 的三处）

- **"contract hash changes invalidate prior seals"** —— 原实现 `_b2_recheck` 不比较 current contract hash，该声称不成立。R4-B2.1 P0-02 落地后成立（ledger ↔ report ↔ current 三方 exact match）。
- **"TOCTOU closed"** —— 原实现只把 validation/component recheck 放进事务，完整 lineage reads 仍在事务外，两句不能同时成立。R4-B2.1 P0-03 落地后成立（全部 authoritative reads 事务内）。
- **"required checks cannot be unexecuted"** —— DQ zero checks 原以 bad-fact absence 直接 PASS，"没跑过扫描"与"跑过且为零"不可区分。R4-B2.1 P0-01 落地后成立（positive execution proof）。

### E.2 P0-01：DQ Required Checks 的 Positive Execution Proof

新表 `meta_artifact_check_execution`（migration 012）：记录某 governed scan **确实执行过**——check_id / feature_artifact_set_id / scan_contract_version / producer / **scanned_component_manifest_hash**（exact 扫描输入身份）/ completed_at。**不含 count、不含 result**（`record_artifact_check_execution` 签名无 result 参数——AST 守卫 + 唯一 INSERT 边界）。

validator 语义：IDENTITY_FALLBACK_ZERO / BLOCKING_DQ_ZERO 要求存在 execution proof 且其 `scanned_component_manifest_hash == current` —— 无 proof → **NOT_TESTABLE**（absence of bad findings != proof of zero findings）；stale proof（组件已变）→ NOT_TESTABLE（rescan required）；匹配 proof + 派生 count==0 → PASS。findings 仍走 append-only 事实表；counts 仍是派生值。残余边界如实记录：execution proof 证明"扫描执行过且绑定 exact 输入"，不证明"扫描者诚实上报了全部 findings"——后者仍是 feature pipeline DQ 治理链（CR-3 域）的责任。

### E.3 P0-02：Full Seal Consumption（ledger ↔ report ↔ current contract）

`_b2_recheck` 扩展为完整 seal 交叉验证：

- `validation_contract_hash`：ledger == report == `validation_contract_hash()` **CURRENT**（语义性 contract 演进使旧 seal 失效——即使 check IDs 不变）；
- `required_checks_hash`：ledger == report == 对 report checks 数组重算的 hash（status 改动未重封即暴露）+ **duplicate check_id 拒绝**（防 dict collapse）；
- `validator_code_commit`：ledger == report 且非空；
- `validation_version`：ledger == report == 当前 supported 版本（**system-derived**——`validate_artifact_for_publish` 移除 caller version 参数，不再允许自报 provenance；无 silent grandfather）。

9 项对抗测试全部在 re-bind report hash（及 required_checks_hash）后仍 BLOCK。

### E.4 P0-03：Full Transaction-Internal Preconditions（Option A 完成）

原文 §2.4 的"precondition read 仍在事务外"描述废除。`publish_snapshot` 重构：**全部** authoritative reads（snapshot / artifact / feature set / pipeline run / universes / validation head / 完整 seal / 物理字节）在 `BEGIN TRANSACTION` 之后执行（`_resolve_publish_preconditions` helper 事务内调用；`_b2_recheck` 同）；写入只消费事务内值。AST ordering 守卫（测试）证明 BEGIN 先于 resolver/recheck/首个 execute。状态变化场景测试（snapshot demoted / artifact demoted/rebound / feature-set member 改动 / run 状态变化 / universe 删除）全部 BLOCK；失败 rollback 保留旧 PUBLISHED（FREEZE 契约零回归）。

### E.5 P0-04：Logical-URI Confinement（frozen P0-4 回归修复）

R4-B2 新增的物理文件读取（validator 组件重验 + publish bytes 终验 + report 读取）原先直接 `data_root / uri`——绕过 frozen helper。修正：全部经 `physical_from_logical_uri(data_root, uri)`（escaped / absolute / drive / backslash / alias URI 在 URI 层 fail closed，先于任何 data_root 外读取）。对抗测试：六类恶意 URI + **data_root 外 perfect sentinel**（bytes 与真实组件完全一致）仍被拒（COMPONENT_EXISTENCE FAIL，confinement 词记录在案）。

### E.6 P1-01：ARTIFACT_MANIFEST check 语义诚实化（Option B）

`ARTIFACT_MANIFEST_INTEGRITY` → **`ARTIFACT_MANIFEST_PRESENT_AND_SEALED`**：该 check 证明注册上游 seal 存在且非空；exact component integrity 由 component_manifest_hash seal + COMPONENT_* checks 证明（publish 侧另有 current registered artifact_manifest_hash == seal 比对）。当前 schema 无法无损重建 registration-time manifest formula（dataset 字段不持久化于 component 行），故不 overclaim 重算；ADR/report detail/tests 与运行时真相一致。

### E.7 治理状态

- R4-B2 机制性建设（16 项）FREEZE 保留；本 amendment 只记录四个 P0 + 一个 P1 的收口；
- DM 登记：§61 DM-CR-20260830-057（positive execution proof）/ 058（full seal consumption）/ 059（transaction-internal preconditions）/ 060（logical-URI confinement；含 P1 rename）；
- migration 012：`meta_artifact_check_execution`（from-zero 12 链 + idempotent + tamper 守卫全过；未改旧文件）。

---

## Amendment 2026-08-31（R4-B2.2，audit 20260831 08:03）——Final Governed DQ Scan Execution Boundary

> **Reviewer Verdict**：R4-B2.1 复审 **REOPENED（仅剩 1 个 P0）**——P0-02 full seal consumption / P0-03 transaction-internal preconditions / P0-04 logical-URI confinement / P1-01 manifest check rename / full CI matrix 全部 **VERIFIED / FREEZE**（不得继续重构）。本 amendment 收口唯一剩余 blocker：execution proof 本身仍可由 caller 直接声明。

### F.1 剩余 P0：Execution Proof 仍是 Caller Assertion

Amendment E.2 的 `record_artifact_check_execution` 不执行任何 scan——只校验字符串非空/check_id 合法后直接 INSERT。攻击路径（Reviewer §2）：caller 读 registry → 调公开 `compute_component_manifest_hash` 得 current hash → 对两个 check 各写一行（contract/producer 任意非空串）→ 不写任何 finding → validate → 两项 DQ check PASS。这不是 positive execution proof，是 **caller self-declare "I executed the scan"**——与 B1（self-declare APPROVED）/ B2（self-declare 0 counts）同构。mock_e2e 的 happy path 恰好正在使用该声明路径。且 proof 的 scan_contract_version / producer 无 current-contract / checker-identity 校验（"fake-v0" + "attacker" 也能通过）。

### F.2 收口：Governed Scan Execution Boundary（Reviewer §5 推荐结构）

新模块 `pipeline/artifact_dq_scan.py`：

```text
run_required_artifact_dq_scan(conn, *, data_root, feature_artifact_set_id)
  -> static registry lookup（ARTIFACT_DQ_CHECKERS，production-owned）
  -> resolve CURRENT components + compute manifest INTERNALLY
  -> for each check: execute the production-owned evaluator
       over authoritative input
  -> persist every detected finding（append-only，dedup by detail）
  -> INSERT execution-completion proof LAST
  -> 单事务 COMMIT（evaluator raise -> ROLLBACK -> 零 completion row）
```

- **签名只有 (conn, data_root, feature_artifact_set_id)**——无 scanned hash / contract / producer / result / count / completed_at 参数（AST 守卫断言）。
- **唯一 INSERT 边界**：production 中 `INSERT INTO meta_artifact_check_execution` 只出现在该函数（AST 守卫）；旧 `record_artifact_check_execution` 从生产命名空间删除。
- **system-derived identity**：completion row 的 scan_contract_version = CURRENT `DQ_SCAN_CONTRACT_VERSION`（"dq-scan-b2.2-v1"）；producer = `artifact-dq-scanner/{check_id}@{checker_version}`（registry 派生的 checker 身份）。
- **validator 三重校验**（artifact_validation.py）：proof 缺失 → NOT_TESTABLE；contract != CURRENT → NOT_TESTABLE（rescan required）；producer != system-derived checker identity → NOT_TESTABLE；manifest != current → NOT_TESTABLE（沿 E.2）。

### F.3 Authoritative Inputs（audit §4.5——每个 check 实际读什么）

- **IDENTITY_FALLBACK evaluator**：artifact set 的 feature component parquet `security_id` 列（distinct）× `dim_security.identity_key_version`。注册为 `SECURITY_IDENTITY_V1_FALLBACK` 的身份是 finding；**未注册的身份也是 finding**（不可证即 fail closed）。mock_e2e 补充 dim_security 注册（master 带 list_date → 全部正式版身份）。
- **BLOCKING_DQ evaluator**：snapshot 绑定的五个 canonical fact 表（fact_daily_bar / fact_security_status_daily / fact_limit_price / fact_adj_factor / fact_corporate_action）的 `quality_flags` 列；blocking flag 集合 = V1.3.2 QualityFlag 集减 IDENTITY_FALLBACK（STALE_WINDOW / BENCHMARK_UNAVAILABLE / INVALID_LIMIT_RANGE / NO_LIMIT_RULE / LOW_SAMPLE）。零 fact 行的 snapshot 上该扫描真实执行且客观发现零。

真实检测测试：UPDATE dim_security 一个身份为 FALLBACK → scanner 真实发现并 persist finding → validate FAIL；INSERT fact_daily_bar 带 STALE_WINDOW flag → scanner 发现 → FAIL。**无 monkeypatch 伪造的检测语义**。

### F.4 scanner failure 语义

evaluator raise（checker unavailable / 无法读取 input）→ 整个 scan 事务 ROLLBACK → **零 completion row** → validator NOT_TESTABLE → publish BLOCK。严禁 no-op scanner 写"completed"（测试覆盖：monkeypatch evaluator raise → rows == 0）。

### F.5 治理状态

- R4-B2.1 已 VERIFIED 的 seal consumption / transaction preconditions / URI confinement / manifest rename / CI 全部 FREEZE（除真实 regression 不重开）；本 amendment 只动 execution truth；
- validation contract version 升为 `b2-exact-v2`（count_source 语义更新：completion proofs 为 governed scanner 产物，system-derived contract/producer identity）——旧 seal 由 P0-02 的 current-contract recheck 自然失效；
- DM 登记：§61 DM-CR-20260831-061；
- mock_e2e 变更：dim_security 注册（registry 行为，feature parquet bytes 不变）+ scanner 替代声明式 proof。

---

## Amendment 2026-08-31（R4-B2.3，audit 20260831 13:37）——Final DQ Authoritative Input Seal + Scan Transaction Closure

> **Reviewer Verdict**：R4-B2.2 复审 **REOPENED（仅剩 1 个 P0）**——scanner ownership / execution boundary 等 16 项 VERIFIED / FREEZE。本 amendment 收口唯一剩余 blocker：completion proof 未绑定 checker 实际读取的完整 authoritative input。

### G.1 剩余 P0：Component Manifest 不是 Checker 的完整输入

Amendment F 的 completion proof 只 seal `scanned_component_manifest_hash`，但两个真实 checker 的 authoritative input 不只 components：

```text
IDENTITY_FALLBACK：components security_id 集 + dim_security.identity_key_version
BLOCKING_DQ：artifact.data_snapshot_id + 五个 fact 表 quality_flags
```

三条可复现错误路径（audit §2）：(A) scan 后 dim_security 某 security 改为 FALLBACK——components 未变、manifest 匹配、findings 仍 0 → **false PASS**；(B) scan 后同 snapshot fact 表新增 STALE_WINDOW——同上；(C) scan 在 S1 下完成，artifact 重绑 S2 且 components 不变——proof 无字段证明当时扫的是哪个 snapshot。根因：`component manifest unchanged` ≠ `checker authoritative input unchanged`。且 scanner 的 artifact/components 读取发生在 `BEGIN TRANSACTION` **之前**（顺序缺陷，audit §5）。

### G.2 收口：Checker-Specific Authoritative Input Seal

**单一 production-owned spec 封装 input resolution / fingerprint / evaluation（audit §4.3——防两套逻辑漂移）**：`ArtifactDQCheckerSpec` 增加 `resolve_input`（解析该 checker 的 authoritative input state）与 `evaluate`（对同一 state 判定）；`fingerprint(input_state)` = canonical JSON（含 check_id + checker_version + state）→ SHA-256。evaluator 不再自行读输入——它消费 resolve_input 的产物，fingerprint 与 evaluation **天然同源**。

- **IDENTITY_FALLBACK input state（§4.1）**：components 的 distinct security_id 集 + 每个 security 的当前 `dim_security.identity_key_version`（未注册 → 显式 `__MISSING__` 标记）。identity version 变化 / 注册增删 / artifact security 集变化都改变 fingerprint。
- **BLOCKING_DQ input state（§4.2）**：当前 `artifact.data_snapshot_id` + 每个 fact 表按 `(table_name, quality_flags, row_count)` 的稳定聚合（NULL/empty 按 evaluator 规则规范化）——只 seal 影响 evaluator 结果的输入，不做无关列全表 hash。

**completion proof 新增两列（migration 013）**：`authoritative_input_hash`（checker-specific input seal）+ `scanned_data_snapshot_id`（显式审计字段）。`DQ_SCAN_CONTRACT_VERSION` → `dq-scan-b2.3-v1`；`VALIDATION_CONTRACT_VERSION` → `b2-exact-v3`（report 新增 `dq_execution_seals` 绑定）。

### G.3 三层 seal 消费链（audit §3——不能只在 validator 比一次）

```text
scanner proof input seal
  -> validation report seal（report.dq_execution_seals：execution_id /
     contract / producer / authoritative_input_hash / component
     manifest / scanned snapshot）
  -> publish transaction current-input recheck（_b2_recheck 重算 CURRENT
     fingerprints 并与 report seals 比对——validation 后 input 变化 ->
     ARTIFACT_DQ_INPUT_STALE BLOCK）
```

validator（artifact_validation）：proof 缺失 / contract != CURRENT / producer != system-derived / manifest != current / **input seal 缺失（legacy）或 != current** → NOT_TESTABLE。publish recheck（publish.py）：report 的 dq_execution_seals 集合必须完整非空；`current_authoritative_input_fingerprints` 重算当前值（不可解析 → DQ_INPUT_UNRESOLVABLE BLOCK）逐一比对。物理 bytes 终验先行（missing/tampered 组件报具体错误），DQ seal 检查在其后。

### G.4 Scan Transaction Closure（audit §5）

`run_required_artifact_dq_scan` 重排：**BEGIN TRANSACTION FIRST**——artifact snapshot / components 的 authoritative reads 全部移入事务内（`_resolve_scan_context` helper）；fingerprint 在事务内对 CURRENT 输入计算；evaluator → findings persist → completion proof LAST → COMMIT。AST ordering 守卫（测试）：函数体内首个 conn.execute 即 BEGIN，且 BEGIN 先于 `_resolve_scan_context` 调用。

### G.5 治理状态

- R4-B2.2 的 16 项 VERIFIED / FREEZE（scanner API shape / static registry / evaluator semantics / 真实检测 / failure 回滚等）全部保留；本 amendment 只增加 input seal 与事务闭合；
- checker_version 升 v2（input resolution 共享封装是 evaluator 语义必要的重构——audit §8 允许"fingerprint 共用解析所必需"）；
- migration 013：两列 ALTER（from-zero 13 链 + idempotent + tamper 守卫全过；未改旧文件）；
- DM 登记：§61 DM-CR-20260831-062。
