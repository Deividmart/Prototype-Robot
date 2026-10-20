#!/usr/bin/env bash
# Instala todo lo necesario para correr el cerebro de Aries y programar el ESP32
# en Ubuntu con tarjeta gráfica NVIDIA. Se puede volver a correr: lo que ya está instalado se salta.
#
# Uso (desde la carpeta robot-ia):
#     bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

paso() { printf '\n=== %s ===\n' "$*"; }

paso "1/7 Paquetes del sistema (te va a pedir tu contraseña)"
sudo apt update
sudo apt install -y curl ffmpeg python3-venv python3-pip pipewire-bin

paso "2/7 Tarjeta gráfica NVIDIA"
if ! command -v nvidia-smi >/dev/null || ! nvidia-smi >/dev/null 2>&1; then
    echo "No encuentro el driver de NVIDIA. Instálalo con:"
    echo "    sudo ubuntu-drivers install"
    echo "reinicia la PC y vuelve a correr: bash setup.sh"
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

paso "3/7 Ollama y el modelo Gemma 3 4B (descarga unos 3,3 GB)"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:4b

paso "4/7 Entorno de Python y librerías (descarga varios GB, puede tardar)"
[ -d robot-env ] || python3 -m venv robot-env
robot-env/bin/pip install --upgrade pip
robot-env/bin/pip install -r requirements.txt

paso "5/7 Voces de Aries (Piper)"
mkdir -p voces
for voz in es_MX-claude-high en_US-ryan-medium; do
    [ -f "voces/$voz.onnx" ] || robot-env/bin/python -m piper.download_voices --data-dir voces "$voz"
done

paso "6/7 Modelo de Whisper (se descarga una sola vez)"
robot-env/bin/python -c "import whisper; whisper.load_model('small'); print('Whisper listo')"

paso "7/7 Herramientas para programar el ESP32"
mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"
grep -q '.local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
command -v arduino-cli >/dev/null || curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
[ -f "$HOME/.arduino15/arduino-cli.yaml" ] || arduino-cli config init
arduino-cli config set board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32@3.3.12
arduino-cli lib install ArduinoJson@7.4.3 WebSockets@2.7.2
# Sin este grupo no se puede usar el puerto USB del ESP32 sin sudo
sudo usermod -aG dialout "$USER"

paso "Listo"
echo "Cierra sesión y vuelve a entrar (o reinicia) para que funcione el puerto USB del ESP32."
echo "Después sigue con el paso 4 de INSTALACION.md (configurar el WiFi)."
