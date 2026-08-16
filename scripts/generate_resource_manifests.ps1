[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Root = '',
    [string[]]$IncludeSkills,
    [string[]]$ExcludeSkills = @(),
    [switch]$Check
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent $PSScriptRoot
}
$Root = (Resolve-Path -LiteralPath $Root).Path

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    Write-Error 'Python is required to generate or validate resource manifests.'
    exit 1
}

$mode = if ($Check) { 'check' } else { 'generate' }
if (-not $Check -and -not $PSCmdlet.ShouldProcess($Root, 'Generate scoped resource manifests')) {
    $mode = 'check'
}

$arguments = @(
    '-B', '-X', 'utf8',
    (Join-Path $PSScriptRoot 'resource_manifest.py'),
    $mode,
    '--root', $Root,
    '--json'
)
foreach ($skill in @($IncludeSkills)) {
    if (-not [string]::IsNullOrWhiteSpace($skill)) {
        $arguments += @('--include-skill', $skill)
    }
}
foreach ($skill in @($ExcludeSkills)) {
    if (-not [string]::IsNullOrWhiteSpace($skill)) {
        $arguments += @('--exclude-skill', $skill)
    }
}

$output = & $python.Source @arguments
$exitCode = $LASTEXITCODE
if ([string]::IsNullOrWhiteSpace(($output -join "`n"))) {
    Write-Error 'Resource manifest worker returned no result.'
    exit 1
}
$result = ($output -join "`n") | ConvertFrom-Json
if ($mode -eq 'check') {
    Write-Host "Resource manifests checked: $($result.checked); stale: $($result.stale)"
} else {
    Write-Host "Resource manifests checked: $($result.checked); written: $($result.written); unchanged: $($result.unchanged); failed: $($result.failed)"
}
foreach ($issue in @($result.issues)) {
    Write-Warning "$($issue.skill): $($issue.detail)"
}
if ($exitCode -ne 0) {
    exit $exitCode
}
