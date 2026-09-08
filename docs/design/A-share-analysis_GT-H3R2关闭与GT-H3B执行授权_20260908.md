# A-share-analysis · GT-H3R2 关闭与 GT-H3B 执行授权（2026-09-08）

## 结论

GT-H3R2 已关闭。PR #23 final head `d990ac3b182f7b4be56b693157f33a09b38fb086` 经独立 Reviewer 二审通过，Review ID `5136117144`，已合并为 `2dff6b85a8b31b60ebad2db76fbbfbd1e803ebab`。

Owner 已明确决定：**不再对 v6 新增 15 条逐案重复人工复核，接受独立 Reviewer 已完成的 15/15 PASS 结论并授权继续推进。** 本项目不再增加额外人工形式门。

本授权不允许绕过数据与证据完整性技术门。

## v6 权威候选基线

- truth version: `v6-candidate-20260908`
- dataset SHA256: `0b3952f9f82ee4f6a55a7f060c47af3cc781b0054ed1f83b5868246c0642a343`
- 125 COMPILED
- LIMIT 30 / corporate action 25 / ST_TRANSITION 50 / DELIST 20
- ST ADD 38 / REMOVE 12 / structural distinct 50
- DELIST distinct 20
- v5→v6 review identity: 110 unchanged eligible / 15 changed not eligible
- ST transition audit: 50/50 PASS
- ACTIVE 当前仍必须保持 `v5-candidate-20260907`，直到下面的受控 promotion 完成。

## 当前任务：GT-H3B-P0 — 安全激活既有 v6 candidate

不得手工编辑 `truth_manifest.json`。

现有 `candidate.py rebuild` 会 create-only 写 versioned dataset/manifest 后推进 ACTIVE；但 v6 versioned 文件已作为 PR #23 的 immutable staged candidate 提前存在。因此必须增加一个**窄范围、fail-closed 的 existing-candidate promotion path**，只解决“已存在、已验证的 versioned candidate 如何原子推进 ACTIVE”。

建议接口可为：

```bash
uv run python scripts/golden/candidate.py promote-existing \
  --truth-version v6-candidate-20260908 \
  --transition-audit docs/golden/gt_h3/remediation/GT_H3R2_ST_TRANSITION_AUDIT.jsonl \
  --carry-forward docs/golden/gt_h3/remediation/v5_to_v6_human_review_carry_forward.jsonl \
  --plan docs/golden/gt_h3/remediation/v5_to_v6_rebuild_plan.json
```

命令名可调整，但语义不得扩大。

### promotion 必须重新验证

1. ACTIVE 当前精确为 v5 candidate；任何其他 ACTIVE 状态 fail closed。
2. v5 dataset hash 精确为既定 SHA；v5/v4 文件不可修改。
3. v6 versioned dataset/manifest 已存在且字节/hash 精确匹配上述 v6 基线。
4. 使用 Golden loader 重新加载 v6；manifest statistics 重算一致。
5. 125 total；30/25/50/20；ST 38/12；ST structural distinct 50；DELIST distinct 20。
6. v5→v6 plan 精确 KEEP 110 / DROP 15 / ADD 15；DROP/ADD set 与已关闭 GT-H3R2 一致。
7. carry-forward ledger 重新按 `review_identity_hash` 计算为 110 eligible / 15 ineligible；禁止只相信文件中的计数。
8. ST audit 必须绑定 exact v6 ST set 并 `PASS 50/50`。
9. v6 仍为 `COMPILED 125/125`，不得在 promotion 阶段伪造 REVIEWED provenance。
10. 所有检查通过后，才允许通过 staging + atomic replace 将 ACTIVE pointer 推进到**已经存在且 hash 已确认的 v6 manifest**。
11. promotion 必须 idempotent：ACTIVE 已是完全相同 v6 时返回成功/no-op；任何同版本不同 bytes 或状态歧义 fail closed。
12. adversarial tests 至少覆盖：错误 v6 hash、tampered v6 bytes、错误 ACTIVE、plan set 漂移、110/15 漂移、49/50 audit、duplicate ST identity、partial/failed pointer write；失败时 ACTIVE 保持原值。

不要为了完成 promotion 重写 v6 dataset/manifest；它们已是 immutable candidate bytes。

## GT-H3B-P1 — 125/125 evidence-byte materialization + atomic REVIEWED seal

v6 promotion 通过后才执行。

### Human decision provenance

- reviewer marker 使用 `project-owner`。
- v5 未变化 110 条沿用既有 Human APPROVE 决策，前提是 review identity 精确一致。
- v6 新增 15 条不做自动 carry-forward；Owner 已在 2026-09-08 明确授权基于独立 Reviewer 15/15 PASS 继续推进，视为本轮 Human final authorization，不再要求逐案重复填写表格。
- 这项治理授权不能替代真实官方 evidence bytes。

### evidence 要求

1. 为 125 case 获取实际官方原始 bytes，并由 `review.py` 自己计算 authoritative SHA256。
2. PDF 保存原 PDF；HTML 保存官方原始响应/body；不得用截图、AI 摘要、搜索结果页、媒体镜像或 Provider-under-test 输出替代。
3. 证据失效、下载内容变化、正文不能证明 claim 时必须 BLOCK，不得 seal。
4. 5 个已确认需要 RULE + APPLICABILITY 的复合 case 必须保留完整双证据链。允许使用最小化确定性 `EVIDENCE_BUNDLE`（若当前实现尚不支持，则在 GT-H3B PR 中以窄范围方式加入）；bundle 内容必须可重现、包含两份原始官方 bytes 及明确清单，不得只存链接文本。
5. 相同官方 artifact 可 content-addressed 复用，不重复存储。
6. review manifest 必须覆盖 ACTIVE v6 的 125 case exactly once。
7. GT-H3B seal manifest **禁止 `expect_fields`**；发现事实问题必须回 candidate 修正，不能在 review 时改 truth。
8. 运行：

```bash
uv run python scripts/golden/review.py \
  --manifest <gt-h3b-125-review-manifest.json> \
  --reviewer project-owner
```

9. 必须一次性得到全量 REVIEWED 125/125；ACTIVE pointer last；失败不得留下半发布状态。

### seal 后必须验证

- ACTIVE 指向新 reviewed version（按实际生成名称记录，不预设硬编码）。
- REVIEWED 125 / COMPILED 0。
- reviewed_by = `project-owner`。
- 每条 evidence ref 都指向 content-addressed evidence store 且 hash 与实际 bytes 精确一致。
- quantity / event coverage / review / production formal gates 均为空。
- v1-v6 历史 versioned files immutable。
- historical run-bound Golden replay 不因 ACTIVE 前进而改变。
- tampered evidence、manifest stats mismatch、partial manifest、duplicate/foreign case、artifact changed after staging 均 fail closed。

## PR / CI / Reviewer 门

建议将 safe promotion + GT-H3B evidence/seal 工具改动放在一个受控 PR 中，但分两个清晰 checkpoint：

- A: promotion implementation + tests；可以在测试/受控执行中推进 ACTIVE v6，但不得 seal。
- B: evidence bytes 完整、125-entry manifest 完成并执行一次 atomic seal。

最终 PR 仍必须通过：Windows 3.14、Windows 3.12、Ubuntu 3.14、Ruff、mypy、full pytest、Spike、SDK-absent、DEVLOG、Management doc，并由独立 Reviewer 对 final head + current-main test-merge 关闭后才能 merge。

## 后续

只有 GT-H3B merged 后，才授权一次受控 Formal Production B1-B7。仍不得提前进入 Data Sufficiency、Provider verdict 或 2020+ backfill。
