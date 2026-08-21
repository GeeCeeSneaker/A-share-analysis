# Local quality gate - the local equivalent of CI (.github/workflows/ci.yml).
# This script does NOT replace real CI (design ruling section 10).
# Usage: ./scripts/quality_gate.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "=== 1/4 ruff check ===" -ForegroundColor Cyan
uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "=== 2/4 ruff format check ===" -ForegroundColor Cyan
uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "=== 3/4 mypy ===" -ForegroundColor Cyan
uv run mypy
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "=== 4/4 pytest ===" -ForegroundColor Cyan
uv run pytest
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`nALL QUALITY GATES PASSED" -ForegroundColor Green
