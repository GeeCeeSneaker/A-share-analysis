"""L1 REALTIME subscription test (task book 1.2 + R2-P1-06 hardening).

CRITICAL DISTINCTION: REALTIME_L1_SUBSCRIPTION != HISTORICAL_SNAPSHOT_QUERY
(separate verdicts; the latter was DENIED on 2026-08-21).

R2-P1-06 hardening:
- Asia/Shanghai session detection (never trust the dev machine's local zone)
- distinct not-testable reasons: NOT_TESTABLE_TIME / NOT_TESTABLE_PERMISSION
  / FAIL_NO_EVENTS (lifecycle-unverified events are NEVER read as
  entitlement evidence)
- provider_event_time parsed to an aware datetime before latency/ordering
- subscription lifecycle (register/run/unregister/stop) is verified live
  BEFORE FAIL_NO_EVENTS can mean anything about permissions

Usage (MUST run during trading hours, Asia/Shanghai):
    uv run python scripts/spike/l1_subscription_test.py --stage 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ashare_state.providers.amazingdata.subscription import SubscriptionController
from ashare_state.providers.lifecycle import SdkLifecycle, SdkLifecycleState

SHANGHAI = ZoneInfo("Asia/Shanghai")
RESULTS = Path("data/spike/results")


def _pick_sample(code_list: list[str], stage: int) -> list[str]:
    """R3-P1-10 32.3: SH/SZ/BJ mixed sample (deterministic round-robin)."""
    buckets = [[c for c in code_list if c.endswith(sfx)] for sfx in (".SH", ".SZ", ".BJ")]
    pool: list[str] = []
    while len(pool) < stage and any(buckets):
        for bucket in buckets:
            if bucket and len(pool) < stage:
                pool.append(bucket.pop(0))
    return pool[:stage]


def _run_id() -> str:
    import uuid

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def load_env(path: Path = Path(".env")) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.startswith("TGW_")}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def session_state(now: datetime | None = None) -> str:
    """Trading-session classification in Asia/Shanghai."""
    now = now or datetime.now(tz=SHANGHAI)
    if now.weekday() >= 5:
        return "NOT_TESTABLE_TIME"  # weekend
    hhmm = now.hour * 100 + now.minute
    if 915 <= hhmm <= 1130 or 1300 <= hhmm <= 1505:
        return "IN_SESSION"
    return "NOT_TESTABLE_TIME"


def parse_event_time(value: object) -> datetime | None:
    """Parse provider event time into an aware datetime (R2-P1-06).

    Handles: epoch ms/µs, HHMMSSmmm within today, yyyymmddHHMMSS.
    """
    if value is None:
        return None
    text = str(value).strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    today = datetime.now(tz=SHANGHAI).date()
    try:
        if len(digits) == 13:  # epoch ms
            return datetime.fromtimestamp(int(digits) / 1000, tz=UTC)
        if len(digits) == 16:  # epoch µs
            return datetime.fromtimestamp(int(digits) / 1e6, tz=UTC)
        if len(digits) == 9:  # HHMMSSmmm today
            h, m, s = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
            return datetime(today.year, today.month, today.day, h, m, s, tzinfo=SHANGHAI)
        if len(digits) == 14:  # yyyymmddHHMMSS
            return datetime(
                int(digits[0:4]),
                int(digits[4:6]),
                int(digits[6:8]),
                int(digits[8:10]),
                int(digits[10:12]),
                int(digits[12:14]),
                tzinfo=SHANGHAI,
            )
    except (ValueError, OSError):
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="L1 realtime subscription test")
    parser.add_argument("--stage", type=int, default=1)
    parser.add_argument("--duration-seconds", type=int, default=60)
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    env = load_env()
    report: dict[str, object] = {
        "capability": "REALTIME_L1_SUBSCRIPTION",
        "stage": args.stage,
        "run_id": _run_id(),
        "started_at": datetime.now(UTC).isoformat(),
        "session_state": session_state(),
    }

    if not all(
        env.get(k) for k in ("TGW_USERNAME", "TGW_PASSWORD", "TGW_SERVER_VIP", "TGW_SERVER_PORT")
    ):
        report["status"] = "NOT_TESTABLE_ACCOUNT"
        _flush(report, args.stage)
        return 2
    if session_state() != "IN_SESSION":
        # outside trading hours: NOTHING about permissions can be concluded
        report["status"] = "NOT_TESTABLE_TIME"
        report["note"] = "run Mon-Fri 09:15-11:30 / 13:00-15:05 Asia/Shanghai"
        _flush(report, args.stage)
        return 2

    try:
        import AmazingData as ad  # noqa: N813
    except ImportError:
        report["status"] = "NOT_TESTABLE_ACCOUNT"
        report["detail"] = "SDK not installed"
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
        report["status"] = "NOT_TESTABLE_ACCOUNT"
        report["login_error"] = f"{type(exc).__name__}: {exc}"[:300]
        _flush(report, args.stage)
        return 1

    # R4-A3.1 P1-01: the SDK lifecycle state machine is the correctness
    # SoR for the whole session (login -> subscribe -> callback ->
    # unsubscribe -> logout); the report dicts below are diagnostic
    # VIEWS derived from it, never a second SoR.
    lifecycle = SdkLifecycle()
    lifecycle.transition(
        SdkLifecycleState.SESSION_READY, reason="login ok", evidence_ref="ad.login"
    )

    events: list[dict] = []
    lifecycle: dict[str, object] = {}
    try:
        base = ad.BaseData()
        code_list = list(base.get_code_list(security_type="EXTRA_STOCK_A"))
        # R3-P1-10 32.3: SH/SZ/BJ mixed sample
        sample = _pick_sample(code_list, args.stage)
        report["sample_size"] = len(sample)
        report["sample_markets"] = {
            sfx: sum(1 for c in sample if c.endswith(sfx)) for sfx in (".SH", ".SZ", ".BJ")
        }

        sub = ad.SubscribeData()
        controller = SubscriptionController(lifecycle, sub)

        def on_snapshot(data) -> None:
            recv = datetime.now(tz=UTC)
            record: dict[str, object] = {"received_at": recv.isoformat()}
            for attr in (
                "security_code",
                "code",
                "last_price",
                "cum_volume",
                "volume",
                "cum_amount",
                "amount",
                "trading_phase",
                "up_limit",
                "high_limited",
                "down_limit",
                "low_limited",
                "bid_price_1",
                "ask_price_1",
                "data_time",
            ):
                value = getattr(data, attr, None)
                if value is None and hasattr(data, "get"):
                    value = data.get(attr)
                if value is not None:
                    record[attr] = str(value)[:40]
            event_time = parse_event_time(record.get("data_time"))
            if event_time is not None:
                record["event_time"] = event_time.isoformat()
                record["latency_ms"] = round((recv - event_time).total_seconds() * 1000, 3)
            events.append(record)

        period_value = None
        for holder in (ad, getattr(ad, "tgw", None)):
            period_enum = getattr(holder, "Period", None)
            if period_enum is not None and hasattr(period_enum, "snapshot"):
                period_value = period_enum.snapshot.value
                break
        if period_value is None:
            report["status"] = "NOT_TESTABLE_PERMISSION"
            report["detail"] = "Period.snapshot enum not found (SDK surface drift)"
            _flush(report, args.stage)
            return 1

        # R4-A3.1 P1-01: register/run/unregister/stop go through the
        # SubscriptionController, which DRIVES the SdkLifecycle state
        # machine (SESSION_READY -> SUBSCRIBE_STARTED -> CALLBACK_ACTIVE
        # -> UNSUBSCRIBED). The ``lifecycle`` dict is the diagnostic
        # VIEW; correctness truth is the state machine.
        lifecycle["register"] = "OK"
        try:
            controller.register(code_list=sample, period=period_value, callback=on_snapshot)
        except Exception as exc:  # noqa: BLE001
            lifecycle["register"] = f"ERROR {type(exc).__name__}: {exc}"[:200]
            report["lifecycle"] = lifecycle
            report["status"] = "NOT_TESTABLE_PERMISSION"
            _flush(report, args.stage)
            return 1

        # run/start loop if the SDK exposes one (verified live per R2-P1-06)
        controller.run()
        if "run" in controller.step_errors:
            lifecycle["run"] = f"ERROR {controller.step_errors['run']}"[:200]
        else:
            lifecycle["run"] = "OK"

        deadline = time.monotonic() + args.duration_seconds
        while time.monotonic() < deadline:
            time.sleep(0.5)

        try:
            controller.unregister(code_list=sample, period=period_value)
            lifecycle["unregister"] = (
                f"ERROR {controller.step_errors['unregister']}"[:200]
                if "unregister" in controller.step_errors
                else "OK"
            )
        except Exception as exc:  # noqa: BLE001
            lifecycle["unregister"] = f"ERROR {type(exc).__name__}"[:200]
        controller.stop()
        lifecycle["stop"] = (
            f"ERROR {controller.step_errors['stop']}"[:200]
            if "stop" in controller.step_errors
            else "OK"
        )
        report["lifecycle"] = lifecycle
        report["lifecycle_state_machine"] = controller.diagnostic()

        report["events_received"] = len(events)
        # R3-P1-10 32.4: two separate verdicts - receiving events with a
        # broken unregister/stop is NOT an overall PASS
        if events:
            latencies = [e["latency_ms"] for e in events if "latency_ms" in e]
            if latencies:
                report["latency_ms"] = {
                    "min": min(latencies),
                    "p50": sorted(latencies)[len(latencies) // 2],
                    "max": max(latencies),
                }
            report["out_of_order_count"] = _out_of_order(events)
            report["fields_observed"] = sorted({k for e in events for k in e})
            report["event_stream_verdict"] = "PASS"
        else:
            report["event_stream_verdict"] = "FAIL_NO_EVENTS"
            report["note"] = (
                "subscription lifecycle recorded above; verify callback "
                "signature against the lifecycle errors before reading this "
                "as an entitlement conclusion (R2-P1-06 17.3)"
            )
        lifecycle_ok = bool(lifecycle) and all(str(v).startswith("OK") for v in lifecycle.values())
        # R4-A3.1 P1-01: the verdict must ALSO be derived from the state
        # machine SoR - a diagnostic dict alone is not lifecycle truth.
        # The happy path ends UNSUBSCRIBED (register -> [callback] ->
        # unregister/stop complete) with no step errors.
        state = lifecycle.state
        lifecycle_ok = (
            lifecycle_ok and state is SdkLifecycleState.UNSUBSCRIBED and not controller.step_errors
        )
        report["lifecycle_verdict"] = "PASS" if lifecycle_ok else "FAIL"
        report["status"] = (
            "PASS"
            if report["event_stream_verdict"] == "PASS" and report["lifecycle_verdict"] == "PASS"
            else str(report["event_stream_verdict"])
        )
        report["evidence_events_sample"] = events[:5]

    except Exception as exc:  # noqa: BLE001 - evidence, not crash
        report["status"] = "NOT_TESTABLE_PERMISSION"
        report["error"] = f"{type(exc).__name__}: {exc}"[:400]
    finally:
        with _suppress():
            ad.logout()
        with _suppress():
            # state-machine truth: logout closes the session (close() is
            # the idempotent terminal path for LOGGED_OUT)
            lifecycle.close(reason="logout", evidence_ref="ad.logout")

    _flush(report, args.stage)
    print(
        json.dumps({k: report.get(k) for k in ("stage", "status", "events_received")}, default=str)
    )
    return 0 if report.get("status") == "PASS" else 1


def _out_of_order(events: list[dict]) -> int:
    last: dict[str, str] = {}
    oo = 0
    for e in events:
        sec = str(e.get("security_code") or e.get("code") or "")
        t = str(e.get("event_time") or "")
        if not sec or not t:
            continue
        if sec in last and t < last[sec]:
            oo += 1
        last[sec] = t
    return oo


def _flush(report: dict, stage: int) -> None:
    report["finished_at"] = datetime.now(UTC).isoformat()
    # R3-P1-10 32.1: run-scoped immutable evidence (no overwrite on rerun)
    run_dir = Path("data/spike/trial-l1") / str(report.get("run_id", "unknown"))
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"l1_subscription_{stage}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"report -> {out}")


def _suppress():
    import contextlib

    return contextlib.suppress(Exception)


if __name__ == "__main__":
    sys.exit(main())
