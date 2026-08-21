"""TGW connectivity smoke test (simulation account, minimal traffic).

Usage (after filling .env):
    uv run python scripts/spike/connectivity_check.py

Probes (each guarded, each archived - a permission denial is EVIDENCE,
not a crash):
    P0  env sanity        - credentials present, no placeholders
    P1  login             - AmazingData.login(username, password, host, port)
    P2  get_calendar      - BaseData.get_calendar()            [tiny]
    P3  get_code_list     - BaseData.get_code_list(...)        [tiny]
    P4  query_snapshot    - 1 stock x 1 day, 5-min window
                            [simulation account: Level-1 snapshot scope]

Simulation-account findings (2026-08-21, recorded in
docs/provider_verification/amazingdata.md section 2.1):
    PermissionCode "3|4|32|33" grants code lists ONLY. Calendar, hist code
    list, adj factor and snapshot queries are denied server-side; the SDK
    surfaces this as an internal TypeError (None subscript) or a generic
    "查询失败" after long retries - both are recorded as DENIED evidence.

Traffic discipline for the 10GB/week + 0.2MB/s simulation account:
serial execution, single stock, time-boxed snapshot window, abort on first
hard failure. Results land in data/spike/results/connectivity.json.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

RESULTS = Path("data/spike/results")
RESULTS.mkdir(parents=True, exist_ok=True)

_SECRET_KEYS = ("TGW_USERNAME", "TGW_PASSWORD", "TGW_SERVER_VIP")


def load_env(path: Path = Path(".env")) -> dict[str, str]:
    """Minimal .env parser (spike scripts stay independent of prod modules)."""
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    merged = {**os.environ, **env}
    return {k: v for k, v in merged.items() if k.startswith("TGW_")}


def scrub(text: str, env: dict[str, str]) -> str:
    """Remove credential values from any error text."""
    out = text
    for key in _SECRET_KEYS:
        val = env.get(key, "")
        if val:
            out = out.replace(val, "***")
    return out


def classify_denial(detail: str) -> str:
    """Map SDK failure shapes to evidence labels."""
    if "NoneType" in detail:
        return "DENIED (server returned no data; SDK crashed with TypeError)"
    if "查询失败" in detail:
        return "DENIED (generic query failure after long retry)"
    return "FAIL"


def main() -> int:
    env = load_env()
    report: dict[str, object] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "account_type": "simulation (PermissionCode 3|4|32|33)",
        "probes": {},
    }
    ok = True

    def record(name: str, status: str, detail: str = "") -> None:
        nonlocal ok
        report["probes"][name] = {"status": status, "detail": detail}
        print(f"[{name}] {status}" + (f" - {detail[:200]}" if detail else ""))
        if status.startswith("FAIL"):
            ok = False

    # P0 - env sanity ------------------------------------------------------
    missing = [
        k
        for k in ("TGW_USERNAME", "TGW_PASSWORD", "TGW_SERVER_VIP", "TGW_SERVER_PORT")
        if not env.get(k)
    ]
    if missing:
        record("p0_env", "FAIL", f"missing env keys: {missing}; copy .env.example to .env and fill")
        _flush(report)
        return 2
    record("p0_env", "PASS")

    # P1 - login ----------------------------------------------------------
    try:
        # N813: `import AmazingData as ad` is the official manual idiom.
        import AmazingData as ad  # noqa: N813

        ad.login(
            username=env["TGW_USERNAME"],
            password=env["TGW_PASSWORD"],
            host=env["TGW_SERVER_VIP"],
            port=int(env["TGW_SERVER_PORT"]),
        )
        record("p1_login", "PASS")
    except Exception as exc:  # noqa: BLE001 - provider errors are opaque evidence
        record("p1_login", "FAIL", scrub(f"{type(exc).__name__}: {exc}", env))
        _flush(report)
        return 2

    # P2 - calendar (expected DENIED on simulation account) ----------------
    try:
        base = ad.BaseData()
        calendar = base.get_calendar()
        last = calendar[-1] if isinstance(calendar, list) and calendar else None
        record("p2_calendar", "PASS", f"trading days={len(calendar)} last={last}")
    except Exception as exc:  # noqa: BLE001
        detail = scrub(f"{type(exc).__name__}: {exc}", env)
        record("p2_calendar", classify_denial(detail), detail)

    # P3 - code list -------------------------------------------------------
    code_list: list[str] = []
    try:
        base = ad.BaseData()
        code_list = base.get_code_list(security_type="EXTRA_STOCK_A")
        record("p3_code_list", "PASS", f"A-share codes={len(code_list)} sample={code_list[:3]}")
    except Exception as exc:  # noqa: BLE001
        record("p3_code_list", "FAIL", scrub(f"{type(exc).__name__}: {exc}", env))

    # P4 - Level-1 snapshot (1 stock, 1 day, 5-minute window) ----------------
    # NOTE: query_snapshot took 2-4 minutes per attempt on the simulation
    # account before failing with "查询失败" (2026-08-21). Keep the probe but
    # expect DENIED; it is the documented permission boundary.
    if code_list:
        try:
            today = int(datetime.now().strftime("%Y%m%d"))
            stock = code_list[0]
            md = ad.MarketData([today])
            snap = md.query_snapshot(
                [stock],
                begin_date=today,
                end_date=today,
                begin_time=93000000,  # 09:30:00.000
                end_time=93500000,  # 09:35:00.000
            )
            if isinstance(snap, dict):
                df = next(iter(snap.values()))
                rows = 0 if df is None else len(df)
                cols = [] if df is None else list(getattr(df, "columns", []))
                record(
                    "p4_snapshot",
                    "PASS",
                    f"stock={stock} date={today} rows={rows} cols={cols[:12]}",
                )
            else:
                record("p4_snapshot", "PASS", f"unexpected shape: {type(snap).__name__}")
        except Exception as exc:  # noqa: BLE001
            detail = scrub(f"{type(exc).__name__}: {exc}", env)
            record("p4_snapshot", classify_denial(detail), detail)
    else:
        record("p4_snapshot", "SKIP", "depends on p3 which failed")

    # logout best-effort -----------------------------------------------------
    with contextlib.suppress(Exception):
        ad.logout()

    _flush(report)
    return 0 if ok else 1


def _flush(report: dict[str, object]) -> None:
    out = RESULTS / "connectivity.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"report -> {out}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - top-level guard for the evidence file
        traceback.print_exc()
        sys.exit(3)
