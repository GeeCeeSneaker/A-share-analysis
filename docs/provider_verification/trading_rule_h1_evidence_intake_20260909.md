# Trading Rule H1R2 证据接收与 Formal 预检记录

日期：2026-09-09（Asia/Shanghai）
源码基线：`main@a797f1186209e7548167e2fa652ce78715f24180`
候选：`v20260909-h1r2-compiled` / dataset version `2026-09-09.2`
候选 manifest-style SHA-256：`6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f`

本记录已由 H1R2 来源合同整改更新。此前 H1R1 intake 的候选字节、1998 起点材料和旧 bundle 数字仅作为本 PR 的历史接收事实；它们不再是当前候选的放行依据。旧 `v20260909-h1-compiled/rules.yaml` 已恢复并保持与 `main` 字节一致，H1R2 使用独立目录。

## 1. Formal Production 前置结果

在新的 detached clean checkout 中确认：

- `git rev-parse HEAD` 为上述 current-main 合并提交；
- `git status --porcelain` 为空；
- Windows Python `3.14.6`；AmazingData `1.1.9`；`tgw` `1.0.9.2`；TGW runtime `V4.3.0.260626-rc2.0-YHZQ`；
- 本次在线预检重新得到 `NETWORK_REACHABLE=REACHABLE`、`AUTHENTICATED=YES`、`QUERY_READY=YES`；脱敏 profile 为 `UNKNOWN_24e2ff401792`，与冻结值一致；
- 通过 SH 交易日历实际读取 8,722 个日期；当前本地日期为 `20260909`，最近一个不含当天的完整交易日为 `20260908`。

**程序性偏差记录**：Issue #34 已明确要求 H1 阶段不得启动、重试或消耗 Formal Production B1-B7。此前仍曾误调用正式入口：

```text
uv run python scripts/spike/spike_runner.py --production --date 20260908
```

运行器在创建 `SpikeRun` 之前因 ACTIVE trading rules 为 `COMPILED` 而拒绝：

```text
PRODUCTION run refused: trading rule dataset not reviewed
```

因此：没有 `run_id`、没有 B1-B7 结果、没有 verdict，也没有消耗正式单次 attempt。不能把这次前置拒绝记作 Provider `FAILED` 或 `NO-GO`。但该调用不符合 Issue #34 的流程约束，属于已记录的程序性偏差；在 H1 evidence/seal PR 经独立 Reviewer 审阅并合并前，**不得再次调用 Formal Production 入口**。

## 2. H1 原文接收结果

已按 H1R2 候选枚举 19 个唯一官方 URL，并将当前使用来源保存到本目录下的 `trading_rule_h1_sources/`：

- 14 个直接来源材料保存为原始 HTTP 200 HTML/PDF 字节；
- SSE 2026 交易规则、SZSE 2020 创业板特别规定和 3 个 BSE 来源的发布页是 locator/notice page；H1R2 的 `source_ref` 与 evidence input 直接绑定实际规则正文 DOCX/PDF 的 URL，发布页只在 catalog 的 `source_page_url` 中作为来源关系元数据保留；
- 3 个 BSE 必需页面的直连请求返回自指向 302/WAF challenge，未把 challenge 响应或渲染 DOM 当作证据；通过官方页面下载的 3 份原始 DOCX 附件已保存，附件响应均为 HTTP 200，H1R2 的 `source_ref` 与 evidence input 直接绑定附件 URL；
- 对 BSE `200010908`，发布页的 `source_page_kind` 是 `EXCHANGE_NOTICE`，但留存的链接附件是规则正文，因此 evidence input 的 `artifact_kind` 明确为 `EXCHANGE_RULEBOOK`；页面与附件不再混为同一材料；
- 原先的 SSE `direct_05` 页面正文只证明低价风险警示股票的最小变动单位，不能直接证明 5% 条款，已改用官方《风险警示板股票交易暂行办法》原文；H1R2 不再把 1998 年历史起点作为 P0 事实，改为 2020-01-01 起的研究范围；
- 原先 `MAIN_BOARD_IPO_DAY` 错把不含 44%/36% 条款的 SSE 历史规则页列为 RULE 来源；现已改绑 SSE 2014 通知与 SZSE 2014 问答，两份原文均直接写出 144%/64%，并保留独立的 2023 过渡/首批上市来源用于终止边界裁决；
- 所有来源的 URL、来源页/附件关系、传输状态、归档方式、字节数、SHA-256 和抽取统计见 [`trading_rule_h1_source_catalog.json`](trading_rule_h1_source_catalog.json)。

原 H1R1 的 `direct_06` / `direct_07` 历史材料仍留在工作区供未来非阻断性历史研究，但不属于 H1R2 的 2020+ source contract；当前 catalog 和 bundle 只统计 H1R2 使用的 19 个来源。

输入 bundle 已按 14 个且仅 14 个 `rule_id` 生成并通过纯校验（没有发布副作用）：

- bundle bytes：16,557；bundle SHA-256：`14f09ed0707b0ef1d84ae2dbe880f87bdd186d0c21e61e6387f26fa41bd403d0`；
- 去重后的 raw artifact：19 个；合计 1,702,416 bytes；
- 输入文件：[`trading_rule_h1_evidence_input.json`](trading_rule_h1_evidence_input.json)。

## 3. 尚未完成、不得跳过的事项

本记录不等于 H1 人工审阅，也没有写入 `APPROVE`、`REJECT`、`REVIEWED` 或 ACTIVE 切换。项目管理者/独立 Reviewer 仍需：

1. 实际打开 H1R2 的 14 条所需官方原文，逐条按 [`TradingRule_H1_人工审阅操作表_20260909.md`](../design/TradingRule_H1_人工审阅操作表_20260909.md) 填写结果、条款/页码和简短理由；
2. 重点裁决 2020-01-01 起主板 ST 5% 与 2026-07-06 切换、主板 IPO 44/36 终止边界、创业板 2020-08-24 改革、BSE venue 起点，以及每条 `RULE` 来源是否确实包含所声明条款；本轮不把 1998 年起点作为 H1R2 放行条件；
3. 只有 14/14 `APPROVE` 且 Reviewer 关闭 2020+ 边界测试、来源绑定和两个 COMPILED candidate 不可变性后，才允许在受控环境运行 `scripts/rules/review.py --candidate ... --evidence-bundle ...` 创建新的 REVIEWED 版本；
4. REVIEWED 版本独立审阅并合并后，再从届时最新 clean `main` 重做 preflight，并重试尚未消耗的唯一 Formal Production B1-B7。

账号、密码、真实 endpoint、Token、Cookie、原始 profile 和 SDK 原始输出未写入本记录、输入 bundle 或 Git。
