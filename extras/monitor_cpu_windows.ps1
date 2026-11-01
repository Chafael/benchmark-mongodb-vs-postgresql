# Monitor de CPU del host (Windows). Corre en PowerShell MIENTRAS corre la matriz en WSL.
# Registra cada 5 s el rendimiento real del procesador, su frecuencia y la temperatura.
# Si la laptop se calienta y baja la velocidad (thermal throttling), las mediciones de esas
# celdas quedan contaminadas; extras/analizar_resultados.py las marca.
#
# Uso (en PowerShell, desde la carpeta del repo):
#   powershell -ExecutionPolicy Bypass -File extras\monitor_cpu_windows.ps1
# Detener con Ctrl+C. El archivo queda en extras\monitor_cpu.csv
#
# Se usan clases WMI/CIM en lugar de Get-Counter porque los nombres de Get-Counter
# cambian con el idioma de Windows; las clases CIM no.

param([int]$Intervalo = 5, [string]$Salida = "$PSScriptRoot\monitor_cpu.csv")

if (-not (Test-Path $Salida)) {
    "epoch,pct_rendimiento,frecuencia_mhz,temp_c" | Out-File -FilePath $Salida -Encoding ascii
}
Write-Host "Registrando en $Salida cada $Intervalo s (Ctrl+C para detener)"

while ($true) {
    $epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()   # mismo reloj que timestamp_epoch del CSV
    $cpu = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter "Name='_Total'" -ErrorAction SilentlyContinue
    $perf = if ($cpu) { $cpu.PercentProcessorPerformance } else { "" }
    $freq = if ($cpu) { $cpu.ProcessorFrequency } else { "" }
    # Temperatura en decimas de Kelvin o Kelvin segun el equipo; muchos portatiles no la exponen
    $tz = Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction SilentlyContinue |
          Sort-Object Temperature -Descending | Select-Object -First 1
    $temp = ""
    if ($tz -and $tz.HighPrecisionTemperature) { $temp = [math]::Round($tz.HighPrecisionTemperature / 10 - 273.15, 1) }
    elseif ($tz -and $tz.Temperature) { $temp = [math]::Round($tz.Temperature - 273.15, 1) }
    "$epoch,$perf,$freq,$temp" | Out-File -FilePath $Salida -Append -Encoding ascii
    Start-Sleep -Seconds $Intervalo
}
