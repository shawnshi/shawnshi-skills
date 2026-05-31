[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Root = '',
    [string[]]$IncludeSkills,
    [string[]]$ExcludeSkills = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Root)) {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $Root = Split-Path -Parent $PSScriptRoot
    } elseif (-not [string]::IsNullOrWhiteSpace($PSCommandPath)) {
        $Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
    } else {
        throw 'Unable to resolve repo root. Pass -Root explicitly.'
    }
}

$LocalReferencePattern = '(?<path>(?<![A-Za-z])(?:(?:scripts|references|assets|examples|prompts|agents)[\\/][^\s`"''<>]+|[A-Za-z0-9._-]+[\\/](?:SKILL\.md|(?:scripts|references|assets|examples|prompts|agents)[\\/][^\s`"''<>]+)))'

$KnownFileSuffixPattern = '(?<stable>.*?(?:SKILL\.md|\.md|\.json|\.py|\.ps1|\.sh|\.csx|\.cs|\.svg|\.png|\.jpg|\.jpeg|\.gif|\.pptx|\.docx|\.pdf|\.txt|\.yaml|\.yml|\.toml|\.csv|\.tsv|\.html|\.css|\.js|\.ts|\.tsx|\.jsx))'

function Normalize-LocalReference {
    param(
        [string]$Path
    )

    $normalized = $Path.Replace('/', '\').Trim()
    if ($normalized.StartsWith('skills\', [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring(7)
    }
    $normalized = $normalized -replace '\]\(.*$', ''
    $normalized = [regex]::Replace($normalized, '[\)\]\.,;:\*]+$', '')
    if ($normalized -match $KnownFileSuffixPattern) {
        $normalized = $Matches['stable']
    }
    return $normalized
}

function Should-IgnoreReference {
    param(
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $true
    }

    $normalized = $Path.Replace('/', '\')
    if ($normalized.StartsWith('tmp\', [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    if ($normalized -match '\[.+?\]' -or $normalized -match '\{.+?\}' -or $normalized -match '<.+?>') {
        return $true
    }

    return $false
}

function Get-SkillFiles {
    $files = Get-ChildItem -Path $Root -Recurse -Filter 'SKILL.md' -File
    foreach ($file in $files) {
        $skill = Split-Path $file.DirectoryName -Leaf
        if ($IncludeSkills -and $skill -notin $IncludeSkills) {
            continue
        }
        if ($skill -in $ExcludeSkills) {
            continue
        }
        $file
    }
}

function Get-DeclaredLocalReferences {
    param(
        [string]$Text,
        [string]$SkillDirectory
    )

    $matches = [regex]::Matches($Text, $LocalReferencePattern)
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'

    foreach ($match in $matches) {
        $relative = Normalize-LocalReference -Path $match.Groups['path'].Value
        if ([string]::IsNullOrWhiteSpace($relative)) {
            continue
        }
        if (Should-IgnoreReference -Path $relative) {
            continue
        }
        if (-not $seen.Add($relative)) {
            continue
        }

        $candidatePaths = @(
            (Join-Path $SkillDirectory $relative),
            (Join-Path $Root $relative)
        )

        $resolved = $null
        foreach ($candidate in $candidatePaths) {
            if (Test-Path -LiteralPath $candidate) {
                $resolved = $candidate
                break
            }
        }

        [PSCustomObject]@{
            path          = $relative
            exists        = $null -ne $resolved
            resolved_path = $resolved
        }
    }
}

function Get-TopLevelResourceDirectories {
    param(
        [string]$SkillDirectory
    )

    $resourceNames = @('scripts', 'references', 'assets', 'examples', 'prompts', 'agents', 'tmp')
    foreach ($name in $resourceNames) {
        $full = Join-Path $SkillDirectory $name
        if (Test-Path -LiteralPath $full) {
            $files = @(Get-ChildItem -Path $full -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '\\__pycache__\\' })
            [PSCustomObject]@{
                name       = $name
                file_count = $files.Count
            }
        }
    }
}

$generated = 0
foreach ($file in (Get-SkillFiles)) {
    $skillDirectory = $file.DirectoryName
    $skillName = Split-Path $skillDirectory -Leaf
    $text = Get-Content -LiteralPath $file.FullName -Raw
    $declared = @(Get-DeclaredLocalReferences -Text $text -SkillDirectory $skillDirectory)
    $missing = @($declared | Where-Object { -not $_.exists } | ForEach-Object { $_.path })
    $topLevelFiles = @(
        Get-ChildItem -Path $skillDirectory -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch '\.bak$|\.p12\.bak$|\.p22\.bak$|resource-manifest\.json$' } |
        ForEach-Object { $_.Name }
    )
    $topLevelDirs = @(
        Get-ChildItem -Path $skillDirectory -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch '^__pycache__$' } |
        ForEach-Object { $_.Name }
    )

    $manifest = [ordered]@{
        schema_version                = 1
        skill                         = $skillName
        generated_at                  = (Get-Date).ToString('s')
        skill_md                      = 'SKILL.md'
        top_level_files               = $topLevelFiles
        top_level_directories         = $topLevelDirs
        resource_directories          = @(Get-TopLevelResourceDirectories -SkillDirectory $skillDirectory)
        declared_local_dependencies   = $declared
        missing_declared_dependencies = $missing
    }

    $manifestPath = Join-Path $skillDirectory 'resource-manifest.json'
    if ($PSCmdlet.ShouldProcess($manifestPath, 'Write resource manifest')) {
        $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        $generated++
    }
}

Write-Host "Resource manifests written: $generated"
