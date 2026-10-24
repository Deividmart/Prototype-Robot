@echo off
rem Apaga a Aries: el cerebro (que corre sin ventana), las graficas y la ventana "lo que escucha".
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'server\.py|graficas\.py|vigilar\.ps1' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Aries apagado.
timeout /t 2 >nul
