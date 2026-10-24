"""
Voz de Aries: convierte texto en audio con Piper y lo reproduce por la salida de audio
de la PC (el parlante Bluetooth montado en el robot, si está conectado).
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice

CARPETA_VOCES = Path(__file__).parent / "voces"
VOCES = {"es": "es_MX-claude-high", "en": "en_US-ryan-medium"}

# Compresión suave para que la voz se escuche más fuerte sin pasarse del máximo.
# 1 = sin cambio, 2.5 ≈ +5.5 dB, 4 ≈ +7.5 dB
REFUERZO = 2.5

_voces_cargadas: dict[str, PiperVoice] = {}
# Una frase a la vez: si llegan dos comandos seguidos, la segunda espera a que termine la primera
_turno = threading.Lock()
# callar() la activa: corta la frase que está sonando ("Aries, para" mientras habla)
_callar = threading.Event()


def _voz(idioma: str) -> PiperVoice:
    idioma = idioma if idioma in VOCES else "es"
    if idioma not in _voces_cargadas:
        _voces_cargadas[idioma] = PiperVoice.load(str(CARPETA_VOCES / f"{VOCES[idioma]}.onnx"))
    return _voces_cargadas[idioma]


def _reforzar(ruta: str) -> None:
    with wave.open(ruta) as w:
        params = w.getparams()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
    y = np.tanh(REFUERZO * x) / np.tanh(REFUERZO)
    with wave.open(ruta, "wb") as w:
        w.setparams(params)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def sintetizar(texto: str, idioma: str, ruta: str) -> None:
    with wave.open(ruta, "wb") as w:
        _voz(idioma).synthesize_wav(texto, w)
    if REFUERZO > 1:
        _reforzar(ruta)


def hablar(texto: str, idioma: str) -> None:
    """Genera y reproduce la frase; bloquea hasta que termina de sonar."""
    if not texto:
        return
    # En Windows un archivo temporal abierto no se puede reabrir por nombre: se usa una ruta suelta
    fd, ruta = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with _turno:
            _callar.clear()
            sintetizar(texto, idioma, ruta)
            _reproducir(ruta)
    finally:
        os.remove(ruta)


def callar() -> None:
    """Corta lo que esté diciendo (si no está hablando, no hace nada)."""
    _callar.set()


def _reproducir(ruta: str) -> None:
    """Reproduce un WAV por la salida de audio predeterminada; espera a que termine o a callar()."""
    with wave.open(ruta) as w:
        duracion = w.getnframes() / w.getframerate()
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(ruta, winsound.SND_FILENAME | winsound.SND_ASYNC)
        # La reproducción asíncrona empieza un poco después: se le da un margen al final
        if _callar.wait(duracion + 0.3):
            winsound.PlaySound(None, 0)  # corta el sonido
    else:
        proceso = subprocess.Popen(["pw-play", ruta])
        inicio = time.monotonic()
        while proceso.poll() is None:
            if _callar.wait(0.05):
                proceso.kill()
                break
            if time.monotonic() - inicio > duracion + 2:
                break


def hablar_en_segundo_plano(texto: str, idioma: str) -> None:
    """Para el servidor: responde al ESP32 enseguida y habla mientras el robot se mueve."""
    threading.Thread(target=hablar, args=(texto, idioma), daemon=True).start()


def precargar() -> None:
    for idioma in VOCES:
        _voz(idioma)


if __name__ == "__main__":
    hablar("¡Hola! Soy Aries, ¿en qué te puedo ayudar?", "es")
    hablar("Hi! I'm Aries. How can I help you?", "en")
