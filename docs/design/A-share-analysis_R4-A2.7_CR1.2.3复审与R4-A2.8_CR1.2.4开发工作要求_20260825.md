# A-share-analysis：R4-A2.7 / CR-1.2.3 复审结论与 R4-A2.8 / CR-1.2.4 开发工作要求

> **Review Date**：2026-08-25 14:27 +08:00  
> **Reviewed Repository HEAD**：`47b47437b0828262e4f9f11c57862af2558a4d34`  
> **Previous Reviewer Requirement Commit**：`8e329a467adb49725c61cdcf7bac3e2edc5b13f2`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2.7 Final Integrity / Provider-Shape Closure、CR-1.2.3 Evidence Identity Closure、ADR-015、Golden Domain Exchange Boundary、Trading Rule Review Lineage、治理与 CI  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.8 Final Exchange-Boundary / Review-Lineage Closure + CR-1.2.4 Pre-Access Integrity**  
> **CR-2**：**BLOCKED**  
> **R4-A3**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. 裁决摘要

本轮实现继续明显收敛。上一轮四个主修复项中，下列主体实现已成立并允许冻结：

```text
RawWriter idempotent evidence identity
→ 返回 hash 已改为磁盘真实 meta bytes 的 SHA-256
→ 首次 meta 不被幂等重试覆盖
→ success / failure / orphan-recovery 身份测试已补

Trading Rule active coherence
→ source_version / dataset_version 已在 active load 中变为必填语义
→ run provenance 已包含 selector/content/source/review 身份
→ resume/verdict/ProbeContext.rule_book 复验完整 bound identity

Corporate Action provider-shape adapter
→ Raw 保留 provider-native 字段
→ semantic view 仅在内存中生成
→ event type 来自 endpoint/domain identity
→ FakeTarget 改为官方文档字段 shape

CI
→ Actions run 40 / HEAD 47b47437... = completed / success
```

因此本轮**不回退** Raw meta-anchor、full request lineage、run-bound Rule SoR、CA provider-native Raw、typed CA Golden truth 等已经通过的主体设计。

但 Reviewer 在 runtime/control-flow 与人工 review workflow 复核中确认了三个新的 blocking correctness 问题：

```text
P0-01  CA domain 重新出现“真实 Exchange 已创建但尚未持久化”的窗口
P0-02  Bound Rule 的严格 lexical-first pre-access contract 尚未真正实现
P0-03  Trading Rule 人工 review 工具没有先验证 ACTIVE dataset 的 hash/coherence，就可封成 REVIEWED
```

其中 P0-01 会直接丢失真实 Provider evidence；P0-03 会允许把被篡改/不一致的 COMPILED 输入“洗成”新的 REVIEWED version；P0-02 则仍与已声明的 fail-closed confinement contract 不一致。

因此本轮不能 VERIFIED。

---

# 1. 本轮已通过并冻结的实现

## 1.1 RawWriter persisted identity —— PASS

`RawWriter._write_success()` 当前最终以：

```python
persisted_meta_bytes = meta_path.read_bytes()
meta_hash = sha256(persisted_meta_bytes)
```

定义 evidence identity。

这正确解决了此前完整幂等重试时：

```text
new in-memory meta ingested_at
!= first persisted meta ingested_at
```

导致返回 hash 与真实磁盘 hash 不一致的问题。

本项后续禁止回退为“hash intended bytes”而非“hash persisted bytes”。

## 1.2 Trading Rule active required coherence —— 主体 PASS

当前 active load 已要求：

```text
manifest.dataset_version non-empty
manifest.source_version non-empty
manifest.review_status == dataset.review_status
manifest.dataset_version == dataset.version
manifest.source_version == dataset.source_version
manifest.review_provenance ~= dataset.review_provenance
```

并且 Production provenance / bound replay 已携带：

```text
selector version
content version
source version
review status
file list
combined hash
```

这一模型保留。

## 1.3 CA provider-shape semantic adapter —— 架构 PASS

保留：

```text
Raw ProviderExchange payload
  provider-native fields
        ↓
ephemeral _ca_provider_view
        ↓
semantic validator view
```

当前文档字段契约：

```text
get_dividend:
  MARKET_CODE / DATE_EX

get_right_issue:
  MARKET_CODE / EX_DIVIDEND_DATE
```

事件类型：

```text
DIVIDEND / RIGHT_ISSUE
```

由 endpoint/domain identity 派生，不假称 provider Raw 自带 EVENT_TYPE。

## 1.4 CI —— VERIFIED GREEN

Reviewer 已正向确认：

```text
Actions run 40
HEAD = 47b47437b0828262e4f9f11c57862af2558a4d34
status = completed
conclusion = success
```

本轮 CI 不是阻塞项。

---

# 2. P0-01：CA Domain 重新引入 Exchange 创建后延迟持久化窗口

## 2.1 当前代码

`CORP_ACTION_CONTEXT` 当前执行顺序为：

```python
dividend_exchange = ctx.target.get_dividend_exchange(symbols)
right_issue_exchange = ctx.target.get_right_issue_exchange(symbols)
dividend = collector.persist(dividend_exchange)
right_issue = collector.persist(right_issue_exchange)
```

这样做的目的，是让后续 semantic adapter 能读取：

```text
exchange.envelope.endpoint
exchange.request_id
```

作为 lineage。

但这个写法重新破坏了 CR-1 的核心不变量：

```text
real provider exchange fires
→ immediately enter immutable evidence boundary
```

## 2.2 直接失败场景

### 场景 A：Dividend 成功，Right Issue 失败

```text
get_dividend_exchange()
→ 成功，dividend_exchange 已真实发生
→ 尚未 persist

get_right_issue_exchange()
→ ProviderError

route_all catches failure
→ persist_failure(right_issue)
→ dividend success exchange 永久丢证据
```

所以：

```text
real provider calls = 2
persisted exchange evidence = 1
```

### 场景 B：两个 Provider call 都成功，但第一条 persist 失败

当前先把两个 Provider call 都发出，然后才 persist。

因此若：

```text
collector.persist(dividend_exchange)
```

在 RawWriter 层失败，第二条 `right_issue_exchange` 已经真实发生，但同样未进入 evidence boundary。

这说明 correctness contract 不能是：

```text
assign now, remember to persist later
```

而必须是：

```text
call + persist as one boundary operation
```

## 2.3 为什么当前 AST Guard 没挡住

当前 Golden Router 的静态守卫允许：

```text
x = target.*_exchange(...)
...
collector.persist(x)
```

只要变量名在整个 AST 里“某处出现过 persist”，就算 approved。

这不是控制流正确性证明。

下面两段都会被现有 guard 视为合法：

```python
x = call1()
persist(x)
```

以及错误的：

```python
x = call1()
y = call2_that_can_fail()
persist(x)
persist(y)
```

所以 static guard 已退化为 name-presence guard，必须收紧。

## 2.4 强制修复

推荐在 `_DomainCollector` 增加统一边界，例如：

```python
@dataclass(frozen=True)
class PersistedExchangeView:
    payload: Any
    request_id: str
    endpoint: str
    evidence_meta: dict[str, Any]


def call(self, fn) -> PersistedExchangeView:
    exchange = fn()
    meta = self.ctx.evidence_from_exchange(exchange)
    self._record(meta)
    return PersistedExchangeView(
        payload=exchange.payload,
        request_id=exchange.request_id,
        endpoint=exchange.envelope.endpoint,
        evidence_meta=meta,
    )
```

于是 CA 路径改成：

```python
dividend = collector.call(
    lambda: ctx.target.get_dividend_exchange(symbols)
)
right_issue = collector.call(
    lambda: ctx.target.get_right_issue_exchange(symbols)
)
```

然后 semantic adapter 使用：

```text
dividend.payload
dividend.endpoint
dividend.request_id
```

这样能够同时满足：

```text
lineage 可读
AND
每次 provider call 成功后立即持久化
```

不接受继续保留“assign then persist later”的 correctness contract。

## 2.5 Required Tests

```text
[ ] dividend success + right_issue permission failure
    -> dividend success meta exactly 1
    -> right_issue failure meta exactly 1
    -> bundle contains both exchanges
    -> provider call count == persisted exchange evidence count

[ ] dividend success + dividend RawWriter persistence failure
    -> right_issue provider call MUST NOT fire

[ ] dividend failure
    -> no right_issue call
    -> failure evidence persisted once

[ ] CA full success
    -> both event exchanges each persisted exactly once
    -> semantic view lineage request_id points to exact persisted exchange

[ ] static guard forbids direct `target.*_exchange` assignment in Golden router
    unless it is syntactically contained in an approved atomic call+persist boundary
```

---

# 3. P0-02：Bound Rule 仍未完全满足 lexical-first pre-access contract

## 3.1 当前实现

`load_bound_rule_book()` 已正确移除了：

```python
(root / dataset_files[0]).is_file()
```

候选 root 探测。

这是实质进步。

但当前每个 rel 仍先调用：

```python
_confined(root, rel)
_confined_dataset_file(root, rel, rule_version=rule_version)
```

而 `_confined()` 内部会先执行：

```python
candidate = (root / normalized).resolve()
```

然后才做 containment 判断。

真正的 lexical `..` rejection 则在 `_confined_dataset_file()` 里稍后发生。

因此：

```text
../../outside.yaml
```

仍会先进入 filesystem-aware `Path.resolve()`，再被 lexical `..` rule 拒绝。

上一轮合同要求的是：

```text
lexical validation
→ then resolved-path/symlink validation
→ then is_file/read/hash
```

当前仍差最后一步。

## 3.2 当前 FsSpy 测试覆盖不足

现有 FsSpy 只 patch：

```text
Path.is_file
Path.read_bytes
Path.open
```

没有观察：

```text
Path.resolve
readlink/stat 等 resolve 可能触发的 filesystem resolution
```

因此测试所证明的是：

```text
没有越界 is_file/read/open
```

而不是严格意义上的：

```text
非法 lexical ref 在任何 filesystem resolution 前被拒绝
```

## 3.3 强制修复

将 bound dataset path validation 拆成清晰两步：

### Step A — lexical-only

不得调用 resolve / stat / open：

```text
non-empty
relative path only
no drive prefix
no ..
path prefix == versions/<rule_version>/
```

### Step B — resolved confinement

只有 Step A 全部通过后：

```text
(root / normalized).resolve()
root.resolve()
relative_to(root_resolved)
```

用于检测 symlink escape。

推荐让 `_confined_dataset_file()` 成为唯一入口，并删除 bound loop 中前置 `_confined(root, rel)`。

不要并列使用两个 helper 产生顺序不透明。

## 3.4 Required Tests

```text
[ ] ../../outside.yaml -> lexical reject BEFORE candidate Path.resolve
[ ] absolute path -> reject BEFORE candidate Path.resolve
[ ] drive-letter path -> reject BEFORE candidate Path.resolve
[ ] versions/<other>/x -> structural reject BEFORE candidate Path.resolve
[ ] valid lexical path -> resolve executes
[ ] valid lexical path + symlink escape -> resolved confinement blocks
[ ] valid normal bound path -> PASS
```

可 monkeypatch/helper-spy `Path.resolve`，区分：

```text
root.resolve() allowed only after lexical validation
candidate.resolve() must not happen for lexical-invalid refs
```

---

# 4. P0-03：Trading Rule Review Tool 可把异常 ACTIVE 输入封成 REVIEWED

## 4.1 当前 review.py preflight

当前流程：

```text
rules_path.is_file()
artifact.is_file()
load_rule_manifest(rules_root)
check --from-version / active path
TradingRuleBook.load(rules_path)
→ build REVIEWED copy
```

问题是：

```text
load_rule_manifest()
```

只证明 selector 可解析、路径存在。

它不会完成：

```text
ACTIVE dataset combined hash re-verification
manifest↔dataset source_version/dataset_version/review_status/provenance coherence
```

这些完整校验属于：

```python
load_active_rules()
```

## 4.2 可利用场景

例如：

```text
rule_manifest.json
  dataset_hash = H(original)

versions/v1-compiled/rules.yaml
  bytes 被人工修改 / 污染
```

此时正常 runtime：

```text
load_active_rules()
→ hash mismatch
→ BLOCK
```

但当前 review.py：

```text
load_rule_manifest()
→ PASS（文件仍存在）
TradingRuleBook.load(tampered rules.yaml)
→ 可以加载
review tool
→ 写出新的 REVIEWED copy
→ 重新计算新 hash
→ ACTIVE 切到新 REVIEWED version
```

这等于把原本会被 ACTIVE integrity gate 拒绝的输入，重新封装成了一个新的“合法 REVIEWED”版本。

这违反：

```text
human review can approve a verified candidate
!= human review can re-seal an integrity-broken candidate
```

## 4.3 强制修复

review 工具开始时必须先调用：

```python
active_book, active_manifest = load_active_rules(rules_root)
```

并把这一步作为不可绕过 preflight。

随后再确认：

```text
active_manifest.rule_version == expected --from-version
len(active_manifest.dataset_files) supported by tool
--rules path == exact verified ACTIVE file
active_book.review_status == COMPILED
```

reviewed copy 应从**已验证 ACTIVE bytes**产生，而不是从另一个未经 hash/coherence gate 的信任路径重新读取。

如果 preflight 失败：

```text
no evidence artifact copy
no versions/<new> directory
no manifest temp/final flip
no partial reviewed output
```

## 4.4 Manifest schema consistency

既然当前系统已声明：

```text
source_version required
dataset_version required
```

建议同时把该要求下沉到：

```python
load_rule_manifest()
```

的 schema validation，而不是只在 `load_active_rules()` 的 coherence 阶段拦。

原因：

```text
load_rule_manifest()
```

已经被 review tool / selector 工具直接使用。

“同一个 manifest API，有时允许缺失 required 字段、有时不允许”会继续制造两套契约。

## 4.5 Required Tests

```text
[ ] ACTIVE rules bytes modified but manifest hash unchanged
    -> review.py refuses
    -> no reviewed version dir created
    -> no evidence artifact copied
    -> ACTIVE manifest unchanged

[ ] ACTIVE manifest source_version missing/empty -> review refuses
[ ] ACTIVE manifest dataset_version missing/empty -> review refuses
[ ] manifest↔dataset source_version mismatch -> review refuses
[ ] manifest↔dataset review_status mismatch -> review refuses
[ ] manifest↔dataset provenance mismatch -> review refuses
[ ] healthy verified COMPILED ACTIVE -> review succeeds normally
```

---

# 5. P1 Hardening

## 5.1 CA endpoint identity 应与实际 envelope.endpoint 交叉校验

当前 `_ca_provider_view(stream, ..., source_endpoint=...)` 的 event type 来自传入的：

```text
stream = dividend / right_issue
```

而不是直接从 `source_endpoint` 判断。

当前 caller 传值正确，所以不是本轮 false PASS。

但既然设计声明：

```text
event_type = endpoint identity
```

建议增加固定映射：

```text
dividend    <-> InfoData.get_dividend
right_issue <-> InfoData.get_right_issue
```

不匹配：

```text
CAProviderShapeError / PROVIDER_SCHEMA
```

这样不会出现 caller 把 right-issue payload 错标成 dividend stream 的可能性。

## 5.2 Empty DataFrame 的 schema contract 应可验证

当前 `_ca_provider_view()` 消费 `_rows(payload)`。

若 Provider 返回：

```text
0-row DataFrame
```

则 `_rows()` 得到空列表，adapter 无法判断 dataframe schema 是否缺：

```text
MARKET_CODE / DATE_EX / EX_DIVIDEND_DATE
```

最后可能被解释成 `EVENT_SOURCE_MISSING`，而不是 `PROVIDER_SCHEMA`。

建议 adapter 能访问：

```text
payload columns/schema
```

或从 Exchange/Raw metadata 获取 schema，做到：

```text
zero rows + correct required columns -> legitimate empty event result
zero rows + missing required columns -> PROVIDER_SCHEMA
```

P1，不阻塞本轮主体，但最好在 R4-A2.8 一并清掉。

---

# 6. Governance Closure

本批修复后必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

必须如实记录：

```text
Reviewed Code Baseline = 47b47437b0828262e4f9f11c57862af2558a4d34
R4-A2.7 / CR-1.2.3 Review = REOPENED
Next = R4-A2.8 / CR-1.2.4
CI = run 40 SUCCESS
RISK-004 remains REOPENED
CR-2 BLOCKED
R4-A3 BLOCKED
P0-M-1B BLOCKED
```

并追加 Reviewer Correction：

```text
R4-A2.7 的 Raw identity / active coherence / provider-shape architecture 保留；
但 CA assign-then-persist control-flow、bound lexical-first 顺序、review input integrity 尚未关闭。
```

不得重写历史 DEVLOG；在顶部追加 correction / review entry。

建议 Change IDs：

```text
DM-CR-20260825-013  Golden Domain Atomic Exchange Persistence
DM-CR-20260825-014  Bound Rule Lexical-First Pre-Access Confinement
DM-CR-20260825-015  Trading Rule Review Input Integrity Gate
DM-CR-20260825-016  R4-A2.7 Reviewer Governance Correction
```

---

# 7. 推荐实施顺序

```text
Batch A — Golden Atomic Exchange Boundary
  collector.call / equivalent
  remove assign-then-persist window
  failure ordering adversarial tests
  tighten AST guard

Batch B — Rule Pre-Access Integrity
  lexical-only validator first
  resolved/symlink check second
  resolve spy tests

Batch C — Review-Lineage Integrity
  load_active_rules preflight
  reject tampered/incoherent ACTIVE
  zero-output-on-preflight-failure tests

Batch D — P1 + Governance
  endpoint identity cross-check
  empty-frame schema validation
  DEVLOG / DEVELOPMENT_MANAGEMENT correction
  CI confirmation
```

不要在该批并行启动 CR-2 或 R4-A3。

---

# 8. 最低验收矩阵

## 8.1 Golden atomic exchange persistence

```text
[ ] every successful formal domain provider call is persisted BEFORE next provider call
[ ] dividend success + right_issue failure -> both success/failure exchanges in bundle
[ ] first persist failure -> no later provider call fires
[ ] call count == persisted raw meta count under injected mid-sequence failure
[ ] AST guard forbids assign-now-persist-later formal exchange pattern
```

## 8.2 Bound lexical-first confinement

```text
[ ] traversal reject before candidate resolve
[ ] absolute reject before candidate resolve
[ ] drive path reject before candidate resolve
[ ] foreign version dir reject before candidate resolve
[ ] valid path reaches resolved confinement
[ ] symlink escape blocked at resolved confinement
[ ] normal bound replay still passes
```

## 8.3 Rule review input integrity

```text
[ ] review tool preflight uses fully verified ACTIVE
[ ] active bytes hash mismatch -> refuse, zero output mutation
[ ] required metadata missing -> refuse
[ ] metadata coherence mismatch -> refuse
[ ] non-ACTIVE input -> refuse
[ ] healthy COMPILED ACTIVE -> REVIEWED flow succeeds
```

## 8.4 Whole system

```text
[ ] ruff check
[ ] ruff format --check
[ ] mypy
[ ] pytest
[ ] Actions GREEN
[ ] dry-run evidence closure == []
[ ] no last_envelopes correctness consumer
[ ] no payload-only formal provider calls
[ ] no direct unbounded target.*_exchange formal call site
```

---

# 9. Exit Gate

R4-A2.8 / CR-1.2.4 只有满足以下条件才允许进入 Reviewer VERIFIED：

```text
[ ] CA domain call+persist is atomic per real exchange
[ ] mid-sequence provider failure cannot orphan a prior success exchange
[ ] mid-sequence persistence failure prevents later provider calls
[ ] Golden static boundary guard is control-flow safe, not name-presence based
[ ] bound invalid lexical refs reject before candidate resolve/filesystem access
[ ] symlink escape still blocked after lexical pass
[ ] review.py seals only a load_active_rules-verified candidate
[ ] tampered/incoherent ACTIVE cannot be converted into REVIEWED
[ ] failed review preflight leaves zero new review artifacts/version/manifest mutation
[ ] RawWriter persisted identity fix remains green
[ ] active/bound rule identity fix remains green
[ ] provider-native CA raw + ephemeral semantic view remains intact
[ ] CI green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT synchronized
[ ] every important change note answers why/how/alternatives/tradeoffs
```

---

# 10. 禁止项

本批禁止：

```text
启动 CR-2 Provider-Normalized + Quarantine
启动 R4-A3 expansion
扩展 Feature / State
修改 Frozen Baseline V1.3.2
把 Fake/CI 结果冒充正式 Provider Truth
把 Raw CA payload 改写成 canonical 字段
通过 last_envelopes 补救丢失 exchange
通过“reviewer 人工确认”绕过 ACTIVE dataset hash/coherence gate
```

---

# 11. 变更 Notes 强制四问

每个重要改动必须回答：

```text
1. 为什么要改？
2. 怎么改？
3. 考虑过哪些方案，为什么没选？
4. 代价与收益是什么？
```

本批至少分别记录：

```text
Golden atomic call+persist boundary
lexical-first vs resolve-first confinement
review verified-candidate preflight vs direct path review
endpoint identity/schema hardening（如实施）
```

---

# 12. Reviewer 下轮复检重点

只复查以下核心：

```text
1. CA success exchange 是否在下一次 provider call 前已经 Raw 落盘
2. injected second-call failure 时 bundle 是否仍包含第一条成功 exchange
3. ../../ ref 是否在 candidate resolve 前被拒绝
4. review.py 是否先 load_active_rules 验证 candidate hash/coherence
5. tampered ACTIVE 是否绝不产生 reviewed version/evidence/manifest flip
6. current CI / exact HEAD / management status 是否真实一致
```

如果这些全部关闭，且没有新的 formal correctness regression，R4-A2.x / CR-1.x 才具备进入 VERIFIED、再启动 CR-2 / R4-A3 的条件。
