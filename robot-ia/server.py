"""
Servidor del "cerebro remoto" del robot.

  /ws       WebSocket del ESP32: recibe el audio del micrófono sin parar y le devuelve
            las acciones cuando escucha "Aries". También acepta comandos escritos.
  /comando  POST con un WAV (pruebas con curl)
  /texto    POST con {"texto": "..."} (pruebas sin micrófono)

Uso (lo más fácil es `bash iniciar.sh`, que pregunta qué micrófono usar):
    python server.py --mic robot   # micrófono del robot (INMP441 en el ESP32), es el normal
    python server.py --mic pc      # micrófono de la computadora, por si el del robot falla
    python server.py --guardar-audio   # guarda lo que manda el micrófono del robot en grabaciones/
"""
import json
import math
import os
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request
from flask_sock import Sock

import oido
import voz
from brain import precargar as precargar_gemma, preguntar
from escucha import BLOQUE, COLA_ECO_SEG, Aries, FuenteMicrofonoPC, Oyente
from simulate import ejecutar_accion_simulada

app = Flask(__name__)
sock = Sock(app)

# Función para mandarle acciones al ESP32 conectado (None si no hay robot conectado)
enviar_al_robot = None

# El INMP441 entrega el audio bastante bajo; se ajusta cuando esté el micrófono real
GANANCIA_MIC_ESP32 = 1.0
# ARIES_MUDO=1 para pruebas: responde sin hablar por el parlante
MUDO = os.environ.get("ARIES_MUDO") == "1"
# --guardar-audio: guarda cada frase que manda el robot en grabaciones/ (sirve para revisar el micrófono)
GUARDAR_AUDIO = "--guardar-audio" in sys.argv


def _opcion(nombre: str, por_defecto: str) -> str:
    if nombre in sys.argv:
        i = sys.argv.index(nombre)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return por_defecto


# "robot": escucha el audio que manda el ESP32. "pc": escucha el micrófono de la computadora
# e ignora el del robot (el robot igual recibe las acciones y los comandos escritos).
MICROFONO = _opcion("--mic", "robot")
if MICROFONO not in ("robot", "pc"):
    sys.exit(f'Opción --mic no válida: "{MICROFONO}". Usa --mic robot o --mic pc.')
CARPETA_GRABACIONES = Path(__file__).parent / "grabaciones"

print("Cargando modelo Whisper (small)...")
_t0 = time.time()
oido.cargar()
print(f"Whisper listo en {time.time() - _t0:.1f}s")
voz.precargar()
print("Voces de Piper listas")
precargar_gemma()
print("Gemma cargada en la GPU")


@app.route("/comando", methods=["POST"])
def comando():
    if "audio" not in request.files:
        return jsonify({"error": "Falta el archivo 'audio' en el form-data"}), 400

    archivo = request.files["audio"]

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        archivo.save(tmp.name)

        t0 = time.time()
        texto, idioma = oido.transcribir(tmp.name)
        t_stt = time.time() - t0

    if not texto:
        return jsonify({"error": "No se transcribió ningún texto del audio"}), 422

    try:
        t0 = time.time()
        accion = preguntar(texto, idioma)
        t_ia = time.time() - t0
    except Exception as e:
        return jsonify({"error": f"Error consultando a Gemma: {e}", "texto": texto}), 500

    # Por ahora no hay ESP32: simulamos la acción en consola del servidor
    ejecutar_accion_simulada(accion)
    voz.hablar_en_segundo_plano(accion["respuesta_hablada"], accion["idioma"])

    return jsonify({
        "texto_transcrito": texto,
        "accion": accion,
        "tiempos_seg": {"stt": round(t_stt, 2), "ia": round(t_ia, 2)},
    })


@app.route("/texto", methods=["POST"])
def texto():
    """Igual que /comando pero recibe texto directo (para probar sin micrófono)."""
    # Ruido en el serial del ESP32 puede meter bytes que no son UTF-8 válido; se descartan
    try:
        datos = json.loads(request.get_data().decode("utf-8", errors="ignore"))
    except ValueError:
        datos = {}
    texto = str(datos.get("texto", "")).strip() if isinstance(datos, dict) else ""
    if not texto:
        return jsonify({"error": "Falta el campo 'texto' en el JSON"}), 400

    try:
        t0 = time.time()
        accion = preguntar(texto)
        t_ia = time.time() - t0
    except Exception as e:
        return jsonify({"error": f"Error consultando a Gemma: {e}", "texto": texto}), 500

    ejecutar_accion_simulada(accion)
    voz.hablar_en_segundo_plano(accion["respuesta_hablada"], accion["idioma"])

    return jsonify({
        "texto_transcrito": texto,
        "accion": accion,
        "tiempos_seg": {"stt": 0, "ia": round(t_ia, 2)},
    })


def registrar_frase_robot(frase: np.ndarray) -> None:
    """Muestra el volumen de la frase (para calibrar el micrófono) y la guarda si se pidió."""
    pico = float(np.max(np.abs(frase))) if len(frase) else 0.0
    dbfs = 20 * math.log10(pico) if pico > 0 else -90.0
    if pico >= 0.99:
        consejo = "  <- SATURA: sube CORRIMIENTO en el firmware"
    elif dbfs < -40:
        consejo = "  <- MUY BAJO: baja CORRIMIENTO en el firmware"
    else:
        consejo = ""
    print(f"🎚️  Frase del robot: {len(frase) / 16000:.1f} s, pico {dbfs:.0f} dBFS{consejo}", flush=True)

    if GUARDAR_AUDIO:
        CARPETA_GRABACIONES.mkdir(exist_ok=True)
        ruta = CARPETA_GRABACIONES / f"frase_{time.strftime('%H%M%S')}.wav"
        with wave.open(str(ruta), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((np.clip(frase, -1, 1) * 32767).astype(np.int16).tobytes())
        print(f"   guardada en {ruta}", flush=True)


@sock.route("/ws")
def ws_robot(ws):
    """
    Mensajes del ESP32:
      binario -> audio PCM 16 bits, 16 kHz, mono
      texto   -> {"texto": "..."} (comando escrito en el monitor serial)
    Mensajes al ESP32:
      texto   -> {"accion", "parametro", "idioma", "respuesta_hablada"}
    """
    print("🤖 Robot conectado", flush=True)
    oyente = Oyente()
    aries = Aries(time.monotonic, mudo=MUDO)
    ocupado = threading.Event()  # mientras piensa y habla no escucha (si no, se oye a sí mismo)
    lock_envio = threading.Lock()
    pendiente = np.zeros(0, dtype=np.float32)
    nivel_dc = 0.0

    def enviar(accion: dict) -> None:
        with lock_envio:
            ws.send(json.dumps(accion))

    global enviar_al_robot
    enviar_al_robot = enviar

    def atender(frase: np.ndarray | None = None, texto: str | None = None) -> None:
        try:
            accion = aries.decidir(frase) if frase is not None else aries.decidir_texto(texto)
            if accion is not None:
                aries.responder(accion, enviar)
                time.sleep(COLA_ECO_SEG)
        except Exception as e:
            print(f"⚠️  Error atendiendo al robot: {e}", flush=True)
        finally:
            oyente.reiniciar()
            ocupado.clear()

    try:
        while True:
            mensaje = ws.receive()

            if isinstance(mensaje, str):
                try:
                    texto = str(json.loads(mensaje).get("texto", "")).strip()
                except (ValueError, AttributeError):
                    texto = ""
                if texto and not ocupado.is_set():
                    ocupado.set()
                    threading.Thread(target=atender, kwargs={"texto": texto}, daemon=True).start()
                continue

            if MICROFONO == "pc" or ocupado.is_set():
                pendiente = np.zeros(0, dtype=np.float32)
                continue

            muestras = np.frombuffer(mensaje, dtype="<i2").astype(np.float32) / 32768.0
            # El INMP441 tiene un pequeño corrimiento de continua (DC); se resta un promedio lento
            nivel_dc = 0.99 * nivel_dc + 0.01 * float(muestras.mean()) if len(muestras) else nivel_dc
            muestras = np.clip((muestras - nivel_dc) * GANANCIA_MIC_ESP32, -1.0, 1.0)
            pendiente = np.concatenate([pendiente, muestras])

            while len(pendiente) >= BLOQUE:
                bloque, pendiente = pendiente[:BLOQUE], pendiente[BLOQUE:]
                frase = oyente.procesar(bloque)
                if frase is not None:
                    ocupado.set()
                    pendiente = np.zeros(0, dtype=np.float32)
                    registrar_frase_robot(frase)
                    threading.Thread(target=atender, kwargs={"frase": frase}, daemon=True).start()
                    break
    finally:
        if enviar_al_robot is enviar:
            enviar_al_robot = None
        print("🔌 Robot desconectado", flush=True)


@app.route("/salud", methods=["GET"])
def salud():
    return jsonify({"estado": "ok"})


def escuchar_microfono_pc() -> None:
    """Plan B (--mic pc): escucha por el micrófono de la computadora y le manda las acciones al ESP32."""
    oyente = Oyente()
    aries = Aries(time.monotonic, mudo=MUDO)
    fuente = FuenteMicrofonoPC()
    print("🎧 Escuchando por el micrófono de la computadora. Di \"Hola Aries\".", flush=True)
    for bloque in fuente:
        frase = oyente.procesar(bloque)
        if frase is None:
            continue
        try:
            accion = aries.decidir(frase)
            if accion is not None:
                aries.responder(accion, enviar_al_robot)
                time.sleep(COLA_ECO_SEG)
        except Exception as e:
            print(f"⚠️  Error con el micrófono de la PC: {e}", flush=True)
        fuente.descartar_pendiente()
        oyente.reiniciar()


if __name__ == "__main__":
    if MICROFONO == "pc":
        print("🎤 Micrófono: el de la COMPUTADORA (el del robot se ignora)", flush=True)
        threading.Thread(target=escuchar_microfono_pc, daemon=True).start()
    else:
        print("🎤 Micrófono: el del ROBOT", flush=True)
    app.run(host="0.0.0.0", port=5000)
