param(
    [string]$TaskName = 'Codex-Garmin-Health-Sync',
    [string]$DailyAt = '06:30',
    [ValidateRange(1, 31)][int]$Days = 7,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$ConfigDir,
    [Parameter(Mandatory = $true)][string]$StateRoot,
    [Parameter(Mandatory = $true)][string]$ScratchRoot
)

$ErrorActionPreference = 'Stop'

if ($TaskName -notmatch '^[A-Za-z0-9_.-]{1,64}$') {
    throw 'TaskName must contain only letters, digits, dot, underscore, or hyphen.'
}

$python = [IO.Path]::GetFullPath($PythonPath)
$config = [IO.Path]::GetFullPath($ConfigDir)
$state = [IO.Path]::GetFullPath($StateRoot)
$scratch = [IO.Path]::GetFullPath($ScratchRoot)
$runner = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'garmin_auto_sync.py'))

foreach ($required in @($python, $config, $runner)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required path is missing: $required"
    }
}

New-Item -ItemType Directory -Force -Path $state, $scratch | Out-Null
$stateFile = Join-Path $state 'status.json'
$arguments = @(
    '-B',
    ('"{0}"' -f $runner),
    '--days', $Days,
    '--config-dir', ('"{0}"' -f $config),
    '--garmindb-python', ('"{0}"' -f $python),
    '--scratch-dir', ('"{0}"' -f $scratch),
    '--state-output', ('"{0}"' -f $stateFile),
    '--timeout-seconds', '600',
    '--allow-network', '--allow-sync', '--allow-health-data'
) -join ' '

$at = [datetime]::ParseExact($DailyAt, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory (Split-Path -Parent $runner)
$trigger = New-ScheduledTaskTrigger -Daily -At $at
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Description 'Bounded daily Garmin health-data sync for the current user.' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
$info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath '\'
[ordered]@{
    status = 'registered'
    task_name = $task.TaskName
    task_path = $task.TaskPath
    state = [string]$task.State
    next_run_time = $info.NextRunTime
    execute = $task.Actions.Execute
    arguments_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($task.Actions.Arguments))).ToLowerInvariant()
    logon_type = [string]$task.Principal.LogonType
    run_level = [string]$task.Principal.RunLevel
    start_when_available = $task.Settings.StartWhenAvailable
    multiple_instances = [string]$task.Settings.MultipleInstances
} | ConvertTo-Json -Compress
