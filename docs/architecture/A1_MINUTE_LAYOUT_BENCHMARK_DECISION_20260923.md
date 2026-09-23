# A1：分钟物理布局基准与选型建议（Issue #79）

状态：**基准可复现、资源门禁通过；物理选型等待 PM/Owner 冻结**

## 运行边界

- runner：`scripts/architecture/benchmark_minute_layout.py`，单文件、一次性合成基准，不是框架；
- 数据：确定性 synthetic only，`provider_calls=0`，没有读取 retained raw/canonical，也没有读取账号或环境变量；
- 形状：4,500 个 security × 240 个分钟/日 = 1,080,000 行/日；20 日 = 21,600,000 行/open month；
- 配置：L0/L1/L2 × `uuid_string`/`fixed16`/`int64`，共 9 组；
- workload：daily ingest、5-day catch-up、month compaction、W4 full-market one-minute、W5 security history、W6 100/500-security range、W7 groupby、W8 identity join、W9 compaction overlap；W4-W8 均分别在 open fragments 与 closed-month compacted artifacts 上执行。

本次修正版 runner 在 W5/W6 的 L1/L2 查询构造 `read_parquet` 之前，先依据稳定 bucket 映射选择候选文件；W4 全市场横截面和 W7/W8 仍读取该 artifact set 的全部相关文件。结果中的 `files_available` 是实际传入 DuckDB 的候选文件数，`all_files_available` 是该 artifact set 的完整文件数。为区分调度抖动，本地对同一 exact runner 做了一次有界确认重跑；本文件及 GitHub 结果文件绑定确认重跑，未继续重复。

完整 JSON/Markdown 原始结果与本文件同批提交；本次结果状态明确分为：

- `resource_gate_status=PASS`：所有资源门禁满足；
- `status=REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION`：尚未把物理布局/键表示铸造成不可变架构决定。

## 资源门禁结果

| 指标 | 结果 | 门禁 |
|---|---:|---:|
| 配置数 | 9/9 | L0/L1/L2 × 3 key reps |
| 每配置行数 | 21,600,000 | 20M–30M open-month shape |
| 最大 daily-ingest RSS | 0.2776 GiB | < 2 GiB |
| 最大 month-compaction RSS | 0.2828 GiB | < 4 GiB |
| 最大查询 RSS | 0.3200 GiB | 作为附加观察 |
| short/long daily elapsed 最大比值 | 1.1580 | ≤ 1.25 |
| closed-month rewrite | 0/18 个 daily append 检查 | 必须为 0 |
| Snapshot/ReadModel full fact copy | 0/9 | 必须为 0 |

所有指标均为本机合成数据观测，不外推为生产 provider 性能保证。

确认说明：同一格式化 exact runner 的第一次完整运行只因 `uuid_string/L1` 的一次性 short/long 耗时比 `1.4325` 触发 FAIL；没有内存、闭月重写或 fact-copy 失败。按有界确认规则仅重跑一次，确认结果即本节及 GitHub 结果文件绑定的 `PASS`，不再继续重试。

## 关键对比（秒；同一机器、同一 runner）

| key | layout | daily short/long | 5-day catch-up | compaction | W4 1m cross-section | W5 security history | W6 100/500 range | W7 groupby | W8 identity join |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| UUID string | L0 | 8.4827 / 8.8287 | 43.1305 | 20.7248 | 0.0833 | 0.0899 | 0.3816 / 0.4784 | 1.0651 | 1.2651 |
| UUID string | L1 | 9.5616 / 9.2932 | 57.6576 | 29.1405 | 0.6743 | 0.0652 | 1.2547 / 1.3324 | 2.0219 | 2.3458 |
| UUID string | L2 | 9.9691 / 8.6092 | 58.2681 | 23.4987 | 0.7148 | 0.1019 | 1.4899 / 1.4799 | 1.9236 | 2.0726 |
| fixed16 | L0 | 8.7676 / 7.6249 | 36.4274 | 16.5500 | 0.0706 | 0.1384 | 0.3736 / 0.4649 | 0.8941 | 0.9176 |
| fixed16 | L1 | 12.9780 / 12.6703 | 58.0334 | 27.4089 | 0.5692 | 0.0884 | 1.2041 / 1.4351 | 2.0736 | 2.3931 |
| fixed16 | L2 | 8.6143 / 9.5644 | 43.8810 | 25.4802 | 0.7064 | 0.0861 | 1.1903 / 1.3782 | 1.8174 | 1.8215 |
| INT64 | L0 | 11.5859 / 11.8324 | 57.6031 | 24.6025 | 0.1099 | 0.1208 | 0.0949 / 0.0934 | 1.0168 | 0.7563 |
| INT64 | L1 | 9.0375 / 9.2210 | 45.9509 | 25.6301 | 0.6215 | 0.0673 | 0.5416 / 0.6826 | 1.7636 | 1.4690 |
| INT64 | L2 | 8.9175 / 9.5613 | 46.4022 | 26.1318 | 0.6532 | 0.0688 | 0.5587 / 0.6888 | 1.9335 | 1.5300 |

Physical observation: open fragments contain 20 files/360 row groups for L0 and 320 files/5,760 row groups for L1/L2; closed compaction contains 1 file/340 row groups for L0 and 16 files/640 row groups for L1/L2. W4 full-market matched 1 file for L0 versus 16 for L1/L2 in both artifact sets. For W5 one-security history, L1/L2 selected one stable bucket per day before `read_parquet` (20 open files versus 320 total; 1 closed file versus 16 total); the candidate byte set fell from roughly 304–324 MiB for L0 to roughly 26–34 MiB for L1/L2. For 100/500-security ranges, the selected keys span all 16 buckets, so L1/L2 selected all 320 open or 16 closed files; no bucket reduction should be claimed there. DuckDB did not expose reliable row-group touch counts.

## Evidence-based proposal, not yet frozen

**Provisional candidate: L1 + fixed16 UUID physical key, with stable UUID governance identity.**

Reasoning:

1. L1/L2 manifest-aware W5 candidate selection reduces the single-security history candidate byte set by roughly 10–12× on both open and closed artifacts; this is the one measured workload with a material research benefit over L0.
2. L2 has no demonstrated advantage over L1 for the approved workloads, so security-first ordering is not justified; L1 keeps time-first ordering and only the required 16-way bucket layout.
3. fixed16 satisfies the corrected resource/workload evidence without introducing a new INT64 surrogate mapping, PIT contract and durable identity dimension. Stable UUID remains the governance identity.

**Simplest alternative:** fixed16 + L0. It remains valid if the project values the smaller file/layout surface over the measured W5 candidate-byte reduction. INT64 is not authorized by this evidence alone: its query observations are faster in places, but fixed16 satisfies the gates without the additional durable mapping contract.

The proposal is not an automatic PM decision. It does not freeze provider numeric types, row-group/file target sizes or a 32-bucket variant. PM must decide whether the measured W5 reduction justifies the 16-way layout; only then can the physical choice be frozen before the daily vertical refactor.

## Measurement limitations and required follow-up

- DuckDB profiling on the installed runtime did not emit a usable row-group touch count; all result fields keep `row_groups_touched=null` rather than inventing a number.
- `files_with_matching_rows` is a matching-output observation, not a kernel I/O counter. `bytes_read_estimate` is the candidate Parquet byte set, not exact physical bytes read.
- The corrected runner records both `open_fragments` and `closed_compacted` query sets. W5/W6 L1/L2 file selection is a deterministic manifest-candidate construction in the runner, not a claim that DuckDB independently discovered those files through runtime pruning.
- Numeric columns are synthetic placeholders; no provider unit/precision decision is implied.
- W9 observed overlap and wrote a separate open-day compaction copy; source fragments remained immutable. This is a concurrency observation, not the final atomic manifest-switch implementation.

Before A1 can be marked fully PASS, the project manager should either accept these measurement limits as sufficient for the bounded vertical slice or authorize a small follow-up instrumentation change that records row-group/file-touch metrics on the target DuckDB version. No 32-bucket experiment is justified by this run.

## Reproduction and integrity

Portable command (output directory must be disposable and empty):

```text
python scripts/architecture/benchmark_minute_layout.py --output <disposable-output> --runner-git-head <exact-committed-runner-head>
```

The run used the defaults in the script. Local evidence hashes before upload:

- exact committed runner Git head: `f940ec782a816e6b63d6a13c462af5441e8256c0`;
- exact committed runner blob SHA: `f91f891ac2dca782603753685c4106308626d15f`;
- runner source SHA-256 recorded in the result: `ad535f18c5de11b154a7291ad2cb4ac0c3384f15acaf2d35c6cfe644384f86d8`;
- benchmark JSON SHA-256: `CD094B2C6509B34405A317BC0CF0D725603BDAB0D323827458CEBFF3DDBD783A`;
- benchmark Markdown SHA-256: `81B8EB85CE5B151B328929DE4BB474BDD402EFBFE25D58E695912057B6D30E6A`.

These hashes identify local evidence only; the GitHub commit carrying the files is the authoritative hand-off reference after upload.

## Next gate

Keep PR #77 Draft and Issue #76 open. Do not resume M1/M2/M3, do not reacquire provider data, and do not migrate the retained 78-month evidence until A0/A1 are reviewed and the scheduler authorizes one bounded `daily_bar` Canonical → logical Snapshot → DuckDB facade vertical slice with net deletion of duplicate fact paths.
