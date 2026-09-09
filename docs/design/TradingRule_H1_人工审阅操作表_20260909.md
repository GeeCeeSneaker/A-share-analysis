# Trading Rule H1 人工审阅操作表

适用候选：`configs/trading_rules/versions/v20260909-h1r2-compiled/rules.yaml`
候选版本：`2026-09-09.2`，共 14 条，当前 `COMPILED`、非 `ACTIVE`。
目的：作为独立 evidence/seal PR 的审阅清单，在不修改候选 YAML 的前提下逐条打开官方原文，确认规则事实、适用范围和制度切换边界。本表不是已合并 PR #35 的合并前置条件。

本次执行基线：`main@e096b0364d3dc5a00e21879fe5bd8fc4a758b07f`；candidate hash：`6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f`；已物化 bundle：`sha256/14f09ed0707b0ef1d84ae2dbe880f87bdd186d0c21e61e6387f26fa41bd403d0`（16,557 bytes），raw artifact 19 个（1,702,416 bytes）。每行结果仍必须由人工实际打开对应原文后填写，当前不得视为已审阅。

## 一、审阅原则

1. 必须实际打开下表的官方页面或 PDF 原文；搜索摘要、接口返回、AI 总结不能替代原文。
2. 每条至少确认“数值/语义 + 生效时间 + 适用市场/股票范围”；复合事实还要确认 `RULE`、`APPLICABILITY`、`TRANSITION` 三类证据是否闭合。
3. 原文无法证明候选值时，填 `REJECT`，备注写明缺少哪一项；不要为了让结果通过而修改规则或放宽证据要求。
4. 只有 14 条全部 `APPROVE`，且每个 `rule_id` 都有至少一个官方来源，才允许用 `--evidence-bundle` 进入封印流程。
5. 评审过程不得填写、保存或提交账号、密码、IP、端口、Token 等运行凭据。

## 二、逐条审阅表

| 序号 | rule_id | 需要确认的具体事实 | 对照的官方原文 | 结果（APPROVE/REJECT） | 原文页码/条款与简短备注 |
|---:|---|---|---|---|---|
| 1 | `MAIN_BOARD_NORMAL` | 沪深主板普通股票日涨跌幅为 10%；代码范围、2020-01-01 起的适用区间与 `st_state=false` 一致；当前区间不能只依赖历史规则 | [SSE 历史主板规则](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml)；[SZSE 历史交易规则](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)；[SSE 2026 现行规则正文 DOCX](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 |  |
| 2 | `MAIN_BOARD_ST_HISTORICAL_SH` | 沪市主板风险警示股票在 `20200101`—`20260705` 为 5%；`st_state=true`、SH/60xxxx 适用范围成立；本轮不要求证明 1998 年起点 | [SSE 历史风险警示板办法](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml)；[SSE 2026 风险警示调整公告](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml) | 待填 | 确认规则正文的 5% 条款、生效覆盖 2020，并确认 2026-07-06 切换；1998 起点属于后续 backlog |
| 3 | `MAIN_BOARD_ST_HISTORICAL_SZ` | 深市主板风险警示股票在 `20200101`—`20260705` 为 5%；`st_state=true`、SZ/000xxx、001xxx、002xxx、003xxx 适用范围成立；本轮不要求证明 1998 年起点 | [SZSE 历史交易规则](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)；[SZSE 2026 风险警示业务指南公告](https://www.szse.cn/lawrules/service/member/t20260630_621404.html) | 待填 | 确认规则正文的 5% 条款、生效覆盖 2020，并确认 2026-07-06 切换；1998 起点属于后续 backlog |
| 4 | `MAIN_BOARD_ST_CURRENT` | 沪深主板风险警示股票自 `20260706` 起为 10%；当前 `20260908` 必须命中 10%，不能命中旧 5% | [SSE 2026 现行规则正文 DOCX](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx)；[SSE 2026 风险警示调整公告](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf)；[SZSE 2026 风险警示业务指南公告](https://www.szse.cn/lawrules/service/member/t20260630_621404.html) | 待填 | 必须记录 2026-07-06 生效条款与 10% 数值 |
| 5 | `MAIN_BOARD_IPO_DAY` | 旧制度上市首日上限 +44%、下限 −36%；`effective_to=20230409` 是否由官方过渡条款和首批注册制主板上市日直接证明 | [SSE 2014 新股上市初期交易监管通知](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml)；[SZSE 2014 新股上市首日问答](https://www.szse.cn/aboutus/trends/news/t20140613_518480.html)；[SSE 过渡说明](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230217_5716420.shtml)；[SZSE 首批注册制主板上市](https://www.szse.cn/aboutus/trends/news/t20230404_599697.html) | 待填 | 需分别确认两交易所的 144%/64% 原文，并单独裁决 2023-04-09 终止边界 |
| 6 | `MAIN_BOARD_FIRST5_NO_LIMIT` | 注册制主板 IPO 上市后前 5 个交易日不限价，第 6 个交易日回到普通 10%；2023-04-10 的生效语义成立；同一条规则对 `is_st=false/true` 均可解析 | [SSE 首 5 个交易日说明](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230201_5715605.shtml)；[SZSE 主板 IPO 问答](https://investor.szse.cn/knowledge/qa/t20230306_599093.html)；[首批上市](https://www.szse.cn/aboutus/trends/news/t20230404_599697.html)；[SSE 2026 现行规则正文 DOCX](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 | 分别记录普通/ST 两次解析结果；不再要求来源证明不存在的独立 ST FIRST5 规则 |
| 7 | `CHINEXT_PRE_REGISTRATION_NORMAL` | 创业板改革前普通股票为 10%，有效期至 2020-08-23；不得误套改革后的 20% | [SZSE 历史交易规则](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html)；[2020-07-10 改革通知](https://www.szse.cn/disclosure/notice/general/t20200710_579459.html) | 待填 |  |
| 8 | `CHINEXT_PRE_REGISTRATION_ST` | 创业板改革前 ST/*ST 为 5%，不是 10%；有效期至 2020-08-23 | [SZSE 2020-07-10 改革通知](https://www.szse.cn/disclosure/notice/general/t20200710_579459.html) | 待填 |  |
| 9 | `CHINEXT_REGISTRATION` | 创业板注册制改革后普通交易日涨跌幅为 20%，生效日 2020-08-24；当前区间由 2026 现行规则继续覆盖 | [创业板交易特别规定正文 PDF](https://docs.static.szse.cn/www/disclosure/notice/general/W020200612831351578076.pdf)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 |  |
| 10 | `CHINEXT_REGISTRATION_FIRST5` | 创业板注册制 IPO 前 5 个交易日不限价，第 6 日适用 20%；必须按交易日计数，当前区间由 2026 现行规则继续覆盖 | [创业板交易特别规定正文 PDF](https://docs.static.szse.cn/www/disclosure/notice/general/W020200612831351578076.pdf)；[SZSE 2026 现行交易规则 PDF](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf) | 待填 |  |
| 11 | `STAR_MARKET` | 科创板上市前 5 个交易日后，普通交易日涨跌幅为 20%；代码和交易所范围正确，当前区间由 2026 现行规则继续覆盖 | [科创板交易特别规定 PDF](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf)；[SSE 2026 现行规则正文 DOCX](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx) | 待填 |  |
| 12 | `STAR_MARKET_FIRST5` | 科创板 IPO 上市后前 5 个交易日不限价，第 6 日为 20%；必须按交易日计数，当前区间由 2026 现行规则继续覆盖 | [科创板交易特别规定 PDF](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf)；[SSE 2026 现行规则正文 DOCX](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx) | 待填 |  |
| 13 | `BSE_LIMIT` | 北交所 venue 为 `BJ`；规则自 2021-11-15 起生效；普通交易日为 30%；2021-11-15 前不得静默命中该 BSE 规则；当前区间由 2026 现行规则继续覆盖 | [BSE 历史交易规则正文 DOCX](https://www.bse.cn/uploads/6/file/public/202209/20220924123627_d6405jicv9.docx)；[BSE 上市规则施行正文 DOCX](https://www.bse.cn/uploads/6/file/public/202209/20220924113331_fwbg1kr3qu.docx)；[BSE 2026 现行交易规则正文 DOCX](https://www.bse.cn/uploads/6/file/public/202604/20260424170528_52kqyhc7p9.docx) | 待填 |  |
| 14 | `BSE_IPO_DAY_NO_LIMIT` | 北交所公开发行股票上市首日不限价，后续交易日为 30%；上市首日必须依赖真实 `listing_date` 与 PIT 日历 | [BSE 2026 现行上市交易规则正文 DOCX](https://www.bse.cn/uploads/6/file/public/202604/20260424170528_52kqyhc7p9.docx) | 待填 |  |

## 三、结果填写规则

每行只填一个最终结果：

- `APPROVE`：原文直接支持候选的数值、语义和时间边界；在最后一列写条款/页码和一句理由。
- `REJECT`：原文与候选冲突、无法覆盖候选，或来源不是官方原文；在最后一列写冲突值或缺失证据。

建议将填好的表格作为评审 PR 的正文或附件提交；不得把账号信息写进表格。若任一行是 `REJECT`，本轮不能运行封印命令，应先形成新的 `COMPILED` 候选并重新评审。

## 四、证据包输入格式

`--evidence-bundle` 接受一个本地 JSON 输入文件。`artifact_path` 相对该 JSON 文件所在目录；原始 HTML/PDF/DOCX 必须先完整保存到本地。H1R2 要求 `source_url` 与 `artifact_path` 中的原始字节一一对应；若官方发布页只是 locator/notice page，发布页只在 `trading_rule_h1_source_catalog.json` 的 `source_page_url` 中记录，不能用发布页 URL 冒充附件 URL。工具会自行计算 SHA-256、字节数，并把发布证据存到 `configs/trading_rules/evidence/sha256/`，不会把本地路径写入发布 bundle。

```json
{
  "schema_version": "RULE_EVIDENCE_BUNDLE.v1",
  "dataset_version": "2026-09-09.2",
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
  --candidate configs/trading_rules/versions/v20260909-h1r2-compiled/rules.yaml \
  --candidate-version v20260909-h1r2-compiled \
  --expected-candidate-hash 6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f \
  --evidence-bundle docs/provider_verification/trading_rule_h1_evidence_input.json \
  --reviewer "稳定的人审标识" \
  --version v20260909-h1r2-reviewed \
  --from-version v20260824-compiled
```

命令会在发布前检查：规则 ID 精确集合、官方域名、来源类型和角色、bundle hash、每个原始文件的 hash/size、路径安全、候选版本未被修改，以及完整 review gate。`--artifact` 单文件模式只为兼容旧测试和非生产工具保留，不能满足生产门禁。

封印成功后还不能直接执行 B1-B7：必须由独立 Reviewer 检查本表、证据包、边界测试和旧版本不可变性，合并 REVIEWED 版本后，再从届时最新 main 做 clean checkout，重新做 SDK/runtime/身份/网络/query preflight，最后才进入唯一一次 Formal Production。

## 六、当前项目状态

- 已完成：H1R2 候选 14 条、`RULE_EVIDENCE_BUNDLE.v1` 校验器、review CLI bundle 模式、生产严格门禁、2020+ 边界测试输入。
- 已保持：旧 `v20260824-compiled` 与当前 ACTIVE pointer 未改动；Golden v7 未改动；凭据未进入仓库。
- 当前阻塞：H1R2 的 14 条官方原文实际留存与独立人工逐条裁决尚未完成；因此不能切换 ACTIVE、不能生成 REVIEWED seal，也不能运行 B1-B7。旧 `v20260909-h1-compiled` 和 H1R2 均保持 `COMPILED`、非 ACTIVE。

## 七、原文获取状态与堵点

2026-09-09 在当前本地环境完成了来源接收：H1R2 使用 19 个唯一来源和 19 个去重 raw artifact；16 个为 HTTP 200 原始 HTML/PDF，3 个 BSE、SSE 2026 规则和 SZSE 2020 创业板规则使用官方链接的原始 DOCX/PDF 附件。H1R2 的每个 `source_ref` 与 evidence input 的 `source_url` 均绑定实际原始字节 URL；发布页只作为 catalog 的 `source_page_url` 关系记录。BSE 三个发布页直连请求返回自指向 302/WAF challenge，未把 challenge 响应或渲染 DOM 当作证据；附件响应均为 HTTP 200。详情见 [`trading_rule_h1_source_catalog.json`](../provider_verification/trading_rule_h1_source_catalog.json)。

当前不再使用 `browser_resolved_dom`。任何情况下都不能用截图、搜索摘要或手工摘录替代 raw artifact。其余来源也必须由 Reviewer 实际打开并确认条款后，才算 `APPROVE`。H1R2 将主板 ST 历史规则下界收窄为 2020-01-01，并将 2026-07-06 作为当前 10% 规则切换点；1998 年起点材料不再参与本轮 bundle 或放行判断，完整 pre-2020 历史重建列为后续非阻断 backlog。

补充边界：当前 main 已有 GT-H3B Golden v7 的历史 BSE evidence，但它属于 Golden 证据域；按本表第三节的项目约束，不能直接充当 Trading Rule H1 evidence。它的存在不等于 H1 两条 BSE 规则已经完成独立原文留存与裁决。
