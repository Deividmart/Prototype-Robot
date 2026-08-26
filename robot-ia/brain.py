"""
Cerebro del robot: le manda el comando del usuario a Gemma (via Ollama)
y devuelve la acción a ejecutar en formato dict.

No depende de hardware (ESP32) ni de audio (Whisper/Piper) todavía.
Sirve para desarrollar y probar la lógica de decisión de forma aislada.
"""
import json
import re
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

ACCIONES_VALIDAS = {"avanzar", "retroceder", "girar", "detener"}

SYSTEM_PROMPT = """Sos el cerebro de un robot. Tenés estas acciones disponibles:
- avanzar(metros): avanza hacia adelante una cantidad de metros
- retroceder(metros): retrocede una cantidad de metros
- girar(grados): gira sobre su eje, positivo = derecha, negativo = izquierda
- detener(): se detiene, sin parámetro (usá 0)

Respondé SIEMPRE y ÚNICAMENTE con un JSON válido, sin texto extra, con este formato exacto:
{"accion": "avanzar", "parametro": 2, "respuesta_hablada": "Voy a avanzar dos metros"}

Reglas:
- "accion" debe ser una de: avanzar, retroceder, girar, detener
- "parametro" es siempre un número (metros o grados según la acción, 0 si no aplica)
- Para "girar": derecha = número POSITIVO, izquierda = número NEGATIVO. Ejemplos:
  "girá a la derecha 45" -> parametro: 45
  "girá a la izquierda 45" -> parametro: -45
  "da media vuelta" -> parametro: 180
- "respuesta_hablada" es una frase corta y natural en español, la que el robot va a decir en voz alta
- Si el comando del usuario no tiene sentido o no es una acción soportada, respondé con accion "detener", parametro 0, y una respuesta_hablada explicando que no entendiste

El usuario dijo: "__COMANDO__"
"""


def _extraer_json(texto: str) -> dict:
    """Gemma a veces rodea el JSON con texto o markdown; esto lo aísla."""
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta del modelo: {texto!r}")
    return json.loads(match.group(0))


def preguntar(comando_usuario: str) -> dict:
    """
    Envía el comando del usuario a Gemma y devuelve un dict validado:
    {"accion": str, "parametro": float, "respuesta_hablada": str}
    """
    prompt = SYSTEM_PROMPT.replace("__COMANDO__", comando_usuario)

    resp = requests.post(
        OLLAMA_URL,
        json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    texto_crudo = resp.json()["response"]

    accion = _extraer_json(texto_crudo)

    # Validación básica antes de confiar en la salida del modelo
    if accion.get("accion") not in ACCIONES_VALIDAS:
        raise ValueError(f"Acción no reconocida: {accion.get('accion')!r}")
    if "parametro" not in accion:
        accion["parametro"] = 0
    if "respuesta_hablada" not in accion:
        accion["respuesta_hablada"] = ""

    return accion


if __name__ == "__main__":
    # Prueba rápida por consola sin necesitar el servidor ni Whisper
    pruebas = [
        "avanza dos metros por favor",
        "girá 90 grados a la derecha",
        "pará ahí",
        "contame un chiste",
    ]
    for comando in pruebas:
        print(f"\n>>> Usuario: {comando}")
        try:
            resultado = preguntar(comando)
            print(f"    Acción: {resultado}")
        except Exception as e:
            print(f"    ERROR: {e}")
