# GT-H3R v5 12 条人工复审结果（已收到）

> 状态：**12/12 APPROVE RECEIVED / PENDING COMPLETE V5 AUTHORIZATION / NOT SEALED**

## 结论

- 评审对象：GT_H3R_V5_REVIEW_TABLE.xlsx。
- 结果统计：APPROVE 12 / REJECT 0。
- 提交者声明：逐条打开 sidecar 所列全部 required official source 原文，确认 HTTP 200 并做全文提取；未使用搜索摘要、接口输出或 AI 总结替代原文。
- 本报告记录提交者提供的人工复审裁决，不把本代理的仓库重算冒充原文人工审阅。

## 仓库侧独立一致性重算

- main 上 v5 JSONL 的 Git blob SHA：74c5a2dea28b877ad7375fe5efc8af2e3da3224e；权威 dataset SHA256：5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c；125 条，review_status=COMPILED 125 条。
- ST_TRANSITION：50 条；IS_ST_SEC=true 38 条、false 12 条；manifest 的 golden_st_transition=50。
- expected_fields 中命中数值 50：0 条；reviewed_by 非空：0 条。
- carry-forward ledger：125 条；eligible=113、not_eligible=12；113 条中 old_case_id/new_case_id、prior_decision 和版本中立哈希一致性重算不一致：0 条。
- 12 条 not eligible 的 ledger 原因：source locator changed 10 条，candidate semantics changed 2 条，与 10 条换源和 2 条语义修正对应。

## 12 条逐案结果

| 序号 | 原案例 ID | v5 案例 ID | 分组 | 核验范围 | 结果 | 提交者结论摘要 |
|---:|---|---|---|---|---|---|
| 1 | GT-LIMIT-ST5-600518-20190603 | GT-LIMIT-ST5-600518-20190603 | AG-025 | RULE + APPLICABILITY | APPROVE | A1 证明 SSE 风险警示股票涨跌幅 5%；A2 证明 600518 在 2019-06-03 为 ST 康美；结论 APPROVE。 |
| 2 | GT-LIMIT-ST5-600518-20191028 | GT-LIMIT-ST5-600518-20191028 | AG-025 | RULE + APPLICABILITY | APPROVE | A1 证明 5% 规则；A3 证明 600518 自 2019-05-21 起为 ST 康美，覆盖 2019-10-28；结论 APPROVE。 |
| 3 | GT-LIMIT-CN20-300750 | GT-LIMIT-CN20-300750 | AG-054 | RULE | APPROVE | B1 证明创业板涨跌幅限制 20%，覆盖 300750.SZ 2021-06-01；结论 APPROVE。 |
| 4 | GT-LIMIT-CN20-300059 | GT-LIMIT-CN20-300059 | AG-054 | RULE | APPROVE | B1 证明创业板涨跌幅限制 20%，覆盖 300059.SZ 2021-06-01；结论 APPROVE。 |
| 5 | GT-LIMIT-CN20-300015 | GT-LIMIT-CN20-300015 | AG-054 | RULE | APPROVE | B1 证明创业板涨跌幅限制 20%，覆盖 300015.SZ 2021-06-01；结论 APPROVE。 |
| 6 | GT-LIMIT-CN20-300124 | GT-LIMIT-CN20-300124 | AG-054 | RULE | APPROVE | B1 证明创业板涨跌幅限制 20%，覆盖 300124.SZ 2021-06-01；结论 APPROVE。 |
| 7 | GT-LIMIT-CN20-300274 | GT-LIMIT-CN20-300274 | AG-054 | RULE | APPROVE | B1 证明创业板涨跌幅限制 20%，覆盖 300274.SZ 2021-06-01；结论 APPROVE。 |
| 8 | GT-LIMIT-STARNO-20200723 | GT-LIMIT-STAR20-688981-20200723 | AG-027 | RULE + APPLICABILITY | APPROVE | C1 证明科创板前五个交易日无涨跌幅限制、之后 20%；C2 证明 688981 于 2020-07-16 上市，7-23 为第 6 个交易日；结论 APPROVE。 |
| 9 | GT-LIMIT-IPO44-601995 | GT-LIMIT-IPO44-601995 | AG-029 | RULE + APPLICABILITY | APPROVE | D1 证明上市首日 +44%/-36% 规则；D2 证明 601995 于 2020-11-02 在上交所主板上市；结论 APPROVE。 |
| 10 | GT-LIMIT-IPO44-605499 | GT-LIMIT-IPO44-605499 | AG-029 | RULE + APPLICABILITY | APPROVE | D1 证明上市首日 +44%/-36% 规则；D3 证明 605499 于 2021-05-27 上市交易；结论 APPROVE。 |
| 11 | GT-H2-ST-ST_ADD-002022-20220506 | GT-H2-ST-ST_ADD-002022-20220506 | AG-064 | CASE_SPECIFIC | APPROVE | E1 证明 002022 自 2022-05-06 起被实施退市风险警示和其他风险警示；结论 APPROVE。 |
| 12 | GT-H2-ST-ST_ADD-300965-20240429 | GT-H2-ST-ST_ADD-300965-20240426 | AG-096 | CASE_SPECIFIC | APPROVE | E2 证明 300965 自 2024-04-26 起被实施退市风险警示；结论 APPROVE。 |

## 五条复合事实

以下 5 条均由提交者报告同时检查 RULE 和 APPLICABILITY：

- GT-LIMIT-ST5-600518-20190603：https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml；https://www.sse.com.cn/market/sseindex/diclosure/c/c_20190531_4830732.shtml。A1 证明 SSE 风险警示股票涨跌幅 5%；A2 证明 600518 在 2019-06-03 为 ST 康美；结论 APPROVE。
- GT-LIMIT-ST5-600518-20191028：https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml；https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2021-11-27/600518_20211127_2_wfwElR2q.pdf。A1 证明 5% 规则；A3 证明 600518 自 2019-05-21 起为 ST 康美，覆盖 2019-10-28；结论 APPROVE。
- GT-LIMIT-STAR20-688981-20200723：https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf；https://star.sse.com.cn/disclosure/listedinfo/bulletin/star/c/688981_20200715_1.pdf。C1 证明科创板前五个交易日无涨跌幅限制、之后 20%；C2 证明 688981 于 2020-07-16 上市，7-23 为第 6 个交易日；结论 APPROVE。
- GT-LIMIT-IPO44-601995：https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml；https://static.sse.com.cn/disclosure/bond/announcement/company/c/new/2023-04-04/175906_20230404_LS9E.pdf。D1 证明上市首日 +44%/-36% 规则；D2 证明 601995 于 2020-11-02 在上交所主板上市；结论 APPROVE。
- GT-LIMIT-IPO44-605499：https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml；https://www.sse.com.cn/disclosure/announcement/listing/ipo/c/c_20210526_81718214.shtml。D1 证明上市首日 +44%/-36% 规则；D3 证明 605499 于 2021-05-27 上市交易；结论 APPROVE。

## 非阻断观察

- A2 的 source name 使用 2019-05-31 URL slug，页面官方日期据提交者核对为 2019-06-03。
- A3 的官方 PDF 据提交者报告需要真实浏览器处理 JS 反爬挑战；其原始文件未上传 GitHub。
- A1、B1、C1 位于交易所已废止规则目录；提交者依据历史施行时间覆盖对应案例日期。
- D2 是回溯型年报材料，不是上市即时公告；本次提交者仍将其作为足以证明代码和上市日期的官方材料。

## 证据留存登记

提交者报告原始文件保存在本地 gt_h3r_v5_evidence/，本仓库不接收这些原始 bytes；以下仅登记提交者提供的类型和字节数：

- A1 HTML 43,937 B
- A2 HTML 117,280 B
- A3 PDF 517,339 B
- B1 PDF 163,021 B
- C1 PDF 268,491 B
- C2 PDF 1,646,911 B
- D1 HTML 34,223 B
- D2 PDF 5,307,257 B
- D3 HTML 33,419 B
- E1 PDF 199,137 B
- E2 PDF 260,756 B

本报告没有写入 source bytes、source SHA256 或 fact_proved。后续 GT-H3B 如获授权，仍需按每个 case 的 required sources 建立 deterministic child manifest 并绑定精确 bytes/hash。

## 完整授权仍缺什么

本次消息已经给出 12/12 APPROVE、113 条沿用确认，也给出了 legacy 50 的定义与中和结论。但尚未提供：

1. 明确的 final human marker。
2. 可关联该 marker 的审阅人标识和审阅日期。

在 marker 和独立项目 Reviewer closure 到位前，不运行 review.py，不生成 GT-H3B，不写入 REVIEWED provenance，不推进 Production、Data Sufficiency、Provider capability verdict 或 backfill。

## 结果文件边界

配套 JSONL 是 received-result audit snapshot，不是 canonical review_decision_template.jsonl，也不是 REVIEWED 数据集；原有空白审阅表继续保留。