# Provider Verification — AmazingData / TGW（中国银河证券 格物金融服务平台）

> 状态：**历史试用账号 B1 证据保留；正式账号本地 SDK 冒烟通过；正式 repo B1-B7 / verdict / approval 仍待执行与复核**
> 本文件是 Provider 事实的唯一权威记录处（V1.3.2 §7.14）。主架构文档不维护接口细节。

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
- 当前状态：configs/production_account.yaml 仍为空；未通过 GitHub-only 仓库工作流发布人工确认记录，因此正式 identity freeze、B1-B7、Data Sufficiency Matrix、verdict 和 capability approval 继续未评定。


## 4. C++ SDK 存档（2026-08-21 摸底，已被 Python 版取代为集成路径）

- TGW C++ V1.0.8 已装运行库（`C:\Users\Public\Documents\mdga_file\lib`），DLL 加载链验证完整
- test_tool JSON 配置解析存在 64→32 位截断 bug（`ColocChannelMode` 三种格式实测均非法），不阻塞 Python 路径
- C++ 手册能力面（K线/快照/复权因子/三方资讯功能号体系）已存档于本文件历史版本与 `data/spike/manual_extract/manual_full.txt`

## 5. 已知问题与修订记录

- **2026-08-21（1）**：C++ SDK 摸底完成，test_tool 配置 bug 确认
- **2026-08-21（2）**：Python SDK（AmazingData 1.1.9 + tgw 1.0.9.2）受控安装 + import/API 面验证通过；发现仿真账号权限限制（仅 Level-1 快照），B2-B7 正式 Spike 顺延至正式账号
- **2026-08-21（3）**：**B1 连通性测试完成**（仿真账号 `330800****81`，掩码处理——审计 P1-18：真实账号编号不入版本库）：login/认证/代码表 PASS；calendar/hist_code_list/adj_factor/snapshot 服务端拒绝（PermissionCode 3|4|32|33 仅覆盖代码表）。SDK 行为观察 4 条入档 §2.2。证据：`data/spike/results/connectivity.json`（本地保存，gitignored）
