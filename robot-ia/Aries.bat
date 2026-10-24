@echo off
rem Doble clic: menu de Aries para cualquier computadora (instalar, conectar el robot a la WiFi,
rem cargar el firmware, encender y apagar). Ver aries.ps1
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0aries.ps1"
