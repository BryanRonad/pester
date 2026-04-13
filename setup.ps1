[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir = Join-Path $HOME ".claude"
$SettingsPath = Join-Path $ClaudeDir "settings.json"
$DefaultConfigPath = Join-Path $ScriptRoot "pester.config.json"
$AppDataDir = Join-Path $env:APPDATA "pester"
$UserConfigPath = Join-Path $AppDataDir "pester.config.json"
$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RunValueName = "Pester"

function Write-Step([string]$Step, [string]$Message) {
    Write-Host "[$Step] $Message"
}

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

function Get-PythonCommand {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return $pythonCmd.Source
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return "$($pyCmd.Source) -3"
    }

    throw "Python 3.11+ was not found on PATH."
}

function Get-InstallTarget {
    $pythonCommand = Get-PythonCommand
    $entrypoint = Join-Path $ScriptRoot "src\pester.py"
    return @{
        Command = "$pythonCommand `"$entrypoint`""
        Display = "$pythonCommand $entrypoint"
    }
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

Write-Host "Pester Setup"
Write-Host ""

Write-Step "1/5" "Checking Python..."
$pythonCommand = Get-PythonCommand
$versionOutput = & cmd /c "$pythonCommand --version" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Failed to run Python: $versionOutput"
}

$versionText = ($versionOutput | Select-Object -First 1).ToString()
if ($versionText -notmatch "Python\s+(\d+)\.(\d+)") {
    throw "Could not determine Python version from: $versionText"
}
if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 11)) {
    throw "Python 3.11+ is required. Found: $versionText"
}
Write-Host "  Python detected: $versionText"

Write-Step "2/5" "Installing dependencies..."
& cmd /c "$pythonCommand -m pip install -r `"$ScriptRoot\requirements.txt`""
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

Write-Step "3/5" "Ensuring config exists..."
New-Item -ItemType Directory -Force -Path $AppDataDir | Out-Null
if (-not (Test-Path $UserConfigPath)) {
    Copy-Item $DefaultConfigPath $UserConfigPath
    Write-Host "  Config created: $UserConfigPath"
} else {
    Write-Host "  Config already present: $UserConfigPath"
}

Write-Step "4/5" "Installing Claude Code hooks..."
New-Item -ItemType Directory -Force -Path $ClaudeDir | Out-Null
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

foreach ($hookName in $hookSpecs.Keys) {
    $scriptPath = Join-Path $hooksDir $hookSpecs[$hookName].Script
    $unixPython = ConvertTo-UnixPath $pythonCommand
    $unixScript = ConvertTo-UnixPath $scriptPath
    $hookCommand = "$unixPython `"$unixScript`""
    $settings["hooks"][$hookName] = @(
        (New-HookEntry -Command $hookCommand -TimeoutSeconds $hookSpecs[$hookName].Timeout)
    )
}

$settings | ConvertTo-Json -Depth 10 | Set-Content -Path $SettingsPath -Encoding UTF8
Write-Host "  Hooks installed in: $SettingsPath"

Write-Step "5/5" "Registering startup and launching Pester..."
$installTarget = Get-InstallTarget
New-Item -Path $RunKeyPath -Force | Out-Null
Set-ItemProperty -Path $RunKeyPath -Name $RunValueName -Value $installTarget.Command
Write-Host "  Startup command: $($installTarget.Display)"

$healthUrl = "http://localhost:9001/health"
try {
    $null = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 1
    $alreadyRunning = $true
} catch {
    $alreadyRunning = $false
}

if (-not $alreadyRunning) {
    $launchCommand = $installTarget.Command
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c $launchCommand"
    Start-Sleep -Seconds 1
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "Config: $UserConfigPath"
Write-Host "Hooks:  $SettingsPath"
