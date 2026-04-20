# Garmin Health Analysis Installer (Windows)
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

Write-Host "🏃 Installing Garmin Health Analysis Skill..." -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pyVersion = python --version 2>&1
    Write-Host "✓ Python found: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Error: Python is required but not found" -ForegroundColor Red
    Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Install Python dependencies
Write-Host ""
Write-Host "📦 Installing Python dependencies..." -ForegroundColor Cyan

try {
    pip install --user garminconnect fitparse gpxpy 2>$null
    if ($LASTEXITCODE -ne 0) {
        pip install garminconnect fitparse gpxpy
    }
    Write-Host "✓ Dependencies installed" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to install Python dependencies" -ForegroundColor Red
    Write-Host "  Try manually: pip install --user garminconnect fitparse gpxpy" -ForegroundColor Yellow
    exit 1
}

# Create output directory
$outputDir = Join-Path $PSScriptRoot "output"
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    Write-Host "✓ Output directory created" -ForegroundColor Green
}

# Create config from example if it doesn't exist
$configFile = Join-Path $PSScriptRoot "config.json"
$configExample = Join-Path $PSScriptRoot "config.example.json"
if ((-not (Test-Path $configFile)) -and (Test-Path $configExample)) {
    Write-Host ""
    Write-Host "📝 Creating config.json from example..." -ForegroundColor Cyan
    Copy-Item $configExample $configFile
    Write-Host "✓ config.json created (edit with your credentials)" -ForegroundColor Green
}

# Success
Write-Host ""
Write-Host "✅ Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Add your Garmin credentials:"
Write-Host "     - Edit config.json, or"
Write-Host "     - Set GARMIN_EMAIL and GARMIN_PASSWORD env vars"
Write-Host ""
Write-Host "  2. Authenticate:"
Write-Host "     python scripts\garmin_auth.py login"
Write-Host ""
Write-Host "  3. Test:"
Write-Host "     python scripts\garmin_data.py summary --days 7"
Write-Host ""
Write-Host "📖 Read SKILL.md for full documentation" -ForegroundColor Cyan
