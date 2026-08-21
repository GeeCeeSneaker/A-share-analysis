# 下一阶段开发任务书（P0-M0 收口 → P0-M-1B → P0a）

> 项目：A股市场态势数据基座（日频模块）  
> 基线：V1.3.2 Frozen Baseline  
> 当前阶段：P0-M0 工程骨架收口 + P0-M-1 Provider Spike 继续推进  
> 依据：`work_report_20260821.md` 及既有设计裁决  
> 日期：2026-08-21  
> 文档性质：**开发执行要求，不修改 Frozen Baseline**

---

# 0. 当前状态判定

根据第一阶段工作报告，当前状态正式定义为：

```text
P0-M0 Engineering Foundation
    PASS_PENDING_CI

P0-M-1A Trial Connectivity / SDK Smoke
    PARTIAL PASS
    - SDK / 网络 / 登录 / 代码表链路已打通
    - Historical / Status / Limit / Adj 等因仿真权限未验证
    - L1 实时订阅需按 SubscribeData 路径重新确认

P0-M-1B Production Capability Spike
    WAITING_FOR_PRODUCTION_ACCOUNT

P0a AmazingData 最小纵贯线
    BLOCKED_BY_P0-M-1B_CORE_GATE

P0b Tushare Essential / SW / Reconciliation
    BLOCKED / PARTIAL
```

当前可以继续大量工程工作，但不得把尚未实测的 AmazingData 能力标记为 `APPROVED`，也不得因为 Tushare 暂不可用而修改 Frozen Baseline 的数学/业务口径。

---

# 1. 第一优先级：立即收口的 4 个问题

## 1.1 M0 状态从 `PASS` 暂改为 `PASS_PENDING_CI`

工作报告显示：

```text
M0 其余出口标准通过
但 GitHub CI 尚未首次运行
```

因此：

```text
M0 = PASS_PENDING_CI
```

GitHub/实际 CI 首跑通过后再改为：

```text
M0 = PASS
```

### CI 最低要求

必须至少执行：

```text
Windows + Python 3.14    REQUIRED
Windows + Python 3.12    COMPATIBILITY（建议）
Linux   + Python 3.14    RECOMMENDED
```

执行：

```text
uv sync
ruff check
ruff format --check
mypy
pytest
migration from zero
security-id deterministic rebuild
manifest deterministic rebuild
secret leak check
```

---

## 1.2 重新测试仿真账号的真正 L1 实时订阅

当前报告中的：

```text
Level-1 快照 = DENIED
query_snapshot 2~4 分钟后失败
```

不能直接推出：

```text
仿真账号没有 L1 实时快照权限
```

因为：

```text
query_snapshot
```

属于历史快照查询，而仿真账号描述的权限是：

```text
Level-1 股票实时快照
```

### 必须重新测试

在交易时段直接使用：

```python
SubscribeData.register(
    code_list=...,
    period=Period.snapshot.value
)
```

并运行：

```text
1只股票
→ 5只
→ 20只
→ 100只以内
```

### 测试结果必须分开记录

```text
REALTIME_L1_SUBSCRIPTION
HISTORICAL_SNAPSHOT_QUERY
```

不得合并成一个 “snapshot capability”。

建议状态：

```text
PASS
FAIL
NOT_TESTABLE_PERMISSION
```

---

## 1.3 修正 `get_history_stock_status` 的 Canonical Mapping 表述

当前工作报告写：

```text
HIGH_LIMITED / LOW_LIMITED / IS_ST_SEC / IS_SUSP_SEC /
IS_WD_SEC / IS_XR_SEC
与 fact_security_status_daily 一一对应
```

这不符合 Frozen Baseline。

### 正确拆分

```text
get_history_stock_status
        │
        ├─ IS_ST_SEC
        │  IS_SUSP_SEC
        │      ↓
        │  Security Status Domain
        │
        ├─ HIGH_LIMITED
        │  LOW_LIMITED
        │      ↓
        │  Limit Price Domain
        │
        └─ IS_WD_SEC
           IS_XR_SEC
               ↓
           Corporate Action Domain
```

### 事实所有权

```text
fact_security_status_daily
    is_listed
    is_st
    is_suspended
    ...

fact_limit_price
    pre_close
    up_limit
    down_limit
    has_price_limit
    ...

fact_corporate_action
    ex_dividend
    ex_rights
    ...
```

Provider DTO 可以保留原接口全部字段，但 Canonicalizer 必须按事实域路由。

---

## 1.4 统一 Python / TGW Runtime 参考环境

当前工作报告显示：

```text
AmazingData == 1.1.9 (cp314)
tgw == 1.0.9.2
实际运行 Python == 3.14
CI == 3.12
```

因此从现在起：

```text
Reference Production Python = Python 3.14
```

CI 至少必须有：

```text
Windows Python 3.14
```

不能长期保持：

```text
生产/Provider Runtime = 3.14
CI only = 3.12
```

---

# 2. Provider Doctor 增加 Runtime Identity 验证

当前同时观察到：

```text
C++ TGW Runtime 1.0.8
Python package tgw 1.0.9.2
AmazingData 1.1.9
```

需要确认 Python 运行时实际加载的 TGW DLL 版本和路径。

## 2.1 Provider Doctor 新增输出

```text
PYTHON_VERSION
AMAZINGDATA_PACKAGE_VERSION
PYTHON_TGW_PACKAGE_VERSION

TGW_RUNTIME_REPORTED_VERSION
TGW_LOADED_DLL_PATH
TGW_LOADED_DLL_VERSION

SDK_ABI
NETWORK_REACHABLE
AUTHENTICATED
QUERY_READY
ACCOUNT_PROFILE
```

如果存在：

```text
Python tgw package = 1.0.9.2
Loaded TGW DLL = 1.0.8
```

必须明确验证兼容性，不能默认无风险。

### 结果状态

```text
RUNTIME_IDENTITY_VERIFIED
RUNTIME_VERSION_MISMATCH
RUNTIME_PATH_AMBIGUOUS
```

---

# 3. 下一批可立即开发任务（不依赖正式账号）

以下工作现在即可启动。

---

## 3.1 AmazingData Production Adapter 骨架

优先级：**P0 / 立即**

目录建议：

```text
src/ashare_state/providers/amazingdata/
├─ provider.py
├─ session.py
├─ sdk_loader.py
├─ dto.py
├─ mapper.py
├─ errors.py
├─ timeout.py
└─ capability.py
```

### Adapter 必须实现

```text
lazy import
login/logout
session lifecycle
SDK stdout/log 隔离
credential masking
统一 error mapping
timeout boundary
capability registry
account_profile_id
runtime identity
```

---

## 3.2 统一 Provider Error Layer

不得让 SDK 原始 `TypeError` 等直接穿透 Provider 边界。

至少定义：

```text
ProviderUnavailableError
ProviderNetworkError
ProviderAuthError
ProviderPermissionError
ProviderTimeoutError
ProviderRateLimitError
ProviderSchemaError
ProviderEmptyResultError
ProviderSdkInternalError
```

### 映射原则

例如：

```text
SDK TypeError
    ↓
结合 endpoint / response / permission context
    ↓
ProviderPermissionError
或
ProviderSdkInternalError
```

如果无法归类：

```text
ProviderSdkInternalError
```

并保存原 exception 作为 internal cause。

---

# 4. Timeout / Cancellation 必须专门测试

当前已发现部分 SDK 调用失败前会等待 2–4 分钟。

## 4.1 必须配置

```text
connect_timeout
query_timeout
max_retries
backoff
jitter
```

## 4.2 不要假设 Python timeout 会终止底层 SDK

必须设计实验：

```text
调用一个明确无权限/长耗时接口
↓
上层 timeout
↓
观察底层线程/SDK请求是否仍存在
↓
观察后续调用是否受影响
```

### 若底层不可取消

记录 ADR 候选：

```text
Provider subprocess isolation
```

但当前阶段只做实验，不直接引入复杂子进程架构。

---

# 5. Raw → Provider-normalized → Canonical Contract 现在就要做实

下一阶段的核心开发目标不是 Feature，而是：

```text
AmazingData SDK
      ↓
Raw Immutable
      ↓
Provider-normalized
      ↓
Canonical-selected
```

---

# 6. Raw Envelope Contract

建议统一字段：

```text
provider
provider_dataset
endpoint

request_id
request_params_hash

requested_at
received_at

sdk_version
runtime_version
account_profile_id

row_count
schema_hash
content_hash

source_revision
raw_file_uri
quality_flags
```

### 特别新增

```text
account_profile_id
```

用于区分：

```text
TRIAL_SIMULATION
PRODUCTION_xxx
```

试用账号和正式账号的能力验证结果不得混在一起。

---

# 7. Provider-normalized DTO

先完成以下 DTO：

```text
DailyBarDTO
SecurityMasterDTO
SecurityStatusDTO
LimitPriceDTO
AdjFactorDTO
CorporateActionDTO
TradeCalendarDTO
EquityStructureDTO
IndustryMemberDTO
IndexDailyDTO
```

### DTO 原则

Provider DTO：

```text
忠实表达 Provider 字段
```

Canonical DTO：

```text
表达系统统一语义
```

不得在 Provider DTO 中提前隐藏/改写供应商字段。

---

# 8. Canonical DDL：现在必须完成 5 个事实域

工作报告建议四个表，设计侧要求增加 Corporate Action。

## 8.1 `fact_daily_bar`

至少：

```text
security_id
trade_date
open
high
low
close
pre_close
volume_shares
amount_cny

selected_provider
source_policy_version
source_revision
reconciliation_status
available_at
quality_flags
```

---

## 8.2 `fact_security_status_daily`

```text
security_id
trade_date
is_listed
is_st
is_suspended
is_delisting_period
trading_status

selected_provider
source_policy_version
...
```

---

## 8.3 `fact_limit_price`

```text
security_id
trade_date
pre_close
up_limit
down_limit
has_price_limit
limit_rule_id

selected_provider
source_policy_version
...
```

---

## 8.4 `fact_adj_factor`

```text
security_id
trade_date
adj_factor
factor_type
effective_date

selected_provider
source_policy_version
...
```

---

## 8.5 `fact_corporate_action`

至少：

```text
security_id
event_date
ex_date
event_type
is_ex_dividend
is_ex_rights
source_revision
available_at
...
```

---

# 9. 单源情况下的 Reconciliation 状态

当前正式第二源不可用。

因此：

```text
reconciliation_status
```

不得写：

```text
PASS
```

必须明确：

```text
NOT_RUN_NO_SECONDARY
```

允许进行：

```text
schema validation
OHLC invariant
unit validation
manual Golden
corporate-action continuity
coverage check
```

这些叫：

```text
Single-source validation
```

不是 cross-provider reconciliation。

---

# 10. Source Policy 骨架继续开发

现在可以完成：

```text
CANDIDATE
APPROVED
RETIRED
```

状态机。

但：

> 未经过正式账号 Spike 的 AmazingData capability 只能进入 `CANDIDATE`。

正式批准流程：

```text
Real account
→ Spike
→ Golden
→ Provider Verification
→ Source Policy Dry-run
→ APPROVED
```

---

# 11. B2–B7 Spike 脚本现在全部实化

不要等正式账号才写代码。

正式账号下来当天应该只做：

```text
配置凭证
运行脚本
分析结果
```

而不是临时开发接口调用。

---

# 12. 正式账号 Spike 顺序

必须按依赖从核心到外围运行。

## B2 — Identity / Security Master

验证：

```text
get_hist_code_list
get_stock_basic
get_bj_code_mapping
```

覆盖：

```text
正常上市
退市
退市整理
ST/*ST
北交所
历史代码
代码映射
```

### Gate

若历史 Security Master 不可满足：

```text
P0a NO_GO
```

---

## B3 — Core Market Facts

验证：

```text
Trade Calendar
Daily Bar
Historical Status
Limit Price
```

样本：

```text
主板10%
科创/创业20%
北交所30%
ST 5%
新股无涨跌幅限制
停牌/复牌
规则切换
```

### Gate

任一核心事实不满足：

```text
P0a NO_GO
```

---

## B4 — Corporate Action / Adjustment

验证：

```text
Adj Factor
Backward Factor
Ex-dividend
Ex-rights
Dividend
Split/rights
```

重点：

```text
raw price
adjusted price
open/preclose
corporate-action continuity
```

---

## B5 — Data Semantics / Unit / Cache / Freshness

验证：

```text
volume unit
amount unit
price scaling
index units
snapshot units
is_local=True/False
cache freshness
history start
latest date
available_at
```

必须输出 Endpoint-Level Unit Map。

---

## B6 — Replacement Assessment

### `free_share / turnover_rate_f`

分类：

```text
EXACT_EQUIVALENT
DERIVABLE_EQUIVALENT
ALTERNATIVE_SEMANTICS
MISSING
```

禁止通过字段名相似直接认定。

### Industry

确认：

```text
SW
or
GALAXY taxonomy
```

未确认前：

```text
GALAXY_UNVERIFIED
```

不得映射成 SW。

### Benchmark

验证：

```text
指数类型
PRICE/TOTAL return
history
index code
```

---

## B7 — Capacity / Backfill

最后再测：

```text
1 month full market
batch download
throughput
retry
cache
failure recovery
```

只有 B2-B5 核心通过后才值得跑 B7。

---

# 13. Spike Gate 的严格定义

整体报告允许输出：

```text
GO_CORE
GO_DEGRADED
NO_GO
```

但进入 P0a 的真正条件是：

```text
CORE capability subset = 全部 GO
```

即：

```text
Security Master          GO
Daily Bar                GO
Historical Status        GO
Limit Price              GO
Adj Factor / CA          GO
Trade Calendar           GO
```

### 允许 GO_DEGRADED 的缺失

只允许因为：

```text
free_share 缺失
SW taxonomy 缺失
真实第二源 Reconciliation 缺失
```

而 degraded。

### 不允许

若：

```text
Historical Status = DEGRADED/FAIL
```

则：

```text
P0a BLOCKED
```

---

# 14. P0a 的真实范围重新固定

P0a 不要求完整 PV。

## P0a 正式纵贯线

```text
AmazingData
    ↓
Raw
    ↓
Provider-normalized
    ↓
Canonical Daily/Status/Limit/Adj/CA
    ↓
Stable Security ID
    ↓
ALL_A Universe
    ↓
Trend BASE
    ↓
Market Aggregate
    ↓
Feature Artifact
    ↓
Publish
    ↓
Published / Exact Reader
```

### P0a 不要求

```text
SW
free_share
完整 PV
真实双源 Reconciliation
Theme
API
```

---

# 15. Trend 优先于 PV

下一阶段 Feature 开发原则：

```text
Trend 先做
PV 只做 Schema / Registry / Mock 骨架
```

禁止为了提前完成 PV：

```text
使用普通流通股本替代 free_share
修改 turnover_rate_f 定义
```

---

# 16. P0a 不直接跑十年全市场

正式数据进入 P0a 后必须分级放量。

## Stage A

```text
20 securities
×
60 trading days
```

验证：

```text
Raw
Canonical
Security ID
Trend
Aggregate
Artifact
Publish
Exact Replay
```

---

## Stage B

```text
100 securities
×
2 years
```

验证：

```text
rolling
revision
snapshot
artifact patch replay
performance
```

---

## Stage C

```text
ALL_A
×
1 month
```

验证：

```text
coverage
memory
partition
file size
runtime
```

---

## Stage D

只有前三阶段全部通过后：

```text
2014/2015 → current
```

执行正式历史 Backfill。

---

# 17. 仿真账号当前还能做的价值测试

若实时 L1 `SubscribeData` 实测通过，建议做一个小型 Capture Test。

## 样本

```text
20 stocks
```

覆盖：

```text
SH
SZ
BJ
high-liquidity
low-liquidity
near-limit
```

## 时段

```text
09:15–10:00
14:45–15:05
```

## 观察

```text
provider_event_time
received_at
latency
duplicate
out-of-order
cumulative volume
cumulative amount
bid/ask 1-5
trading_phase
up/down limit
unsubscribe
reconnect
```

### 注意

仿真账号：

```text
订阅数 100
带宽 0.2MB/s
周流量 10GB
```

这些是账户 entitlement，不是 AmazingData 平台性能上限。

不得拿来做 Phase 2 容量结论。

---

# 18. 正式账号到位后的 Runtime 必须重新验证

正式账号不是简单“换用户名密码”。

必须重新运行：

```text
provider doctor
login
L1 subscription
minimal query
B2-B7
```

重新记录：

```text
account_profile_id
permission profile
subscription limit
bandwidth
history permission
cache behavior
server endpoint
SDK/runtime version
```

仿真结果不得自动继承。

---

# 19. Runbook 现在可以开始写

建议同时完成：

```text
docs/runbook/
├─ install_core.md
├─ install_amazingdata.md
├─ init_db.md
├─ provider_doctor.md
├─ run_spike.md
├─ run_backfill.md
├─ recover_duckdb.md
└─ publish_recovery.md
```

目标：

> 换一台干净机器时，可以仅靠文档完成安装和恢复。

---

# 20. 下一次设计侧评审提交物

下一次不需要再交泛泛工作总结。

必须提交以下 4 份材料。

## 20.1 M0 Final Exit Report

包含：

```text
GitHub CI
Python 3.14
Windows/Linux
Migration
Security ID
Manifest
Failure Injection
```

---

## 20.2 P0-M-1 Production Spike Report

包含：

```text
B2-B7
GO_CORE / GO_DEGRADED / NO_GO
权限矩阵
历史覆盖
单位
Cache
Availability
Security Master
Status
Limit
Adj
Corporate Action
free-float
Industry
Benchmark
Capacity
```

---

## 20.3 AmazingData Provider Verification

必须包含：

```text
wheel filename
SHA256
AmazingData package version
tgw package version
loaded DLL path/version
Python ABI
OS
account_profile_id
verified_at
capabilities
known issues
```

---

## 20.4 P0a Entry Checklist

逐项：

```text
M0 PASS
Runtime identity verified
Core Spike all GO
Canonical contracts frozen
Source Policy candidate defined
Security ID Golden pass
Feature Set Registry ready
```

只有全部通过才批准 Real P0a。

---

# 21. 当前禁止事项

从现在到正式账号完成 Spike 前，开发人员不得：

```text
1. 把 AmazingData 未实测接口标 APPROVED
2. 把 Galaxy 行业写成 SW
3. 把 FLOAT_A_SHARE 写成 free_share
4. 把单源自洽写成 Reconciliation PASS
5. 修改 CORE Feature 数学口径迁就 Provider
6. 直接开始 10 年全市场 Backfill
7. 绕过 Raw 层直接 SDK → Canonical
8. 让 SDK TypeError 穿透 Provider 边界
9. 把 Trial 带宽/订阅上限当平台容量
10. 自动将 AKShare 设为正式 fallback
11. 在 Python 3.12-only CI 下宣称 3.14 生产环境已验证
12. 把 Provider 一个接口返回的多个事实域合并成一个 Canonical 事实所有者
```

---

# 22. 推荐执行顺序

```text
NOW
│
├─ 1. GitHub CI 首跑 + Python 3.14
├─ 2. L1 SubscribeData 真实重测
├─ 3. Runtime/DLL identity doctor
├─ 4. AmazingData Adapter
├─ 5. Raw Envelope
├─ 6. Provider-normalized DTO
├─ 7. Canonical 5 Domains DDL
├─ 8. Source Policy/Reconciliation Skeleton
├─ 9. B2-B7 Spike Scripts 实化
└─ 10. Runbook

WAIT FOR PRODUCTION ACCOUNT
│
└─ P0-M-1B Full Spike
       │
       ├─ CORE all GO
       │      ↓
       │     P0a
       │
       └─ any CORE NO_GO
              ↓
             BLOCK
             ADR / New Provider / Permission Resolution

P0a
│
├─ 20 × 60d
├─ 100 × 2y
├─ ALL_A × 1m
└─ Full Historical Backfill
```

---

# 23. 设计侧正式结论

第一阶段工作可以继续。

当前工程重点从：

```text
“搭架子”
```

切换到：

```text
“把 Provider → Raw → Normalized → Canonical Contract 做扎实”
```

而不是提前进入大量 Feature 开发。

下一阶段成功的标志不是：

```text
写了多少接口
```

而是：

```text
正式账号一到，
B2-B7 能直接跑，
核心能力能被客观判定，
数据能无歧义地进入 Canonical，
然后 P0a 可以快速打通。
```

正式执行口径：

```text
M0 = 收口
P0-M-1 = 等正式账号完成
Adapter/Canonical = 立即推进
Feature = Trend优先、PV不抢跑
P0a = Core Spike GO 后进入
```

**本任务书即为下一阶段开发执行要求。**
