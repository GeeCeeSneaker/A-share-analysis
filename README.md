# A-share Market State Data Foundation (Daily Module)

可复现、可审计、可追溯的 A 股市场态势数据基座。项目当前处于受控的 SH/SZ 日频研究数据建设阶段；活跃任务与阻塞见 [`CURRENT_EXECUTION_PLAN.md`](docs/project/CURRENT_EXECUTION_PLAN.md)，优先级路线见 [`IMPLEMENTATION_ROADMAP_20260925.md`](docs/project/IMPLEMENTATION_ROADMAP_20260925.md)。

设计依据（冻结基线，只读保存于 `docs/design/`）：

- 《A股市场态势数据基座（日频模块）V1.3.2 开发方案》（Frozen Baseline）
- 《Phase0 启动方案 设计评审与裁决回复》（GO WITH CHANGES，2026-08-21）

## 环境要求

- Windows 10/11 x64 + PowerShell；Python 3.14.x 是唯一支持/参考应用运行时
- Ubuntu + Python 3.14 仅用于 CI 跨平台检查，不代表支持 Linux 部署
- [uv](https://docs.astral.sh/uv/) 包管理器
- 当前仅支持从**源码 checkout** 运行；wheel/独立安装不受支持，因为 DuckDB migrations 位于仓库根目录。`ashare self-test` 会在不符合此布局时给出明确错误。

## 快速开始（Windows / PowerShell）

```powershell
# 1. 安装依赖（含 dev 工具链；不含 AmazingData SDK）
uv sync

# 2. 配置非敏感连接设置（用户名、服务地址、端口；.env 已被 gitignore）
Copy-Item .env.example .env
# 首次安装或密码轮换：隐藏输入一次，保存到当前 Windows 用户的 Credential Manager
uv run python scripts/spike/production_account_bootstrap.py --store-credential

# 3. 从源码 checkout 初始化数据库（顺序执行全部 migrations，带 checksum 登记）
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
uv run ashare update --through 2026-09-25 --plan  # 无登录地检查接受边界/更新计划
$env:ASHARE_EVIDENCE_BACKUP_ROOT = "\\backup-host\ashare-evidence" # 独立网络/异地目录
uv run ashare update --through 2026-09-25         # 有批准能力、已验收基线和备份根时增量更新
uv run ashare evidence verify                     # 校验接受运行、归档与第二副本
uv run ashare evidence archive <update-run-id>     # 补做/重试某次接受运行的归档
```

每次新接受的日增量会封装为一个不可变 ZIP，内含更新 manifest、原始响应元数据和载荷；同一 ZIP 与留存收据会复制到 `ASHARE_EVIDENCE_BACKUP_ROOT`。也可用 `--backup-root <path>` 单次覆盖。备份失败会在更新结果中标为 `BACKUP_FAILED` 并输出醒目警告，但不会撤销已经接受的数据；之后可用 `ashare evidence archive <update-run-id>` 重试。备份根应位于独立网络共享/异地存储，不能与 `data_root` 重叠；程序只校验目录分离，无法判断配置的目标是否确实在另一台机器上。历史已接受运行可通过 `ashare evidence verify` 巡检本地 ZIP、第二副本和收据哈希。

更新后应通过 `DuckDBReadModel.open_read_only_with_snapshot(snapshot_id)` 打开经 Snapshot seal 验证的只读研究面；先从 `meta_daily_update_run` 读取最近一次成功记录的 `snapshot_id`。目前没有独立 `ashare read` CLI，避免把未定义的查询接口伪装成稳定命令。

## 目录结构

```text
docs/design/                  冻结设计文档（只读）
docs/research/                CR-7 R1 研究面板合同与下游读取说明
docs/adr/                     架构决策记录（ADR-007 Tushare 缺位、ADR-008 DuckDB 进程模型…）
docs/provider_verification/   Provider 联调验证记录
migrations/                   DuckDB 顺序迁移（按版本号连续应用）
src/ashare_state/             核心包（identity / providers / canonical / snapshot / readmodel / update / cli）
scripts/spike/                P0-M-1 AmazingData Spike 脚本（真实账号，输出隔离 data/spike/）
tests/                        unit / integration / fixtures
data/                         本地数据（gitignored，非 git 记录对象）
```

## 项目核心原则：最小化优先

**在系统架构、业务逻辑、任务流转、接口、参数字段、数据契约、安全机制和运维流程的所有设计与审阅中，始终优先选择满足当前目标、正确性和必要安全边界的最小方案。**

- 能用明确规则、约定、模块边界或已有机制解决的问题，不新增服务、框架、状态层、审批环节、抽象层或持久化对象。
- 不为极端、尚未发生或没有现实证据的场景预先增加复杂度；只有出现真实需求或已证实风险时，才增加对应机制。
- 一个问题原则上只在一个责任层解决，避免同一约束在多个层级重复实现、重复校验或重复存储。
- 不为“未来可能复用”提前抽象；没有第二个真实使用场景时，优先保持直接实现。
- 字段、状态、配置项、流程节点和证据项都必须有当前明确用途；没有用途或可由既有事实推导出的内容应删除，而不是保留备用。
- 安全设计遵循“足够而非最大化”：保护真实风险，但不得以防御极端情况为理由制造持续的人工作业、重复确认、双重数据面或复杂凭证流转。
- 每次方案评审、代码审阅和阶段收口都必须反向检查：**是否存在可以删除的层、字段、状态、流程、校验、测试或兼容路径，而不损害当前目标与正确性。** 如果存在，应优先简化。
- 临时 Spike、迁移辅助和一次性兼容代码完成使命后应评估删除；但不得为了“清理”而进行与当前目标无关的大规模重构。

这是一条长期工程约束，不是某个阶段的临时偏好。后续任何设计、实现或调度如果与本原则冲突，应默认要求给出具体、现实、可验证的必要性，否则选择更简单的方案。

## 关键工程纪律（摘自设计裁决）

- **仓库操作本地 Git 优先**：Codex / Agent 默认在本地 clone / worktree 中完成仓库读取、diff、分支、提交、fetch/push 与 SHA 核对；GitHub Connector / API 仅作为故障回退或 PR / Issue / Actions 等 API 原生动作的辅助路径，不替代本地仓库作为日常代码事实源。远端写入或合并前必须核对 exact base/head SHA；本地与 Connector 视图不一致时 BLOCK，先完成同步与对账。
- DuckDB 采用**进程级独占所有权**：任一时刻整个库只由一个进程持有，不承诺跨进程读写并存
- Manifest `file_uri` 为逻辑 URI（相对 `data_root`、统一 `/`、无盘符），**精确比较**；仅大小写不同 → BLOCK
- Manifest 身份 Hash 只由逻辑字段生成，与机器路径 / run_id / 时间戳无关
- 已应用 migration 的 SQL 被修改 → 启动 BLOCK
- Security ID：UUIDv5 固定命名空间（ADR-002）；缺 `first_list_date` 不得进入 PUBLISHED
- 单源状态下 reconciliation 状态为 `NOT_RUN_NO_SECONDARY`，禁止伪造 PASS
- 银河行业 ≠ 申万；`FLOAT_A_SHARE` ≠ `free_share`；未验证语义不得替代
