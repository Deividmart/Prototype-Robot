#!/usr/bin/env bash
# Enciende el cerebro de Aries.
#
#   bash iniciar.sh          pregunta qué micrófono usar
#   bash iniciar.sh robot    micrófono del robot (INMP441 en el ESP32)
#   bash iniciar.sh pc       micrófono de la computadora (si el del robot falla)
set -euo pipefail
cd "$(dirname "$0")"

mic="${1:-}"
if [ -z "$mic" ]; then
    echo "¿Qué micrófono quieres usar?"
    echo "  1) El del robot"
    echo "  2) El de la computadora (si el del robot no funciona)"
    read -rp "Escribe 1 o 2 y presiona Enter: " opcion
    case "$opcion" in
        1) mic=robot ;;
        2) mic=pc ;;
        *) echo "Opción no válida: escribe 1 o 2."; exit 1 ;;
    esac
fi

case "$mic" in
    robot | pc) ;;
    *) echo "Opción no válida: \"$mic\". Usa: bash iniciar.sh robot   o   bash iniciar.sh pc"; exit 1 ;;
esac

source robot-env/bin/activate
exec python3 server.py --mic "$mic" "${@:2}"
