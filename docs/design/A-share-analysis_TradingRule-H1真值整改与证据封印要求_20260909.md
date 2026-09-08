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
