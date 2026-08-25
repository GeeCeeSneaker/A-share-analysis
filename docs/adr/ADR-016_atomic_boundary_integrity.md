# ADR-016: Atomic Exchange Boundary + Lexical-First Confinement + Review Input Integrity（R4-A2.8 / CR-1.2.4）

- 状态：ACCEPTED
- 日期：2026-08-25
- 依据：审计 R4-A2.7/CR-1.2.3 复审（裁决 REOPENED）→ R4-A2.8 / CR-1.2.4 开发工作要求（P0-01..03 + P1-01/02）
- 关系：**amendment to ADR-013 §4 / ADR-015**（不变量收紧：原子边界 / lexical-first / review preflight）
- 登记变更：DM-CR-20260825-013 / 014 / 015 / 016（管理总册 §61）

## 1. Golden Domain Atomic Exchange Boundary（P0-01，DM-CR-013）

**为什么**：CA 域曾以 assign-then-persist 取得 lineage（`x = target.X(); ...
collector.persist(x)`）——第二个 provider call 失败时，**第一个已真实发生的
success exchange 永久丢证据**（real calls=2 / persisted=1），违反
"real exchange fires → immediately enters immutable evidence boundary"。

**怎么改**：`_DomainCollector.call(fn) -> PersistedExchangeView`——
call + persist 是**一个边界操作**：exchange 在边界返回前已持久化；
返回的 frozen view 携带 `payload / request_id / endpoint /
evidence_meta`（lineage 从 view 读取，不再持有裸 exchange 引用）。全部
域 fetch（ST/DELISTED/LIMIT/CA/BJ）统一改走该边界。

**备选与取舍**：保留 assign-then-persist + 收紧注释（否——审计明确拒绝：
correctness contract 不能是"记得稍后持久化"）；把 lineage 塞进
PersistedExchange 以外的通道如 last_envelopes（否——diagnostic-only，
历轮审计已禁）。

**代价/收益**：fetch 代码全部经 lambda 间接（可读性略降）；换来
mid-sequence failure 永不孤儿化先序 success exchange（对抗测试证明），
AST 守卫从 name-presence 升级为**控制流安全**（exchange 调用必须位于
`collector.call(lambda: ...)` 内；负向测试证明旧模式被拒）。

## 2. Bound Rule Lexical-First Pre-Access（P0-02，DM-CR-014）

**为什么**：`_confined()` 先 `Path.resolve()` 再比较——非法 `../..` ref
在被 lexical 拒绝前已触发 filesystem resolution，违反 ADR-014 声明的
"confinement before ANY filesystem access"（overclaim 实锤）。

**怎么改**：`_lexically_confined_dataset_file`（Step A：非空/相对/无盘符/
无 `..`/versions/<v>/ 结构——**零 fs 访问**）→ `_confined_dataset_file`
唯一入口：Step A 通过后才 resolve（Step B：symlink escape 检测）。bound
loop 删除前置 `_confined` 双 helper 并列（顺序不透明）；evidence ref 的
`_confined` 同样加 lexical `..` 前置拒绝。

**测试**：`Path.resolve` spy——traversal/绝对/盘符/异版本目录的拒绝全程
candidate 未被 resolve；合法路径才触发 resolve；symlink escape 仍在 Step B
拦截。

## 3. Trading Rule Review Input Integrity（P0-03，DM-CR-015）

**为什么**：review.py 曾只 `load_rule_manifest()`（selector 可解析）即可
封 REVIEWED——被篡改/不一致的 COMPILED ACTIVE 可被"洗成"新的合法 REVIEWED
版本（human review ≠ re-seal an integrity-broken candidate）。

**怎么改**：preflight 不可绕过地执行 `load_active_rules(rules_root)`
（ACTIVE dataset hash 复算 + manifest↔dataset 四字段 coherence）；随后
校验 --from-version / 单文件支持 / --rules == 已验证 ACTIVE 文件 /
review_status == COMPILED；REVIEWED 副本从**已验证 ACTIVE bytes** 产生
（读取后再次复验 hash，无 TOCTOU）；preflight 失败 → **零输出**（无
evidence 拷贝、无 versions/<new>/、无 manifest 变更）。§4.4：
source_version/dataset_version REQUIRED 下沉到 `load_rule_manifest` 的
schema 校验（同一 manifest API 单一契约）。

**备选与取舍**：review 工具内联重实现 hash/coherence 检查（否——两套
逻辑必然漂移；复用 load_active_rules 即同一 gate）；允许 reviewer 人工
确认覆盖 hash gate（否——审计 §10 明令禁止）。

**代价/收益**：review 工具对 ACTIVE 状态强依赖（ACTIVE 异常时无法出
REVIEWED——预期行为）；换来看不见的篡改面归零 + manifest schema 单一化。

## 4. P1 Hardening（DM-CR-016 内）

- **P1-01 endpoint 身份交叉校验**：`CA_STREAM_ENDPOINTS` 固定映射
  （dividend ↔ InfoData.get_dividend；right_issue ↔
  InfoData.get_right_issue）；不匹配 → `CAProviderShapeError`（payload
  不可跨流重标）。
- **P1-02 空 frame schema 契约**：`_payload_columns(payload)` 提取列集
  （frame.columns / row keys）；`_ca_provider_view(payload_columns=)`：
  0 行 + 必需列齐 → 合法空事件流；0 行 + 缺列 → PROVIDER_SCHEMA。

## 5. 测试与验证

- **608 tests / 0 failed**（580 → 608，+28：CA 原子边界 7 + lexical-first
  9 + review 输入完整性 9 + endpoint/空 frame P1 内含 + 适配）；
  ruff check / format --check / mypy 全绿；
- dry-run 冒烟：35 meta-anchored exchanges + 5 bundles，整 run 双向闭合
  零问题（原子边界下 Spy 计数不变量保持）。
