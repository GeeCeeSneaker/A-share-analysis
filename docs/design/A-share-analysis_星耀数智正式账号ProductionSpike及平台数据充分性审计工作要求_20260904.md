# A-share-analysis：星耀数智正式账号 Production Spike 及平台数据充分性审计工作要求

> **Date**：2026-09-04  
> **Reviewer Baseline**：`4ac274747e86d5f386560ceabbffa3273ca9d14b`  
> **Parallel Track**：CR-6 State 开发可并行；本批次不得修改 CR-5 冻结语义，也不得越权批准未验证 Provider capability  
> **Status**：**P0-M-1B ACCOUNT DETAILS RECEIVED / SDK SMOKE PASS / FORMAL VALIDATION PENDING**  
> **Production Truth**：正式账号“已存在”≠正式数据源“已验证”；只有 frozen account identity + production Spike + golden + evidence closure + Reviewer approval 才能授予 APPROVED  
> **Credentials**：用户名、密码、Token、真实 host 明文等一律只进 `.env`/运行环境，不得写入 Git、日志、issue、PR body 或本文件

---

# 0. 本轮目标

正式账号已经具备，原 `AWAITING PRODUCTION ACCOUNT` 前置条件解除。现在启动两个彼此关联但结论必须分开的工作流：

```text
A. Provider Production Validation
   正式账号到底能不能稳定、正确、可审计地提供平台核心事实？

B. Platform Data Sufficiency Audit
   即便核心 Spike 通过，星耀数智的数据面是否足以支撑当前平台与后续研究？
   哪些数据可直接进入既有 Canonical？
   哪些接口存在但还没有平台合同？
   哪些语义/PIT 不足，必须补充其他数据源？
```

禁止仅凭 SDK 手册/API 名称、登录成功或“有返回值”给出 GO。

---

## 0.1 Repository implementation update (2026-09-04)

- Added `scripts/spike/production_account_bootstrap.py` as the P0-AD-01 controlled entry point. It reads credentials only from environment/.env, emits an allowlisted scrubbed profile, and never writes `configs/production_account.yaml`.
- Added offline/injected-doctor tests proving missing credentials fail closed, `--offline` passes no credentials, raw error fields are not emitted, and human confirmation remains required.
- This advances the executable boundary only; the production identity is not frozen, B1-B7 and Data Sufficiency Matrix remain pending, and no capability approval is claimed.

---

---

# 1. 当前事实基线

## 1.1 当前本地 SDK 冒烟事实（2026-09-04）

- 受控 Python 3.14.6 已安装官方 `AmazingData==1.1.9` cp314 wheel、`tgw==1.0.9.2` 和 `tables` 运行依赖；TGW runtime 为 `V4.3.0.260626-rc2.0-YHZQ`，`uv pip check` 通过。
- 正式账号登录成功，profile 已解析，权限/功能权限字段存在。SDK 原始 stdout/stderr 在调用边界被捕获；用户名、密码、Token、host、port、原始 payload 和临时 profile 均未写入 GitHub、日志或结果文件。
- 直连小窗口结果：calendar 8,719；当前沪深代码 5,215；2026-09-03 单日历史代码列表 5,215；北交所映射 248；stock basic 1；history status 1；adj factor 8,719；dividend 54；right issue 0；equity structure 68；industry base 511；industry constituent、股票日线、指数日线均返回结构化结果；logout 正常。
- 这不是正式 Production Spike：未执行仓库 facade/provider-doctor、run-scoped B1-B7、Golden/Data Sufficiency Matrix 或 verdict；历史代码列表仅做单日窗口，不能替代 2020+ 全历史覆盖。
- 用户提供的 wheel 和所需依赖已保存在本地被忽略目录 `vendor/amazingdata/`，不上传 GitHub。当前 SDK 测试环境没有仓库源码，所以形式化 runner 尚未执行；`configs/production_account.yaml` 继续为空，正式 approval 不得提前授予。

仓库已有正式 Spike 框架：

```text
b1 formal runtime gates
b2 security master
b3 core facts
b4 golden
b5 units / PIT / freshness
b6 replacement / optional semantics
b7 capacity / backfill
```

正式 run 必须是一个 `RunKind.PRODUCTION` 单 run 全阶段执行，run-scoped 保存原始 ProviderExchange、Raw evidence、cases、verdict，并通过 evidence closure。

现有 capability gate：

## 1.1 Core 8（全部 PASS 才能 GO_CORE）

1. `security_master_with_delisted`
2. `daily_bar_units`
3. `historical_st_suspend`
4. `limit_price_and_no_limit_days`
5. `adj_factor_corporate_action_continuity`
6. `history_start_2020`
7. `symbol_mapping_unambiguous`
8. `sdk_permission_cache_freshness`

## 1.2 Existing Optional 4

1. `free_float_equivalence`
2. `sw_taxonomy`
3. `benchmark_index_availability`
4. `capacity_backfill`

现有 production provider operation 已覆盖/预留：

```text
trade_calendar
security_master / hist_code_list / stock_basic
code_mapping_bj
daily_bar
security_status_history -> status / limit / CA facts
adj_factor / backward_factor
corporate_action dividend / right_issue
equity_structure
industry_taxonomy base / constituent
index_daily kline
```

但当前 operation contract **尚未**覆盖：

```text
index constituent
index daily weight
industry daily
industry daily weight
margin summary/detail
financial statements / forecast / express
shareholder / pledge / unlock etc.
```

这些接口即使 SDK 可调用，也不得未经新 capability / operation / normalization / Canonical contract 直接进入平台。

---

# 2. 第一阶段：正式账号身份冻结（P0-M-1B.0）

## P0-AD-01：真实登录，只产生 scrubbed identity

使用现有 `AmazingDataSession` 完成正式登录，必须得到：

```text
auth_ok = true
profile_parsed = true
PermissionCode 非空
account_profile_id = <scrubbed stable id>
SubscribeLimitNum
TotalWeekFlow
PushBandwidth / QueryBandwidth（若 profile 提供）
```

禁止记录：

```text
username
password
Token
完整账号号
真实凭证内容
```

现有 `scripts/spike/connectivity_check.py` 仍硬编码 simulation account 文案，**不得直接把它的 `account_type=simulation` 输出作为 production identity 证据**。如需 bootstrap 工具，应新增正式 `production_account_bootstrap.py` 或使用现有 session/profile API，只输出 scrubbed profile。

## P0-AD-02：人工确认 production 身份

在确认该账号确属本项目正式星耀数智账号后，把**仅 scrubbed** 的：

```yaml
production_account_profile_id: "<scrubbed-id>"
confirmed_at: "YYYY-MM-DD HH:mm +08:00"
confirmed_by: "<human/operator role or approved identifier>"
```

写入 `configs/production_account.yaml`。

这是 governance allowlist，不是凭证文件。

必须验证：

```text
load_frozen_production_identity() != None
production_account_status(live_profile) == PRODUCTION
trial / unknown / different-account profile 均不能匹配
```

`production_account.yaml` 从空变为非空是正式 contract change：同 commit 必须更新 DEVLOG + DEVELOPMENT_MANAGEMENT，并新增测试覆盖 exact match / mismatch / trial refusal。

---

# 3. 第二阶段：正式 Production Spike（P0-M-1B.1）

账号身份冻结后执行：

```powershell
uv run python scripts/spike/spike_runner.py --production --date <最近已完整收盘交易日>
```

不得用 future/non-trading date；不得拆成多个独立 production run 后拼 verdict。

完成后：

```powershell
uv run python scripts/spike/spike_runner.py --verdict --run-id <id>
```

输出必须至少有：

```text
spike_run.json
raw/
cases/
verdict.json
formal gate reports
```

需要记录：

- run id；
- frozen account_profile_id（scrubbed）；
- code commit / environment lock / config hash；
- SDK / runtime version；
- permission codes / quota snapshot（不得含 secret）；
- B1..B7 每阶段状态；
- Core 8 每项 PASS/FAIL/NOT_TESTABLE；
- Optional 4 每项结论；
- `GO_CORE / GO_DEGRADED / NO_GO / SPIKE_INCOMPLETE`；
- p0a/p0b/backfill eligibility；
- evidence closure result。

任何 permission denial、SDK `NoneType`、generic 查询失败、schema drift 均作为 evidence，不得人工改写为 PASS。

---

# 4. 平台数据充分性审计（P0-M-1B.2）

Production Spike 只回答“现有核心能力能不能用”。本批还必须追加一张**Data Sufficiency Matrix**，逐项输出：

```text
REQUIRED_NOW
REQUIRED_NEXT
OPTIONAL_RESEARCH
NOT_NEEDED_CURRENTLY
```

以及：

```text
AVAILABLE_AND_VERIFIED
AVAILABLE_NOT_VERIFIED
AVAILABLE_BUT_SEMANTICS_INSUFFICIENT
NOT_IN_PLATFORM_CONTRACT
MISSING_FROM_PROVIDER_OR_ACCOUNT
```

## 4.1 当前平台事实层（必须满足）

### A. Trade Calendar

需要：沪/深/北交易日历、历史完整性、可用时间。  
结论门：`BaseData.get_calendar` production entitlement + 历史覆盖 + freshness/PIT。

### B. Security Master / Delisted / BJ Mapping

需要：

- 当前 + 历史证券列表；
- 上市/退市日期；
- 退市证券不丢失；
- 沪深北身份；
- 北交所新旧代码 mapping；
- 禁止代码前缀猜交易所。

### C. Stock Daily Bar

需要：

```text
open/high/low/close/pre_close/volume/amount
```

必须验证：

- 2020-01-01 起历史深度是否真实可取；
- 2020+ 全 A 研究覆盖；
- volume 是股还是手；
- amount 是元还是其他单位；
- 停牌日/无成交日行为；
- 北交所覆盖；
- EOD 实际 available_at；
- cache / is_local / repeated pull 的修订行为。

### D. Historical Security Status + Limit Facts

需要按日：

```text
ST
suspension
pre_close
high_limit
low_limit
limit rates
ex-right / ex-dividend flags
```

必须与交易所制度 golden 比对，特别覆盖：

- ST 加/脱帽；
- 主板/创业板/科创板/北交所不同涨跌停制度；
- 新股/无涨跌停日；
- 退市整理等特殊制度（若研究期覆盖）；
- 除权除息连续性。

### E. Adjustment / Corporate Action

需要：

- adj factor；
- backward factor；
- dividend；
- right issue；
- event date / ex-date 与价格连续性。

**注意**：接口存在不等于复权公式已被证明。只有 factor orientation / base / revision semantics 被验证后，未来 CR 才能解锁 adjusted return。

## 4.2 当前 CR-6 V1 是否够用

CR-6 当前四个描述性 State 只依赖 CR-5 已冻结的 market daily features，其核心 value 最终来自 stock daily bars。

因此：

```text
若 daily_bar + master/calendar 的 production validation 通过，
当前 CR-6 V1 的“数值输入”原则上够用。
```

但平台数据源不能因此只验 daily bar：status/limit/CA/adj/master 仍是后续 Feature/Research 的基础事实域，必须完成 Core Spike。

---

# 5. 近中期平台“必须补审”的数据面

以下是“SDK 看起来有，但当前平台合同还不完整”的优先数据。

## P1-01：指数成分 + 权重（高优先）

SDK 文档提供：

```text
get_index_constituent
get_index_weight
```

当前平台只有 `index_daily` kline operation，没有正式 index constituent/weight operation。

用途：

- benchmark-relative research；
- HS300/500/1000/2000 等 benchmark universe；
- 指数成分 PIT；
- 后续相对强弱 / beta / breadth benchmark。

必须验证 `INDATE/OUTDATE/TRADE_DATE` 及历史修订行为。若通过，再新建 capability + normalization + Canonical contract；不得直接从 InfoData 绕过 provider facade。

## P1-02：行业 taxonomy / constituent / weight / daily（高优先）

现有 provider operation 只有：

```text
industry_base_info
industry_constituent
```

而 SDK 文档另有：

```text
industry_weight
industry_daily
```

当前 operations.py 明确把后两者留在 NOT_APPLICABLE/non-operation 状态。

必须判断：

1. taxonomy 是申万还是银河自编；
2. 若非申万，必须明确 `GALAXY_xxx`，禁止冒充 SW；
3. constituent 的 INDATE/OUTDATE 是否是历史 PIT；
4. weight/daily 是否有足够历史；
5. 数据是否会因 provider 后续修订改写历史。

这是以后行业轮动/市场结构扩展的关键数据。

## P1-03：股本 / 自由流通口径（高优先）

已有 `get_equity_structure` operation，但当前只是 Optional `free_float_equivalence`。

必须把字段结论分为：

```text
EXACT
DERIVABLE_WITH_PROVEN_FORMULA
ALTERNATIVE_SEMANTIC
MISSING
```

重点回答：

- 总股本；
- 流通股；
- 自由流通股/比例是否等价；
- 数据生效日/公告日/归档日；
- 历史股本变更是否完整。

若无法严格得到 free float，不得为了算换手率而猜。

## P1-04：融资融券（中高优先）

SDK 文档存在 `get_margin_detail` / `get_margin_summary`，当前 Provider contract 未接入。

用途候选：

- leverage / stress；
- 风险偏好；
- 市场流动性压力；
- 后续 State 扩展。

先做 availability/schema/history/PIT 验证，不进入当前 CR-6 V1。

## P1-05：财务三表 / 业绩快报 / 预告（研究平台高优先、当前 State 非必需）

SDK 有财务数据，但**平台能否使用的关键不是有没有报表，而是 PIT**：

必须验证：

```text
announcement_date / publish_time
report_period
revision/update identity
同一 report_period 多版本
restatement 后旧世界是否可重建
可用时间是否早于实际公告
```

如果只能拿“当前修订后的最终值”而没有版本/公告时点，就不能作为历史因子真相。

这种情况下必须寻找第二数据源或公告原文事实源。

---

# 6. 当前不必为了日频平台采购的数据

除非未来范围改变，下列不作为本轮核心 GO 条件：

```text
Level-2 tick/orderbook
超高频逐笔
期货/期权全量微观结构
实时交易接口
另类新闻/舆情
ML vendor factors
```

星耀数智官方支持 L1/分钟/日线及实时订阅；L1 可以独立验证，但**当前日频平台不应因为账号有权限就扩大架构范围**。

---

# 7. 预计数据缺口 / 第二来源策略

在 production evidence 出来前，不预设一定缺失，但重点关注以下可能缺口：

## Gap-A：PIT 财务版本历史

若星耀只能返回最终修订表，不含可重建的历史版本，则需要：

- 具备公告时点/修订版本的数据源；或
- 交易所/巨潮等公告原文 + 自建 PIT ingest。

## Gap-B：自由流通股的严格语义

若 `equity_structure` 只能给流通股而非 free-float，则不能静默替代。可考虑其他已验证来源；TDX/miniQMT 只在各自项目通过正式验证后才能成为候选。

## Gap-C：标准行业体系

若 AmazingData 行业为银河自有 taxonomy，而后续研究要求申万历史分类，则需要独立 SW 数据授权/来源；不得通过名称相似强行映射。

## Gap-D：指数 PIT 成分/权重

若历史 constituent/weight 的 OUTDATE/历史权重存在回写/缺口，需要补第二来源或将其降级为不可作为 PIT universe truth。

## Gap-E：跨源独立验证

`daily_bar_units` 等关键口径不能只靠 provider 自证。TDX / miniQMT / 交易所公开事实可作为独立校验源，但只有各自验证通过后才可进入 production SourcePolicy；验证源和生产源身份必须分开。

---

# 8. 正式账号验证后必须输出的 Data Sufficiency Matrix

至少形成如下表格并写入 `docs/provider_verification/amazingdata.md` 的新 append-only/current-truth section，另可生成独立报告：

| 数据域 | Provider endpoint | Account permission | History | PIT/Revision | Semantic result | Platform contract | Decision |
|---|---|---|---|---|---|---|---|
| trade calendar | get_calendar | ? | ? | ? | ? | existing | ? |
| security master | get_hist_code_list/get_stock_basic | ? | ? | ? | ? | existing | ? |
| daily bar | query_kline | ? | ? | ? | ? | existing | ? |
| status/limit | get_history_stock_status | ? | ? | ? | ? | existing | ? |
| adj factor | get_adj_factor/get_backward_factor | ? | ? | ? | ? | existing | ? |
| corporate action | get_dividend/get_right_issue | ? | ? | ? | ? | existing | ? |
| equity/free float | get_equity_structure | ? | ? | ? | EXACT/... | candidate | ? |
| index daily | query_kline(index) | ? | ? | ? | ? | existing candidate | ? |
| index constituent | get_index_constituent | ? | ? | ? | ? | **not yet** | ? |
| index weight | get_index_weight | ? | ? | ? | ? | **not yet** | ? |
| industry taxonomy | get_industry_base_info | ? | ? | ? | SW/GALAXY | candidate | ? |
| industry constituent | get_industry_constituent | ? | ? | ? | ? | candidate | ? |
| industry daily | get_industry_daily | ? | ? | ? | ? | **not yet** | ? |
| industry weight | get_industry_weight | ? | ? | ? | ? | **not yet** | ? |
| margin | get_margin_* | ? | ? | ? | ? | **not yet** | ? |
| financials | get_balance_sheet/get_cash_flow/get_income | ? | ? | **critical** | ? | **not yet** | ? |

Decision 只能使用：

```text
APPROVE_EXISTING_CAPABILITY
GO_DEGRADED_EXISTING
NEW_CAPABILITY_REQUIRED
SEMANTICS_BLOCKED
PIT_BLOCKED
PERMISSION_BLOCKED
PROVIDER_MISSING
NOT_NEEDED_CURRENTLY
```

---

# 9. 运行顺序与流量纪律

正式账号虽可能额度更高，也不得一开始就全量 2020+ 全市场猛拉；2020 年以前不是当前回填目标。

建议顺序：

```text
Step 0  account profile bootstrap/freeze
Step 1  B1 formal gates
Step 2  tiny permission probes
Step 3  B2/B3 targeted samples
Step 4  B4 golden cases
Step 5  B5 units + availability/freshness
Step 6  B6 optional semantics
Step 7  B7 one-month capacity
Step 8  production verdict
Step 9  extended sufficiency probes
Step 10 whole-market historical backfill only after approval
```

要求：

- serial/bounded retry；
- 记录 account quota before/after；
- provider generic retry 不得吞掉 permission error；
- 所有成功/失败 exchange 都有 Raw evidence；
- extended probes 也必须走 hardened provider adapter，禁止 notebook 直接调用 SDK 后口头下结论。

如果需要探测尚无 operation 的接口，先新增 **SPIKE-only typed operation/capability contract**，经 Reviewer 审查后执行；不得直接把未治理 SDK 方法塞入正式 raw/canonical 路径。

---

# 10. 与 CR-6 的并行关系

CR-6 当前可继续开发，因为它的 correctness contract 不依赖“今天实时去拉星耀数据”；它只消费 Verified Feature Run。

并行规则：

```text
CR-6 track
  继续 State Registry / engine / artifact / replay 开发

Provider validation track
  冻结 production account -> production Spike -> data sufficiency audit
```

二者不互相改写历史。

如果 Provider Spike 发现核心数据语义与当前 frozen Canonical assumption 冲突：

```text
不要静默修 CR-3/CR-5
→ 先提交 reproducible provider evidence
→ Reviewer 判断是 provider NO_GO、mapper correction、还是需要新 ADR/CR
```

---

# 11. Exit Gate

本批次完成必须同时满足：

1. 正式账号 scrubbed identity 已人工确认并冻结；
2. `production_account.yaml` 无任何 secret；
3. live profile exact-match production allowlist；
4. 单一 CLOSED PRODUCTION run B1-B7 完整；
5. verdict + evidence closure；
6. Core 8 全部有明确结论；
7. Existing Optional 4 全部有明确结论；
8. 历史深度必须证明满足 2020+ 研究；2020 年以前不再作为 GO 条件或回填目标；
9. daily bar volume/amount unit 有独立证据；
10. EOD available_at/freshness 有实测；
11. historical status/limit golden 达标；
12. adjustment/CA continuity golden 达标；
13. delisted survivorship golden 达标；
14. BJ mapping 无歧义；
15. capacity/backfill 有真实 throughput/quota 证据；
16. 完成 Data Sufficiency Matrix；
17. 对 index constituent/weight、industry weight/daily、equity/free-float、margin、financial PIT 给出明确下一步；
18. `docs/provider_verification/amazingdata.md` 更新当前 production 事实；
19. `docs/spike_report_p0m1.md` 更新正式结果；
20. DEVLOG + DEVELOPMENT_MANAGEMENT 同步；
21. 未经 Reviewer 审批不得把 CANDIDATE capability 改为 APPROVED；
22. 未经 PIT/semantic proof 不得新增 Feature/State 公式消费扩展数据。

---

## 11.1 当前阻塞记录（2026-09-04）

本批文档要求可以继续推进的代码、合同和测试已进入仓库；但以下生产事实不能由开发人员伪造，因此仍保持阻塞：

1. `configs/production_account.yaml` 的 `production_account_profile_id`、`confirmed_at`、`confirmed_by` 仍为空；
2. 当前仅有试用仿真账号的 B1 连通性证据，B2-B7 正式生产验证尚未执行；
3. `docs/provider_verification/amazingdata.md` 已记录正式账号 native SDK smoke 通过；但 scrubbed production profile identity 与 entitlement allowlist 仍待人工确认；
4. `docs/spike_report_p0m1.md` 当前结论仍为 `未评定`，没有生产 `GO_CORE` / `GO_DEGRADED` / `NO_GO` verdict；
5. 因此不得勾选正式账号、CLOSED PRODUCTION B1-B7、Golden/Data Sufficiency Matrix、Reviewer approval 或 capability APPROVED 等退出项。

解除阻塞所需的最小外部输入是：由 Owner/Reviewer 人工确认的脱敏稳定账号画像和实际 entitlement；凭证只能通过运行环境注入。账号到位后仍必须按本文件的单一 production run、evidence closure、2020+ 历史合同和 Reviewer 复核流程执行。

---

# 12. Reviewer 当前预判（非最终 verdict）

在正式 run 之前，仅依据已验证 API 面与官方文档，可给出以下**预判而非 APPROVAL**：

```text
当前日频平台核心事实层：
  星耀数智“能力面上大概率足够”，但 formal entitlement / history / semantics 尚未证明。

当前 CR-6 descriptive V1：
  若 daily_bar production PASS，数据输入原则上足够。

近中期完整市场研究底座：
  预计需要把 index constituent/weight、industry weight/daily、equity/free-float
  纳入正式验证和平台 contract。

基本面/PIT 因子研究：
  不能仅凭“三表接口存在”判定足够；公告时点与历史修订版本是硬门。

高频/Level-2：
  当前平台不需要，不作为本轮采购或 GO 条件。
```

最终只能以正式账号 evidence 为准。


## 11.2 SDK 安装前正式账号验证尝试记录（2026-09-04，历史记录）

- Owner 已通过当前协作会话提供正式账号连接信息；用户名、密码、Token、真实 host 和端口值均未写入 GitHub、日志、Issue、PR 或本文件。
- 对 Owner 提供的两个候选服务端点执行了独立 TCP 可达性探测：端口可达。该结果只证明网络路径，不证明登录、账号身份、权限或数据正确性。
- 当前受控 Python 3.14.6 环境未安装官方 `AmazingData` 与 `tgw` wheel；未发送登录请求，因此 `AUTHENTICATED`、`ACCOUNT_PROFILE`、`QUERY_READY` 均为 `NOT_TESTED`，B1-B7 尚未执行。
- `configs/production_account.yaml` 继续保持空白；未生成 frozen production identity、正式 verdict、Golden 或 Data Sufficiency Matrix 结论。
- 解除当前阻塞的最小输入：在受控环境安装并记录银河提供的官方 wheel 指纹，然后依次运行 provider doctor、单一 CLOSED PRODUCTION B1-B7 run、verdict 和人工复核；安装包不是公共同名包的替代品。
