param(
    [ValidateSet('Inspect', 'Start')][string]$Mode,
    [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$TaskName = 'Codex-Garmin-Health-Sync'
)

$ErrorActionPreference = 'Stop'

if ($Mode -eq 'Start') {
    Start-ScheduledTask -TaskName $TaskName -TaskPath '\'
    [ordered]@{ ok = $true; status = 'start_requested' } | ConvertTo-Json -Compress
    exit 0
}

try {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
    $action = if ($task.Actions.Count -eq 1) { $task.Actions[0] } else { $null }
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    try {
        $taskUserSid = if ([string]$task.Principal.UserId -match '^S-1-') {
            ([Security.Principal.SecurityIdentifier]::new([string]$task.Principal.UserId)).Value
        } else {
            ([Security.Principal.NTAccount]::new([string]$task.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
        }
    } catch {
        $taskUserSid = $null
    }
    $argumentHash = if ($action) {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            -join ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$action.Arguments)) | ForEach-Object { $_.ToString('x2') })
        } finally { $hasher.Dispose() }
    } else { $null }
    [ordered]@{
        ok = $true
        exists = $true
        task_name = $task.TaskName
        task_path = $task.TaskPath
        state = [string]$task.State
        enabled = [bool]$task.Settings.Enabled
        current_identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        current_sid = $currentSid
        user_id = [string]$task.Principal.UserId
        task_user_sid = $taskUserSid
        run_level = [string]$task.Principal.RunLevel
        logon_type = [string]$task.Principal.LogonType
        multiple_instances = [string]$task.Settings.MultipleInstances
        start_when_available = [bool]$task.Settings.StartWhenAvailable
        action_count = $task.Actions.Count
        execute = if ($action) { [string]$action.Execute } else { $null }
        arguments = if ($action) { [string]$action.Arguments } else { $null }
        arguments_sha256 = $argumentHash
        working_directory = if ($action) { [string]$action.WorkingDirectory } else { $null }
    } | ConvertTo-Json -Compress
} catch [Microsoft.Management.Infrastructure.CimException] {
    $category = [string]$_.CategoryInfo.Category
    $fqid = [string]$_.FullyQualifiedErrorId
    $hresult = '0x' + [Convert]::ToString([int]$_.Exception.HResult, 16)
    if ($category -eq 'ObjectNotFound' -or $fqid -match '0x80070002' -or $hresult -eq '0x80070002') {
        [ordered]@{ ok = $true; exists = $false; task_name = $TaskName; reason = 'task_missing' } | ConvertTo-Json -Compress
        exit 0
    }
    $errorCode = if ($category -eq 'PermissionDenied' -or $fqid -match '0x80041003' -or $hresult -eq '0x80041003') {
        'task_probe_permission_denied'
    } else {
        'task_probe_failed'
    }
    [ordered]@{ ok = $false; exists = $null; task_name = $TaskName; error_code = $errorCode } | ConvertTo-Json -Compress
    exit 2
} catch {
    [ordered]@{ ok = $false; exists = $null; task_name = $TaskName; error_code = 'task_probe_failed' } | ConvertTo-Json -Compress
    exit 2
}
