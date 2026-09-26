"""CLI source-checkout support contract."""

from __future__ import annotations

from typer.testing import CliRunner

from ashare_state import cli


def test_self_test_reports_unsupported_layout_without_migrations(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_MIGRATIONS_DIR", tmp_path / "missing")

    result = CliRunner().invoke(cli.app, ["self-test"])

    assert result.exit_code == 2
    assert "unsupported runtime layout" in result.output
    assert "source checkout" in result.output


def test_update_rejects_non_iso_date_before_startup(tmp_path):
    result = CliRunner().invoke(
        cli.app,
        ["update", "--through", "20260926", "--db-path", str(tmp_path / "unused.duckdb")],
    )

    assert result.exit_code == 2
    assert "expected YYYY-MM-DD" in result.output


def test_evidence_cli_exposes_archive_and_verify_commands():
    runner = CliRunner()

    archive = runner.invoke(cli.app, ["evidence", "archive", "--help"])
    verify = runner.invoke(cli.app, ["evidence", "verify", "--help"])

    assert archive.exit_code == 0
    assert "--backup-root" in archive.output
    assert verify.exit_code == 0
    assert "--backup-root" in verify.output
