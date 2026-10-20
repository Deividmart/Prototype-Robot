@echo off
rem Enciende el cerebro de Aries en Windows.
rem   iniciar.bat          pregunta que microfono usar
rem   iniciar.bat robot    microfono del robot (INMP441 en el ESP32)
rem   iniciar.bat pc       microfono de la computadora (si el del robot falla)
setlocal
cd /d "%~dp0"
rem Para que los emojis y las tildes del servidor se vean bien en la consola
set PYTHONUTF8=1
chcp 65001 >nul

if not exist "robot-env\Scripts\python.exe" (
    echo Falta instalar: haz doble clic en instalar.bat primero.
    pause
    exit /b 1
)

set "MIC=%~1"
if not "%MIC%"=="" goto revisar

echo Que microfono quieres usar?
echo   1^) El del robot
echo   2^) El de la computadora ^(si el del robot no funciona^)
set /p "OPCION=Escribe 1 o 2 y presiona Enter: "
if "%OPCION%"=="1" set "MIC=robot"
if "%OPCION%"=="2" set "MIC=pc"
if "%MIC%"=="" (
    echo Opcion no valida: escribe 1 o 2.
    pause
    exit /b 1
)

:revisar
if /i not "%MIC%"=="robot" if /i not "%MIC%"=="pc" (
    echo Opcion no valida: "%MIC%". Usa: iniciar.bat robot   o   iniciar.bat pc
    exit /b 1
)

"robot-env\Scripts\python.exe" server.py --mic %MIC% %2 %3
pause
