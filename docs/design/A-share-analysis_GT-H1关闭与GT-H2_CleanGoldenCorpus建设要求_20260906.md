# A-share-analysis GT-H1 关闭与 GT-H2 Clean Golden Corpus 建设要求

> Date: 2026-09-06  
> Authoritative baseline: `6af6731613169c439abbb138a475a78b21797295`  
> PR #16 final head: `c559023f11cb86a26af1b471ba6c0113d47e84bb`  
> Reviewer final review: `5124122588`  
> PR #16 final CI: run 320 / `34008802590`; test-merge `d68f59248ef649ac57f64678076b14f740d371a8`; Windows 3.14 `1550 passed`；Windows 3.12 / Ubuntu 3.14 同为 SUCCESS  
> PR #16 merge: `6af6731613169c439abbb138a475a78b21797295`  
> Status: **GT-H1 / GT-H1.1 / GT-H1.2 CLOSED — GT-H2 CLEAN CANDIDATE CONSTRUCTION AUTHORIZED**

## 1. 阶段裁决

PR #16 已关闭以下 Golden Truth 工具/契约问题：

- ST / DELIST structural identity 必须使用显式、合法的 `event_effective_date`，禁止回退 `trade_date`；
- structural identity 只用于事件资格去重，不是 row uniqueness key；同一真实事件允许多个 observation cases；
- v1-v3 继续 immutable / loadable，但结构字段不完整时 Formal fail-closed；
- v4+ semantic hash 绑定事件身份字段；schema-v2 manifest 使用同一 structural statistics 重算；
- candidate rebuild 只能经显式 `KEEP / REPLACE / DROP / ADD`，旧 `build-version` 隐式追加入口已禁用；
- review 必须从 clean v4+/schema-v2、全量 COMPILED candidate 开始；
- review publish 必须一次覆盖 ACTIVE 全部 case 且各一次，最终原子形成 `REVIEWED N/N`。

因此当前允许进入 **GT-H2：构建一个紧凑、独立、可审计、可进入人工审核的 clean Golden candidate**。

本阶段仍不授权：

```text
Human full review / review.py final seal
Formal Production B1-B7
Data Sufficiency Matrix
Provider capability GO / CONDITIONAL GO / NO-GO
2020+ backfill
strategy / backtest / trading
```

## 2. 当前 v3 只作为 rebuild source，不作为事实数量基线

当前 ACTIVE 仍是：

```text
truth_version     v3-candidate-20260822
case_count        123
review_summary    COMPILED 123
rows:
  ST              50
  DELIST          20
  LIMIT           30
  CORP_ACTION     20
  BJ_MAPPING       3
```

旧 manifest 记录的 ST/DELIST distinct-event 数字属于旧语义。v3 structural rows 中存在缺失 `event_effective_date`、同一事件多观察日等历史结构，因此 **不得把 v3 的 `distinct_events` 数字作为 GT-H2 可继承事实**。

GT-H2 必须从真实外部事实重新判定 structural identity。

## 3. GT-H2 的目标不是“把门槛数字凑满”

Golden Truth 是用来验证 Provider 的独立事实资产，不得从 AmazingData 返回结果反推真值，也不得为了过 Formal gate 复制 observation rows、改 `event_id` 或制造别名。

默认原则：

1. **一个真实 structural event 默认只建立一个 canonical validation case**；
2. 只有在确实需要验证“状态持续性 / 多日期一致性”时，才为同一事件增加额外 observation case；
3. 额外 observation case 不增加 structural event count；
4. 冗余、难以独立证明、只增加人工审核成本的旧 case 应 DROP，而不是机械 KEEP；
5. 项目历史研究边界以 **2020-01-01 以后**为主。GT-H2 新增 structural facts 原则上选 2020+；若保留/新增 2020 年以前事件，必须说明其对规则边界、历史兼容或 Provider 行为验证的必要性。

## 4. Formal gate 的硬性最低要求

GT-H2 candidate 在进入人工审核前必须已经满足 quantity + structural event gates：

```text
golden_st_transition rows           >= 50
distinct ST_TRANSITION events       >= 50
ST_ADD / STAR_ST_ADD events          > 0
ST_REMOVE / STAR_ST_REMOVE events    > 0

golden_delisted rows                >= 20
distinct DELIST events               >= 20
distinct delisted securities         >= 20

golden_limit_regime rows            >= 30
golden_corporate_action rows         >= 20
```

这些是最低 gate，不是选样质量目标。不得用“49 ADD + 1 token REMOVE”之类机械方式理解覆盖要求；PR 必须给出 subtype / board / exchange / year 分布表，由 Reviewer 判断是否明显失衡。

`golden_bj_mapping` 当前没有上述 quantity minimum，但若保留该能力验证，case 必须同样有独立、可追溯事实依据。

## 5. ST_TRANSITION 建设规则

每个 structural event 必须具备：

```text
provider_symbol
event_class = ST_TRANSITION
event_subtype ∈ {ST_ADD, ST_REMOVE, STAR_ST_ADD, STAR_ST_REMOVE}
event_effective_date = exact YYYYMMDD
```

事实来源优先使用交易所官方风险警示/撤销风险警示公告、正式证券简称变更/交易安排公告等。

要求：

- 至少 50 个真实独立 transition identities；
- 必须同时存在 ADD family 与 REMOVE family；
- 尽量覆盖 SSE / SZSE 及主板、创业板、科创板等实际适用场景；
- `event_id` 仅作为可读别名，不参与资格计数；
- `trade_date` 是 Provider 状态验证日期，不是事件日期；
- 旧 v3 ST structural row：若 exact effective date / subtype 能由独立官方来源确认，可 `REPLACE`；否则 `DROP`；不得直接 `KEEP` 一个结构不完整 row。

负样本 `NEGATIVE_SAMPLE` 可以保留，但必须真正测试不同风险点。针对同一证券逐年重复、没有新增验证价值的负样本应精简；负样本不计入 50 个 ST transition events。

## 6. DELIST 建设规则

必须形成至少：

```text
20 distinct (provider_symbol, event_effective_date)
20 distinct provider_symbol
```

每只证券至少有一个可独立验证的真实退市/终止上市生效事实。优先使用交易所终止上市决定、摘牌公告、官方证券状态记录。

旧 v3 DELIST row 同样执行：

```text
可独立确认 exact effective date -> REPLACE
不能独立确认 / 只是退市后观察日期 -> DROP
```

不得把同一退市证券的多个观察日当成多个退市事件。

## 7. LIMIT / Corporate Action / BJ Mapping 的处理

### 7.1 LIMIT

至少 30 rows。现有 v3 case 可以作为候选，但每条都必须重新检查 `expected_fields` 与事实来源，不因“当前刚好 30 条”而默认 KEEP。

应覆盖与 2020+ 数据平台直接相关的主要制度场景，例如：

- 主板普通股票；
- ST 风险警示；
- 创业板注册制改革后的规则；
- 科创板；
- 北交所；
- IPO / no-limit day 等特殊阶段。

规则真值来自交易所正式业务规则/公告，不从 Provider 输出反推。

### 7.2 Corporate Action

至少 20 rows。当前运行时已经区分 dividend 与 right-issue typed stream；因此若两个 stream 都属于正式支持范围，GT-H2 corpus 必须实际覆盖二者，不能长期只用 dividend case 验证一个双 stream 合同。

每个 case 的除权/除息或配股除权生效日必须由独立正式披露证明。

### 7.3 BJ Mapping

保留的每个北交所/代码迁移 case 必须能够说明它具体验证什么映射事实；只保留能够对 B7 / symbol mapping 产生真实验证价值的 case。

## 8. Truth source 独立性与来源层级

Golden Truth **禁止把被测 Provider 自身作为事实来源**。

优先级：

1. SSE / SZSE / BSE 官方规则、公告、证券信息；
2. 通过交易所正式披露系统发布的公司公告；
3. CSRC 或其他正式监管/登记结算来源；
4. 二手网站、搜索结果、媒体只能用于发现线索，不得作为唯一 Golden truth 证据。

每个 candidate 必须保留清晰的 `truth_source` / `source_ref`，并能让 Human Reviewer 独立重新定位原始事实。

## 9. Review packet：本阶段必须准备，但不得冒充 Human Review

GT-H2 PR 必须同时提交一个 **review packet index**，覆盖 candidate 中每个 `golden_case_id` 恰好一次。

建议路径：

```text
docs/golden/gt_h2/review_packet_index.jsonl
docs/golden/gt_h2/GT_H2_CORPUS_REPORT.md
```

每条 packet 至少包含：

```text
golden_case_id
case_type
provider_symbol
trade_date
event_class / event_subtype / event_effective_date（适用时）
expected_fields
official_source_name
official_source_ref
artifact_kind_candidate
fact_proved
human_review_checklist
```

允许一个官方 artifact 证明多个 case，但 packet 必须逐 case 显式建立 mapping。

Developer / Agent 可以：

- 搜集官方来源；
- 整理 case；
- 准备下载/取证说明；
- 在本地准备 artifact；
- 计算候选 digest 供核对。

Developer / Agent **不得**：

```text
review_status = REVIEWED
reviewed_by = project-owner / human-reviewer
伪造人工确认
运行 review.py 形成最终 reviewed ACTIVE
```

GT-H2 也不要为了审阅方便批量提交大量原始网页/PDF。先提交安全、可追溯的 review packet；最终 artifact bytes 在 Human Review / GT-H3 阶段按 review.py 的 content-addressed contract seal。

## 10. rebuild 交付物

GT-H2 PR 应从当前 v3 exact binding 构建一个新的 clean candidate：

```text
source_truth_version = v3-candidate-20260822
source_dataset_hash  = ab841d25858a5520c2357dcf72da9932fc1f25f988d900fd94730eb5a1a6f79e
```

使用：

```powershell
uv run python scripts/golden/candidate.py --root data/golden/provider/amazingdata rebuild --plan <gt-h2-plan.json>
```

PR 中应有：

```text
rebuild plan（KEEP / REPLACE / DROP / ADD 全覆盖）
new golden_cases_v4.jsonl（或工具产生的 next version）
new truth_manifest_v4.json
updated truth_manifest.json ACTIVE pointer
GT_H2_CORPUS_REPORT.md
review_packet_index.jsonl
DEVLOG / DEVELOPMENT_MANAGEMENT 同步
必要测试
```

旧 `golden_cases_v1/v2/v3`、旧 versioned manifest 必须 byte-for-byte 不变。

## 11. GT-H2 候选的退出门

提交 Reviewer 前，必须证明：

```text
GoldenTruthStore.load()              PASS
manifest_schema                      == 2
truth_version                        v4+ candidate
review_summary                       COMPILED N/N
review_readiness_gate                ZERO problems
quantity_gate                        ZERO problems
event_coverage_gate                  ZERO problems
```

此外应验证：

```text
production_formal_gate problems
= 只剩“not fully human-reviewed”这一类 review blocker
```

也就是说，GT-H2 candidate 在结构、数量、事件覆盖方面已经 Formal-ready，**唯一尚未满足的是 Human Review / artifact seal**。

Review packet 同时必须满足：

```text
packet case IDs == candidate ACTIVE case IDs exactly once
no missing
no duplicate
no foreign case
```

## 12. PR 与 CI 要求

GT-H2 必须单独 PR，保持 open，等待 Reviewer 审阅，不得自行 merge。

最终 head 必须通过：

```text
Windows latest / Python 3.14
Windows latest / Python 3.12
Ubuntu latest  / Python 3.14
Ruff
format
mypy
full pytest
Spike dry-run
SDK-absent
DEVLOG gate
Management gate
```

PR 说明必须给出：

- source main SHA；
- v3 binding hash；
- rebuild plan summary：KEEP / REPLACE / DROP / ADD 数量；
- 新 candidate case 数；
- counts by type；
- structural ST / DELIST counts；
- ST subtype distribution；
- exchange / board / year distribution；
- review packet coverage；
- formal gate 当前唯一 blocker；
- 明确声明未运行 `review.py` final seal、未运行 Production B1-B7。

## 13. Reviewer 将重点拒绝的模式

以下任一出现即不接受 GT-H2：

- 用 Provider 返回结果本身构造 truth；
- 用多个 trade_date / event_id alias 放大 structural event count；
- 把结构不完整的 v3 ST/DELIST 直接 KEEP；
- 为过门槛机械复制样本；
- 隐藏来源不确定性；
- 把 Agent 生成的判断写成 `REVIEWED`；
- 人为降低 Golden gate 阈值；
- 顺手修改 CR-5 / CR-6 或启动 B1-B7 / Data Sufficiency / backfill；
- commit credentials、Token、真实端点、raw SDK profile/output 或专有 SDK。

## 14. 当前项目状态

```text
Production identity              FROZEN / VERIFIED
GT-H1 structural/tool contract   CLOSED
GT-H1.1 correctness              CLOSED
GT-H1.2 atomic review publish    CLOSED

GT-H2 clean Golden candidate     AUTHORIZED  <- current task
Human full review / GT-H3        BLOCKED
Formal Production B1-B7          BLOCKED
Data Sufficiency                 BLOCKED
Provider capability decision     BLOCKED
2020+ backfill                   BLOCKED
```

下一次交付应是 **GT-H2 clean candidate + review packet PR**。Reviewer 审阅通过并合并后，再单独进入 Human Review / GT-H3；不得跨阶段合并。