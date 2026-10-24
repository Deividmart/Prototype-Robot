@echo off
rem Abre las graficas de los movimientos de Aries.
rem   graficas.bat            en vivo (el movimiento que se esta registrando)
rem   graficas.bat --ultimo   el ultimo movimiento guardado
rem   graficas.bat --lista    lista de movimientos guardados
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
chcp 65001 >nul

if not exist "robot-env\Scripts\python.exe" (
    echo Falta instalar: haz doble clic en instalar.bat primero.
    pause
    exit /b 1
)

"robot-env\Scripts\python.exe" graficas.py %*
if errorlevel 1 pause
