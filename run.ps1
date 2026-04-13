[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir = Join-Path $HOME ".claude"
$SettingsPath = Join-Path $ClaudeDir "settings.json"
$DefaultConfigPath = Join-Path $ScriptRoot "pester.config.json"
$AppDataDir = Join-Path $env:APPDATA "pester"
$UserConfigPath = Join-Path $AppDataDir "pester.config.json"
$entrypoint = Join-Path $ScriptRoot "src\pester.py"

function ConvertTo-PlainValue($Value) {
    if ($null -eq $Value) {
        return $null
    }

    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $result = @{}
        foreach ($property in $Value.PSObject.Properties) {
            $result[$property.Name] = ConvertTo-PlainValue $property.Value
        }
        return $result
    }

    if ($Value -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $Value.Keys) {
            $result[$key] = ConvertTo-PlainValue $Value[$key]
        }
        return $result
    }

    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $items = @()
        foreach ($item in $Value) {
            $items += ,(ConvertTo-PlainValue $item)
        }
        return $items
    }

    return $Value
}

function Read-JsonObject([string]$Path) {
    if (-not (Test-Path $Path)) {
        return @{}
    }

    $raw = Get-Content $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return @{}
    }

    return ConvertTo-PlainValue (ConvertFrom-Json $raw)
}

function ConvertTo-UnixPath([string]$Path) {
    $drive = $Path[0].ToString().ToLower()
    $rest = $Path.Substring(2).Replace('\', '/')
    return "/$drive$rest"
}

function Get-PythonLaunch {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @{
            FilePath = $pythonCmd.Source
            PrefixArgs = @()
            Display = $pythonCmd.Source
        }
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @{
            FilePath = $pyCmd.Source
            PrefixArgs = @("-3")
            Display = "$($pyCmd.Source) -3"
        }
    }

    throw "Python not found on PATH."
}

function New-HookEntry([string]$Command, [int]$TimeoutSeconds) {
    return @{
        matcher = ""
        hooks = @(
            @{
                type = "command"
                command = $Command
                timeout = $TimeoutSeconds
            }
        )
    }
}

function Install-Hooks([string]$PythonPath) {
    New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null
    New-Item -ItemType Directory -Force -Path $AppDataDir | Out-Null

    if (-not (Test-Path $UserConfigPath)) {
        Copy-Item $DefaultConfigPath $UserConfigPath
        Write-Host "Created config: $UserConfigPath"
    }

    if (Test-Path $SettingsPath) {
        $settings = Read-JsonObject $SettingsPath
    } else {
        $settings = @{}
    }

    if (-not $settings) {
        $settings = @{}
    }
    if (-not $settings.ContainsKey("hooks") -or -not ($settings["hooks"] -is [hashtable])) {
        $settings["hooks"] = @{}
    }

    $hooksDir = Join-Path $ScriptRoot "src\hooks"
    $hookSpecs = @{
        PreToolUse = @{ Script = "pre_tool_use.py"; Timeout = 65 }
        PermissionRequest = @{ Script = "permission_request.py"; Timeout = 305 }
        SessionStart = @{ Script = "session_lifecycle.py"; Timeout = 5 }
        SessionEnd = @{ Script = "session_lifecycle.py"; Timeout = 5 }
        Notification = @{ Script = "notification.py"; Timeout = 5 }
        Stop = @{ Script = "stop.py"; Timeout = 12 }
    }

    $unixPython = ConvertTo-UnixPath $PythonPath
    foreach ($hookName in $hookSpecs.Keys) {
        $scriptPath = Join-Path $hooksDir $hookSpecs[$hookName].Script
        $unixScript = ConvertTo-UnixPath $scriptPath
        $hookCommand = "$unixPython `"$unixScript`""
        $settings["hooks"][$hookName] = @(
            (New-HookEntry -Command $hookCommand -TimeoutSeconds $hookSpecs[$hookName].Timeout)
        )
    }

    $settings | ConvertTo-Json -Depth 10 | Set-Content -Path $SettingsPath -Encoding UTF8
    Write-Host "Hooks installed: $SettingsPath"
}

$pythonLaunch = Get-PythonLaunch

Write-Host "Installing dependencies..."
& $pythonLaunch.FilePath -m pip install -r "$ScriptRoot\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Install-Hooks -PythonPath $pythonLaunch.FilePath

# Kill any existing instance
$healthUrl = "http://localhost:9001/health"
try {
    $null = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 1
    Write-Host "Stopping existing Pester instance..."
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*pester.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
} catch {
    # Not running — nothing to stop
}

Write-Host "Starting Pester (on-demand)..."
Start-Process -FilePath $pythonLaunch.FilePath -ArgumentList ($pythonLaunch.PrefixArgs + @("`"$entrypoint`"")) -WindowStyle Hidden
