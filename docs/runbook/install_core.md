# Runbook — 核心 Runtime 安装（干净机器）

> 前提：Windows 10/11 x64，管理员 PowerShell

## 1. 安装 uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# 重开终端确认
uv --version
```

## 2. Python 3.14（Reference Production Python，任务书 §1.4）

```powershell
uv python install 3.14
uv python list
```

> 注：若 uv 托管安装损坏（曾见 untrusted mount point, os error 448），
> 用系统 Python 3.14 安装器并 `.python-version` 固定，仓库已带此文件。

## 3. 克隆并同步

```powershell
git clone <repo-url> A-share-analysis
cd A-share-analysis
uv sync --frozen          # 核心依赖；不含 AmazingData SDK
```

## 4. 验证安装

```powershell
uv run pytest             # 全部通过（无需任何凭证/SDK）
uv run ashare self-test
```

预期：`121 passed`（以最新 CI 为准）、self-test 打印 namespace 与 fixture 校验。

## 5. CI 矩阵确认（任务书 §1.1）

推送 GitHub 后确认 Actions 三矩阵：Windows+3.14（REQUIRED）、
Windows+3.12、Linux+3.14。首跑全绿后将 M0 状态从 `PASS_PENDING_CI`
改为 `PASS`（`docs/m0_exit_report.md`）。

## 常见问题

| 症状 | 处置 |
|---|---|
| `uv sync` 慢/失败 | 确认网络；中国网络可设置 `UV_INDEX_URL` 镜像 |
| pytest 报 `pytz`/`tzdata` 缺失 | 确认用 `uv run` 而非裸 `python` |
| Windows 长路径报错 | `git config --system core.longpaths true` 后重克隆 |
