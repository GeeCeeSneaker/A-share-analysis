# Formal B1-B7 失败归因后的框架整改记录（2026-09-11）

## 状态

`IMPLEMENTED / LOCAL VERIFIED / SEPARATE REVIEW REQUIRED / NO FORMAL RERUN`

本记录对应独立分支 `fix/provider-canonicalization-diagnostics-20260911`，基于
最新 `main@8dfb8a5cf1f03c5c974ea435bf04f13deac9fc65`。它承接 PR #42 的独立审阅意见，
只修复已能从既有失败归因和离线回归夹具直接证明的消费层问题。

旧 Formal run、sealed catalog、`SPIKE_INCOMPLETE` verdict、Golden 数据、交易规则、
Provider 配置和原始 Provider 文件均未修改。没有重新执行 Production、`--resume` 或
`--verdict`，也没有把正式账号、密码、真实 endpoint、Token、Cookie 或专有 SDK/runtime
写入仓库。

## 已确认的问题与修复

PR #42 的只读归因 artifact 将 B4 的 125 条失败分为：

- 103 条状态/Golden canonical key mismatch；
- 20 条历史代码列表的标量 `value` 行形状 mismatch；
- 2 条 BSE 状态空响应，仍保留为 `uncertain`。

### 1. 单一 canonical status view

`src/ashare_state/spike/row_adapter.py` 新增 `canonical_status_view()`，在内存克隆中
统一把原生状态行转换为语义消费者需要的字段：

- `MARKET_CODE=600000.SH`、`000001.SZ`、`835185.BJ` 等完整标识被拆成裸
  `SECURITY_CODE`、数字市场码和 `EXCHANGE_CODE`，并保留 `PROVIDER_SYMBOL`；
- `TRADE_DATE` 和已知状态字段统一为 canonical 名称；大小写/`pre_close` 这类
  provider 拼写差异只在该视图处理；
- 状态路由的 ST、涨跌停、公司行为和北交所路径，以及 B3/B5 状态消费，均在进入
  semantic validator 前经过这一个视图；validator 不再各自维护 native alias；
- 歧义、冲突、未知市场或缺失日期会抛出明确的 `ProviderRowShapeError`。上层保留已
  成功写入的 raw exchange，并生成结构化 `PROVIDER_STATUS_SHAPE` fail-closed 结果；
  不猜测证券身份。成功但 0 行的状态响应仍保持 0 行，不被改成 PASS。

该视图只复制行，不修改 raw evidence，因此不会改变既有证据字节或旧 catalog。

### 2. scalar 历史代码列表边界

- 只有明确的单字段 `{"value": "<完整证券标识>"}` 才能作为代码成员身份；多字段行、
  冲突身份和未知市场不被猜测。
- Golden 退市连续性可以使用 `value` 证明“代码出现在历史列表”；这不等于证明退市。
- B2 `security_master_with_delisted` 遇到 value-only 数据时返回
  `MISSING / DELISTED_SEMANTIC_FIELD_MISSING`，不会合成 `IS_LISTED=3`、
  `DELISTING_DATE` 或其他 Provider 未返回的语义字段。

### 3. 日线字段契约

新增 `canonical_daily_bar_view()`，以大小写不敏感且有明确拼写优先级的契约提供
`CLOSE_PRICE`、`VOLUME`、`AMOUNT`、`TRADE_DATE`。B3 的 `_observe_units()` 和现有
独立数量级校验都消费该视图；`checked_n == 0` 仍然失败闭合，不会因为字段漂移而 PASS。

### 4. 历史起点与交易日历

- `first_applicable_trading_day()` 从 run-bound trading calendar 选择 baseline（默认
  `20200101`）之后的第一个交易日，因此不要求在元旦这个非交易日有记录。
- `validate_history_coverage_by_symbol()` 对固定夹具逐标的校验，避免一个长历史标的
  掩盖另一个标的缺口。
- B5 对 `835185.BJ` 显式使用 `20211115` 的夹具适用起点；这是测试夹具的
  listing/market-applicability 元数据，不是从 Provider 推断的退市语义。其余固定标的
  仍受项目 `20200101` baseline 约束。
- 日线 `kline_time` 先进入 canonical bar view 再参与日期计算；不再把无法读取的日期
  填成 `99991231`。

## 整改矩阵

| PR #42 归因类别 | 代码整改 | 回归验证 | 仍待 Provider/独立审阅确认 |
|---|---|---|---|
| 103 条 status canonical-key mismatch | `canonical_status_view()`；Golden router、B3/B5 入口统一接入；status validator 只消费 canonical 字段 | SH/SZ/BJ 完整标识、大小写字段、冲突身份拒绝；既有 router/CA 集成测试 | 两条 `835185.BJ` 空状态响应仍是 unresolved；BJ 专用 mapping endpoint/权限未证明 |
| 20 条 scalar history-code shape mismatch | value-only 仅进入 membership/continuity；B2 不合成退市字段 | scalar 成员 Golden 连续性；B2 semantic-field 缺失测试；多字段 scalar fail closed | 真实代码列表 endpoint、权限和可证明的 `IS_LISTED`/退市日期字段 |
| lower-case daily-bar fields | `canonical_daily_bar_view()` 接入 `_observe_units()` 与日线数量级校验 | lower-case `close/volume/amount` 与 uppercase `CLOSE_PRICE/VOLUME/AMOUNT` 双路径 | Provider 单位语义仍需真实数据独立确认，不能仅凭字段可读性批准 |
| `kline_time` 被读成 sentinel | canonical bar date extraction；按 persisted calendar 选首个适用 session；按固定标的分别核验 | lower-case timestamp；2020-01-01 holiday；BSE applicability boundary | 真实 Formal 数据的逐标的 2020+ 覆盖仍未重跑/批准 |
| status 阻断后的公司行为误读风险 | 公司行为 status gate 只接受 canonical view；raw-only event presence 不改变语义门 | 既有 CA SOR、event type、缺 bar/停牌和 provider schema 测试 | dividend 2/20、right_issue 5/5 的 raw-only 观察仍是 diagnostic，不是 PASS |

## 未解决的边界

这些代码修复不能证明 Provider 已经具备下列能力，也没有把旧 Formal 结果改写为通过：

1. B2 真实退市语义字段、代码列表 mapping endpoint/权限仍待外部确认。
2. BSE 状态空响应仍是 `uncertain`；成功空响应被保留为 `MISSING / PROVIDER_EMPTY_STATUS_UNRESOLVED`，
   不是 PASS，也不在 endpoint/schema 语义确认前标成 Provider-only FAIL。
3. BJ 历史 mapping 仍未获得独立 endpoint/golden 证明。
4. 历史 2020 覆盖和公司行为事件语义没有因字段适配自动成立；没有新增事件、期望值或
   Golden case，也没有用复权因子替代公司行为事件来源。

因此，旧 run `dad1e1b8-0c34-4031-8e94-cc87a03dbbf4` 的 `CLOSED` 与
`SPIKE_INCOMPLETE` 仍是不可变历史结果；本分支只降低已证实的 framework/validator
shape mismatch 风险。

## 本地验证

在本分支执行：

```text
uv run pytest -q
uv run ruff check src tests scripts/spike
uv run ruff format --check src tests scripts/spike
uv run mypy src
uv pip check
git diff --check
```

已完成的验证包括：

- 定向 row-adapter、validator、Golden router、B5、CA 集成测试通过；
- 全量 pytest：`1717 collected, 1714 passed, 3 skipped`，退出码为 0；
- Ruff check/format、mypy、依赖检查和 diff 检查通过。

上述结果只证明本地代码/测试回归通过；3 个 skip 是仓库既有的环境条件分支，不构成
Provider capability 或 Formal 结论。远端仍以当前提交的三平台 CI 和独立 Reviewer 审阅为准。

## 下一步工作要求

1. 由独立 Reviewer 审阅本分支 diff，重点确认适配器没有绕过字段语义，没有放宽
   `MISSING`/`FAIL` 到 `PASS`，没有改动 Golden/规则/Provider 配置。
2. 独立 Reviewer 接受后，合并本整改 PR；合并本身不等于 Provider capability approval。
3. 若项目仍需新的 Formal 结论，必须由调度者针对合并后的 clean main 重新给出一次性
   授权；PR #42 的旧授权不产生第三次 Formal run 权限。新 run（若获授权）须对比旧
   归因 artifact，单独保存 run-bound receipt，不能覆盖旧 run/verdict。
4. 在任何新 run 前，项目管理者需补齐 B2 退市语义、代码列表 mapping、BSE endpoint/权限
   和历史覆盖的外部确认；无法确认的项目继续保持 fail-closed。
