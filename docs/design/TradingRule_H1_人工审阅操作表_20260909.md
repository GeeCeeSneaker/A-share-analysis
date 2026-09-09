# Trading Rule H1 人工审阅操作表

适用候选：`configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml`
候选版本：`2026-09-09.1`，共 14 条，当前 `COMPILED`、非 `ACTIVE`。
目的：在不修改候选 YAML 的前提下，逐条打开官方原文，确认规则事实、适用范围和制度切换边界。

## 一、审阅原则

1. 必须实际打开下表的官方页面或 PDF 原文；搜索摘要、接口返回、AI 总结不能替代原文。
2. 每条至少确认“数值/语义 + 生效时间 + 适用市场/股票范围”；复合事实还要确认 `RULE`、`APPLICABILITY`、`TRANSITION` 三类证据是否闭合。
3. 原文无法证明候选值时，填 `REJECT`，备注写明缺少哪一项；不要为了让结果通过而修改规则或放宽证据要求。
4. 只有 14 条全部 `APPROVE`，且每个 `rule_id` 都有至少一个官方来源，才允许用 `--evidence-bundle` 进入封印流程。
5. 评审过程不得填写、保存或提交账号、密码、IP、端口、Token 等运行凭据。

## 二、逐条审阅表

| 序号 | rule_id | 需要确认的具体事实 | 对照的官方原文 | 结果（APPROVE/REJECT） | 原文页码/条款与简短备注 |
|---:|---|---|---|---|---|
| 1 | `MAIN_BOARD_NORMAL` | 沪深主板普通股票日涨跌幅为 10%；代码范围、长期生效语义与 `st_state=false` 一致；当前区间不能只依赖历史规则 | [SSE 历史主板规则](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml)；[SZSE 历史交易规则](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)；[SSE 2026 现行交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 |  |
| 2 | `MAIN_BOARD_ST_HISTORICAL_SH` | 沪市主板风险警示股票在 `19980422`—`20260705` 为 5%；官方沪市历史记录的首次特别处理日期为 1998-04-22；`st_state=true`、SH/60xxxx 适用范围成立 | [SSE 历史风险警示板办法](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20210531_5478105.shtml)；[SSE 官方市场史](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170577/files/ae3c4a6d91b74aacbddc96a4d600f06f.pdf) | 待填 | 需同时确认 1998-04-22 起点与 2026-07-05 终点 |
| 3 | `MAIN_BOARD_ST_HISTORICAL_SZ` | 深市主板风险警示股票在 `19980428`—`20260705` 为 5%；官方深市历史记录的首次特别处理日期为 1998-04-28；`st_state=true`、SZ/000xxx、001xxx、002xxx、003xxx 适用范围成立 | [SZSE 历史交易规则](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)；[SZSE 官方 1998 年大事记](https://www.szse.cn/aboutus/sse/events/t20070328_497832.html) | 待填 | 需同时确认 1998-04-28 起点与 2026-07-05 终点 |
| 4 | `MAIN_BOARD_ST_CURRENT` | 沪深主板风险警示股票自 `20260706` 起为 10%；当前 `20260908` 必须命中 10%，不能命中旧 5% | [SSE 2026 现行交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)；[SSE 2026 风险警示调整公告](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf)；[SZSE 2026 风险警示业务指南公告](https://www.szse.cn/lawrules/service/member/t20260630_621404.html) | 待填 | 必须记录 2026-07-06 生效条款与 10%数值 |
| 5 | `MAIN_BOARD_IPO_DAY` | 旧制度上市首日上限 +44%、下限 −36%；`effective_to=20230409` 是否由官方过渡条款和首批注册制主板上市日直接证明 | [SSE 主板规则](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml)；[SSE 过渡说明](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230217_5716420.shtml)；[SZSE 首批注册制主板上市](https://www.szse.cn/aboutus/trends/news/t20230404_599697.html) | 待填 |  |
| 6 | `MAIN_BOARD_FIRST5_NO_LIMIT` | 注册制主板 IPO 上市后前 5 个交易日不限价，第 6 个交易日回到普通 10%；2023-04-10 的生效语义成立；同一条规则对 `is_st=false/true` 均可解析 | [SSE 首 5 个交易日说明](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230201_5715605.shtml)；[SZSE 主板 IPO 问答](https://investor.szse.cn/knowledge/qa/t20230306_599093.html)；[首批上市](https://www.szse.cn/aboutus/trends/news/t20230404_599697.html)；[SSE 2026 现行交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 | 分别记录普通/ST 两次解析结果；不再要求来源证明不存在的独立 ST FIRST5 规则 |
| 7 | `CHINEXT_PRE_REGISTRATION_NORMAL` | 创业板改革前普通股票为 10%，有效期至 2020-08-23；不得误套改革后的 20% | [SZSE 历史交易规则](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)；[2020-07-10 改革通知](https://www.szse.cn/disclosure/notice/general/t20200710_579459.html) | 待填 |  |
| 8 | `CHINEXT_PRE_REGISTRATION_ST` | 创业板改革前 ST/*ST 为 5%，不是 10%；有效期至 2020-08-23 | [SZSE 2020-07-10 改革通知](https://www.szse.cn/disclosure/notice/general/t20200710_579459.html) | 待填 |  |
| 9 | `CHINEXT_REGISTRATION` | 创业板注册制改革后普通交易日涨跌幅为 20%，生效日 2020-08-24；当前区间由 2026 现行规则继续覆盖 | [创业板交易特别规定](https://www.szse.cn/disclosure/notice/general/t20200612_578381.html)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 |  |
| 10 | `CHINEXT_REGISTRATION_FIRST5` | 创业板注册制 IPO 前 5 个交易日不限价，第 6 日适用 20%；必须按交易日计数，当前区间由 2026 现行规则继续覆盖 | [创业板交易特别规定](https://www.szse.cn/disclosure/notice/general/t20200612_578381.html)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 |  |
| 11 | `STAR_MARKET` | 科创板上市前 5 个交易日后，普通交易日涨跌幅为 20%；代码和交易所范围正确，当前区间由 2026 现行规则继续覆盖 | [科创板交易特别规定 PDF](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf)；[SSE 2026 现行交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml) | 待填 |  |
| 12 | `STAR_MARKET_FIRST5` | 科创板 IPO 上市后前 5 个交易日不限价，第 6 日为 20%；必须按交易日计数，当前区间由 2026 现行规则继续覆盖 | [科创板交易特别规定 PDF](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf)；[SSE 2026 现行交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml) | 待填 |  |
| 13 | `BSE_LIMIT` | 北交所 venue 为 `BJ`；规则自 2021-11-15 起生效；普通交易日为 30%；2021-11-15 前不得静默命中该 BSE 规则；当前区间由 2026 现行规则继续覆盖 | [BSE 历史交易规则](https://www.bse.cn/jygl_list/200010919.html)；[BSE 上市规则施行公告](https://www.bse.cn/cxjg_list/200010908.html)；[BSE 2026 现行交易规则](https://www.bse.cn/jygl_list/200028217.html) | 待填 |  |
| 14 | `BSE_IPO_DAY_NO_LIMIT` | 北交所公开发行股票上市首日不限价，后续交易日为 30%；上市首日必须依赖真实 `listing_date` 与 PIT 日历 | [BSE 现行上市交易规则](https://www.bse.cn/jygl_list/200028217.html) | 待填 |  |

## 三、结果填写规则

每行只填一个最终结果：

- `APPROVE`：原文直接支持候选的数值、语义和时间边界；在最后一列写条款/页码和一句理由。
- `REJECT`：原文与候选冲突、无法覆盖候选，或来源不是官方原文；在最后一列写冲突值或缺失证据。

建议将填好的表格作为评审 PR 的正文或附件提交；不得把账号信息写进表格。若任一行是 `REJECT`，本轮不能运行封印命令，应先形成新的 `COMPILED` 候选并重新评审。

## 四、证据包输入格式

`--evidence-bundle` 接受一个本地 JSON 输入文件。`artifact_path` 相对该 JSON 文件所在目录；原始 HTML/PDF 必须先完整保存到本地。工具会自行计算 SHA-256、字节数，并把发布证据存到 `configs/trading_rules/evidence/sha256/`，不会把本地路径写入发布 bundle。

```json
{
  "schema_version": "RULE_EVIDENCE_BUNDLE.v1",
  "dataset_version": "2026-09-09.1",
  "entries": [
    {
      "rule_id": "MAIN_BOARD_NORMAL",
      "sources": [
        {
          "artifact_path": "sources/main_board_rules.html",
          "source_url": "https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml",
          "artifact_kind": "EXCHANGE_RULEBOOK",
          "role": "RULE"
        }
      ]
    }
  ]
}
```

实际提交时，`entries` 必须包含 14 个且仅包含上述 14 个 `rule_id`；每个 `sources` 必须非空。复合事实按需要为同一条规则提供 `RULE`、`APPLICABILITY`、`TRANSITION` 多个来源。来源 URL 必须是 HTTPS 且属于 SSE、SZSE、BSE、NEEQ 或 CSRC 官方域名。

工具还会把输入中的 `source_url` 与候选 YAML 对应 `rule_id` 的 `source_ref` 中声明的 URL 做精确匹配；不能用另一条规则的官方链接替换。bundle 和 raw artifact 的发布引用必须分别是 `sha256/<bundle_hash>` 与 `sha256/<raw_sha256>`，仅“文件内容能验 hash”但路径未按内容寻址也会被拒绝。

## 五、封印命令与放行条件

人工审阅全部 APPROVE、原文文件已留存后，由项目管理者在仓库根目录运行：

```text
uv run python scripts/rules/review.py \
  --rules configs/trading_rules/versions/v20260909-h1-compiled/rules.yaml \
  --evidence-bundle docs/provider_verification/trading_rule_h1_evidence_input.json \
  --reviewer "稳定的人审标识" \
  --version v20260909-h1-reviewed \
  --from-version v20260909-h1-compiled
```

命令会在发布前检查：规则 ID 精确集合、官方域名、来源类型和角色、bundle hash、每个原始文件的 hash/size、路径安全、候选版本未被修改，以及完整 review gate。`--artifact` 单文件模式只为兼容旧测试和非生产工具保留，不能满足生产门禁。

封印成功后还不能直接执行 B1-B7：必须由独立 Reviewer 检查本表、证据包、边界测试和旧版本不可变性，合并 REVIEWED 版本后，再从届时最新 main 做 clean checkout，重新做 SDK/runtime/身份/网络/query preflight，最后才进入唯一一次 Formal Production。

## 六、当前项目状态

- 已完成：H1 候选 14 条、`RULE_EVIDENCE_BUNDLE.v1` 校验器、review CLI bundle 模式、生产严格门禁、边界测试。
- 已保持：旧 `v20260824-compiled` 与当前 ACTIVE pointer 未改动；Golden v7 未改动；凭据未进入仓库。
- 当前阻塞：14 条官方原文的实际留存与独立人工逐条裁决尚未完成，因此不能切换 ACTIVE、不能生成 REVIEWED seal，也不能运行 B1-B7。

## 七、原文获取状态与堵点

2026-09-09 在当前本地环境做了只读连通性检查：列出的 SSE、SZSE 页面和科创板 PDF 返回 HTTP 200；BSE 页面及 BSE PDF 在该环境返回 HTTP 403，部分请求还出现重定向循环。403 响应不是官方原文，不能作为证据包成员，也不能据此判定规则事实。

因此，BSE 两条规则的原文需要项目管理者或独立 Reviewer 用真实浏览器完成反爬挑战后保存，或直接提供从 BSE 官方页面下载的原始 PDF/HTML。保存后仍需用文件原始字节生成 SHA-256，不能把截图、搜索摘要或手工摘录当作 raw artifact。其余来源即使能抓取，也必须由 Reviewer 实际打开并确认条款后，才算 `APPROVE`。

补充边界：当前 main 已有 GT-H3B Golden v7 的历史 BSE evidence，但它属于 Golden 证据域；按本表第三节的项目约束，不能直接充当 Trading Rule H1 evidence。它的存在不等于 H1 两条 BSE 规则已经完成独立原文留存与裁决。
