# A-share-analysis · 125 条独立二审发现与 GT-H3R2 ST 结构事件整改要求（2026-09-07）

## 1. Reviewer 结论

**INDEPENDENT SECOND REVIEW = NOT PASS / GT-H3B REMAINS BLOCKED**

Owner 已完成 v5 125-case Human Review；项目 Reviewer 按独立第二审阅人标准重新核验时，发现当前 `v5-candidate-20260907` 的 ST 结构事件中存在一类系统性语义错误：若证券在目标日期前已经处于 ST/其他风险警示状态，而目标日期只是从 `ST` 升级为 `*ST`（或叠加退市风险警示），当前若仍记为 `event_subtype=ST_ADD`，会把“风险警示内部状态变化”错误计成“从非 ST 进入 ST”的结构性新增事件。

这会直接影响 `ST_TRANSITION` distinct ADD 的真实性，因此在整改完成前不得执行 GT-H3B atomic seal。

## 2. 已确认的 P0 错误样本

独立二审已确认下列 v5 case 在 effective date 前已经处于 ST/风险警示状态，目标日期属于 `ST -> *ST` 或风险警示层级叠加，不应计作 binary `IS_ST_SEC: false -> true` 的 `ST_ADD`：

1. `GT-H2-ST-ST_ADD-600654-20220506`
2. `GT-H2-ST-ST_ADD-002113-20200429`
3. `GT-H2-ST-ST_ADD-000806-20220506`
4. `GT-H2-ST-ST_ADD-002781-20220506`
5. `GT-H2-ST-ST_ADD-000606-20220506`
6. `GT-H2-ST-ST_ADD-000410-20220419`
7. `GT-H2-ST-ST_ADD-002433-20230505`
8. `GT-H2-ST-ST_ADD-002086-20230505`
9. `GT-H2-ST-ST_ADD-300167-20240430`
10. `GT-H2-ST-ST_ADD-000525-20240919`
11. `GT-H2-ST-ST_ADD-300209-20240429`
12. `GT-H2-ST-ST_ADD-300108-20240430`

这些 case 的官方材料能够证明目标日期发生了退市风险警示/简称变化，但同时也能证明目标日期前已处于 `ST` 或其他风险警示状态。因此它们可以作为“风险警示层级变化”事实，但不能计入当前 binary ST transition 的 `ST_ADD` 结构计数。

## 3. 冻结语义：ST_TRANSITION 必须表达 binary 状态转换

从本裁决开始，`ST_TRANSITION` 的计数语义明确冻结为：

- `ST_ADD`: effective date 前一可确认状态 `IS_ST_SEC=false`，effective date 起 `IS_ST_SEC=true`；
- `ST_REMOVE`: effective date 前一可确认状态 `IS_ST_SEC=true`，effective date 起 `IS_ST_SEC=false`；
- `ST -> *ST` 不得计作 `ST_ADD`；
- `*ST -> ST` 不得计作 `ST_REMOVE`；
- “其他风险警示 + 退市风险警示叠加/解除其中一层”若 binary `IS_ST_SEC` 未改变，不得计入 ADD/REMOVE；
- 如果未来研究需要保存 ST 与 *ST 之间的层级变化，应另建独立事件语义，不得污染当前 `ST_TRANSITION` 的 binary 计数。

`trade_date` 仍不得替代真实 `event_effective_date`。

## 4. GT-H3R2 执行范围

### 4.1 全量复核当前 50 条 ST_TRANSITION

不能只修上面 12 条。开发者必须对 v5 当前全部 50 条 ST transition 做统一口径的 transition audit，逐条记录：

- `golden_case_id`
- `provider_symbol`
- `event_subtype`
- `event_effective_date`
- `pre_effective_is_st`
- `effective_is_st`
- PRE-STATE 官方证据定位
- EFFECTIVE-STATE 官方证据定位
- `transition_valid=true/false`
- 简短判断说明

建议形成独立整改 ledger，例如：

`docs/golden/gt_h3/remediation/GT_H3R2_ST_TRANSITION_AUDIT.jsonl`

这只是 build/review evidence ledger，不要求为了此次整改扩张 runtime Golden schema。

### 4.2 对已确认 invalid case 的处理

- 不允许在 v5 文件上原地修改；v5 保持历史候选快照。
- 从 v5 治理性重建下一 clean candidate（预期 `v6-candidate-*`，实际名称由现有 versioning 工具生成/校验）。
- 上述 invalid ST_ADD 不得继续作为 ST_ADD 结构事件计数。
- 可以 DROP / REPLACE，但必须保留明确 lineage。
- 若替换，需要使用真实、独立、官方一手材料能够证明 `non-ST -> ST` 的结构事件。
- 禁止为了凑够 50 条而使用 Provider-under-test 输出、搜索摘要、媒体报道或重复观察行充数。

### 4.3 数量门仍然保持，不降低门槛

整改后的 clean candidate 仍需满足：

- ST_TRANSITION structural distinct >= 50；
- ADD > 0；
- REMOVE > 0；
- 每一个 ADD/REMOVE 都是实际 binary 状态转换；
- structural identity 仍按 `(provider_symbol, event_effective_date, event_subtype)`；
- event_id / observation count 不得膨胀计数。

如果清除 invalid case 后不足 50 条，应新增真实、独立有据的结构事件；不得降低数量门或重新定义 ADD 以制造通过。

## 5. 低复杂度防回归要求

不要求现在建设复杂状态机。只需增加一个明确的候选构建/整改前置 gate：

- ST_ADD 必须有 `pre=false -> effective=true` 的审核证据；
- ST_REMOVE 必须有 `pre=true -> effective=false` 的审核证据；
- transition ledger 任何 `false` / 缺失 / 证据不完整 => candidate publication fail closed；
- 增加针对 `ST -> *ST must not count as ST_ADD`、`*ST -> ST must not count as ST_REMOVE` 的回归测试。

不要修改 `review.py` 来“兼容”错误 truth，也不要使用 `expect_fields` 修真值。

## 6. 125 条二审的其余结论边界

截至本次 P0 发现：

- LIMIT_REGIME 30 条：独立二审未发现新的制度比例/边界真值错误；
- Corporate Action 25 条：已复核范围未发现新的确定性 truth error；
- DELIST 20 条：已复核范围未发现新的确定性 truth error；
- ST_TRANSITION：发现上述系统性 P0，故完整 125/125 Independent PASS 不成立。

因为 ST structural truth 已经阻塞 seal，本轮不以“其余大类看起来正确”替代最终 125/125 关闭。GT-H3R2 完成后，Reviewer 对新 candidate 做增量独立复核：

1. 校验全部 50 条 ST transition audit；
2. 对新增/替换的 ST case 独立复核官方证据；
3. 对其余未改 case 校验 review identity / semantic identity 未变；
4. 只有不存在 `REJECT / NEED_MORE_EVIDENCE` 才关闭 Independent Second Review。

## 7. Human Review / carry-forward

Owner 之前的人类审核结论继续作为历史审阅记录，不因本次 Reviewer 发现而抹除。

下一 candidate：

- 未改 case 若 review identity 完全一致，可继续 carry-forward Owner 的 Human Review；
- 被删除、替换、日期/来源/expected semantics 改动的 case 不得 carry-forward；
- 仅对实际发生变化的新/替换 case 重新请求 Owner Human Review，不重新让 Owner 审全部 125 条。

## 8. GT-H3R2 PR 验收条件

PR 必须至少证明：

1. v5 immutable；
2. 50 条 ST transition 全量 audit 完成；
3. 上述 12 条 confirmed-invalid case 已全部正确处理；
4. 未发现的同类 false ADD/REMOVE 也一并处理；
5. 下一 clean candidate 结构门全部通过；
6. 125 总体 Golden 数量与其他类型语义无意外漂移；
7. carry-forward 仅发生在 review identity 完全不变的 case；
8. changed/new ST case 有官方一手证据；
9. Windows 3.14 / Windows 3.12 / Ubuntu 3.14 三套 required CI 全绿；
10. final-head + current-main test-merge CI 完成后，由独立 Reviewer closure，方可 merge。

## 9. 当前项目状态

```text
Owner Human Review               historical record retained
Independent Second Review        NOT PASS (ST structural P0 found)
GT-H3R2 ST remediation           CURRENT TASK
GT-H3B atomic seal               BLOCKED
review.py seal                   BLOCKED
Formal Production B1-B7          BLOCKED
Data Sufficiency                 BLOCKED
Provider capability verdict      BLOCKED
2020+ backfill                   BLOCKED
```

下一次开发更新后，Reviewer 只审 GT-H3R2 增量与 ST transition 全量 audit，不重新打开已经关闭的 GT-H2/GT-H3R 基础机制。