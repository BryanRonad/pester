[CmdletBinding()]
param(
    [switch]$RemoveConfig
)

$ErrorActionPreference = "Stop"

$ClaudeDir = Join-Path $HOME ".claude"
$SettingsPath = Join-Path $ClaudeDir "settings.json"
$AppDataDir = Join-Path $env:APPDATA "pester"
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

Write-Host "Pester Uninstall"
Write-Host ""

Write-Step "1/4" "Stopping running Pester processes..."
$processes = Get-Process -Name pester, python, python3 -ErrorAction SilentlyContinue
foreach ($process in $processes) {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)").CommandLine
    } catch {
        $cmd = ""
    }

    if ($process.ProcessName -ieq "pester" -or $cmd -match "src\\pester\.py" -or $cmd -match "dist\\pester\.exe") {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "  Running instances stopped if present"

Write-Step "2/4" "Removing Pester hooks from Claude Code settings..."
if (Test-Path $SettingsPath) {
    $settings = Read-JsonObject $SettingsPath
    if (-not $settings) {
        $settings = @{}
    }

    $hookNames = @("PreToolUse", "PermissionRequest", "SessionStart", "SessionEnd", "Notification", "Stop")
    if ($settings.ContainsKey("hooks") -and ($settings["hooks"] -is [hashtable])) {
        foreach ($hookName in $hookNames) {
            if (-not $settings["hooks"].ContainsKey($hookName)) {
                continue
            }

            $entries = @($settings["hooks"][$hookName])
            $keptEntries = @()
            foreach ($entry in $entries) {
                $commands = @()
                if ($entry -is [hashtable] -and $entry.ContainsKey("hooks")) {
                    foreach ($hook in @($entry["hooks"])) {
                        if ($hook -is [hashtable] -and $hook.ContainsKey("command")) {
                            $commands += [string]$hook["command"]
                        }
                    }
                }

                $isPesterEntry = $false
                foreach ($command in $commands) {
                    if ($command -match "pester" -or $command -match "src\\hooks\\") {
                        $isPesterEntry = $true
                        break
                    }
                }

                if (-not $isPesterEntry) {
                    $keptEntries += $entry
                }
            }

            if ($keptEntries.Count -gt 0) {
                $settings["hooks"][$hookName] = $keptEntries
            } else {
                $settings["hooks"].Remove($hookName)
            }
        }

        if ($settings["hooks"].Count -eq 0) {
            $settings.Remove("hooks")
        }

        $settings | ConvertTo-Json -Depth 10 | Set-Content -Path $SettingsPath -Encoding UTF8
        Write-Host "  Hooks updated: $SettingsPath"
    } else {
        Write-Host "  No hooks section found"
    }
} else {
    Write-Host "  No Claude settings file found"
}

Write-Step "3/4" "Removing startup registration..."
if (Get-ItemProperty -Path $RunKeyPath -Name $RunValueName -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $RunKeyPath -Name $RunValueName
    Write-Host "  Startup entry removed"
} else {
    Write-Host "  No startup entry found"
}

Write-Step "4/4" "Cleaning config..."
if ($RemoveConfig) {
    if (Test-Path $AppDataDir) {
        Remove-Item -LiteralPath $AppDataDir -Recurse -Force
        Write-Host "  Removed: $AppDataDir"
    } else {
        Write-Host "  No config directory found"
    }
} else {
    Write-Host "  Config retained: $AppDataDir"
    Write-Host "  Re-run with -RemoveConfig to delete it"
}

Write-Host ""
Write-Host "Uninstall complete."
