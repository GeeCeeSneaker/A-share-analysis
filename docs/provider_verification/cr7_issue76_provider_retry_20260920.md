# Issue #76 provider 查询失败重试整改（2026-09-20）

## 结论

2025-09 的 InfoData.get_stock_basic 返回了 SDK 通用的“查询失败”。现有分类只能确认这是
ProviderSdkInternalError / QUERY_FAIL_UNCLASSIFIED，不能仅凭这条消息证明是服务端瞬时故障；
也不能排除请求参数、证券集合规模或权限边界。

因此本次只增加“显式端点准入的有界重试”，不把该错误全局改成可重试：

- 通用“查询失败”默认仍只尝试 1 次，保持原有 fail-closed 语义。
- 只有当前 Issue 观察到的 InfoData.get_stock_basic 端点在历史构建 runner 中显式允许重试。
- 首次失败后最多再尝试 2 次；默认运行参数为指数退避约 30 秒、60 秒，抖动 ±25%，单次等待封顶 120 秒。
- 认证、权限、schema、普通未知 SDK 错误不因本策略获得重试资格。
- 重试耗尽仍然 STOP(BLOCKED)，不得伪造 stock_basic 成功、删减证券或跳过月份；最终仍保留 ProviderSdkInternalError，并在 context 标明已重试次数。
- 每次 provider exchange 的 attempt_count 继续写入失败/成功 envelope，便于复核实际是否发生重试；预算耗尽错误额外保留 last_error_class 与分类规则 ID。

## 实现位置

- src/ashare_state/providers/amazingdata/timeout.py
  - RetryPolicy 新增端点级 generic-query-failure allowlist。
  - 修正指数退避为 base, 2*base, 4*base...，增加最大等待封顶。
  - run_with_budget() 默认使用带端点上下文的 policy，保留显式 callback 覆盖能力。
- tests/unit/test_amazingdata_provider.py
  - 覆盖默认不重试、端点 allowlist、端点隔离和等待序列/上限。
- tests/unit/test_provider_reliability.py
  - 覆盖真实 provider executor 的重试次数和 envelope attempt_count。
- 本机 data/spike/issue76_history_build_20260916/runner.py 已采用上述 2 次重试配置。该目录受
  .gitignore 的 data/* 规则保护，未作为源码上传；配置意图与参数在本报告中留档。

## 验证

- focused provider tests：64 passed。
- full tests/unit：505 passed，1 skipped。
- Ruff：通过。
- mypy（provider timeout/provider facade）：通过。
- 尚未用正式账号重跑 2025-09；因此不能把本次代码验证写成在线数据已恢复，也不能宣称 Issue #76 已解除阻断。

## 下一次在线运行要求

1. 在同一个安全 PowerShell 进程注入已有环境变量，执行 --resume --retry-blocked。
2. 观察 2025-09 的 InfoData.get_stock_basic 是否出现最多 3 次调用，以及等待是否按约 30/60 秒展开。
3. 若成功，核对该月份的 raw anchor、request hash、row count、completeness 和 state transition，再继续后续月份。
4. 若 3 次均返回同一通用失败，保持 STOP(BLOCKED)；不得继续增加次数或把所有端点加入 allowlist。按当前执行计划做受控的分块/新增证券窄探针，以区分瞬时服务故障和请求触发条件。
5. 任何在线结果都必须追加脱敏执行记录；凭据和原始 provider payload 只保留在本地 ignored 目录。

## 与当前调度的关系

此整改只处理 Issue #76 当前 2025-09 capture 的可恢复性，不授权：

- 跳过 2025-09 或其他月份；
- receipt、coverage、materialization、publication；
- Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1、strategy 工作。
