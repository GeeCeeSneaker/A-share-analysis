# Runbook — Provider Doctor（Runtime Identity 诊断）

> 任务书 §2：Python tgw 包版本 ≠ C++ SDK 版本 ≠ 实际加载 DLL。
> 每次换机/升级 SDK/换账号后必须先跑 doctor。

## 1. 运行

```powershell
# 离线（无凭证）：SDK/版本/DLL 路径检查
uv run ashare provider-doctor --offline

# 在线（需 .env）：网络可达 + 登录 + 查询就绪 + 账号画像
uv run ashare provider-doctor --output data/spike/results/provider_doctor.json
```

## 2. 输出字段对照

| 字段 | 含义 | 参考值（2026-08-21） |
|---|---|---|
| PYTHON_VERSION | 解释器 | 3.14.6 |
| SDK_ABI | ABI 标识 | cpython314/win32-x64 |
| AMAZINGDATA_PACKAGE_VERSION | 数据接口层版本 | 1.1.9 |
| PYTHON_TGW_PACKAGE_VERSION | Python 绑定包版本 | 1.0.9.2 |
| TGW_RUNTIME_REPORTED_VERSION | 运行时自报版本（tgw.GetVersion） | V4.3.0.260626-rc2.0-YHZQ |
| TGW_LOADED_DLL_PATH | 实际加载的 DLL（进程模块枚举） | `...site-packages\tgw\win_py314_x64_package\tgw.dll` |
| TGW_LOADED_DLL_VERSION | DLL 文件版本资源 | null（TGW DLL 无版本资源，以自报为准） |
| NETWORK_REACHABLE | TCP 可达 | REACHABLE |
| AUTHENTICATED | 登录成功 | YES |
| QUERY_READY | 最小查询可用 | YES |
| ACCOUNT_PROFILE | 账号画像（脱敏） | TRIAL_SIMULATION_xxx + 权限码 |

## 3. 判定

| verdict | 含义 | 动作 |
|---|---|---|
| RUNTIME_ACTUAL_LOAD_VERIFIED | Python wheel 自带运行时已实际加载且路径一致 | 可继续正式 Spike 前置 |
| RUNTIME_PACKAGE_VERIFIED | 仅确认 wheel 层打包运行时存在，实际 DLL 尚未确认 | 先在线运行 doctor |
| RUNTIME_VERSION_MISMATCH | 版本线索冲突 | 停止；对照 provider_verification §1 排查后再测 |
| RUNTIME_PATH_AMBIGUOUS | 加载了 wheel 外的 tgw DLL（如公共路径 C++ 库） | 停止；排查 PATH/DLL 搜索顺序 |

## 4. 账号画像纪律（任务书 §6/§18）

- `account_profile_id` 区分 TRIAL_SIMULATION 与正式账号
- **仿真账号与正式账号的验证结果不得混记**：provider_verification 与
  Spike 案例目录都按 profile 分节
- 正式账号当前已完成本地 native SDK smoke；正式 Production run 前仍必须在线重跑 doctor，确认实际加载路径、脱敏 profile 和 entitlement，再按单一 B1-B7 run 执行
