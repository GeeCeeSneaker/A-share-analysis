# A-share Market State Data Foundation (Daily Module)

可复现、可审计、可追溯的 A 股市场态势数据基座。本仓库当前处于 **Phase 0**：
工程骨架（P0-M0）与 AmazingData Provider Spike（P0-M-1）并行推进。

设计依据（冻结基线，只读保存于 `docs/design/`）：

- 《A股市场态势数据基座（日频模块）V1.3.2 开发方案》（Frozen Baseline）
- 《Phase0 启动方案 设计评审与裁决回复》（GO WITH CHANGES，2026-08-21）

## 环境要求

- Windows 10/11 + PowerShell（Linux 亦受 CI 支持）
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器

## 快速开始（Windows / PowerShell）

```powershell
# 1. 安装依赖（含 dev 工具链；不含 AmazingData SDK）
uv sync

# 2. 配置凭证（复制模板并填写真实值；.env 已被 gitignore）
Copy-Item .env.example .env

# 3. 从零初始化数据库（顺序执行 migrations 001-004，带 checksum 登记）
uv run ashare init-db

# 4. 运行全部测试（含迁移从零初始化、双重建身份一致性、单写者、失败注入）
uv run pytest

# 5. 本地质量门禁（CI 的本地等价物，不替代 CI）
./scripts/quality_gate.ps1
```

## AmazingData SDK（可选，仅受控机器安装）

SDK 为券商本地分发的 wheel，**不进入** `uv.lock`（禁止机器绝对路径污染锁文件）。
在受控开发机上手动安装：

```powershell
uv pip install <path-to-amazingdata-wheel>
```

安装后记录包名/版本/安装方式/哈希到 `docs/provider_verification/amazingdata.md`。
核心代码通过 lazy import 使用 SDK；SDK 缺失时核心功能与 CI 全部正常。

## 常用 CLI

```text
uv run ashare init-db            # 从零执行迁移
uv run ashare migrate            # 增量执行未应用迁移（幂等 + checksum 校验）
uv run ashare security-id-check  # 双重建确定性校验（固定 fixture）
uv run ashare self-test          # 快速自检
```

## 目录结构

```text
docs/design/                  冻结设计文档（只读）
docs/adr/                     架构决策记录（ADR-007 Tushare 缺位、ADR-008 DuckDB 进程模型…）
docs/provider_verification/   Provider 联调验证记录
migrations/                   DuckDB 顺序迁移（001-004）
src/ashare_state/             核心包（identity / providers / storage / cli）
scripts/spike/                P0-M-1 AmazingData Spike 脚本（真实账号，输出隔离 data/spike/）
tests/                        unit / integration / fixtures
data/                         本地数据（gitignored，非 git 记录对象）
```

## 关键工程纪律（摘自设计裁决）

- DuckDB 采用**进程级独占所有权**：任一时刻整个库只由一个进程持有，不承诺跨进程读写并存
- Manifest `file_uri` 为逻辑 URI（相对 `data_root`、统一 `/`、无盘符），**精确比较**；仅大小写不同 → BLOCK
- Manifest 身份 Hash 只由逻辑字段生成，与机器路径 / run_id / 时间戳无关
- 已应用 migration 的 SQL 被修改 → 启动 BLOCK
- Security ID：UUIDv5 固定命名空间（ADR-002）；缺 `first_list_date` 不得进入 PUBLISHED
- 单源状态下 reconciliation 状态为 `NOT_RUN_NO_SECONDARY`，禁止伪造 PASS
- 银河行业 ≠ 申万；`FLOAT_A_SHARE` ≠ `free_share`；未验证语义不得替代
