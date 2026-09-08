# GT-H3B 合并后治理更正与正式运行预检记录

日期：2026-09-08（Asia/Shanghai）

## 1. 已确认的远端基线

- 当前 main：22b5423109f0448ee954cac40b6c4c186c298a27
- GT-H3B merge commit：d5d98c2b1485a9a378f0c2dd9090b14f7b6168b1
- reviewed Golden：v7-reviewed-20260908 / 125 条 / REVIEWED 125/125
- 本记录不改写 v7 数据集、103 个 evidence ref、历史 receipt 或 v1-v6 immutable 文件。

## 2. Receipt 来源字段更正

审阅者指出，历史 GT_H3B_EXECUTION_RECEIPT.json 的 source_main_sha 实际来自 GitHub Actions GITHUB_SHA；在 PR 工作流中它表示 merge-ref，而不是 main parent。该字段按审阅意见保留，历史 receipt 原字节不重写。

后续受控执行将使用 receipt v2 的明确字段：

| 字段 | 含义 |
|---|---|
| source_base_sha | PR base 的 main parent SHA |
| source_merge_ref_sha | GitHub Actions GITHUB_SHA / PR merge-ref SHA |
| source_head_sha | PR head SHA |

工作流同时注入 GITHUB_BASE_SHA；未取得某个角色时保留 null，不猜测或回填。

## 3. 幂等 verifier 加固

gt_h3b_execute.py::_verify_existing_seal() 现在复用首次 seal 的强校验路径：

- 重新加载并校验当前 v7 ACTIVE、125 个 case、REVIEWED provenance、dataset hash；
- 绑定并校验 immutable v6 dataset 与冻结 source contract，而不是把 v6 contract 错当成 v7 header；
- 逐一重新计算所有 evidence ref 的 SHA-256；
- 重新校验 5 个 composite evidence bundle 的成员、顺序、来源和内部 hash；
- 重新运行 review / quantity / event-coverage / production-formal 四类 Golden gates；
- 将强校验结果逐字段与历史 receipt 的 phase C 摘要比对。

已有 v1 receipt 仍只读验证；未来新执行写入 v2 字段。该 hardening 不重新打开 GT-H3B，也不修改历史 seal。

## 4. 本次 Formal Production 预检状态

本次检查发现受控工作区没有可执行的 main checkout：标准入口 scripts/spike/spike_runner.py 在工作区不可用，且系统 Python 尚未导入 AmazingData SDK。虽然本地依赖介质已存在，但在没有经过源码 SHA 绑定的干净 main 工作树前，不能启动正式 runner。

因此：

- 未读取或注入任何账号密码、Token、Cookie 或真实 endpoint；
- 未发起正式 Provider 登录或查询；
- 未创建 RunKind.PRODUCTION / SpikeRun，没有 run_id；
- 未执行 B1-B7，也未执行 verdict；
- 本次一次性授权仍为 AUTHORIZED / NOT EXECUTED，不记为 FAILED、CLOSED 或已消耗的正式 run。

## 5. 下一步

由具备干净 main 检出和受控 SDK 注入能力的 Windows operator，按正式 runbook：

1. 以至少 main@d5d98c2b1485a9a378f0c2dd9090b14f7b6168b1 的源码启动；
2. 通过 Provider 交易日历解析最新已完整结束交易日；
3. 只启动一次完整 --production B1-B7；
4. 若为 CLOSED，再对同一 run_id 执行 --verdict；
5. 将脱敏、run-bound evidence 放入独立 evidence PR。

本记录不是 Formal Production 结果证据，也不产生 Provider GO/NO-GO 或 Data Sufficiency 结论。
