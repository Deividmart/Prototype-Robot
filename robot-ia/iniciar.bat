@echo off
rem Enciende a Aries en Windows: abre la ventana de las graficas en vivo y deja esta terminal
rem mostrando lo que Aries escucha, dice y le manda al robot.
rem   iniciar.bat          microfono de la computadora (el robot ya no tiene el suyo)
rem   iniciar.bat robot    microfono del robot (INMP441 en el ESP32), si algun dia se lo vuelven a poner
setlocal
cd /d "%~dp0"
title Aries - lo que escucha
rem Para que los emojis y las tildes del servidor se vean bien en la consola
set PYTHONUTF8=1
chcp 65001 >nul

if not exist "robot-env\Scripts\python.exe" (
    echo Falta instalar: haz doble clic en instalar.bat primero.
    pause
    exit /b 1
)

set "MIC=%~1"
if "%MIC%"=="" set "MIC=pc"
if /i not "%MIC%"=="robot" if /i not "%MIC%"=="pc" (
    echo Opcion no valida: "%MIC%". Usa: iniciar.bat   o   iniciar.bat robot
    pause
    exit /b 1
)

rem Las graficas van en su propia ventana, sin terminal (pythonw); se cierran con la X
start "" "robot-env\Scripts\pythonw.exe" graficas.py

rem El cerebro corre sin ventana y esta solo muestra lo que oye (vigilar.ps1): cerrarla o un Ctrl+C
rem sin querer ya no apagan a Aries. Para apagarlo: apagar.bat
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vigilar.ps1" -Mic %MIC%
