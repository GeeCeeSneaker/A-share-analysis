# PR #20 GT-H3R.1 Reviewer 补充说明

> 状态：**SUPPLEMENT TO CANONICAL REVIEW / DO NOT MERGE**

本文件不是独立的第二套首轮复审基线。PR #20 的权威 Reviewer 管理裁决是：

`docs/design/A-share-analysis_PR20首轮复审与GT-H3R.1证据完整性及审计历史收口要求_20260907.md`

对应 main commit：`f623d44094972855601a2f520184062b4ff7944d`  
对应 Reviewer review：`5130019385`

本轮补充 Reviewer review `5130031817` 进一步明确：权威裁决中的“复合事实证据完整性”除 AG-029×2、AG-027×1 外，还应显式覆盖 **AG-025×2**。

## AG-025 补充约束

`GT-LIMIT-ST5-600518-20190603` 与 `GT-LIMIT-ST5-600518-20191028` 当前 SSE 风险警示板规则只能证明“风险警示股票适用 5%”，不能单独证明 `600518` 在两个 observation date 的确处于 ST/风险警示状态。

因此 delta Human Review 必须同时具备：

1. RULE：SSE 风险警示板 5% 官方规则；
2. APPLICABILITY：能够覆盖相应 observation date 的 SSE official 状态材料。

已定位的 SSE 2019-06-03 官方指数调整公告直接列出 `600518 | ST康美`，可作为 2019-06-03 的状态佐证：

`https://www.sse.com.cn/market/sseindex/diclosure/c/c_20190531_4830732.shtml`

2019-10-28 仍必须有能够覆盖该日期的 official applicability artifact；如果一份 SSE official material 明确记录 600518 自 2019-05-17 起实施其他风险警示并覆盖该状态，可由 Human Reviewer 检查后同时支持两个 case。

## 其他补充 locator

- AG-027 / 688981 listing applicability：
  `https://www.sse.com.cn/disclosure/announcement/listing/c/c_20200713_5152912.shtml`
- AG-029 / 605499 listing applicability：
  `https://www.sse.com.cn/disclosure/announcement/listing/ipo/c/c_20210526_81718214.shtml`
- AG-029 / 601995：仍要求定位 exact SSE official listing/applicability artifact，或稳定且明确写出 `601995` 于 `2020-11-02` 上市的 SSE official retrospective evidence。

除上述补充外，所有 exit gates、PR #19 审计历史恢复要求、GT-H3A snapshot 保留要求、final-head governance sync、PR body v4 hash 修正以及 NOT SEALED 边界均以 `f623d440...` 的权威文档为准。
