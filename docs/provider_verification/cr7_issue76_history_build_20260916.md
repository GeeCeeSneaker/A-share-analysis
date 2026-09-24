# Issue #76：78 个月权威历史构建执行记录

## 最新运行检查点（2026-09-20：2025-09 provider 查询阻断）

> 状态：**STOP(BLOCKED) at 2025-09 / 68 of 78 capture PASS / no publication**

本次重启已使用本机 broker-enabled Python 环境加载最新代码，已越过认证和 SDK 缺失边界；这不是账号、密码、端口、窗口或 AmazingData/tgw 缺失问题。

- 2025-02 retained replay、2025-03 至 2025-08 均为 PASS，当前累计 68/78 个月 capture PASS；2025-09 是首个未通过月份，之后还有 9 个月未运行。
- 2025-09 的 BaseData.get_hist_code_list 已成功返回 5,161 个证券，raw request 为 00d56838-f7b5-4f4f-87ff-203251a647e2；与 2025-08 的 5,153 个相比新增 8 个 provider symbol：001285.SZ、301563.SZ、301575.SZ、301584.SZ、301656.SZ、301668.SZ、603370.SH、603418.SH。这只是输入差异观察，不是根因结论。
- 阻断发生在随后唯一的 InfoData.get_stock_basic(code_list) 调用：ProviderSdkInternalError，cause chain 为 Exception，脱敏原文为“generic query failure ... 查询失败”。2025-09 没有形成 stock_basic raw meta，因此不能把该月标为部分成功。
- 代码对该通用错误按低置信度、未归因的 SDK 内部错误处理，当前 runner 的 RetryPolicy(max_retries=0) 不会自动重试；fail-closed 逻辑因此正式写入 STOP(BLOCKED)，没有跳过该月。
- 这不是已证实的参数上限：2025-07 的 stock_basic 曾以 5,159 个代码成功，2025-08 以 5,153 个代码成功。当前仍无法仅凭“查询失败”区分服务瞬时故障、某个新增证券/请求组合问题或账号侧接口限制。
- 停止后没有活动 runner 子进程；安全启动窗口仅停留在结束提示。凭证、账号身份、服务地址、原始 payload 和本地 ledger 均未写入 GitHub。

### 最小下一步

1. 保持 2025-09 阻断，不跳过、不删减 8 个新增证券、不把失败调用伪造为 raw 成功。
2. 重新登录后对同一 2025-09 输入做一次明确重试；若仍失败，再做受控的分块/新增证券窄探针，以区分 provider 瞬时故障与请求/证券数据触发条件。
3. 只有 2025-09 及后续月份全部 capture PASS，才可进入 receipt、coverage、materialization、ordinary-reader、幂等、冲突和 publication gates。

## 当前整改检查点（2026-09-20：身份切换适用性修复与留存重放）

> 状态：**STOP(BLOCKED) at 2025-03 / 62 of 78 capture-or-retained-replay PASS / no publication**

本次已按 PM review 在既有 completeness/status applicability 边界接入 ApprovedIdentityEvent 注册表：

- 对批准事件一侧的越区间状态行，仅当同一事件的另一侧是该交易日 exact-day applicable member 时消除结构误报；不重写原始 provider symbol、不制造另一侧状态，也不改 daily-bar/request pair。
- 对应回归覆盖当前事件、第二个合成批准事件、半开区间边界、无关行、歧义/重叠、非法区间以及 old/new 冲突；失败证据仍 fail-closed。
- 最终代码/测试提交为 `a5093e9ef9eefab2fd981441dd9873608554c6bc`；本地 unit 为 `500 passed, 1 skipped`，精确提交 CI run `666` 成功，GT-H3B run `176` 按范围跳过。
- 使用已保留 raw 做 2025-02 retained replay：`PASS`，月度证券 `5,133`、交易日 `18`，required/returned `92,190/92,190`，missing/extra/unresolved/structural 均为 `0`。这次重放没有 SDK/网络 provider 请求；状态文件中的 `30` 是 retained in-memory facade 的方法调用计数，不是外部请求。
- 2025-03 尚未发起 provider 请求，在同一 Codex 执行进程的安全环境检查处停止：`TGW_PASSWORD` 不可见。账号、口令、服务地址、原始 payload 和本地 ledger 均未写入 GitHub。

因此当前不是数据完整性失败，也不是 78/78 完成；下一步是让 2025-03 起始在线 runner 在同一进程安全获得变量后继续，直到新的真实 blocker 或 78/78 capture closure。后续 receipt、authoritative coverage、materialization、ordinary-reader、idempotency 和 changed-content conflict gates 仍未到达。

> 历史状态（修复前）：**STOP(BLOCKED) at 2025-02 / 61 of 78 capture PASS / identity-applicability mismatch / no publication**

## 历史检查点（2026-09-20，身份修复前的 2025-02 fail-closed）

- 这次不是窗口异常退出：runner 已将状态正式写成 `STOP(BLOCKED)`，安全启动窗口仍停留在结束提示；当前没有第二个 runner。状态文件最后更新时间为 `2026-09-20T08:02:13.8040243Z`。
- 已完成 `61/78` 个月 capture `PASS`；最近通过的是 `2024-09` 至 `2025-01`，`2025-02` 是第一个未通过月份，之后 `2025-03` 至 `2026-06` 的 `16` 个月尚未运行。此次 `2025-02` 实际发生 `30` 次 provider calls，失败不是认证或窗口问题。
- `2025-02` 的 raw 请求元数据均为 provider `OK`；交易日 `18` 天、月度证券 `5,133` 个，daily bar required/returned `92,190/92,190`，missing/extra/unresolved 为 `0/0/0`。但完整性状态仍为 `FAIL_CLOSED`，因为存在 `1` 个 `PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH`，结构错误为 `STATUS_OUTSIDE_APPLICABILITY_SET`。
- 直接对本地 raw 做了只读重算：历史代码表在 `2025-02-05` 至 `2025-02-14` 使用 `300114.SZ`，从 `2025-02-17` 起切换为 `302132.SZ`；history-status 返回的 `302132.SZ / IS_SUSP_SEC=0` 却覆盖了整个月，因此前半月的 `8` 条当前代码状态行落在历史代码的 exact-day applicability 集合之外。缺失的旧码 pair 被正交易 fallback 解析为 `POSITIVE_TRADE_COUNT_ACTIVE=8`，但越界 status 行仍必须 fail-closed，不能静默当作旧码历史状态。
- 仓库已有 Owner 批准的 `300114.SZ -> 302132.SZ` identity event（旧码区间至 `2025-02-17`、新码自该日生效），但当前 capture completeness evaluator 仍按 provider 原始代码检查 exact-day applicability，没有把 Canonical/PIT identity bridge 应用到这层 status 证据。这是当前的身份连续性与采集适用性边界问题；本次只完成诊断，没有未经授权修改生产语义或把两套代码强行合并。

### 为什么会“跑几个月就停”

这是项目明确采用的 **fail-fast / fail-closed** 行为，不是每隔几个月随机崩溃：runner 会逐月推进，遇到此前没有被证据和规则覆盖的第一个新语义或结构问题，就停止并保留精确月份。此前的 `2023-02` 是跨月官方停牌事件传递缺陷；本次的 `2025-02` 是代码变更后的 provider status 与历史 exact-day universe 不一致。若跳过这些月份，后续的 78 月结果会把未证明的身份/适用关系混入数据，反而不符合验收要求。

### 当前最小解除要求

1. 不得把本次 blocker 归因于账号、端口或窗口，也不能重跑同一输入期待它随机通过。
2. 需要在既有 Owner 批准的 identity event 范围内，明确并实现一条可 replay 的 capture-layer 规则：如何把 `300114.SZ` 与 `302132.SZ` 的 provider status、exact-day code list、daily bar 和 request evidence 按有效区间绑定；不能用裸码替换、全局 alias 或忽略 `STATUS_OUTSIDE_APPLICABILITY_SET` 代替。
3. 先用已落盘 `2025-02` raw 做 retained replay 和新增边界测试；只有该月达到 `PASS`，再恢复在线 runner 继续 `2025-03`。receipt、coverage、materialization、ordinary-reader、幂等、冲突和 publication 仍不得提前执行。

## 最新运行检查点（2026-09-20，窗口退出后）

> 上述正式 `2025-02` 阻断已取代本节的 `2024-08` 中断观察；以下保留为历史检查点。

- 检查时没有匹配的 runner 进程；本地状态文件最后更新时间为 `2026-09-20T03:40:59.9365129Z`，其内容仍为 `status=RUNNING`、`phase=CAPTURE`，当前月为 `2024-08`、状态为 `CAPTURE_RUNNING`。因此这是一个**未写入终态的进程中断**，不是已确认的 provider 数据 blocker。
- 状态文件中已完成 `55/78` 个月 `PASS`，最近三个完成月份为 `2024-05`（provider calls `44`）、`2024-06`（`42`）、`2024-07`（`50`）；`2024-08` 尚未形成完整性结论。状态文件的 `failure` 为空。
- 仅凭落盘状态无法区分 runner 正常返回、未处理异常、窗口被关闭或系统终止；当前不能把原因编造成 API、账号或数据质量问题。旧的 `execution_summary.json` 仍描述早期 `2023-02` 检查点（`37` 个月），与本次 `55/78` 状态不一致，已标记为过期观察，不能作为当前结果依据。
- 本地安全启动脚本已补充退出码、异常类型和结束停留提示；它不会保存或输出密码。脚本本身位于本地忽略路径，不进入 GitHub。

### 重新启动要求

1. 先确认没有第二个 runner，再使用同一个本地安全启动脚本从现有状态恢复；`2024-08` 需重新取得并通过完整性结论，不能直接记为 PASS。
2. 启动脚本会再次要求输入密码；用户名、服务地址和端口继续从本机用户环境读取，密码只存在于当前进程及子进程，运行结束后清除。
3. 恢复成功后，先把新的脱敏状态（至少包含当前月、PASS 数、终态/失败字段和退出码）写入本报告，再继续后续月份；未完成 78/78 前不进入 receipt、coverage、materialization、ordinary-reader、idempotency、changed-content conflict 或 publication。

## 上一个正式恢复检查点（2026-09-18，已被最新状态替代）

- 已在同一安全 PowerShell 进程完成变量注入并正式执行 `--resume --retry-blocked`；当前没有启动第二个 runner。密码只在该进程及其子进程中存在，未写入文件、日志或 GitHub。
- `2023-02` 已由正式 runner 使用既有 raw 做 retained replay 并通过：required/returned `98,194/98,194`、missing/extra/structural `0/0/0`、`UNRESOLVED=0`、`SUSPENSION_NON_TRADING=173`；本次 replay 的 facade provider calls 为 `43`，没有重新请求该月网络数据。
- `2023-03` 已完成 fresh-provider capture PASS：`4,950` 个证券、`23` 个交易日、required/returned `113,421/113,421`、returned rows `113,421`，missing/extra/structural `0/0/0`、`UNRESOLVED=0`，provider calls `50`；分类为 `NOT_APPLICABLE_SESSION=278`、`POSITIVE_TRADE_COUNT_ACTIVE=23`、`SUSPENSION_NON_TRADING=151`。
- 当前 runner 已进入 `2023-04`，状态为 `CAPTURE_RUNNING`；尚未产生该月完整性结论。当前累计 capture PASS 为 `39/78`。
- 仍未进入 receipt、authoritative coverage、materialization、ordinary-reader、idempotency、changed-content conflict 或 publication；必须继续遵守首个新 blocker 即停止规则。

## 2023-02 诊断检查点（历史快照）

- 本次从既有 anchored raw evidence 做 retained replay。状态文件确认 `37/78` 个月 capture PASS；其中原始 `2020-03` 至 `2022-12` 是此前已完成的 fresh-provider capture，本次只是重放，不应重复计为新的在线采集。
- `2023-01` 已按 Owner 批准的最小范围接入一条官方停牌事实：`300114.SZ`，区间为半开区间 `[2023-01-12, 2023-02-02)`。该事实只作用于当前仍 `UNRESOLVED` 的目标 pair，不覆盖 provider 已给出的状态，不把零成交推断为停牌，也不引入 carry-forward 或第二 provider。
- `2023-01` retained replay 结果：monthly universe `4911`、交易日 `16`、required/returned bar pairs `78,403/78,403`、returned rows `78,403`；missing `0`、extra `0`、structural error `0`、`UNRESOLVED=0`。分类为 `NOT_APPLICABLE_SESSION=67`、`POSITIVE_TRADE_COUNT_ACTIVE=7`、`SUSPENSION_NON_TRADING=106`。事件实际闭合原先的 9 个 `300114.SZ` pair，evaluation/catalog 已保存事件 ID、区间和来源 URL，retained replay 会重新校验该对象。
- 官方原文来源：[CNINFO 2023-001（2023-01-12 起停牌）](https://static.cninfo.com.cn/finalpage/2023-01-12/1215580484.PDF)、[CNINFO 2023-007（2023-02-02 起复牌）](https://static.cninfo.com.cn/finalpage/2023-02-02/1215749576.PDF)、[深交所停复牌表（记录 300114.SZ 的 2023-01-12 停牌）](https://docs.static.szse.cn/www/certificate/secondb/GEMmsb/W020230202562529948780.html)。前两份公告证明区间起止，第三份是起始日的交易所交叉核验。
- 用户在本机同一进程完成安全变量注入后，`2023-02` 已实际完成 `44` 次 provider calls；因此此前“认证前停止”的旧检查点已被新结果取代，账号、口令、地址和端口仍未进入日志、文件或 GitHub。
- 原始脱敏请求证据：calendar `27cd797f-43d7-460d-ac8f-1390178427d0`、hist code list `f0db8a97-700a-49db-b464-996719a3c83f`、stock basic `e0979f16-5c56-4fc9-bd66-1b934e30e771`、history status `5f13940b-d241-4320-91d7-aa30a9d3bd01`、daily bar `f6192d4d-74c3-4896-a0a1-cfd3b8ff623f`；均为 provider `OK`，raw bytes 留在本地 anchored capture。
- `2023-02` 原始 completeness 为 `FAIL_CLOSED`：`4,926` 个证券、`20` 个交易日，required/returned `98,194/98,194`，missing/extra/structural `0/0/0`，但 `UNRESOLVED=1`；分类为 `NOT_APPLICABLE_SESSION=153`、`POSITIVE_TRADE_COUNT_ACTIVE=19`、`SUSPENSION_NON_TRADING=172`、`UNRESOLVED=1`。唯一未决 pair 是 `300114.SZ / 2023-02-01`：status member 为 `0×0` 空表，daily bar 恰缺该日，不能靠零活动推断停牌。
- 诊断确认这是本地 runner 的跨月事件传递缺陷：已批准事件 `[2023-01-12, 2023-02-02)` 本来覆盖 `2023-02-01`，但 runner 只在月份字符串等于 `2023-01` 时传入事件。已在本地未跟踪 runner 中改为按事件半开区间与月份相交传递；没有修改生产语义、没有放宽零成交规则，也没有重新请求 provider。用同一批已落盘 raw 做离线 retained replay 后，`2023-02` 为 `PASS`，required/returned 仍为 `98,194/98,194`，`UNRESOLVED=0`，`SUSPENSION_NON_TRADING=173`。
- 该离线 replay 只证明修正后的 runner 编排能够重放已取得证据，不等同于完整 runner 已推进到下个月；当前状态文件仍保留原始 `STOP(BLOCKED)`，下一次正式 `--resume --retry-blocked` 应先重放 `2023-02`，随后从 `2023-03` 继续真实请求。receipt、coverage、materialization 和 78 个月验收仍未完成。
- 远端 exact-head CI：最新文档头 `e15128f431d23f0c512d99d6e15d4d29185274b8` 的 CI run `35294943702`（`659`）在 Ubuntu 3.14、Windows 3.14、Windows 3.12 均为 `success`；GT-H3B run `35294943736`（`169`）按当前范围为 `skipped`。这只证明 GitHub 门禁通过，不改变 capture 尚未闭合 78 个月的事实。

## 启动前检查（已完成）

- 启动前的 Codex 主进程没有四个 TGW 安全变量，且未发现正在运行的匹配 runner；因此没有从错误的主进程盲目重跑。
- 随后已由可见的独立安全 PowerShell 窗口注入变量并启动正式 runner；当前进程已越过认证阶段，`2023-02` 和 `2023-03` 的结果已写回本地状态。

### 当前可执行下一步

1. 不要启动第二个 runner；让当前安全进程从 `2023-04` 继续逐月执行。后续月份仍须通过 exact-session、状态、生命周期、bar 集合和 replay 校验，遇到新语义/结构/权限 blocker 必须停下并记录，不能跳过月份。
2. 后续恢复若需重新启动，使用本地辅助脚本读取已保存的非密码变量，只在隐藏提示中输入密码；不要把值放进参数、脚本、截图、日志或聊天。
3. 78 个月 capture 全部通过后，才可继续 receipt、authoritative coverage、materialization、ordinary-reader、幂等和 changed-content conflict 验收；当前仍无 publication。

## 上一个执行检查点（2026-09-17，静态事件整改前的历史快照）

- 本地 runner 在安全变量可见的同一进程中已通过登录并恢复执行。`2020-01`、`2020-02` 为 retained replay，`2020-03` 至 `2022-12` 为 fresh provider；共 `36/78` 个月 capture PASS。当前尚未对这些月份做完整 finalize/receipt/publication 链路，因此“capture PASS”不等于整月最终验收 PASS。
- `2023-01` 使用 fresh provider：monthly universe `4911`、交易日 `16`、required/returned bar pairs `78,403/78,403`、returned rows `78,403`；missing `0`、extra `0`、structural error `0`。completeness 为 `FAIL_CLOSED`，因为 `UNRESOLVED=9`。

### 2023-01 未决 pair 与原始证据

9 个未决 pair 均为 `300114.SZ`：

| 交易日 | fallback snapshot request_id | rows | `num_trades` | 当前结论 |
|---|---|---:|---:|---|
| 2023-01-12 | `dbe180c6-7698-4326-8e43-04ae96c4d960` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-13 | `59ea6494-d606-41be-a8c9-c96d8c4525ef` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-16 | `0b2b19b3-0553-4a34-9b08-887a887acc87` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-17 | `d9665403-2b6a-44e0-b582-712bf047bba4` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-18 | `5c741edd-7a02-413b-88a7-d283a79718b5` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-19 | `f7e7ec77-fdf0-478c-a03f-d85f8daf0a9b` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-20 | `dae30f98-9da8-4978-9e27-9b1b7dae032c` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-30 | `89b006f1-e20e-4f4c-80f1-e0a636ac3659` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-31 | `bac0a57a-8cb9-4756-a7df-9c7fa741b454` | 331 | 全部 0 | UNRESOLVED |

对应的可复核事实：

- 当月 hist code list request `2d0f3cbe-99e4-4585-8c26-4cfcb3c69a0f` 有 `4911` 个代码并包含 `300114.SZ`。
- 当月 `stock_basic` request `14545323-755d-4369-ad68-6a83a140f351` 返回 `4910` 行；`300114.SZ` 不在 `MARKET_CODE` 中，因而本次没有把 LISTDATE/DELISTDATE 事实用于排除这些 pair。
- 当月 history-status request `beb1ade5-f2de-431f-9bf8-70e98e4428eb` 的 provider status 为 `OK`、总行数 `78,493`；其 `300114_SZ.parquet` 是 `0×0` 空 schema，不是一个可解释的停牌状态记录。
- 9 个 fallback snapshot 均是 exact-session 请求，均返回 `331` 行；原始快照的 `num_trades` 全为 `0`，且当前执行合同只把正交易次数作为 active fallback。零活动、空 status 和未返回状态不能被等同为停牌，也不能从相邻日期 carry-forward。

本次 `2023-01` 的分类计数为：`NOT_APPLICABLE_SESSION=67`、`POSITIVE_TRADE_COUNT_ACTIVE=7`、`SUSPENSION_NON_TRADING=97`、`UNRESOLVED=9`、`UNEXPLAINED_MISSING=0`、`EXTRA_RETURNED=0`、`PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH=0`。daily bar request `717d823d-1695-4b99-b090-1b575958a3bf` 的 required/returned pair set 相等，故这不是 bar 缺失或数量不一致问题。

## PM/Owner 在本次整改前需要决定的最小下一步（历史快照）

1. 提供 `300114.SZ` 在上述 9 个 exact-session 的 provider-owned 非交易/停牌状态事实，且能绑定到现有 raw capture 和 retained replay；或
2. 明确批准一个最小 zero-activity 语义/API 扩展，写明允许使用的 provider 字段、零值/空值含义、适用范围、持久化与 replay 校验；同时决定当月 stock_basic 不含历史代码时的身份/生命周期事实来源。

在上述决定前，工程侧不应修改 `0` 交易次数的含义、不应把空 status 判成停牌、不应添加第二来源、不应跳过 `2023-01`，也不应继续后续月份。决定落实后只重跑该月，确认 `UNRESOLVED=0` 后再继续。

## 执行范围与验收状态（本次重跑后）

- 已完成的是 `37/78` 个月 capture；`2023-01` 已通过官方静态事件 retained replay，当前 blocker 已移动到 `2023-02` 的本地安全凭据可见性边界，未进入该月 provider 请求。
- 本地 QA：本次新增事件边界与 retained replay 回归已通过；完整 QA 数字以本次提交前最后一次运行结果为准，远端 CI 以新 commit 的 checks 为准。
- 78 个月的 receipt、authoritative coverage、bounded materialization、ordinary-reader、idempotency 和 changed-content conflict 尚未全部形成结论；因此不能称项目已完成，也没有 publication。
- 原始 payload、ledger、物化文件、账号/身份、网络地址、SDK/runtime 和凭证均未进入 GitHub；本文件只保留脱敏计数、request id、hash/规则引用、官方来源 URL 和阻断事实。
- 范围外的 Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1、baseline、策略和多源 reconciliation 仍未执行。

## 先前检查点（历史留存，已被后续执行替代）

## 已完成

- 基线：`main@ad2ad528d3ffec1269772084f0860c8224e632d2`；范围：2020-01 至 2026-06，共 78 个日历月。
- PM 已批准最小生命周期修复：复用已验证 security-master 的 `stock_basic.DELISTDATE`；仅当交易日 `session >= DELISTDATE` 时分类为 `NOT_APPLICABLE_SESSION`。不把前一日停牌 carry-forward，不用第二数据源，不跳过未决 pair。
- month-completeness/applicability 规则已升级到 v4；`DELISTDATE` 由 verified normalized security-master 进入 identity view，并只在实际排除 pair 时写入 evaluation 和 retained replay。既有 `LISTDATE`、PIT、raw closure 与 finalize 约束保持不变。

| 月份 | capture 结果 | required/returned | unresolved | 实际使用的生命周期事实 |
|---|---|---:|---:|---|
| 2020-01 | PASS（retained replay，未 finalize） | 59,930 / 59,930 | 0 | 既有 5 条 LISTDATE 事实 |
| 2020-02 | PASS（retained replay，未 finalize） | 75,463 / 75,463 | 0 | `600240.SH -> 2020-02-05` 的 DELISTDATE |

2020-02 的分类为 `NOT_APPLICABLE_SESSION=238`、`SUSPENSION_NON_TRADING=79`、
`POSITIVE_TRADE_COUNT_ACTIVE=20`、`UNRESOLVED=0`、`missing=0`、`extra=0`、
`structural=0`。原先 `600240.SH / 2020-02-05` 的缺状态 pair 因已验证 DELISTDATE 正好落在该交易日，按获批规则闭合；它不是把 02-03/02-04 状态外推成 02-05 停牌。

## 上一个检查点的阻断（历史快照）

执行器按 fail-fast 顺序到达 2020-03，但当前 Codex 执行进程看不到安全环境变量
`TGW_USERNAME`、`TGW_PASSWORD`、`TGW_SERVER_VIP`、`TGW_SERVER_PORT`，所以在 provider 登录前停止。
这是本地执行环境阻断，不是 2020-03 的 provider 数据结论；变量值没有写入聊天、本地跟踪文件或 GitHub。

项目管理者下一步只需在本机安全配置这四个变量，然后使用现有保留状态恢复执行。恢复后仍须逐月
capture PASS；出现新的 API、schema、语义、PIT 或身份 blocker 时立即停止并记录 exact month/pair，
不得跳过、carry-forward 或推断。

## 上一个检查点的本地 QA 与边界（历史快照）

- focused：`67 passed`。
- full offline pytest：`1874 passed, 3 skipped`。
- `ruff check src tests`、`ruff format --check src tests`、`mypy src/ashare_state`：通过。
- 2020-03 至 2026-06 的 76 个月未运行；尚未形成 78 个月的 receipt、authoritative coverage、
  materialization、ordinary-reader、idempotency 或 changed-content conflict 完成结论。
- 原始 payload、ledger、物化文件、账号/身份、网络地址、SDK/runtime 和凭证均未进入 GitHub；
  本记录只保留脱敏计数、规则版本和阻断原因。
- 范围外的 Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1、baseline、策略与多源
  reconciliation 均未执行。

对应机器记录见同目录 [`cr7_issue76_history_build_20260916.json`](cr7_issue76_history_build_20260916.json)。

