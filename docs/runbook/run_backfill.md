# Runbook — 历史回补（Backfill）

> 前提：Spike 核心事实全 GO + Source Policy CANDIDATE 就绪。
> **禁止跳级**：任务书 §16 的 Stage A→D 放量纪律。

## Stage A：20 证券 × 60 交易日

验证目标：Raw → Canonical → Security ID → Trend → Aggregate → Artifact →
Publish → Exact Replay 全链路。

## Stage B：100 证券 × 2 年

验证目标：rolling / revision / snapshot / artifact patch replay / performance。

## Stage C：ALL_A × 1 个月

验证目标：coverage / memory / partition / file size / runtime。

## Stage D：2014/2015 → 当前（全历史）

**只有 A/B/C 全部通过后才执行。**

## 运行纪律

1. 每阶段开始前：`uv run ashare provider-doctor`（账号画像确认）
2. 每阶段结束：检查 `meta_ingest_run` 无失败残留；snapshot 状态机走完
   DATA_VALIDATED；发布走 publish 事务
3. 流量预算：对照 ACCOUNT_PROFILE 的周流量上限，跨周分批
4. 断点续跑：回补任务幂等（同参数重跑跳过已落盘日期，依据
   content_hash 对账）
5. 任何 Provider 错误按错误层分类记录，不许吞掉

## 回补后的可用时间口径（PIT 纪律）

历史回补无法还原当年真实发布时刻：`available_at` 使用版本化的
CONSERVATIVE_ASSUMED 规则（configs/base.yaml + provider_verification §5），
与 OBSERVED（真实观测时刻）严格区分。
