# ADR-014: Rule Manifest Selector Contract（confinement + coherence + 双版本绑定）

- 状态：ACCEPTED
- 日期：2026-08-25
- 依据：审计 R4-A2.5/CR-1.2.1 复审（裁决 REOPENED）→ R4-A2.6 / CR-1.2.2 开发工作要求（P0-03/P0-04 + P1-01/02）
- 关系：**amendment to ADR-013 §1-§2**（版本模型不变；selector 契约收紧）
- 登记变更：DM-CR-20260825-006（管理总册 §61）

## 1. Confinement（P0-03）

`rule_manifest.json` 的 `dataset_files[]` 在**任何文件系统访问之前**经过
`_confined_dataset_file`：

- 相对路径（无绝对路径 / 无盘符）；
- 词法与 resolve 双重拒绝 `..`（resolve 同时覆盖 symlink 逃逸）；
- 必须位于 `versions/<rule_version>/` 之下——**selector id 与版本目录结构
  一致**（manifest 声明 v1 的数据就只能引用 versions/v1/ 内的文件）。

ACTIVE 加载（`load_rule_manifest`）与 bound 复放（`load_bound_rule_book`）
**共用同一 helper**——不存在两套漂移的 confinement 规则。

## 2. Metadata Coherence（P0-04）

manifest 与 dataset 是同一版本身份的两个视图；重复的治理字段**必须比较**，
不允许"两边都写但不比"：

```text
manifest.review_status    == dataset.review_status
manifest.source_version   == dataset.source_version
manifest.review_provenance ~= dataset.review_provenance  (语义等价)
manifest.dataset_version  == dataset.version
```

review_provenance 的语义等价：任一侧非空的键必须两侧精确一致（空值键 /
缺失键等价——COMPILED 占位形态；datetime 由 yaml 自动反序列化，比较前
规范化为 ISO）。**REVIEWED 印章从不为空**，真实分歧必然暴露。

### Run 双版本绑定

SpikeRun 绑定**两个独立的版本身份**：

```text
trading_rule_version          = manifest.rule_version   (SELECTOR id)
trading_rule_dataset_version  = rules.yaml.version      (CONTENT version)
trading_rule_dataset_files[]  + dataset_hash            (文件清单+联合 hash)
trading_rule_review_status    + trading_rule_source_version
```

`load_bound_rule_book` 复验：文件清单 confinement（结构上属于
versions/<selector>/）+ 联合 hash + dataset content version——三重一致才
放行。

## 3. P1 落地

- `provenance_complete()`：formal（PRODUCTION）provenance 完整性包含
  rule binding（selector + files + hash + review status）；
- review 工具 ACTIVE 切换 crash-safe（tmp + os.replace）；`--from-version`
  血缘检查（拒绝 ACTIVE 已移动后的静默切换）；输入必须是当前 ACTIVE
  数据集（拒绝任意旧/外部 compiled yaml 直接产出 REVIEWED 并切 ACTIVE）；
  切换后 coherence 自验证。

## 4. 治理字段 SoR 说明

重复字段（review_status / source_version / provenance / version）在 manifest
与 dataset 双写并强制相等，而不是删除一侧：dataset 自描述是审计友好性
（单文件可判读其身份）；manifest 是 selector 的原子视图。等价比较使双写
成为**交叉校验**而非分歧源。

## 5. 测试

tests/integration/test_rule_manifest_closure.py：traversal / 绝对路径 /
symlink / version-dir 不匹配 ×2（ACTIVE + bound）/ 一致性 ×5 / 双版本
绑定 / provenance ×3 / review 工具 ×3。
