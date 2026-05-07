$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python not found on PATH. Install Python 3.11+ from https://www.python.org/."
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment in .venv ..."
    python -m venv .venv
}

$pip = Join-Path $root ".venv\Scripts\pip.exe"
& $pip install --upgrade pip
& $pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host "Created .env from .env.example. Edit it with your credentials before running." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Next steps:" -ForegroundColor Green
Write-Host "  1. Edit .env with your Jira / Slack / Anthropic credentials"
Write-Host "  2. Test with: .\scripts\run.ps1   (set DRY_RUN=true in .env first)"
Write-Host "  3. Schedule daily 9 AM run: .\scripts\setup_scheduler.ps1"
