# 复合 / 兜底来源记录契约（2026-09-12）

## 结论先行

这是 Issue #39 要求的**来源选择 / 设计闸门**，基线为
`main@661dddfe7bba2f8ff13a3f7512bde4e1a15db383`。本 PR 的状态是
`DESIGN_ONLY_NOT_ACTIVE`，调度侧推荐是
`SOURCE_SELECTION_STILL_UNRESOLVED`。

推荐仍未达到 `COMPOSITE_CONTRACT_READY_FOR_IMPLEMENTATION`，原因不是没有候选
来源，而是候选来源还没有同时满足完整历史覆盖、可重复机器读取、PIT/as-of、证据
留存和许可/使用兼容性。交易所页面的官方身份和公开字段可以作为下一步合同的基础，
但不能把“页面存在”写成“生产接口已经可用”。

本文件只定义未解决的五个领域，不修改 `source-policy-v1`、Provider facade、
Golden/H1、全局 2020 基线、旧 Formal/run/catalog/verdict，也不启动 Production、
Formal、backfill 或策略工作。机器可校验版本见
[`composite_fallback_source_contract_20260912.json`](composite_fallback_source_contract_20260912.json)。

## 一、来源分层与最小候选集合

| 层级 | 含义 | 处理原则 |
|---|---|---|
| `OFFICIAL_EXCHANGE_PROCESSED_OR_DECISION` | 交易所发布的处理结果或交易所决定，直接给出事件、有效日或处理后参考价 | 对同一事实具有最高语义优先级 |
| `OFFICIAL_EXCHANGE_OR_ISSUER_EVENT_DOCUMENT` | 交易所或发行人正式公告，原文直接陈述事件和日期 | 可作为事件证据；发行人文件须保留原文身份 |
| `AMAZINGDATA_VALID_NORMALIZED_OBSERVATION` | 形状合格、保留 Provider 身份和证据链的观察 | 可承担已定义的数值观察，不自动补足一手语义 |
| `CNINFO_TRANSPORT_OF_ORIGINAL_DOCUMENT` | 发行人原始披露的检索 / 传输通道 | 只作 transport，不能因索引存在而提升语义级别 |

候选来源按能力复用交易所的一手入口，尽量不引入第三方聚合器：

| 来源 ID | 作用 | 已观察到的可重复性边界 |
|---|---|---|
| `exchange_lifecycle_events` | SSE、SZSE、BSE 的上市、停牌、复牌、风险警示、终止 / 恢复上市事件 | SSE/SZSE 入口在本次公开检查返回 HTTP 200，但部分表格动态加载；BSE 直接非浏览器读取遇到 HTTP 403，已有浏览器渲染 DOM 不能冒充 raw bytes |
| `exchange_corporate_action_records` | 分红、送股、转增、配股及 record/ex-date / 参考价 | SSE 表格动态；SZSE 有官方月度分红派息配股表；BSE 仍受访问和许可闸门约束 |
| `bse_code_mapping` | BSE 新旧代码身份解析 | 官方 mapping 与切换公告已绑定，但有效区间、缓存版本和生产留存政策未冻结 |
| `cninfo_original_disclosure_transport` | 找到发行人原始公告及定位 | 页面可访问不等于完整性或时效性保证，也不独立决定事实 |
| `amazingdata_normalized_observation` | 已验证形状的 Provider 观察 | SDK 没有被项目证实的 PIT / 进度码 / 公司行为语义文档，异常行继续 fail-closed |
| `exchange_calendar_and_history_fixture` | 交易所日历 + 生命周期适用性 + 日线证据 | 601558 尚未绑定精确首个适用 session 和最小 bar，600068 只是备用候选 |

## 二、按来源类别拆分的许可 / 使用兼容性

上一版把 SSE、SZSE、BSE 的法律 / 数据边界概括成一个 venue 级结论，粒度不够，
不能直接供未来 `source-policy` 选择。本节按**实际来源类别**拆分；所有状态都仍是
未决，不表示项目已经取得任何许可。

| source class | 适用来源 | 官方材料当前能支持的事实 | 明确不能推断的事项 | license_decision |
|---|---|---|---|---|
| `exchange_announcement_disclosure_document` | SSE / SZSE / BSE 公告、上市、停复牌、退市和发行人事件原文 | [SSE 法律声明](https://www.sse.com.cn/home/legal/)与 [SZSE 法律声明](https://www.szse.cn/application/laws/)说明在遵守法律和声明前提下可基于非商业目的浏览 / 下载，并对牟利型拷贝、存储、电子抓取、转载等设有书面许可边界；BSE 公共文档可见性单独记录 | 公共页面可见、HTTP 200 或能下载，不等于允许本项目自动抓取、长期保存、解析、发布或生成派生数据；BSE 文档可见性不等于 BSE 行情许可 | `PROJECT_DECISION_REQUIRED` |
| `bse_mapping_cutover_document` | BSE 新旧代码 mapping、代码切换和准备公告 | 可作为身份解析和请求路由的官方文档证据 | 不得把 mapping / cutover 文档归类为 BSE `行情信息`，也不得由此推断 BSE 行情或处理价数据已获许可 | `PROJECT_DECISION_REQUIRED` |
| `exchange_corporate_action_record` | SSE dividend/history、SZSE 月度分红派息配股表、BSE 公司行为公告 / 处理记录 | 可按实际记录绑定事件类型、record/ex-date 等字段 | 不得把公司行为文档自动等同于行情授权；若同一 artifact 含报价 / 处理价字段，必须另外走 market-data 类别 | `PROJECT_DECISION_REQUIRED`（SSE/SZSE 还需按条款复核） |
| `exchange_quotation_or_processed_market_data` | SSE / SZSE / BSE 行情、日线、处理后价格或参考价数据 | 只说明候选的事实来源类别；[BSE 行情许可通知](https://www.bse.cn/important_news/200011008.html)和[授权指南](https://www.bse.cn/application/guide.html)明确行情信息实行许可使用模式 | BSE 公共公告、mapping、日历或统计页的访问权，不能替代行情许可；SSE/SZSE 公共下载条款也不能自动替代项目用途审查 | `BLOCKED_PENDING_PER_VENUE_LICENSE_DECISION`；BSE=`LICENSE_REQUIRED`，SSE/SZSE=`TERMS_REVIEW_REQUIRED` |
| `cninfo_original_issuer_document_transport` | CNINFO 公共披露入口 / 数据服务作为发行人原文传输通道 | 可帮助定位并传输发行人原文，前提是保留原始身份、日期、hash 和 locator | CNINFO 索引 / API 不是独立语义裁判，也不自动授权本项目自动抓取、保存或派生使用 | `PROJECT_DECISION_REQUIRED` |
| `amazingdata_provider_observation` | 本地 AmazingData SDK 返回的 Provider 观察 | 仅在供应商条款和项目用途获准、且行形状有效时保留观察 | Provider 行形状不提供交易所一手授权，也不解决未文档化的 PIT / 进度码语义 | `VENDOR_TERMS_AND_PROJECT_DECISION_REQUIRED` |
| `exchange_calendar_or_statistics_document` | 交易所日历、年鉴、统计文档 | 可绑定 session 或最低限度的历史统计事实 | 不得从日历 / 年鉴页面推断行情或处理价数据许可 | `PROJECT_DECISION_REQUIRED` |

### 激活规则

未来 source-policy 必须为**每个实际选中的 source class**记录独立的许可 / 使用
决定，至少覆盖自动读取、原始留存、解析、内部使用、对外发布和派生 artifact。任何
一个被选中的类别仍为 `PROJECT_DECISION_REQUIRED`、`TERMS_REVIEW_REQUIRED`、
`LICENSE_REQUIRED` 或 `BLOCKED_PENDING_VENUE_LICENSE_DECISION` 时，不得激活对应
fallback。尤其是：

- BSE 公告 / mapping / cutover 文档的决定，不能继承到 BSE `行情信息`或处理后价格；
- SSE/SZSE 的非商业网页浏览 / 下载边界，不能自动等同于项目生产化抓取和派生使用；
- CNINFO 仅是 transport，不能提升为独立来源或绕过原始文档的许可边界。

## 三、五项来源矩阵

下面每一行严格对应调度要求的
`capability -> primary source -> fallback/first-party source -> exact fields/facts -> PIT rule -> conflict precedence -> evidence contract -> implementation impact`。

| capability | primary source | fallback / first-party source | exact fields / facts | PIT rule | conflict precedence | license / usage boundary | evidence contract | implementation impact |
|---|---|---|---|---|---|---|---|---|
| security lifecycle / listing PIT | `exchange_lifecycle_events` | CNINFO 只传输发行人原文；AmazingData `stock_basic` 只作佐证 | `exchange`、`security_code`、事件时证券简称、`LIST/SUSPEND/RESUME/RISK_WARNING_ADD/RISK_WARNING_REMOVE/DELIST/RELIST`、披露日、有效日、有效 session、原因、公告 ID、文档 URL、文档 SHA-256 | 建立事件台账和有效区间；只有 `effective_session/interval` 覆盖目标日且 `available_at <= as_of` 才能选中。当前快照、当前 code-list、事件缺失都不能当作历史反证 | 交易所处理结果 / 决定 > 交易所或发行人正式事件原文 > 合格 AmazingData 观察 > CNINFO transport；同层冲突进入 `SOURCE_CONFLICT` 并阻断 | `exchange_announcement_disclosure_document`；SSE/SZSE 条款和 BSE 文档使用决定均待项目确认，BSE 文档决定不延伸至行情信息 | 保存 canonical URL、retrieval ID、UTC 抓取时间、HTTP 状态、表示形式、字节数、SHA-256、稳定公告 / 记录 ID、事件 key、有效日 / session、`available_at`、解析器指纹、原文定位、许可决定；`rendered_dom` 不得标作 raw | 新增窄范围 lifecycle evidence adapter + interval builder；保持 Parquet SoR 和 lineage；本 PR 不改 `source-policy-v1` |
| historical status by day | 交易所生命周期事件 + 版本化 trading-rule SoR | 合格 AmazingData 行承担数值限价观察；CNINFO 仅补原文事件细节 | `MARKET_CODE`、`TRADE_DATE`、`IS_ST_SEC`、`IS_SUSP_SEC`、`HIGH_LIMITED`、`LOW_LIMITED`、高 / 低限价比例、生命周期事件类型和有效 session、交易规则 ID / version | ST / 风险警示 / 停复牌来自事件台账；数值限价字段仅在行形状合格且使用 trade_date 对应规则时采用；所有来源须 `available_at <= as_of`；双缺身份 / 日期、未知进度和规则不匹配继续隔离 / fail-closed | 交易所处理事实优先；事件原文次之；合格 AmazingData 只承担无更高层处理事实的数值观察；transport 最低；官方与 Provider 不一致时阻断，不 last-write-wins | 生命周期文档、AmazingData 观察和可能的 processed market-data artifact 分别决策；BSE 公告 / mapping 的公共访问不能替代行情许可 | 除来源身份、交易日、available、raw / evidence hash 外，记录规则版本和行形状校验；禁止以“看起来像汇总行”静默跳过缺失身份 / 日期 | 新增 status partition adapter，不做通用 Provider 抽象；保留 `ProviderRowShapeError` / quarantine；未来 fallback 必须新建 source-policy 版本 |
| corporate actions | 交易所处理后的公司行为记录：SSE dividend/history、SZSE 月度分红派息配股表、BSE 正式记录 / 公告 | 发行人实施公告经 CNINFO 传输；AmazingData 只作佐证 | 事件类型、交易所、证券代码、公告 ID、`record_date`、`ex_date`、派付日 / 新股上市日、每股现金、送股 / 转增比例、配股比例 / 价、募集资金、调整后参考价、URL、定位、文档 hash | `available_at <= as_of`；以官方 record / ex-date / effective session 解释事件；T-1/T/T+1 是相邻交易 session，不是自然日；缺必需日期或事件类型未知即 UNKNOWN | 交易所处理结果（含 ex-date / reference price） > 交易所 / 发行人原文 > 合格 AmazingData > CNINFO transport；同事件冲突阻断并要求版本化更正 | `exchange_corporate_action_record` 与发行人文档分别决策；若 artifact 含报价 / 处理价，另走 `exchange_quotation_or_processed_market_data`，BSE 必须单独满足 license gate | 必须留事件类型、所有调整算术输入、record/ex/effective session、定位、hash、available、按类许可决定；原始事件存在但缺日期不能通过连续性 | 新增公司行为解析器和交易日历 join；不得按观察到的进度码相关性过滤异常行；仍需解决自动留存许可 |
| BJ identity mapping | BSE 官方 mapping 表 + 代码切换公告 | BSE 上市 / 公告；AmazingData mapping 仅佐证 | old/new code、证券名、原精选层挂牌日、mapping valid from/to、exchange、源表行定位、URL、artifact hash、retrieved_at | 原挂牌日与 mapping 有效期分开；当前运行时仅按官方记录的 2025-10-09 切换区间选 mapping，且 snapshot `available_at <= as_of`；不能从挂牌日推断所有历史有效期 | BSE mapping + cutover > BSE listing / announcement > AmazingData；缺区间或冲突直接阻断 | `bse_mapping_cutover_document`；公共 mapping / cutover 文档使用决定独立于 BSE 行情信息 license | 版本化 mapping snapshot、代码对、有效区间、稳定行定位、artifact hash、检索 / available 时间、mapping policy version；记录原始逻辑 symbol 与解析后的 provider symbol；许可决定按 source class 留存 | 在 caller / ingest 边界加入窄 resolver；facade 继续原样接收已解析 code，不隐藏调用或重写 `code_list`；另建 Golden case 才能形成 mapping PASS |
| history fixture | 官方交易所日历 + listing / suspension / delisting 事件 | 合格 AmazingData 日线；若许可和传输可接受，再用交易所官方日线 / 统计 | exchange、code / provider symbol、listing date、停牌区间、delisting date、calendar session、first applicable session、bar trade_date、最小 bar 字段、bar 来源身份 | `first_applicable_session = min(session >= 2020-01-01 且证券已上市且不在官方停牌区间)`；之后再验证最小 bar；不能把市场首个开市日硬编码成证券适用性 | 交易所日历和生命周期决定 > 交易所市场数据 / 统计 > 合格 AmazingData 日线 | 日历 / 统计文档、AmazingData bar 和交易所行情 / 处理数据分别决策；任何 BSE bar / processed-price 来源不能继承文档或 mapping 决定 | 绑定生命周期、交易日历、精确首 session、最小 bar 数 / 字段、bar 行身份 / hash、available、夹具决定原因和各来源类许可；证明不足就 deferred | 601558 先做精确 session + bar 证明；失败再同样评估 600068；不替换 300104、不放宽全局 2020-01-01 基线 |

## 四、统一 PIT、冲突和证据规则

### 1. `available_at` 是选择条件，不是装饰字段

所有候选来源都必须记录证据何时可被本系统取得，并要求
`available_at <= as_of`。不能用交易日、公告发布日期的午夜或当前系统时间回填
不可证明的可用性。一个后来抓到的历史公告，不能自动成为更早 `as_of` 的可见事实。

### 2. 缺失和冲突默认阻断

以下情况都输出 UNKNOWN / quarantine / `SOURCE_CONFLICT`，而不是猜测或“取最新”：

- 事件没有有效日、session 或稳定身份；
- corporate action 缺少连续性所需的 record/ex-date；
- AmazingData 行同时缺少交换所身份和交易日，或有未知进度语义；
- 同一事件的一手来源互相冲突；
- mapping 没有可证明的有效区间；
- 夹具没有精确首个适用 session 或最小 bar 证据。

官方更正应作为新的、有版本的来源记录进入 lineage，不能原地覆盖旧证据。

### 3. 证据文件与凭据隔离

未来若实现，建议使用内容寻址的本地 ignored evidence tree，例如：

```text
source_evidence/source=<source_id>/retrieval=<retrieval_id>/raw
source_evidence/source=<source_id>/retrieval=<retrieval_id>/manifest.json
```

`manifest.json` 至少包含 source ID、canonical URL、请求 / 查询参数 hash、HTTP
状态、content type、UTC 抓取时间、字节数、SHA-256、表示形式、稳定记录 / 公告 ID、
解析器指纹、HTML selector / PDF 页码 / 表格行定位、event key、effective / available
字段和许可决定。原始 Provider payload、账号密码、Token、Cookie、真实 endpoint、
专有 SDK 和本地 profile 不进入 GitHub。

## 五、事实、判断与仍未验证事项

### 已确认事实

- 仓库当前 `main` 是 `661dddfe…`；PR #46 已合并。Issue #39 明确禁止第三次
  Formal，并要求本次只提交来源契约设计。
- 已有 BSE 官方 mapping 事实把贝特瑞的 `835185` 与 `920185` 关联；这解释了旧
  BSE 空请求需要先做代码路由整改，但尚未形成 `golden_bj_mapping` PASS。
- 现有整改已确认 `300104.SZ` 不适合作为通用 2020 交易夹具；`601558.SH`
  仍是未激活候选。当前文档不改 Golden 或全局基线。
- SSE、SZSE、BSE 都有官方公告 / 上市状态入口；SSE 有停复牌、退市和分红入口，
  SZSE 有公司公告和月度分红派息配股表，BSE 有公告和新旧代码表。
- SSE/SZSE 的网站法律声明与 BSE 的行情许可通知属于不同 source class：前者描述
  非商业网页浏览 / 下载及牟利型 reuse 边界，后者明确 `行情信息` 采用许可使用模式。
  BSE 公告、mapping、cutover 文档另行归类，不能从其公开可见性推断行情许可。

### 合理判断（尚需审阅接受）

- 采用“一手交易所事件台账 + 受约束 AmazingData 数值观察”的分区合同，能够比
  单一 Provider 更接近解决 PIT、状态和公司行为语义，同时保持最小来源集合。
- CNINFO 最适合做原始发行人公告的传输和定位，不适合在交易所处理结果缺失时被
  当作独立语义裁判。
- BJ mapping 应属于 caller / ingest 的可审计身份解析，而不是 Provider facade 的
  隐式副作用；这样能保持请求身份、映射版本和证据一致。

### 暂时无法验证

- 各交易所动态页面是否能按项目需要稳定、完整地重放 2020+ 全历史；BSE 在本环境
  的直接 GET 还会触发 403/WAF。
- 逐类自动保存一手页面 / PDF、解析、内部使用和生成衍生数据是否获得项目所需的
  许可 / 使用授权；尤其是 BSE 行情 / 处理价是否已有授权。
- AmazingData 的 PIT `IS_LISTED`、状态进度码和公司行为字段是否有尚未取得的正式
  SDK 契约。
- `601558.SH` 的精确首个适用 2020 session 与最小日线证据；若失败，`600068.SH`
  也必须重新走同一证明流程。

## 六、下一步工作要求与硬边界

1. 项目管理者先按 source class 对 SSE/SZSE/BSE 公告文档、BSE mapping/cutover、
   交易所行情/处理数据、CNINFO transport 和 AmazingData 分别作出自动读取、留存、
   解析、内部/派生使用的许可 / 合规决定；没有对应决定，不激活 fallback。
2. 为每个 venue 冻结可重复的 retrieval contract：动态表的请求 / 分页 / 记录 ID、
   BSE 浏览器渲染表示形式、原始字节或 DOM 的区分、失败重试和覆盖率检查。
3. 独立 Reviewer 逐项审阅本矩阵和 JSON，特别核对：交易所处理记录与发行人公告
   的优先级、`available_at`、冲突阻断、BSE mapping 有效期、以及 601558/600068
   的 deferred 边界。
4. 只有来源合同接受后，才允许另开实现 PR：窄 adapter、版本化 source policy、
   lineage 和回归测试；实现 PR 仍不得自动启动 Formal。
5. 先完成 601558 的首 session + 最小 bar 证据；若失败，提出 600068 的同等证据，
   但不修改全局 2020-01-01 baseline。

禁止事项：Production、新 Formal SpikeRun、`--resume`、`--verdict`、backfill、
universe sweep、Golden/H1/基线阈值变化、策略工作、facade 内隐式映射、按相关性
过滤异常 Provider 行、用当前 snapshot 伪造 PIT 状态。

## 七、官方参考入口

- [SSE 上市公司公告](https://www.sse.com.cn/assortment/stock/list/info/announcement/)、
  [停复牌信息](https://www.sse.com.cn/disclosure/dealinstruc/suspension/)、
  [退市信息](https://www.sse.com.cn/assortment/stock/list/delisting/)
- [SSE 股息数据](https://www.sse.com.cn/market/stockdata/dividends/dividend/)、
  [SSE 法律声明](https://www.sse.com.cn/home/legal/)
- [SZSE 公司公告](https://www.szse.cn/disclosure/notice/company/)、
  [分红派息配股月度表](https://www.szse.cn/market/periodical/documents/t20041229_521990.html)、
  [SZSE 法律声明](https://www.szse.cn/application/laws/)
- [BSE 新旧代码映射](https://www.bse.cn/service/code_mapping.html)、
  [代码切换公告](https://www.bse.cn/important_news/200026735.html)、
  [行情许可通知](https://www.bse.cn/important_news/200011008.html)、
  [数据使用指引](https://www.bse.cn/application/guide.html)
- [601558 上交所摘牌公告](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20200623_78480676.shtml)、
  [600068 终止上市公告](https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20210909_82957014.shtml)
- [CNINFO 公共披露入口](https://www.cninfo.com.cn/new/commonUrl?url=data%2Fgongkai)、
  [CNINFO 数据服务说明](https://webapi.cninfo.com.cn/notice.html)

### 调度侧推荐

`SOURCE_SELECTION_STILL_UNRESOLVED`

该推荐只表示来源合同还需要许可、覆盖和可重复检索方面的决策；不代表 Provider
失败结论已被替换，也不授权任何 Formal、Production、回填或生产化。
