#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$WindowsUser,
    [string]$DistroName = 'CatsBot',
    [string]$HostDirectory = 'D:\WSL\CatsBot\host',
    [switch]$StartNow
)

$ErrorActionPreference = 'Stop'
$taskName = 'CatsBot-WSL-Autostart'
$taskResult = Join-Path $PSScriptRoot '.local\autostart-result.json'

try {
    New-Item -ItemType Directory -Path $HostDirectory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start-CatsBot.ps1') -Destination $HostDirectory -Force
    $taskLauncher = Join-Path $HostDirectory 'Start-CatsBot.ps1'
    $taskArguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -DistroName "{1}"' -f $taskLauncher, $DistroName
    $taskAction = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $taskArguments -WorkingDirectory $HostDirectory
    $taskTrigger = New-ScheduledTaskTrigger -AtStartup
    $taskTrigger.Delay = 'PT30S'
    # WSL distributions belong to a Windows SID. S4U runs that user's task at
    # system boot without an interactive session or storing the user's password.
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType S4U -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description 'Starts the dedicated CatsBot WSL distribution at Windows boot, without user logon, and keeps it running.' -Force | Out-Null
    if ($StartNow) {
        Start-ScheduledTask -TaskName $taskName
    }
    @{ Success = $true; TaskName = $taskName; WindowsUser = $WindowsUser; CompletedAt = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $taskResult -Encoding UTF8
}
catch {
    @{ Success = $false; Error = $_.Exception.Message; CompletedAt = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $taskResult -Encoding UTF8
    throw
}
