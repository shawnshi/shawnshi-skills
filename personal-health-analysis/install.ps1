# Garmin Health Analysis Installer (Windows)
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SkillRoot = $PSScriptRoot
$ScriptsDir = Join-Path $SkillRoot 'scripts'
$AssetsDir = Join-Path $SkillRoot 'assets'
$OutputDir = Join-Path $SkillRoot 'output'
$ConfigFile = Join-Path $SkillRoot 'config.json'
$ConfigExample = Join-Path $SkillRoot 'config.example.json'
$DashboardTemplate = Join-Path $AssetsDir 'dashboard_v2.html'
$GarminDbDir = Join-Path $HOME '.GarminDb\HealthData\DBs'
$GarminDbFile = Join-Path $GarminDbDir 'garmin.db'
$GarminSummaryDbFile = Join-Path $GarminDbDir 'garmin_summary.db'
$GarminActivitiesDbFile = Join-Path $GarminDbDir 'garmin_activities.db'

function Write-Section([string]$Text) {
    Write-Host ''
    Write-Host $Text -ForegroundColor Cyan
}

function Write-Ok([string]$Text) {
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn([string]$Text) {
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}

function Write-Fail([string]$Text) {
    Write-Host "[FAIL] $Text" -ForegroundColor Red
}

function Test-PythonImport([string]$ModuleName) {
    $result = & python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Install-PythonPackages([string[]]$Packages) {
    if (-not $Packages -or $Packages.Count -eq 0) {
        return $true
    }

    $packageList = $Packages -join ' '
    Write-Host "Installing missing Python packages: $packageList" -ForegroundColor Cyan

    & python -m pip install --user @Packages
    if ($LASTEXITCODE -eq 0) {
        return $true
    }

    Write-Warn 'User-site install failed. Retrying without --user.'
    & python -m pip install @Packages
    return ($LASTEXITCODE -eq 0)
}

Write-Host 'Installing Garmin Health Analysis Skill...' -ForegroundColor Cyan
Write-Host 'This installer checks package availability, local data capability, sync capability, and dashboard assets.' -ForegroundColor DarkGray

Write-Section '1. Python Runtime'
try {
    $pyVersion = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'python command failed'
    }
    Write-Ok "Python found: $pyVersion"
} catch {
    Write-Fail 'Python is required but was not found on PATH.'
    Write-Host 'Install Python from https://www.python.org/downloads/ and rerun this installer.' -ForegroundColor Yellow
    exit 1
}

try {
    & python -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'pip unavailable'
    }
    Write-Ok 'pip is available'
} catch {
    Write-Fail 'pip is required but unavailable for the current Python interpreter.'
    exit 1
}

Write-Section '2. Python Packages'
$moduleToPackage = [ordered]@{
    'garminconnect' = 'garminconnect'
    'fitparse' = 'fitparse'
    'gpxpy' = 'gpxpy'
    'pandas' = 'pandas'
}

$missingPackages = New-Object System.Collections.Generic.List[string]
foreach ($entry in $moduleToPackage.GetEnumerator()) {
    if (Test-PythonImport $entry.Key) {
        Write-Ok "Python module available: $($entry.Key)"
    } else {
        Write-Warn "Python module missing: $($entry.Key)"
        $missingPackages.Add($entry.Value)
    }
}

if ($missingPackages.Count -gt 0) {
    $installed = Install-PythonPackages ($missingPackages | Select-Object -Unique)
    if (-not $installed) {
        Write-Fail 'Failed to install required Python packages.'
        Write-Host 'Try manually: python -m pip install --user garminconnect fitparse gpxpy pandas' -ForegroundColor Yellow
        exit 1
    }
    Write-Ok 'Required Python packages installed'
} else {
    Write-Ok 'All required Python packages are already installed'
}

Write-Section '3. Skill Files'
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    Write-Ok "Output directory created: $OutputDir"
} else {
    Write-Ok "Output directory exists: $OutputDir"
}

if ((-not (Test-Path -LiteralPath $ConfigFile)) -and (Test-Path -LiteralPath $ConfigExample)) {
    Copy-Item -LiteralPath $ConfigExample -Destination $ConfigFile
    Write-Ok 'config.json created from config.example.json'
} elseif (Test-Path -LiteralPath $ConfigFile) {
    Write-Ok 'config.json already exists'
} else {
    Write-Warn 'config.example.json not found; skipped config bootstrap'
}

if (Test-Path -LiteralPath $DashboardTemplate) {
    Write-Ok 'Dashboard template present (Viz layer asset ready)'
} else {
    Write-Warn 'dashboard_v2.html is missing; HTML dashboard generation will not work'
}

Write-Section '4. Capability Detection'
$coreReady = $false
$syncReady = $false
$vizReady = $false

$localDbFiles = @($GarminDbFile, $GarminSummaryDbFile, $GarminActivitiesDbFile)
$existingDbFiles = @($localDbFiles | Where-Object { Test-Path -LiteralPath $_ })
if ($existingDbFiles.Count -gt 0) {
    $coreReady = $true
    Write-Ok "Local GarminDB snapshot detected in $GarminDbDir"
    foreach ($db in $existingDbFiles) {
        Write-Host "       - $db" -ForegroundColor DarkGray
    }
} else {
    Write-Warn 'No local GarminDB SQLite snapshot detected. Core local-first analysis is not ready yet.'
}

$garmindbCommand = Get-Command 'garmindb_cli.py' -ErrorAction SilentlyContinue
if (-not $garmindbCommand) {
    $garmindbCommand = Get-Command 'garmindb_cli' -ErrorAction SilentlyContinue
}

if ($garmindbCommand) {
    $syncReady = $true
    Write-Ok "Garmin sync CLI detected: $($garmindbCommand.Source)"
} else {
    Write-Warn 'Garmin sync CLI not found on PATH. Sync layer is unavailable until GarminDB is installed.'
}

if ((Test-Path -LiteralPath $DashboardTemplate) -and (Test-PythonImport 'pandas')) {
    $vizReady = $true
    Write-Ok 'Viz layer prerequisites detected'
} else {
    Write-Warn 'Viz layer is incomplete. Text analysis can still run without dashboard rendering.'
}

Write-Section '5. Capability Summary'
if ($coreReady) {
    Write-Host 'Core : READY  - Local SQLite / GarminDB analysis can run.' -ForegroundColor Green
} else {
    Write-Host 'Core : BLOCKED - No local SQLite snapshot detected.' -ForegroundColor Yellow
}

if ($syncReady) {
    Write-Host 'Sync : READY  - Local snapshot can be refreshed.' -ForegroundColor Green
} else {
    Write-Host 'Sync : PARTIAL - Installer packages are present, but GarminDB sync CLI is missing.' -ForegroundColor Yellow
}

if ($vizReady) {
    Write-Host 'Viz  : READY  - Dashboard rendering assets are available.' -ForegroundColor Green
} else {
    Write-Host 'Viz  : PARTIAL - HTML dashboard generation may be unavailable, but text output can still work.' -ForegroundColor Yellow
}

Write-Section '6. Next Steps'
if (-not $syncReady) {
    Write-Host '1. Install GarminDB / garmindb_cli.py if you want local sync refresh capability.' -ForegroundColor Cyan
}
if (-not $coreReady) {
    Write-Host '2. Build or import a local GarminDB snapshot before expecting local-first analysis.' -ForegroundColor Cyan
    if ($syncReady) {
        Write-Host '   Suggested: run your GarminDB sync command to populate ~/.GarminDb/HealthData/DBs.' -ForegroundColor DarkGray
    }
}
Write-Host '3. Optional: add Garmin credentials in config.json or environment variables GARMIN_EMAIL / GARMIN_PASSWORD.' -ForegroundColor Cyan
Write-Host '4. Test text analysis:' -ForegroundColor Cyan
Write-Host '   python scripts\garmin_intelligence.py readiness --days 1' -ForegroundColor DarkGray
Write-Host '   python scripts\garmin_intelligence.py insight_cn --days 7' -ForegroundColor DarkGray
if ($vizReady) {
    Write-Host '5. Test dashboard rendering:' -ForegroundColor Cyan
    Write-Host '   python scripts\garmin_chart.py dashboard --days 7' -ForegroundColor DarkGray
}

Write-Section '7. Installer Result'
if ($coreReady -or $syncReady) {
    Write-Ok 'Installer completed. The skill can run in at least one supported mode.'
    if (-not $coreReady) {
        Write-Warn 'Current mode is API-first or dependency-prep only until a local snapshot exists.'
    }
} else {
    Write-Warn 'Installer completed, but the skill is not operational yet because neither Core nor Sync capability is ready.'
}

Write-Host ''
Write-Host 'Read SKILL.md for the VNext execution contract and fallback rules.' -ForegroundColor Cyan
