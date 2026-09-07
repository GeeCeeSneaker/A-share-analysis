# A-share-analysis Owner Human 授权关闭与 GT-H3B 原子封印执行要求（2026-09-07）

## 1. 管理裁决

本文件关闭此前仅剩的 Human authorization 形式性阻断，并授权进入 **GT-H3B：完整 evidence-byte binding + atomic REVIEWED seal**。

权威基线：

- 执行前 main：`535826509803913d4c8f45b0e4dd65414607e675`
- ACTIVE candidate：`v5-candidate-20260907`
- v5 dataset SHA256：`5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c`
- PR #22 received-result：12/12 `APPROVE`，0 `REJECT`
- 原 113 条 APPROVE：review-identity carry-forward 已验证并由 Owner 明确认可
- legacy `50`：仅表示 ST_TRANSITION corpus coverage quota，不具有市场真值/expected-field 语义
- Owner/Human final authorization：PR #22 comment `5571626576`
- Human marker / `reviewed_by`：`project-owner`
- Owner authorization time：`2026-09-07T21:49:00+08:00`

Owner 已明确说明自己就是本轮 Human Reviewer；后续不得再要求额外模板化 human marker、签名文本或重复 125/125 审阅。GitHub Owner 评论即为可审计的 Human authorization provenance。

## 2. GT-H3B 目标

把当前 v5 `COMPILED 125/125` 一次性转换为一个新的、不可变、content-addressed、`REVIEWED 125/125` Golden 版本。

目标状态：

- 125/125 `REVIEWED`
- 0 `COMPILED`
- `reviewed_by == "project-owner"`
- 每条 case 的 evidence 必须可解析、可 hash、可复核
- `quantity_gate=[]`
- `event_coverage_gate=[]`
- `review_gate=[]`
- `production_formal_gate=[]`
- v1-v5 versioned datasets/manifests 保持不可变
- ACTIVE 仅在 evidence 与新 reviewed version 全部验证成功后最后推进

本阶段只完成 Golden seal；Formal Production B1-B7 仍须等 GT-H3B PR final CI、独立 Reviewer closure 和 merge 后另行授权。

## 3. 不得改变 Golden truth

GT-H3B 是 evidence binding，不是 candidate correction。

严格要求：

- 不得修改 v5 case identity、symbol、trade_date、effective date、event class/subtype、expected_fields、truth_source 或 source_ref 来“让 seal 通过”。
- seal manifest 禁止 `expect_fields`。
- 若 materialized official evidence 不能证明现有 case，立即停止该 seal，返回 candidate governance；不得在 review 阶段修 truth。
- 不得使用 Provider-under-test 输出、搜索摘要、AI 总结、截图、媒体转载替代官方原始材料。

## 4. Evidence materialization

对全部 125 条建立最终 evidence binding。允许多个 case 复用同一份 content-addressed official artifact，不重复存储同一 bytes。

优先材料仍为 GT-H2 / GT-H3 / GT-H3R 中已人工核验的 exact official source。下载/采集时：

1. PDF 保留官方原 PDF bytes。
2. HTML 保留官方原始 response/body，不转成浏览器打印 PDF。
3. redirect/final URL 可记录，但不得静默换成不同事实来源。
4. review.py 自行对实际 seal bytes 计算 SHA256；禁止手工录 hash 作为真值。
5. materialization 后若材料不存在、内容不再支持 claim、或来源发生实质变化，fail closed。

Owner 对 12 条整改结果与 113 条 carry-forward 的确认不豁免 evidence-byte 完整性。

## 5. P0：5 个复合事实必须同时绑定 RULE + APPLICABILITY

当前 `review.py` 和 Golden case provenance 是单 `source_artifact_*` 模型：每个 case 只能直接绑定一个 artifact。GT-H3R 已明确以下 5 条 Human approval 依赖两份官方材料：

- `GT-LIMIT-ST5-600518-20190603`
- `GT-LIMIT-ST5-600518-20191028`
- `GT-LIMIT-STAR20-688981-20200723`
- `GT-LIMIT-IPO44-601995`
- `GT-LIMIT-IPO44-605499`

因此 **不得在 final seal 时只选其中一份材料并丢弃另一份证明链**。

### 首选低复杂度实现：content-addressed EVIDENCE_BUNDLE

保持 Golden case 的单 root artifact 模型，不把数据结构全面改成 list：

- 新增 artifact kind：`EVIDENCE_BUNDLE`。
- 每个复合 case 生成一个 deterministic bundle（推荐 deterministic ZIP；固定 entry 顺序和 metadata）。
- bundle 内至少包含：
  - `MANIFEST.json`
  - RULE 官方原始 bytes
  - APPLICABILITY 官方原始 bytes
- `MANIFEST.json` 至少绑定：case ID、role、official source ref、child filename、child artifact kind、child SHA256。
- child bytes 必须保持官方原始 bytes，不做内容转换。
- `review.py` 在 staging 阶段必须验证 bundle schema、case ID、RULE/APPLICABILITY roles、child hashes、official-source mapping；验证通过后对整个 bundle bytes 做现有 SHA256 content-addressed seal。
- `GoldenTruthStore._verify_artifact()` 对 `EVIDENCE_BUNDLE` 不仅验证 outer hash，还必须打开 bundle、验证 manifest 与 child hashes；缺 child、hash mismatch、foreign role/source、malformed bundle 一律 fail closed。

允许开发者提出同等或更简单且可证明不会丢失第二份证据的实现，但不得退回“只 bind 一份、另一份留在 Markdown/sidecar”的弱方案。

该修正属于 GT-H3B evidence model 的必要技术收口，不是重新打开 Golden semantics。

## 6. 其余 120 条

单一官方材料足以支撑 case 的，继续使用现有 native artifact kinds：

- `SSE_ANNOUNCEMENT`
- `SZSE_ANNOUNCEMENT`
- `BSE_ANNOUNCEMENT`
- `CSRC_DOCUMENT`
- `EXCHANGE_RULEBOOK`
- `COMPANY_ANNOUNCEMENT`
- `INDEX_METHODOLOGY`
- `OTHER_OFFICIAL`

相同 bytes 在不同 case/group 中必须自然复用同一 `sha256/<hash>.<ext>`。

## 7. 原子 seal

在 multi-evidence 技术收口及全部 evidence materialization 完成后，构造完整 125-entry review manifest。

每个普通 entry 仅允许：

```json
{"case":"...","artifact":"...","kind":"...","note":"..."}
```

复合 case 的 `artifact` 指向已经通过严格校验的 `EVIDENCE_BUNDLE`。

执行：

```bash
uv run python scripts/golden/review.py --manifest <gt-h3b-review-batch.json> --reviewer project-owner
```

必须一次覆盖 ACTIVE 125 case exactly once。任何 missing / duplicate / foreign / malformed / artifact error 都必须在 durable publication 前失败。

review.py 生成的 `reviewed_at` 可以使用 seal execution timestamp；Owner Human authorization 的实际时间已由 PR #22 comment `5571626576` 独立保存，不需要人为伪造 reviewed_at。

## 8. Seal 后验收

开发者必须输出并在 PR 中登记实际生成值，不提前硬编码版本名。预计会从 v5 进入下一个 reviewed version，但以 review.py 实际输出为准。

至少验证：

- ACTIVE truth_version / dataset_file / dataset_hash
- 125 `REVIEWED` / 0 `COMPILED`
- 所有 `reviewed_by == project-owner`
- 所有 `reviewed_at` 合法 ISO timestamp
- 每条 source artifact ref 可解析
- outer hash 全部精确匹配
- 5 个 composite bundles 内部 child hash 与 RULE/APPLICABILITY mapping 全部精确匹配
- reviewed dataset semantic hashes 全通过
- manifest statistics 重算一致
- quantity/event/review/formal gates 全部为空
- v1-v5 immutable bytes 未变化
- 历史 run-bound Golden replay 不因 ACTIVE advance 改变

## 9. 必需 adversarial tests

除现有 partial/duplicate/foreign/changed-after-staging 等测试外，新增：

- composite bundle missing RULE -> reject
- composite bundle missing APPLICABILITY -> reject
- child hash mismatch -> reject
- bundle case ID mismatch -> reject
- bundle source mapping 与 GT-H3R required sources 不一致 -> reject
- malformed/unsafe bundle path -> reject
- tampered sealed bundle -> Formal review gate fail closed
- GT-H3B manifest 出现 `expect_fields` -> reject
- single-source case 不得无故使用 composite bundle 来逃避 native artifact validation

## 10. PR / CI / merge gate

GT-H3B 使用独立 PR。最终 head 必须通过：

- Windows Python 3.14
- Windows Python 3.12
- Ubuntu Python 3.14
- Ruff lint / format
- mypy
- full pytest
- Spike gates
- SDK-absent
- DEVLOG gate
- Development Management gate

流程固定为：Developer final head -> current-main GitHub test-merge -> required CI -> 独立项目 Reviewer closure -> merge。

在 Reviewer closure / merge 前不得运行 Formal Production B1-B7。

## 11. 下一阶段

GT-H3B 合并后，项目管理者再单独授权一次 controlled Formal Production B1-B7 attempt。该运行仍可能得到 NO-GO；不得为了制造 GO 修改 Golden truth 或规则。
