[CmdletBinding()]
param(
    [ValidateSet('Audit', 'Report', 'Gate')]
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
    $Root = Split-Path -Parent $PSScriptRoot
}
$Root = (Resolve-Path -LiteralPath $Root).Path

if ([string]::IsNullOrWhiteSpace($ReportDir)) {
    $ReportDir = Join-Path $Root 'reports'
}

$DeprecatedPatterns = [ordered]@{
    invoke_subagent = '(?i)\binvoke_subagent\b'
    call_mcp_tool = '(?i)\bcall_mcp_tool\b'
    run_command = '(?i)\brun_command\b'
    write_to_file = '(?i)\bwrite_to_file\b'
    view_file = '(?i)\bview_file\b'
    ask_question = '(?i)\bask_question\b'
    generate_image = '(?i)\bgenerate_image\b'
    mcp_vector_lake = '(?i)\bmcp_vector-lake\b'
    vector_lake_mcp = '(?i)\bvector-lake-mcp\b'
    request_feedback = '(?i)RequestFeedback\s*='
}

$ForeignRuntimePatterns = [ordered]@{
    gemini_path = '(?i)(?:[A-Z]:\\Users\\[^\s`"''<>]+\\\.gemini|\.gemini[\\/])'
    kimi_path = '(?i)(?:/app/\.kimi|\.kimi[\\/])'
    app_data_macro = '(?i)<appDataDir>'
    conversation_brain = '(?i)brain[\\/]<(?:conversation-)?id>'
    file_uri = '(?i)file:///'
    antigravity = '(?i)Antigravity'
    v11_runtime = '(?i)\bV11(?:\.\d+)?\b'
    ir_native = '(?i)IR Native'
    fable_runtime = '(?i)Fable\s*5'
}

$ForbiddenReasoningPatterns = [ordered]@{
    thought_xml = '(?i)<\/?thought>'
    thinking_xml = '(?i)<\/?thinking>'
    reasoning_draft = '(?i)(\u601D\u7EF4\u7A3F|\u63A8\u7406\u8349\u7A3F|\u5185\u90E8\u63A8\u7406|chain[- ]of[- ]thought)'
}

$HardcodedModelPatterns = [ordered]@{
    openai_version = '(?i)\bgpt-[0-9][A-Za-z0-9._-]*'
    gemini_version = '(?i)\bgemini-[0-9][A-Za-z0-9._-]*'
    claude_version = '(?i)\bclaude-(?:[0-9]|opus|sonnet|haiku)[A-Za-z0-9._-]*'
}

$MandatorySubagentPattern = '(?im)^\s*(?:[-*]\s*)?(?:\u5FC5\u987B|\u5F3A\u5236|\u52A1\u5FC5|must|required)[^\r\n]{0,80}(?:\u5B50\u4EE3\u7406|subagent)'
$MandatoryPersistencePattern = '(?im)^\s*(?:[-*]\s*)?(?:\u5FC5\u987B|\u5F3A\u5236|\u52A1\u5FC5|must|required)[^\r\n]{0,100}(?:Vector Lake|\u5165\u6E56|MEMORY|\u77E5\u8BC6\u5E93|\u6301\u4E45\u5316|persist)'

function Get-SkillDirectories {
    Get-ChildItem -LiteralPath $Root -Directory |
        Where-Object {
            $_.Name -notin @('.system', 'scripts', 'shared', 'reports') -and
            (Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md'))
        } |
        Where-Object {
            (-not $IncludeSkills -or $_.Name -in $IncludeSkills) -and
            $_.Name -notin $ExcludeSkills
        } |
        Sort-Object Name
}

function Get-PatternHits {
    param(
        [string]$Text,
        [System.Collections.IDictionary]$Patterns
    )

    foreach ($entry in $Patterns.GetEnumerator()) {
        if ($Text -match $entry.Value) {
            $entry.Key
        }
    }
}

function Get-SkillTextCorpus {
    param([string]$SkillDirectory)

    $extensions = @('.md', '.txt', '.py', '.ps1', '.js', '.ts', '.mjs', '.json', '.yaml', '.yml', '.html', '.css', '.toml')
    $parts = foreach ($file in Get-ChildItem -LiteralPath $SkillDirectory -Recurse -File -ErrorAction SilentlyContinue) {
        if ($file.Name -eq 'resource-manifest.json' -or $file.Name -match '^(?:package-lock|pnpm-lock|yarn\.lock)') {
            continue
        }
        if ($file.Extension.ToLowerInvariant() -notin $extensions) {
            continue
        }
        try {
            [IO.File]::ReadAllText($file.FullName)
        } catch {
            continue
        }
    }
    $parts -join "`n"
}

function Get-FrontmatterStatus {
    param(
        [string[]]$Lines,
        [string]$DirectoryName
    )

    $endIndex = -1
    if ($Lines.Count -gt 1 -and $Lines[0] -eq '---') {
        for ($i = 1; $i -lt $Lines.Count; $i++) {
            if ($Lines[$i] -eq '---') {
                $endIndex = $i
                break
            }
        }
    }

    $keys = @()
    $name = ''
    $description = ''
    if ($endIndex -gt 0) {
        foreach ($line in $Lines[1..($endIndex - 1)]) {
            if ($line -match '^(?<key>[A-Za-z][A-Za-z0-9_-]*):\s*(?<value>.*)$') {
                $key = $Matches.key
                $value = $Matches.value.Trim().Trim([char]39).Trim([char]34)
                $keys += $key
                if ($key -eq 'name') { $name = $value }
                if ($key -eq 'description') { $description = $value }
            }
        }
    }

    $unexpected = @($keys | Where-Object { $_ -notin @('name', 'description') } | Sort-Object -Unique)
    $duplicate = @($keys | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
    $nameValid = $name -match '^[a-z0-9]+(?:-[a-z0-9]+)*$' -and $name.Length -le 64 -and $name -eq $DirectoryName
    $descriptionValid = $description.Length -ge 1 -and $description.Length -le 1024
    $hasTriggerContext = $description -match '(\u5F53|\u7528\u4E8E|\u9002\u5408|\u7528\u6237.{0,12}(?:\u8981\u6C42|\u9700\u8981)|Use when|Use this skill|when Codex)'

    [PSCustomObject]@{
        Starts = $Lines.Count -gt 0 -and $Lines[0] -eq '---'
        Ends = $endIndex -gt 0
        Name = $name
        Description = $description
        Keys = $keys
        UnexpectedKeys = $unexpected
        DuplicateKeys = $duplicate
        NameValid = $nameValid
        DescriptionValid = $descriptionValid
        HasTriggerContext = $hasTriggerContext
    }
}

function Get-ManifestStatus {
    param([string]$SkillDirectory)

    $path = Join-Path $SkillDirectory 'resource-manifest.json'
    if (-not (Test-Path -LiteralPath $path)) {
        return [PSCustomObject]@{ Exists = $false; ParseError = $false; Missing = @() }
    }

    try {
        $manifest = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $missing = if ($null -eq $manifest.missing_declared_dependencies) {
            @()
        } else {
            @($manifest.missing_declared_dependencies)
        }
        [PSCustomObject]@{ Exists = $true; ParseError = $false; Missing = $missing }
    } catch {
        [PSCustomObject]@{ Exists = $true; ParseError = $true; Missing = @('__PARSE_ERROR__') }
    }
}

function Get-TriggerOwnershipStatus {
    param([string[]]$KnownSkills)

    $path = Join-Path $Root 'shared\trigger-ownership-matrix.json'
    if (-not (Test-Path -LiteralPath $path)) {
        return [PSCustomObject]@{ Exists = $false; ClassCount = 0; Conflicts = @('__MISSING_MATRIX__') }
    }

    try {
        $matrix = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return [PSCustomObject]@{ Exists = $true; ClassCount = 0; Conflicts = @('__PARSE_ERROR__') }
    }

    $conflicts = [System.Collections.Generic.List[string]]::new()
    $owners = @{}
    $classCount = 0

    foreach ($domain in @($matrix.domains)) {
        foreach ($class in @($domain.classes)) {
            $classCount++
            $location = "$($domain.domain)/$($class.id)"
            $primary = [string]$class.primary_skill
            if ($KnownSkills -notcontains $primary) {
                $conflicts.Add("$location unknown primary_skill: $primary")
            }
            foreach ($secondary in @($class.secondary_skills)) {
                if ($KnownSkills -notcontains [string]$secondary) {
                    $conflicts.Add("$location unknown secondary_skill: $secondary")
                }
            }
            foreach ($signal in @($class.request_signals)) {
                $normalized = ([string]$signal).Trim().ToLowerInvariant()
                if ([string]::IsNullOrWhiteSpace($normalized)) {
                    $conflicts.Add("$location contains empty request_signal")
                } elseif ($owners.ContainsKey($normalized)) {
                    $conflicts.Add("duplicate request_signal '$signal' in $($owners[$normalized]) and $location")
                } else {
                    $owners[$normalized] = $location
                }
            }
        }
    }

    [PSCustomObject]@{ Exists = $true; ClassCount = $classCount; Conflicts = @($conflicts) }
}

$skillDirectories = @(Get-SkillDirectories)
$records = foreach ($directory in $skillDirectories) {
    $skillPath = Join-Path $directory.FullName 'SKILL.md'
    $lines = @(Get-Content -LiteralPath $skillPath -Encoding UTF8)
    $text = $lines -join "`n"
    $corpus = Get-SkillTextCorpus -SkillDirectory $directory.FullName
    $frontmatter = Get-FrontmatterStatus -Lines $lines -DirectoryName $directory.Name
    $manifest = Get-ManifestStatus -SkillDirectory $directory.FullName

    [PSCustomObject]@{
        Skill = $directory.Name
        Path = $skillPath
        LineCount = $lines.Count
        FrontmatterValid = (
            $frontmatter.Starts -and
            $frontmatter.Ends -and
            $frontmatter.NameValid -and
            $frontmatter.DescriptionValid -and
            $frontmatter.HasTriggerContext -and
            $frontmatter.UnexpectedKeys.Count -eq 0 -and
            $frontmatter.DuplicateKeys.Count -eq 0 -and
            $frontmatter.Keys.Count -eq 2
        )
        FrontmatterKeys = @($frontmatter.Keys)
        UnexpectedFrontmatterKeys = @($frontmatter.UnexpectedKeys)
        Name = $frontmatter.Name
        DescriptionHasTriggerContext = $frontmatter.HasTriggerContext
        HasResourceManifest = $manifest.Exists
        ManifestIssues = @($manifest.Missing)
        DeprecatedTokens = @(Get-PatternHits -Text $corpus -Patterns $DeprecatedPatterns)
        ForeignRuntime = @(Get-PatternHits -Text $corpus -Patterns $ForeignRuntimePatterns)
        ReasoningDirectives = @(Get-PatternHits -Text $corpus -Patterns $ForbiddenReasoningPatterns)
        HardcodedModels = @(Get-PatternHits -Text $corpus -Patterns $HardcodedModelPatterns)
        MandatorySubagent = [bool]($corpus -match $MandatorySubagentPattern)
        MandatoryPersistence = [bool]($corpus -match $MandatoryPersistencePattern)
    }
}

$readmePath = Join-Path $Root 'README.md'
$declaredInventory = 0
if (Test-Path -LiteralPath $readmePath) {
    $readmeText = Get-Content -LiteralPath $readmePath -Raw -Encoding UTF8
    if ($readmeText -match '\u5F53\u524D\u5E93\u5B58\u4E3A\s*(?<count>\d+)\s*\u4E2A\u7528\u6237\u6280\u80FD') {
        $declaredInventory = [int]$Matches.count
    }
}

$skillJsonFiles = @(
    Get-ChildItem -LiteralPath $Root -Recurse -Filter 'skill.json' -File |
        Where-Object { $_.FullName -notmatch '[\\/]\.system[\\/]' }
)
$nodeModules = @(
    Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter 'node_modules' -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '[\\/]\.system[\\/]' }
)
$triggerStatus = Get-TriggerOwnershipStatus -KnownSkills @($records.Skill)

$summary = [PSCustomObject]@{
    Root = $Root
    DeclaredInventory = $declaredInventory
    SkillCount = $records.Count
    InventoryMismatch = $declaredInventory -ne $records.Count
    FrontmatterFailures = @($records | Where-Object { -not $_.FrontmatterValid }).Count
    OversizedSkills = @($records | Where-Object LineCount -gt $LineThreshold).Count
    MissingResourceManifests = @($records | Where-Object { -not $_.HasResourceManifest }).Count
    ManifestDependencyIssues = @($records | Where-Object { $_.ManifestIssues.Count -gt 0 }).Count
    DeprecatedToolSkills = @($records | Where-Object { $_.DeprecatedTokens.Count -gt 0 }).Count
    ForeignRuntimeSkills = @($records | Where-Object { $_.ForeignRuntime.Count -gt 0 }).Count
    ReasoningDirectiveSkills = @($records | Where-Object { $_.ReasoningDirectives.Count -gt 0 }).Count
    HardcodedModelSkills = @($records | Where-Object { $_.HardcodedModels.Count -gt 0 }).Count
    MandatorySubagentSkills = @($records | Where-Object MandatorySubagent).Count
    MandatoryPersistenceSkills = @($records | Where-Object MandatoryPersistence).Count
    SkillJsonFiles = $skillJsonFiles.Count
    NodeModulesDirectories = $nodeModules.Count
    TriggerOwnershipClasses = $triggerStatus.ClassCount
    TriggerOwnershipConflicts = @($triggerStatus.Conflicts).Count
}

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($entry in @(
    @{ Name = 'inventory_mismatch'; Value = [int]$summary.InventoryMismatch },
    @{ Name = 'frontmatter_failures'; Value = $summary.FrontmatterFailures },
    @{ Name = 'oversized_skills'; Value = $summary.OversizedSkills },
    @{ Name = 'missing_resource_manifests'; Value = $summary.MissingResourceManifests },
    @{ Name = 'manifest_dependency_issues'; Value = $summary.ManifestDependencyIssues },
    @{ Name = 'deprecated_tool_skills'; Value = $summary.DeprecatedToolSkills },
    @{ Name = 'foreign_runtime_skills'; Value = $summary.ForeignRuntimeSkills },
    @{ Name = 'reasoning_directive_skills'; Value = $summary.ReasoningDirectiveSkills },
    @{ Name = 'hardcoded_model_skills'; Value = $summary.HardcodedModelSkills },
    @{ Name = 'mandatory_subagent_skills'; Value = $summary.MandatorySubagentSkills },
    @{ Name = 'mandatory_persistence_skills'; Value = $summary.MandatoryPersistenceSkills },
    @{ Name = 'skill_json_files'; Value = $summary.SkillJsonFiles },
    @{ Name = 'node_modules_directories'; Value = $summary.NodeModulesDirectories },
    @{ Name = 'trigger_ownership_conflicts'; Value = $summary.TriggerOwnershipConflicts }
)) {
    if ($entry.Value -gt 0) {
        $failures.Add("$($entry.Name)=$($entry.Value)")
    }
}

$summary | Format-List
$records |
    Select-Object Skill, LineCount, FrontmatterValid, HasResourceManifest, MandatorySubagent, MandatoryPersistence |
    Format-Table -AutoSize

if ($Mode -eq 'Report') {
    if (-not (Test-Path -LiteralPath $ReportDir)) {
        New-Item -ItemType Directory -Path $ReportDir | Out-Null
    }
    [PSCustomObject]@{
        Summary = $summary
        Records = $records
        TriggerOwnership = $triggerStatus
    } | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $ReportDir 'skills-audit.json') -Encoding UTF8
}

if ($Mode -eq 'Gate') {
    if ($failures.Count -gt 0) {
        Write-Error ('Skill audit gate failed: ' + ($failures -join '; '))
        exit 1
    }
    Write-Host 'Skill audit gate passed.'
}
