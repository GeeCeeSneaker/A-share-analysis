# A-share-analysis · Trading Rule H1 二审发现与 H1R 整改要求

日期：2026-09-09（Asia/Shanghai）

## 1. 结论

PR #32 的 H1 实现方向整体正确，但当前 **不得合并、不得生成真实 evidence bundle、不得发布 REVIEWED、不得切换 ACTIVE、不得重试 Formal Production**。

独立二审确认两个生产阻断项：

- `P0-TR-H1-06`：2026-07-06 起沪深主板风险警示股票涨跌幅已由 5% 调整为 10%，当前候选仍把 `MAIN_BOARD_ST` 固定为 5% 到 2099，直接导致 `as_of_date=20260908` 的规则真值错误。
- `P0-TR-H1-07`：`RULE_EVIDENCE_BUNDLE.v1` 当前只验证“提交的 URL 属于该 rule_id 声明来源之一”，没有验证“该 rule_id 声明的全部必要来源均已提交且各出现一次”，多来源规则可只交其中一份而通过。

Reviewer checkpoint：PR #32 review `5149191372`。

当前 main 基线：`a69e207839b2adf7908dc434493b2106869aa5c6`。
PR #32 当前 head：`b74e976a5c25538d9b26e5e9f3cca5389fd9b9d4`。
current-main test-merge：`a5db9149f01d244bcb6b190b1b6486407e19bb43`。
CI #486：三平台 SUCCESS。CI 仅证明实现稳定，不能覆盖下述真值错误。

## 2. P0-TR-H1-06 · 2026 主板 ST 涨跌幅制度变化必须进入 PIT truth

官方 2026 制度已经发生变化：

- 上海证券交易所 2026 年修订交易规则明确将主板风险警示股票价格涨跌幅限制比例由 5% 调整为 10%，自 2026-07-06 起施行；
- 深圳证券交易所 2026 年交易规则/风险警示业务指南同样完成该调整，自 2026-07-06 起实施。

因此，PR #32 中：

```text
MAIN_BOARD_ST
SH + SZ
19980401 -> 20991231
5%
```

是确定性错误，尤其会使已经解析出的 Formal Production `20260908` 错误命中 5%。

### H1R 要求

必须按 PIT 时间切分，禁止运行时特判。推荐最低复杂度表达：

- 历史主板风险警示 5%：截止 `20260705`；
- 当前主板风险警示 10%：自 `20260706` 起；
- SH/SZ 若制度边界一致，可继续共用同一组时间切片；若后续官方证据显示场所差异，则拆 venue，不得强行合并。

rule_id 名称不冻结，可采用清晰的历史/当前命名。规则总数也不是验收指标。

必须新增真实边界测试：

1. SH ST：`20260703 -> 5%`，`20260706 -> 10%`；
2. SZ ST：`20260703 -> 5%`，`20260706 -> 10%`；
3. 普通主板同期仍为 10%；
4. `20260908` ST 主板必须解析为 10%。

不得修改 Golden v7 或 Provider 输出制造匹配。

### 2.1 补充历史起点边界：当前候选不得继续共用 `19980401`

在本文件形成后，PR #32 时间线中的独立只读审阅又指出了历史起点证据缺口。该意见不是对本节 2026 制度结论的替代，而是同一候选的额外生产阻断项：

- [SSE 官方市场史](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170577/files/ae3c4a6d91b74aacbddc96a4d600f06f.pdf)记载 1998-04-22 对“财务状况异常”的上市公司实施股票交易特别处理；
- [SZSE 官方 1998 年大事记](https://www.szse.cn/aboutus/sse/events/t20070328_497832.html)记载 1998-04-28 首次对上市股票实行特别处理。

因此，H1R 候选将历史 ST 5% 规则改为按 venue 分开表达：`SH/60xxxx` 自 `19980422` 起，`SZ/000xxx、001xxx、002xxx、003xxx` 自 `19980428` 起，二者均至 `20260705`。这是根据交易所第一方历史记录收紧 PIT 下界的候选实现；“首次记载日期”是否足以作为完整法律生效日，仍须独立 Reviewer 打开原文后确认，不能仅凭搜索摘要或本记录自动视为已审定。

必须增加起点前一日 fail-closed 与起点当日 5% 的测试：SH `19980421/19980422`、SZ `19980427/19980428`。在 Reviewer 关闭该历史边界 P0 前，候选继续保持 `COMPILED`、非 `ACTIVE`，不得生成可发布到 `configs/trading_rules/evidence/` 的真实 H1 evidence bundle；供 Reviewer 查看的本地 intake 原文和未封印输入清单不等同于发布态 bundle。

## 3. P0-TR-H1-07 · evidence source contract 必须从 subset 升级为 exact coverage

当前实现的核心检查是：每个 bundle source URL 必须属于对应 rule 的 `source_ref` URL 集合。

这仍允许：

```text
source_ref declares: [SSE source, SZSE source]
bundle supplies:      [SSE source only]
=> current validator may pass
```

对于跨 venue、RULE + TRANSITION、历史 + 当前连续性规则，这不足以证明完整真值。

### H1R 要求

保持简单，不建立通用 evidence graph：

1. 把每个 rule 的 `source_ref` 中 URL 集合定义为该 rule 的 **required source set**；
2. bundle 对该 rule 的实际 `source_url` 集合必须与 required source set **完全相等**；
3. 每个 required URL 必须恰好出现一次；
4. missing / extra / duplicate URL 均 fail closed；
5. 继续保留现有 host/kind/role/path/hash/size/content-addressed 校验；
6. role 可保持描述性，不需要引入 claim graph，只要 required URL set 已经完整表达必要来源。

必须新增对抗测试：

- rule 声明 2 个 URL，bundle 只交 1 个 -> FAIL；
- 交齐 2 个 -> PASS；
- 同一 URL 重复两次 -> FAIL；
- 额外第三个官方 URL -> FAIL。

## 4. P1 收口要求

### 4.1 `MAIN_BOARD_ST_FIRST5_NO_LIMIT`

当前 `source_ref` 包含：`including risk-warning applicability to be checked`。

任何带“待确认”语义的 rule 不得进入 REVIEWED。

优先使用更简单的表达：若 resolver 证明主板 IPO 前 5 日不限价与 ST 状态无关，可只保留一个 `MAIN_BOARD_FIRST5_NO_LIMIT`，设置 `st_state: null`，删除单独的 `MAIN_BOARD_ST_FIRST5_NO_LIMIT`；同时保留 is_st=false/true 两个解析测试。

若实现选择保留独立 ST FIRST5 rule，则必须用第一方证据明确证明其适用性并删除全部待确认文字。

### 4.2 当前有效规则来源连续性

凡 `effective_to` 延续到 2026-09 的 rule，source contract 必须包含足以证明 **当前有效制度** 的 2026 第一方来源，不能只依赖已废止/历史页面。

至少重新检查：

- MAIN 普通 / FIRST5 / ST；
- ChiNext 20% / FIRST5；
- STAR 20% / FIRST5；
- BSE 30% / IPO-day no-limit。

历史来源用于证明历史区间；当前 2026 来源用于证明当前区间。若事实在 2026 修订中改变，必须拆 PIT row，而不是仅补新 URL。

## 5. 已接受、不需返工的部分

以下方向已通过二审，不要重做架构：

- 新 candidate 非 ACTIVE、create-only；
- 原 `v20260824-compiled` immutable；
- Golden v7 不受影响；
- 主板注册制 FIRST5 缺口修正方向；
- 创业板改革前 normal/ST 拆分方向；
- BSE venue 边界改为 2021-11-15；
- BSE IPO 上市首日不限价概念；
- content-addressed bundle/raw artifact；
- SHA256 / byte size / path confinement；
- Production `new_run` 与 `verdict` 强制 evidence bundle gate；
- CI #486 三平台通过。

## 6. PR #32 H1R 验收条件

PR #32 可在同一分支继续整改，不需要另起复杂分支。最终必须满足：

1. 2026-07-06 主板 ST 5% -> 10% PIT transition 正确；
2. `20260908` 主板 ST 解析为 10%；
3. H1 其他已知边界仍正确；
4. evidence required URL set exact-match；
5. missing/extra/duplicate/subset 对抗测试齐全；
6. 不存在任何 `to be checked` / TODO 式未决 truth；
7. 当前有效 2026 制度有第一方 current-effective evidence；
8. old compiled / ACTIVE / Golden v7 不变；
9. final-head + current-main test-merge 三平台 CI green；
10. 历史 ST 起点按 venue 的第一方记录建模，且起点前一日 fail-closed 测试通过；
11. 独立 Reviewer 明确关闭本文件的全部 P0 后，才允许真实 evidence materialization 与 REVIEWED seal。

## 7. 阶段状态

- GT-H3B / Golden v7：CLOSED / ACTIVE / REVIEWED 125/125
- Trading Rule H1：OPEN
- Trading Rule H1R：CURRENT TASK
- PR #32：DO NOT MERGE YET
- ACTIVE trading rules：仍为旧 COMPILED，NOT PRODUCTION-ELIGIBLE
- Formal Production B1-B7：PROHIBITED UNTIL H1 REVIEWED PR IS INDEPENDENTLY CLOSED / NOT STARTED
- Formal attempt：未消耗
- Provider verdict：PENDING
- Data Sufficiency：BLOCKED
