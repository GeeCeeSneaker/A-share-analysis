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
    from typer.main import get_command

    evidence = get_command(cli.app).commands["evidence"]
    archive = evidence.commands["archive"]
    verify = evidence.commands["verify"]

    assert any("--backup-root" in parameter.opts for parameter in archive.params)
    assert any("--backup-root" in parameter.opts for parameter in verify.params)
