# GT-H3R v5 候选整改报告

> 状态：**V5 CANDIDATE PREPARED / 12-CASE HUMAN RE-REVIEW PENDING / NOT SEALED**
>
> 本提交只执行管理裁决要求的 v4→v5 候选重建，不执行 `review.py` 或任何生产动作。

## 基线与结果

- v4 source truth version：`v4-candidate-20260906`
- v4 source dataset SHA256：`8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`
- v5 truth version：`v5-candidate-20260907`
- v5 dataset SHA256：`5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c`
- v5 case count：`125`，review summary：`{'COMPILED': 125}`
- carry-forward eligible：`113`；not eligible：`12`
- delta human review：`12` cases exactly
- `truth_manifest.json` 已指向 v5 candidate；v4 version files 未修改。

## 复合事实来源契约

- `GT_H3R_V5_SUPPORTING_OFFICIAL_SOURCES.jsonl` 逐案例列出 Human 必须打开的官方材料；它是审阅入口，不是已证明事实。
- AG-025 两条、AG-027 一条和 AG-029 两条各自要求同时核对 `RULE` 与 `APPLICABILITY`；其余 7 条保持单一主官方材料，不扩大整改范围。
- 侧车固定声明 `CANDIDATE_SOURCES_DECLARED_NOT_HUMAN_VERIFIED`，未提交来源 bytes/hash，也不含 `fact_proved` 或任何人工结果。601995 与 2019-10-28 的 600518 使用官方回溯材料，审阅人需自行判断是否覆盖目标日期。

## Carry-forward 哈希契约

现有 `case_semantic_hash` 是版本感知哈希，包含 `truth_version`，所以 v4/v5 的该字段不能在版本切换后保持相等。为避免伪造相等，本提交新增 `review_identity_hash_for_doc()`：它沿用同一 canonical semantic statement，仅移除版本标签，仍保留案例 ID、代码、日期、expected fields、事件身份和来源定位。

- ledger 的 `old_case_semantic_hash` / `new_case_semantic_hash` 使用上述版本中立哈希。
- `old_dataset_case_semantic_hash` / `new_dataset_case_semantic_hash` 保存两版真实的版本感知字段，便于审计。
- 113 条 APPROVE 同时满足 ID 相同、版本中立哈希相同、carry_forward_eligible=true。
- 12 条原 REJECT 均为 false；不自动转为 APPROVE。

## 12 条变更

| 原案例 | v5 案例 | 分组 | 类型 | 交易日 | 变更摘要 |
|---|---|---|---|---|---|
| `GT-LIMIT-ST5-600518-20190603` | `GT-LIMIT-ST5-600518-20190603` | `AG-025` | 官方来源替换 | `20190603` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-ST5-600518-20191028` | `GT-LIMIT-ST5-600518-20191028` | `AG-025` | 官方来源替换 | `20191028` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-CN20-300750` | `GT-LIMIT-CN20-300750` | `AG-054` | 官方来源替换 | `20210601` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-CN20-300059` | `GT-LIMIT-CN20-300059` | `AG-054` | 官方来源替换 | `20210601` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-CN20-300015` | `GT-LIMIT-CN20-300015` | `AG-054` | 官方来源替换 | `20210601` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-CN20-300124` | `GT-LIMIT-CN20-300124` | `AG-054` | 官方来源替换 | `20210601` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-CN20-300274` | `GT-LIMIT-CN20-300274` | `AG-054` | 官方来源替换 | `20210601` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-STARNO-20200723` | `GT-LIMIT-STAR20-688981-20200723` | `AG-027` | 候选事实修正 | `20200723` | 改为上市后第 6 个交易日 STAR 20% 边界案例并重新编号 |
| `GT-LIMIT-IPO44-601995` | `GT-LIMIT-IPO44-601995` | `AG-029` | 官方来源替换 | `20201102` | 只替换来源定位，expected semantics 保持不变 |
| `GT-LIMIT-IPO44-605499` | `GT-LIMIT-IPO44-605499` | `AG-029` | 官方来源替换 | `20210527` | 只替换来源定位，expected semantics 保持不变 |
| `GT-H2-ST-ST_ADD-002022-20220506` | `GT-H2-ST-ST_ADD-002022-20220506` | `AG-064` | 官方来源替换 | `20220506` | 只替换来源定位，expected semantics 保持不变 |
| `GT-H2-ST-ST_ADD-300965-20240429` | `GT-H2-ST-ST_ADD-300965-20240426` | `AG-096` | 候选事实修正 | `20240426` | 生效日/交易日改为 2024-04-26 并重新编号 |

## 可验证边界

- v5 所有记录仍为 `COMPILED`，无 `REVIEWED`、证据 bytes/hash、reviewed dataset 或 reviewed ACTIVE pointer。
- GT-H3R 只生成 12 条人工复审表；必须重新打开修正后的官方材料并逐条决定。
- `50` 不被写入 v5 reviewed provenance；真实审阅人必须显式确认其为非语义值或给出定义。
- 仅当 12/12 复审通过、113 条 carry-forward 证明成立、`50` 被中和/定义并给出 human marker 后，才能请求最终 125/125 授权和 GT-H3B。
- Formal Production、Data Sufficiency、Provider capability、backfill、策略、回测、交易和 `review.py` 继续 BLOCKED。
