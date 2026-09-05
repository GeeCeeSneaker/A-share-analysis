# A-share-analysis：PR #9 关闭与受控线上身份确认工作要求

> Date: 2026-09-05  
> Reviewer baseline: `main@f38e77ff2cbcf040837bc1c15504f847e1cfb1d8`  
> Closed PR: #9 `P0-M-1B.0 harden positive production identity gates`  
> Current stage: controlled online bootstrap -> human confirmation -> separate identity-freeze governance commit  

---

## 0. Reviewer 裁决

PR #9 已完成最终复审并合并。

最终关闭事实：

```text
PR #9 final head                  23bd8b37afd7e64982f44a665fb1f071d89fa9c6
PR #9 merge commit                f38e77ff2cbcf040837bc1c15504f847e1cfb1d8
exact config identity contract    VERIFIED / CLOSED
bootstrap exact candidate gate    VERIFIED / CLOSED
config whitespace adversarial     VERIFIED / CLOSED
bootstrap whitespace adversarial  VERIFIED / CLOSED
Trial non-freezable boundary       VERIFIED / CLOSED
final-head CI                      SUCCESS
production_account.yaml            EMPTY / KEEP
AmazingData production identity    NOT YET FROZEN
Provider capability approval       BLOCKED
```

PR #9 的合并只关闭仓库内 production identity gate 与 bootstrap safe-projection correctness，不代表：

- 已获得正式生产账号身份；
- 已完成正式 Production B1-B7；
- 已完成 Data Sufficiency Matrix；
- 已形成 Provider verdict；
- 已批准 AmazingData 为生产数据源；
- 已批准 2020+ 正式回填。

---

## 1. 当前唯一主线

严格按以下顺序执行：

```text
T1  controlled Windows online bootstrap
    -> scrubbed IDENTITY_CANDIDATE only
    -> Reviewer/Owner inspect safe projection

T2  human confirmation
    -> confirm exact scrubbed identity belongs to project production account

T3  separate identity-freeze governance PR
    -> exact allowlist config
    -> CI / review / merge

T4  formal Production B1-B7
    -> one governed Production run

T5  formal verdict + Data Sufficiency Matrix
    -> Provider capability decision

T6  only after Provider approval
    -> 2020-01-01 -> current backfill
```

禁止跳步。

---

## 2. T1 — Controlled Windows online bootstrap

### 2.1 环境前提

只允许在受控 Windows 环境、官方 AmazingData SDK/runtime 已安装且本地离线 preflight 已通过的机器执行。

执行前必须确认：

1. 工作副本基于 clean `main`，至少包含 `f38e77ff2cbcf040837bc1c15504f847e1cfb1d8`；
2. tracked files 无未审查本地修改；
3. `configs/production_account.yaml` 三个字段仍为空；
4. credentials 只存在于本地进程环境变量或本地 `.env`；
5. `.env`、用户名、密码、Token、真实 host、真实 port、raw profile、raw SDK stdout/stderr 均不得进入 Git、PR、Issue 或聊天交接材料；
6. 不得把 credentials 作为 CLI 参数；
7. 不得在 GitHub Actions / 公共 CI 中执行真实账号 online bootstrap。

### 2.2 允许的入口

使用仓库唯一受控入口：

```text
uv run python scripts/spike/production_account_bootstrap.py
```

如需落盘，优先输出到仓库外的本地临时路径；在人工确认内容确实只有 scrubbed projection 之前，不得复制进仓库：

```text
uv run python scripts/spike/production_account_bootstrap.py --output <LOCAL_PATH_OUTSIDE_REPO>/production_account_bootstrap.json
```

不得绕过该入口直接把 doctor raw result 或 SDK 原始日志作为正式身份材料。

### 2.3 T1 唯一可接受的正向结果

只有以下状态可以进入人工确认：

```text
bootstrap_status             IDENTITY_CANDIDATE
sdk_state                    SDK_INSTALLED
AUTHENTICATED                YES
QUERY_READY                  YES
ACCOUNT_PROFILE.profile_id   UNKNOWN_<12 lowercase hex>
profile_parsed               true
entitlement_verified         true
production_identity_status   NOT_FROZEN
config_written               false
human_confirmation_required  true
```

注意：`IDENTITY_CANDIDATE` 仍不是 Production truth，只是“允许人工确认的脱敏候选”。

以下任一状态都必须 STOP，不得冻结配置：

```text
TRIAL_ACCOUNT_NOT_FREEZABLE
NOT_TESTABLE_ACCOUNT
NOT_TESTABLE_SDK
NOT_TESTABLE_PROFILE
NOT_TESTABLE_ENTITLEMENT
NOT_QUERY_READY
ERROR
```

特别地，Trial、未知格式 identity、带前后空白 identity、legacy/fake identity 都不得通过人工解释升级为 production candidate。

---

## 3. T1 允许提交的证据

Reviewer 只接受 bootstrap 的 scrubbed safe projection。

允许字段包括当前 `production_account_bootstrap.v1` 输出中的：

- checked_at；
- platform / Python / SDK ABI；
- SDK/package/runtime version；
- runtime_verdict；
- NETWORK_REACHABLE；
- AUTHENTICATED；
- QUERY_READY；
- scrubbed `account_profile_id`；
- profile_kind / profile_parsed / entitlement_verified；
- numeric permission codes；
- safe numeric quota fields；
- production_identity_status；
- bootstrap_status；
- config_written；
- human_confirmation_required；
- sdk_stderr_observed boolean。

严禁提交：

- TGW_USERNAME；
- TGW_PASSWORD；
- Token / credential；
- 真实 host / port；
- raw SDK output；
- raw profile payload；
- raw stderr/stdout；
- 本地 `.env`；
- 能反推出上述秘密的截图或日志。

如果对输出是否安全存在任何疑问，默认不提交，先本地人工审查。

---

## 4. T2 — Human confirmation

只有 T1 得到 `IDENTITY_CANDIDATE` 后才进入本阶段。

Owner/Reviewer 必须在 Git 之外依据本地账号事实确认：

```text
该 exact UNKNOWN_<12hex> scrubbed identity
确实来自本项目计划使用的正式 AmazingData 账号
```

确认只针对 scrubbed identity 本身，不需要也不得把真实用户名、host、port、密码、Token 带入仓库。

人工确认结果只有两种：

```text
CONFIRMED
REJECTED / UNPROVABLE
```

`REJECTED / UNPROVABLE` 时保持 config 为空，回到账号/环境核查；不得继续 T3。

---

## 5. T3 — Separate identity-freeze governance PR

只有人工确认 `CONFIRMED` 后，才能新建独立分支/PR 修改：

```yaml
production_account_profile_id: "UNKNOWN_<12 lowercase hex>"
confirmed_at: "<timezone-aware ISO-8601>"
confirmed_by: "<safe human/operator marker>"
```

要求：

1. profile id 必须与 T1 人工确认的 exact value 字节级一致；
2. 禁止 trim、case-normalization、alias、手工改写 digest；
3. `confirmed_at` 必须有 timezone；
4. `confirmed_by` 只使用安全的人类/操作员标记，不得包含 credential/username/host/port/token 等内容；
5. 不得增加其它 config keys；
6. 同批更新 `docs/DEVLOG.md`、`docs/project/DEVELOPMENT_MANAGEMENT.md` 和本阶段证据引用；
7. 必须通过 focused identity tests 与完整三平台 CI；
8. Reviewer 必须独立核对 config exact value 与 T1 scrubbed candidate；
9. identity-freeze PR 合并前，Formal Production B1-B7 仍禁止执行。

---

## 6. T4 之后的 gate

identity-freeze governance PR 合并且最终 CI 通过后，才允许：

```text
Formal Production B1-B7
```

正式 B1-B7 必须绑定同一受治理 Production run，不得使用 Trial、bootstrap、offline preflight 或历史 smoke 结果替代。

B1-B7 完成后，才进入：

```text
formal verdict
+ Data Sufficiency Matrix
+ Reviewer Provider capability decision
```

只有 Provider capability 明确批准后，才允许 2020-01-01 -> current 正式回填。

---

## 7. 本轮 Developer 任务

当前只执行 T1；不要同时提交 identity freeze。

交付物：

```text
1. controlled online bootstrap 已执行的说明
2. scrubbed production_account_bootstrap.v1 safe projection
3. bootstrap_status / exit code
4. 候选 scrubbed account_profile_id（仅当 IDENTITY_CANDIDATE）
5. 明确声明 credentials/raw logs/raw profile 未进入 Git
6. configs/production_account.yaml 仍为空
```

开发人员完成 T1 后停止，等待 Reviewer/Owner 对 scrubbed candidate 做人工确认和 T2 裁决。

不得自行把 candidate 写入 `configs/production_account.yaml`。

---

## 8. Reviewer 下一次审查入口

收到下一次“仓库已更新”后，Reviewer 默认检查：

1. 当前 `main` / active branch SHA；
2. 是否只提交 scrubbed bootstrap evidence；
3. 是否存在 credential/endpoint/raw-log 泄漏；
4. bootstrap 是否真的是受控 online run，而非 offline/Trial/smoke；
5. `bootstrap_status` 是否为 `IDENTITY_CANDIDATE`；
6. candidate 是否满足 exact `UNKNOWN_<12 lowercase hex>` contract；
7. auth / query-ready / entitlement 是否完整；
8. config 是否仍为空；
9. T1 PASS 时才进行 human confirmation；
10. T2 CONFIRMED 后才下发独立 identity-freeze PR 工作要求。

当前状态：

```text
PR #9                            MERGED / CLOSED
Identity contract                VERIFIED / FREEZE
Controlled online bootstrap      AUTHORIZED / NOT YET REVIEWED
Human identity confirmation      NOT YET DONE
Production identity freeze       BLOCKED
Formal Production B1-B7          BLOCKED
Data Sufficiency Matrix          BLOCKED
AmazingData capability approval  BLOCKED
2020+ backfill                   BLOCKED
```
