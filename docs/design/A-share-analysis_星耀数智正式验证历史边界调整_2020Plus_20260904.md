# A-share-analysis：星耀数智正式验证历史边界调整（2020+）

> **Owner Decision Date**：2026-09-04  
> **Applies To**：星耀数智 Production Spike / Platform Data Sufficiency Audit / historical backfill / future research default data horizon  
> **Parent Requirement**：`docs/design/A-share-analysis_星耀数智正式账号ProductionSpike及平台数据充分性审计工作要求_20260904.md`  
> **Decision**：**默认历史边界统一调整为 2020-01-01 起；不再要求、拉取或回填 2020 年以前历史数据。**

---

## 1. 正式业务边界

Owner 已明确：A 股市场结构与参与者行为变化较快，平台研究价值主要集中在较近市场制度/生态。因此平台默认历史事实世界统一采用：

```text
DEFAULT_HISTORY_START = 2020-01-01
```

正式含义：

1. Raw / Provider-Normalized / Canonical / Snapshot / Feature / State 的默认历史回填从 2020-01-01 起；
2. 不建立 2020 年以前的常规平台历史库；
3. 不因 MA60 / lag60 / observed-window 等 Feature warmup 需要向 2019 或更早回填；
4. 2020 年初窗口不足时，继续使用 CR-5 已冻结的 missingness / insufficient-history 语义，值保持 NULL/UNKNOWN，禁止用 2019 数据偷偷补齐；
5. 研究、策略回测、数据充分性评估默认只要求 2020+；
6. 任何未来要求恢复 2020 年以前数据，必须由 Owner 新决策 + 独立工作批次，不得由开发人员自行扩大历史范围。

---

## 2. Production Spike Core Gate 必须调整

当前 Spike core capability 仍包含历史旧合同：

```text
history_start_2018_plus_warmup
```

其旧描述要求：

```text
history depth covers 2018 + warmup to 2014/2015
```

该合同从本 Owner Decision 起不再符合项目要求，**在正式 production run 前必须完成治理和实现调整**。

### 2.1 推荐新 capability identity

推荐替换为：

```text
history_start_2020
```

描述：

```text
provider historical coverage continuously supports required A-share facts from 2020-01-01 onward
```

validator 推荐：

```text
history_coverage_2020_v1
```

### 2.2 GO_CORE 新判定

历史覆盖 Core Gate 只需证明：

- 2020-01-01 起交易日历可覆盖；
- 2020-01-01 起股票日线可取；
- 2020-01-01 起历史证券身份/退市证券不产生 survivorship omission；
- 2020-01-01 起 ST/停牌/涨跌停等核心状态在供应商可用范围内连续；
- 2020-01-01 起复权/公司行动满足对应 Core/Golden 合同；
- 沪/深/北在各自适用时间段内按真实上市制度覆盖。

不得因为缺失 2019、2018、2015、2014 数据判定 NO_GO / SPIKE_INCOMPLETE。

---

## 3. 需要修改的代码/治理位置

开发人员在正式 Production Spike 前必须至少检查并同步：

```text
src/ashare_state/spike/capabilities.py
src/ashare_state/spike/validators.py（或实际 history validator 所在模块）
src/ashare_state/spike/probes.py（若采样起点硬编码旧年份）
src/ashare_state/spike/verdict.py / coverage mapping（如涉及 capability id）
tests/unit|integration 下所有 history_start_2018_plus_warmup 断言

docs/spike_report_p0m1.md
docs/provider_verification/amazingdata.md
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

如果 capability id 被正式改名，所有 registry / approval mapping / case type / verdict mapping 必须 exact 同步，禁止留下旧 id 和新 id 双真相。

历史 Git/DEVLOG 中旧的 `2018 + 2014/2015 warmup` 记录保留为历史，不回写篡改；以本决策及后续治理同步为当前真相。

---

## 4. Data Sufficiency Matrix 历史列的新标准

原数据充分性审计中所有“历史深度”判断统一改为：

```text
REQUIRED HISTORY = 2020-01-01 -> latest complete trading day
```

每个数据域至少输出：

```text
coverage_start
coverage_end
missing_date_count / missing_interval
revision/PIT semantics
permission result
2020_plus_sufficiency = PASS | FAIL | NOT_TESTABLE
```

不再使用“2013 起”“2014/2015 warmup”“2018 起”作为平台 GO 条件。

---

## 5. Backfill 纪律

正式账号验证通过后，历史回填执行顺序调整为：

```text
1. 小样本权限/字段/语义验证
2. Golden / PIT / unit validation
3. 近期 1 个月全市场容量测试
4. GO 后分批回填 2020-01-01 -> 当前
5. 不拉 2020-01-01 以前数据
```

不得因为供应商“能提供 2013 至今”就默认拉全量。

容量、磁盘、网络流量和 evidence 存储评估也必须以 **2020+ 实际目标数据量**重新计算。

---

## 6. 对当前 Feature / State 的影响

CR-5 已冻结的 `OBSERVED_SECURITY_BARS` 语义天然支持该历史边界：

- MA5/20/60、lag5/20/60 等只消费实际已有 observation；
- 2020 年初不足窗口自然 NULL；
- 不要求 pre-2020 warmup；
- Feature verifier / State verifier 的 PIT 与 deterministic replay 逻辑不需要因此重开。

因此：

```text
CR-5: remains VERIFIED / CLOSED / FREEZE
CR-6: remains START / ACTIVE
```

本次只调整 Provider historical eligibility 与后续 backfill policy，不修改冻结 Feature 公式。

---

## 7. Reviewer Exit Gate

正式 Production Spike 启动前必须满足：

- [x] 旧 `history_start_2018_plus_warmup` core gate 已移除/替换；
- [x] 新 2020+ history validator 有单元/集成测试；
- [x] 2019 及更早缺失不会导致 GO_CORE 失败；
- [x] 2020-01-01 后任一关键连续性缺口仍 fail closed；
- [x] 不为 Feature warmup 拉 2019 数据；
- [ ] Data Sufficiency Matrix 统一使用 2020+；
- [x] Backfill plan 明确禁止 pre-2020；
- [x] DEVLOG / DEVELOPMENT_MANAGEMENT 同步；
- [ ] 三平台 CI 全绿。

---

## 7.1 已完成的代码/测试同步（2026-09-04）

- Core capability 已改为 `history_start_2020`，validator 已改为 `history_coverage_2020_v1`，默认阈值为 `20200101`。
- Probe 的历史覆盖请求起点已改为 `20200101`；证券主数据退市覆盖探测仍保留其独立的历史样本范围，不与本合同混淆。
- 单元测试：`tests/unit/test_spike_validators_v2.py::TestHistoryCoverage2020::test_2020_plus_contract`。
- 集成测试：`tests/integration/test_spike_framework.py::TestHistoryCoverageWiring::test_dry_run_uses_2020_history_contract`。
- Data Sufficiency Matrix、正式账号、生产 B1-B7 和正式 verdict 仍未完成；原因不是代码缺失，而是仓库中没有可用于生产验证的人工确认账号画像和 entitlement 证据。

## 8. 当前正式裁决

```text
Default platform history       2020-01-01 -> present
Pre-2020 routine backfill      FORBIDDEN / NOT REQUIRED
Pre-2020 Feature warmup        FORBIDDEN / NOT REQUIRED
Production history GO gate     2020+ only
CR-5 frozen semantics          unchanged
CR-6 development               continues in parallel
AmazingData Production Spike   may start only after old history gate is updated
```
