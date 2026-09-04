"""P0-M-1 Spike CLI (thin entry point; logic lives in ashare_state.spike).

Usage:
    # framework self-test (fake data, isolated)
    uv run python scripts/spike/spike_runner.py --dry-run

    # trial account run (terminal state always persisted)
    uv run python scripts/spike/spike_runner.py --trial --date 20260824

    # PRODUCTION: ONE run, ALL phases (R3-P0-02 - verdict needs a single
    # closed production run)
    uv run python scripts/spike/spike_runner.py --production --date <as-of>

    # replay-all recovery for an interrupted RUNNING production run
    # (identity and persisted as-of must match; no --phase selector)
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
    RunLifecycleError,
    RunStatus,
    RunStore,
    abort_run,
    close_run,
    compute_config_hash,
    compute_environment_lock_hash,
    compute_verdict,
    current_code_commit,
    fail_run,
    formal_anchor_connection,
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


def _parse_as_of_date(value, *, required: bool, source: str) -> int:
    """Validate an explicit YYYYMMDD as-of date.

    Formal runs never substitute wall-clock today or a historical default.
    Dry-run may use its stable fixture date when the option is omitted.
    """
    if value is None or str(value).strip() == "":
        if required:
            raise ValueError(f"{source} requires an explicit YYYYMMDD as-of date")
        return 20260824
    text = str(value).strip()
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        raise ValueError(f"{source} must be an 8-digit YYYYMMDD date")
    from datetime import datetime

    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{source} is not a valid calendar date: {text}") from exc
    return int(text)


def _resolve_resume_as_of_date(run, requested_date) -> int:
    """Resolve resume to the persisted run date and reject drift."""
    frozen = _parse_as_of_date(run.as_of_date, required=True, source="stored run")
    if requested_date is not None:
        requested = _parse_as_of_date(requested_date, required=True, source="--date")
        if requested != frozen:
            raise RunLifecycleError(
                f"resume refused for run {run.spike_run_id}: as-of date mismatch "
                f"(stored {frozen}, requested {requested})"
            )
    return frozen


def _resolve_wanted_phases(*, run_kind: RunKind, resume: bool, phase: str) -> list[str]:
    """Resolve phase selection before any formal side effect.

    Production recovery deliberately uses replay-all because the current
    catalog has no durable phase checkpoint. Trial keeps its existing
    phase-selection behavior.
    """
    if phase == "all":
        return list(PHASES)
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; valid: {list(PHASES)}")
    if run_kind is RunKind.PRODUCTION:
        if resume:
            raise RunLifecycleError(
                "Production --resume uses replay-all recovery; --phase bN is not accepted"
            )
        raise RunLifecycleError(
            "R3-P0-02: PRODUCTION runs execute ALL phases in one run; use --phase only with --trial"
        )
    return [phase]


def _build_probe_context(run, store, catalog, target, conn):
    """The single Production/Trial ProbeContext construction boundary."""
    return ProbeContext(run, store, catalog, target, conn)


def _build_resume_catalog(store, run):
    """Start replay-all recovery with a fresh, unsealed catalog.

    The previous catalog may contain a partial checkpoint from a hard crash.
    It is intentionally not loaded: successful replay flushes this fresh
    catalog over the RUNNING run's unsealed catalog, while raw evidence and
    anchor rows remain append-only audit history.
    """
    return CaseCatalog(store, run.spike_run_id)


def _current_persisted_run(store, run):
    try:
        return store.load_run(run.spike_run_id, run.run_kind)
    except Exception:  # noqa: BLE001 - preserve the original object for diagnostics
        return run


def _best_effort_catalog_flush(catalog, store, run) -> str | None:
    try:
        catalog.flush(store.run_dir(run))
    except Exception as exc:  # noqa: BLE001 - terminalization must continue
        return f"{type(exc).__name__}: {exc}"[:240]
    return None


def _execute_run(
    run,
    store,
    catalog,
    target,
    conn,
    wanted,
    sample_date,
    *,
    context_factory=_build_probe_context,
) -> int:
    """Execute one formal run with a terminalization boundary.

    Context construction, catalog loading/flushing, phase setup, and phase
    execution all live inside this boundary. A normal exception cannot leave
    a persisted run RUNNING; only a hard process crash can do that for
    later --resume recovery.
    """
    try:
        ctx = context_factory(run, store, catalog, target, conn)
        _run_phases(ctx, wanted, sample_date)
        catalog.flush(store.run_dir(run))
        closed = close_run(store, run)
        print(f"spike_run_id: {run.spike_run_id}")
        print(f"run_dir: {store.run_dir(run)}")
        print(f"status: {closed.status}")
        return 0
    except KeyboardInterrupt:
        flush_error = _best_effort_catalog_flush(catalog, store, run)
        current = _current_persisted_run(store, run)
        if current.status == RunStatus.RUNNING.value:
            abort_run(store, current)
        print(f"run {run.spike_run_id} ABORTED (operator interrupt)")
        if flush_error:
            print(f"catalog flush during abort failed: {flush_error}")
        return 130
    except Exception as exc:  # noqa: BLE001 - formal run must terminalize
        flush_error = _best_effort_catalog_flush(catalog, store, run)
        current = _current_persisted_run(store, run)
        if current.status == RunStatus.RUNNING.value:
            fail_run(store, current, RunFailureReason.FRAMEWORK_ERROR)
        print(f"run {run.spike_run_id} FAILED: {type(exc).__name__}: {exc}"[:400])
        if flush_error:
            print(f"catalog flush during failure failed: {flush_error}")
        return 3


def _formal_anchor_connection(repo_root: Path | None = None):
    """CLI alias kept explicit so tests can exercise the formal DB boundary."""
    return formal_anchor_connection(repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="P0-M-1 Spike runner (R3)")
    parser.add_argument("--dry-run", action="store_true", help="framework self-test (fake data)")
    parser.add_argument("--production", action="store_true", help="real account run")
    parser.add_argument("--trial", action="store_true", help="trial account run")
    parser.add_argument(
        "--phase",
        default="all",
        help="b1..b7|all - PRODUCTION defaults to all (R3-P0-02)",
    )
    parser.add_argument(
        "--date", type=int, default=None, help="explicit run as-of trade date (YYYYMMDD)"
    )
    parser.add_argument(
        "--resume", action="store_true", help="resume a RUNNING run (needs --run-id)"
    )
    parser.add_argument("--verdict", action="store_true", help="aggregate verdict for --run-id")
    parser.add_argument("--run-id", help="spike run id for --verdict / --resume")
    parser.add_argument("--spike-root", default="data/spike")
    args = parser.parse_args()

    selected_modes = [
        flag
        for flag, enabled in (
            ("--dry-run", args.dry_run),
            ("--production", args.production),
            ("--trial", args.trial),
            ("--verdict", args.verdict),
        )
        if enabled
    ]
    if len(selected_modes) > 1:
        print(
            "mode conflict: choose exactly one of --dry-run, --production, --trial, or --verdict",
            file=sys.stderr,
        )
        return 2
    if args.verdict and args.resume:
        print("argument conflict: --verdict cannot be combined with --resume")
        return 2

    spike_root = Path(args.spike_root)

    if args.dry_run:
        try:
            dry_run_date = _parse_as_of_date(args.date, required=False, source="dry-run")
        except ValueError as exc:
            print(f"date refused: {exc}")
            return 2
        out = run_dry_run(spike_root, sample_date=dry_run_date, repo_root=Path.cwd())
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
        if args.resume and not args.production:
            print(
                "argument conflict: --resume is supported only for --production replay-all recovery"
            )
            return 2
        try:
            wanted = _resolve_wanted_phases(
                run_kind=RunKind.PRODUCTION if args.production else RunKind.TRIAL,
                resume=args.resume,
                phase=args.phase,
            )
        except (RunLifecycleError, ValueError) as exc:
            print(f"formal run refused: {exc}")
            return 2
        if args.resume and not args.run_id:
            print("--resume requires --run-id")
            return 2
        if not args.resume and args.date is None:
            print("formal Production/Trial runs require an explicit --date YYYYMMDD")
            return 2
        try:
            requested_date = (
                _parse_as_of_date(args.date, required=True, source="--date")
                if args.date is not None
                else None
            )
        except ValueError as exc:
            print(f"date refused: {exc}")
            return 2

        run_kind = RunKind.PRODUCTION if args.production else RunKind.TRIAL
        target, session = _make_real_target()
        try:
            identity = target.identity()
            profile = session.profile

            if args.production and not args.resume:
                # R3-P0-14: verify the account before opening the run
                verify_production_account(profile)

            with _formal_anchor_connection(Path.cwd()) as conn:
                if args.resume:
                    store = RunStore(spike_root)
                    run = store.load_run(args.run_id, run_kind)
                    effective_date = _resolve_resume_as_of_date(run, requested_date)
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
                    catalog = _build_resume_catalog(store, run)
                    print(
                        f"resuming run {run.spike_run_id}; replaying all phases {wanted}; "
                        "rebuilding a fresh unsealed catalog; "
                        f"as_of_date={effective_date}"
                    )
                else:
                    assert requested_date is not None
                    effective_date = requested_date
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
                        as_of_date=str(effective_date),
                        account_profile=profile,
                    )
                    catalog = CaseCatalog(store, run.spike_run_id)

                return _execute_run(
                    run,
                    store,
                    catalog,
                    target,
                    conn,
                    wanted,
                    effective_date,
                )
        except (RunLifecycleError, ValueError) as exc:
            # Explicit operator/configuration refusal leaves an existing
            # RUNNING run untouched; only failures after entering _execute_run
            # are terminalized.
            print(f"formal run refused: {exc}"[:400])
            return 2
        except Exception as exc:  # noqa: BLE001 - DB/setup failure occurs before a new run
            print(f"formal runner setup failed: {type(exc).__name__}: {exc}"[:400])
            return 3
        finally:
            session.logout()

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
