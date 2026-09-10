# Trading Rule H1R3 来源合同修正执行记录

日期：2026-09-10（Asia/Shanghai）
状态：`H1R3 CANDIDATE STAGED / SOURCE CONTRACT CLOSED FOR 2020-08-24 / BUNDLE VERIFIED / HUMAN REVIEW PENDING / NOT SEALED`

> **H1R4 后续（2026-09-10）**：H1R3 的 BSE 第 14 条逐条来源绑定问题已在新建 `v20260910-h1r4-compiled` 中按最小范围修正；H1R4 的 candidate/bundle/input/catalog 与授权 AI 审阅状态见 [`TradingRule_H1R4_授权AI审阅记录_20260910.md`](TradingRule_H1R4_授权AI审阅记录_20260910.md)。H1R3 本记录保留为历史 checkpoint，不作为最终 seal 候选；身份必须记录为 `owner-authorized-ai-reviewer`，而非人工/Owner 本人审阅。

> **后续状态（2026-09-10）**：PR #36 已通过独立 re-review 并合并到 `main@f0bf1f8233fedfeea4fa3010237589938f6a5daf`。H1R3 已从 source-contract checkpoint 进入最终 evidence/seal 通道；候选、证据包和旧版本身份继续冻结，14 行正式人工表仍待真实 Reviewer 填写。AI 辅助原文定位见 [`TradingRule_H1R3_AI原文核验草案_20260910.md`](TradingRule_H1R3_AI原文核验草案_20260910.md)，不构成人工批准。

## 1. 修正原因与范围

独立实质审阅指出，H1R2 已有的两份创业板来源能够证明改革前后规则语义和 20% 数值，但不能单独证明 `2020-08-24` 这个精确切换日期。该缺口影响以下四条规则：

- `CHINEXT_PRE_REGISTRATION_NORMAL`（`effective_to=20200823`）；
- `CHINEXT_PRE_REGISTRATION_ST`（`effective_to=20200823`）；
- `CHINEXT_REGISTRATION`（`effective_from=20200824`）；
- `CHINEXT_REGISTRATION_FIRST5`（`effective_from=20200824`）。

本记录只补充深圳证券交易所 2020-08-21 官方问答，不改变任何涨跌幅、代码范围、`st_state`、上市日计数或其他交易语义；不做额外历史研究。

## 2. 新建候选与不可变基线

- 分支从 clean `main@e096b0364d3dc5a00e21879fe5bd8fc4a758b07f` 建立。
- 旧 ACTIVE `v20260824-compiled` 的 dataset hash `dd2219d2383b01d2b8a5019ddf713d36a04f1badbeabe1aeffc7e20fa91ef2d8` 未改变。
- 旧 H1 candidate `v20260909-h1-compiled`、H1R2 candidate `v20260909-h1r2-compiled`、Golden v7 和 ACTIVE selector 未修改。
- 新建 [`v20260910-h1r3-compiled/rules.yaml`](../../configs/trading_rules/versions/v20260910-h1r3-compiled/rules.yaml)，dataset version `2026-09-10.1`，14 条，`COMPILED`、非 `ACTIVE`。
- H1R3 candidate manifest-style SHA-256（`versions/v20260910-h1r3-compiled/rules.yaml` 路径 + 原始 bytes）为 `f2ca5504f8282cc25941b910593b8548160b1dabdffe5e9666093b6a3807ebf9`。
- 对 H1R2 做逐条比较后，14 条规则的交易语义字段完全相同；只有上述四条的 `source_ref` 各增加同一份日期来源。

## 3. 官方原文与证据包

新增来源：<https://www.szse.cn/aboutus/trends/news/t20200821_580924.html>

- 直连响应 HTTP 200，最终 URL 未跳转，`Content-Type: text/html`；原始文件为 [`direct_17.html`](../provider_verification/trading_rule_h1_sources/direct_17.html)，34,508 bytes，SHA-256 `cba74610a5c582e2ac94f3bb21a04f2e5fa1fa175131b0cd287f9bbfc311b1ae`。
- 官方页面标题为“深交所新闻发言人就创业板改革并试点注册制相关问题答记者问”，页面日期为 2020-08-21；正文直接写明“2020 年 8 月 24 日起，《深圳证券交易所创业板交易特别规定》正式施行”，并说明创业板存量股票涨跌幅限制于 8 月 24 日调整为 20%。
- 新来源已加入 [`trading_rule_h1r3_evidence_input_20260910.json`](../provider_verification/trading_rule_h1r3_evidence_input_20260910.json) 的上述四个 `rule_id`，每条各出现一次，角色为 `TRANSITION`；候选 `source_ref` 与 input 的 URL 集 exact match。
- 20 个来源的 HTTP 状态、原始字节 hash/size 和来源关系见 [`trading_rule_h1r3_source_catalog_20260910.json`](../provider_verification/trading_rule_h1r3_source_catalog_20260910.json)。
- 由 H1R3 input 重新生成 20 个去重 raw artifact，合计 `1,736,924` bytes；canonical bundle 为 `18,181` bytes，发布引用与 hash 均为：`sha256/41600f428076024c81e72372a15be738cce592aba8cbd424c9b404448eaa9cee`。
- H1R2 的旧 canonical bundle `sha256/14f09ed0707b0ef1d84ae2dbe880f87bdd186d0c21e61e6387f26fa41bd403d0` 未作为孤立/过期输出保留在本分支；原有内容寻址 raw artifact 仅在字节完全相同时复用。

## 4. 已执行校验

以下结果均为只读或确定性准备/校验，不是人工批准：

```text
TradingRuleBook.load(H1R3 candidate): pass, 14 rules, COMPILED, non-ACTIVE
prepare_rule_evidence_bundle(H1R3 input): pass, 14/14 rules, 20 URLs, 20 raw artifacts
validate_rule_evidence_bundle(H1R3 bundle): pass, required URL exact coverage, hash, size, path confinement
H1R3 candidate source-contract regression tests: pass
```

## 5. 人工审阅、seal 与 Formal 边界

- H1R3 人工表为 [`TradingRule_H1R3_人工审阅操作表_20260910.md`](TradingRule_H1R3_人工审阅操作表_20260910.md)，14 行结果仍为 `待填`。
- 不能把本次 HTTP/哈希/结构校验写成 `APPROVE`，也不能把独立审阅意见当作 14 条人工原文裁决。
- 未运行 `scripts/rules/review.py --candidate`，未创建 `v20260910-h1r3-reviewed`，未切换 ACTIVE，未启动或消耗 Formal Production；B1-B7 继续禁止。
- 账号、密码、IP、端口、Token、Cookie、profile、Provider 原始输出和专有 SDK/runtime 文件未写入 GitHub。

后续顺序：独立 Reviewer 重新检查 H1R3 source contract、四条创业板边界、candidate/bundle/raw 不可变性并合并本 checkpoint；合并后再进行 14/14 人工原文裁决，另开最终 evidence/seal PR；只有 REVIEWED 合并且从届时最新 clean main 完成 preflight 后，才重新评估 Formal B1-B7。
