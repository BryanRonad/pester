[CmdletBinding()]
param()

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entrypoint = Join-Path $ScriptRoot "src\pester.py"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python not found on PATH." }
    $python = "$($py.Source) -3"
} else {
    $python = $pythonCmd.Source
}

# Kill any existing instance
$healthUrl = "http://localhost:9001/health"
try {
    $null = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 1
    Write-Host "Stopping existing Pester instance..."
    Get-Process -Name python -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*pester.py*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
} catch {
    # Not running — nothing to stop
}

Write-Host "Starting Pester (on-demand)..."
& cmd /c start "" /b $python `"$entrypoint`"
