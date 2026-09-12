# AmazingData 剩余能力与契约闭环矩阵（2026-09-12）

## 状态与范围

本文件是 Issue #39 最新调度要求的**一次窄范围、非 Production 闭环 PR**。基线为
`main@6ad53a84111fa9b8cc86276d4ed78c9b08f8e469`。本轮没有重新调用 Provider，没有创建
`SpikeRun`，没有运行 `--production`、`--resume` 或 `--verdict`，没有改 Golden、H1、
2020-01-01 基线、旧 run/catalog/verdict 或 Provider 配置。

证据优先使用仓库已有封存字节和本轮实际直连读取的一手交易所/发行人页面。官方页面的
下载字节、HTTP 状态和 SHA-256 见同目录的
[`remaining_capability_truth_20260912.json`](remaining_capability_truth_20260912.json)。
一手页面只提交定位信息和哈希，不把原始网页/PDF重新复制进仓库；Provider 原始返回仍只
留在本地 ignored raw 目录。

调度侧建议为 `COMPOSITE/FALLBACK_SOURCE_REQUIRED`，仅是诊断结论，不是 Provider approval，
也不是新的 Formal 授权。原因是 BJ 映射和 BSE/历史夹具事实已能由一手材料收窄，但
历史 PIT 状态、状态异常行、公司行为字段语义仍没有可授权的 AmazingData 契约。

## 阻断闭环矩阵

| 阻断项 | 一手/封存证据 → 已确认事实 | 分类 | 当前运行时边界 | 对 Formal 的影响 |
|---|---|---|---|---|
| 状态双缺失行 | 封存收据 `status_date_shape`：20,638 行中 8 行同时缺身份和 `TRADE_DATE`，仍带状态/限价字段 | `PROVIDER_CAPABILITY_LIMITATION_STILL_UNRESOLVED` | `canonical_status_view()` 遇该形状失败关闭；不依据相关性跳过 | 历史状态语义仍阻断 |
| 退市 PIT 语义 | `get_stock_basic` 返回 `IS_LISTED/LISTDATE/DELISTDATE`；SDK 签名没有 as-of 参数，也没有语义文档；`hist_code_list` 只有 membership | `PROVIDER_PIT_SEMANTICS_UNRESOLVED` | 不从 code-list 合成 `IS_LISTED` 或退市日期 | B2/退市 Golden 仍阻断 |
| BJ old/new mapping | Provider 封存观察为 248 行；BSE 官方 mapping 表第 242 行为“贝特瑞 / 2020/7/27 / 835185 / 920185”，并说明平移公司的日期是原精选层挂牌日期 | `FIRST_PARTY_MAPPING_FACT_BOUND_BUT_GOLDEN_CONTRACT_NOT_MET` | 仅新增脱敏 truth bundle；不新增 Golden case，不改期望值 | mapping gate 仍未 ready |
| BSE `835185.BJ` 状态 | Provider 对 2022 全年返回 0 行、1 个空表；BSE 官方规则说明 2021-11-15 生效且精选层公司上市时间连续计算；官方 2022 报告使用代码 835185 | `NOT_INAPPLICABLE_PROVIDER_HISTORICAL_STATUS_COVERAGE_OR_SEMANTICS_LIMITATION` | 空响应不能变成“不适用”或 PASS | BSE 历史状态仍阻断，需 composite/fallback |
| 公司行为 | Dividend 123 行/50 行缺 `DATE_EX`，相关性集中在进度 1/2/12；Right issue 当前 6 行全有日期，但旧封存材料有历史缺失观察；SDK 无字段语义文档 | `PROVIDER_CORPORATE_ACTION_FIELD_SEMANTICS_UNRESOLVED` | 任一必需日期缺失均失败关闭；事件存在不等于连续性 PASS | 公司行为连续性仍阻断 |
| `300104.SZ` fixture | 深交所 2020-05-14 原文明确：300104 自 2019-05-13 暂停上市，2020-05-14 决定终止上市，2020-06-05 进入退市整理期；Provider 目标窗口 0 bars、600519 控制 7 bars | `INAPPLICABLE_FOR_2020_BASELINE` | 不把目标空 bars 归因成 Provider 覆盖失败，不放宽全局基线 | 目标夹具延期，history_start_2020 仍未闭合 |

## BJ 最小真值包

本轮只绑定一个足够说明 old/new 关系的独立事实，不把它误称为 Golden 通过：

```text
贝特瑞 | former Selected Layer listing date: 2020-07-27 | OLD_CODE: 835185 | NEW_CODE: 920185
source: https://www.bse.cn/service/code_mapping.html, table row 242
```

这解决的是“是否有一手 mapping 事实”问题，不解决项目现有 `golden_bj_mapping` 的
Golden case、人工审阅和 evidence-contract 要求。现有 Golden/H2 文档已经把该类行标记为
延后；因此本轮不修改 `golden_cases`、manifest、阈值或期望值。

## BSE 空历史响应的归因

结论不是“835185 在 2022 不适用”。一手 BSE 规则和 2022 发行人报告至少绑定了：

1. BSE 自 2021-11-15 起承接精选层平移公司，并连续计算上市时间；
2. 贝特瑞的 old code、new code、原精选层挂牌日期以及 2022 年 BSE 报告代码。

因此，Provider 对 `835185.BJ` 的成功空表不能被解释为不适用；它最多说明该 Provider
历史状态端点的覆盖、路由或语义仍不足以支撑 Formal。没有 Provider 契约证明空表语义前，
运行时继续把它作为 unresolved/fail-closed。

## 2020 历史夹具处置

`300104.SZ` 不是合适的通用 2020 基线交易夹具：深交所一手公告证明它早在 2019-05-13
已经暂停上市。其 `hist_code_list` membership 不能反证可交易性，Provider 0 bars 也不能
单独证明覆盖缺失。

提出 `601558.SH` 为替代候选，理由是：

- 上交所摘牌公告绑定代码 601558 和 2020-07-02 摘牌日期；
- 上交所《统计年鉴（2021卷）》的 2020 统计在“主板A股十大跌幅股票”列出 601558 的
  上年收盘、本年收盘和跌幅，说明它是明确的历史交易证券。

这仍不是对 Provider 首个适用交易日的证明。候选状态保持 `PROPOSED_NOT_ACTIVATED`；在
没有单独绑定精确首个适用 2020 交易日并完成最小 Provider bar 检查前，不替换通用夹具，
不改全局 baseline，也不把 `history_start_2020` 投影成 PASS。

## 下一道门

- 独立 Reviewer 逐项核对 JSON 中的官方 URL、下载状态、字节哈希、摘录定位和分类；特别核对“BSE 空表不是不适用”和“300104 是夹具不适用”这两个方向相反的结论。
- 如需把 `835185/920185` 加入 `golden_bj_mapping`，项目管理者必须另开符合现有 Golden/evidence/human-review 合同的变更；本 PR 不代替人工审阅。
- 如需激活 `601558.SH`，先补精确首个适用交易日和 Provider bar 证据；失败则继续保持 deferred，不放宽基线。
- 未解决的 PIT、状态 shape、公司行为语义需 composite/fallback source 或正式 SDK 契约；不能靠再次观察相同返回、相关性过滤或新建 Formal run 绕过。

### 调度侧推荐

`COMPOSITE/FALLBACK_SOURCE_REQUIRED`

该字符串只表示下一阶段需要复合/回退来源来完成未决语义，**不构成 Production 授权**，也
不授权第三次 Formal、回填、策略扩展或生产化。
