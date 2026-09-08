# Registers Task Scheduler tasks that start the MAD DAY services at Windows
# startup and restart them automatically if they crash.

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$PythonExe  = Join-Path $ProjectDir ".venv\Scripts\python.exe"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

$Tasks = @(
    @{ Name = "MadDay-TelegramBot"; Script = "bot.py" },
    @{ Name = "MadDay-VkBot"; Script = "vk_bot.py" },
    @{ Name = "MadDay-WebForm"; Script = "web_form.py" }
)

foreach ($t in $Tasks) {
    $ScriptPath = Join-Path $ProjectDir $t.Script
    $Action = New-ScheduledTaskAction -Execute $PythonExe -Argument ('"' + $ScriptPath + '"') -WorkingDirectory $ProjectDir
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName $t.Name -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
    Write-Host "Task '$($t.Name)' registered."
}

# Public tunnel for the web form via serveo.net (SSH reverse tunnel, no
# account/signup needed - Cloudflare Tunnel does not work on this network).
# The public URL is random and changes every restart - read it from
# serveo.log after (re)start.
$TunnelScript = Join-Path $ProjectDir "run_tunnel.ps1"
$TunnelAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $TunnelScript + '"') `
    -WorkingDirectory $ProjectDir
$TunnelTrigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "MadDay-WebTunnel" -Action $TunnelAction -Trigger $TunnelTrigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host "Task 'MadDay-WebTunnel' registered."
