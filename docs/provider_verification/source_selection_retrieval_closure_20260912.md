# 来源选择 / 检索闭环矩阵（2026-09-12）

## 结论与范围

本文件对应 Issue #39 合并 PR #47 后唯一获准的窄范围闭环，基线是
main@538bf8ea1f62cac4461215ac316484acf078b09a。它是设计和决策记录，不是运行时实现；
不修改 source-policy-v1、Provider facade、Golden/H1、全局 2020 baseline、旧封存产物或
Formal/Production 状态。

最小组合只保留五类实际需要的来源：

1. 交易所公告 / 披露文档：生命周期和 PIT 事件；
2. 交易所公司行为记录：分红、送转、配股及日期；
3. BSE mapping / cutover 文档：北交所身份和请求路由；
4. 交易所日历 / 统计文档：601558.SH 的首个适用 2020 session；
5. AmazingData：已经接受的数值限价观察和日线观察。

本阶段明确不选 CNINFO 原始发行人文档 transport，也不选 SSE/SZSE/BSE 直接行情或处理后
市场数据。若已选来源不能证明事实，就保持 UNKNOWN / deferred，不静默增加来源。

## 一、来源类别选择与检索合同

以下每一行都写明：实际用途、条款或授权依据、项目决策、可重放定位、表示形式、缓存版本、
失败行为、最小留存物和能力影响。STILL_UNRESOLVED 是当前事实，不是默认许可。

| 来源类别 | 选择状态 / 能力 | 项目用途（检索、留存、解析、派生、再分发） | 条款 / 授权依据与项目决策 | 可重放检索与稳定身份 | 表示、缓存与失败关闭 | 最小留存物 |
|---|---|---|---|---|---|---|
| exchange_announcement_disclosure_document | SELECTED_PRIMARY；lifecycle、historical status、history fixture applicability | 只取 SSE/SZSE/BSE 官方事件文档；留抽取事实、manifest、hash；解析事件和有效日；生成 PIT 区间及夹具生命周期输入；无外部再分发 | SSE/SZSE 法律声明与 BSE 官方公告入口；STILL_UNRESOLVED，需逐 venue 决定自动读取、留存、解析、内部/派生使用 | 官方列表页只做入口，必须跟到公告/文档身份；身份优先用官方 announcement/record ID，否则用 canonical URL + immutable hash + 定位符 | raw bytes、official PDF、rendered_dom_index_only 分开标记；每次 retrieval_id 内容寻址，不覆盖旧版本；HTTP/WAF、动态响应不完整、缺有效日/身份/同层冲突均 fail closed | venue、代码、事件类型、披露/有效日、session、原因、官方 ID、URL、定位、表示、抓取/可用时间、字节数、SHA-256、解析器指纹、许可决定 |
| exchange_corporate_action_record | SELECTED_PRIMARY；corporate actions | 只取官方公司行为记录；留事件事实和 provenance/hash；解析 record/ex/effective、现金、比例等；生成事件区间；无外部再分发 | SSE/SZSE/BSE 官方公司行为入口和各自法律声明；STILL_UNRESOLVED；若 artifact 含处理价，另走 market-data 类 | SSE 股息页、SZSE 月度表、BSE 官方公告；优先官方 record/announcement ID；无 ID 时需 table version + row locator + row hash，稳定性不足则阻断 | dynamic table 不得冒充 raw；retrieval_id + content hash 版本化；缺日期/事件类型、身份不稳、同事件冲突或出现未获许可的处理价均 fail closed | 事件类型、代码、官方 ID、record/ex/effective/payment/listing 日期、所有调整算术输入、URL/定位、表示、hash、available_at、许可决定 |
| bse_mapping_cutover_document | SELECTED_PRIMARY；BJ mapping | 只用于 caller/ingest 身份解析和请求路由；留最小 mapping 事实及版本化 provenance/hash；不改写 facade 请求；无外部再分发 | BSE mapping 表、代码切换和准备公告；STILL_UNRESOLVED，需决定自动读取、缓存、解析和内部路由使用；不等于 BSE 行情许可 | mapping 表行 + 官方 notice number/date；身份为 old/new code + 官方表/公告身份 + 行/段落定位；挂牌日与 mapping 有效期分开 | raw/PDF/rendered DOM 分开；BSE WAF 时 DOM 只能标 DOM；snapshot 不覆盖，policy 单独版本化；缺 old/new、有效区间冲突、隐式 facade 映射均阻断 | old/new code、名称、明确给出的原挂牌日、明确有效区间、行/段落定位、URL、表示、抓取/可用时间、hash、mapping policy 版本、许可决定 |
| exchange_calendar_or_statistics_document | SELECTED_SUPPORTING；只限 SSE 601558 首轮 | 取最小官方 session 和统计身份；留首 session 事实及 hash；解析日历/候选身份；与独立生命周期文档 join 后生成 fixture applicability；无外部再分发 | SSE 日历/年鉴入口和 SSE 法律声明；STILL_UNRESOLVED，需决定该最小用途 | 官方 calendar publication/document identity + session；yearbook 用 document/page/table/row 定位；禁止硬编码市场首个开市日 | raw/PDF/DOM 诚实区分；按官方身份和 hash 版本化；无精确 session、被阻断或仅凭日历推断可交易性均 deferred | 候选代码、生命周期引用、日历 session、精确首 session（仅在公式通过后）、文档/页表定位、表示、hash、available_at、fixture 原因、许可决定 |
| amazingdata_provider_observation | SELECTED_SUPPORTING；historical status 数值字段、history fixture 日线 | 保留已有 facade 合同：status 用真实日期窗口、is_local=false；日线显式 period=10008；留规范化观察和 hash；解析前做身份/日期/形状校验；不再分发 raw | 本地 AmazingData 1.1.9 SDK surface 与已接受 facade 合同；STILL_UNRESOLVED，需 vendor terms/entitlement 与项目用途决定 | provider + method + normalized symbol/code + date window + SDK args + request hash；返回表/key、schema/payload/evidence hash；无限定身份/日期不接收 | raw provider 只留本地 ignored；repo 只留脱敏事实/hash；请求证据不可变；SDK/transport/timeout、双缺失、未知进度、畸形形状、用观察补一手语义均 fail closed | provider/method、请求身份、窗口、代码、接受字段/隔离分类、形状结果、schema/payload/evidence hash、抓取/可用时间、SDK/runtime 版本、语义限制、许可决定 |
| cninfo_original_issuer_document_transport | NOT_SELECTED；本阶段无能力必需 | 本阶段不自动检索、留存、解析或派生 | 有官方入口，但不作本阶段授权判断；NOT_SELECTED。若以后需要，另作 transport 决策 | 无 canonical locator / request；exchange 来源不足时保持 UNKNOWN，不静默加入 CNINFO | NOT_APPLICABLE；不以 CNINFO index/API 作为独立语义裁判 | 本阶段无留存物 |
| exchange_quotation_or_processed_market_data | NOT_SELECTED；本阶段无能力必需 | 不读取 SSE/SZSE/BSE 直接行情、日线或处理价；不留存或派生 | BSE 官方材料明确行情信息为许可使用；SSE/SZSE 也需按用途审查；本阶段不选、不请求许可 | 无 canonical locator / request；未来若确实需要，必须先作 venue-specific terms/license 决定 | NOT_APPLICABLE；不由公告、mapping、日历或统计页推断行情授权；缺处理价/交易所 bar 时保持 blocked | 本阶段无留存物 |

“公开可见”不是“项目已经获准自动抓取、长期存储、解析或产生衍生数据”。选择状态是合同
状态，不是来源事实的 PASS。

## 二、五项能力决策矩阵

| 能力 | 实际选中的来源类别 | 必须绑定的事实 | PIT / 冲突 / 失败关闭 | 实现影响与当前阻断 |
|---|---|---|---|---|
| security lifecycle / listing PIT | exchange_announcement_disclosure_document | exchange、code、事件类型、披露/有效日、有效 session、原因、官方 ID、URL/hash | 事件有效区间覆盖目标 session 且 available_at <= as_of 才可选；当前 snapshot、code-list 和事件缺失不是历史反证；同层冲突为 SOURCE_CONFLICT | 未来只加窄 lifecycle adapter + interval builder；当前被文档许可、历史覆盖、动态/WAF 检索合同阻断 |
| historical status by day | 一手生命周期文档 + amazingdata_provider_observation；另用版本化 trading-rule SoR | MARKET_CODE、TRADE_DATE、ST/停牌字段、限价字段、生命周期事件、规则 ID/version | ST/停复牌来自事件区间；数值限价仅接受合格 AmazingData 行和适用 rule version；双缺身份/日期、未知进度、规则不匹配继续 quarantine/fail closed；不选 direct exchange market-data | 未来加窄 status partition adapter，保留现有 ProviderRowShapeError；当前被两类用途许可、历史覆盖和 provider 语义边界阻断 |
| corporate actions | exchange_corporate_action_record | 事件类型、代码、官方 ID、record/ex/effective/payment/listing 日期、现金和比例 | available_at <= as_of；相邻 session 不是自然日；缺日期/事件类型或同事件冲突为 UNKNOWN/阻断；调整参考价显式延期，不从未选 market-data 类补 | 未来加窄 parser + calendar join；不按 progress code 相关性过滤；当前被公司行为记录许可/覆盖和稳定身份阻断 |
| BJ identity mapping | bse_mapping_cutover_document | old/new code、名称、原挂牌日、明确 mapping 有效期、行定位、hash、policy version | 只按明确有效区间；挂牌日不推导 mapping 有效期；BSE WAF/缺区间/冲突阻断；facade 不隐式改写 | 未来在 caller/ingest 加可审计 resolver；不创建 Golden PASS；当前被 BSE 文档用途决定和可重放表示合同阻断 |
| history fixture | exchange_announcement_disclosure_document + SSE exchange_calendar_or_statistics_document + amazingdata_provider_observation 日线 | listing/suspension/delisting、calendar session、精确首 session、bar trade_date、最小 bar 字段/身份 | first_applicable_session = min(session >= 2020-01-01 且已上市且不在官方停牌区间)；生命周期和日历先 join，再验最小 bar；不选交易所行情 fallback | 300104.SZ=INAPPLICABLE_FOR_2020_BASELINE；601558.SH=PROPOSED_NOT_ACTIVATED；需首 session + 最小 bar，失败后才同法评估 600068；不改全局 baseline |

### 未选择的两类来源

- CNINFO transport 本阶段不必要；交易所一手来源不足时保持 UNKNOWN，避免悄悄引入另一套条款和完整性假设。
- 交易所行情 / 处理后市场数据本阶段不必要；AmazingData 数值/日线观察承担已定义数值部分，一手文档承担语义部分。BSE 行情信息的许可不能从公开公告或 mapping 继承。

## 三、仍需项目管理者作出的具体外部决定

1. 对四类已选第一方文档分别确认：自动读取、原始留存、解析、内部使用、派生事实和再分发状态；范围必须逐 venue、逐 source class。
2. 对 AmazingData status 数值和 daily-bar 观察确认 vendor terms/entitlement，以及本地证据留存和内部派生事实的项目用途。
3. 接受每个 venue 的可重放检索测试：稳定 ID、动态表参数、raw/PDF/rendered-DOM 表示、缓存版本、HTTP/WAF 失败行为和 2020+ 覆盖。BSE 只能把浏览器结果标成 rendered_dom。
4. 单独绑定 601558.SH 的精确首个适用 2020 session 和最小有效日线；失败后按同一合同评估 600068.SH，不放宽全局基线。

这些决定完成并经独立 Reviewer 接受后，才可另开窄实现 PR（适配器、新 source-policy
版本、lineage 和回归测试）。本 PR 不实现、不激活、不运行 Provider 或 Formal。

## 四、调度侧推荐

SOURCE_SELECTION_STILL_UNRESOLVED
