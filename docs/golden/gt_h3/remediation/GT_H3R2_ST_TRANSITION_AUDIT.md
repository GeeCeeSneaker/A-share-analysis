# GT-H3R2 ST_TRANSITION 全量审计台账

> 状态：**25 条已完成官方双核扫描；15 条已识别为语义无效；10 条待补证；独立语义门未通过；v5 不变；未发布 v6**

## 1. 审计边界

本台账逐行绑定 v5-candidate-20260907 的 50 条 ST_TRANSITION。它是独立二审的 build/review 证据，不扩展 Golden row schema，也不把 expected_fields 当作状态转换证明。

判定规则只有一条：ST_ADD 必须由官方一手材料证明 effective date 前 IS_ST_SEC=false、effective date 后 IS_ST_SEC=true；ST_REMOVE 必须证明 true -> false。ST→*ST、*ST→ST、仅增加/移除退市风险层级，均不属于二元 ST_TRANSITION。

## 2. 当前结果

| 项目 | 数量 | 说明 |
| --- | ---: | --- |
| ST_TRANSITION 总行数 | 50 | 与 v5 manifest 的 38 ADD + 12 REMOVE 一致 |
| transition_valid=true 且 audit_status=PASS | 25 | 14 条 ADD + 11 条 REMOVE；已逐案打开并读取官方一手材料，仍待最终独立 Reviewer 关闭 |
| 已识别语义无效 | 15 | 原独立复核 12 条 + 300064、000616 + 本轮 300506；均为 ST 层级变化或其他风险层级变化 |
| 尚待补齐官方双核证据 | 10 | 6 条 SSE static ADD、3 条 SSE 共用公告 ADD、1 条 STAR_ST_REMOVE；当前不能推断为合法或非法 |
| 可发布干净候选 | 否 | 仍有 15 条语义无效和 10 条证据未闭环；发布门 fail closed |

注意：本台账中的 transition_valid=false 同时覆盖“已证伪”和“待补证”两种状态，必须结合 audit_status 阅读；这是故意的 fail-closed 设计。25 条 PASS 是本轮官方原文扫描结果，不等同于最终独立 Reviewer 的批准。

## 3. 已识别的 15 条语义无效

原独立复核指出的 12 条为：600654、002113、000806、002781、000606、000410、002433、002086、300167、000525、300209、300108。另有本轮官方原文扫描识别的 300064（2021-04-28）和 000616（2023-05-04），以及 300506（2024-04-29）。这些条目均按 pre=true, effective=true 记录，不再当作二元 ST_ADD。

300506 的官方原文进一步表明：公司在目标日期前已有其他风险警示，2024-04-29 又叠加退市风险警示并冠以 *ST；这属于警示层级变化，不是 false→true。其官方材料定位已写入 JSONL，仍需独立 Reviewer 复核。

## 4. 已完成双核扫描的 25 条

- ADD 14 条：300312、600593、002022、002417、000995、300336、300297、300330、002485、000540、300742、300208、002217、300965。
- REMOVE 11 条：000408、002513、002058、000007、002022、300010、002482、002086、002021、300209、300965。

每条 PASS 都写入了 pre/effective 两侧官方 source_ref、页码或正文定位，并使用 audit_status=PASS；这不是对最终 Reviewer 的替代。

## 5. 尚待补证的 10 条

1. SSE static 直取受反爬挑战影响的 ADD：600077、601258、600466、600543、603963、STAR_ST_ADD-688500（6 条）。
2. SSE 共用公告只直接说明 effective 侧、没有 pre-state 的 ADD：600213、603363、STAR_ST_ADD-688282（3 条）。
3. STAR_ST_REMOVE-688500（1 条）仍受 SSE static 原文取得阻塞。

补证时必须逐条取得完整官方原文并记录 pre/effective 双侧定位；不得使用搜索摘要、接口输出、媒体报道或 provider 值替代。若清洗无效条目后数量不足，必须补入新的真实官方事件，不能降低 50 条结构门。

## 6. 版本和治理边界

- v5 文件保持 immutable；本次只更新独立审计台账及其说明，不把审计判断回写 v5。
- 当前不生成 v6，不修改 review.py，不解除 GT-H3B、正式发布或 Data Sufficiency 阻塞。
- 25 条 PASS 还需要独立 Reviewer 逐条复开；只有 50 条全部满足二元语义、官方双核证据和治理验收条件，才可生成 v6 并重跑 125 总量、身份唯一性、carry-forward、其他事件语义及三平台 CI。

命令：

    python scripts/golden/gt_h3r2_transition_audit.py
    python scripts/golden/gt_h3r2_transition_audit.py --require-clean

默认命令只检查台账覆盖和结构；--require-clean 仍应失败，因为当前存在 15 条无效和 10 条待补证。