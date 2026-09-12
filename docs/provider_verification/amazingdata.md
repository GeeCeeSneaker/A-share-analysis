## 1.4 2026-09-05 合并后 T1 受控 online bootstrap 前置检查（历史记录）

- main 当前已包含 PR #9 merge commit `f38e77ff2cbcf040837bc1c15504f847e1cfb1d8`；本次只验证受控入口的环境门禁，不重述或扩大历史 smoke 事实。
- Windows Python 3.14.6 离线 preflight 实际加载 `AmazingData==1.1.9` 与 `tgw==1.0.9.2`，runtime verdict 为 `RUNTIME_ACTUAL_LOAD_VERIFIED`，offline 状态为 `OFFLINE_RUNTIME_VERIFIED`。
- online bootstrap 在登录前因本地工作区没有 `.env` 且进程环境没有 `TGW_*` 变量而停止；安全无凭证检查为 `NOT_TESTABLE_ACCOUNT` / exit 2。未发起登录请求，不产生正式账号 profile、live identity candidate 或 entitlement 事实。
- `configs/production_account.yaml` 仍为空；凭证、Token、真实 host/port、raw SDK stdout/stderr、raw profile 不进入 GitHub。
- 下一步：只在受控 Windows 进程环境或未跟踪本地 `.env` 安全注入凭证后重跑 `production_account_bootstrap.py`；得到 scrubbed `IDENTITY_CANDIDATE` 后停止等待 T2 人工确认。T3、B1-B7、Data Sufficiency、verdict 和 Provider approval 继续 blocked。

# Provider Verification — AmazingData / TGW（中国银河证券 格物金融服务平台）

> 状态：**T2 已确认；T3 身份冻结 PR 待独立审阅与合并；正式身份在合并前仍未冻结；Production B1-B7 / verdict / approval 继续 blocked**
> 本文件是 Provider 事实的唯一权威记录处（V1.3.2 §7.14）。主架构文档不维护接口细节。


## 1.5 2026-09-05 T1 受控线上身份候选（当前权威）

- **源码绑定**：本次使用的 H1 源码树为 `6671c6e388163b9cb15137f716247b36d0290cc4`，已随 merge commit `c9787d243be5ca02a46496e38d5401fbf38a255b` 进入 main；当前复核 main 为 `9b08d40b4318dbd6a7784a14a9e86a743374713f`。
- **受控环境**：Windows Python 3.14.6；AmazingData 1.1.9；tgw 1.0.9.2；runtime reported version `V4.3.0.260626-rc2.0-YHZQ`；checked_at `2026-09-05T13:36:45.179509+00:00`。
- **安全投影**：`SDK_INSTALLED`、`RUNTIME_ACTUAL_LOAD_VERIFIED`、`NETWORK_REACHABLE=REACHABLE`、`AUTHENTICATED=YES`、`QUERY_READY=YES`；profile 解析/数字权限校验通过；脱敏候选为 `UNKNOWN_24e2ff401792`。
- **当前门禁**：`production_identity_status=NOT_FROZEN`、`bootstrap_status=IDENTITY_CANDIDATE`、`config_written=false`、`human_confirmation_required=true`。`configs/production_account.yaml` 保持为空。
- **边界**：这只是允许 T2 人工确认的脱敏候选，不是正式身份冻结、Provider capability approval、Production B1-B7、Data Sufficiency、verdict 或 backfill。原始凭证、endpoint、Token、profile、SDK stdout/stderr 和本地原始文件不进入 GitHub。
- **证据**：完整 allowlisted projection 见 [T1 bootstrap evidence](t1_bootstrap_20260905.md)；下一步只等待 T2，不重复无凭证预检或直接启动 B1-B7。



## 1.6 2026-09-05 T2 人工确认与 T3 身份冻结提案（当前权威）

- **T2 状态**：项目 Owner 已确认 exact scrubbed candidate `UNKNOWN_24e2ff401792` 对应计划使用的正式账号；确认时间为 `2026-09-05T22:19:58+08:00`，安全确认标记为 `project-owner`。
- **T3 提案**：本 PR 仅设置 `production_account_profile_id`、`confirmed_at`、`confirmed_by` 三个允许字段，候选值不做 trim、大小写归一化、alias 或手工改写。
- **当前门禁**：在 T3 PR 完成独立审阅、三平台 required CI 通过并合并前，生产身份仍不得视为冻结；不得运行 Production B1-B7、Data Sufficiency、verdict、Provider capability approval 或 backfill。
- **秘密边界**：账号、密码、Token、真实 endpoint、原始 profile、原始 SDK stdout/stderr 和本地 bootstrap 文件不进入 GitHub。

## 1. SDK 与环境（已验证）

| 项 | 值 |
|---|---|
| Python SDK 包 | `AmazingData==1.1.9`（cp314 wheel，匹配本机 Python 3.14.6） |
| wheel SHA-256 | `D9A5D12F20523F865F5CF017D134862BC985E01F1DCB0333C36F1876328006FA` |
| 底层依赖包 | `tgw==1.0.9.2`（`tgw-1.0.9.2-py3-none-any.whl`） |
| tgw wheel SHA-256 | `CBC30194E2D3923C87E5D40CE469B79575758001F9D5F7481D46C29C9667E21D` |
| 安装方式 | `uv pip install <wheel>`（受控安装，**不写入 uv.lock**——设计裁决 9） |
| 登录 API | `AmazingData.login(username, password, host, port)`（.env 注入凭证） |
| import 验证 | ✓（B1 离线冒烟：`data/spike/results/b1_sdk_env.json`） |
| 附带依赖 | numpy 2.5.2 / pandas 3.0.5 / scipy / statsmodels（SDK 自带数据分析栈） |
| C++ 运行库 | VC++ 14.50 已在系统（tgw 底层需要）；证书+运行库在 `C:\Users\Public\Documents\mdga_file\lib` |

### 1.1 API 面清单（import 实测）

- **BaseData**（10 方法）：`get_calendar`、`get_code_list`、`get_hist_code_list`、`get_code_info`、`get_adj_factor`（单次复权）、`get_backward_factor`（后复权）、`get_etf_pcf`、期货/期权代码表
- **InfoData**（53 方法）：`get_history_stock_status`（按日 ST/停牌/涨跌停/除权除息状态）、`get_stock_basic`（含 IS_LISTED 1上市/3终止上市）、`get_bj_code_mapping`（北交所新旧代码对照）、`get_equity_structure`（股本结构）、`get_dividend`/`get_right_issue`（分红配股）、`get_index_constituent`/`get_index_weight`（指数成分/权重）、`get_industry_base_info`/`get_industry_constituent`/`get_industry_daily`/`get_industry_weight`（行业四件套）、`get_margin_detail`/`get_margin_summary`（融资融券）、财务三表（`get_balance_sheet`/`get_cash_flow`/`get_income`）、龙虎榜/大宗交易/股东数据等
- **其他**：`MarketData`（行情查询）、`SubscribeData`（实时订阅）、`DownloadInfoData`（批量下载）+ 量化工具类（PortfolioOptimizer/RiskModel 等，项目不使用）

### 1.2 关键接口字段（手册确认）

`get_history_stock_status` 返回（按日、沪深 A）：
`MARKET_CODE / TRADE_DATE / PRECLOSE / HIGH_LIMITED / LOW_LIMITED / PRICE_HIGH_LMT_RATE / PRICE_LOW_LMT_RATE / IS_ST_SEC / IS_SUSP_SEC / IS_WD_SEC / IS_XR_SEC`——**单接口跨三个 Canonical 事实域**（任务书 §1.3 裁定）：`IS_ST_SEC/IS_SUSP_SEC` → Security Status 域；`HIGH_LIMITED/LOW_LIMITED` → Limit Price 域；`IS_WD_SEC/IS_XR_SEC` → Corporate Action 域。Provider DTO 保留全字段，Canonicalizer 按事实域路由，禁止合并为单一事实所有者。

缓存模式：`local_path` + `is_local`（True=本地优先缺则拉取并缓存；False=强制拉取并更新本地）。

## 1.3 2026-09-04 正式账号本地 SDK 冒烟验证

- **环境事实**：官方 `AmazingData==1.1.9` cp314 wheel、`tgw==1.0.9.2` 与 `tables` 运行依赖在受控 Python 3.14.6 环境导入成功；`uv pip check` 通过。依赖 wheel 只保存在本地被忽略目录 `vendor/amazingdata/`，未提交 GitHub。
- **认证事实**：正式账号登录成功，logon profile 可解析，权限码/功能权限字段存在；测试边界捕获了 SDK stdout/stderr，未持久化用户名、密码、Token、host、port 或原始 profile。
- **小窗口数据事实**：calendar 8,719；沪深当前代码 5,215；2026-09-03 单日历史代码列表 5,215；北交所映射 248；stock basic 1 行；历史状态 1 个结果；复权因子 8,719 行；分红 54 行；配股样本 0 行；股权结构 68 行；行业基础 511 行；行业成分 1 个结构化结果；股票/指数日线各 1 个结构化结果键；logout 正常。
- **边界**：这是原生 SDK 直连 smoke，不等同于 Provider facade、provider-doctor、run-scoped Production B1-B7、Golden/Data Sufficiency Matrix 或 capability approval。历史代码列表仅验证单日窗口，未宣称 2020+ 全历史覆盖。
- `configs/production_account.yaml` 仍为空，未冻结 production identity；正式结论保持未评定，待仓库源码环境执行单一 Production run 并完成人工 profile/Golden/Rule review。

## 2. 历史试用账号与当前正式账号状态

| 项 | 值 |
|---|---|
| 账号类型 | **历史试用/仿真账号（仅历史证据）**；正式账号当前事实见 §1.3 |
| 历史登录信息 | login 成功（2026-08-21 实测）：`SubscribeLimitNum=100`、`TotalWeekFlow=10GB`、`PushBandwidth/QueryBandwidth=3000`、`PermissionCode="3|4|32|33"` |
| 实测权限边界 | `get_code_list` **可用**（默认 5211 / EXTRA_STOCK_A 5549 只，后缀式代码 `600000.SH`）；`get_calendar` / `get_hist_code_list` / `get_adj_factor` / `query_snapshot` **全部无权限**（服务端拒绝） |
| 凭证注入 | `.env`（TGW_USERNAME/TGW_PASSWORD/TGW_SERVER_VIP/TGW_SERVER_PORT），不入库不入日志 |
| 证据 | `data/spike/results/connectivity.json`（P0-P4 探针全记录） |

### 2.1 历史仿真账号下的 Spike 范围裁定（2026-08-21）

| 阶段 | 仿真账号可做 | 结果 |
|---|---|---|
| B1 连通性 | login + 代码表 + 快照冒烟 | **完成**：网络/认证/SDK 数据面部分通（详见 §2）；快照被服务端拒绝（权限码不含） |
| B2-B7 正式评估 | ✗ **等正式账号** | 历史 K 线/历史状态/复权因子/行业成分均超出权限 |
| 正式 Spike 结论（GO/NO-GO） | ✗ **等正式账号** | "核心事实未验证前不得给 GO" |

> 本节仅记录 2026-08-21 仿真账号历史状态；2026-09-04 正式账号的当前事实见 §1.3。

### 2.2 SDK 行为观察（历史试用探测；生产 Adapter 必须处理）

1. **login 会向 stdout 打印含 Token 的 logon json**——生产 Adapter 不得转发 SDK stdout 进日志（Secret 纪律）；
2. **无权限请求的失败形态**：内部 `TypeError: 'NoneType' object is not subscriptable`（BaseData 系）或长重试后 `Exception: 查询失败`（MarketData 系）——**无类型化错误**，Adapter 必须包装所有调用并做 None/异常双防御；
3. `query_snapshot` 失败前重试 2-4 分钟（0.2MB/s 带宽）——生产 Adapter 需显式超时；
4. `get_code_info(["600000.SH"])` 报 `unhashable list`——签名与手册示例可能不一致，正式账号到位后核对。

历史试用轮次流量纪律执行情况：全轮探测累计消耗约 0.08GB / 10GB 周额度。

## 3. 正式账号 Production Spike 待验证事项

1. K 线历史深度实测（当前合同：2020-01-01 至最新完整交易日；不要求或回填 2020 年以前历史）
2. 退市证券包含性（当前合同：2020-01-01 起不产生 survivorship omission + `get_stock_basic.IS_LISTED=3`）
3. 历史证券状态全字段抽样（50 ST 加/脱帽 / 20 退市 / 30 涨跌停制度 / 20 除权除息连续性 Golden）
4. 复权因子表全历史 + 与交易所公告一致性
5. 行业 taxonomy 归属（`get_industry_base_info`：申万 or 银河自编 → GALAXY_xxx 纪律）
6. 行业成分历史区间（INDATE/OUTDATE）与日权重
7. Benchmark 指数日线可得性（中证全指/300/500/1000/2000）
8. EOD 数据可得时刻连续观测（OBSERVED vs CONSERVATIVE_ASSUMED）
9. volume/amount 单位实测（股/手、元/千元）
10. free-float 语义评估（`get_equity_structure` 字段 → EXACT/DERIVABLE/ALTERNATIVE/MISSING 四级结论）
11. 限流/并发实测（正式账号额度）
12. 指数成分股（`get_index_constituent` A010200001 对应）

## 3.1 当前 2020+ 合同与生产阻塞

- 默认历史边界已由 Owner 决策统一为 `2020-01-01 -> latest complete trading day`。
- `history_start_2020` / `history_coverage_2020_v1` 是当前 Spike Core Gate 的实现合同；旧的 `history_start_2018_plus_warmup` 只保留在历史文档中，不再作为当前 GO 条件。
- 正式账号已完成本地 native SDK 登录/API smoke，但正式 production profile identity 与 entitlement allowlist 尚未人工冻结；因此 B2-B7、正式 verdict、Golden/Data Sufficiency Matrix 和 capability approval 均保持未验证。
- 解除条件：Owner/Reviewer 提供脱敏稳定账号画像和实际 entitlement 后，按生产 Spike 单 Run 流程补齐证据；不得用试用账号结果替代正式生产证据。

## 3.2 2026-09-04 正式账号验证尝试（SDK 安装前历史记录）

| 项 | 当前事实 |
|---|---|
| 连接信息 | 已收到；原始凭据只保留在本次运行环境，不入库 |
| 独立网络探测 | Owner 提供的两个候选服务端点端口均 TCP `REACHABLE`；未在本文件记录 host |
| 官方 SDK | 当前受控 Python 3.14.6 环境未发现 `AmazingData` / `tgw` |
| AUTHENTICATED | `NOT_TESTED`（未发送登录请求） |
| ACCOUNT_PROFILE | `NOT_TESTED`（未产生 profile） |
| QUERY_READY | `NOT_TESTED` |
| B1-B7 / verdict | 未执行 / 未评定 |
| 配置纪律 | `configs/production_account.yaml` 继续为空；不以连接可达性替代 frozen identity |

当前结论：网络路径可达，但缺少银河官方 wheel，无法安全执行 provider doctor、正式登录或单一 Production Spike。安装官方 wheel 后，必须先完成 runtime actual-load doctor，再按单一 B1-B7 run、evidence closure、2020+ 历史合同和人工 Reviewer 流程继续。

### 3.3 P0-AD-01 脱敏身份 bootstrap 工具（2026-09-04）

- `scripts/spike/production_account_bootstrap.py` 是正式账号身份检查的受控入口：凭证只从 `TGW_*` 环境变量或本地 `.env` 读取，不接受 CLI 凭证参数，不打印或写出凭证。
- 输出只包含 scrubbed `account_profile_id`、权限/额度摘要、运行时版本、网络/认证/查询状态和 `production_identity_status`；原始 SDK error、stdout、Token、host、port 不进入输出。
- 默认只打印 JSON；`--output` 可写入操作者指定的本地证据文件。工具不会自动写入 `configs/production_account.yaml`，必须由 Owner/Reviewer 人工确认后再做独立治理提交。
- `--offline` 只验证 SDK/runtime，不读取或使用账号凭证，且完全绕过 `.env`/`--env-file` 读取。退出码只表达环境缺失、账号未就绪或候选 identity，不表达 capability approval。
- run `33889959971`（run `266`）已在三平台完成 bootstrap focused tests 与全量回归，每腿 `1427 passed`；这验证的是 P0-AD-01.1 工具边界，不是 live identity 冻结、Production B1-B7、Data Sufficiency Matrix、verdict 或 Provider approval。

示例：

```powershell
uv run python scripts/spike/production_account_bootstrap.py
uv run python scripts/spike/production_account_bootstrap.py --offline
uv run python scripts/spike/production_account_bootstrap.py --output data/spike/results/production_account_bootstrap.json
```

### 3.4 2026-09-05 P0-M-1B.0 identity gate hardening

- 仓库实现已把 frozen identity 收敛为 positive exact-match allowlist：profile id 必须是 digest-shaped scrubbed 值，且必须同时具备带时区的人工确认时间和 approved human/operator marker。
- 空配置、未确认配置、试用形态、畸形 YAML、额外字段、敏感 marker、未解析 profile、缺 PermissionCode 和未知/非 exact-match profile 均保持 NOT_TESTABLE / UNKNOWN；RunKind.PRODUCTION 不会单独升级账号身份。
- bootstrap projection 对 provider 返回的 profile id、权限码和额度执行安全类型投影；这批 focused tests 只证明仓库 fail-closed 边界，不产生 live identity candidate。
- 仓库 CI 证据：最终代码 head `66ab5ec7` 对应 run `33899576457`（run 277）在 Ubuntu 3.14、Windows 3.12、Windows 3.14 全部成功，每腿 `1449 passed`；Ruff、mypy、Spike dry-run、SDK-absent 及适用治理门禁均通过。该结果只验证仓库 guard，不是 live bootstrap 或正式 profile 证据。
- 当前状态：T1 脱敏 identity candidate `UNKNOWN_24e2ff401792` 已获项目 Owner T2 确认；T3 仅待独立审阅、CI 和合并，正式 identity freeze 在合并前仍未生效，B1-B7、Data Sufficiency Matrix、verdict 和 capability approval 继续 blocked。


## 4. C++ SDK 存档（2026-08-21 摸底，已被 Python 版取代为集成路径）

- TGW C++ V1.0.8 已装运行库（`C:\Users\Public\Documents\mdga_file\lib`），DLL 加载链验证完整
- test_tool JSON 配置解析存在 64→32 位截断 bug（`ColocChannelMode` 三种格式实测均非法），不阻塞 Python 路径
- C++ 手册能力面（K线/快照/复权因子/三方资讯功能号体系）已存档于本文件历史版本与 `data/spike/manual_extract/manual_full.txt`

## 5. 已知问题与修订记录

- **2026-08-21（1）**：C++ SDK 摸底完成，test_tool 配置 bug 确认
- **2026-08-21（2）**：Python SDK（AmazingData 1.1.9 + tgw 1.0.9.2）受控安装 + import/API 面验证通过；发现仿真账号权限限制（仅 Level-1 快照），B2-B7 正式 Spike 顺延至正式账号
- **2026-08-21（3）**：**B1 连通性测试完成**（仿真账号 `330800****81`，掩码处理——审计 P1-18：真实账号编号不入版本库）：login/认证/代码表 PASS；calendar/hist_code_list/adj_factor/snapshot 服务端拒绝（PermissionCode 3|4|32|33 仅覆盖代码表）。SDK 行为观察 4 条入档 §2.2。证据：`data/spike/results/connectivity.json`（本地保存，gitignored）
## 6. 2026-09-12 定向能力闭环预检（当前状态）

本节覆盖 Issue #39 comment `5636256765` 指定的六个问题。它是**非 Production capability probe**，不是 Formal B1-B7，也没有创建 `SpikeRun`、写入 catalog/verdict 或修改 Golden/H1/2020 基线。完整脱敏收据见 [`capability_closure_20260911.json`](capability_closure_20260911.json)，逐项矩阵见 [`capability_closure_20260911.md`](capability_closure_20260911.md)。

独立 exact-head 审阅指出：观察到的行形状和进度码相关性不足以授权生产归一化。本节因此区分“收据中的原生观察”和“当前运行时行为”；两条猜测性过滤均已删除，当前语义保持 `STILL_UNRESOLVED` 并失败关闭。

### 6.1 已确认的 SDK 契约

- AmazingData `1.1.9` 的 `InfoData.get_history_stock_status`、`get_dividend`、`get_right_issue` 在传入日期窗口时使用 `begin_date`/`end_date`；`is_local=False` 才明确走远端下载分支。facade 已记录实际生效参数。
- `InfoData.get_bj_code_mapping` 是无 `code_list` 参数的完整表端点；facade 不再向 SDK 传入不支持的参数，调用时保留客户端过滤声明。
- `MarketData.query_kline` 的 SDK 默认 period 为分钟值 `10000`；日线值为 `10008`。`DAY` facade 现在显式传 `period=10008`，避免表面上请求日线而实际落到分钟默认值。
- BJ mapping 预检此前被本地运行时缺少 `PyTables` 阻断；当前工作区已补存并安装 `tables==3.11.1` 及其直接依赖 wheel。该依赖只在本地 `vendor/`，不进入 Git。

### 6.2 预检结论

| 能力/问题 | 结果 | 当前边界 |
|---|---|---|
| 状态日期 shape | 20,638 行中 8 行同时缺身份与 `TRADE_DATE`；原生 shape 观察已确认 | 不再做双缺失过滤；`canonical_status_view()` 对缺失交换所限定身份失败关闭；“汇总行”语义仍 `STILL_UNRESOLVED` |
| 退市字段 | 4 个请求返回 3 行，含 `IS_LISTED`/`LISTDATE`/`DELISTDATE`，`PROVIDER_CONFIRMED` | 历史 PIT 退市语义仍 `STILL_UNRESOLVED`；`hist_code_list` 只作连续性证据 |
| BJ mapping | 原生端点返回 248 行，`PROVIDER_CONFIRMED` | `golden_bj_mapping` 仍未建设；接口可用不等于 mapping gate PASS |
| BSE 历史状态 | `835185.BJ` 精确 2022 年请求返回 0 行空表，`PROVIDER_CONFIRMED` | 空响应的历史覆盖/适用性语义 `STILL_UNRESOLVED` |
| 公司行为 | Dividend 123 行，其中 50 行 `DATE_EX` 缺失且集中在观察到的进度 1/2/12；Right issue 6 行均有 `EX_DIVIDEND_DATE` | Dividend `STILL_UNRESOLVED`，任何缺 `DATE_EX` 行均失败关闭；Right issue 因旧缺失未复现仍 `STILL_UNRESOLVED` |
| `300104.SZ` fixture | code-list 3,907 行包含目标；目标日线 0 行，同窗口 `600519.SH` 控制为 7 行，`PROVIDER_CONFIRMED` | 目标 fixture 当前不可用；替代候选仅提出未应用；适用性/可交易性 `STILL_UNRESOLVED` |

### 6.3 复核与下一道门

原始收据绑定代码提交为 `258489bc29359a1212cd33528ac5764ceb97e110`；本次语义整改代码提交为 `de411142bd3a80a998418ce2c48ae8e134993012`。本地全量 pytest、Ruff、mypy、py_compile、`uv pip check`、`git diff --check` 已通过；整改精确 head `5680d9365794872be4e8767b7aa379be7e534406` 的 GitHub Actions CI `#547` 三个平台均成功，GT-H3B `#95` 按策略 skipped。当前未重新调用 Provider 或重跑在线预检，仍需独立 delta review。未决项不得通过新建 Formal run、修改 Golden、放宽基线或重跑旧 verdict 来掩盖。

## 7. 2026-09-12 剩余六项能力闭环（当前交接）

独立 Reviewer 接受 PR #45 后，调度要求只允许再做一次窄范围能力/契约闭环。详细的
“证据来源 → 已确认事实 → 分类 → Formal 影响”矩阵见
[`remaining_capability_closure_20260912.md`](remaining_capability_closure_20260912.md)，
机器可校验 truth bundle 见
[`remaining_capability_truth_20260912.json`](remaining_capability_truth_20260912.json)。

> BSE 历史状态行的归因已由下方第 8 节审阅者授权的当前代码 delta 更新；其余边界和
> Golden/H1/基线不变。

本轮没有新增 Provider 调用或 Formal run。BSE 一手材料把 `835185.BJ` 的空历史响应
排除了“不适用”的解释，但不能把 Provider 空响应升级成历史状态 PASS；深交所一手公告
则证明 `300104.SZ` 自 2019-05-13 已暂停上市，因此它被分类为 2020 基线不适用。
`601558.SH` 仅作为有一手退市与 2020 统计依据的替代候选，尚未激活。

调度侧推荐为 `COMPOSITE/FALLBACK_SOURCE_REQUIRED`（仅诊断，不是 Production 授权）。
在 PIT 状态、状态异常行、公司行为字段语义取得权威契约前，运行时继续失败关闭，不改
Golden、H1、全局 baseline 或旧封存结果。

## 8. 2026-09-12 BSE 当前代码归因 delta

> 状态：**REVIEWER-AUTHORIZED SINGLE PROBE COMPLETED / OLD RECEIPT PRESERVED / LOCAL REGRESSION ADDED / INDEPENDENT DELTA REVIEW REQUIRED**

- Issue #39 最新审阅要求只允许一次窄范围请求：同一 `2022-01-01/2022-12-31` 窗口、同一 `InfoData.get_history_stock_status` 端点、单证券 `920185.BJ`、不重试。请求完成并返回 242 行；脱敏 request id、request hash、schema/payload/evidence hash 见 [`remaining_capability_truth_20260912.json`](remaining_capability_truth_20260912.json) 的 `bse-historical-status.current_code_probe`。
- 上一版封存的 `835185.BJ` 0 行结果、request/evidence hash 和本地 raw 闭包均保持不变。BSE 官方 mapping 表将 `835185` 绑定到 `920185`；官方代码切换公告说明自 2025-10-09 起交易委托、行情查询和业务办理使用新证券代码。因此旧空结果现在分类为 `CODE_MIGRATION_REQUEST_ROUTING_REMEDIATION_REQUIRED`，不再归因于 Provider 历史覆盖限制，也不改写为“不适用”或 PASS。
- 定向 probe 的 BSE 状态请求已改用当前代码，并新增离线单元回归；`get_history_stock_status_exchange()` 仍按输入原样发送并记录请求，不在 facade 内隐式调用 mapping 或静默重写用户请求。需要当前运行时查询的调用方必须先应用一手 mapping。
- 该 delta 只解决请求身份归因，不证明历史 PIT、异常 status shape 或 status 字段语义；这些仍 fail-closed，`COMPOSITE/FALLBACK_SOURCE_REQUIRED` 仍只是诊断推荐。没有创建 Formal/SpikeRun，没有运行 Production、`--resume` 或 `--verdict`，没有修改 Golden、H1、2020 baseline、catalog、verdict 或 Provider 配置。
