# A-share-analysis · Trading Rule H1 真值整改与证据封印要求

日期：2026-09-09（Asia/Shanghai）

## 1. 目的与权威性

本文件是当前 Formal Production B1-B7 前置的 Trading Rule H1 权威执行要求。

它补充并覆盖 PR #29 中“直接复核现有 9 条规则后使用 `scripts/rules/review.py` 封印”的解除方案；PR #29 的 preflight 运行事实本身仍然有效。

起始基线：`main@0148ae06cdd7b84709b235476eda7b170ad7e026`。
Reviewer checkpoint：PR #29 review `5148115710`。

当前正式状态：

- reviewed Golden v7：`v7-reviewed-20260908` / REVIEWED 125/125 / 不重新打开；
- AmazingData SDK/runtime/network/auth/query readiness：本轮 preflight 已真实验证；
- Provider-derived as_of_date：`20260908`；
- Formal Production：在创建 `SpikeRun` / `run_id` 前因 ACTIVE trading rules 为 COMPILED fail-closed；
- B1-B7：NOT RUN；
- 正式单次 attempt：未消耗；
- Provider verdict：未产生。

## 2. 为什么不能直接封印当前 9 条

当前 ACTIVE rule candidate：

- `v20260824-compiled`
- dataset hash `dd2219d2383b01d2b8a5019ddf713d36a04f1badbeabe1aeffc7e20fa91ef2d8`
- 9 records
- `review_status=COMPILED`

独立复核发现当前 candidate 至少存在以下 P0 truth gap / error，因此禁止原样 COMPILED -> REVIEWED：

### TR-H1-01 · 主板注册制新股前 5 日缺失

现有规则只有 `MAIN_BOARD_NORMAL` 10%，没有主板注册制后 IPO `FIRST_5_DAYS_NO_LIMIT`。

沪深交易所官方规则均明确：主板首次公开发行上市股票上市后的前 5 个交易日不实行价格涨跌幅限制；此后普通股 10%、风险警示股 5%。

参考官方来源：

- SSE：https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230201_5715605.shtml
- SZSE：https://investor.szse.cn/knowledge/qa/t20230306_599093.html
- SZSE 首批注册制主板上市日：https://www.szse.cn/aboutus/trends/news/t20230404_599697.html

当前规则若不补这一 regime，会让注册制主板新股前 5 日错误解析为普通 10%。

### TR-H1-02 · 创业板改革前 ST 语义错误

当前 `CHINEXT_PRE_REGISTRATION` 使用 `st_state: null` 且统一 10%。

深交所官方说明明确：创业板改革实施前，风险警示股票（ST、*ST）价格涨跌幅限制比例为 5%；改革实施后创业板股票统一为 20%。

参考官方来源：

- https://investor.szse.cn/institute/rules/t20200807_580310.html

必须拆分/重构改革前普通与风险警示语义，禁止把 ANY/10% 原样封印。

### TR-H1-03 · BSE 起始边界错误 / 场所语义混淆

当前 `BSE_LIMIT`：

- `exchange=BJ`
- `effective_from=20201030`

该边界既不是精选层开市日，也不是北交所施行日。

官方事实：

- 新三板精选层 2020-07-27 开市；
- 北京证券交易所规则自 2021-11-15 施行。

参考官方来源：

- 精选层：https://www.neeq.com.cn/m/bse_news/200010652.html
- BSE 上市规则施行：https://www.bse.cn/cxjg_list/200010908.html

Provider-neutral institutional truth 不得把 BSE 成立前的精选层时期直接标成 `exchange=BJ`。若项目确实需要 2020-07-27 至 2021-11-14 的精选层连续性，应在正确的 venue/mapping/universe 语义下单独建模，不得靠错误 BSE effective date 吞并。

### TR-H1-04 · BSE 上市首日不限价规则缺失

北交所官方交易规则明确：普通交易日涨跌幅限制为 30%，向不特定合格投资者公开发行股票上市交易首日不设涨跌幅限制。

参考官方来源：

- https://www.bse.cn/jygl_list/200028217.html

当前 candidate 只有普通 `BSE_LIMIT`，没有 listing-day no-limit regime，必须补齐。

### TR-H1-05 · 主板旧 IPO 44/36 结束日期需重新裁决

当前 `MAIN_BOARD_IPO_DAY effective_to=20230131` 缺乏与实际交易制度切换一致的官方依据。

2023 修订交易规则于 2023-02-17 发布，但沪深交易所均明确交易规则自按照注册制办法发行的首只主板股票上市首日起施行；首批主板注册制企业于 2023-04-10 上市。

参考官方来源：

- SZSE 规则通知：https://investor.szse.cn/lawrules/index/rule/t20230217_598773.html
- 首批上市：https://www.szse.cn/aboutus/trends/news/t20230404_599697.html
- SSE 过渡说明：https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230217_5716420.shtml

必须从官方过渡规则重新确定旧 IPO 44%/36% regime 的精确终止语义，不得保留 `20230131` 作为未经证明的日期。

## 3. Evidence binding 的 P0 缺口

现有 `scripts/rules/review.py` 一次只接受一个 `--artifact`，并把该 artifact 作为整个 rule dataset 的顶层 review provenance。

当前 rules 横跨 SSE / SZSE / STAR / BSE 及多个历史制度期，一个 official artifact 不可能机器可验证地证明全部 rule facts；现有路径理论上允许“一份无关但官方的文件”为整套 rulebook 提供 REVIEWED provenance。

因此，在正式 rule seal 前必须补一个最小而充分的 per-rule evidence contract。

推荐最低复杂度方案：

1. 保持 rule dataset 单文件结构，不引入通用 evidence graph；
2. 增加 deterministic `RULE_EVIDENCE_BUNDLE`（或等价的简单结构）；
3. bundle manifest 对每个 `rule_id` 精确列出：
   - official source identity / URL；
   - artifact kind；
   - role（仅复合事实需要，例如 RULE / APPLICABILITY / TRANSITION）；
   - raw artifact SHA256 / size；
4. rule candidate 中的 `source_ref` 改为精确可核验 locator，而不是泛化文字；
5. seal 前验证：
   - candidate rule_id set 与 evidence contract exactly match；
   - 无 missing / duplicate / extra rule；
   - source host / kind / role 符合冻结合同；
   - raw bytes hash 与 manifest 一致；
   - bundle member path 安全；
6. `trading_rule_review_gate` 在 REVIEWED 版本加载时重新验证 bundle/contract，而不仅仅验证一个顶层 artifact hash。

不得为了这 9~若干条规则建立复杂通用证据系统；复用 Golden 已有 deterministic bundle 思路即可。

## 4. Trading Rule H1 的执行顺序

### H1-A · 全量规则语义复核

对当前 9 条逐条复核，但规则数不是冻结指标；目标是制度语义正确、覆盖无洞、PIT 可解析。

当前可暂定：

- `MAIN_BOARD_NORMAL`：保留候选，复核 10% / tick / rounding / effective semantics；
- `MAIN_BOARD_ST`：保留候选，复核 5% / effective semantics；
- `MAIN_BOARD_IPO_DAY`：保留概念但重新裁决 transition boundary；
- 主板注册制 FIRST5：新增；
- `CHINEXT_PRE_REGISTRATION`：不得原样保留，拆分普通/ST 或用等价无歧义表达；
- `CHINEXT_REGISTRATION`：复核 20%；
- `CHINEXT_REGISTRATION_FIRST5`：复核首 5 交易日不限；
- `STAR_MARKET`：复核 20%；
- `STAR_MARKET_FIRST5`：复核首 5 交易日不限；
- `BSE_LIMIT`：修正为真实 BSE venue/effective boundary；
- BSE listing-day no-limit：新增；
- pre-BSE Selected Layer：只有在明确属于 A-share 基座所需研究域时才单独建模，不得冒充 BJ 历史。

### H1-B · 构建 NEW COMPILED candidate

- 原 `v20260824-compiled` 保持 immutable；
- 新版本目录 create-only；
- ACTIVE 在 candidate review 前不得切换；
- dataset hash、rule count、每条 source identity 明确；
- 不允许通过修改 Golden v7 或 provider output 来反推规则。

### H1-C · 边界/对抗测试

至少新增以下真实边界测试：

1. 主板注册制 IPO 第 1~5 交易日 -> no limit，第 6 日 -> normal 10%；
2. 主板旧 IPO 44/36 transition boundary 前后；
3. 创业板 2020 改革前 normal 10% / ST 5%；
4. 创业板改革后 first5 no limit / 第 6 日 20%；
5. STAR first5 no limit / 第 6 日 20%；
6. BSE 实际成立边界：BSE 前不得以 BJ rule 静默命中；
7. BSE IPO listing day no limit / 后续 30%；
8. missing calendar / listing_date / ambiguous rule 仍 fail closed；
9. evidence bundle missing/extra/wrong-rule/wrong-hash/wrong-role/tamper 均 fail closed。

### H1-D · Independent Reviewer checkpoint

在任何 REVIEWED publication 前，独立 Reviewer 需要检查：

- corrected candidate facts；
- official-first-party source contract；
- per-rule evidence coverage；
- transition boundary tests；
- old candidate immutability；
- CI final-head + current-main composition。

只有 Reviewer 明确关闭 H1-D 后，才允许 seal。

### H1-E · REVIEWED seal

- 使用 hardened rule review path 创建 NEW immutable REVIEWED version；
- reviewer marker 使用项目 Owner / Human Review 的稳定标识即可，不增加额外人工表单；
- evidence bytes 由工具计算 SHA；
- publication atomic；
- ACTIVE pointer 最后推进；
- failure 不留下半 REVIEWED state；
- 原 COMPILED 版本和旧 manifest history 保留。

## 5. Formal Production 后续

Trading Rule H1 REVIEWED seal 被独立 Reviewer 接受并合并后：

1. 从届时 current main 建立新的 clean Windows checkout；
2. 重新核 SDK/runtime/identity/network/auth/query readiness；
3. 再由 Provider/项目日历解析最新完整交易日；
4. 执行仍未消耗的唯一一次 Formal Production B1-B7；
5. 只有创建 run_id 后才算正式 attempt 开始；
6. 若 CLOSED，对同一 run_id 执行 verdict；
7. 建独立 evidence PR，供 Reviewer 做 Provider GO / CONDITIONAL GO / NO-GO 裁决。

本次 pre-run rule blocker：

- 不标记 FAILED；
- 不标记 NO-GO；
- 不生成 run_id；
- 不消耗正式 attempt。

## 6. 明确禁止

- 禁止把当前 9 条原样 `COMPILED -> REVIEWED`；
- 禁止手工改 `review_status` 或 ACTIVE pointer；
- 禁止用 GT-H3 Golden evidence 替代 rule evidence；
- 禁止把 Selected Layer 历史静默改写成 BJ institutional truth；
- 禁止为赶 Formal Production 而降低 rule review gate；
- 禁止看到 Provider 结果后再反向修改 rule truth 来制造 GO。

## 7. 当前阶段状态

- GT-H3B / Golden v7：CLOSED / ACTIVE / REVIEWED 125/125
- clean Windows checkout：PRECHECK VERIFIED
- AmazingData runtime/online identity/query：PRECHECK VERIFIED
- Trading Rule H1：OPEN / CURRENT TASK
- ACTIVE trading rules：COMPILED / NOT PRODUCTION-ELIGIBLE
- Formal Production B1-B7：AUTHORIZED / NOT STARTED
- Provider verdict：PENDING
- Data Sufficiency：BLOCKED
- 2020+ backfill：BLOCKED

## 8. 2026-09-09 实施进度与剩余门禁

本轮已在独立分支实现并测试以下内容：

- 新建非 ACTIVE 的 `v20260909-h1-compiled` 候选，规则数从 9 条扩为 14 条，覆盖主板 IPO 前 5 日、主板 ST venue 历史起点、创业板改革前 ST、BSE 生效边界与上市首日不限价；
- 新增 `RULE_EVIDENCE_BUNDLE.v1`，要求每个 `rule_id` 精确对应官方来源，校验来源域名、角色、文件路径、原始字节 SHA-256 和字节数；
- bundle 输入中的 `source_url` 还必须精确命中对应候选 `rule_id` 的 `source_ref`；bundle/raw 引用必须按 `sha256/<hash>` 内容寻址，避免用另一条规则的官方文件或非内容寻址别名绕过来源绑定；
- `scripts/rules/review.py` 新增 `--evidence-bundle` 封印路径；旧 `--artifact` 仅保留兼容性用途；
- Production 的 run 创建和 verdict 路径均强制 bundle 复核；
- 新增 H1 边界、证据篡改、缺失/多余 rule_id、完整 bundle 发布流程测试；旧审阅测试夹具已同步升级为 bundle 契约。

当前仍未完成、不能绕过的事项：

1. 由项目管理者/独立 Reviewer 实际打开并留存 14 条规则所需的每份官方 HTML/PDF 原文；
2. 按《TradingRule H1 人工审阅操作表》逐条填出 14 个 `APPROVE`，并对旧 IPO 44/36 终止边界、主板 ST 首 5 日适用性、主板 ST venue 历史起点、BSE venue 历史语义作明确裁决；
3. 用真实原文生成输入 bundle 并通过 `scripts/rules/review.py` 发布 NEW `REVIEWED` 版本；
4. 独立 Reviewer 接受后，才可推进 ACTIVE，再从最新 main 做 Formal Production preflight 和 B1-B7。

在上述事项完成前，旧 ACTIVE `v20260824-compiled` 继续保持原样，Formal Production 继续保持 NOT STARTED；没有生成 run_id，也没有消耗正式 attempt。当前 main 中已有 GT-H3B Golden v7 的历史 BSE evidence，但该 evidence 域不得替代 H1 的独立 Trading Rule 原文证据。

## 9. H1R 二审整改已落地的实现约束（2026-09-09）

本节记录并落实最新 main 的二审要求（PR #32 review checkpoint `5149191372`）。它不改变“候选不得直接封印”的状态。

### 9.1 主板 ST 的 PIT 分段

候选 `2026-09-09.1` 现为 14 条。主板 ST 的历史片段进一步按交易场所拆分，当前片段仍按同一制度边界覆盖沪深两市：

- `MAIN_BOARD_ST_HISTORICAL_SH`：SH、`60xxxx`，`19980422`—`20260705`，5%；
- `MAIN_BOARD_ST_HISTORICAL_SZ`：SZ、`000xxx/001xxx/002xxx/003xxx`，`19980428`—`20260705`，5%；
- `MAIN_BOARD_ST_CURRENT`：自 `20260706` 起，10%。

历史起点来自交易所官方历史材料：[SSE 官方市场史](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170577/files/ae3c4a6d91b74aacbddc96a4d600f06f.pdf)记载 1998-04-22 实施特别处理，[SZSE 官方 1998 年大事记](https://www.szse.cn/aboutus/sse/events/t20070328_497832.html)记载 1998-04-28 首次实行特别处理。这里将该首次实施记录作为候选 PIT 下界，完整法律生效语义仍需独立 Reviewer 逐条打开原文确认；起点前一日不静默回退到普通规则，而是 fail closed。解析依赖规则数据，不使用运行时日期特判。已加入 SH、SZ 的起点前/起点日测试以及 2026-07-03、2026-07-06、2026-09-08 边界测试，普通主板同期仍必须为 10%。

### 9.2 主板首五日语义收口

删除 `MAIN_BOARD_ST_FIRST5_NO_LIMIT`，将 `MAIN_BOARD_FIRST5_NO_LIMIT` 设为 `st_state: null`。解析器按 `listing_age_rule` 分别选择 ST-specific 与 ANY 规则，使同一条首五日不限价规则同时覆盖 `is_st=false/true`，而第六个交易日仍回到对应的历史 5%或当前 10% ST 规则。

候选 `source_ref` 不再允许 `to be checked`、`TODO`、`TBD` 或“待确认/待核”等未决标记；规则加载校验会 fail closed。

### 9.3 Evidence required URL set 升级为 exact coverage

`RULE_EVIDENCE_BUNDLE.v1` 的 prepare 与 runtime validator 现在都要求：对每个 `rule_id`，bundle 实际 `source_url` 列表与候选 `source_ref` 中的 required URL set 完全相等；缺失、额外或重复 URL 均拒绝，同时保留官方 host、kind/role、路径、SHA-256、字节数和 `sha256/<hash>` 内容寻址校验。

新增反例测试覆盖：两条声明只提交一条、两条全部提交、同一 URL 重复、增加第三条官方 URL。模板已同步到 14 个新 rule_id，并为所有延续至 2026-09 的规则加入当前第一方来源 locator：

- [SSE 2026 年修订交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)；
- [SSE 2026 风险警示调整公告](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)；
- [SZSE 2026 年现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf)；
- [SZSE 2026 风险警示业务指南公告](https://www.szse.cn/lawrules/service/member/t20260630_621404.html)；
- [BSE 现行上市交易规则](https://www.bse.cn/jygl_list/200028217.html)。

这些 URL 只是候选 required source contract；当前已把来源原始字节/浏览器归档作为**待审阅 intake**保存在 `docs/provider_verification/trading_rule_h1_sources/`，并生成输入 bundle。它们尚未写入发布态 `configs/trading_rules/evidence/`，也没有把搜索结果或摘要当成证据。

### 9.4 当前放行状态

本轮实现已达到 `H1R IMPLEMENTED / CI VERIFIED GREEN / HUMAN REVIEW REQUIRED`（GitHub Actions run `34310188331` / #490，Ubuntu 3.14、Windows 3.14、Windows 3.12 全部成功）。旧 `v20260824-compiled`、ACTIVE pointer、Golden v7 及其 evidence/receipt 未修改；真实 14 条（按 required URL 集合展开后的全部原文）仍须由项目管理者/独立 Reviewer 实际打开、留存并逐条裁决。Reviewer 未明确关闭本文件的全部 P0（包括历史 ST venue 起点）前，不得生成真实 REVIEWED seal、切换 ACTIVE、创建 run_id 或执行 Formal Production B1-B7。
