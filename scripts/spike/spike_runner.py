"""P0-M-1 Spike CLI (thin entry point; logic lives in ashare_state.spike).

Usage:
    # framework self-test (fake data, isolated)
    uv run python scripts/spike/spike_runner.py --dry-run

    # trial account run (terminal state always persisted)
    uv run python scripts/spike/spike_runner.py --trial --date 20260824

    # PRODUCTION: ONE run, ALL phases (R3-P0-02 - verdict needs a single
    # closed production run; per-phase execution requires --resume)
    uv run python scripts/spike/spike_runner.py --production --date <as-of>

    # resume an interrupted RUNNING production run (identity must match)
    uv run python scripts/spike/spike_runner.py --production --resume --run-id <id>

    # verdict (closed production runs only)
    uv run python scripts/spike/spike_runner.py --verdict --run-id <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ashare_state.spike import (
    CaseCatalog,
    ProbeContext,
    RunFailureReason,
    RunKind,
    RunStore,
    abort_run,
    close_run,
    compute_config_hash,
    compute_environment_lock_hash,
    compute_verdict,
    current_code_commit,
    fail_run,
    new_run,
    resume_run,
    run_dry_run,
    verify_production_account,
)
from ashare_state.spike.formal_gates import probe_b1_formal_gates
from ashare_state.spike.probes import (
    probe_b2_security_master,
    probe_b3_core_facts,
    probe_b4_golden,
    probe_b5_units_pit_freshness,
    probe_b6_replacement,
    probe_b7_capacity,
)

# R4-A3.1 P0-01: b1 (formal runtime gate boundary) is the mandatory
# first phase of every formal run - capability approval consumes its
# gate-proof cases and cannot approve a run without them.
PHASES = ("b1", "b2", "b3", "b4", "b5", "b6", "b7")


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


def _run_phases(ctx: ProbeContext, wanted: list[str], sample_date: int) -> dict:
    phases = {
        "b1": lambda: probe_b1_formal_gates(ctx),
        "b2": lambda: probe_b2_security_master(ctx),
        "b3": lambda: probe_b3_core_facts(ctx, sample_date),
        "b4": lambda: probe_b4_golden(ctx, sample_date),
        "b5": lambda: probe_b5_units_pit_freshness(ctx, sample_date),
        "b6": lambda: probe_b6_replacement(ctx, sample_date),
        "b7": lambda: probe_b7_capacity(ctx, sample_date),
    }
    results = {}
    for phase in wanted:
        if phase not in phases:
            print(f"unknown phase {phase!r}; valid: {list(phases)}")
            sys.exit(2)
        results[phase] = phases[phase]()
        print(f"[{phase}] {results[phase]}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="P0-M-1 Spike runner (R3)")
    parser.add_argument("--dry-run", action="store_true", help="framework self-test (fake data)")
    parser.add_argument("--production", action="store_true", help="real account run")
    parser.add_argument("--trial", action="store_true", help="trial account run")
    parser.add_argument(
        "--phase",
        default="all",
        help="b2..b7|all - PRODUCTION defaults to all (R3-P0-02)",
    )
    parser.add_argument("--date", type=int, default=20260824, help="run as-of trade date")
    parser.add_argument(
        "--resume", action="store_true", help="resume a RUNNING run (needs --run-id)"
    )
    parser.add_argument("--verdict", action="store_true", help="aggregate verdict for --run-id")
    parser.add_argument("--run-id", help="spike run id for --verdict / --resume")
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
        print(json.dumps(verdict.to_json(), ensure_ascii=False, default=str)[:800])
        print(f"verdict written: {out_path}")
        return 0

    if args.production or args.trial:
        run_kind = RunKind.PRODUCTION if args.production else RunKind.TRIAL
        target, session = _make_real_target()
        try:
            identity = target.identity()
            profile = session.profile

            # R3-P0-02: production defaults to ALL phases in ONE run
            wanted = list(PHASES) if args.phase == "all" else [args.phase]
            if args.production and args.phase != "all" and not args.resume:
                print(
                    "R3-P0-02: PRODUCTION runs execute ALL phases in one run; "
                    "per-phase continuation requires --resume --run-id <id>"
                )
                return 2

            if args.resume:
                if not args.run_id:
                    print("--resume requires --run-id")
                    return 2
                store = RunStore(spike_root)
                run = store.load_run(args.run_id, run_kind)
                run = resume_run(
                    store,
                    run,
                    account_profile_id=identity.get("account_profile_id", "UNKNOWN"),
                    code_commit=current_code_commit(Path.cwd(), require_clean=True),
                    environment_lock_hash=compute_environment_lock_hash(Path.cwd()),
                    config_hash=compute_config_hash(Path.cwd()),
                    sdk_version=identity.get("sdk_version"),
                    runtime_version=identity.get("runtime_version"),
                )
                catalog = CaseCatalog(store, run.spike_run_id)
                catalog.load(store.run_dir(run))
                print(f"resuming run {run.spike_run_id}; continuing with {wanted}")
            else:
                if args.production:
                    # R3-P0-14: verify the account BEFORE opening the run
                    verify_production_account(profile)
                run, store = new_run(
                    run_kind=run_kind,
                    spike_root=spike_root,
                    code_commit=(
                        current_code_commit(Path.cwd(), require_clean=True)
                        if args.production
                        else current_code_commit()
                    ),
                    environment_lock_hash=compute_environment_lock_hash(Path.cwd()),
                    config_hash=compute_config_hash(Path.cwd()),
                    sdk_version=identity.get("sdk_version"),
                    runtime_version=identity.get("runtime_version"),
                    account_profile_id=identity.get("account_profile_id", "UNKNOWN"),
                    as_of_date=str(args.date),
                    account_profile=profile,
                )
                catalog = CaseCatalog(store, run.spike_run_id)

            ctx = ProbeContext(run, store, catalog, target)
            try:
                _run_phases(ctx, wanted, args.date)
                catalog.flush(store.run_dir(run))
                # R3-P0-01: ALWAYS reach a terminal state
                closed = close_run(store, run)
                print(f"spike_run_id: {run.spike_run_id}")
                print(f"run_dir: {store.run_dir(run)}")
                print(f"status: {closed.status}")
                return 0
            except KeyboardInterrupt:
                catalog.flush(store.run_dir(run))
                abort_run(store, run)
                print(f"run {run.spike_run_id} ABORTED (operator interrupt)")
                return 130
            except Exception as exc:  # noqa: BLE001
                # fail_run already persisted FAILED_ACCOUNT inside the executor
                # for auth errors; anything else is a framework error
                catalog.flush(store.run_dir(run))
                if run.status == "RUNNING":
                    fail_run(store, run, RunFailureReason.FRAMEWORK_ERROR)
                print(f"run {run.spike_run_id} FAILED: {type(exc).__name__}: {exc}"[:400])
                return 3
        finally:
            session.logout()

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
