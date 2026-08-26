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
import tempfile
import time

import whisper
from flask import Flask, jsonify, request

from brain import preguntar
from simulate import ejecutar_accion_simulada

app = Flask(__name__)

print("Cargando modelo Whisper (small)...")
_t0 = time.time()
modelo_whisper = whisper.load_model("small")
print(f"Whisper listo en {time.time() - _t0:.1f}s")


@app.route("/comando", methods=["POST"])
def comando():
    if "audio" not in request.files:
        return jsonify({"error": "Falta el archivo 'audio' en el form-data"}), 400

    archivo = request.files["audio"]

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        archivo.save(tmp.name)

        t0 = time.time()
        resultado_stt = modelo_whisper.transcribe(tmp.name, language="es")
        texto = resultado_stt["text"].strip()
        t_stt = time.time() - t0

    if not texto:
        return jsonify({"error": "No se transcribió ningún texto del audio"}), 422

    try:
        t0 = time.time()
        accion = preguntar(texto)
        t_ia = time.time() - t0
    except Exception as e:
        return jsonify({"error": f"Error consultando a Gemma: {e}", "texto": texto}), 500

    # Por ahora no hay ESP32: simulamos la acción en consola del servidor
    ejecutar_accion_simulada(accion)

    return jsonify({
        "texto_transcrito": texto,
        "accion": accion,
        "tiempos_seg": {"stt": round(t_stt, 2), "ia": round(t_ia, 2)},
    })


@app.route("/salud", methods=["GET"])
def salud():
    return jsonify({"estado": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
