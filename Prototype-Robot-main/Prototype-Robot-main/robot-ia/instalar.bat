@echo off
rem Doble clic para instalar todo en Windows (llama a setup.ps1 sin pedir permisos de scripts)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause
