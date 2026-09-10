# Trading Rule H1R3 AI 原文核验草案

日期：2026-09-10（Asia/Shanghai）
适用候选：`v20260910-h1r3-compiled`（dataset `2026-09-10.1`）
当前基线：`main@f0bf1f8233fedfeea4fa3010237589938f6a5daf`
候选 manifest-style SHA-256：`f2ca5504f8282cc25941b910593b8548160b1dabdffe5e9666093b6a3807ebf9`

## 重要性质

这是一份 AI 辅助原文核验草案，不是人工审阅结果，不是 `APPROVE` 授权，也不产生 `reviewed_by`、human marker、REVIEWED 版本或 ACTIVE 变更。项目 Owner/真实人工 Reviewer 仍必须逐条打开官方原文，在正式表 [`TradingRule_H1R3_人工审阅操作表_20260910.md`](TradingRule_H1R3_人工审阅操作表_20260910.md) 中填写最终 `APPROVE`/`REJECT`、条款/页码/定位和简短理由。

本草案只用于帮助审阅人定位原文和识别需要特别注意的边界；不能替代人工阅读，也不能直接作为封印命令的输入结论。

## 核验方法与已确认事实

- 按 H1R3 evidence input 的 14 个 `rule_id` 读取全部 20 个唯一官方原始 artifact；未用搜索摘要、接口摘要或 AI 总结代替原文。
- 每个 artifact 均完成完整字节读取，并与 source catalog 的 SHA-256/size 比对；HTML 做全文提取，PDF 用 `pypdf` 提取全文，DOCX 用 `python-docx` 提取全文。
- PDF 关键页已做视觉检查：SZSE 现行规则第 13 页、科创板规则第 5 页、创业板特别规定第 1 页，文字和版面可读。
- DOCX 的完整文本已读取，但当前环境缺少可用的 LibreOffice/`soffice`，没有把 DOCX 标记为“视觉渲染通过”；人工 Reviewer 应以官方 DOCX 原文自行打开确认。
- 证据合同目前为 20 个唯一官方 URL、20 个 raw artifact、1,736,924 bytes；canonical bundle 为 `sha256/41600f428076024c81e72372a15be738cce592aba8cbd424c9b404448eaa9cee`（18,181 bytes）。这些是机器完整性事实，不是人工事实裁决。

## 14 条逐案核验导航

“AI 预核验”只表示本地读取的原文与候选语义相容；“人工最终结果”必须由真实 Reviewer 在正式表中填写。

| # | `rule_id` | AI 预核验（非最终裁决） | 原文最小定位 | 人工最终需要确认 |
|---:|---|---|---|---|
| 1 | `MAIN_BOARD_NORMAL` | 支持候选的 10% 普通主板交易语义；当前规则与 2020+ 覆盖相容 | `direct_01.html` §3.4.13；`direct_02.html` §3.3.14；`sse_10816482_rules.docx` §3.3.13；`direct_04.pdf` p.13 §3.3.13 | 主板 venue/代码前缀、`20200101` 研究窗口下界及 `st_state=false` 是否被正式证据和候选范围正确解释；不要把历史规则自动当作当前规则 |
| 2 | `MAIN_BOARD_ST_HISTORICAL_SH` | 支持 2020+ 至 2026-07-05 的沪市风险警示 5%，以及 2026-07-06 切换 | `sse_risk_warning_2012.html` §7（5%，2013-01-01 施行）；`direct_08.html`（2026-07-06 起调整） | SH/60xxxx 适用范围、5% 的历史覆盖和 2026-07-06 终止边界；本轮不要求补证 1998 起点 |
| 3 | `MAIN_BOARD_ST_HISTORICAL_SZ` | 支持 2020+ 至 2026-07-05 的深市风险警示 5%，以及 2026-07-06 切换到当前规则 | `direct_02.html` §3.3.14；`direct_09.html`（业务指南自 2026-07-06 施行）；`direct_04.pdf` p.13 §3.3.13 | SZ/000、001、002、003 前缀与主板风险警示范围是否可由候选配置和官方规则共同闭合；本轮不要求补证 1998 起点 |
| 4 | `MAIN_BOARD_ST_CURRENT` | 支持 2026-07-06 起主板风险警示 10%，当前日期不能回落到旧 5% | `sse_10816482_rules.docx` §3.3.13、§4.4.1/§4.4.2；`direct_08.html`；`direct_04.pdf` p.13 §3.3.13；`direct_09.html` | 2026-07-06 生效关系、沪深双市场覆盖、`st_state=true` 和当前日期命中 10% 的解析结果 |
| 5 | `MAIN_BOARD_IPO_DAY` | 支持旧制度上市首日 +44%/−36%；支持 2023-04-09 为旧制度最后一日 | `sse_ipo_2014_notice.html` §I（120%/80%、144%/64%）；`szse_ipo_2014_qa.html` Q1/Q2（144%/64%）；`direct_10.html`、`direct_13.html`；`direct_11.html`（首批注册制主板 2023-04-10 上市） | 沪深两所 144%/64% 到 +44%/−36% 的换算、两所过渡条款以及 2023-04-10 首批上市日如何推出 `effective_to=20230409` |
| 6 | `MAIN_BOARD_FIRST5_NO_LIMIT` | 支持注册制主板 IPO 上市后前 5 个交易日不限价，第 6 个交易日回到普通 10% | `direct_12.html`；`direct_13.html`；`direct_11.html`；`sse_10816482_rules.docx` §3.3.15；`direct_04.pdf` p.13 §3.3.15 | 2023-04-10 生效边界、按交易日而非自然日计数，以及同一条通用 FIRST5 规则对 `st_state=false/true` 的解析；不要臆造独立 ST FIRST5 制度 |
| 7 | `CHINEXT_PRE_REGISTRATION_NORMAL` | 支持改革前普通创业板 10%，且 2020-08-23 是旧制度最后一日 | `direct_02.html` §3.3.14；`direct_14.html`（改革前规则及施行安排）；`direct_17.html`（特别规定自 2020-08-24 起正式施行） | `20200101` 作为研究窗口下界而非法律起始日的含义、普通股票范围，以及 2020-08-24 不得误套改革前 10% |
| 8 | `CHINEXT_PRE_REGISTRATION_ST` | 支持改革前创业板 ST/*ST 为 5%，且 2020-08-23 是旧制度最后一日 | `direct_14.html`（改革前风险警示 5%）；`direct_17.html`（2020-08-24 实施边界） | `st_state=true` 的适用范围、5% 与普通 10% 的区分，以及切换日的方向；不得把 2020-08-24 后的 20% 倒灌到旧区间 |
| 9 | `CHINEXT_REGISTRATION` | 支持注册制创业板普通交易日 20%，自 2020-08-24 起适用并由现行规则继续覆盖 | `szse_chinext_special_rules.pdf` §2.1 p.1；`direct_04.pdf` p.13 §3.3.13；`direct_17.html` | 2020-08-24 一手日期证据、20% 数值、注册制创业板范围和当前规则延续覆盖是否闭合 |
| 10 | `CHINEXT_REGISTRATION_FIRST5` | 支持注册制创业板 IPO 上市后前 5 个交易日不限价，第 6 个交易日适用 20% | `szse_chinext_special_rules.pdf` §2.1 p.1；`direct_04.pdf` p.13 §3.3.13；`direct_17.html` | 必须按交易日计数，确认 FIRST5 与普通 20% 的先后关系、2020-08-24 生效边界和当前规则继续覆盖 |
| 11 | `STAR_MARKET` | 支持科创板普通交易日 20%，且前 5 个交易日之后适用 20% | `direct_16.pdf` §18 p.5；`sse_10816482_rules.docx` §6.1/§6.6（约 paragraphs 356–373） | 科创板 venue/688、689 代码范围、当前规则覆盖，以及普通 20% 与 FIRST5 不限价的规则优先级 |
| 12 | `STAR_MARKET_FIRST5` | 支持科创板 IPO 上市后前 5 个交易日不限价，第 6 个交易日为 20% | `direct_16.pdf` §18 p.5；`sse_10816482_rules.docx` §6.6 | 按交易日计数、FIRST5 适用条件、科创板代码范围和当前规则延续覆盖 |
| 13 | `BSE_LIMIT` | 支持北交所普通交易日 30%，历史规则自 2021-11-15 起并由 2026 现行规则继续覆盖 | `bse_200010919.docx` §3.3.11、§10.6；`bse_200010908.docx` §13.3；`bse_200028217.docx` §3.3.11、§10.6 | BJ venue/代码前缀、2021-11-15 生效起点、2026 现行规则衔接，以及普通交易日不得误命中上市首日无涨跌幅 |
| 14 | `BSE_IPO_DAY_NO_LIMIT` | 条款事实支持：北交所公开发行股票上市首日不限价，后续交易日为 30%；但该行 evidence input 只绑定当前 BSE 2026 DOCX | `bse_200028217.docx` §3.3.11、§3.3.12(a)、§10.6 | 人工必须特别核对候选 `effective_from=20211115` 的历史依据：历史 BSE 交易规则 `bse_200010919.docx` §3.3.12(a)/§10.6 当前绑定在第 13 行而非第 14 行；若项目要求逐行 source contract 直接覆盖起点，应先由项目管理者决定补证/调整绑定，不能默认为已闭合 |

## 人工填写前的两个边界决定

1. **代码前缀不是数值条款本身。** 多数交易所正文以“主板/创业板/科创板/北交所股票”表述，未必逐字列出候选 YAML 的代码正则。人工 Reviewer 应按项目既定的 venue/code mapping 规则审阅；如果其职责要求“同一条官方原文必须逐字列出前缀”，应在正式表中如实记为证据不足并交项目管理者处理，不得用本草案替代该决定。
2. **第 14 行存在来源绑定不对称。** 当前条款正文足以支持“上市首日不限价、后续 30%”，但历史 `20211115` 起点的直接证据落在第 13 行的历史交易规则来源中。是否允许第 13/14 行共享同一历史来源，必须由人审/项目管理者按 source contract 规则裁决；本草案不替他们放行。

## 建议的后续操作

- 人工 Reviewer 逐行打开上表对应的官方页面或仓库 raw artifact，直接填写正式表 14 行。
- 每行写一个最终结果和精确 locator；复合事实至少闭合数值/语义、适用范围、制度切换三类事实。
- 只有正式表 14 行全部为人工 `APPROVE`，并解决第 14 行历史起点绑定和任何代码范围疑问后，才可按文档中的固定参数运行一次 candidate seal。
- 在此之前保持 H1R3 为 `COMPILED`、非 `ACTIVE`；不创建 REVIEWED，不启动 Formal Production，不执行 B1-B7。

本文件不包含任何账号、密码、IP、端口、Token、Cookie、profile 或 Provider 原始输出。
