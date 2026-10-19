param(
    [ValidateSet('Inspect', 'Start')][string]$Mode,
    [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$TaskName = 'Codex-Garmin-Health-Sync'
)

$ErrorActionPreference = 'Stop'

function Get-TaskProbeErrorCode {
    param([System.Management.Automation.ErrorRecord]$Record)
    $category = [string]$Record.CategoryInfo.Category
    $fqid = [string]$Record.FullyQualifiedErrorId
    $hresult = '0x' + [Convert]::ToString([int]$Record.Exception.HResult, 16)
    # PowerShell's scheduled-task cmdlet uses CimJobException, not only
    # CimException. Recognize its exact not-found signal, never all errors.
    if ($category -eq 'ObjectNotFound' -and
        $fqid -match '^CmdletizationQuery_NotFound(?:_[^,]+)?,Get-ScheduledTask$') {
        return 'task_missing'
    }
    if ($category -eq 'PermissionDenied' -or $fqid -match '0x80041003' -or $hresult -eq '0x80041003') {
        return 'task_probe_permission_denied'
    }
    return 'task_probe_failed'
}

if ($Mode -eq 'Start') {
    Start-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop
    [ordered]@{ ok = $true; status = 'start_requested' } | ConvertTo-Json -Compress
    exit 0
}

try {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop
    if ($null -eq $task) { throw 'task_probe_empty_result' }
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
} catch {
    $errorCode = Get-TaskProbeErrorCode -Record $_
    if ($errorCode -eq 'task_missing') {
        [ordered]@{ ok = $true; exists = $false; task_name = $TaskName; reason = 'task_missing' } | ConvertTo-Json -Compress
        exit 0
    }
    [ordered]@{ ok = $false; exists = $null; task_name = $TaskName; error_code = $errorCode } | ConvertTo-Json -Compress
    exit 2
}
