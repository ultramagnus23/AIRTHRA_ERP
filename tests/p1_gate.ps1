# P1 gate verification (PowerShell wrapper).
#
# Starts the edge daemon (--mock) + ingest service against the live Docker
# stack, simulates a broker outage by stopping mosquitto, and asserts the
# SQLite-buffer-then-backfill-drain path produces zero gaps / zero
# duplicates / an empty dead_letter_readings table. Prints PASS/FAIL per
# check and exits non-zero on any failure.
#
# Usage (from repo root):
#   .\tests\p1_gate.ps1
#
# Requires the Docker Compose stack to already be up (at minimum: postgres,
# mosquitto) and .env to be resolvable. If `docker` isn't on PATH in this
# shell but Docker Desktop is installed, add it first, e.g.:
#   $env:PATH += ";C:\Program Files\Docker\Docker\resources\bin"

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python (Join-Path $RepoRoot "tests\p1_gate.py")
exit $LASTEXITCODE
