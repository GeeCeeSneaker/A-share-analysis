# A-share-analysis · Trading Rule H1 Seal 生命周期 P0 实现记录

日期：2026-09-09（Asia/Shanghai）

## 1. 本轮交付

已在 `scripts/rules/review.py` 增加显式 non-ACTIVE candidate seal 路径，保留原有 `--rules` 兼容路径。新路径不会先把 H1 candidate 暴露为 ACTIVE，受控迁移为：

```text
expected old ACTIVE COMPILED
        + explicit non-ACTIVE candidate snapshot
        + complete RULE_EVIDENCE_BUNDLE.v1
        ↓
new immutable REVIEWED version
        ↓
ACTIVE 最后一次原子切换
```

当前实现只在隔离临时规则根目录使用合成证据字节做合同测试；没有读取、保存或提交正式 H1 原始 HTML/PDF bytes，也没有运行真实 H1 seal、切换仓库 ACTIVE 或执行 Formal Production B1-B7。

## 2. 显式输入合同

```text
--candidate <rules-root>/versions/<candidate-version>/rules.yaml
--candidate-version <single-safe-component>
--expected-candidate-hash <sha256>
--evidence-bundle <RULE_EVIDENCE_BUNDLE.v1 input>
--reviewer project-owner
--version <new-reviewed-version>
--from-version <expected-current-active-parent>
```

`--expected-candidate-hash` 使用与规则 manifest 相同的组合算法：对规范化相对路径 `versions/<candidate-version>/rules.yaml` 和候选文件 bytes 按顺序计算 SHA-256。当前 H1 candidate 的本地冻结值为：

```text
candidate: v20260909-h1-compiled
dataset version in YAML: 2026-09-09.1
candidate dataset hash: 75d21777f1f135c47b963868641dfffc5428c5c5d897e17480a91ebaec1edd51
expected ACTIVE parent: v20260824-compiled
```

candidate version、候选 hash、父 ACTIVE 版本和 reviewer marker 均显式传入；工具不会扫描目录自动挑选“最新 candidate”。

## 3. 已实现的安全边界

| 要求 | 实现位置 / 行为 | 失败结果 |
|---|---|---|
| 单写者边界 | `main()` 先取得 `.review.lock`，再读取 ACTIVE/candidate，锁覆盖 staging 到 ACTIVE commit | 锁存在时 fail closed，不读取候选 |
| 父版本绑定 | `--from-version` / `--expected-active-version` 与完整 `load_active_rules()` 校验 | 父版本、文件列表或 hash 漂移时不发布 |
| candidate 路径 | 只接受 `versions/<candidate-version>/rules.yaml`；拒绝 traversal、外部路径、staging、版本目录/文件符号链接 | 零输出副作用 |
| 单次快照 | candidate source bytes 只从版本库读取一次；hash、解析、变换均使用同一 bytes 对象；提交前/后回读仅做 bytes、hash 和文件身份验证 | 第二次读取永不重绑定 reviewed 或 candidate hash；candidate 发生漂移时分别在提交前 fail closed 或提交后返回 `REVIEW_COMMIT_INCONSISTENT` |
| candidate 状态 | 要求 non-ACTIVE、`COMPILED`、非空 dataset version、`RULE_EVIDENCE_BUNDLE.v1` | 已 REVIEWED 或合同缺失时拒绝 |
| 证据合同 | 复用 `prepare_rule_evidence_bundle()` 的 14/14 rule、required URL exact coverage、官方 host/kind/role、原始 hash/size/content-address/path confinement | missing/extra/duplicate/tamper fail closed |
| reviewed 变换 | 从 candidate snapshot 在内存中生成新 bytes；候选目录只读 | candidate 保持 COMPILED，不被覆盖 |
| staging gate | 暂存 raw evidence、bundle 和新 reviewed 版本后运行完整 `trading_rule_review_gate(..., require_evidence_bundle=True)` | 失败清理本次所有新文件，ACTIVE 不变 |
| 原子发布 | 新版本先 rename/publish，manifest 最后 `Path.replace()` | manifest 写入/替换失败回滚版本、证据和临时文件 |
| post-commit | 重新加载 ACTIVE、重跑完整 review/evidence gate，并验证 candidate 与旧 parent 保持不变 | 已提交但 ACTIVE/candidate 不一致时返回 `REVIEW_COMMIT_INCONSISTENT`，不伪装为成功 |

旧 `v20260824-compiled` 和 H1 `v20260909-h1-compiled` 不在本路径中写入；正常 happy path 下两者 bytes 均保持不变。

## 4. 回归覆盖

新增 `tests/integration/test_h1_rule_seal_lifecycle.py`，覆盖：

1. candidate non-ACTIVE → 新 REVIEWED → ACTIVE 直接切换；
2. 错误 expected parent 零副作用；
3. candidate 外部路径、traversal 和符号链接逃逸拒绝；
4. candidate 已 REVIEWED 拒绝；
5. candidate hash 不匹配拒绝；
6. candidate snapshot 后被修改时拒绝提交，且不会使用第二次读取的新 bytes；提交后 candidate 修改返回 `REVIEW_COMMIT_INCONSISTENT`；
7. parent 在 seal 前或 staging 后移动时阻断并清理；
8. 预存 single-writer lock 在候选读取前阻断；
9. evidence bundle 的 missing、extra、duplicate、预存 wrong-hash 和运行时 raw tamper 均经 `--candidate` 入口 fail closed；
10. staging gate 失败清理 raw/bundle/version；
11. ACTIVE manifest 写入失败回滚并释放锁；
12. happy path post-commit bundle gate 为空且候选/旧 parent bytes 不变。

本地 focused 结果：`19 passed, 1 skipped`（20 个用例）；skip 仅表示当前 Windows 环境无法创建测试符号链接，不代表生产路径放宽该检查。

## 5. 当前治理边界与下一步

本实现分支仍未获得独立 Reviewer 合并确认，因此：

- 不开始正式 14-rule evidence materialization；
- 不运行 H1 REVIEWED seal；
- 不把 H1 candidate 切为 ACTIVE；
- 不重试 Formal Production B1-B7。

待本 P0 实现经三平台 CI 和独立 Reviewer 审阅并合并后，才从届时 clean current-main checkout 获取真实第一方 bytes、构造 14-rule exact bundle，生成独立 evidence/seal PR；该 PR 合并后才按要求重试 B1-B7。
