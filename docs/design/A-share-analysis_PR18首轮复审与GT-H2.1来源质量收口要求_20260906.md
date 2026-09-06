# A-share-analysis PR #18 首轮复审与 GT-H2.1 来源质量收口要求

> Date: 2026-09-06  
> Authoritative pre-review baseline: `5f76ad411801998de7bd3be7f26c880a73005853`  
> PR: #18 `feat: build GT-H2 clean golden candidate`  
> Reviewed head: `4c4ab355a8cf0e748026ed3933810c009b23e47e`  
> Reviewer review: `5124616299`  
> CI: run 327 / `34018727322` — Windows 3.14 / Windows 3.12 / Ubuntu 3.14 SUCCESS  
> Status: **GT-H2 MECHANICS PASS / KEEP; GT-H2.1 SOURCE-QUALITY + REPRESENTATIVENESS CHANGES REQUIRED; DO NOT MERGE**

## 1. 本轮裁决

PR #18 在工具链、版本治理和 gate 语义上基本达到 GT-H2 预期，应保留：

- v3 -> v4 rebuild 明确绑定 `v3-candidate-20260822` 与 dataset SHA256；
- 123 个 v3 source rows 全部有且仅有一个显式操作；
- 旧 v1/v2/v3 dataset / versioned manifest 不改写；
- v4 candidate 保持 `COMPILED N/N`，没有伪造 `REVIEWED`；
- review packet 覆盖 ACTIVE case IDs 恰好一次；
- quantity gate / structural event gate / review readiness 均通过；
- Formal Production gate 当前只剩 human-review blocker；
- 未运行 `review.py` final seal、Production B1-B7、Data Sufficiency、Provider capability verdict 或 backfill；
- final head run 327 三个 required platform jobs 全绿。

因此本轮不回退 GT-H1/H1.1/H1.2，也不推翻 GT-H2 的 clean-candidate 路线。

但 **Golden Truth 的可信度不是“域名属于交易所 + 数量达到门槛”即可成立**。当前 candidate 在来源精确度和 ST 覆盖分布上仍存在阻塞项，进入 Human Review 前必须先关闭。

## 2. GT-H2.1 P0-01：case-level source locator 不足以唯一重定位原始事实

当前 packet 对 128 条 case 都提供了 `official_source_ref` 并设 `fact_proved=true`，但相当一部分 ref 只是官方门户首页或栏目页，而不是证明该 case 的具体规则/公告/文档。

确认的典型问题：

### 2.1 Dividend 20 rows

现有 legacy dividend rows 被 REPLACE 后，多数仍只使用：

```text
SSE:    https://www.sse.com.cn/disclosure/listedinfo/announcement/
CNINFO: https://www.cninfo.com.cn/new/disclosure
```

同时 packet 声称具体证券、具体年度 dividend 的具体 ex-date 已 `fact_proved=true`。

这种链接只能证明“这里可以搜索公告”，不能唯一证明：

```text
symbol
annual distribution period
exact ex-date
expected IS_WD_SEC semantics
```

Human Reviewer 还必须重新进行搜索和事实发现，后续 content-addressed artifact seal 也无法确定绑定哪一个原始文档。

### 2.2 BSE 30% limit

当前 BSE 30% price-limit cases 使用：

```text
https://www.bse.cn/
```

作为 `EXCHANGE_RULEBOOK` source ref。

BSE 首页不是具体规则版本，也不能证明该 observation date 上适用的 exact 30% rule/version。

### 2.3 BJ mapping 3 rows

三条 `BJ_CODE_MIGRATION` / segment case 同样都只指向：

```text
https://www.bse.cn/
```

但 source claim 分别是：

- 北交所开市时精选层公司迁移且代码不变；
- 2022 quotation/code continuity；
- 2024 920 code segment。

三个不同事实不能由同一个交易所首页稳定证明。

### 2.4 Generic rule category pages

类似：

```text
https://www.szse.cn/lawrules/rule/trade/
```

只属于规则目录。若官方存在具体规则版本、通知、PDF、HTML 文档 ID，应替换为该 exact locator。

## 3. 来源修正合同

GT-H2.1 后，每个 candidate 的 `official_source_ref` 必须满足以下至少一种：

1. 直接打开具体官方 PDF/HTML 公告；
2. 稳定官方文档 URL；
3. 官方系统中的唯一、稳定 document ID，能够无歧义重新取回同一文档。

**不接受**：

```text
exchange home page
generic disclosure portal root
generic announcement search page
generic rule directory
search-engine result URL
secondary-media URL
Provider output URL
```

除非该 URL 本身就是官方具体文档页面。

`fact_proved=true` 的含义同步收紧为：

> Agent 已实际打开/检查该 case 对应的 specific official artifact，确认 artifact 本身包含支持 candidate claim 的事实；它仍然不是 Human Review。

若 Agent 只找到了门户入口、搜索页或线索，必须：

```text
fact_proved=false
```

并不得以该 case 进入 GT-H2 closure。

## 4. 必须补齐的 case-level evidence 范围

### P0 required

- 20 个 `DIVIDEND_EX_DATE`：每条使用 exact profit-distribution / ex-rights announcement；
- BSE 30% limit：使用适用于 observation dates 的 exact BSE trading rule/version；
- 3 个 BJ mapping：分别绑定 exact opening / migration / quotation / code-segment official document；
- 其他 generic portal/category locator：能找到 exact document 的必须替换。

### Historical retrospective references

少量 ST / DELIST / right-issue 当前使用较晚年份官方披露回溯证明更早事实。允许这种做法，但必须满足：

- 文档内明确写出 exact historical date；
- specific official artifact 可稳定定位；
- 如果 contemporaneous official notice 可获得，优先使用 contemporaneous notice。

Reviewer 已抽样验证 002681：

- 2020-04-30 SZSE official announcement 明确写明自 2020-05-06 实施退市风险警示；
- 2021-04-10 SZSE official announcement 明确写明自 2021-04-13 撤销退市风险警示。

说明 exact-artifact 路线完全可行，应一致应用到全 corpus。

## 5. 必须增加 source-quality adversarial tests

现有 test 只检查：

```text
scheme == http/https
netloc in official-domain allowlist
fact_proved is True
```

这会让“交易所首页”错误通过。

新增至少以下 fail-closed tests：

```text
BSE homepage                       -> not valid as case-level fact locator
CNINFO disclosure root             -> not valid as case-level fact locator
SSE listed announcement root       -> not valid as case-level fact locator
known generic SZSE rule directory  -> not valid when exact document is required
```

实现不要求建立复杂 URL classifier；可以维护一个小而明确的 `PORTAL_ONLY_LOCATORS` denylist / candidate evidence validation helper。

目标是防止以后重新退化，而不是对互联网 URL 做通用安全分类。

## 6. GT-H2.1 P1-02：ST corpus 明显偏向 SZSE

当前 50 个 distinct structural ST events：

```text
SSE   4
SZSE 46

MAIN     34
CHINEXT  15
STAR      1

ST_ADD       37
STAR_ST_ADD   1
ST_REMOVE    12
STAR_ST_REMOVE 0
```

ADD/REMOVE family 本身已不再是 token coverage，但 exchange / board coverage 明显不平衡。

GT-H2 管理合同已经明确：Formal minimum 不是样本质量目标，Reviewer 必须判断 subtype / board / exchange / year 是否失衡。

当前 92% ST events 来自 SZSE，SSE 只占 8%，STAR 只有单点样本。这不足以对以下风险提供可靠检测：

- SSE 与 SZSE symbol/status mapping 差异；
- 主板与 STAR 风险警示状态语义差异；
- STAR ADD/REMOVE 方向差异；
- Provider 对不同交易所历史状态接口的非一致行为。

## 7. ST rebalance 要求

不要简单扩容 corpus。优先：

```text
DROP / replace 部分重复价值较低的 SZSE ST cases
ADD / replace 为 independently evidenced SSE cases
保持总 distinct events >= 50
```

目标：

- SSE 不得继续只是 4/50 token coverage；
- STAR 必须有多个独立事件，而不是 1 个；
- 如 2020+ 可找到真实官方 `STAR_ST_REMOVE`，至少纳入 1 个；
- 若经系统检索确实找不到合适 STAR remove，必须在 report 写明检索范围和不纳入原因，由 Reviewer 单独裁决；
- 不人为制造固定比例，不为了数字美观增加低价值 case。

建议质量目标（非长期 Formal 常量）：

```text
SSE distinct ST events >= 10
STAR distinct ST events >= 3
STAR remove >= 1 when a valid 2020+ official case exists
```

如果开发者认为实际市场事件分布使该建议不合理，必须用官方事实分布说明，而不是直接维持 46/4。

## 8. GT-H2.1 P1-03：新增 pre-2020 right-issue case

当前 H2 新增：

```text
002202.SZ
RIGHT_ISSUE_EX_DATE
2019-03-29
```

项目研究/回补边界原则是 2020-01-01+。GT-H2 新增事实原则上也应 2020+。

处理：

- 优先替换为 2020+ exact right-issue official case；
- 如必须保留 2019 case，GT_H2_CORPUS_REPORT 和 packet 必须说明具体规则边界/兼容性必要性；
- `000750.SZ / 2020-01-14` 当前使用 2025 annual report 回溯证明，优先寻找 2020 contemporaneous rights-issue announcement。

## 9. GT-H2.1 re-review exit criteria

下一次 Reviewer 复审前必须全部满足：

```text
[ ] PR remains COMPILED N/N; no Human seal
[ ] every case has exact/stable case-specific official locator or document ID
[ ] no portal-only locator is presented as fact_proved=true
[ ] all 20 dividend cases point to exact official distribution/ex-date artifact
[ ] BSE 30% limit uses exact rule/version
[ ] all BJ mapping cases use exact official supporting document
[ ] source-quality adversarial tests exist and pass
[ ] ST SSE/STAR representation materially rebalanced
[ ] STAR remove included when supportable, or absence documented for Reviewer
[ ] new pre-2020 facts removed/replaced or explicitly justified
[ ] review packet still equals ACTIVE case-ID set exactly once
[ ] quantity_gate == []
[ ] event_coverage_gate == []
[ ] review_readiness_gate == []
[ ] production_formal_gate has only human-review blocker
[ ] v1-v3 immutable bindings unchanged
[ ] no review.py final seal
[ ] no Production B1-B7 / Data Sufficiency / Provider verdict / backfill
[ ] Windows 3.14 / Windows 3.12 / Ubuntu 3.14 final-head CI SUCCESS
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / GT_H2_CORPUS_REPORT synchronized
```

## 10. 阶段状态

```text
GT-H1                          CLOSED
GT-H2 candidate mechanics      PASS / KEEP
GT-H2.1 source quality         OPEN
GT-H2.1 sample balance         OPEN

Human Review / GT-H3           BLOCKED
Formal Production B1-B7        BLOCKED
Data Sufficiency               BLOCKED
Provider capability verdict    BLOCKED
2020+ backfill                 BLOCKED
```

在 GT-H2.1 Reviewer closure 前，不得合并 PR #18，不得运行 final Human seal。
