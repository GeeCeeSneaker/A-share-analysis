# Trading Rule H1 证据接收与 Formal 预检记录

日期：2026-09-09（Asia/Shanghai）
源码基线：`main@a797f1186209e7548167e2fa652ce78715f24180`
候选：`v20260909-h1-compiled` / dataset version `2026-09-09.1`
候选 manifest-style SHA-256：`75d21777f1f135c47b963868641dfffc5428c5c5d897e17480a91ebaec1edd51`

## 1. Formal Production 前置结果

在新的 detached clean checkout 中确认：

- `git rev-parse HEAD` 为上述 current-main 合并提交；
- `git status --porcelain` 为空；
- Windows Python `3.14.6`；AmazingData `1.1.9`；`tgw` `1.0.9.2`；TGW runtime `V4.3.0.260626-rc2.0-YHZQ`；
- 本次在线预检重新得到 `NETWORK_REACHABLE=REACHABLE`、`AUTHENTICATED=YES`、`QUERY_READY=YES`；脱敏 profile 为 `UNKNOWN_24e2ff401792`，与冻结值一致；
- 通过 SH 交易日历实际读取 8,722 个日期；当前本地日期为 `20260909`，最近一个不含当天的完整交易日为 `20260908`。

随后按唯一正式入口尝试：

```text
uv run python scripts/spike/spike_runner.py --production --date 20260908
```

运行器在创建 `SpikeRun` 之前因 ACTIVE trading rules 为 `COMPILED` 而拒绝：

```text
PRODUCTION run refused: trading rule dataset not reviewed
```

因此：没有 `run_id`、没有 B1-B7 结果、没有 verdict，也没有消耗正式单次 attempt。不能把这次前置拒绝记作 Provider `FAILED` 或 `NO-GO`。

## 2. H1 原文接收结果

已按候选和输入模板枚举 19 个唯一官方 URL，并将来源保存到本目录下的 `trading_rule_h1_sources/`：

- 16 个 URL 由直接 HTTPS 请求返回 HTTP 200，保存原始 HTML/PDF 字节；
- 3 个 BSE 必需 URL 的直接请求返回自指向 302/WAF challenge，未把 challenge 响应当作证据；
- 3 个 BSE 页面随后使用隔离 Chrome profile 执行页面 challenge，得到浏览器解析后的完整官方页面 DOM，分别对应 `200010919`、`200010908`、`200028217`。这三份文件在 catalog 中明确标为 `browser_resolved_dom`，不是未经说明的 HTTP 200 原始响应，必须由 Reviewer 确认其是否满足项目的“原文/原始字节”要求；如不接受，应由管理者提供浏览器下载的原始 HTML/PDF/DOCX，再替换对应文件并重算 hash。
- 直接取得的 PDF 已在本地完成全文抽取检查；来源 URL、传输状态、归档方式、字节数、SHA-256 和抽取统计见 [`trading_rule_h1_source_catalog.json`](trading_rule_h1_source_catalog.json)。

输入 bundle 已按 14 个且仅 14 个 `rule_id` 生成并通过纯校验（没有发布副作用）：

- bundle bytes：15,886；bundle SHA-256：`a63b652ab08dda4cc12bd20716131ed3eff3b6f7845ddb6b1fa3af3462c33aa`；
- 去重后的 raw artifact：19 个；合计 3,232,349 bytes；
- 输入文件：[`trading_rule_h1_evidence_input.json`](trading_rule_h1_evidence_input.json)。

## 3. 尚未完成、不得跳过的事项

本记录不等于 H1 人工审阅，也没有写入 `APPROVE`、`REJECT`、`REVIEWED` 或 ACTIVE 切换。项目管理者/独立 Reviewer 仍需：

1. 实际打开 14 条所需的全部官方原文，逐条按 [`TradingRule_H1_人工审阅操作表_20260909.md`](../design/TradingRule_H1_人工审阅操作表_20260909.md) 填写结果、条款/页码和简短理由；
2. 特别裁决主板 ST 的 1998 起点与 2026-07-06 切换、主板 IPO 44/36 终止边界、BSE venue 起点，以及 BSE 浏览器归档是否属于可接受的原文证据；
3. 只有 14/14 `APPROVE` 且 Reviewer 关闭边界测试、来源绑定和旧 candidate 不可变性后，才允许在受控环境运行 `scripts/rules/review.py --candidate ... --evidence-bundle ...` 创建新的 REVIEWED 版本；
4. REVIEWED 版本独立审阅并合并后，再从届时最新 clean `main` 重做 preflight，并重试尚未消耗的唯一 Formal Production B1-B7。

账号、密码、真实 endpoint、Token、Cookie、原始 profile 和 SDK 原始输出未写入本记录、输入 bundle 或 Git。
