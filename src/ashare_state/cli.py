"""Typer CLI (V1.3.2 section 25): every command is idempotent."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from ashare_state.config import load_config
from ashare_state.identity import PROJECT_SECURITY_NAMESPACE, resolve_security_identity
from ashare_state.logging_setup import setup_logging
from ashare_state.storage.connection import DuckDBConnectionManager
from ashare_state.storage.migrations import apply_migrations

app = typer.Typer(
    name="ashare",
    help="A-share market state data foundation CLI (Phase 0 skeleton)",
    no_args_is_help=True,
)
evidence_app = typer.Typer(name="evidence", help="Archive and verify accepted raw evidence.")
app.add_typer(evidence_app, name="evidence")

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _require_source_migrations() -> Path:
    """Require the documented source-checkout layout; wheels are not supported."""
    if not _MIGRATIONS_DIR.is_dir() or not any(_MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        typer.echo(
            "unsupported runtime layout: migrations/ must be present; run from a source checkout",
            err=True,
        )
        raise typer.Exit(code=2)
    return _MIGRATIONS_DIR


@app.command()
def init_db(
    db_path: Path = typer.Option(None, help="Override DuckDB path"),
) -> None:
    """Initialize the database from zero (runs all pending migrations)."""
    config = load_config()
    path = db_path or config.paths.duckdb_path
    migrations_dir = _require_source_migrations()
    manager = DuckDBConnectionManager(path)
    with manager.owner("read_write") as conn:
        applied = apply_migrations(conn, migrations_dir)
    if applied:
        typer.echo(f"applied {len(applied)} migration(s): {[r.filename for r in applied]}")
    else:
        typer.echo("database already up to date")


@app.command()
def migrate(
    db_path: Path = typer.Option(None, help="Override DuckDB path"),
) -> None:
    """Apply pending migrations (idempotent; verifies checksums)."""
    init_db(db_path=db_path)


@app.command()
def security_id_check() -> None:
    """Verify deterministic identity on the fixed security fixture."""
    _run_security_fixture_check()


def _run_security_fixture_check() -> None:
    """Shared fixture check body (used by CLI commands and self-test)."""
    fixture = [
        ("SZSE", "STOCK", "000001", date(1991, 4, 3)),
        ("SSE", "STOCK", "600000", date(1990, 12, 19)),
        ("SZSE", "STOCK", "300750", date(2018, 6, 11)),
        ("SSE", "STOCK", "688981", date(2020, 7, 22)),
        ("BSE", "STOCK", "830799", date(2021, 11, 15)),
        # delisted + relisted code reuse -> distinct identity
        ("SZSE", "STOCK", "000003", date(1991, 1, 1)),
        ("SZSE", "STOCK", "000003", date(2030, 1, 1)),
    ]
    run_a = [resolve_security_identity(*row) for row in fixture]
    run_b = [resolve_security_identity(*row) for row in fixture]
    for a, b in zip(run_a, run_b, strict=True):
        assert a.security_id == b.security_id
        assert a.identity_key == b.identity_key
    typer.echo(f"namespace: {PROJECT_SECURITY_NAMESPACE}")
    typer.echo(f"fixture identities deterministic: {len(fixture)} entries OK")


@app.command()
def self_test() -> None:
    """Quick sanity self-check (imports, config, identity, migrations dir)."""
    migrations_dir = _require_source_migrations()
    setup_logging()
    config = load_config()
    n_migrations = len(list(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")))
    typer.echo(f"config loaded: data_root={config.paths.data_root}")
    typer.echo(f"migrations found: {n_migrations}")
    _run_security_fixture_check()


@app.command()
def provider_doctor(
    offline: bool = typer.Option(False, help="Skip login/connectivity probes"),
    output: Path = typer.Option(None, help="Also write the JSON report to this path"),
) -> None:
    """Runtime identity + connectivity diagnosis (task book section 2)."""
    import json

    from ashare_state.providers.amazingdata.credentials import (
        TgwCredentialsError,
        credential_rotation_hint,
        load_tgw_environment,
        resolve_tgw_credentials,
    )
    from ashare_state.providers.amazingdata.doctor import run_doctor
    from ashare_state.providers.amazingdata.safe_diagnostics import (
        safe_diagnostic_projection,
        safe_error_code,
    )
    from ashare_state.providers.amazingdata.stdout_capture import (
        CapturedStderr,
        CapturedStdout,
        sdk_stderr_into,
        sdk_stdout_into,
    )

    creds = None
    if not offline:
        try:
            creds = resolve_tgw_credentials(load_tgw_environment())
        except TgwCredentialsError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from None
    stdout, stderr = CapturedStdout(), CapturedStderr()
    try:
        with sdk_stdout_into(stdout), sdk_stderr_into(stderr):
            try:
                raw = run_doctor(credentials=creds, offline=offline)
            except Exception as exc:  # noqa: BLE001 - no raw diagnostic traceback
                raw = {"sdk_state": "ERROR", "error_code": safe_error_code(exc)}
        report = safe_diagnostic_projection(raw, offline=offline)
    finally:
        stdout.text = ""
        stderr.text = ""
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if report.get("auth_error") == "ProviderAuthError":
        typer.echo(credential_rotation_hint(), err=True)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        typer.echo("report written")


@app.command()
def update(
    through: str = typer.Option(
        ...,
        "--through",
        help="Advance accepted SH/SZ daily data through this date (YYYY-MM-DD).",
    ),
    plan: bool = typer.Option(
        False,
        "--plan",
        help="Inspect the accepted boundary without Provider login or network calls.",
    ),
    db_path: Path = typer.Option(None, help="Override DuckDB path"),
    backup_root: Path = typer.Option(
        None,
        "--backup-root",
        envvar="ASHARE_EVIDENCE_BACKUP_ROOT",
        help="Secondary evidence root; defaults to ASHARE_EVIDENCE_BACKUP_ROOT.",
    ),
) -> None:
    """Advance the accepted daily-bar Snapshot through one exchange date."""
    import json
    from dataclasses import asdict

    from ashare_state.providers.amazingdata.credentials import (
        TgwCredentialsError,
        load_tgw_environment,
        resolve_tgw_credentials,
    )
    from ashare_state.update import (
        DailyUpdateError,
        DailyUpdateRunner,
        read_repository_identity,
    )

    try:
        through_date = date.fromisoformat(through)
    except ValueError:
        typer.echo("invalid --through date; expected YYYY-MM-DD", err=True)
        raise typer.Exit(code=2) from None
    if through_date.isoformat() != through:
        typer.echo("invalid --through date; expected YYYY-MM-DD", err=True)
        raise typer.Exit(code=2)

    config = load_config()
    path = db_path or config.paths.duckdb_path
    migrations_dir = _require_source_migrations()
    repository_root = Path(__file__).resolve().parents[2]
    data_root = config.paths.data_root
    raw_root = data_root / "raw"
    normalized_root = data_root / "normalized"
    manager = DuckDBConnectionManager(path)

    if plan:
        try:
            with manager.owner("read_only") as conn:
                runner = DailyUpdateRunner(
                    conn,
                    provider=None,
                    repository_root=repository_root,
                    data_root=data_root,
                    raw_root=raw_root,
                    normalized_root=normalized_root,
                    evidence_backup_root=backup_root,
                    batch_size=500,
                    progress=lambda event: None,
                )
                typer.echo(
                    json.dumps(asdict(runner.plan(through_date)), default=str, ensure_ascii=False)
                )
        except Exception as exc:  # noqa: BLE001 - CLI safety boundary
            typer.echo(f"update plan unavailable: {exc}", err=True)
            raise typer.Exit(code=2) from None
        return

    try:
        with manager.owner("read_write") as conn:
            apply_migrations(conn, migrations_dir)
            runner = DailyUpdateRunner(
                conn,
                provider=None,
                repository_root=repository_root,
                data_root=data_root,
                raw_root=raw_root,
                normalized_root=normalized_root,
                evidence_backup_root=backup_root,
                batch_size=500,
            )
            update_plan = runner.plan(through_date)
            if update_plan.action == "NO_PROVIDER_WORK":
                result = runner.run(through_date)
                typer.echo(json.dumps(asdict(result), default=str, ensure_ascii=False))
                return
            repository = read_repository_identity(repository_root)
            if repository.dirty:
                raise DailyUpdateError(
                    "accepted daily update refused: tracked repository state is dirty; "
                    "commit the reviewed code and rerun"
                )
            from ashare_state.providers.amazingdata.capability import (
                CapabilityStatus,
                load_approvals,
            )

            approvals = load_approvals(conn)
            required = ("trade_calendar", "security_master", "daily_bar")
            blocked = [
                name for name in required if approvals.get(name) is not CapabilityStatus.APPROVED
            ]
            if blocked:
                typer.echo(
                    f"daily update requires approved Provider capabilities: {', '.join(blocked)}",
                    err=True,
                )
                raise typer.Exit(code=2)
            credentials = resolve_tgw_credentials(load_tgw_environment())
            from ashare_state.providers.amazingdata.provider import (
                AmazingDataProvider,
                ProviderUseMode,
            )
            from ashare_state.providers.amazingdata.session import AmazingDataSession

            session = AmazingDataSession(*credentials)
            try:
                session.login()
                provider = AmazingDataProvider(session, use_mode=ProviderUseMode.PRODUCTION)

                def report_progress(event: dict[str, object]) -> None:
                    typer.echo(json.dumps(event, ensure_ascii=False, sort_keys=True), err=True)

                runner = DailyUpdateRunner(
                    conn,
                    provider=provider,
                    repository_root=repository_root,
                    data_root=data_root,
                    raw_root=raw_root,
                    normalized_root=normalized_root,
                    evidence_backup_root=backup_root,
                    batch_size=500,
                    progress=report_progress,
                )
                result = runner.run(through_date)
            finally:
                session.logout()
            if result.retention_status == "NOT_CONFIGURED":
                typer.echo(
                    "WARNING: accepted run has no configured secondary evidence backup; "
                    "set ASHARE_EVIDENCE_BACKUP_ROOT or pass --backup-root",
                    err=True,
                )
            elif result.retention_status == "BACKUP_FAILED":
                typer.echo(
                    "WARNING: daily update was accepted, but evidence backup failed; "
                    "inspect EVIDENCE_RETENTION_FAILED and retry with `ashare evidence archive`",
                    err=True,
                )
            typer.echo(json.dumps(asdict(result), default=str, ensure_ascii=False))
    except typer.Exit:
        raise
    except (DailyUpdateError, TgwCredentialsError) as exc:
        typer.echo(f"daily update blocked: {exc}", err=True)
        raise typer.Exit(code=2) from None
    except Exception as exc:  # noqa: BLE001 - do not expose SDK objects or credentials
        typer.echo(f"daily update failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=2) from None


def _resolve_backup_root(value: Path | None) -> Path:
    if value is None:
        typer.echo(
            "evidence command requires --backup-root or ASHARE_EVIDENCE_BACKUP_ROOT",
            err=True,
        )
        raise typer.Exit(code=2)
    return value.expanduser().resolve()


@evidence_app.command("archive")
def evidence_archive(
    update_run_id: str,
    backup_root: Path = typer.Option(
        None,
        "--backup-root",
        envvar="ASHARE_EVIDENCE_BACKUP_ROOT",
        help="Distinct secondary/off-machine evidence root.",
    ),
    db_path: Path = typer.Option(None, help="Override DuckDB path"),
) -> None:
    """Archive one accepted daily-update run and copy its receipt to the backup root."""
    import json

    from ashare_state.update.retention import archive_daily_update

    config = load_config()
    data_root = config.paths.data_root
    raw_root = data_root / "raw"
    manager = DuckDBConnectionManager(db_path or config.paths.duckdb_path)
    try:
        with manager.owner("read_only") as conn:
            result = archive_daily_update(
                conn,
                update_run_id=update_run_id,
                data_root=data_root,
                raw_root=raw_root,
                secondary_root=_resolve_backup_root(backup_root),
            )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - avoid leaking paths or payload details
        typer.echo(f"evidence archive failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))


@evidence_app.command("verify")
def evidence_verify(
    backup_root: Path = typer.Option(
        None,
        "--backup-root",
        envvar="ASHARE_EVIDENCE_BACKUP_ROOT",
        help="Distinct secondary/off-machine evidence root.",
    ),
    db_path: Path = typer.Option(None, help="Override DuckDB path"),
) -> None:
    """Check accepted-run receipts and local/secondary archive integrity."""
    import json
    from dataclasses import asdict

    from ashare_state.update.retention import verify_daily_update_archives

    config = load_config()
    data_root = config.paths.data_root
    manager = DuckDBConnectionManager(db_path or config.paths.duckdb_path)
    try:
        with manager.owner("read_only") as conn:
            result = verify_daily_update_archives(
                conn,
                data_root=data_root,
                secondary_root=_resolve_backup_root(backup_root),
            )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - avoid leaking paths or payload details
        typer.echo(f"evidence verification failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    if result.issues:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
