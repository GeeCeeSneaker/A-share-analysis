# GT-H3R2 ST_TRANSITION 全量审计台账

> 状态：**台账已建立；独立语义门未通过；v5 不变；未发布 v6**

## 1. 审计边界

本台账逐行绑定 v5-candidate-20260907 的 50 条 ST_TRANSITION。它是独立二审的 build/review 证据，不扩展 Golden row schema，也不把 expected_fields 当作状态转换证明。

判定规则只有一条：ST_ADD 必须由官方一手材料证明 effective date 前 IS_ST_SEC=false、effective date 后 IS_ST_SEC=true；ST_REMOVE 必须证明 true -> false。ST→*ST、*ST→ST、仅增加/移除退市风险层级，均不属于二元 ST_TRANSITION。

## 2. 当前结果

| 项目 | 数量 | 说明 |
| --- | ---: | --- |
| ST_TRANSITION 总行数 | 50 | 与 v5 manifest 的 38 ADD + 12 REMOVE 一致 |
| 已识别语义无效 | 14 | 最新独立复核指出的 12 条，加本轮官方原文扫描识别的 300064、000616 |
| 尚缺 effective 前官方状态证据 | 36 | 未证明为合法二元转换，统一 fail closed |
| transition_valid=true 且 audit_status=PASS | 0 | 尚未有可直接放行的完整双核证据 |
| 可发布干净候选 | 否 | 必须先完成 36 条补证，并为无效条目做真实替换/删改 |

注意：本台账中的 transition_valid=false 同时覆盖“已证伪”和“待补证”两种状态，必须结合 audit_status 阅读；这是故意的 fail-closed 设计，不代表 36 条都已经被证明为错误。

## 3. 已识别的 14 条

12 条来自最新独立复核：600654、002113、000806、002781、000606、000410、002433、002086、300167、000525、300209、300108。另有本轮从官方公告原文扫描识别的 300064（2021-04-28）和 000616（2023-05-04）。这些条目均按 pre=true, effective=true 记录，不再当作 ST_ADD；其中 000806、300064、000616 的官方 PDF 已完成本地原文扫描，其余 11 条沿用独立复核报告指出的官方原文定位，仍需在最终 Reviewer 关闭前逐页复核。

## 4. 阻塞原因与下一步

- 36 条没有可提交的 effective 前官方二元状态证据，不能靠 provider 输出、搜索摘要、媒体报道或重复材料补齐。
- 部分 SSE static PDF 直取返回交易所反爬挑战页，不能把挑战页当作原文；需用真实浏览器取得全文后逐页记录定位。
- 目前只提交审计台账、校验模块和测试，没有改写 v5，没有伪造 v6，没有触碰 review.py 或 GT-H3B。
- 下一步是补齐每条 pre-state/effective-state 官方证据，独立 Reviewer 逐条复核；对证伪条目生成带 lineage 的 v6 candidate，重新过结构数量、身份唯一性、125 总量、carry-forward 和三平台 CI 门。

命令：

    python scripts/golden/gt_h3r2_transition_audit.py
    python scripts/golden/gt_h3r2_transition_audit.py --require-clean

默认命令只检查台账覆盖和结构；--require-clean 才要求发布门通过。当前预期：台账覆盖可检查，但发布门 fail closed。
