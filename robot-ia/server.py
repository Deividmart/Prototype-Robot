"""
Servidor del "cerebro remoto" del robot.

Recibe un audio (WAV) por HTTP, lo transcribe con Whisper, le pasa el texto
a Gemma (brain.py) para decidir la acción, y por ahora simula la ejecución
en consola (no hay ESP32 conectado todavía).

Uso:
    python server.py
    # en otra terminal:
    curl -F audio=@test_mic.wav http://localhost:5000/comando

Cuando llegue el ESP32, el endpoint /comando queda igual: lo único que
cambia es quién le habla (el ESP32 en vez de curl) y qué se hace con el
JSON de respuesta (moverlo a los motores en vez de simularlo).
"""
import json
import tempfile
import time

from flask import Flask, jsonify, request

import oido
import voz
from brain import preguntar
from simulate import ejecutar_accion_simulada

app = Flask(__name__)

print("Cargando modelo Whisper (small)...")
_t0 = time.time()
oido.cargar()
print(f"Whisper listo en {time.time() - _t0:.1f}s")
voz.precargar()
print("Voces de Piper listas")


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


@app.route("/salud", methods=["GET"])
def salud():
    return jsonify({"estado": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
