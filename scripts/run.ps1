$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    Write-Warning ".venv not found, falling back to system 'python'. Run scripts\setup.ps1 first."
    $python = "python"
}

$logsDir = Join-Path $root "logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$logFile = Join-Path $logsDir ("run-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') === Starting Jira Risk Detector" |
    Out-File -FilePath $logFile -Append -Encoding utf8

& $python -m src.main 2>&1 | Tee-Object -FilePath $logFile -Append
exit $LASTEXITCODE
