# A-share-analysis：R4-A2.6 / CR-1.2.2 复审结论与 R4-A2.7 / CR-1.2.3 开发工作要求

> **Review Date**：2026-08-25 13:19 +08:00  
> **Reviewed Repository HEAD**：`2e85f4477c89486a7de401d068c383378ecbc3f0`  
> **Previous Reviewer Requirement Commit**：`8bb4d2fa5e2fb3298587962ebb0141602c2b7dfc`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2.6 Formal Truth / Manifest Closure、CR-1.2.2 Probe Exchange Enforcement、ADR-014、RawWriter idempotency、Corporate Action Provider Shape、DEVLOG / Development Management、CI  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.7 Final Integrity / Provider-Shape Closure + CR-1.2.3 Evidence Identity Closure**  
> **CR-2**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. 裁决摘要

本轮相对上一批继续取得实质进展。上一轮四项 P0 中，以下主体实现已经成立并允许保留：

```text
B5/B6 provider-call execution boundary
→ 已统一进入 ProbeExecutor.call
→ success / failure exchange 均可落 Raw
→ B6 prerequisite failure 不再继续发射 stock_basic

Golden CA typed truth
→ event_class 成为 formal type fact
→ DIVIDEND_EX_DATE / RIGHT_ISSUE_EX_DATE 显式映射
→ unknown / untyped / conflict fail closed
→ actual v3 20 个 CA cases 已进入 regression

Rule Manifest
→ ACTIVE selector 已建立 path confinement
→ selector version / dataset content version 已分离绑定
→ manifest↔dataset metadata coherence 已开始强校验

Raw commit recovery
→ partial same-byte orphan 可恢复
→ undeclared orphan member 整集 quarantine

CI
→ GitHub Actions run 38 / HEAD 2e85f447... = completed / success
```

因此本轮**不回退** ADR-010/011/012/013/014 的主体架构，也不重新打开已经关闭的 hidden-calendar、meta-anchor、full-request lineage、run-bound rule consumer 等问题。

但 Reviewer 在代码级复核中发现新的 blocking correctness 问题：

```text
1. Bound Rule confinement 仍在一次 filesystem existence probe 之后执行；
2. RawWriter complete-idempotent success 返回的 evidence_hash 不是磁盘真实 meta hash；
3. Rule metadata coherence 对 source_version / dataset_version 的缺失仍可放行；
4. Corporate Action 的真实 AmazingData payload shape 与当前 validator/FakeTarget 的 canonical-like shape 不一致。
```

其中第 2、4 项直接影响 Immutable Evidence / Real Provider Truth；第 1、3 项直接违反上一轮已写入 ADR-014 的 fail-closed contract。

因此本轮不能 VERIFIED。

---

# 1. 本轮已通过并冻结的实现

## 1.1 CR-1.2.2：B5 / B6 Exchange Enforcement —— PASS

当前 B5 / B6 code-list prerequisite 已改为：

```python
payload, meta = executor.call(
    "BaseData.get_code_list",
    lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
    ...
)
```

并具备：

```text
success exchange -> RawWriter
failure exchange -> failure meta + structured case
B6 prerequisite failure -> stock_basic does not fire
```

`tests/integration/test_probe_exchange_enforcement.py` 已增加：

```text
B5 success/failure
B6 success/failure
B2-B7 spy count: exchange calls == persisted metas
AST formal boundary guard
```

这一设计保留，禁止回退为“调用者手工记得 persist”。

## 1.2 Golden CA formal event type —— 语义模型 PASS

当前 formal CA type resolution：

```text
DIVIDEND_EX_DATE    -> DIVIDEND
RIGHT_ISSUE_EX_DATE -> RIGHT_ISSUE
```

且：

```text
expected_fields.event_type present -> must agree
event_class unknown/missing        -> EVENT_TYPE_UNRESOLVED
exact-date wrong event type        -> EVENT_TYPE_MISMATCH
```

actual Golden v3 的 20 个 CA cases 已参与类型回归，不再是 synthetic-only。

注意：**本节只代表 Golden Truth 的类型语义模型通过；真实 Provider payload 字段适配尚未通过，见 P0-04。**

## 1.3 Rule selector/content 双版本模型 —— 主体 PASS

保留：

```text
trading_rule_version          = manifest.rule_version
trading_rule_dataset_version  = dataset version
trading_rule_dataset_files[]
trading_rule_dataset_hash
trading_rule_review_status
trading_rule_source_version
```

以及 ACTIVE advance 后 historical run 继续使用 bound dataset 的原则。

## 1.4 CI —— VERIFIED GREEN

Reviewer 通过 GitHub Actions API 正向确认：

```text
run 38
HEAD = 2e85f4477c89486a7de401d068c383378ecbc3f0
status = completed
conclusion = success
```

所以本轮 CI 不是阻塞项。

---

# 2. P0-01：Bound Rule Dataset 在 confinement 前发生 filesystem probe

## 2.1 当前代码问题

ADR-014 明确要求：

```text
dataset_files[]
→ confinement FIRST
→ only then filesystem existence/read/hash
```

ACTIVE path `load_rule_manifest()` 已基本符合。

但 `load_bound_rule_book()` 当前首先通过：

```python
root = next(
    (c for c in candidates if (c / dataset_files[0]).is_file()),
    None,
)
```

来选择 root，之后才对每个 `rel` 调用：

```python
_confined(...)
_confined_dataset_file(...)
```

这意味着一个被篡改的 historical run binding：

```text
dataset_files[0] = ../../outside.yaml
```

在被拒绝前，已经对 root 外路径进行了一次 filesystem existence probe。

虽然随后仍会 fail closed、当前没有形成 false GO，但它直接违背：

```text
confinement before ANY filesystem access
ACTIVE and bound use the same confinement discipline
```

而且管理文档 / ADR-014 已把该要求声明成已实现。

## 2.2 强制修复

`load_bound_rule_book()` 不得根据未经验证的 `dataset_files[0]` 探测 root。

root 的来源已经是确定性的：

```text
rules_root
OR repo_root/configs/trading_rules
OR default rules dir
```

因此应：

```text
1. resolve root without touching dataset_files
2. for ALL dataset_files:
   - lexical confinement
   - resolved-path confinement
   - versions/<rule_version>/ structural confinement
3. only after ALL pass:
   - is_file
   - read/hash
   - dataset load
```

## 2.3 Required Tests

```text
[ ] bound ../../outside.yaml, outside file exists -> BLOCK
[ ] above case proves outside path is not stat/read/opened before rejection
[ ] bound absolute path -> BLOCK before fs access
[ ] bound symlink escape -> BLOCK
[ ] bound versions/<other>/... -> BLOCK
[ ] valid bound multi-file version -> PASS
```

建议用 monkeypatch / spy 包装 Path.is_file/read_bytes/open（或更窄的 file-access abstraction），证明非法路径在 confinement 前没有被触碰。

---

# 3. P0-02：RawWriter complete-idempotent success 返回错误 evidence identity

## 3.1 当前问题

`RawWriter._meta_bytes()` 每次调用都会生成新的：

```python
"ingested_at": datetime.now(UTC).isoformat()
```

`_check_idempotent()` 对完整已存在 exchange 的比较会忽略 `ingested_at`：

```text
same meta except ingested_at + same payload bytes
=> idempotent = True
```

这是正确的幂等判定方向。

但 `_write_success()` 随后做：

```python
idem = self._check_idempotent(...)
if not idem:
    self._commit_files(...)

meta_hash = sha256(meta_bytes).hexdigest()
return RawWriteResult(
    evidence_hash=meta_hash,
    meta_artifact=ArtifactRef(..., content_hash=meta_hash),
)
```

当 `idem=True` 时：

```text
磁盘保留 OLD meta bytes（old ingested_at）
函数持有 NEW meta_bytes（new ingested_at）
函数返回 sha256(NEW meta_bytes)
```

所以：

```text
returned evidence_hash
!=
sha256(actual persisted <request_id>.meta.json)
```

这会导致调用者把第二次幂等返回值绑定到 SpikeCase 后，`verify_evidence_closure()` 对真实文件复算 hash 时直接失败。

这违反：

```text
RawWriteResult must describe the persisted evidence, not an unpersisted candidate serialization.
```

## 3.2 强制修复

所有 success return path 最终都必须以**磁盘实际持久化 bytes**为证据身份：

推荐：

```python
persisted_meta_bytes = meta_path.read_bytes()
meta_hash = sha256(persisted_meta_bytes).hexdigest()
```

对于 `idem=False` 的新 commit，可以额外断言：

```text
persisted_meta_bytes == intended meta_bytes
```

对于 `idem=True`：

```text
return existing persisted meta hash
```

不要为了让 hash 一致而覆盖旧 meta；immutable semantics 应保留首次成功落盘的 meta bytes。

## 3.3 Required Tests

```text
[ ] write same exact success exchange twice
[ ] second.idempotent == True
[ ] second.evidence_hash == sha256(actual meta file bytes)
[ ] second.meta_artifact.content_hash == same actual hash
[ ] single-table idempotent retry -> SpikeCase binding -> evidence closure PASS
[ ] multi-table idempotent retry -> SpikeCase binding -> evidence closure PASS
[ ] failure idempotent retry keeps existing correct behavior
[ ] orphan-recovery retry still returns actual persisted meta hash
```

现有仅检查：

```text
first.idempotent is False
second.idempotent is True
```

不够，必须检查**returned identity == persisted identity**。

---

# 4. P0-03：Rule metadata coherence 仍允许 source_version / dataset_version 缺失

## 4.1 当前代码

ADR-014 的契约是：

```text
manifest.review_status   == dataset.review_status
manifest.source_version  == dataset.source_version
manifest.dataset_version == dataset.version
manifest.review_provenance ~= dataset.review_provenance
```

但当前 `load_active_rules()` 对两个字段仍使用条件比较：

```python
if manifest.dataset_version and book.version != manifest.dataset_version:
    ...

if manifest.source_version and manifest.source_version != book.source_version:
    ...
```

因此：

```text
manifest.source_version = ""
dataset.source_version  = "official-source-vX"
```

或者：

```text
manifest.dataset_version = ""
dataset.version          = "2026-08-24.1"
```

当前仍可通过 coherence load。

更重要的是 `new_run()` 当前把：

```text
trading_rule_source_version = manifest.source_version
```

写入 Run，因此空 manifest source_version 会直接形成缺失的 formal source lineage。

## 4.2 强制修复

当前版本模型下，manifest schema 必须要求：

```text
source_version  = non-empty
dataset_version = non-empty
```

然后**无条件 exact compare**：

```text
manifest.source_version == book.source_version
manifest.dataset_version == book.version
```

不要用“如果 manifest 填了才比较”的 optional semantics。

`SpikeRun.provenance_complete()` 对 PRODUCTION 建议同时要求：

```text
trading_rule_dataset_version
trading_rule_source_version
```

非空；否则 semantic SoR provenance 不完整。

Bound replay / verdict 也建议把 bound source_version/review_status 与实际 loaded book 复验，而不仅复验 selector/content-version/hash。

## 4.3 Required Tests

```text
[ ] source_version missing -> manifest load / active load BLOCK
[ ] source_version empty -> BLOCK
[ ] dataset_version missing -> BLOCK
[ ] dataset_version empty -> BLOCK
[ ] source_version mismatch -> BLOCK
[ ] dataset_version mismatch -> BLOCK
[ ] PRODUCTION provenance with empty trading_rule_source_version -> incomplete
[ ] PRODUCTION provenance with empty trading_rule_dataset_version -> incomplete
[ ] bound loaded book source/review status disagrees with run binding -> BLOCK
```

---

# 5. P0-04：Corporate Action 使用的字段契约与 AmazingData 官方 payload 文档不一致

## 5.1 Reviewer 外部契约核验

Reviewer 对照 AmazingData 官方 API 文档：

```text
https://amazing.ptradeapi.com/index.html
3.5.7.1 get_dividend
3.5.7.2 get_right_issue
```

官方文档当前列出的关键字段：

### get_dividend

```text
MARKET_CODE   证券代码
DATE_EX       除权除息日
```

文档未列出：

```text
SECURITY_CODE
EX_DATE
EVENT_TYPE
```

### get_right_issue

```text
MARKET_CODE        证券代码
EX_DIVIDEND_DATE   除权日
```

文档同样未列出：

```text
SECURITY_CODE
EX_DATE
EVENT_TYPE
```

## 5.2 当前真实 Provider adapter

当前 `AmazingDataProvider` 对两个接口直接：

```python
_info().get_dividend(code_list=...)
_info().get_right_issue(code_list=...)
```

通过 `_call_or_exchange()` 包装成 ProviderExchange，没有在 adapter 中把 payload 字段归一化为：

```text
SECURITY_CODE / EX_DATE / EVENT_TYPE
```

这很好地保留了 raw provider payload，但意味着下游 validator 必须显式理解 provider schema 或经一个明确的 validation adapter。

## 5.3 当前 Golden validator / FakeTarget

当前 CA validator 却按下面字段筛选：

```python
r.get("SECURITY_CODE")
r.get("EX_DATE")
r.get("EVENT_TYPE")
```

FakeTarget 同样直接合成：

```text
SECURITY_CODE
EX_DATE
EVENT_TYPE
```

因此当前 CI/Golden CA tests 证明的是：

```text
validator works with synthetic canonical-like Fake rows
```

但没有证明：

```text
real AmazingData get_dividend / get_right_issue payload
→ validator input contract
```

在真实账号上，按官方文档 shape，很可能发生：

```text
symbol never matches SECURITY_CODE
or date never matches EX_DATE
or EVENT_TYPE absent
```

最终 Corporate Action formal Golden 无法按真实 provider 数据完成验证。

## 5.4 强制设计原则

**不要修改 Raw evidence。Raw 必须继续保存 provider 原始字段。**

应在 Spike semantic validation 边界增加明确、可测试的 provider-shape adapter，例如：

```text
raw ProviderExchange payload
        ↓
AmazingData CA validation adapter (ephemeral / in-memory)
        ↓
canonical validator view
        ↓
Golden CA validator
```

最低映射契约：

### Dividend stream

```text
provider MARKET_CODE -> validator security_code
provider DATE_EX     -> validator ex_date
event type           -> DIVIDEND（来自 endpoint identity，不伪造 payload field）
```

### Right-issue stream

```text
provider MARKET_CODE       -> validator security_code
provider EX_DIVIDEND_DATE  -> validator ex_date
event type                 -> RIGHT_ISSUE（来自 endpoint identity）
```

重要：

```text
EVENT_TYPE 是 endpoint/domain semantics
!= 假称 provider payload 原生包含 EVENT_TYPE
```

建议不要直接往 raw row 原地塞 `EVENT_TYPE` 后再假装是 provider 字段；可使用 typed normalized view/dataclass，并保留来源：

```text
source_endpoint
source_field_mapping
raw_request_id
```

但不要借此提前启动 CR-2 Provider-Normalized 持久化层。本批只解决 Spike validator 的真实 Provider schema boundary。

## 5.5 Fail-closed 要求

如果真实 payload 缺少官方契约字段：

```text
DIVIDEND missing MARKET_CODE/DATE_EX
RIGHT_ISSUE missing MARKET_CODE/EX_DIVIDEND_DATE
```

必须：

```text
ProviderSchemaError / structured VALIDATED_FAIL
```

不得：

```text
silent empty rows
first plausible alias wins
infer from unrelated fields
```

如果 SDK 实际版本与当前官方文档字段发生差异，应在 P0-M-1B live evidence 中记录并建立版本化 schema mapping；当前代码至少要对文档 contract 有真实 fixture 覆盖。

## 5.6 Required Tests

新增 **provider-shaped fixtures**，不能只使用 Fake canonical-like rows：

```text
[ ] dividend row: MARKET_CODE + DATE_EX, no SECURITY_CODE/EX_DATE/EVENT_TYPE -> normalized semantic row correct
[ ] right_issue row: MARKET_CODE + EX_DIVIDEND_DATE, no SECURITY_CODE/EX_DATE/EVENT_TYPE -> normalized semantic row correct
[ ] endpoint-derived event type is DIVIDEND / RIGHT_ISSUE respectively
[ ] wrong endpoint-type cannot satisfy opposite Golden event type
[ ] missing MARKET_CODE -> fail loud
[ ] dividend missing DATE_EX -> fail loud
[ ] right_issue missing EX_DIVIDEND_DATE -> fail loud
[ ] raw persisted payload remains ORIGINAL provider field names
[ ] semantic validator uses normalized view from the exact same persisted exchange
[ ] actual Golden v3 DIVIDEND case + provider-shaped dividend fixture -> reaches typed validator
```

若项目有可使用的真实 SDK schema sample（已 scrub），可加入 contract fixture；但 trial/live 数据仍不能替代正式 Production Truth。

---

# 6. P1-01：review.py 当前实际上只支持 single-file ACTIVE dataset

Rule Manifest 模型已经支持：

```text
dataset_files[]
```

并有 multi-file loader / hashing 语义。

但 `scripts/rules/review.py` 当前：

```text
只取 active.dataset_files[0]
只接受一个 --rules
只创建 versions/<new>/rules.yaml
新 manifest 也只写一个 dataset_file
```

当前真实 ACTIVE 恰好只有一个文件，所以不是本轮 false correctness P0。

但在引入 multi-file rule version 前必须二选一：

### Option A（推荐短期）

显式 fail loud：

```text
len(active.dataset_files) != 1
=> review tool refuses with clear unsupported-multi-file message
```

### Option B

review 整个 dataset_files[] 集合并原样复制/封存，新版本保持完整文件清单。

禁止未来 silent review only first file。

---

# 7. P1-02：atomic replace 与 durability wording 分离

当前 review.py：

```text
temp manifest
→ Path.replace(manifest_path)
```

可以保证 reader 看到 old-or-new 完整文件，这一点正确。

但未显式 fsync temp file / parent directory 时，不应把语义扩大为“power-loss durable crash-safe”。

二选一：

```text
A. 文档准确写 atomic replacement / reader-safe
B. 若要承诺 durable crash-safe，则加入 file fsync + parent-dir fsync（平台差异需处理）
```

这项 P1 不阻塞 R4-A2.7，只要求文档与实现一致。

---

# 8. Governance Closure

本批实现后必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

当前管理总册仍存在需要本批纠正的 current-truth 问题：

1. 顶部 `Current Code Baseline` 仍写“本批提交……提交后以其 SHA 为新基线”，没有记录当前 exact implementation SHA：

```text
2e85f4477c89486a7de401d068c383378ecbc3f0
```

2. CI 状态仍主要写 run35/run36；Reviewer 已确认当前：

```text
run38 / 2e85f447... = SUCCESS
```

3. ADR-014 / §41 声明 bound dataset “任何 fs 访问前 confinement”，但 runtime 目前并不完全满足。必须用本次 Reviewer correction 记录修正，不能继续 overclaim。

4. R4-A2.6 / CR-1.2.2 当前 Review 应更新为：

```text
REOPENED
```

5. RISK-004 保持 OPEN/REOPENED，直到 R4-A2.7 / CR-1.2.3 Reviewer VERIFIED。

历史 DEVLOG 不删除；顶部追加 correction / review entry。

建议 Change IDs：

```text
DM-CR-20260825-008  Bound Rule Pre-Access Confinement Closure
DM-CR-20260825-009  Raw Evidence Identity / Idempotency Closure
DM-CR-20260825-010  Rule Metadata Required-Coherence Closure
DM-CR-20260825-011  Corporate Action Provider-Shape Adapter
DM-CR-20260825-012  R4-A2.7 Reviewer Governance Closure
```

P0-04 如引入明确的 provider-specific semantic adapter contract，建议新增 ADR-015 或 amendment to ADR-010/014；不要借此改变 Raw SoR 或提前进入 CR-2 persisted normalized layer。

---

# 9. 推荐实施顺序

```text
Batch A — Raw Evidence Identity
  fix idempotent returned meta hash
  add closure regression

Batch B — Bound Rule + Metadata Integrity
  confinement before any fs probe
  mandatory source_version/dataset_version
  bound source/review coherence

Batch C — Corporate Action Real Provider Shape
  provider-shaped validation adapter
  documented-schema fixtures
  raw bytes remain untouched

Batch D — Review Tool Hardening
  explicit single-file limitation OR true multi-file review
  correct atomic/durability wording

Batch E — Adversarial / Whole-run Regression
  all P0 matrix
  dry-run closure
  rule replay
  actual Golden v3 CA regression

Batch F — Governance Closure
  DEVLOG
  DEVELOPMENT_MANAGEMENT exact SHA/current CI/status
  ADR if triggered
```

不要并行启动 CR-2 以避免把尚未稳定的 provider-shape / raw-evidence contract 传播到 normalized/canonical 层。

---

# 10. 最低验收矩阵

## 10.1 Raw identity

```text
[ ] success same-request same-bytes retry -> idempotent
[ ] returned evidence_hash == actual persisted meta sha256
[ ] returned meta_artifact hash == actual persisted meta sha256
[ ] single + multi table both pass
[ ] retry result used by SpikeCase -> verify_evidence_closure == []
[ ] failure idempotency unchanged
[ ] orphan recovery returned hash correct
```

## 10.2 Rule confinement / coherence

```text
[ ] ACTIVE traversal/absolute/symlink/version-dir mismatch BLOCK
[ ] BOUND traversal/absolute/symlink/version-dir mismatch BLOCK
[ ] BOUND invalid ref rejected before any file probe/read
[ ] source_version missing/empty BLOCK
[ ] dataset_version missing/empty BLOCK
[ ] review_status/source_version/provenance/content-version mismatch BLOCK
[ ] run binds selector + content version + source version
[ ] resume/verdict reverify bound identity
```

## 10.3 CA provider shape

```text
[ ] documented dividend fields normalize correctly
[ ] documented right_issue fields normalize correctly
[ ] event type derives from endpoint identity
[ ] raw evidence retains provider-native fields
[ ] semantic view references exact raw request/exchange lineage
[ ] required source field missing -> structured failure
[ ] actual v3 DIVIDEND case works with provider-shaped fixture
[ ] opposite endpoint event never satisfies case
```

## 10.4 Whole-system

```text
[ ] ruff check
[ ] ruff format --check
[ ] mypy
[ ] pytest
[ ] Actions GREEN
[ ] dry-run evidence closure zero problems
[ ] Spy exchange count closure zero difference
[ ] no last_envelopes runtime consumer
[ ] no payload-only formal provider calls
```

---

# 11. Exit Gate

R4-A2.7 / CR-1.2.3 只有满足以下条件才允许 Developer 标记 DONE / PENDING_REVIEW：

```text
[ ] P0-01 bound confinement before ANY file probe/read
[ ] P0-02 RawWriter idempotent returned identity == persisted identity
[ ] P0-03 rule source/content version required + exact coherent
[ ] P0-04 documented AmazingData CA provider shape reaches typed validator
[ ] raw evidence remains provider-native / immutable
[ ] CA type remains fail-closed
[ ] rule run-bound exact replay remains intact
[ ] all new adversarial tests pass
[ ] local CI-equivalent checks green
[ ] GitHub Actions result recorded accurately
[ ] DEVLOG updated
[ ] DEVELOPMENT_MANAGEMENT updated
[ ] ADR updated if semantic adapter contract introduced
[ ] every important change note records why / how / alternatives / costs-benefits
```

Reviewer 下轮重点只复查：

```text
1. RawWriter second idempotent return hash vs on-disk meta bytes
2. BOUND illegal dataset ref has zero pre-confinement filesystem access
3. missing source_version/dataset_version cannot enter a formal run
4. provider-shaped dividend/right-issue fixtures use documented field names
5. raw provider payload and normalized validator view remain clearly separated
6. actual Golden v3 CA cases use the mapped real-provider shape
7. current Actions result + exact HEAD recorded in governance docs
```

---

# 12. 后续阶段约束

在本批 VERIFIED 前：

```text
CR-2 Provider-Normalized + Quarantine = BLOCKED
R4-A3 expansion                       = BLOCKED
Production P0-M-1B                    = BLOCKED
```

本批 VERIFIED 后，可以重新评估：

```text
R4-A3 SDK/Lifecycle/Early Stop
CR-2 Provider-Normalized + Quarantine
```

但 Production P0-M-1B 仍需满足：

```text
Golden Truth 人工 Review + distinct-event gate
Trading Rule 人工 Review
正式 Production Account Profile
Provider Doctor actual runtime verified
所有 formal entry gates
```

Trial / Fake / CI 的成功仍不得作为正式 Provider business truth 的替代证据。

---

# 13. 变更记录要求

每个重要变更同批 Notes 必须回答四件事：

```text
1. 为什么要改？
2. 是怎么改的？
3. 之前考虑过哪些方案，为什么没有选？
4. 这样做的代价和收益是什么？
```

本批尤其必须记录：

```text
Raw idempotency: reuse persisted meta identity vs regenerate/overwrite meta
CA mapping: ephemeral validation adapter vs modify raw vs start CR-2 normalization
Rule source_version: mandatory metadata vs optional compatibility
Bound confinement: deterministic root vs probing candidate roots
```

不得只写“tests pass / bug fixed”。

---

# 14. Implementation Mapping（Developer 回填，2026-08-25）

> 本批：R4-A2.7 Final Integrity / Provider-Shape Closure + CR-1.2.3 Evidence Identity Closure（Batch A→F 全部完成；**未启动 CR-2**——遵守 §9/§12 约束）。
> 测试基线：**580 passed / 0 failed**（544 → 580，+36）；CI 等价四检查（ruff check + format --check + mypy + pytest）本地全绿；dry-run 冒烟 35 exchanges + 5 bundles 双向闭合零问题。
> Change IDs：DM-CR-20260825-008/009/010/011/012；**ADR-015**（amendment to ADR-013 §4 + ADR-014 契约补全；含 §13 四问完整记录）。
> CI：本批提交后以 Actions 实际结果为准（上批 run 38 / 2e85f447 = success，Reviewer API 确认口径——本批不预写结果）。
> **§13 四问对照**：Raw idempotency → ADR-015 §5.2（reuse persisted identity；不重写旧 meta——immutable 首次落盘保留）；CA mapping → ADR-015 §3 表（ephemeral adapter vs 改 raw vs CR-2 的取舍）；Rule source_version → ADR-015 §5.3（mandatory；optional 语义走私 lineage）；Bound confinement → ADR-015 §5.1（deterministic root；probing candidates 违反 pre-access 契约）。

## P0-01（Bound Pre-Access Confinement，§2）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 2.2 root 确定性解析（不碰 dataset_files） | `trading_rule.load_bound_rule_book`：root = rules_root / repo_root+configs/trading_rules / default dir（参数驱动三选一）；**废除** `(root/dataset_files[0]).is_file()` 候选探测 | pre_access ×3 |
| 2.2 全文件 confinement 先行 | confinement 循环（lexical `_confined` + `_confined_dataset_file` resolved+versions/<v>/ 结构）→ 存在性循环 → hash/load | 同上 |
| 2.3 非法路径零触碰证明 | **FsSpy**（monkeypatch `Path.is_file/read_bytes/open`，记录 root 外访问） | traversal（**外部文件真实存在**）/绝对路径/异版本目录 → `outside_probes == []` |
| 2.3 symlink / valid multi-file | resolve 覆盖 symlink（既有测试）；multi-file 合法加载（hash 覆盖全部文件） | closure::symlink + pre_access::test_valid_bound_multi_file_version_passes |

## P0-02（Raw Evidence Identity，§3）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 3.2 幂等返回 persisted hash | `raw_writer._write_success`：`persisted_meta_bytes = meta_path.read_bytes()` → `meta_hash = sha256(persisted)`；幂等重试**不覆盖旧 meta** | identity::test_second_write_returns_persisted_meta_hash（含 meta_artifact.content_hash） |
| 3.2 fresh commit 断言 persisted == intended | `if not idem and persisted != intended: raise RawWriterError` | identity::test_fresh_commit_asserts_persisted_equals_intended |
| 3.3 全场景 returned == persisted | 单表/多表 binding→closure / 失败幂等 / orphan 恢复 | identity 6 个（second.evidence_hash == sha256(actual file) 全断言） |

## P0-03（Required Coherence，§4）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 4.2 必填 + 无条件比较 | `load_active_rules`：两字段非空校验（"REQUIRED and empty"）+ exact compare（可选语义废除） | coherence::TestRequiredCoherence（missing/empty/mismatch ×6 + PASS） |
| 4.2 provenance 含两字段 | `model.provenance_complete`：rules_bound 增 dataset_version + source_version | coherence::TestProvenanceRequirements ×3 |
| 4.2 bound source/review 复验 | `load_bound_rule_book(source_version=, review_status=)`；runner verdict/resume + probes.rule_book 三处传完整身份 | coherence::TestBoundIdentityDisagreement ×2 + 完整一致加载 |

## P0-04（CA Provider-Shape，§5）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 5.4 ephemeral adapter（raw 不动） | `golden_router.CA_PROVIDER_FIELD_CONTRACT + _ca_provider_view`（event_type=端点身份；lineage=source_endpoint/raw_request_id）；DomainData 事件行 = normalized view | shape::TestProviderView ×7（含 payload 伪造 EVENT_TYPE 被忽略） |
| 5.5 缺字段 fail-closed | `CAProviderShapeError` → route_all 结构化 `VALIDATED_FAIL(PROVIDER_SCHEMA)` | shape::test_broken_provider_shape_structured_fail |
| 5.6 provider-shaped fixtures | FakeTarget 改文档字段（MARKET_CODE/DATE_EX；MARKET_CODE/EX_DIVIDEND_DATE）；raw parquet 列名断言 {MARKET_CODE, DATE_EX} | shape::test_fake_target_uses_documented_provider_fields + test_raw_evidence_retains_provider_native_fields |
| 5.6 opposite endpoint / actual v3 | 反向类型 fail；真实 v3 CA case provider-shaped 端到端 PASS（validator v6） | shape::test_opposite_endpoint_never_satisfies_case + test_actual_v3_case_with_provider_shape_passes |

## P1-01/02（§6/§7）

| 要求 | 实现位置 |
|---|---|
| Option A 单文件 fail loud | `review.py`：`len(dataset_files) != 1` → clear unsupported-multi-file ERROR（exit 2；禁止未来 silent review only first file） |
| Option A wording | 注释/文档更正为 **atomic replacement / reader-safe**（非 power-loss durable，无 fsync）；DEVLOG/总册不再使用 crash-safe 措辞 |

## §8 Governance（DM-CR-20260825-012）

| 要求 | 落实 |
|---|---|
| exact SHA baseline | 总册头部：上批 implementation `2e85f4477c89486a7de401d068c383378ecbc3f0`（run 38 = success） |
| CI = run 38 SUCCESS | 头部 CI Status 更新 |
| ADR-014 overclaim 修正 | 总册头部 **Reviewer Correction 段**（如实记录两处不成立；ADR-015 §5 为准；ADR-014 原文保留为历史）+ ADR-000 索引标注 |
| R4-A2.6/CR-1.2.2 → REOPENED | §40（"由 R4-A2.7/CR-1.2.3 修复（本批）"） |
| RISK-004 保持 REOPENED | §52 理由更新为本批四 P0 |
| DEVLOG 顶部追加 | 2026-08-25 新条目（历史全保留） |

## §11 Exit Gate 自检

```text
[x] P0-01 bound confinement before ANY file probe/read（FsSpy 零越界证明）
[x] P0-02 idempotent returned identity == persisted identity（6 测试全场景）
[x] P0-03 source/content version required + exact coherent（required×4 + mismatch×2 + provenance×3 + bound×2）
[x] P0-04 documented AmazingData CA provider shape reaches typed validator（fixtures + v6 + 真实 v3）
[x] raw evidence remains provider-native / immutable（parquet 列名断言；adapter ephemeral）
[x] CA type remains fail-closed（EVENT_TYPE_UNRESOLVED / EVENT_TYPE_MISMATCH / PROVIDER_SCHEMA）
[x] rule run-bound exact replay remains intact（身份三重复验 + adversarial 保持）
[x] all new adversarial tests pass（580/0）
[x] local CI-equivalent checks green（四检查全绿）
[x] GitHub Actions result recorded accurately（run 38 已录；本批以 Actions 为准）
[x] DEVLOG updated / DEVELOPMENT_MANAGEMENT updated / ADR updated（ADR-015 + 索引）
[x] every important change note records why / how / alternatives / costs-benefits（ADR-015 §1-§5 + DM-CR 方案取舍段）
```

已知开放项（如实声明）：Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED。
