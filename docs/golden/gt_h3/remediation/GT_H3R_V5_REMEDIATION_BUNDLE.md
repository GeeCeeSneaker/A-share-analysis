# GT-H3R v5 候选整改交接包

> 状态：**V5 CANDIDATE PREPARED / 12-CASE HUMAN RE-REVIEW PENDING / NOT SEALED**
>
> 本交接包只记录管理裁决后的候选重建和人工复审入口，不包含证据文件、不写入 `REVIEWED`，也不运行 `review.py`。

## 审阅人先看什么

1. 先看 `GT_H3R_V5_REMEDIATION_REPORT.md`，确认本次只改 12 条被拒案例。
2. 再打开 `GT_H3R_V5_REVIEW_TABLE.xlsx` 或同名 Markdown 表，逐行打开“官方链接”，阅读官方原文。
3. 每行只在“结果”填写 `APPROVE` 或 `REJECT`；不一致、链接失效或原文不能证明事实时填 `REJECT`，并在“简短反馈”写明原因。
4. 完成 12 行后，由真实 Owner/Human Reviewer 在 PR 评论中明确写出：12/12 结果、113 条沿用确认、`50` 已中和/定义，以及最终 human marker。

## 候选绑定

| 项目 | 值 |
|---|---|
| v4 source | `v4-candidate-20260906` |
| v4 dataset SHA256 | `8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b` |
| v5 candidate | `v5-candidate-20260907` |
| v5 dataset SHA256 | `5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c` |
| rows | `125` (`COMPILED 125/125`) |
| prior APPROVE carry-forward | `113`，机器校验通过后沿用 |
| corrected rows for re-review | `12`，不得自动批准 |

## 复审范围

- AG-054（5 条）、AG-025（2 条）、AG-029（2 条）、AG-064（1 条）：只换官方来源定位，expected semantics 不变。
- AG-027（1 条）：将 688981.SH 2020-07-23 改为上市后第 6 个交易日的 STAR 20% 首个受限日案例，保留 2020-07-22 的无涨跌幅边界案例。
- AG-096（1 条）：将 300965.SZ 的 ST_ADD 生效日/交易日改为 2024-04-26，expected `IS_ST_SEC=true` 不变。

机器校验脚本为 `scripts/golden/gt_h3_remediate.py verify`。它同时确认 v4 文件哈希未变、v5 只有上述两条 rekey、10 条证据-only 语义未变、113 条 carry-forward 合格以及 12 条未自动沿用。

## 复审完成前不得做的事

- 不要把表格结果直接写入 Golden dataset；不要填写 `REVIEWED` 或证据 hash。
- 不要运行 `review.py`、GT-H3B、Formal Production B1-B7、Data Sufficiency、Provider capability、backfill、策略、回测或交易流程。
- 不要把账号、密码、IP、Token、原始 SDK 输出或专有依赖提交到仓库。

只有整改 PR 独立审阅并合并、12 条全部重新 APPROVE、113 条 carry-forward 通过、`50` 被明确中和/定义且提供最终 human marker 后，才能申请 v5 完整 125/125 授权并进入 GT-H3B。
