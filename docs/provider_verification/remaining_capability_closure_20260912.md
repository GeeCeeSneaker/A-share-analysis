# AmazingData 剩余能力与契约闭环矩阵（2026-09-12）

## 状态与范围

本文件是 Issue #39 最新调度要求的**一次窄范围、非 Production 闭环 PR**，并包含审阅者
授权的 BSE 当前代码归因 delta。基线为
`main@6ad53a84111fa9b8cc86276d4ed78c9b08f8e469`。本轮仅新增 1 次单证券、无重试的
`920185.BJ` 历史状态调用；没有创建 `SpikeRun`，没有运行 `--production`、`--resume` 或
`--verdict`，没有改 Golden、H1、2020-01-01 基线、旧 run/catalog/verdict 或 Provider 配置。

证据优先使用仓库已有封存字节和本轮实际读取的一手交易所/发行人页面。官方页面的
HTTP 状态、表示形式、字节数和 SHA-256 见同目录的
[`remaining_capability_truth_20260912.json`](remaining_capability_truth_20260912.json)。
一手页面只提交定位信息和哈希，不把原始网页/PDF重新复制进仓库；Provider 原始返回仍只
留在本地 ignored raw 目录。

调度侧建议为 `COMPOSITE/FALLBACK_SOURCE_REQUIRED`，仅是诊断结论，不是 Provider approval，
也不是新的 Formal 授权。原因是 BJ 映射和 BSE/历史夹具事实已能由一手材料收窄，但
旧 BSE 空结果已被当前代码路由问题重新归因；历史 PIT 状态、状态异常行、公司行为字段
语义仍没有可授权的 AmazingData 契约。

## 阻断闭环矩阵

| 阻断项 | 一手/封存证据 → 已确认事实 | 分类 | 当前运行时边界 | 对 Formal 的影响 |
|---|---|---|---|---|
| 状态双缺失行 | 封存收据 `status_date_shape`：20,638 行中 8 行同时缺身份和 `TRADE_DATE`，仍带状态/限价字段 | `PROVIDER_CAPABILITY_LIMITATION_STILL_UNRESOLVED` | `canonical_status_view()` 遇该形状失败关闭；不依据相关性跳过 | 历史状态语义仍阻断 |
| 退市 PIT 语义 | `get_stock_basic` 返回 `IS_LISTED/LISTDATE/DELISTDATE`；SDK 签名没有 as-of 参数，也没有语义文档；`hist_code_list` 只有 membership | `PROVIDER_PIT_SEMANTICS_UNRESOLVED` | 不从 code-list 合成 `IS_LISTED` 或退市日期 | B2/退市 Golden 仍阻断 |
| BJ old/new mapping | Provider 封存观察为 248 行；BSE 官方 mapping 表第 242 行为“贝特瑞 / 2020/7/27 / 835185 / 920185”，并说明平移公司的日期是原精选层挂牌日期 | `FIRST_PARTY_MAPPING_FACT_BOUND_BUT_GOLDEN_CONTRACT_NOT_MET` | 仅新增脱敏 truth bundle；不新增 Golden case，不改期望值 | mapping gate 仍未 ready |
| BSE 旧代码状态 | 封存的 `835185.BJ` 请求为 0 行；BSE 2025 代码切换公告要求 2025-10-09 起查询/业务使用新代码；同窗口单次 `920185.BJ` 请求返回 242 行 | `CODE_MIGRATION_REQUEST_ROUTING_REMEDIATION_REQUIRED` | facade 按输入原样传递；当前运行时调用方必须先解析官方 old/new mapping；旧收据保持不可变 | 不是 Provider 历史覆盖失败的证据；当前代码路由回归需先收口，PIT/状态语义仍阻断 Formal |
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

## BSE 旧代码结果的归因与当前代码 delta

上一版封存收据中的 `835185.BJ` 结果保持原样：请求窗口为 2022 全年，返回 0 行、1 个
空表，request/evidence hash 也不改写。审阅者授权的唯一 delta 是用同一窗口、同一端点、
无重试查询 `920185.BJ`；结果只写入脱敏锚点，raw 仍留在本地 ignored 目录：

| 请求 | request id | rows / table | evidence hash |
|---|---|---:|---|
| 封存旧代码 `835185.BJ` | `86d2e9dc-c731-4104-b490-7ee3183dee3b` | 0 / `835185.BJ` | `c024ff9f…a2a8179e` |
| 当前代码 `920185.BJ` | `67f449d0-4c66-4bb2-bafe-e0cddaf8dcab` | 242 / `920185.BJ` | `cb756dc0…ed619a81` |

BSE [官方 mapping 表](https://www.bse.cn/service/code_mapping.html) 将贝特瑞的 `835185`
绑定到 `920185`；[2025-09-12 代码切换公告](https://www.bse.cn/important_news/200026735.html)
进一步说明，自 2025-10-09 起存量股票的交易委托、行情查询和业务办理使用切换后的新代码。
因此，旧空表应分类为**代码迁移/请求路由整改所需**，不能再作为 Provider 历史覆盖不足的
证据，也不能回写成“不适用”或 PASS。

本次最小运行时防回归措施是：定向 capability probe 的 BSE 状态请求改用 `920185.BJ`，
并以单元测试锁住该当前代码。`get_history_stock_status_exchange()` 继续保持透明的
request-faithful 行为，不在 facade 内隐式调用 mapping 端点或偷偷改写请求；需要查询旧代码
的调用方必须先取得并应用官方 mapping，再把当前代码传入 facade。当前 242 行只证明请求
路由得到非空结构化返回，不证明 status 字段的历史 PIT/业务语义已获 Provider approval。

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

- 独立 Reviewer 逐项核对 JSON 中的官方 URL、HTTP 状态、表示形式、字节哈希、摘要定位和分类；特别核对“旧 BSE 空表是代码路由问题”和“300104 是夹具不适用”这两个方向相反的结论。
- 如需把 `835185/920185` 加入 `golden_bj_mapping`，项目管理者必须另开符合现有 Golden/evidence/human-review 合同的变更；本 PR 不代替人工审阅。
- 如需激活 `601558.SH`，先补精确首个适用交易日和 Provider bar 证据；失败则继续保持 deferred，不放宽基线。
- 未解决的 PIT、状态 shape、公司行为语义需 composite/fallback source 或正式 SDK 契约；不能靠再次观察相同返回、相关性过滤或新建 Formal run 绕过。若需扩大 BJ 代码解析到生产入口，必须另行设计可审计的 mapping 输入/缓存与回归合同。

### 调度侧推荐

`COMPOSITE/FALLBACK_SOURCE_REQUIRED`

该字符串只表示下一阶段需要复合/回退来源来完成未决语义，**不构成 Production 授权**，也
不授权第三次 Formal、回填、策略扩展或生产化。
