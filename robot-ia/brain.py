"""
Cerebro del robot: le manda el comando del usuario a Gemma (via Ollama)
y devuelve la acción a ejecutar en formato dict.

No depende de hardware (ESP32) ni de audio (Whisper/Piper) todavía.
Sirve para desarrollar y probar la lógica de decisión de forma aislada.
"""
import json
import re
import requests

from clima import frase_clima

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "gemma3:4b"

NOMBRE_ROBOT = "Aries"

ACCIONES_VALIDAS = {"avanzar", "retroceder", "girar", "detener", "clima", "saludo", "desconocido"}

# Gemma solo clasifica el comando; la frase hablada la arma frase_accion() con plantillas,
# porque el modelo de 4B no respeta de forma confiable el idioma pedido al redactar.
SYSTEM_PROMPT = """Sos el cerebro de un robot. Tenés estas acciones disponibles:
- avanzar(metros): avanza hacia adelante una cantidad de metros
- retroceder(metros): retrocede una cantidad de metros
- girar(grados): gira sobre su eje, positivo = derecha, negativo = izquierda
- detener(): se detiene
- clima(): el usuario pregunta por el clima, la temperatura, si llueve o si hace calor/frío
- saludo(): el usuario saluda al robot
- desconocido(): el pedido no es ninguna de las anteriores

El usuario puede hablar en español o en inglés; entendé los dos.

Respondé SIEMPRE y ÚNICAMENTE con un JSON válido, sin texto extra, con este formato exacto:
{"accion": "avanzar", "parametro": 2}

Reglas:
- "accion" debe ser una de: avanzar, retroceder, girar, detener, clima, saludo, desconocido
- "parametro" es siempre un número: metros para avanzar/retroceder, grados para girar, 0 para el resto
- Si pide avanzar o retroceder sin decir cuánto, usá 1
- Para "girar": derecha = número POSITIVO, izquierda = número NEGATIVO. Ejemplos:
  "girá a la derecha 45" / "turn right 45 degrees" -> 45
  "girá a la izquierda 45" / "turn left 45 degrees" -> -45
  "da media vuelta" / "turn around" -> 180
  Sin cantidad de grados, girá 90: "girá a la derecha" / "turn right" -> 90, "girá a la izquierda" / "turn left" -> -90
- Pedidos de frenar ("para", "pará", "quieto", "detente", "frená", "stop", "halt") son "detener"
- Preguntas del clima ("¿qué clima hace?", "¿va a llover hoy?", "how's the weather?", "is it hot outside?") son "clima"
- Saludos o charla de cortesía ("¿cómo estás?", "¿qué tal?", "how are you?") son "saludo"
- Cualquier otra cosa (chistes, charla, preguntas generales) es "desconocido"

El usuario dijo: "__COMANDO__"
"""

_PALABRAS_EN = {
    "the", "a", "an", "is", "it", "it's", "its", "how", "how's", "what", "what's", "you", "me", "my",
    "please", "move", "go", "forward", "back", "backward", "backwards", "turn", "left", "right", "around",
    "stop", "halt", "meter", "meters", "metre", "metres", "degrees", "weather", "rain", "raining",
    "hot", "cold", "outside", "today", "temperature", "tell", "joke", "one", "two", "three", "and", "to",
    "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
}
_PALABRAS_ES = {
    "el", "la", "los", "las", "un", "una", "que", "qué", "es", "hace", "hay", "por", "favor", "me",
    "avanza", "avanzá", "avanzar", "retrocede", "retrocedé", "gira", "girá", "girar", "date", "vuelta",
    "izquierda", "derecha", "para", "pará", "quieto", "detente", "frená", "frena", "metro", "metros",
    "grados", "clima", "tiempo", "llover", "llueve", "calor", "frío", "hoy", "cuántos", "cuántas",
    "dos", "tres", "contame", "cuéntame", "chiste", "y", "de", "al", "adelante", "atrás",
    "hola", "buenos", "buenas", "días", "tardes", "noches",
}


_SALUDO = re.compile(
    r"^(hola|hello|hi|hey|buenas|buen[oa]s\s+(d[ií]as|tardes|noches)|good\s+(morning|afternoon|evening))\b[\s,.!¡]*",
    re.IGNORECASE,
)


def separar_saludo(texto: str) -> tuple[bool, str]:
    """
    Gemma confunde "Aries, ¿qué clima hace?" con un saludo, así que el nombre y el saludo
    se sacan acá. Devuelve (es_solo_saludo, pedido_sin_nombre_ni_saludo).
    """
    sin_nombre = re.sub(rf"\b{re.escape(NOMBRE_ROBOT)}\b", " ", texto, flags=re.IGNORECASE)
    limpio = re.sub(r"^[\s,.!¡¿?]+", "", sin_nombre).strip()
    sin_saludo = _SALUDO.sub("", limpio).strip(" ,.!¡¿?")
    if not sin_saludo:
        return True, ""
    return False, sin_saludo


def detectar_idioma(texto: str) -> str:
    """'es' o 'en' contando palabras típicas; ante la duda, español."""
    if re.search(r"[áéíóúñ¿¡]", texto.lower()):
        return "es"
    palabras = re.findall(r"[a-z']+", texto.lower())
    en = sum(p in _PALABRAS_EN for p in palabras)
    es = sum(p in _PALABRAS_ES for p in palabras)
    return "en" if en > es else "es"


def _numero(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def frase_accion(accion: str, parametro: float, idioma: str) -> str:
    n = abs(parametro)
    uno = n == 1
    if idioma == "en":
        if accion == "avanzar":
            return f"Moving forward {_numero(n)} meter{'' if uno else 's'}."
        if accion == "retroceder":
            return f"Moving back {_numero(n)} meter{'' if uno else 's'}."
        if accion == "girar":
            if n == 180:
                return "Turning around."
            return f"Turning {'right' if parametro >= 0 else 'left'} {_numero(n)} degrees."
        if accion == "detener":
            return "Stopping."
        if accion == "saludo":
            return f"Hi! I'm {NOMBRE_ROBOT}. How can I help you?"
        return "Sorry, I didn't understand. I can move forward, move back, turn, stop, or tell you the weather."

    if accion == "avanzar":
        return f"Avanzo {_numero(n)} metro{'' if uno else 's'}."
    if accion == "retroceder":
        return f"Retrocedo {_numero(n)} metro{'' if uno else 's'}."
    if accion == "girar":
        if n == 180:
            return "Doy media vuelta."
        return f"Giro {_numero(n)} grados a la {'derecha' if parametro >= 0 else 'izquierda'}."
    if accion == "detener":
        return "Me detengo."
    if accion == "saludo":
        return f"¡Hola! Soy {NOMBRE_ROBOT}, ¿en qué te puedo ayudar?"
    return "Perdón, no entendí. Puedo avanzar, retroceder, girar, detenerme o decirte el clima."


def _extraer_json(texto: str) -> dict:
    """Gemma a veces rodea el JSON con texto o markdown; esto lo aísla."""
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta del modelo: {texto!r}")
    return json.loads(match.group(0))


def preguntar(comando_usuario: str, idioma: str | None = None) -> dict:
    """
    Envía el comando del usuario a Gemma y devuelve un dict validado:
    {"accion": str, "parametro": float, "idioma": "es"|"en", "respuesta_hablada": str}

    idioma: si viene de Whisper (audio) se usa ese; si es None se detecta del texto.
    """
    if idioma not in ("es", "en"):
        idioma = detectar_idioma(comando_usuario)

    solo_saludo, pedido = separar_saludo(comando_usuario)
    if solo_saludo:
        return {"accion": "saludo", "parametro": 0.0, "idioma": idioma, "respuesta_hablada": frase_accion("saludo", 0, idioma)}

    prompt = SYSTEM_PROMPT.replace("__COMANDO__", pedido)

    resp = requests.post(
        OLLAMA_URL,
        json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json", "keep_alive": "2h"},
        timeout=30,
    )
    resp.raise_for_status()
    crudo = _extraer_json(resp.json()["response"])

    # No confiar a ciegas en el modelo: acción fuera de la lista o número inválido -> no se mueve
    accion = crudo.get("accion")
    try:
        parametro = float(crudo.get("parametro", 0))
    except (TypeError, ValueError):
        parametro = 0.0
    if accion not in ACCIONES_VALIDAS:
        accion = "desconocido"
    if accion in ("detener", "clima", "saludo", "desconocido"):
        parametro = 0.0

    if accion == "clima":
        frase = frase_clima(idioma)
    else:
        frase = frase_accion(accion, parametro, idioma)

    return {"accion": accion, "parametro": parametro, "idioma": idioma, "respuesta_hablada": frase}


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
