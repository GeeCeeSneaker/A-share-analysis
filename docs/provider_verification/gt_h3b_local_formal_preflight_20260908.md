# GT-H3B Formal Production 本地预检记录（2026-09-08）

## 结论

本次没有启动 Formal Production B1-B7，也没有创建正式 run ID。原因是本地没有满足文档第 3 节要求的当前主线干净工作树；这不是账号权限结论，也不是 SDK 未安装结论。

## 已确认事实

- GitHub `main` 当前提交：`d08530ef7f02472761d6db6eb61bea9be316765c`。
- 已发现的完整本地副本：`work/audit_h1_c939b747`。
- 该副本 HEAD：`d54f3c3624e51ec0051ac308ae9e2dd452169212`，分支为 `master`，工作区有 26 项修改/未跟踪变更；因此不满足正式运行的 clean-worktree 要求。
- 该副本缺少当前封印基线所需的关键文件：`golden_cases_v7.jsonl`、`truth_manifest_v7.json`、`evidence/`、`GT_H3B_EXECUTION_RECEIPT.json`、`GT_H3B_EXECUTION_REQUEST.md`、`scripts/golden/gt_h3b_execute.py`、`src/ashare_state/spike/evidence_bundle.py`、`src/ashare_state/spike/evidence_contract.py` 和 `tests/integration/test_gt_h3b_execution.py`。
- 工作区已保存用户提供的 SDK 文件：`vendor/amazingdata/tgw-1.0.9.2-py3-none-any.whl`、`vendor/amazingdata/AmazingData (1).zip`；zip 已解压到 `vendor/amazingdata/unpacked`，依赖 wheel 保存在 `vendor/amazingdata/dependencies`。
- 隔离环境离线 doctor：`SDK_INSTALLED` / `RUNTIME_ACTUAL_LOAD_VERIFIED`，识别到 AmazingData `1.1.9`、tgw `1.0.9.2`。
- 离线 production-account bootstrap：`OFFLINE_RUNTIME_VERIFIED`。
- 上述检查没有联网认证、没有查询 Provider 数据、没有读取或输出密码/Token/endpoint secret，也没有改写 Golden 真值。

## 阻塞原因

仓库授权的是从已封印 v7 基线进行一次受控 B1-B7 尝试。若在旧提交、脏工作树、缺 v7/evidence 的副本上启动，运行记录将无法证明源码、Golden、证据和结果属于同一可复现状态，也违反正式运行前置条件。因此当前不能把本地 SDK 通过误报成 Formal Production 已完成。

## 解除条件与下一步

在不覆盖现有本地修改的前提下，准备一份从当前 `main`（至少包含 `d5d98c2b1485a9a378f0c2dd9090b14f7b6168b1`，当前主线为 `d08530ef7f02472761d6db6eb61bea9be316765c`）得到的干净工作树，并保留完整 v7/evidence 文件。之后重新执行本次运行时事实检查，依据 Provider/项目交易日历解析最近一个已完整结束的交易日，再按 runbook 启动唯一一次：

```bash
uv run python scripts/spike/spike_runner.py --production --date <provider-derived-date>
```

Formal run 完成后才允许执行 verdict 并创建独立 evidence PR。不得把本记录、CI 结果或离线检查解释为 Provider GO / Data Sufficiency 批准。


## 2026-09-09 连接器复核补充

- 通过 GitHub 连接器已成功读取当前 `main` 的 v7 manifest、v7 dataset、Formal 脚本、evidence bundle/contract 以及历史 receipt 文本，说明远端文件可访问。
- 但当前连接器提供的是按路径读取/写入的 GitHub 文件接口，不会自动把包含二进制 evidence 的完整 Git tree 同步为本地 checkout；工作区也没有另一个完整、干净、绑定 `main@d08530ef7f02472761d6db6eb61bea9be316765c` 的副本。
- 因此“远端可读取”不能等同于“正式运行所需的本地源码、v7、evidence 和提交身份已完整落地”。在项目管理者准备好该本地 checkout 前，B1-B7 继续保持 `NOT_RUN`。
- 请项目管理者解决以下任一项：提供当前 `main` 的完整干净本地 checkout；或为运行环境配置受治理的 GitHub checkout/materialization 方式（含二进制 evidence），并保留可核验的 source SHA。不得通过修改 Golden、伪造本地 SHA 或绕过 clean-worktree gate 解决。

## 2026-09-09 直接 Git checkout 与 Formal Production 预检补充

> 本节记录本次实际运行时事实；前文关于旧提交和旧本地副本的内容保留为历史记录。正式执行以本次执行时已审阅进入 `main` 的源码为准。

### 操作台账与当前堵点（摘要）

| 阶段 | 实际操作 | 结果 | 当前状态 |
|---|---|---|---|
| 仓库基线 | GitHub 连接器复核当前 `main`，再建立完整 HTTPS Git checkout | `main@0148ae06cdd7b84709b235476eda7b170ad7e026`；非 shallow；444 commits / 531 tracked entries；工作区干净 | 已完成 |
| 依赖与运行时 | 在本地隔离环境同步依赖，安装用户提供的本地 SDK 包并运行 doctor / pip check | AmazingData `1.1.9`、tgw `1.0.9.2`；runtime 实际加载验证通过；依赖兼容性通过 | 已完成；依赖文件仅保存在本地 `vendor/`，未上传 |
| 在线预检 | 使用临时进程环境变量执行生产 bootstrap，并在线查询 Provider 日历 | 网络、认证、查询均通过；生产身份与已确认的脱敏标识一致；Provider 解析出 `20260908` | 已完成；凭证、真实 endpoint、raw 输出未落盘 |
| Formal 入口 | 只执行唯一允许的命令：`uv run python scripts/spike/spike_runner.py --production --date 20260908` | 在创建 `SpikeRun` 前因 ACTIVE trading rules 为 `COMPILED` fail-closed，退出码 1 | B1-B7 未执行；无 `run_id`、无 verdict |
| 质量门禁 | 执行 pytest、Ruff、mypy、`uv pip check` | 1618 passed / 2 skipped；Ruff、mypy、依赖检查均通过 | 已完成 |
| 当前堵点 | 人工复核 ACTIVE 交易制度规则集，并封存官方来源证据 | 当前 `v20260824-compiled` 有 9 条规则，`review_status=COMPILED`，缺少已封存 source artifact | 必须由项目管理者 / Reviewer 解除 |

因此，当前问题已经不是“拿不到完整 checkout”、不是账号权限、不是 SDK 安装，也不是 Provider 网络连通性；唯一实际阻断是交易制度规则数据尚未完成受治理的人工复核。GT-H3R v7 的 125/125 REVIEWED 属于另一审阅对象，不能替代这 9 条规则的审核。

### 完整 checkout

- 先由 GitHub 连接器复核 `main`，得到当前 HEAD：`0148ae06cdd7b84709b235476eda7b170ad7e026`。
- 在用户解除直接 Git 限制后，使用标准 HTTPS Git clone 建立了独立完整副本 `work/A-share-analysis-clean-20260909`；不是旧的 `work/audit_h1_c939b747`，保留完整 `.git`。
- `git rev-parse HEAD`、`git branch --show-current` 和连接器结果一致：`main@0148ae06cdd7b84709b235476eda7b170ad7e026`；`git ls-tree -r` 与 `git ls-files` 均为 531 个 tracked entries。
- Windows 默认换行配置使 5 个历史 CRLF blob 出现 EOL-only 伪变更；逐个核对后，5 个工作区文件的原始 blob SHA 均与 HEAD 一致。本地仅在 `.git/info/attributes` 对这 5 个精确路径关闭文本换行转换，未改 tracked 文件、未改提交、未上传该本地配置；随后 `git status --porcelain` 为空。该本地 checkout 差异已披露，不能把它解释成修改 Golden。
- v7 文件完整存在：`truth_manifest.json` / `truth_manifest_v7.json` 均为 `v7-reviewed-20260908`、125 条、`REVIEWED:125`；`golden_cases_v7.jsonl` 为 125 行，dataset hash 为 `a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e`。Formal runner、evidence store、5 个 composite bundles、receipt、Provider/Golden/capability 代码均已在 clone 中存在。

### 本次 runtime / online preflight

- 新 checkout 的离线依赖同步和 SDK 安装成功：AmazingData `1.1.9`、tgw `1.0.9.2`。
- 新 checkout 离线 doctor：`SDK_INSTALLED` / `RUNTIME_ACTUAL_LOAD_VERIFIED`；runtime reported version `V4.3.0.260626-rc2.0-YHZQ`。
- 本次在线 bootstrap（不落盘凭证、不输出 raw SDK 内容）返回：`NETWORK_REACHABLE=REACHABLE`、`AUTHENTICATED=YES`、`QUERY_READY=YES`、`production_identity_status=PRODUCTION`；脱敏 profile 为已确认的 `UNKNOWN_24e2ff401792`。脚本没有写入 `configs/production_account.yaml`。
- 通过 `AmazingData.BaseData.get_calendar()` 在线读取交易日历；查询时本地日期为 `20260909`，Provider 返回的最近交易日为 `20260908`。尾部还含 `20260909`，所以本次按“严格早于本地日期”的保守规则选取 `20260908`。

### Formal 入口结果

按当前主线唯一入口执行：

```text
uv run python scripts/spike/spike_runner.py --production --date 20260908
```

运行器在创建 `RunKind.PRODUCTION` / `SpikeRun` 前后完成 clean、身份和 Golden 绑定检查，但因交易制度规则集仍为 COMPILED 而拒绝继续：

```text
formal run refused: PRODUCTION run refused: trading rule dataset not reviewed
```

- 退出码：1。
- 正式 `run_id`：没有创建。
- B1-B7：未执行。
- `--verdict`：未执行。
- 本次属于执行前 fail-closed blocker，不应标记为 FAILED/ABORTED/CLOSED，也不应以 Provider NO-GO 解释；没有消耗一次合法的正式 run。

### 当前真实 blocker：交易制度规则集未完成人工复核

本次门禁实际加载的是：

| 字段 | 当前值 |
|---|---|
| ACTIVE rule version | `v20260824-compiled` |
| review_status | `COMPILED` |
| dataset file | `versions/v20260824-compiled/rules.yaml` |
| dataset hash | `dd2219d2383b01d2b8a5019ddf713d36a04f1badbeabe1aeffc7e20fa91ef2d8` |
| rule records | 9 |
| source artifact | 当前 `configs/trading_rules` 未提供已封存的官方 source artifact |

这与 GT-H3R v5/v7 的 12 条换源/语义修正人工裁决是不同审阅对象。GT-H3R v7 已是 `REVIEWED 125/125`，但不能替代这里的 9 条交易制度规则复核。

### 解除条件

项目管理者/人工 Reviewer 需要：

1. 对 `MAIN_BOARD_NORMAL`、`MAIN_BOARD_ST`、`MAIN_BOARD_IPO_DAY`、`CHINEXT_PRE_REGISTRATION`、`CHINEXT_REGISTRATION`、`CHINEXT_REGISTRATION_FIRST5`、`STAR_MARKET`、`STAR_MARKET_FIRST5`、`BSE_LIMIT` 逐条核对适用交易所、代码范围、起止日期、涨跌幅、首五交易日语义和 tick/舍入规则；
2. 提供可实际打开的官方 source artifact，并由审阅流程计算并封存 artifact hash、来源类型、检索时间和 reviewer provenance；
3. 使用 `scripts/rules/review.py` 生成新的不可变 REVIEWED 版本，保持原 COMPILED 版本不变，再通过受审阅的 manifest/CI 提交切换 ACTIVE；
4. 重新建立最新 main 的 clean checkout，并在规则集 REVIEWED 后才重新申请一次完整 B1-B7。不得手工把 `COMPILED` 改成 `REVIEWED`，不得用 GT-H3R 证据冒充规则集 source artifact。

本次记录没有写入账号密码、真实 endpoint、Token、raw profile、raw SDK 输出或本地 SDK 文件。
