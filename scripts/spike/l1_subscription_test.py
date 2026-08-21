"""L1 REALTIME subscription test (task book section 1.2 + 17).

CRITICAL DISTINCTION (task book 1.2):
    REALTIME_L1_SUBSCRIPTION      SubscribeData.register(period=snapshot)
    HISTORICAL_SNAPSHOT_QUERY     MarketData.query_snapshot(...)
These are SEPARATE capabilities with SEPARATE verdicts. The 2026-08-21
DENIED evidence was for the HISTORICAL path only; the realtime path is
UNTESTED until this script runs during trading hours.

Usage (MUST run during trading hours, Mon-Fri 09:15-11:30 / 13:00-15:05):
    uv run python scripts/spike/l1_subscription_test.py --stage 1
    uv run python scripts/spike/l1_subscription_test.py --stage 5
    uv run python scripts/spike/l1_subscription_test.py --stage 20
    uv run python scripts/spike/l1_subscription_test.py --stage 100

Stages (task book 1.2): 1 -> 5 -> 20 -> 100 stocks.

Results land in data/spike/results/l1_subscription_<stage>.json with:
    provider_event_time / received_at / latency / duplicates /
    out-of-order / cumulative volume/amount / bid-ask depth presence /
    up-down limit fields / trading phase / unsubscribe / reconnect.

Entitlement note (task book 17): the trial account's 100-subscription /
0.2MB/s / 10GB-week limits are ACCOUNT entitlements, NOT platform
capacity. No Phase-2 capacity conclusions may be drawn from this test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

RESULTS = Path("data/spike/results")
RESULTS.mkdir(parents=True, exist_ok=True)

# 20-stock capture sample (task book 17): SH/SZ/BJ, high/low liquidity,
# near-limit names refined on the run day from the live code list.
DEFAULT_STAGES = [1, 5, 20, 100]


def load_env(path: Path = Path(".env")) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.startswith("TGW_")}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def pick_sample_stocks(code_list: list[str], stage: int) -> list[str]:
    """Deterministic sample: spread across SH/SZ/BJ suffixes."""
    sh = [c for c in code_list if c.endswith(".SH")]
    sz = [c for c in code_list if c.endswith(".SZ")]
    bj = [c for c in code_list if c.endswith(".BJ")]
    if stage <= len(sh):
        pool = sh[:stage]
    else:
        pool = sh[: stage // 3] + sz[: stage // 3] + bj[: (stage - 2 * (stage // 3))]
        # top up deterministically if BJ list is short
        i = 0
        while len(pool) < stage and i < len(sz):
            pool.append(sz[i])
            i += 1
    return pool[:stage]


def main() -> int:
    parser = argparse.ArgumentParser(description="L1 realtime subscription test")
    parser.add_argument("--stage", type=int, default=1, help="1/5/20/100 stocks")
    parser.add_argument("--duration-seconds", type=int, default=60, help="how long to collect")
    args = parser.parse_args()

    env = load_env()
    if not all(
        env.get(k) for k in ("TGW_USERNAME", "TGW_PASSWORD", "TGW_SERVER_VIP", "TGW_SERVER_PORT")
    ):
        print("missing TGW_* env; fill .env first")
        return 2

    report: dict[str, object] = {
        "capability": "REALTIME_L1_SUBSCRIPTION",
        "distinct_from": "HISTORICAL_SNAPSHOT_QUERY (DENIED 2026-08-21, separate verdict)",
        "stage": args.stage,
        "started_at": datetime.now(UTC).isoformat(),
        "trading_hours_check": datetime.now().strftime("%H:%M"),
    }

    # trading-hours sanity (Asia/Shanghai): warn but allow override for study
    now_local = datetime.now()
    hhmm = now_local.hour * 100 + now_local.minute
    in_session = (915 <= hhmm <= 1130) or (1300 <= hhmm <= 1505)
    report["in_trading_session"] = in_session
    if not in_session:
        print("WARNING: outside trading hours - subscription may return nothing")
        print("(run Mon-Fri 09:15-11:30 / 13:00-15:05 for a meaningful verdict)")

    try:
        # N813: manual idiom
        import AmazingData as ad  # noqa: N813
    except ImportError:
        report["status"] = "NOT_TESTABLE_SDK_MISSING"
        _flush(report, args.stage)
        return 2

    try:
        ad.login(
            username=env["TGW_USERNAME"],
            password=env["TGW_PASSWORD"],
            host=env["TGW_SERVER_VIP"],
            port=int(env["TGW_SERVER_PORT"]),
        )
    except Exception as exc:  # noqa: BLE001
        report["status"] = "FAIL"
        report["login_error"] = f"{type(exc).__name__}: {exc}"[:300]
        _flush(report, args.stage)
        return 1

    try:
        base = ad.BaseData()
        code_list = base.get_code_list(security_type="EXTRA_STOCK_A")
        sample = pick_sample_stocks(list(code_list), args.stage)
        report["sample"] = sample[:20]
        report["sample_size"] = len(sample)

        # ---- the actual realtime subscription --------------------------
        sub = ad.SubscribeData()
        events: list[dict] = []
        received_at_ms: list[float] = []

        def on_snapshot(data):  # SDK callback signature verified on first run
            recv = time.time()
            try:
                events.append(_snapshot_record(data, recv))
                received_at_ms.append(recv * 1000)
            except Exception as exc:  # noqa: BLE001 - record the shape issue
                events.append({"callback_error": f"{type(exc).__name__}: {exc}"})

        # subscribe call per manual; Period enum may be ad.Period or tgw.Period
        period_value = None
        for holder in (ad, getattr(ad, "tgw", None)):
            period_enum = getattr(holder, "Period", None)
            if period_enum is not None and hasattr(period_enum, "snapshot"):
                period_value = period_enum.snapshot.value
                break
        if period_value is None:
            report["status"] = "NOT_TESTABLE_PERMISSION"
            report["detail"] = "Period.snapshot enum not found; check SDK version"
            _flush(report, args.stage)
            return 1

        sub.register(code_list=sample, period=period_value, callback=on_snapshot)
        deadline = time.monotonic() + args.duration_seconds
        while time.monotonic() < deadline:
            time.sleep(0.5)
        try:
            sub.unregister(code_list=sample, period=period_value)
        except Exception:  # noqa: BLE001 - unregister best-effort evidence
            report["unregister_note"] = "unregister raised (recorded)"

        # ---- observations (task book 17) --------------------------------
        report["events_received"] = len(events)
        if events:
            keys = set()
            for e in events:
                keys.update(e.keys())
            report["observed_fields"] = sorted(keys)
            latencies = [e.get("latency_ms") for e in events if e.get("latency_ms") is not None]
            if latencies:
                report["latency_ms"] = {
                    "min": min(latencies),
                    "p50": sorted(latencies)[len(latencies) // 2],
                    "max": max(latencies),
                }
            report["duplicate_count"] = _duplicates(events)
            report["out_of_order_count"] = _out_of_order(events)
            report["trading_phases_seen"] = sorted(
                {str(e.get("trading_phase")) for e in events if e.get("trading_phase")}
            )
            report["has_limit_fields"] = any(e.get("up_limit") is not None for e in events)
            report["has_bid_ask_depth"] = any(e.get("bid_price_1") is not None for e in events)
        report["status"] = (
            "PASS"
            if events
            else ("NOT_TESTABLE_PERMISSION" if not in_session else "FAIL_NO_EVENTS")
        )
        report["evidence_events_sample"] = events[:5]
        report["duration_seconds"] = args.duration_seconds

    except Exception as exc:  # noqa: BLE001 - evidence, not crash
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"[:400]
    finally:
        with contextlib_suppress():
            ad.logout()

    _flush(report, args.stage)
    print(json.dumps({k: report[k] for k in ("stage", "status", "events_received")}, default=str))
    return 0 if report.get("status") == "PASS" else 1


def _snapshot_record(data, recv_ts: float) -> dict:
    """Extract observation fields from one snapshot callback payload.

    Defensive: SDK callback shapes are verified by the first live run;
    attribute/dict access failures are recorded, never crash the collector.
    """

    def g(name: str):
        for source in (data, getattr(data, "fields", None)):
            if source is None:
                continue
            if hasattr(source, name):
                return getattr(source, name)
            if hasattr(source, "get"):
                return source.get(name)
        return None

    event_time = g("provider_event_time") or g("data_time") or g("time")
    record: dict = {
        "provider_event_time": str(event_time)[:32] if event_time is not None else None,
        "received_at": recv_ts,
        "security": g("security_code") or g("code") or g("symbol"),
        "last_price": g("last_price") or g("close"),
        "cumulative_volume": g("cum_volume") or g("volume"),
        "cumulative_amount": g("cum_amount") or g("amount"),
        "trading_phase": g("trading_phase") or g("trade_phase"),
        "up_limit": g("up_limit") or g("high_limited"),
        "down_limit": g("down_limit") or g("low_limited"),
        "bid_price_1": g("bid_price_1") or g("bid1_price"),
        "ask_price_1": g("ask_price_1") or g("ask1_price"),
    }
    if event_time is not None:
        try:
            # provider event time formats vary; assume ms epoch or HHMMSSmmm
            ev = float(event_time)
            record["latency_ms"] = round(recv_ts * 1000 - ev, 3)
        except (TypeError, ValueError):
            pass
    return record


def _duplicates(events: list[dict]) -> int:
    seen: set[tuple] = set()
    dupes = 0
    for e in events:
        key = (e.get("security"), e.get("provider_event_time"))
        if key in seen and key[0] is not None:
            dupes += 1
        seen.add(key)
    return dupes


def _out_of_order(events: list[dict]) -> int:
    last: dict[str, str] = {}
    oo = 0
    for e in events:
        sec, t = e.get("security"), e.get("provider_event_time")
        if sec is None or t is None:
            continue
        if sec in last and str(t) < str(last[sec]):
            oo += 1
        last[sec] = str(t)
    return oo


def _flush(report: dict, stage: int) -> None:
    report["finished_at"] = datetime.now(UTC).isoformat()
    out = RESULTS / f"l1_subscription_{stage}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"report -> {out}")


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(Exception)


if __name__ == "__main__":
    sys.exit(main())
