"""P0-M-1 Spike CLI (thin entry point; logic lives in ashare_state.spike).

Usage:
    uv run python scripts/spike/spike_runner.py --dry-run
    uv run python scripts/spike/spike_runner.py --verdict --run-id <id>   # production only
    uv run python scripts/spike/spike_runner.py --production --phase b2   # real account (B2-B7)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ashare_state.spike import (
    CaseCatalog,
    ProbeContext,
    RunKind,
    RunStore,
    compute_verdict,
    current_code_commit,
    new_run,
    run_dry_run,
)
from ashare_state.spike.probes import (
    probe_b2_security_master,
    probe_b3_core_facts,
    probe_b4_golden,
    probe_b5_units_pit_freshness,
    probe_b6_replacement,
    probe_b7_capacity,
)


def _load_env(path: Path = Path(".env")) -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if k.startswith("TGW_")}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _make_real_target():
    from ashare_state.providers.amazingdata.session import AmazingDataSession
    from ashare_state.spike.target import make_real_target

    env = _load_env()
    missing = [
        k
        for k in ("TGW_USERNAME", "TGW_PASSWORD", "TGW_SERVER_VIP", "TGW_SERVER_PORT")
        if not env.get(k)
    ]
    if missing:
        print(f"missing env keys: {missing}; fill .env first")
        sys.exit(2)
    session = AmazingDataSession(
        env["TGW_USERNAME"],
        env["TGW_PASSWORD"],
        env["TGW_SERVER_VIP"],
        int(env["TGW_SERVER_PORT"]),
    )
    session.login()
    return make_real_target(session), session


def main() -> int:
    parser = argparse.ArgumentParser(description="P0-M-1 Spike runner (R2A)")
    parser.add_argument("--dry-run", action="store_true", help="framework self-test (fake data)")
    parser.add_argument("--production", action="store_true", help="real account run (B2-B7)")
    parser.add_argument("--trial", action="store_true", help="trial account run")
    parser.add_argument("--phase", default="all", help="b2|b3|b4|b5|b6|b7|all (production/trial)")
    parser.add_argument("--date", type=int, default=20260814, help="sample trade date")
    parser.add_argument("--verdict", action="store_true", help="aggregate verdict for --run-id")
    parser.add_argument("--run-id", help="spike run id for --verdict")
    parser.add_argument("--spike-root", default="data/spike")
    args = parser.parse_args()

    spike_root = Path(args.spike_root)

    if args.dry_run:
        out = run_dry_run(spike_root, sample_date=args.date, repo_root=Path.cwd())
        print(json.dumps(out, ensure_ascii=False, default=str)[:600])
        return 0

    if args.verdict:
        if not args.run_id:
            print("--verdict requires --run-id (production run)")
            return 2
        store = RunStore(spike_root)
        run = store.load_run(args.run_id, RunKind.PRODUCTION)
        verdict = compute_verdict(store, run)
        out_path = store.run_dir(run) / "verdict.json"
        out_path.write_text(
            json.dumps(verdict.to_json(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(verdict.to_json(), ensure_ascii=False, default=str)[:600])
        print(f"verdict written: {out_path}")
        return 0

    if args.production or args.trial:
        run_kind = RunKind.PRODUCTION if args.production else RunKind.TRIAL
        target, session = _make_real_target()
        try:
            identity = target.identity()
            run, store = new_run(
                run_kind=run_kind,
                spike_root=spike_root,
                code_commit=current_code_commit(),
                sdk_version=identity.get("sdk_version"),
                runtime_version=identity.get("runtime_version"),
                account_profile_id=identity.get("account_profile_id", "UNKNOWN"),
            )
            catalog = CaseCatalog(store, run.spike_run_id)
            ctx = ProbeContext(run, store, catalog, target)
            phases = {
                "b2": lambda: probe_b2_security_master(ctx),
                "b3": lambda: probe_b3_core_facts(ctx, args.date),
                "b4": lambda: probe_b4_golden(ctx, args.date),
                "b5": lambda: probe_b5_units_pit_freshness(ctx, args.date),
                "b6": lambda: probe_b6_replacement(ctx, args.date),
                "b7": lambda: probe_b7_capacity(ctx, args.date),
            }
            wanted = list(phases) if args.phase == "all" else [args.phase]
            results = {}
            for phase in wanted:
                if phase not in phases:
                    print(f"unknown phase {phase!r}; valid: {list(phases)}")
                    return 2
                results[phase] = phases[phase]()
                print(f"[{phase}] {results[phase]}")
            catalog.flush(store.run_dir(run))
            print(f"spike_run_id: {run.spike_run_id}")
            print(f"run_dir: {store.run_dir(run)}")
            return 0
        finally:
            session.logout()

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
