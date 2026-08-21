"""Typer CLI (V1.3.2 section 25): every command is idempotent."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from ashare_state.config import Settings, load_config
from ashare_state.identity import PROJECT_SECURITY_NAMESPACE, resolve_security_identity
from ashare_state.logging_setup import setup_logging
from ashare_state.storage.connection import DuckDBConnectionManager
from ashare_state.storage.migrations import apply_migrations

app = typer.Typer(
    name="ashare",
    help="A-share market state data foundation CLI (Phase 0 skeleton)",
    no_args_is_help=True,
)


@app.command()
def init_db(
    db_path: Path = typer.Option(None, help="Override DuckDB path"),
) -> None:
    """Initialize the database from zero (runs all pending migrations)."""
    config = load_config()
    path = db_path or config.paths.duckdb_path
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
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
    setup_logging()
    config = load_config()
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
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

    from ashare_state.providers.amazingdata.doctor import run_doctor

    settings = Settings()
    creds = None
    if settings.tgw_username and settings.tgw_password and not offline:
        creds = (
            settings.tgw_username,
            settings.tgw_password,
            settings.tgw_server_vip,
            settings.tgw_server_port,
        )
    report = run_doctor(credentials=creds, offline=offline)
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        typer.echo(f"report written: {output}")


if __name__ == "__main__":
    app()
