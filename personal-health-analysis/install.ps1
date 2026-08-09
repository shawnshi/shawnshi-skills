[CmdletBinding()]
param(
    [string]$VenvPath = (Join-Path $PSScriptRoot '.venv'),
    [switch]$Offline,
    [string]$Wheelhouse = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:HashRequirementsDirectory = $null
$script:HashRequirementsFile = $null
$script:StagingVenv = $null

function Clear-InstallTemporaryFiles {
    if ($null -ne $script:HashRequirementsFile -and
        (Test-Path -LiteralPath $script:HashRequirementsFile -PathType Leaf)) {
        Remove-Item -LiteralPath $script:HashRequirementsFile -Force
    }
    if ($null -ne $script:HashRequirementsDirectory -and
        (Test-Path -LiteralPath $script:HashRequirementsDirectory -PathType Container)) {
        Remove-Item -LiteralPath $script:HashRequirementsDirectory -Force
    }
    $script:HashRequirementsFile = $null
    $script:HashRequirementsDirectory = $null
    if ($null -ne $script:StagingVenv -and
        (Test-Path -LiteralPath $script:StagingVenv -PathType Container)) {
        $stagingFull = [System.IO.Path]::GetFullPath($script:StagingVenv)
        $stagingLeaf = [System.IO.Path]::GetFileName($stagingFull)
        if (-not $stagingLeaf.StartsWith('.pia-venv-staging-')) {
            throw 'Refusing to remove an unexpected staging path.'
        }
        Remove-Item -LiteralPath $stagingFull -Recurse -Force
    }
    $script:StagingVenv = $null
}

function Stop-Install {
    param([string]$Message, [int]$ExitCode)
    Clear-InstallTemporaryFiles
    [Console]::Error.WriteLine($Message)
    exit $ExitCode
}

trap {
    Clear-InstallTemporaryFiles
    throw
}

if (-not $Offline) {
    Stop-Install 'Online installation is disabled. Use -Offline -Wheelhouse <verified-directory>.' 2
}
if ([string]::IsNullOrWhiteSpace($Wheelhouse) -or
    -not (Test-Path -LiteralPath $Wheelhouse -PathType Container)) {
    Stop-Install 'Offline installation requires -Wheelhouse <existing-directory>.' 2
}

try {
    $pythonExe = (
        Get-Command python -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
    ).Source
    $pythonVersion = & $pythonExe --version 2>&1
} catch {
    Stop-Install 'Python 3 is required and was not found on PATH.' 1
}
& $pythonExe -I -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Stop-Install 'Python 3.11 or newer is required.' 1
}

$requirements = Join-Path $PSScriptRoot 'requirements.lock.txt'
if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    Stop-Install 'requirements.lock.txt is missing.' 1
}
$integrityScript = Join-Path $PSScriptRoot 'scripts\wheelhouse_integrity.py'
if (-not (Test-Path -LiteralPath $integrityScript -PathType Leaf)) {
    Stop-Install 'scripts\wheelhouse_integrity.py is missing.' 1
}
$environmentGate = Join-Path $PSScriptRoot 'scripts\installed_environment_gate.py'
if (-not (Test-Path -LiteralPath $environmentGate -PathType Leaf)) {
    Stop-Install 'scripts\installed_environment_gate.py is missing.' 1
}
$publishScript = Join-Path $PSScriptRoot 'scripts\publish_directory_no_replace.py'
if (-not (Test-Path -LiteralPath $publishScript -PathType Leaf)) {
    Stop-Install 'scripts\publish_directory_no_replace.py is missing.' 1
}

$resolvedWheelhouse = (Resolve-Path -LiteralPath $Wheelhouse).Path
$wheelhouseManifest = Join-Path $resolvedWheelhouse 'wheelhouse-manifest.json'
& $pythonExe -I -B $integrityScript verify `
    --wheelhouse $resolvedWheelhouse `
    --manifest $wheelhouseManifest `
    --requirements-lock $requirements
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Wheelhouse integrity verification failed (exit $LASTEXITCODE); the target virtual environment was not changed." 3
}
$script:HashRequirementsDirectory = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("pia-wheelhouse-" + [System.Guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($script:HashRequirementsDirectory) | Out-Null
$script:HashRequirementsFile = Join-Path $script:HashRequirementsDirectory 'requirements.hashed.txt'
& $pythonExe -I -B $integrityScript generate-hash-requirements `
    --wheelhouse $resolvedWheelhouse `
    --manifest $wheelhouseManifest `
    --requirements-lock $requirements `
    --output $script:HashRequirementsFile
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Hashed requirements generation failed (exit $LASTEXITCODE); the target virtual environment was not changed." 3
}

$resolvedVenv = [System.IO.Path]::GetFullPath($VenvPath)
if (Test-Path -LiteralPath $resolvedVenv) {
    Stop-Install 'The target virtual-environment path already exists; choose a new empty path.' 2
}
$venvParent = [System.IO.Path]::GetDirectoryName($resolvedVenv)
if ([string]::IsNullOrWhiteSpace($venvParent) -or
    -not (Test-Path -LiteralPath $venvParent -PathType Container)) {
    Stop-Install 'The target virtual-environment parent directory must already exist.' 2
}
$script:StagingVenv = Join-Path `
    $venvParent `
    ('.pia-venv-staging-' + [System.Guid]::NewGuid().ToString('N'))
Write-Host "Python: $pythonVersion"
Write-Host "Virtual environment: $resolvedVenv"

& $pythonExe -I -m venv -- $script:StagingVenv
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Failed to create the virtual environment (exit $LASTEXITCODE)." 1
}

$venvPython = Join-Path $script:StagingVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Stop-Install 'The virtual-environment Python executable was not created.' 1
}

$pipArgs = @(
    '-I', '-m', 'pip', '--isolated', 'install',
    '--requirement', $script:HashRequirementsFile,
    '--require-hashes',
    '--only-binary=:all:',
    '--no-index',
    '--disable-pip-version-check',
    '--find-links', $resolvedWheelhouse
)

& $venvPython @pipArgs
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Dependency installation failed (exit $LASTEXITCODE)." 1
}
& $venvPython -I -m pip --isolated check
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Installed dependency validation failed (exit $LASTEXITCODE)." 1
}
& $venvPython -I -B $environmentGate --requirements-lock $requirements
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Installed package-set validation failed (exit $LASTEXITCODE)." 1
}
& $pythonExe -I -B $integrityScript verify `
    --wheelhouse $resolvedWheelhouse `
    --manifest $wheelhouseManifest `
    --requirements-lock $requirements
if ($LASTEXITCODE -ne 0) {
    Stop-Install 'Wheelhouse changed during installation; do not use the target virtual environment.' 3
}
& $pythonExe -I -B $publishScript --staging $script:StagingVenv --target $resolvedVenv
if ($LASTEXITCODE -ne 0) {
    Stop-Install "Atomic no-replace publication failed (exit $LASTEXITCODE)." 3
}
$script:StagingVenv = $null
$venvPython = Join-Path $resolvedVenv 'Scripts\python.exe'
Clear-InstallTemporaryFiles

Write-Host 'Dependencies installed in the isolated virtual environment.'
$localScript = Join-Path $PSScriptRoot 'scripts\garmin_data.py'
Write-Host "Local check: & '$venvPython' '$localScript' summary --days 7 --source local"
Write-Host 'Authentication and synchronization remain separate, explicitly authorized operations.'
Write-Host 'GarminDB synchronization requires a separately reviewed runner environment.'
