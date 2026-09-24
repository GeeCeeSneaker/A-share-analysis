# Issue #82 — Formal B1–B7 post-#76 compatibility/preflight checkpoint

**状态：兼容性映射与离线核查 PASS；在线账户 T1 预检 BLOCKED（当前执行环境缺少密码）；未运行 Production。**  
**范围：** 仅处理 Issue #82 的兼容性/非 Production 预检，不授权 Formal Production、历史 provider 重抓或下游研究任务。

## 精确代码基线

- Base SHA：`1d4418a649dddc196277fc0087521d3a069b05f5`
- 经检查、运行离线 QA 的代码 head：`1d4418a649dddc196277fc0087521d3a069b05f5`（与 base 相同；本 checkpoint 没有改动代码）
- 提交内容仅为本 checkpoint 与执行计划文档。PR 的确切提交 SHA 由 PR head 记录；不改变上述被检查的代码 head。
- 当前 main 与 Issue #82 指定的起始基线一致；本地 worktree 在核查前干净。

## B1–B7 与 post-#76 架构对照

| 阶段 | 当前不变量 / 入口 | post-#76 兼容判断 | 本轮执行与边界 |
|---|---|---|---|
| B1 | 每个已注册 capability 必须先通过其 Formal runtime gate；入口 `probe_b1_formal_gates` → `FormalRuntimeGateExecutor` | 有效；校验 gate 证据，不要求复制 daily facts 到物理 Snapshot/ReadModel | DRY_RUN fixture 完成结构执行；不能替代真实 Provider 判断 |
| B2 | 按 run as-of 检查含退市证券的历史 Security Master；`probe_b2_security_master` 调用 `BaseData.get_hist_code_list(20200101, as_of)` | 有效；这是 Provider security-master 语义，不依赖旧 ReadModel | 本轮未发真实 Provider 请求 |
| B3 | 单日验证日线单位、ST/停牌状态、涨跌停规则；`probe_b3_core_facts` 使用显式证券列表/交易日历 exchange | 有效；直接验证 Provider 原始响应与 canonical adapter，不依赖旧物理事实副本 | DRY_RUN fixture 有执行；不代表实盘语义 PASS |
| B4 | Golden 按 run-bound version/hash 加载，并按 domain 路由比对；`probe_b4_golden` / `GoldenTruthStore.load_bound` | 有效；Golden 绑定独立于 Snapshot/ReadModel 存储形态 | DRY_RUN 使用 FakeTarget，合成样本不匹配产生的失败不作 Provider REJECT/语义结论 |
| B5 | SDK 权限/cache/freshness、2020 起历史覆盖及 BSE 限价证据；`probe_b5_units_pit_freshness` | 不依赖旧 ReadModel；但真实实现会向 Provider 查询 `20200101..as_of` 历史日线，并查 2022 BSE 状态 | 因本任务禁止历史 provider reacquisition，未在线执行该阶段 |
| B6 | 可选 free-float 等价性、行业分类归属、基准指数可用性；`probe_b6_replacement` | 有效的 Provider 语义观察，不依赖物理 Snapshot/ReadModel | 仅在 DRY_RUN fixture 中经过结构路径；未执行在线观察 |
| B7 | 全市场容量观测；`probe_b7_capacity` 用交易日历末尾最多 5 日记录行数/字节/吞吐/失败率 | 有效的有界容量探针，不依赖旧物理副本 | 本轮未在线执行；无密码时不能建立账户会话，且不以 dry-run 数字冒充 Provider 吞吐 |

静态核查在 `src/ashare_state/spike` 下未找到 `rm_daily_bar`、`ReadModel`、`SnapshotBuilder`、physical Snapshot/ReadModel 或 full-fact-copy 依赖匹配。**未发现因 #76 新架构而需要修改 B1–B7 的代码；本轮不做代码整改。** B5 的历史 Provider 请求和 B7 的五日全市场请求是执行范围边界，不是旧架构依赖。

## 冻结 Formal 输入（只读）

- 固定 as-of：`20260908`（Issue #82 明确冻结）。
- Trading Rule ACTIVE：`v20260910-h1r4-reviewed` / dataset `2026-09-10.2`；声明/重算 dataset SHA-256 `b8b77ef83f5741c12a2effef988f793c0827f737ea471494814c1b0b6d7f9aed` 一致；review gate（含 evidence bundle 要求）返回空问题列表。Evidence bundle SHA-256：`115971e9ecb35c34d364c708ca74f8db9fcb233d03d5d7e5f6c6bef02f02d0f4`。
- Golden ACTIVE：`v7-reviewed-20260908`，125 cases；125/125 为 REVIEWED；dataset SHA-256 `a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e`，加载器校验通过。
- 冻结输入未修改、未 reseal。

## 非 Production 预检

- 离线运行时：Python 3.14.6、AmazingData 1.1.9、TGW 1.0.9.2；`SDK_INSTALLED`、`RUNTIME_ACTUAL_LOAD_VERIFIED`。离线 doctor 退出码 0。
- `spike_runner.py --dry-run --date 20260908`：FakeTarget dry-run 关闭成功，180 cases；只证明 fixture/wiring 可执行。B4 等合成事实与 Golden 的差异不构成真实行情语义失败。
- scrubbed account bootstrap：`NOT_TESTABLE_ACCOUNT`；`AUTHENTICATED`、`NETWORK_REACHABLE`、`QUERY_READY` 均为 `NOT_TESTED`，`config_written=false`。脚本在缺少完整凭据时提前返回，未调用 SDK 登录、网络或查询。
- 当前进程环境只确认 TGW_USERNAME、TGW_SERVER_VIP、TGW_SERVER_PORT 存在；TGW_PASSWORD 缺失且 checkout 无 `.env`。凭据值未读取/记录到本 checkpoint。需要账户 T1 预检时，由授权人员在本机安全注入密码后，只重跑既有 scrubbed bootstrap；不得把密码发入聊天或提交仓库。

## QA、数据与 Production 边界

- 聚焦离线 pytest：`test_spike_framework.py`、`test_formal_gate_wiring.py`、`test_formal_runner_wiring.py`、`test_endpoint_requirement_proof.py`、`test_trading_rule_binding.py`、`test_trial_production_boundary.py`、`test_h1_rule_seal_lifecycle.py` 全部通过（退出码 0）。
- `git diff --check` 通过；本地 GitHub main 基线 commit 的 combined status 未返回 checks。PR 精确 head 的检查状态需在 PR 创建后记录；本轮没有代码变化。
- 未执行 `spike_runner.py --production`，未创建 Production `spike_run_id`；未发起 Provider 历史重取/重建；Golden/H1/trading-rule 冻结产物无改动。
- 不包含账号密码、真实 endpoint、token、profile 原始数据或 Provider 原始输出。

## 交接 / 下一步

1. 先由授权人员在本机安全提供 TGW_PASSWORD，再只运行受控的账户 identity/network/minimal-query T1 bootstrap；不得经聊天传密码。
2. 若 T1 通过，将结果补入 checkpoint 并交回 scheduler；scheduler 单独决定是否刷新/替换历史 Issue #39，以及是否授权唯一一次 Production Formal B1–B7。**本 checkpoint 不构成 Production 授权。**
