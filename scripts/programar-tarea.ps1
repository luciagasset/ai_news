# Programa la actualización diaria de AI News en el Programador de tareas de Windows: cada día a las 07:07.
# - Despierta el ordenador si está en suspensión (WakeToRun).
# - Si a esa hora estaba apagado, se ejecuta en cuanto se enciende (StartWhenAvailable) y recupera los días que falten.
# - Se ejecuta con la sesión de Windows de Lucía, que es la que tiene iniciada Claude Code y las credenciales de GitHub.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\programar-tarea.ps1      (para quitarla: -Quitar)
param([switch]$Quitar)

$name = "AI News - actualizacion diaria"
if ($Quitar) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Output "Tarea eliminada."
    return
}

$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute (Join-Path $root ".venv\Scripts\pythonw.exe") `
    -Argument "scripts\daily.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At "07:07"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Incorpora las noticias de IA del dia anterior y publica la web (scripts\daily.py). Registro en logs\diario.log." `
    -Force | Out-Null
$info = Get-ScheduledTaskInfo -TaskName $name
Write-Output "Tarea '$name' programada. Proxima ejecucion: $($info.NextRunTime)"
