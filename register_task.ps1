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

# The web form (port 8080) is published to the internet via the router's
# built-in Keenetic KeenDNS remote-access feature (Settings -> Домен ->
# KeenDNS -> "Доступ к веб-приложениям"), not a PC-side tunnel. No extra
# task is needed here for that.
