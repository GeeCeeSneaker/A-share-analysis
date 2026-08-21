# 对《Phase 0 启动：项目骨架（P0-M0）+ AmazingData Provider Spike》的设计评审与裁决

> 评审角色：V1.3.2 Frozen Baseline 设计侧  
> 评审日期：2026-08-21  
> 评审对象：开发人员提交的 Phase 0 启动方案  
> 总体判定：**GO WITH CHANGES（允许启动，但需先落实本文 P0/P1 裁决）**

---

## 0. 结论先行

开发人员的总体方向是正确的，尤其是以下几点应予肯定并继续执行：

1. **P0-M0 工程骨架与 P0-M-1 AmazingData Spike 并行推进**可以接受；
2. AmazingData SDK 与核心工程隔离、CI 不安装真实 Provider SDK 的方向正确；
3. Spike 与正式生产数据路径隔离，`data/spike/` 不进入 Canonical，是正确的爆炸半径控制；
4. 确定性 UUIDv5 Security ID、不可变 Parquet、Snapshot/Manifest、单 Writer、Secret 脱敏等均符合 Frozen Baseline；
5. 在 Tushare 当前不可用的情况下，先扩大 AmazingData Spike 去验证原 Tushare 职责的可替代性，是合理的现实处理；
6. **但不能把“当前只有 AmazingData 可用”静默解释成“V1.3.2 已经改为 AmazingData 单源方案”**。Frozen Baseline 没有变化。

本轮我给开发侧的正式执行结论是：

```text
P0-M0                         GO
P0-M-1 AmazingData Spike      GO
P0a                           必须等待 Spike 对核心事实给出 GO
P0b                           Tushare 缺失时允许 BLOCKED，不允许伪装完成
Phase 0 完整 DoD              仍按 V1.3.2 Frozen Baseline
```

也就是说，可以立即开始仓库、迁移、Mock、Identity、CI、Spike 脚本开发；但 **P0a 的真实 Canonical/Publish 不能在 AmazingData 核心能力尚未通过 Spike 时正式推进，P0b 更不能因为 Tushare 暂不可用而自动降低验收标准。**

---

# 1. 对当前 TODO 的逐项裁决

| TODO | 裁决 | 说明 |
|---|---|---|
| `init-repo-foundation` | **GO** | 按计划实施 |
| `build-storage-base` | **GO WITH CHANGES** | DuckDB 跨进程模型、Migration 表集、Manifest URI/Hash 规则需按本文修正 |
| `impl-identity-provider` | **GO WITH CHANGES** | UUIDv5正确，但 fallback 与发布后冻结规则必须补齐 |
| `build-cli-tests` | **GO** | 但“CI”不能只等于本地 `quality_gate.ps1` |
| `run-amazingdata-spike` | **GO WITH CHANGES** | 需要按“等价/可推导/不同语义/缺失”四类输出，不得只给“能/不能” |
| `spike-report-adr` | **GO** | ADR-007 可记录单源/降级风险；另建议增加 ADR-008 记录 DuckDB 进程访问模型 |

---

# 2. P0：在对应代码落地前必须修正的问题

## P0-1 DuckDB 跨进程并发方案需要立即改

开发方案当前写的是：

```text
写进程独占；
读侧 read-only 连接 + 退避重试。
```

这里容易产生一个错误预期：**认为一个进程长期以 read-write 打开 `atlas.duckdb` 时，其他进程可以稳定地同时以 read-only 打开同一个数据库文件。**

不应这样设计。

DuckDB 当前官方并发模型的核心是：

```text
模式 A：一个进程以 read-write 打开，可在该进程内部并发读写；
模式 B：多个进程以 read-only 打开，但此时不能同时存在写进程。
```

因此 Phase 0 最简单、安全的实现裁决是：

### Phase 0 采用“数据库文件进程级独占所有权”

```text
atlas.duckdb

任一时刻：
    要么由一个 Pipeline/CLI 进程持有
    要么由一个研究/查询进程持有
    不承诺跨进程读写并存
```

`DuckDBConnectionManager` 建议改成：

```python
class DuckDBConnectionManager:
    def owner(self, mode: Literal["read_write", "read_only"]):
        ...
```

或者保留 `writer()/reader()` 名称，但二者**跨进程使用同一个外部排他 Gate**。

Phase 0 不需要为“多个进程边写边读”设计复杂读写锁。

### 允许的并发

同一 Owner 进程内部可以建立多个连接/线程，遵循 DuckDB 单进程并发规则。

### 不允许的假设

```text
Pipeline Worker 长期开着 read-write DuckDB
+
FastAPI/Notebook 另一个进程持续 read-only DuckDB
```

不要把这个作为保证。

### Phase 1 若需要 API 在 EOD 写入期间零中断读取

到时单独触发 ADR，再从以下方案选择：

```text
A. 单一 DuckDB Owner 服务进程，同时承载读写请求
B. 读服务使用发布快照/只读副本
C. 元数据迁移到服务型数据库
D. 届时成熟的 DuckDB client-server / lakehouse 路径
```

不要现在提前工程化。

### 必须增加的测试

1. 两个写进程竞争：第二个明确失败；
2. 写进程持有时，另一个进程不得被测试成“应该可以正常 read-only 读取”；
3. DB Owner 异常退出后锁可恢复；
4. 不因锁残留导致永久不可启动。

**这是本次评审唯一要求在 `storage/connection.py` 编码前先修改的架构性问题。**

---

## P0-2 P0-M0 的数据库最小表集缺了 Feature Artifact 骨架

开发方案目前的 `003_snapshot_publish.sql` 只列：

```text
meta_data_snapshot(+component)
meta_pipeline_run
meta_publish_snapshot(+universe)
```

但 Frozen Baseline 的 `meta_publish_snapshot` 已经正式绑定：

```text
data_snapshot_id
feature_artifact_set_id
feature_set_version
```

因此如果 M0 只建 Data Snapshot 和 Publish，不建 Feature Artifact，Publish Skeleton 本身是不闭合的。

### 裁决

M0 至少补入：

```text
meta_feature_artifact_set
meta_feature_artifact_component
```

建议迁移拆成：

```text
001_identity_calendar.sql
    meta_schema_version
    dim_security
    bridge_security_provider_symbol
    dim_trade_calendar
    dim_trading_rule

002_provider_governance.sql
    meta_data_source
    meta_provider_capability
    meta_provider_field_map
    meta_source_policy          # 先有Schema，逻辑P0b再完整启用
    meta_tolerance_rule
    meta_ingest_run

003_run_snapshot_publish.sql
    dim_universe               # 至少支持 ALL_A 的骨架
    meta_pipeline_run
    meta_data_snapshot
    meta_data_snapshot_component
    meta_feature_artifact_set
    meta_feature_artifact_component
    meta_publish_snapshot
    meta_publish_universe
```

如果某些完整字段暂时不使用，可以保持空表，但不要建立一个从结构上无法表达 Frozen Published Contract 的 M0 数据库。

---

## P0-3 `feature_set_version` 不能继续只是一个没有定义来源的字符串

开发人员指出 Frozen 文档里没有 `meta_feature_set`，这个问题判断是正确的。

目前：

```text
meta_feature_artifact_set.feature_set_version
meta_publish_snapshot.feature_set_version
```

都依赖这个字段，但如果系统不能回答：

> “这个 Feature Set 到底由哪些 Feature Version / Param Set 组成？”

那么它只是一个人工字符串，不足以支撑复现。

### 裁决：补一个轻量 Feature Set Registry

建议：

```text
meta_feature_set
----------------
feature_set_version PK
definition_hash
status
created_at
note

meta_feature_set_member
-----------------------
feature_set_version
feature_id
feature_version
param_set_id
```

唯一键：

```text
(feature_set_version, feature_id, feature_version, param_set_id)
```

`definition_hash` 必须从排序后的成员定义生成，不依赖插入顺序。

### 时点

不要求在最初一小时就实现完整 Feature Registry，但：

> **在 P0a 第一次创建 `feature_artifact_set_id` 前必须完成。**

可以作为 `004_feature_governance.sql`，不必强塞进前三个 migration。

这属于**实现闭环补充**，不是新增业务功能，不违反 Frozen Baseline。

---

## P0-4 Manifest 的 URI 身份不能使用“大小写不敏感比较”

开发方案提出：

> `file_uri` 保留原始大小写，Manifest 匹配做大小写不敏感比较（NTFS 特性）。

**这一条不采纳。**

原因是 Manifest 是跨机器、跨操作系统的可复现身份，不应该继承 Windows 文件系统的大小写语义。

例如：

```text
Feature/Trend/a.parquet
feature/trend/a.parquet
```

在部分 Windows 环境可能指向同一路径，但在 Linux 可以是两个不同对象。

如果 Manifest 在 Windows 下把二者视为相同，会造成跨平台语义不一致。

### 正确规则

`file_uri` 定义为**逻辑 URI**：

```text
相对 data_root
统一 /
UTF-8
使用程序规定的确定大小写
禁止 drive letter
禁止机器绝对路径
```

例如：

```text
canonical/fact_daily_bar/year=2026/month=08/part-0001.parquet
```

Manifest 比较使用：

> **精确字符串比较。**

Windows 物理路径解析可以大小写不敏感，但那属于 `paths.py` 的 OS 适配，不能影响 Manifest 身份。

同时加入 DQ：

```text
如果发现两个逻辑 URI 仅大小写不同 → BLOCK
```

---

## P0-5 Manifest Hash 不能被 run_id / 机器路径污染

开发方案已经提出“不含机器绝对路径”，方向正确，但还要再明确一步。

Raw/Staging 路径中经常存在：

```text
run_id=...
```

如果 `data_manifest_hash` 直接 hash `file_uri`，那么同一份内容在两次干净重建时会因为不同 run_id 产生不同 Manifest Hash。

### 裁决

Manifest 的**身份 Hash**建议由以下逻辑字段排序后生成：

```text
dataset
logical_partition_key
content_hash
schema_hash
row_count
provider/source_revision（若属于该Snapshot语义）
```

不要把以下字段作为复现 Hash 的核心输入：

```text
机器绝对路径
临时 staging 路径
随机 run_id
created_at
ingested_at
```

`file_uri` 可以保存在 Component 中作为 Locator，但不必成为跨环境 Manifest Hash 的身份来源。

### 必测

把同一组文件分别放在：

```text
D:\research\data
E:\temp\another_root
```

重新登记 Snapshot，逻辑 Manifest Hash 应一致。

---

# 3. 关于 Tushare 当前不可用：允许继续，但不能修改语义

开发方案目前最大的现实变化是：

```text
AmazingData 可用
Tushare 积分不足
```

我同意先推进 AmazingData Spike，并把原 Tushare 职责加入验证清单。

但是必须把“替代”拆成四种结果，而不是简单回答“有/没有这个字段”。

## 3.1 Spike 对每项能力必须给出四级结论

```text
A. EXACT_EQUIVALENT
   字段经济/交易含义与 Canonical 需求一致，可直接替代

B. DERIVABLE_EQUIVALENT
   可由供应商基础事实按确定公式重建，且语义等价

C. ALTERNATIVE_SEMANTICS
   有类似数据，但定义不同，只能作为新的独立数据域

D. MISSING
   无法满足
```

---

## 3.2 `free_share / turnover_rate_f` 不允许“看起来像”就替代

这是 Spike 中最需要小心的一项。

AmazingData 文档中的：

```text
FLOAT_SHARE
FLOAT_A_SHARE
```

不能因为名字像“流通股”就自动视为 Tushare：

```text
free_share
```

只有确认其分母语义就是系统要求的“自由流通股本”时，才能标记：

```text
EXACT_EQUIVALENT
```

否则即使可以计算：

```text
volume / FLOAT_A_SHARE
```

得到的也只是另一种换手率。

### 裁决

```text
语义完全一致 → 可成为新的 Source Policy Candidate
语义不同     → 保留为独立字段，不改 PV_TURNOVER_F 定义
```

**禁止为了摆脱 Tushare 依赖而偷偷修改 Feature 的数学语义。**

---

## 3.3 银河行业 taxonomy 不能自动替代申万

AmazingData 有 L1/L2/L3 行业、历史成分和日权重，这非常有价值。

但在没有验证 taxonomy 标准之前：

```text
GALAXY industry ≠ SW industry
```

### 裁决

如果 Spike 发现银河是自有行业体系：

```text
taxonomy_id = GALAXY_xxx
```

独立保存。

不能把它映射成：

```text
SW2021
```

也不能用它来宣称 V1.3.2 的：

```text
SW L1 Phase 0 DoD
```

已经完成。

如果 Tushare 暂不可用，允许：

```text
P0a 完成
P0b / SW相关M2 暂时 BLOCKED
```

而不是修改验收标准。

---

## 3.4 单源自洽检查不是 Reconciliation

开发方案写：

> Reconciliation 双源对账暂缓为单源自洽校验。

作为临时开发安排可以，但术语必须严格。

不要输出：

```text
reconciliation_status = PASS
```

建议使用：

```text
NOT_RUN_NO_SECONDARY
```

或类似明确状态。

单源可以做：

```text
schema check
unit check
OHLC invariants
corporate-action continuity
coverage
manual Golden
exchange evidence check
```

但这不叫“双源 Reconciliation”。

Reconciliation 框架可以用 Mock Provider 在 CI 中测试逻辑，真实 Provider Reconciliation 等第二源可用后再启用。

---

## 3.5 AmazingData No-Go 且 Tushare 不可用时：必须停止，不自动切 AKShare

开发人员已经正确识别：

> 当前 No-Go fallback 实际不可执行。

正式裁决：

```text
若 AmazingData 在 Daily/Status/Limit/Identity 核心事实上 No-Go
且 Tushare FUSED fallback 不可用
→ P0a BLOCKED
```

此时可选动作：

1. 补足 Tushare 权限；
2. 对新的候选 Provider 单独做 Spike；
3. 形成新 ADR 后再批准进入 Source Policy。

**AKShare 不因为“免费能拿到”就自动成为生产 fallback。**

---

# 4. Provider Spike 的 Go/No-Go 应改成三级，而不是二元

为了适配当前 Tushare 不可用的现实，我建议 Spike 报告输出：

## `GO_CORE`

AmazingData 的以下核心事实全部通过：

```text
Security Master
Daily Bar
Historical ST/Suspend
Limit Price
Adj Factor/Corporate Action continuity
Trade Calendar
```

允许进入 P0a。

---

## `GO_DEGRADED`

核心事实足够支撑 P0a，但：

```text
free_share/turnover_rate_f
SW taxonomy
cross-source reconciliation
```

仍缺失。

结论：

```text
P0a GO
P0b / 部分 P0-M2 BLOCKED
```

这很可能是当前最现实的结果。

---

## `NO_GO`

AmazingData 在核心状态/行情/PIT 事实上无法满足 Frozen 要求。

结论：

```text
P0a BLOCKED
```

---

# 5. Canonical-selected DDL 缺口的裁决

开发人员提出 Canonical selected 层 DDL 尚未落到实现细节，这个缺口存在，但**不阻塞 P0-M0**。

### 裁决

M0 只完成：

```text
Schema骨架
Provider DTO
Provider-normalized约束
Snapshot/Source Policy元数据
```

P0a 开始前再完成具体：

```text
fact_daily_bar
fact_limit_price
fact_security_status_daily
fact_adj_factor
```

等 Canonical DDL/Writer。

### 不要做一个通用 EAV “selected facts”表

Canonical 应按业务事实域建表/Parquet Dataset。

每条正式 selected 事实必须能追溯：

```text
selected_provider
source_policy_version
source_revision
selection_reason
reconciliation_status
quality_flags
```

P0a 单源情况下：

```text
reconciliation_status = NOT_RUN_NO_SECONDARY
```

而不是伪造 PASS。

---

# 6. Security ID 实现的补充裁决

开发方向：

```text
UUIDv5(
    PROJECT_SECURITY_NAMESPACE,
    exchange + asset_type + initial_symbol + first_list_date
)
```

正确。

但还要补四条。

## 6.1 `PROJECT_SECURITY_NAMESPACE` 必须是代码中的固定字面 UUID

禁止：

```python
uuid4()
```

禁止首次启动自动生成后写配置。

一经 ADR-002 固定，永久不变。

---

## 6.2 `initial_symbol` 必须是内部标准化交易所代码

例如：

```text
000001
600000
```

而不是：

```text
000001.SZ
SZ000001
provider-specific-code
```

Provider Symbol 只进入映射表。

---

## 6.3 Phase 0 A股缺失 `first_list_date` 时不得正式 Publish

Frozen 方案允许 fallback 的目的是处理异常身份发现，而不是让正常 A 股数据长期带着不稳定身份发布。

建议：

```text
缺 first_list_date
→ Spike/STAGING 可以生成 temporary identity + IDENTITY_FALLBACK flag
→ PUBLISHED Core A-share 必须 BLOCK
```

如果未来确有特殊资产需要 fallback，再单独定义。

---

## 6.4 首次正式 Published 后 identity 冻结

供应商后来修正 `list_date`：

```text
不 re-key
不改变 security_id
写 identity_errata
```

这一规则需要进入测试。

---

# 7. Windows 文件提交方案：方向正确，但需要明确 crash recovery

`同卷 + os.replace + fsync + 指针最后切换` 的总体方向接受。

建议固定顺序：

```text
1. 写 temp
2. flush
3. fsync(temp file)
4. close
5. SHA-256验证
6. os.replace(temp, final)     # 同卷
7. 登记 Component
8. 最后一次 DuckDB transaction 切 Publish Pointer
```

不要把 Python/Windows 的目录级 durability 描述成强保证。

系统真正的恢复保证来自：

```text
不可变文件
+ content hash
+ 元数据指针最后切换
+ 启动恢复检查
```

### 必须增加 Failure Injection

模拟：

```text
A. 文件已移动，DB尚未登记
   → orphan file 不可见，可后续清理

B. Snapshot登记完成，尚未Publish
   → latest仍是上一版本

C. Feature Artifact完成，Publish事务前崩溃
   → Artifact不可被latest读到

D. Publish事务失败
   → 旧PUBLISHED仍保持
```

---

# 8. Migration Runner 不只是“幂等跳过”

开发方案写“已应用版本重跑跳过”，还需要加：

```text
migration checksum
```

### 规则

每个 migration：

```text
migration_id
filename
content_hash
applied_at
```

一旦应用：

> **禁止修改原 SQL 文件内容。**

如果发现：

```text
migration_id 相同
但 content_hash 不同
```

启动直接 BLOCK。

每个 migration 在事务中执行；失败完整 ROLLBACK。

这样才能避免“开发人员修改 001.sql，但数据库还认为 001 已执行”的常见漂移问题。

---

# 9. AmazingData SDK optional dependency：方向接受，但先确认实际分发方式

开发方案把 AmazingData 放 optional group，CI 不安装，这个方向正确。

但 Spike 必须记录：

```text
SDK package/version
安装方式
wheel/installer hash（若可得）
Python版本要求
Windows依赖
登录方式
```

如果 AmazingData SDK 是券商提供的本地 wheel/安装包，而不是稳定私有/公开包源：

> **不要把机器绝对路径写进 `uv.lock`。**

可以采用：

```text
Core environment:
    uv.lock

Provider proprietary SDK:
    docs/provider_verification/amazingdata.md
    + SDK version/build/hash
    + 本机受控安装
```

Adapter 采用 lazy import：

```python
try:
    import AmazingData
except ImportError:
    raise ProviderUnavailableError(...)
```

核心包、Mock、CI 不能因 SDK 缺失 import 失败。

---

# 10. CI：`quality_gate.ps1` 不等于 CI

本地脚本应保留，但 M0 出口要求“CI”时，建议至少有一个真实自动 runner。

例如：

```text
.github/workflows/ci.yml
```

或者团队现有 CI 系统等价物。

最低执行：

```text
uv sync（不含 AmazingData）
ruff
format check
mypy
pytest
migration from zero
security fixture rebuild
secret leak test
```

建议 core tests 做：

```text
Windows runner：必须
Linux runner：推荐
```

因为项目声称 Windows/Linux 可用，而路径、大小写、时区正是最容易跨平台漂移的地方。

---

# 11. Spike 样本结果必须是可审计证据，不只是脚本 stdout

建议 `scripts/spike/` 最终形成：

```text
data/spike/
    raw/                    # gitignore，真实供应商响应
    normalized/
    results/

docs/provider_verification/amazingdata.md
docs/spike_report_p0m1.md
```

另增加：

```text
spike_case_catalog
```

字段至少：

```text
case_id
case_type
security/provider_symbol
trade_date
expected_value
actual_value
evidence_type
evidence_ref
result
reason_code
checked_at
```

### “差异可解释”的定义

不能写：

> “供应商就是这么给的，所以解释通过。”

至少要归因到明确类别，例如：

```text
CORPORATE_ACTION
PRICE_TICK_ROUNDING
AFTER_HOURS_INCLUDED
SESSION_BOUNDARY
SYMBOL_MAPPING
SOURCE_REVISION
PROVIDER_TIMING
DOCUMENTED_UNIT_DIFFERENCE
```

无法解释即 FAIL。

---

# 12. `available_at` 的 Spike 结论不要过度承诺

历史数据回补无法从一次查询恢复当年的真实发布时刻。

因此继续严格区分：

```text
OBSERVED
CONSERVATIVE_ASSUMED
```

### Spike 可以验证

- 当前真实账户在若干交易日的首次可见时间；
- `is_local=True/False` 对 freshness 的影响；
- Provider 返回数据的最大 trade_date；
- EOD 最终值何时稳定。

### Spike 不能证明

> “2018 年每天都是今天观察到的这个更新时间。”

因此历史 PIT 仍使用版本化 Conservative Availability Policy。

建议至少连续记录多个真实交易日的可见时间；样本不足时在 Provider Verification 标记为：

```text
PROVISIONAL
```

不需要因此阻塞整个工程骨架。

---

# 13. 对开发人员提到的主要“待裁决问题”的正式答复

## Q1. P0-M0 与 P0-M-1 能否并行？

**可以。**

条件：

```text
M0不得把尚未验证的AmazingData字段语义写死进Canonical业务逻辑；
P0a真实数据链必须等核心Spike GO。
```

---

## Q2. Tushare 当前不可用，能否扩大 AmazingData Spike？

**可以，而且应该。**

但这只是能力验证，不代表 Frozen Baseline 自动改单源。

---

## Q3. AmazingData 如果有股本数据，能否替代 `free_share/turnover_rate_f`？

**只有语义等价验证通过才能替代。**

`FLOAT_A_SHARE` 等字段不得默认等于自由流通股本。

---

## Q4. AmazingData 的行业 L1/L2/L3 能否代替申万？

**不能默认代替。**

若不是申万体系，则注册为独立 Galaxy taxonomy。

---

## Q5. 没有第二源时能否把单源自洽写成 Reconciliation PASS？

**不能。**

使用 `NOT_RUN_NO_SECONDARY` 等明确状态。

---

## Q6. AmazingData No-Go 且 Tushare 不可用怎么办？

**P0a BLOCKED。**

不能自动用 AKShare 顶上；新 Provider 必须单独 Spike + Source Policy 审批。

---

## Q7. `meta_feature_set` 要不要补？

**要。**

在第一次生成 Feature Artifact 前补 `meta_feature_set + member`，否则 `feature_set_version` 不可审计。

---

## Q8. Canonical-selected DDL 是否必须在 M0 完成？

**不必。**

但 P0a 开始前必须完成 Daily/Status/Limit/Adj 等实际 Canonical Contract。不要做通用 EAV。

---

## Q9. DuckDB 能否一个写进程 + 其他 read-only 进程同时工作？

**Phase 0 不按这个假设设计。**

采用进程级 DB Owner/排他访问；Phase 1 若需要持续在线读写再做 ADR。

---

## Q10. `file_uri` 是否应按 NTFS 做大小写不敏感比较？

**不应。**

Manifest URI 使用跨平台精确逻辑字符串；OS 路径解析另做适配。

---

## Q11. M0 只建当前列出的 001–003 表是否足够？

**不完全够。**

至少补 Feature Artifact Skeleton；Feature Set Registry 在 P0a 首次 Feature Artifact 前补齐。Publish 所依赖的 Universe/Artifact 关系必须结构闭合。

---

# 14. 建议修改后的启动顺序

```text
并行轨 A：P0-M0
────────────────────────────────
A1 repo + uv + actual CI
A2 deterministic identity
A3 migration/checksum
A4 DB owner / process lock
A5 snapshot + artifact + publish skeleton
A6 Mock end-to-end contract
A7 failure injection / secret tests


并行轨 B：P0-M-1
────────────────────────────────
B1 AmazingData SDK install/version verification
B2 security master / historical code
B3 daily / status / limit / adj
B4 ST/delist/corp-action Golden
B5 volume/amount/unit/cache/freshness
B6 free-float equivalence assessment
B7 taxonomy/index assessment
B8 Go-Core / Go-Degraded / No-Go
B9 Provider Verification + ADR


同步 Gate
────────────────────────────────
M0 PASS
+
Spike >= GO_DEGRADED（且核心事实必须GO）
        ↓
进入 P0a
```

---

# 15. P0-M0 建议出口标准（修订版）

在现有出口标准上增加：

- [ ] DuckDB 不依赖“跨进程写者+read-only读者可同时存在”的假设；
- [ ] Migration 文件有 checksum，已执行 migration 被修改时 BLOCK；
- [ ] Snapshot Manifest Hash 与机器绝对路径、随机 run_id 无关；
- [ ] Windows/Linux 对同一逻辑 component 集合生成相同 Manifest Hash；
- [ ] `file_uri` 精确比较，case collision 自动 BLOCK；
- [ ] `meta_feature_artifact_set/component` Schema 已存在；
- [ ] `feature_set_version` 在首次 Feature Artifact 前有可解析 Registry；
- [ ] Security ID 缺 list_date 不允许正式 PUBLISHED；
- [ ] 模拟“文件落盘后崩溃 / Snapshot后崩溃 / Publish事务失败”的恢复测试通过；
- [ ] 真实 CI 不安装 AmazingData SDK，Mock 全测试通过。

---

# 16. P0-M-1 建议出口标准（结合当前单源现实）

## 核心 GO 条件

以下必须全部通过：

- [ ] Security Master / 历史代码含退市；
- [ ] Daily OHLCV/amount 单位明确；
- [ ] ST/停牌历史样本正确；
- [ ] up/down limit 与无涨跌幅限制日正确；
- [ ] Adj Factor / Corporate Action 连续性通过；
- [ ] 2018 + Warmup 所需历史起点满足；
- [ ] Symbol Mapping 无关键歧义；
- [ ] Provider SDK/权限/缓存/freshness 行为已记录。

## 可允许暂时缺失、但会 BLOCK P0b/M2 的项目

- [ ] `free_share/turnover_rate_f` 语义等价；
- [ ] SW taxonomy；
- [ ] 真实双源 Reconciliation。

因此 Spike 报告不得只写：

```text
GO / NO-GO
```

而应至少给：

```text
GO_CORE
GO_DEGRADED
NO_GO
```

并明确：

```text
P0a status
P0b status
P0-M2 status
```

---

# 17. 最终给开发人员的执行指令

### 允许立即开始

```text
仓库初始化
uv/lock
Mock Provider
UUIDv5
Migration Runner
Snapshot/Artifact/Publish Schema
Secret/Logging
CI
AmazingData Spike scripts
```

### 编码前必须先改设计

```text
DuckDB connection.py 的跨进程并发假设
Manifest file_uri 大小写规则
Manifest Hash 的随机路径污染
003 migration 缺 Feature Artifact Schema
```

### P0a 开始前必须完成

```text
AmazingData 核心事实 Spike GO
meta_feature_set 定义
Canonical Daily/Status/Limit/Adj Contract
单源 reconciliation_status 语义
```

### 不允许因为 Tushare 暂不可用而做

```text
把 Galaxy 行业冒充 SW
把 FLOAT_A_SHARE 冒充 free_share
把单源自洽冒充 Reconciliation PASS
降低 Phase 0 Frozen DoD
把 AKShare 自动升级为生产 fallback
修改 CORE Feature 数学定义
```

---

# 18. 总体评价

这份开发启动方案**可以作为实际施工起点**，而且开发人员对 Frozen Baseline 的理解总体是准确的：他们没有急于开始 Feature 开发，而是先处理工程骨架、Provider Spike、身份、迁移、Mock、CI 和数据源风险，这个顺序正确。

目前最需要纠正的不是业务模型，而是三个工程边界：

1. **DuckDB 的进程级并发语义不能想当然；**
2. **Snapshot / Artifact / Publish Schema 必须在 M0 就保持结构闭环；**
3. **当前只有 AmazingData 可用时，必须把“能力验证”与“语义替代”严格分开。**

按本文裁决调整后，我同意：

> **P0-M0 与 P0-M-1 立即并行开工。**

后续下一次需要设计侧正式 Review 的节点不是“代码写了一半”，而是：

```text
1. M0 Exit Report
2. AmazingData Spike Report
```

两份同时提交。

只要 M0 出口通过、AmazingData 对核心事实达到 `GO_CORE`（即便 free-float/SW 仍为 `GO_DEGRADED`），即可批准进入 **P0a 最小纵贯线**；P0b 与 SW/自由流通相关能力则保持显式 BLOCKED，直到满足 Frozen Baseline，而不是通过修改口径绕过去。

---

## 附：本轮设计裁决优先级

| 优先级 | 项目 |
|---|---|
| **P0** | 修正 DuckDB 跨进程访问模型 |
| **P0** | M0 补齐 Feature Artifact Schema |
| **P0** | Manifest URI/Hash 跨环境确定性 |
| **P0** | AmazingData 核心事实 Spike Gate |
| **P1** | 增加 `meta_feature_set + member` |
| **P1** | Security ID fallback/发布冻结 |
| **P1** | Migration checksum |
| **P1** | Canonical-selected DDL 在 P0a 前落地 |
| **P1** | Spike GO_CORE/GO_DEGRADED 分级 |
| **P1** | 真实 CI workflow |
| **P2** | Phase 1 API 零中断读写方案 |
| **P2** | 其他新 Provider / 自动 GC / Table Format |

**设计侧结论：GO WITH CHANGES。**
