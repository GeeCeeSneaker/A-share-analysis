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
