# Formal B1-B7 失败归因后的框架整改记录（2026-09-11）

## 状态

`IMPLEMENTED / LOCAL VERIFIED / SEPARATE REVIEW REQUIRED / NO FORMAL RERUN`

本记录对应独立分支 `fix/provider-canonicalization-diagnostics-20260911`，基于
`main@fba18153a986cc1283a8c082e5d5629902d774cf`。它承接 PR #42 的独立审阅意见，
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

本分支新增 `src/ashare_state/spike/row_adapter.py`，统一处理 provider 原生行的
身份和日期，不改写 raw evidence：

- 支持 `SECURITY_CODE`、`code` 与数字/文本市场码组合；支持原生完整
  `MARKET_CODE`（例如带市场后缀的证券标识）；
- 只在明确的单字段 `{"value": "<完整证券标识>"}` 形状下读取标量代码列表；
  多字段行、市场冲突、未知市场码均返回空身份并由上层 fail closed；
- 将日期、时间戳、大小写字段统一转换为 `YYYYMMDD` 比较键，禁止使用未来日期哨兵；
- 保留 `0` 和空字符串的字段存在性，不因 `or` 回退误替换合法值。

接入点包括 Golden 状态/退市/涨跌停/北交所路由、ST/停牌与涨跌停 validator、
复权连续性 validator、B5 历史日期读取和 B5 日线单位观察。新增 13 条回归测试覆盖
原生身份、冲突拒绝、时间戳、大小写字段及各主要 validator/router 路径。

## 仍未解决的边界

这些代码修复不能证明 Provider 已经具备下列能力，也没有把旧 Formal 结果改写为通过：

1. B2 仍需要真实的退市语义字段（如 `IS_LISTED=3` 或可信退市日期）；历史代码列表
   中出现一个标识只能证明代码存在，不能单独证明已退市。
2. `symbol_mapping_unambiguous` 的缺失仍需确认真实代码列表 endpoint、权限和返回形状；
   本分支没有把空响应推断成 Provider 能力结论。
3. BSE 状态空响应仍是 `uncertain`，需由受控环境确认 endpoint/权限/历史可用性。
4. 历史 2020 覆盖和公司行为事件语义没有因日期/字段适配而自动成立；没有新增事件、
   期望值或 Golden case，也没有用复权因子替代公司行为事件来源。

因此，旧 run 的 `CLOSED` 与 `SPIKE_INCOMPLETE` 仍然是不可变的历史结果；本分支只
降低已证实的 framework/validator shape mismatch 风险。

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

结果：pytest 收集 1706 项，退出码 0，保留 2 个既有 skip；Ruff、format、mypy、依赖
检查和 diff 检查均通过。另有针对性 spike/router/CA/row-adapter 回归测试全部通过。

## 下一步工作要求

1. 由独立 Reviewer 审阅本分支 diff，重点确认适配器没有绕过字段语义、没有放宽
   `MISSING`/`FAIL` 到 `PASS` 的条件、没有改动 Golden/规则/Provider 配置。
2. 独立 Reviewer 接受后，合并本整改 PR；合并本身不等于 Provider capability approval。
3. 若项目仍需新的 Formal 结论，必须由调度者针对合并后的 clean main 重新给出一次性
   授权；PR #42 的旧授权不产生第三次 Formal run 权限。新 run（若获授权）须对比旧
   归因 artifact，单独保存 run-bound receipt，不能覆盖旧 run/verdict。
4. 在任何新 run 前，项目管理者需补齐 B2 退市语义、代码列表 mapping、BSE endpoint/权限
   和历史覆盖的外部确认；无法确认的项目继续保持 fail-closed。
