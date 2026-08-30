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
