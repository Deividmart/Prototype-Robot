# Instala todo lo necesario para correr el cerebro de Aries y programar el ESP32
# en Windows 10/11, con tarjeta gráfica NVIDIA o AMD. Se puede volver a correr: lo que ya está instalado se salta.
#   NVIDIA: Whisper y Gemma en la tarjeta gráfica.
#   AMD:    Gemma en la tarjeta gráfica (Ollama la usa sola) y Whisper en el procesador con faster-whisper
#           (PyTorch en Windows solo usa NVIDIA). Sin tarjeta compatible, todo va en el procesador.
#
# No lo corras directo: haz doble clic en instalar.bat (o escribe instalar.bat en la terminal).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Paso($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }
function Fallar($texto) { Write-Host "`nERROR: $texto" -ForegroundColor Red; exit 1 }
# winget agrega cosas al PATH, pero esta ventana no se entera sola
function Recargar-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
# winget devuelve varios códigos de error cuando el programa ya estaba instalado, así que en
# vez de mirar el código se comprueba después si el comando quedó disponible.
function Instalar-Winget($id, $comando) {
    if ($comando -and (Get-Command $comando -ErrorAction SilentlyContinue)) {
        Write-Host "$id ya está instalado."
        return
    }
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
    Recargar-Path
}
function Correr($comando) {
    & $comando[0] $comando[1..($comando.Length - 1)]
    if ($LASTEXITCODE -ne 0) { Fallar "falló: $($comando -join ' ')" }
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fallar "no encuentro winget. Instala 'Instalador de aplicación' desde la Microsoft Store y vuelve a intentar."
}

Paso "1/8 Tarjeta gráfica"
$tarjetas = (Get-CimInstance Win32_VideoController).Name
$tarjetas | ForEach-Object { Write-Host "Encontré: $_" }
if ($tarjetas -match "NVIDIA") {
    $marca = "NVIDIA"
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        Fallar "no encuentro el driver de NVIDIA. Instálalo desde https://www.nvidia.com/drivers (o con la app NVIDIA), reinicia y vuelve a correr instalar.bat."
    }
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
} elseif ($tarjetas -match "AMD|Radeon") {
    $marca = "AMD"
    Write-Host "Tarjeta AMD: Gemma va a usar la tarjeta y Whisper el procesador (con faster-whisper)."
    Write-Host "Para que Ollama use la AMD hace falta el driver AMD Software: Adrenalin Edition al día (https://www.amd.com/support)."
    if (-not ($tarjetas -match "RX [6-9]\d\d\d")) {
        # Ollama usa las AMD con ROCm solo desde la RX 6000. Las anteriores (RX 5500 XT, RX 580, Vega...)
        # las puede usar por Vulkan, que en Ollama todavía es experimental y hay que encenderlo
        Write-Host "Esta AMD es anterior a la RX 6000: activo el modo Vulkan de Ollama (experimental) para que Gemma la use."
        [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
        $env:OLLAMA_VULKAN = "1"
        # Ollama lee la variable al arrancar: si ya estaba abierto, se reinicia
        Get-Process "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force
    }
} else {
    $marca = "ninguna"
    Write-Host "AVISO: no encontré una tarjeta NVIDIA ni AMD. Todo va a correr en el procesador: funciona, pero responde más lento." -ForegroundColor Yellow
}

Paso "2/8 Python 3.12, ffmpeg y Ollama"
Instalar-Winget "Python.Python.3.12" "py"
Instalar-Winget "Gyan.FFmpeg" "ffmpeg"
Instalar-Winget "Ollama.Ollama" "ollama"
foreach ($c in "py", "ffmpeg") {
    if (-not (Get-Command $c -ErrorAction SilentlyContinue)) {
        Fallar "no encuentro '$c' después de instalarlo. Cierra esta ventana y vuelve a correr instalar.bat."
    }
}

Paso "3/8 Modelo Gemma 3 4B (descarga unos 3,3 GB)"
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
$ollama = if ($ollama) { $ollama.Source } else { "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
if (-not (Test-Path $ollama)) { Fallar "no encuentro ollama.exe. Ciérrala y vuelve a correr instalar.bat." }
# Ollama tiene que estar abierto (icono de la llama junto al reloj) para descargar modelos
try { Invoke-RestMethod http://localhost:11434/api/version -TimeoutSec 2 | Out-Null }
catch { Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep -Seconds 5 }
Correr @($ollama, "pull", "gemma3:4b")

Paso "4/8 Entorno de Python"
if (-not (Test-Path "robot-env\Scripts\python.exe")) { Correr @("py", "-3.12", "-m", "venv", "robot-env") }
$py = "robot-env\Scripts\python.exe"
Correr @($py, "-m", "pip", "install", "--upgrade", "pip")

if ($marca -eq "NVIDIA") {
    Paso "5/8 PyTorch con CUDA y librerías (descarga unos 3 GB, puede tardar)"
    # El torch normal de PyPI en Windows no usa la tarjeta gráfica: se instala antes el de CUDA
    Correr @($py, "-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cu126")
    Correr @($py, "-m", "pip", "install", "-r", "requirements.txt")
    & $py -c "import torch, sys; ok = torch.cuda.is_available(); print('Whisper va a usar la tarjeta grafica:', torch.cuda.get_device_name(0) if ok else 'NO (va a ir lento)'); sys.exit(0 if ok else 1)"
    if ($LASTEXITCODE -ne 0) { Write-Host "AVISO: PyTorch no ve la tarjeta gráfica. Funciona igual, pero Whisper va a tardar varios segundos." -ForegroundColor Yellow }
} else {
    Paso "5/8 PyTorch para el procesador, faster-whisper y librerías (descarga unos 500 MB)"
    # Sin NVIDIA no hace falta el torch de CUDA (pesa 3 GB): el de procesador alcanza para el detector de voz
    Correr @($py, "-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cpu")
    Correr @($py, "-m", "pip", "install", "-r", "requirements.txt", "faster-whisper>=1.1")
    Write-Host "Whisper va a usar el procesador con faster-whisper (alrededor de 1 segundo por frase)."
}

Paso "6/8 Voces de Aries y modelo de Whisper"
New-Item -ItemType Directory -Force voces | Out-Null
foreach ($voz in "es_MX-claude-high", "en_US-ryan-medium") {
    if (-not (Test-Path "voces\$voz.onnx")) { Correr @($py, "-m", "piper.download_voices", "--data-dir", "voces", $voz) }
}
if ($marca -eq "NVIDIA") {
    Correr @($py, "-c", "import whisper; whisper.load_model('small'); print('Whisper listo')")
} else {
    Correr @($py, "-c", "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8'); print('Whisper listo')")
}

Paso "7/8 Herramientas para programar el ESP32"
Instalar-Winget "ArduinoSA.CLI" "arduino-cli"
if (-not (Get-Command arduino-cli -ErrorAction SilentlyContinue)) {
    Fallar "no encuentro arduino-cli después de instalarlo. Cierra esta ventana y vuelve a correr instalar.bat."
}
if (-not (Test-Path "$env:LOCALAPPDATA\Arduino15\arduino-cli.yaml")) { Correr @("arduino-cli", "config", "init") }
Correr @("arduino-cli", "config", "set", "board_manager.additional_urls", "https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json")
Correr @("arduino-cli", "core", "update-index")
Correr @("arduino-cli", "core", "install", "esp32:esp32@3.3.12")
Correr @("arduino-cli", "lib", "install", "ArduinoJson@7.4.3", "WebSockets@2.7.2", "MD_MAX72XX@3.5.1", "MD_Parola@3.7.7")

Paso "8/8 Permiso del firewall para que el ESP32 llegue al cerebro"
Write-Host "Windows te va a pedir permiso de administrador: acepta."
# Solo abre el puerto 5000 a equipos de la misma red (LocalSubnet)
$regla = 'if (-not (Get-NetFirewallRule -DisplayName "Aries cerebro (puerto 5000)" -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName "Aries cerebro (puerto 5000)" -Direction Inbound -Protocol TCP -LocalPort 5000 -RemoteAddress LocalSubnet -Action Allow -Profile Any | Out-Null }'
try { Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-Command", $regla }
catch { Write-Host "AVISO: no se pudo crear la regla del firewall. Cuando corras iniciar.bat, si Windows pregunta, permite el acceso en redes privadas." -ForegroundColor Yellow }

Paso "Listo"
Write-Host "Cierra esta ventana y abre una nueva para que funcionen los comandos instalados."
Write-Host "Después, en Aries.bat: 8 carga el firmware al robot y 2 lo conecta a la WiFi de esta computadora."
