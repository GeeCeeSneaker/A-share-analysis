# GT-H3R2 ST_TRANSITION 全量审计台账

> 状态：**35 条已完成官方双核扫描；15 条已识别为语义无效；0 条待补证；独立语义门未通过；v5 不变；未发布 v6**

## 1. 审计边界

本台账逐行绑定 v5-candidate-20260907 的 50 条 ST_TRANSITION。它是独立二审的 build/review 证据，不扩展 Golden row schema，也不把 expected_fields 当作状态转换证明。

判定规则只有一条：ST_ADD/STAR_ST_ADD 必须由官方一手材料证明 effective date 前 IS_ST_SEC=false、effective date 后 IS_ST_SEC=true；ST_REMOVE/STAR_ST_REMOVE 必须证明 true -> false。ST→*ST、*ST→ST、仅增加/移除退市风险层级，均不属于二元 ST_TRANSITION。

## 2. 当前结果

| 项目 | 数量 | 说明 |
| --- | ---: | --- |
| ST_TRANSITION 总行数 | 50 | 与 v5 manifest 的 38 ADD + 12 REMOVE 一致 |
| transition_valid=true 且 audit_status=PASS | 35 | 23 条 ADD + 12 条 REMOVE；35 条均已逐案打开并读取官方一手材料，仍待最终独立 Reviewer 关闭 |
| 已识别语义无效 | 15 | 原独立复核 12 条 + 300064、000616 + 本轮 300506；均为 ST 层级变化或其他风险层级变化 |
| 尚待补齐官方双核证据 | 0 | 10 条此前待补证已通过官方 CNINFO/SSE 全文材料闭环 |
| 可发布干净候选 | 否 | 仍有 15 条语义无效；发布门继续 fail closed |

注意：本台账中的 transition_valid=false 仅出现在已识别语义无效条目；必须结合 audit_status 阅读。这是故意的 fail-closed 设计。35 条 PASS 是本轮官方原文扫描结果，不等同于最终独立 Reviewer 的批准。

## 3. 已识别的 15 条语义无效

原独立复核指出的 12 条为：600654、002113、000806、002781、000606、000410、002433、002086、300167、000525、300209、300108。另有本轮官方原文扫描识别的 300064（2021-04-28）和 000616（2023-05-04），以及 300506（2024-04-29）。这些条目均按 pre=true, effective=true 记录，不再当作二元 ST_ADD。

300506 的官方原文进一步表明：公司在目标日期前已有其他风险警示，2024-04-29 又叠加退市风险警示并冠以 *ST；这属于警示层级变化，不是 false→true。其官方材料定位已写入 JSONL，仍需独立 Reviewer 复核。

## 4. 已完成双核扫描的 35 条

- ADD 23 条：300312、600593、002022、002417、000995、300336、300297、300330、002485、000540、300742、300208、002217、300965、600077、601258、600466、600543、603963、688500、600213、603363、688282。
- REMOVE 12 条：000408、002513、002058、000007、002022、300010、002482、002086、002021、300209、300965、688500。

新增 10 条补证均采用可读取的官方一手全文：600077/601258/600466/600543/688500 ADD 使用 CNINFO 同日公司公告；600213 使用 CNINFO 上市公司公告；603963 使用官方年报与后续官方风险状态披露；603363/688282 使用官方年报与上交所正式公告；688500 REMOVE 使用官方年报与上交所正式公告。每条都写入了 pre/effective 两侧官方 source_ref、页码或正文定位，并标记为 audit_status=PASS。

## 5. 证据闭环记录

本轮关闭的 10 条及其可复核材料：

| 案例 | pre-state 材料 | effective-state 材料 |
| --- | --- | --- |
| 600077 ADD | [CNINFO 1216688532](https://static.cninfo.com.cn/finalpage/2023-04-29/1216688532.PDF)，p.1“宋都股份” | 同一公告 p.1，2023-05-05 变更为“*ST宋都” |
| 601258 ADD | [CNINFO 1216709508](https://static.cninfo.com.cn/finalpage/2023-04-29/1216709508.PDF)，p.1“庞大集团” | 同一公告 p.1，2023-05-05 变更为“*ST庞大” |
| 600466 ADD | [CNINFO 1216663174](https://static.cninfo.com.cn/finalpage/2023-04-28/1216663174.PDF)，p.1“蓝光发展” | 同一公告 p.1，2023-05-04 变更为“*ST蓝光” |
| 600543 ADD | [CNINFO 1216663507](https://static.cninfo.com.cn/finalpage/2023-04-28/1216663507.PDF)，p.1“莫高股份” | 同一公告 p.1，2023-05-04 变更为“*ST莫高” |
| 603963 ADD | [CNINFO 1219837022](https://static.cninfo.com.cn/finalpage/2024-04-26/1219837022.PDF)，p.1“大理药业” | [CNINFO 1222285513](https://static.cninfo.com.cn/finalpage/2025-01-10/1222285513.PDF)，p.1/正文确认2024-04-29为“*ST大药” |
| 688500 ADD | [CNINFO 1216712142](https://static.cninfo.com.cn/finalpage/2023-04-29/1216712142.PDF)，p.1“慧辰股份” | 同一公告 p.1，2023-05-05 变更为“*ST慧辰” |
| 600213 ADD | [CNINFO 1219910374](https://static.cninfo.com.cn/finalpage/2024-04-30/1219910374.PDF)，p.1“亚星客车” | 同一公告 p.1，2024-05-06 变更为“*ST亚星” |
| 603363 ADD | [CNINFO 1219925618](https://static.cninfo.com.cn/finalpage/2024-04-30/1219925618.PDF)，p.1“傲农生物” | [上交所正式公告](https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml)，正文确认2024-05-06实施退市风险警示 |
| 688282 ADD | [CNINFO 1219925844](https://static.cninfo.com.cn/finalpage/2024-04-30/1219925844.PDF)，p.1“理工导航” | 同一份[上交所正式公告](https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml)，正文确认2024-05-06实施退市风险警示 |
| 688500 REMOVE | [CNINFO 1219838927](https://static.cninfo.com.cn/finalpage/2024-04-26/1219838927.PDF)，p.1“*ST慧辰” | [上交所正式公告](https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240607_10758549.shtml)，正文确认2024-06-11撤销退市风险警示 |

这些是替代受反爬影响 sidecar 的官方可读全文，不是搜索摘要、接口输出或媒体材料；原始 PDF/HTML bytes 仍未上传 GitHub。

## 7. 替换候选池（草案）

已准备 15 条经开发者直接打开官方 CNINFO PDF 全文后筛选出的 `false -> true` 候选，供独立 Reviewer 逐案复核：[GT_H3R2_REPLACEMENT_CANDIDATES.md](./GT_H3R2_REPLACEMENT_CANDIDATES.md)。候选池不是 v6，也没有改变本台账的 35 PASS / 15 INVALID 结论；Reviewer closure 前不得将候选写入 Golden。

## 6. 版本和治理边界

- v5 文件保持 immutable；本次只更新独立审计台账及其说明，不把审计判断回写 v5。
- 当前不生成 v6，不修改 review.py，不解除 GT-H3B、正式发布或 Data Sufficiency 阻塞。
- 35 条 PASS 仍需要独立 Reviewer 逐条复开；15 条语义无效必须先做真实替换/删改并保留 lineage。完成后才可生成 v6，并重跑 125 总量、身份唯一性、carry-forward、其他事件语义及三平台 CI。
- `python scripts/golden/gt_h3r2_transition_audit.py --require-clean` 预计仍失败，因为台账中仍有 15 条 INVALID_ST_LEVEL_CHANGE；这不是证据未闭环，而是样本语义仍不合格。

命令：

    python scripts/golden/gt_h3r2_transition_audit.py
    python scripts/golden/gt_h3r2_transition_audit.py --require-clean
