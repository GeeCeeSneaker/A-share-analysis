# R4-B1.1 Reviewer 补充治理更正（2026-08-30）

> **关联 Reviewer Verdict**：`docs/design/A-share-analysis_R4-B1.1复审与R4-B1.2最终ApprovalBoundary及IndustryEndpoint收口要求_20260830.md`  
> **性质**：P1 文档计数更正；不改变 R4-B1.1 = REOPENED / R4-B1.2 ACTIVE 的裁决。

ADR-020 Amendment C.3 当前写：

```text
SDK_METHOD_CLASSIFICATIONS 表（19 条）
```

Reviewer 按 `CAPABILITY_REGISTRY[*].sdk_methods` 逐项计数并与当前 `SDK_METHOD_CLASSIFICATIONS` 对照：实际为 **18 条**：

```text
trade_calendar             1
security_master            3
code_mapping_bj            1
daily_bar                  1
security_status_history    1
adj_factor                 2
corporate_action           2
equity_structure           1
industry_taxonomy          4
index_daily                2
TOTAL                     18
```

当前结构守卫 `set(registry sdk_methods) == set(classifications)` 能通过，因此这是**治理文档数字错误，不是 runtime contract 缺项**。

下一逻辑开发提交应在 ADR-020 amendment / DEVLOG / management current-truth 同步时将“19 条”更正为“18 条”，保留历史，不改写旧提交。
