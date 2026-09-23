# A1：分钟物理布局基准与选型建议（Issue #79）

状态：**基准可复现、资源门禁通过；物理选型等待 PM/Owner 冻结**

## 运行边界

- runner：`scripts/architecture/benchmark_minute_layout.py`，单文件、一次性合成基准，不是框架；
- 数据：确定性 synthetic only，`provider_calls=0`，没有读取 retained raw/canonical，也没有读取账号或环境变量；
- 形状：4,500 个 security × 240 个分钟/日 = 1,080,000 行/日；20 日 = 21,600,000 行/open month；
- 配置：L0/L1/L2 × `uuid_string`/`fixed16`/`int64`，共 9 组；
- workload：daily ingest、5-day catch-up、month compaction、W4 full-market one-minute、W5 security history、W6 100/500-security range、W7 groupby、W8 identity join、W9 compaction overlap。

完整 JSON/Markdown 原始结果与本文件同批提交；本次结果状态明确分为：

- `resource_gate_status=PASS`：所有资源门禁满足；
- `status=REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION`：尚未把物理布局/键表示铸造成不可变架构决定。

## 资源门禁结果

| 指标 | 结果 | 门禁 |
|---|---:|---:|
| 配置数 | 9/9 | L0/L1/L2 × 3 key reps |
| 每配置行数 | 21,600,000 | 20M–30M open-month shape |
| 最大 daily-ingest RSS | 0.2585 GiB | < 2 GiB |
| 最大 month-compaction RSS | 0.2636 GiB | < 4 GiB |
| 最大查询 RSS | 0.3352 GiB | 作为附加观察 |
| short/long daily elapsed 最大比值 | 1.1226 | ≤ 1.25 |
| closed-month rewrite | 0/18 个 daily append 检查 | 必须为 0 |
| Snapshot/ReadModel full fact copy | 0/9 | 必须为 0 |

所有指标均为本机合成数据观测，不外推为生产 provider 性能保证。

## 关键对比（秒；同一机器、同一 runner）

| key | layout | daily short/long | 5-day catch-up | compaction | W4 1m cross-section | W5 security history | W6 100/500 range | W7 groupby | W8 identity join |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| UUID string | L0 | 7.564 / 7.869 | 38.570 | 18.660 | 0.097 | 0.096 | 0.400 / 0.429 | 1.059 | 1.298 |
| UUID string | L1 | 9.177 / 9.250 | 46.493 | 23.970 | 0.580 | 0.559 | 1.153 / 1.364 | 1.684 | 1.805 |
| UUID string | L2 | 8.258 / 8.392 | 41.998 | 25.467 | 0.523 | 0.382 | 0.930 / 1.150 | 1.450 | 1.525 |
| fixed16 | L0 | 6.152 / 6.287 | 32.301 | **14.421** | 0.074 | 0.115 | 0.365 / 0.386 | 0.959 | 1.095 |
| fixed16 | L1 | 11.086 / 12.221 | 51.422 | 23.279 | 0.620 | 0.847 | 1.169 / 1.332 | 1.698 | 1.734 |
| fixed16 | L2 | 7.112 / 7.984 | 36.242 | 20.387 | 0.531 | 0.777 | 1.031 / 1.130 | 1.576 | 1.550 |
| INT64 | L0 | 7.189 / 7.252 | 36.316 | 15.548 | **0.075** | **0.068** | **0.068 / 0.081** | 1.011 | **0.734** |
| INT64 | L1 | 8.526 / 8.658 | 35.919 | 22.461 | 0.485 | 0.396 | 0.408 / 0.478 | **1.355** | 1.191 |
| INT64 | L2 | 7.270 / 7.460 | 36.613 | 19.575 | 0.585 | 0.424 | 0.455 / 0.499 | 1.541 | 1.240 |

Physical observation: L0 creates 20 fragment files and 360 row groups per configuration; L1/L2 create 320 fragment files and 5,760 row groups. For the tested time-only W4, matching files were 1 for L0 versus 16 for L1/L2. For one-security history, L1/L2 matched one bucket per day (20 files), but this run did not expose reliable DuckDB row-group touch counts. For 100/500-security all-history range scans, the selected keys span all 16 buckets, so L1/L2 matched 320 files; no bucket advantage should be claimed for that workload.

## Evidence-based proposal, not yet frozen

**Proposed default: L0 + INT64 physical key, with stable UUID identity mapping in the manifest/dimension.**

Reasoning:

1. L0 dominates the tested shape on file count, daily bytes, W4 time-range matching files, catch-up/compaction simplicity and avoidance of 16-way file amplification.
2. INT64 L0 is materially fastest for the security-range and identity-join observations while staying within the same resource gates; W4 is tied with fixed16 at this scale.
3. This proposal does not change governance identity: UUID remains the stable logical identity, and the INT64 mapping must be PIT-bound, immutable for a revision and included in the manifest seal.

**Alternative if identity mapping governance is rejected:** fixed16 + L0. It has the fastest L0 daily append and compaction in this run, but its range/identity-join observations were slower than INT64.

The proposal is not an automatic PM decision. The benchmark does not prove that L0 is optimal for every future security/time workload, nor does it freeze provider numeric types, row-group/file target sizes or bucket count. A PM approval or a changed weighting must be recorded before the daily vertical refactor.

## Measurement limitations and required follow-up

- DuckDB profiling on the installed runtime did not emit a usable row-group touch count; result fields therefore keep `row_groups_touched=null` rather than inventing a number.
- `files_with_matching_rows` is a matching-output observation, not a kernel I/O counter. `bytes_read_estimate` is the candidate Parquet byte set, not exact physical bytes read.
- Numeric columns are synthetic placeholders; no provider unit/precision decision is implied.
- W9 observed overlap and wrote a separate open-day compaction copy; source fragments remained immutable. This is a concurrency observation, not the final atomic manifest-switch implementation.

Before A1 can be marked fully PASS, the project manager should either accept these measurement limits as sufficient for the bounded vertical slice or authorize a small follow-up instrumentation change that records row-group/file-touch metrics on the target DuckDB version. No 32-bucket experiment is justified by this run.

## Reproduction and integrity

Portable command (output directory must be disposable and empty):

```text
python scripts/architecture/benchmark_minute_layout.py --output <disposable-output>
```

The run used the defaults in the script. Local evidence hashes before upload:

- runner SHA-256: `CDC182A1ED518747BD1693259EE6D6D5443FDCA246820EEAB290C27CD53D20BB`;
- benchmark JSON SHA-256: `8B10B1B8A4995AC31652276CC31A1ADC083033131381A5785BBFBC461AB2B4FD`;
- benchmark Markdown SHA-256: `3D8B9FA93044B9A6825876AA96A90347BF5928F657865E5AC4654023DD2820AB`.

These hashes identify local evidence only; the GitHub commit carrying the files is the authoritative hand-off reference after upload.

## Next gate

Keep PR #77 Draft and Issue #76 open. Do not resume M1/M2/M3, do not reacquire provider data, and do not migrate the retained 78-month evidence until A0/A1 are reviewed and the scheduler authorizes one bounded `daily_bar` Canonical → logical Snapshot → DuckDB facade vertical slice with net deletion of duplicate fact paths.

