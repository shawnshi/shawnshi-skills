[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Audit', 'FixFrontmatter', 'Report', 'Gate')]
    [string]$Mode = 'Audit',

    [string]$Root = '',

    [string[]]$IncludeSkills,

    [string[]]$ExcludeSkills = @(),

    [int]$LineThreshold = 500,

    [string]$ReportDir = ''
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

if ([string]::IsNullOrWhiteSpace($ReportDir)) {
    $ReportDir = Join-Path $Root 'reports'
}

$UnsupportedToolTokens = @(
    'ask_user',
    'replace',
    'google_web_search',
    'web_fetch',
    'generalist',
    'ipython',
    'datasource'
)

$ForeignRuntimePatterns = @(
    '/app/.kimi',
    'C:\Users\shich\.gemini\extensions\vector-lake'
)

$LocalReferencePattern = '(?<path>(?<![A-Za-z])(?:(?:scripts|references|assets|examples|prompts|agents)[\\/][^\s`"''<>]+|[A-Za-z0-9._-]+[\\/](?:SKILL\.md|(?:scripts|references|assets|examples|prompts|agents)[\\/][^\s`"''<>]+)))'

$StandardSectionPatterns = [ordered]@{
    WhenToUse      = @("## When to Use")
    Workflow       = @("## Workflow")
    Resources      = @("## Resources")
    FailureModes   = @("## Failure Modes")
    OutputContract = @("## Output Contract")
    Telemetry      = @("## Telemetry")
}

$TriggerOwnershipMatrixRelativePath = 'shared\trigger-ownership-matrix.json'
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

function Get-FrontmatterStatus {
    param(
        [string[]]$Lines
    )

    $startsCorrectly = $Lines.Count -gt 0 -and $Lines[0] -eq '---'
    $endIndex = $null

    if ($startsCorrectly) {
        for ($i = 1; $i -lt $Lines.Count; $i++) {
            if ($Lines[$i] -eq '---') {
                $endIndex = $i
                break
            }
        }
    }

    $frontmatterLines = if ($null -ne $endIndex) { $Lines[0..$endIndex] } else { @() }
    $frontmatterText = $frontmatterLines -join "`n"

    [PSCustomObject]@{
        StartsCorrectly = $startsCorrectly
        EndsCorrectly   = $null -ne $endIndex
        EndIndex        = $endIndex
        HasName         = [bool]($frontmatterText -match '(?m)^name:')
        HasDescription  = [bool]($frontmatterText -match '(?m)^description:')
    }
}

function Get-UnsupportedTokens {
    param(
        [string]$Text
    )

    foreach ($token in $UnsupportedToolTokens) {
        if ($Text -match [regex]::Escape($token)) {
            $token
        }
    }
}

function Get-ForeignRuntimeHits {
    param(
        [string]$Text
    )

    foreach ($pattern in $ForeignRuntimePatterns) {
        if ($Text -match [regex]::Escape($pattern)) {
            $pattern
        }
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
            Path         = $relative
            Exists       = $null -ne $resolved
            ResolvedPath = $resolved
        }
    }
}

function Get-MissingLocalReferences {
    param(
        [string]$Text,
        [string]$SkillDirectory
    )

    foreach ($reference in (Get-DeclaredLocalReferences -Text $Text -SkillDirectory $SkillDirectory)) {
        if (-not $reference.Exists) {
            $reference.Path
        }
    }
}

function Get-ResourceManifestStatus {
    param(
        [string]$SkillDirectory
    )

    $manifestPath = Join-Path $SkillDirectory 'resource-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        return [PSCustomObject]@{
            Exists                      = $false
            Path                        = $manifestPath
            MissingDeclaredDependencies = @()
        }
    }

    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $missing = @()
        if ($null -ne $manifest.missing_declared_dependencies) {
            $missing = @($manifest.missing_declared_dependencies)
        }
        return [PSCustomObject]@{
            Exists                      = $true
            Path                        = $manifestPath
            MissingDeclaredDependencies = $missing
        }
    } catch {
        return [PSCustomObject]@{
            Exists                      = $true
            Path                        = $manifestPath
            MissingDeclaredDependencies = @('__MANIFEST_PARSE_ERROR__')
        }
    }
}

function Get-StandardStructureStatus {
    param(
        [string]$Text
    )

    $positions = [ordered]@{}
    foreach ($key in $StandardSectionPatterns.Keys) {
        $index = -1
        foreach ($heading in $StandardSectionPatterns[$key]) {
            $candidateIndex = $Text.IndexOf($heading, [System.StringComparison]::OrdinalIgnoreCase)
            if ($candidateIndex -ge 0 -and ($index -lt 0 -or $candidateIndex -lt $index)) {
                $index = $candidateIndex
            }
        }
        $positions[$key] = $index
    }

    $missing = @($positions.GetEnumerator() | Where-Object { $_.Value -lt 0 } | ForEach-Object { $_.Key })
    $presentPositions = @($positions.GetEnumerator() | Where-Object { $_.Value -ge 0 } | ForEach-Object { $_.Value })
    $ordered = $true
    if ($presentPositions.Count -gt 1) {
        $ordered = (($presentPositions | Sort-Object) -join ',') -eq ($presentPositions -join ',')
    }

    [PSCustomObject]@{
        MissingSections = $missing
        IsCompliant     = ($missing.Count -eq 0 -and $ordered)
        Ordered         = $ordered
    }
}

function Get-TriggerOwnershipStatus {
    param(
        [string]$RootPath,
        [string[]]$KnownSkills
    )

    $matrixPath = Join-Path $RootPath $TriggerOwnershipMatrixRelativePath
    if (-not (Test-Path -LiteralPath $matrixPath)) {
        return [PSCustomObject]@{
            Exists         = $false
            Path           = $matrixPath
            DomainCount    = 0
            ClassCount     = 0
            ConflictMessages = @('__MISSING_TRIGGER_OWNERSHIP_MATRIX__')
        }
    }

    try {
        $matrix = Get-Content -LiteralPath $matrixPath -Raw | ConvertFrom-Json
    } catch {
        return [PSCustomObject]@{
            Exists           = $true
            Path             = $matrixPath
            DomainCount      = 0
            ClassCount       = 0
            ConflictMessages = @('__TRIGGER_OWNERSHIP_MATRIX_PARSE_ERROR__')
        }
    }

    $conflicts = [System.Collections.Generic.List[string]]::new()
    $signalOwners = @{}
    $domainCount = 0
    $classCount = 0

    foreach ($domain in @($matrix.domains)) {
        $domainCount++
        $domainName = [string]$domain.domain
        foreach ($class in @($domain.classes)) {
            $classCount++
            $classId = [string]$class.id
            $primary = [string]$class.primary_skill

            if ([string]::IsNullOrWhiteSpace($primary)) {
                $conflicts.Add("$domainName/$classId missing primary_skill")
            } elseif ($KnownSkills -notcontains $primary) {
                $conflicts.Add("$domainName/$classId unknown primary_skill: $primary")
            }

            foreach ($secondary in @($class.secondary_skills)) {
                $secondaryName = [string]$secondary
                if (-not [string]::IsNullOrWhiteSpace($secondaryName) -and $KnownSkills -notcontains $secondaryName) {
                    $conflicts.Add("$domainName/$classId unknown secondary_skill: $secondaryName")
                }
            }

            foreach ($signal in @($class.request_signals)) {
                $normalizedSignal = ([string]$signal).Trim().ToLowerInvariant()
                if ([string]::IsNullOrWhiteSpace($normalizedSignal)) {
                    $conflicts.Add("$domainName/$classId contains empty request_signal")
                    continue
                }

                if ($signalOwners.ContainsKey($normalizedSignal)) {
                    $conflicts.Add("duplicate request_signal '$signal' in $($signalOwners[$normalizedSignal]) and $domainName/$classId")
                } else {
                    $signalOwners[$normalizedSignal] = "$domainName/$classId"
                }
            }
        }
    }

    [PSCustomObject]@{
        Exists           = $true
        Path             = $matrixPath
        DomainCount      = $domainCount
        ClassCount       = $classCount
        ConflictMessages = @($conflicts)
    }
}

function Repair-Frontmatter {
    param(
        [System.IO.FileInfo]$File,
        [string[]]$Lines
    )

    if ($Lines.Count -eq 0) {
        return $false
    }

    $mutated = $false
    $newLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $Lines) {
        $newLines.Add($line)
    }

    if ($newLines[0] -ne '---' -and $newLines[0] -match '^(name|description|version|triggers|benefits-from|license|metadata):') {
        $newLines.Insert(0, '---')
        $mutated = $true
    }

    $endIndex = $null
    for ($i = 1; $i -lt $newLines.Count; $i++) {
        if ($newLines[$i] -eq '---') {
            $endIndex = $i
            break
        }
        if ($newLines[$i] -eq '--') {
            $newLines[$i] = '---'
            $endIndex = $i
            $mutated = $true
            break
        }
    }

    if ($null -eq $endIndex) {
        for ($i = 1; $i -lt $newLines.Count; $i++) {
            if ($newLines[$i] -notmatch '^\s*$' -and $newLines[$i] -notmatch '^[A-Za-z0-9_-]+:') {
                $newLines.Insert($i, '---')
                $endIndex = $i
                $mutated = $true
                break
            }
        }
    }

    if (-not $mutated) {
        return $false
    }

    if ($PSCmdlet.ShouldProcess($File.FullName, 'Normalize SKILL frontmatter')) {
        Set-Content -LiteralPath $File.FullName -Value $newLines -Encoding UTF8
    }

    return $true
}

function New-AuditRecord {
    param(
        [System.IO.FileInfo]$File
    )

    $lines = @(Get-Content -LiteralPath $File.FullName)
    $text = if ($lines.Count -gt 0) { $lines -join "`n" } else { '' }
    $frontmatter = Get-FrontmatterStatus -Lines $lines
    $unsupported = @(Get-UnsupportedTokens -Text $text)
    $foreign = @(Get-ForeignRuntimeHits -Text $text)
    $missingRefs = @(Get-MissingLocalReferences -Text $text -SkillDirectory $File.DirectoryName)
    $manifestStatus = Get-ResourceManifestStatus -SkillDirectory $File.DirectoryName
    $structureStatus = Get-StandardStructureStatus -Text $text

    [PSCustomObject]@{
        Skill                  = Split-Path $File.DirectoryName -Leaf
        Path                   = $File.FullName
        LineCount              = $lines.Count
        OverLineThreshold      = ($lines.Count -gt $LineThreshold)
        FrontmatterStarts      = $frontmatter.StartsCorrectly
        FrontmatterEnds        = $frontmatter.EndsCorrectly
        HasName                = $frontmatter.HasName
        HasDescription         = $frontmatter.HasDescription
        HasResourceManifest    = $manifestStatus.Exists
        ResourceManifestPath   = $manifestStatus.Path
        ManifestMissingDependencies = $manifestStatus.MissingDeclaredDependencies
        StandardStructureCompliant = $structureStatus.IsCompliant
        MissingStandardSections = $structureStatus.MissingSections
        StandardSectionsOrdered = $structureStatus.Ordered
        UnsupportedTools       = $unsupported
        ForeignRuntimePatterns = $foreign
        MissingLocalReferences = $missingRefs
    }
}

$skillFiles = @(Get-SkillFiles)

if ($Mode -eq 'FixFrontmatter') {
    $fixed = 0
    foreach ($file in $skillFiles) {
        $lines = Get-Content -LiteralPath $file.FullName
        if (Repair-Frontmatter -File $file -Lines $lines) {
            $fixed++
        }
    }
    Write-Host "Frontmatter fixes applied: $fixed"
}

$records = @(
    foreach ($file in $skillFiles) {
        New-AuditRecord -File $file
    }
)

$triggerOwnershipStatus = Get-TriggerOwnershipStatus -RootPath $Root -KnownSkills @($records | ForEach-Object { $_.Skill })

$summary = [PSCustomObject]@{
    Root                       = $Root
    SkillCount                 = $records.Count
    FrontmatterFailures        = @($records | Where-Object { -not $_.FrontmatterStarts -or -not $_.FrontmatterEnds -or -not $_.HasName -or -not $_.HasDescription }).Count
    OversizedSkills            = @($records | Where-Object { $_.OverLineThreshold }).Count
    SkillsMissingResourceManifest = @($records | Where-Object { -not $_.HasResourceManifest }).Count
    SkillsWithManifestDependencyIssues = @($records | Where-Object { $_.ManifestMissingDependencies.Count -gt 0 }).Count
    SkillsMissingStandardSections = @($records | Where-Object { -not $_.StandardStructureCompliant }).Count
    SkillsWithUnsupportedTools = @($records | Where-Object { $_.UnsupportedTools.Count -gt 0 }).Count
    SkillsWithForeignRuntime   = @($records | Where-Object { $_.ForeignRuntimePatterns.Count -gt 0 }).Count
    SkillsWithMissingRefs      = @($records | Where-Object { $_.MissingLocalReferences.Count -gt 0 }).Count
    TriggerOwnershipClasses    = $triggerOwnershipStatus.ClassCount
    TriggerOwnershipConflicts  = @($triggerOwnershipStatus.ConflictMessages).Count
}

$gateFailures = [System.Collections.Generic.List[string]]::new()
if ($summary.FrontmatterFailures -gt 0) {
    $gateFailures.Add("frontmatter_failures=$($summary.FrontmatterFailures)")
}
if ($summary.OversizedSkills -gt 0) {
    $gateFailures.Add("oversized_skills=$($summary.OversizedSkills)")
}
if ($summary.SkillsMissingResourceManifest -gt 0) {
    $gateFailures.Add("missing_resource_manifests=$($summary.SkillsMissingResourceManifest)")
}
if ($summary.SkillsWithManifestDependencyIssues -gt 0) {
    $gateFailures.Add("manifest_dependency_issues=$($summary.SkillsWithManifestDependencyIssues)")
}
if ($summary.SkillsWithUnsupportedTools -gt 0) {
    $gateFailures.Add("unsupported_tools=$($summary.SkillsWithUnsupportedTools)")
}
if ($summary.SkillsWithForeignRuntime -gt 0) {
    $gateFailures.Add("foreign_runtime_paths=$($summary.SkillsWithForeignRuntime)")
}
if ($summary.SkillsWithMissingRefs -gt 0) {
    $gateFailures.Add("missing_local_references=$($summary.SkillsWithMissingRefs)")
}
if ($summary.TriggerOwnershipConflicts -gt 0) {
    $gateFailures.Add("trigger_ownership_conflicts=$($summary.TriggerOwnershipConflicts)")
}

$summary | Format-List
$records |
    Sort-Object Skill |
    Select-Object Skill, LineCount, FrontmatterStarts, FrontmatterEnds, HasName, HasDescription, HasResourceManifest, StandardStructureCompliant, OverLineThreshold |
    Format-Table -AutoSize

if ($Mode -eq 'Report') {
    if (-not (Test-Path -LiteralPath $ReportDir)) {
        New-Item -ItemType Directory -Path $ReportDir | Out-Null
    }

    $jsonPath = Join-Path $ReportDir 'skills-audit.json'
    $mdPath = Join-Path $ReportDir 'skills-audit.md'

    [PSCustomObject]@{
        Summary = $summary
        Records = $records
        TriggerOwnership = $triggerOwnershipStatus
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    $md = [System.Collections.Generic.List[string]]::new()
    $md.Add('# Skills Audit Report')
    $md.Add('')
    $md.Add(('Root: `' + $Root + '`'))
    $md.Add('')
    $md.Add('## Summary')
    $md.Add('')
    $md.Add("- Skill count: $($summary.SkillCount)")
    $md.Add("- Frontmatter failures: $($summary.FrontmatterFailures)")
    $md.Add("- Oversized skills: $($summary.OversizedSkills)")
    $md.Add("- Skills missing resource manifests: $($summary.SkillsMissingResourceManifest)")
    $md.Add("- Skills with manifest dependency issues: $($summary.SkillsWithManifestDependencyIssues)")
    $md.Add("- Skills missing standard sections: $($summary.SkillsMissingStandardSections)")
    $md.Add("- Skills with unsupported tools: $($summary.SkillsWithUnsupportedTools)")
    $md.Add("- Skills with foreign runtime paths: $($summary.SkillsWithForeignRuntime)")
    $md.Add("- Skills with missing local references: $($summary.SkillsWithMissingRefs)")
    $md.Add("- Trigger ownership classes: $($summary.TriggerOwnershipClasses)")
    $md.Add("- Trigger ownership conflicts: $($summary.TriggerOwnershipConflicts)")
    $md.Add('')
    $md.Add('## Trigger Ownership')
    $md.Add('')
    $md.Add(('- Matrix: `' + $triggerOwnershipStatus.Path + '`'))
    $md.Add(('- Domains: ' + $triggerOwnershipStatus.DomainCount))
    $md.Add(('- Classes: ' + $triggerOwnershipStatus.ClassCount))
    $md.Add(('- Conflicts: ' + $(if ($triggerOwnershipStatus.ConflictMessages.Count) { $triggerOwnershipStatus.ConflictMessages -join '; ' } else { 'none' })))
    $md.Add('')
    $md.Add('## Records')
    $md.Add('')

    foreach ($record in ($records | Sort-Object Skill)) {
        $md.Add("### $($record.Skill)")
        $md.Add('')
        $md.Add(('- Path: `' + $record.Path + '`'))
        $md.Add("- Line count: $($record.LineCount)")
        $md.Add("- Frontmatter: start=$($record.FrontmatterStarts), end=$($record.FrontmatterEnds), name=$($record.HasName), description=$($record.HasDescription)")
        $md.Add("- Resource manifest: $(if ($record.HasResourceManifest) { 'present' } else { 'missing' })")
        $md.Add("- Manifest dependency issues: $(if ($record.ManifestMissingDependencies.Count) { $record.ManifestMissingDependencies -join ', ' } else { 'none' })")
        $md.Add("- Standard structure: $(if ($record.StandardStructureCompliant) { 'compliant' } else { 'drift' })")
        $md.Add("- Missing standard sections: $(if ($record.MissingStandardSections.Count) { $record.MissingStandardSections -join ', ' } else { 'none' })")
        $md.Add("- Unsupported tools: $(if ($record.UnsupportedTools.Count) { $record.UnsupportedTools -join ', ' } else { 'none' })")
        $md.Add("- Foreign runtime paths: $(if ($record.ForeignRuntimePatterns.Count) { $record.ForeignRuntimePatterns -join ', ' } else { 'none' })")
        $md.Add("- Missing local references: $(if ($record.MissingLocalReferences.Count) { $record.MissingLocalReferences -join ', ' } else { 'none' })")
        $md.Add('')
    }

    Set-Content -LiteralPath $mdPath -Value $md -Encoding UTF8
    Write-Host "Report written:"
    Write-Host "  $jsonPath"
    Write-Host "  $mdPath"
}

if ($Mode -eq 'Gate') {
    if ($gateFailures.Count -gt 0) {
        Write-Error ("Skill audit gate failed: " + ($gateFailures -join '; '))
        exit 1
    }

    Write-Host 'Skill audit gate passed.'
    exit 0
}
