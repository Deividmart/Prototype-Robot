# Ventana "Aries - lo que escucha": muestra lo que el cerebro oye, dice y le manda al robot.
# El cerebro (server.py) corre aparte, sin ventana: cerrar esta o presionar Ctrl+C acá NO lo apaga
# (antes un Ctrl+C sin querer, por ejemplo para copiar, apagaba a Aries). Cada 5 s revisa que el
# cerebro siga vivo y, si se cerró, lo vuelve a encender. Para apagar a Aries: apagar.bat
param([string]$Mic = "pc")

$Host.UI.RawUI.WindowTitle = "Aries - lo que escucha"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = "1"
$log = Join-Path $PSScriptRoot "servidor.log"

function Cerebro-Vivo {
    [bool](Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "server\.py" })
}
# Gemma corre en Ollama: si no está abierto (no arrancó con Windows, o lo cerraron) el cerebro se cerraba
# al empezar con "No se puede establecer una conexión" (puerto 11434). Se abre antes y se espera a que responda
function Encender-Ollama {
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null; return } catch {}
    Write-Host "Abriendo Ollama (el programa de Gemma)..." -ForegroundColor Cyan
    $carpeta = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
    if (Test-Path (Join-Path $carpeta "ollama app.exe")) { Start-Process (Join-Path $carpeta "ollama app.exe") }
    elseif (Get-Command ollama -ErrorAction SilentlyContinue) { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
    else { Write-Host "No encuentro Ollama: corre instalar.bat." -ForegroundColor Red; return }
    for ($i = 0; $i -lt 40; $i++) {
        try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 1 | Out-Null; return } catch { Start-Sleep -Milliseconds 500 }
    }
}
function Encender-Cerebro {
    Encender-Ollama
    # python.exe (no pythonw): el firewall de Windows ya lo deja recibir al robot; pythonw es otro programa
    # y lo bloqueaba. La ventana va oculta, así nadie la cierra sin querer
    Start-Process (Join-Path $PSScriptRoot "robot-env\Scripts\python.exe") -ArgumentList "server.py", "--mic", $Mic `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}

if (-not (Test-Path $log)) { New-Item -ItemType File $log | Out-Null }
# Se empieza a leer desde el final: lo viejo no interesa
$archivo = [System.IO.File]::Open($log, "Open", "Read", "ReadWrite")
$archivo.Seek(0, "End") | Out-Null
$lector = New-Object System.IO.StreamReader($archivo, [System.Text.Encoding]::UTF8)

if (Cerebro-Vivo) {
    Write-Host "Aries ya estaba encendido." -ForegroundColor Green
} else {
    Write-Host "Encendiendo a Aries (tarda unos segundos)..." -ForegroundColor Cyan
    Encender-Cerebro
}
Write-Host "Esta ventana solo muestra lo que Aries oye y hace: si la cierras, Aries sigue funcionando."
Write-Host "Para apagar a Aries: doble clic en apagar.bat`n"

$revisado = Get-Date
while ($true) {
    $linea = $lector.ReadLine()
    if ($null -ne $linea) {
        Write-Host $linea
        continue
    }
    Start-Sleep -Milliseconds 300
    if (((Get-Date) - $revisado).TotalSeconds -ge 5) {
        $revisado = Get-Date
        if (-not (Cerebro-Vivo)) {
            Write-Host "`nEl cerebro se cerró: lo vuelvo a encender..." -ForegroundColor Yellow
            Encender-Cerebro
            Start-Sleep -Seconds 15  # que alcance a arrancar antes de volver a revisar
        }
    }
}
