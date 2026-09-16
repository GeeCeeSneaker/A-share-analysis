# Issue #59 / PR #71 DEVLOG cleanup gate blocker（2026-09-15）

状态：`HISTORICAL_GATE_POLICY_REMEDIATION_VERIFIED / REVIEW_PENDING / IDENTITY_IMPLEMENTATION_NOT_STARTED`

本文件先记录 cleanup 提交触发的历史扫描失败；最新 scheduler checkpoint `5691108824`
已给出后续治理决议：删除 obsolete history scanner，重新验证 exact head。以下历史 CI 事实
不因治理策略变更而被抹去。

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
- Ubuntu 3.14 job：`104633217457`，结果 `failure`；lint、format、mypy 均成功；完整 pytest
  为 `1850 passed, 6 skipped, 1 failed`；
- Windows 3.14 job：`104633217255`，结果 `failure`；完整 pytest 为
  `1850 passed, 6 skipped, 1 failed`；
- Windows 3.12 job：`104633217454`，结果 `failure`；完整 pytest 为
  `1850 passed, 6 skipped, 1 failed`；
- 三个平台唯一失败均为 `TestDevlogGate.test_code_commit_requires_devlog_change`，错误均为：
  `a4cad46b0e: ['src/ashare_state/providers/amazingdata/mapper.py']`。

该 `a4cad46...` 是主线已有的不可变历史代码提交；本次 cleanup 删除了允许它通过的临时
grandfather 后，历史扫描器按当前规则在三个矩阵中均报告它。给新提交补充 DEVLOG 不能改变原提交
的同批文件集合，重写主线历史也没有获得授权。因此这不是连续性调查或产品实现失败，而是一个
独立的历史治理/门禁策略阻断；当前 exact head 不能宣称全矩阵通过。

## 当前决策与解除条件

PR #71 继续保持 Draft/evidence-only。当前不得：

- 重新添加 `a4cad46...` 或其他新的 SHA grandfather；
- 重写主线历史以伪造原提交的 DEVLOG 同批变更；
- 开始 `300114.SZ → 302132.SZ` 身份事件实现；
- 重跑 2024-01 Canonical → Snapshot → ReadModel → projection 或下游 receipt、coverage、
  materialization 链。

## 最新治理整改

按 scheduler checkpoint `5691108824`，PR #71 本轮删除整个
`tests/integration/test_devlog_gate.py`。原因是该测试扫描不可变 Git 历史、携带永久 SHA
grandfather，并把维护约定当作产品 pytest 门禁；项目约定已由 `CONTRIBUTING.md` 和
`ENGINEERING_PRINCIPLES.md` 覆盖。整改明确不引入任何替代历史扫描、diff scanner、hook、
policy engine 或 SHA allowlist，也不改写历史。

删除后的完整 QA 与 exact-head 三平台 CI 已通过：head
`669137f7629f1b68e5a6401052cfd601c5b8530b` 的 CI run `35049654822` 中，Ubuntu 3.14、Windows
3.14、Windows 3.12 均为 success，每平台 `1848 passed, 6 skipped`，AmazingData SDK absence
检查通过；GT-H3B run `35049654866` 按范围 skipped。当前证据文件前述旧 run 仍是整改前的历史
结果，不与这次成功混淆。PR #71 仍为 evidence-only Draft，等待独立审阅/合并；合并后才允许
开始最小身份事件 follow-up。

最小解除条件是项目经理/Owner 单独决定并实施门禁历史策略整改，使 immutable pre-existing
commit 的处理与项目当前治理目标一致；该整改应作为独立治理变更审阅，不能藏进身份证据 PR。
之后重新对 PR #71 exact head 运行三平台 CI，并由独立审阅者决定是否接受 evidence-only PR。
身份事件仍应在该门禁阻断解除后作为小范围后续实现处理。

账号、密码、IP、端口、Token、Cookie、SDK/runtime、DuckDB 与 raw payload 均未进入 Git。
