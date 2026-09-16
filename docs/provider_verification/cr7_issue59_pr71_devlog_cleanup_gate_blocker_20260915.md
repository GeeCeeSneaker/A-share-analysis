# Issue #59 / PR #71 DEVLOG cleanup gate blocker（2026-09-15）

状态：`CLEANUP_APPLIED / CI_BLOCKED_BY_HISTORICAL_GATE / IDENTITY_IMPLEMENTATION_NOT_STARTED`

## 授权与清理结果

本记录承接 Owner decision comment `5690500282` 与 scheduler comment `5690539134`：先清理
PR #71 本轮新增的 DEVLOG SHA grandfather；如果扫描器因此失败，作为独立最小治理阻断返回，
不得再增加一条豁免。

清理提交为
`aa4a63554388d9fbd6c129f4b2f3ad0fb14223c9`，实际完成两项窄修改：

- 从 `tests/integration/test_devlog_gate.py` 移除
  `a4cad46b0ea54f7a08ec6f6c80ef20918aef2d39`；
- 从 `docs/DEVLOG.md` 删除为该临时豁免新增的说明段。

既有八条更早的历史 grandfather 未改动。本提交没有新增豁免、没有改写历史、没有运行时代码、
身份映射、universe 或 provider 行为变更。

## 权威 CI 事实

- base：`main@9423c1799ec970ea3d5076e1af5b3a5ab145ed8d`；
- cleanup head：`aa4a63554388d9fbd6c129f4b2f3ad0fb14223c9`；
- CI run：`35045136501`；
- Ubuntu 3.14 job：`104633217457`，结果 `failure`；lint、format、mypy 均成功；
  完整 pytest 为 `1850 passed, 6 skipped, 1 failed`；
- 唯一失败：`TestDevlogGate.test_code_commit_requires_devlog_change`，错误为：
  `a4cad46b0e: ['src/ashare_state/providers/amazingdata/mapper.py']`。

该 `a4cad46...` 是主线已有的不可变历史代码提交；本次 cleanup 删除了允许它通过的临时
grandfather 后，历史扫描器按当前规则正确地把它报告出来。给新提交补充 DEVLOG 不能改变原提交
的同批文件集合，重写主线历史也没有获得授权。因此这不是连续性调查或产品实现失败，而是一个
独立的历史治理/门禁策略阻断。

Windows 3.14 / 3.12 两条矩阵在本记录第一次固化时仍在执行；最终状态以同一 run 的 Actions
结果为准，并在 JSON 中更新。Ubuntu 的失败已足以证明当前 exact head 不能宣称全矩阵通过。

## 当前决策与解除条件

PR #71 继续保持 Draft/evidence-only。当前不得：

- 重新添加 `a4cad46...` 或其他新的 SHA grandfather；
- 重写主线历史以伪造原提交的 DEVLOG 同批变更；
- 开始 `300114.SZ → 302132.SZ` 身份事件实现；
- 重跑 2024-01 Canonical → Snapshot → ReadModel → projection 或下游 receipt、coverage、
  materialization 链。

最小解除条件是项目经理/Owner 单独决定并实施门禁历史策略整改，使 immutable pre-existing
commit 的处理与项目当前治理目标一致；该整改应作为独立治理变更审阅，不能藏进身份证据 PR。
之后重新对 PR #71 exact head 运行三平台 CI，并由独立审阅者决定是否接受 evidence-only PR。
身份事件仍应在该门禁阻断解除后作为小范围后续实现处理。

账号、密码、IP、端口、Token、Cookie、SDK/runtime、DuckDB 与 raw payload 均未进入 Git。
