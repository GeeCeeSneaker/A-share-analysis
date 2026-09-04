# Runbook — AmazingData / TGW SDK 受控安装

> 前提：完成 [install_core.md](install_core.md)；已从银河获得两个 wheel
> （`AmazingData-<ver>-cp<py>-none-any.whl` + `tgw-<ver>-py3-none-any.whl`）

## 1. 记录 wheel 指纹（先存证再安装）

```powershell
Get-FileHash <wheel路径> -Algorithm SHA256
# 填入 docs/provider_verification/amazingdata.md §1
```

## 2. 受控安装（不写入 uv.lock —— 设计裁决 9）

```powershell
uv pip install .\Downloads\AmazingData\tgw-1.0.9.2-py3-none-any.whl `
               .\Downloads\AmazingData\AmazingData-1.1.9-cp314-none-any.whl
```

> cp 标签必须与本机 Python 一致（本机 3.14 → cp314）。
> 版本升级时：先记录新 wheel hash → 卸载旧版 → 安装新版 → 重跑 provider doctor。

## 2.1 运行时资料接口依赖（2026-09-04）

`AmazingData` 的 wheel 元数据不声明 PyTables，但历史状态、复权、北交所映射、公司行动、股权结构和行业资料接口会使用 `tables`。受控离线安装时，需把 `tables` 及其二进制/传递依赖 wheel 放在本地被忽略目录（例如 `vendor/amazingdata/dependencies/`），再执行：

```powershell
uv pip install --python <受控Python路径> --no-index --find-links <工作区>\\vendor\\amazingdata\\dependencies tables
uv pip check --python <受控Python路径>
```

缺少 `tables` 时，登录、日历、代码表和部分行情接口可能仍可用，但资料接口会返回 `ImportError`；这不能判定为账号无权限。

## 3. 版本兼容性事实（2026-08-21 验证）

- `tgw` wheel **自带全套原生运行时**（`site-packages/tgw/win_py314_x64_package/`
  内含 `tgw.dll` + `_tgw.pyd` + boost/ssl 依赖），运行时自报
  `V4.3.0.260626-rc2.0-YHZQ`
- 公共路径 `C:\Users\Public\Documents\mdga_file\lib\` 下的 C++ SDK 1.0.8
  运行库与 Python 链路**互不影响**（DLL 无版本资源，版本以
  `tgw.GetVersion()` 自报为准）

## 4. C++ 运行库（可选，仅 test_tool/独立 C++ 程序需要）

系统需 VC++ 2015-2022 x64 Redistributable。检查：

```powershell
Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
```

## 5. 验证

```powershell
# 5.1 离线验证（不联网）：import + 版本 + DLL 路径
uv run ashare provider-doctor --offline

# 5.2 在线验证（需 .env 凭证）：网络/认证/查询
uv run ashare provider-doctor --output data/spike/results/provider_doctor.json
```

离线预期 verdict：`RUNTIME_PACKAGE_VERIFIED`；在线且完成首次 SDK 调用后预期 verdict：`RUNTIME_ACTUAL_LOAD_VERIFIED`。
任何 `RUNTIME_PATH_AMBIGUOUS` / `RUNTIME_VERSION_MISMATCH` 都必须先排查
（对照 provider_verification §1-2）再继续。

## 6. CI 纪律

CI **永不安装**本 SDK（ci.yml 有显式 absence 断言）。SDK 相关代码全部
lazy import，缺 SDK 时抛 `ProviderUnavailableError`（类型化，非 ImportError）。

## 已知坑（2026-08-21 实录）

| 坑 | 说明 |
|---|---|
| login 打印 Token | SDK 向 stdout 打印 logon json（含 Token）；provider 层已做 fd 级捕获脱敏，勿绕过 session 直接调 `ad.login` |
| 无权限=TypeError | 无权限端点返回 None → SDK 内部 `TypeError: 'NoneType' ...`；一律通过 provider 层调用获得 `ProviderPermissionError` |
| 快照长重试 | `query_snapshot` 失败前重试 2-4 分钟；生产调用必须走 `TimeBudget` |
| C++ test_tool 配置 bug | 其 JSON 解析器 64→32 位截断（`ColocChannelMode`）；勿据此判断 SDK 故障 |
