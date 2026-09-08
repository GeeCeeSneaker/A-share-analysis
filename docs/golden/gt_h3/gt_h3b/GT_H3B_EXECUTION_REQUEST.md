# GT-H3B 受控真实执行请求

日期：2026-09-08

## 目的

本文件是 PR ops/gt-h3b-controlled-execution-20260908 的执行请求记录，不是成功回执，也不代表 Golden 已经激活或封版。

执行基线为 main@36d238a97f1d1fbadd3a8f5f7b74c13d6c0be096。工作流只在该专用同仓库 Pull Request 上运行，并且不读取或提交 Provider 凭据。

## 受控顺序

1. Phase A：调用已通过 Reviewer 审阅的 candidate.py promote-existing，重新验证 v4/v5/v6 bytes、v5→v6 plan、110/15 carry-forward、50/50 ST audit，并原子推进 ACTIVE 到冻结 v6。
2. Phase B：严格按冻结的 v6_case_evidence_source_contract.jsonl 获取 HTTP 200 的官方 HTTPS 原始响应；普通 case 保存原始 HTML/PDF，5 个复合 case 生成有序、不可压缩、确定性的 RULE → APPLICABILITY bundle。
3. Phase C：构造 125-entry、无 expect_fields 的 review manifest，仅在证据、来源绑定、覆盖、hash 和 loader gates 全部通过后调用 review.py --reviewer project-owner 一次性 seal。

## 安全边界

- 任意官方来源失败、反爬挑战、非官方跳转、内容超过安全上限或证据/hash 不一致均立即 BLOCK；不得静默换源。
- 运行器只写同一 PR 分支，不写 main；只有 PR 审阅/合并后结果才会进入主分支。
- 若执行成功，生成 GT_H3B_EXECUTION_RECEIPT.json、DEVLOG/Management 成功记录和 review/evidence 输出；若失败，不产生可合并的成功回执。
- 账号、密码、Token、Cookie、IP、SDK wheel、Provider-under-test 输出及任何其他敏感数据均不入库。
- 本 PR 不执行 Formal Production B1-B7、Provider capability verdict、Data Sufficiency、2020+ backfill、策略/回测或交易工作。
