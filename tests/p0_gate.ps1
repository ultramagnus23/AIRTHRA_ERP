# P0 gate verification (PowerShell wrapper).
#
# Runs migrations twice (idempotency) and proves Row-Level-Security tenant
# isolation. Prints PASS/FAIL per check and exits non-zero on any failure.
#
# Usage (from repo root):
#   .\tests\p0_gate.ps1
#
# Requires DATABASE_URL (and PG_TENANT_ROLE / PG_GLOBAL_ROLE + passwords) to
# be resolvable from .env, and that the target Postgres is reachable
# (docker compose up -d postgres, or a local dev instance).

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python (Join-Path $RepoRoot "tests\p0_gate.py")
exit $LASTEXITCODE
