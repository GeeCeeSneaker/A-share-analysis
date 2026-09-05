# Runbook — Provider Doctor / T1 安全诊断

> AUDIT-H1：本说明替代旧的直接导出原始 doctor 报告方式。
> 当前整改 PR 经 Reviewer 合并、最终三平台 required CI 通过前，暂停任何真实账号 online bootstrap。
> SDK、版本、权限代码存在与正式身份/数据能力批准是不同事实。

## 1. 离线检查

在仓库根目录运行；不读取或使用账号凭证：

```powershell
uv run python scripts/spike/production_account_bootstrap.py --offline
uv run ashare provider-doctor --offline
```

| runtime verdict | bootstrap status | 退出码 | 证据含义 |
|---|---|---:|---|
| RUNTIME_ACTUAL_LOAD_VERIFIED | OFFLINE_RUNTIME_VERIFIED | 0 | 运行时实际加载证据 |
| RUNTIME_PACKAGE_VERIFIED | OFFLINE_PACKAGE_VERIFIED | 0 | 仅包级证据，不能替代实际加载 |
| ambiguous / mismatch / unverified | NOT_TESTABLE_RUNTIME | 2 | 停止排查 |
| SDK 不可用 | NOT_TESTABLE_SDK | 2 | 尚不可验证 |
| 未预期诊断错误 | ERROR | 3 | 不输出原始异常 |

离线报告不包含账号画像、认证、查询或冻结身份事实。退出码 0 也不构成 T1 证据。

## 2. 受控 T1（仅在 AUDIT-H1 合并后）

本地进程环境或未被跟踪的本地 .env 注入 TGW_*；值不进 CLI 参数、Git 或报告。
T1 使用唯一入口：

```powershell
uv run python scripts/spike/production_account_bootstrap.py --output data/spike/results/production_account_bootstrap.json
```

IDENTITY_CANDIDATE 同时要求：

- SDK_INSTALLED + RUNTIME_ACTUAL_LOAD_VERIFIED；
- AUTHENTICATED=YES、QUERY_READY=YES；
- exact generated/freezable non-trial profile；
- 解析到至少一个 ASCII 十进制 permission code；
- production_identity_status=NOT_FROZEN。

package-only 在线状态为 NOT_TESTABLE_RUNTIME；空白、纯分隔符、非法混合字符权限被拒绝。
存在不同冻结身份时为 FROZEN_IDENTITY_MISMATCH，不产生新候选；相同冻结身份继续人工审阅状态。
此命令始终不写 production_account.yaml。

候选之后仍需 T2 人工确认、T3 独立配置冻结，再进入治理要求的 B1-B7 与 Data Sufficiency/verdict。
provider-doctor 是诊断工具，不替代 T1 或正式能力审批。

## 3. 安全输出边界

doctor、provider-doctor 的 stdout/--output、bootstrap 共享 Safe Diagnostic Projection。
允许输出已验证格式的版本、ABI、固定状态、生成的脱敏 profile、解析后的权限码和有限数值。
删除 raw exception、自由文本 detail、原始 profile、任意附加字段及本地 DLL 路径。
版本无法通过格式验证时输出 null，不猜测版本。DLL 路径仍用于内部加载判断，但不作为公共报告字段。

登录/加载错误只公开稳定的 Provider 错误类别，不复制 SDK 原始消息、上下文或异常链。
嵌套 dict/list/tuple 的敏感键递归脱敏；通用脱敏不是允许任意自由文本公开的理由。
provider-doctor 的 stdout JSON 与 --output 文件来自同一个安全报告。

## 4. 本机临时介质（REV-02B）

TemporaryFile 会在本机临时介质捕获原始 fd 输出；正常退出/异常展开时自动关闭清理。
不能宣称秘密从不接触磁盘，也不能承诺强制终止后的安全擦除。
临时捕获不属于 repository 或持久 evidence，不得复制/提交；只保留投影后的报告。
登录在外层诊断隔离中使用独立的内层捕获，保留 profile 解析能力；其他嵌套捕获仍可复用外层。
不支持可靠捕获的平台在调用 SDK 前失败关闭。

REV-06 后续评估 hard deadline、kill/reap、pipe/内存 IPC 和 backpressure；本轮不重写为纯内存捕获。

## 5. 分层验收

1. Repository CI：Windows 3.14、Windows 3.12、Ubuntu 3.14 都必须成功；不安装专有 SDK、无真实凭证。
2. Controlled SDK/runtime：受控机器的独立加载证据，绑定源码 SHA 与环境。
3. Formal account / Production：T1/T2/T3、单一正式 run 和 capability 决策。

不得将第一层绿灯升级成第二/三层通过；未达到治理门禁保持暂停。
