"""
Cerebro del robot: le manda el comando del usuario a Gemma (via Ollama)
y devuelve la acción a ejecutar en formato dict.

No depende de hardware (ESP32) ni de audio (Whisper/Piper) todavía.
Sirve para desarrollar y probar la lógica de decisión de forma aislada.
"""
import json
import re
import requests

import enciclopedia
import matematicas
import nube
from clima import frase_clima

# 127.0.0.1 y no localhost: en Windows localhost prueba primero IPv6 (::1), donde Ollama no
# escucha, y cada consulta pierde ~2 s esperando
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "gemma3:4b"

NOMBRE_ROBOT = "Aries"

ACCIONES_VALIDAS = {
    "avanzar", "retroceder", "girar", "detener", "reiniciar", "clima", "saludo", "calcular", "consultar", "explicar",
    "desconocido",
}
# Acciones que no mueven el robot (el parámetro va en 0). "conversar" no la elige Gemma: es "desconocido"
# cuando Groq (nube.py) supo qué responder
SIN_MOVIMIENTO = {"detener", "reiniciar", "clima", "saludo", "calcular", "consultar", "explicar", "desconocido",
                  "conversar"}

# Gemma solo clasifica el comando; la frase hablada la arma frase_accion() con plantillas,
# porque el modelo de 4B no respeta de forma confiable el idioma pedido al redactar.
SYSTEM_PROMPT = """Sos el cerebro de un robot. Tenés estas acciones disponibles:
- avanzar(metros): avanza hacia adelante una cantidad de metros
- retroceder(metros): retrocede una cantidad de metros
- girar(grados): gira sobre su eje, positivo = derecha, negativo = izquierda
- detener(): se detiene
- reiniciar(): borrar las gráficas y empezar la medición de cero
- clima(): el usuario pregunta por el clima, la temperatura, si llueve o si hace calor/frío
- saludo(): el usuario saluda al robot
- calcular(expresion): una cuenta, ecuación, derivada, integral o conversión de unidades
- consultar(tema): una pregunta de conocimiento general ("¿qué es...?", "¿quién fue...?", "what is...?")
- explicar(): explicar la física de lo que el robot midió en su último movimiento
- desconocido(): el pedido no es ninguna de las anteriores (charla, chistes, opiniones)

El usuario puede hablar en español o en inglés; entendé los dos.

Respondé SIEMPRE y ÚNICAMENTE con un JSON válido, sin texto extra, con este formato exacto:
{"accion": "avanzar", "parametro": 2}
Para "calcular" agregá "expresion" y para "consultar" agregá "tema":
{"accion": "calcular", "parametro": 0, "expresion": "sqrt(2*9.81*1.5)"}
{"accion": "consultar", "parametro": 0, "tema": "Ley de Ohm"}

Reglas:
- "accion" debe ser una de: avanzar, retroceder, girar, detener, reiniciar, clima, saludo, calcular, consultar, explicar, desconocido
- "parametro" es siempre un número: metros para avanzar/retroceder, grados para girar, 0 para el resto
- Si pide avanzar o retroceder sin decir cuánto, usá 1
- Para "girar": derecha = número POSITIVO, izquierda = número NEGATIVO. Ejemplos:
  "girá a la derecha 45" / "turn right 45 degrees" -> 45
  "girá a la izquierda 45" / "turn left 45 degrees" -> -45
  "da media vuelta" / "turn around" -> 180
  Sin cantidad de grados, girá 90: "girá a la derecha" / "turn right" -> 90, "girá a la izquierda" / "turn left" -> -90
- Pedidos de frenar ("para", "pará", "quieto", "detente", "frená", "stop", "halt") son "detener"
- Pedidos de empezar de nuevo ("reiniciá", "borrá las gráficas", "empezá de nuevo", "reset", "restart") son "reiniciar"
- Preguntas del clima ("¿qué clima hace?", "¿va a llover hoy?", "how's the weather?", "is it hot outside?") son "clima"
- Saludos o charla de cortesía ("¿cómo estás?", "¿qué tal?", "how are you?") son "saludo"
- Cuentas y matemáticas son "calcular". "expresion" va en sintaxis de Python/SymPy: * para multiplicar,
  ** para potencias, sqrt(), sin() cos() tan() con los ángulos en grados escritos como 30*deg, pi,
  ecuaciones con un solo = y la incógnita x, diff(f, x) para derivar, integrate(f, x) para integrar.
  Para convertir unidades: "<cantidad con unidades> to <unidades>", con nombres en inglés y en singular
  (meter, kilometer, second, hour, kilogram, newton, joule, kilojoule, watt, kilowatt, volt, ampere,
  milliampere, ohm, coulomb, tesla, hertz, calorie, horsepower). Ejemplos:
  "¿cuánto es 25 por 4?" / "what's 25 times 4?" -> "25*4"
  "raíz cuadrada de 2 por 9,8 por 1,5" -> "sqrt(2*9.8*1.5)"
  "15 por ciento de 200" / "15 percent of 200" -> "15/100*200"
  "seno de 30 grados" / "sine of 30 degrees" -> "sin(30*deg)"
  "resuelve x al cuadrado menos 4 igual a cero" / "solve x squared minus 4 equals zero" -> "x**2 - 4 = 0"
  "deriva x al cuadrado por seno de x" / "derivative of x squared" -> "diff(x**2*sin(x), x)" / "diff(x**2, x)"
  "integral de x al cuadrado" / "integral of x squared" -> "integrate(x**2, x)"
  "¿cuántos julios son 5 kilovatios hora?" -> "5*kilowatt*hour to joule"
  "convert 36 kilometers per hour to meters per second" -> "36*kilometer/hour to meter/second"
- Preguntas de conocimiento ("¿qué es la ley de Ohm?", "¿quién fue Faraday?", "what is a capacitor?",
  "who was Tesla?", "explícame el efecto Hall") son "consultar". "tema" es el nombre corto del tema, en el
  idioma de la pregunta: "Ley de Ohm", "Michael Faraday", "Capacitor", "Nikola Tesla", "Efecto Hall"
- Problemas de física con números ("si un carro va a 20 metros por segundo durante 5 segundos, ¿cuánto recorre?",
  "¿qué corriente pasa por 10 ohmios con 5 voltios?") también son "calcular"
- Pedidos de explicar lo que hizo o midió el robot ("explícame el último movimiento", "¿qué física hubo en lo que
  hiciste?", "explica tus gráficas", "explain your last move") son "explicar"
- Cualquier otra cosa (chistes, charla, opiniones, "¿por qué...?") es "desconocido"

El usuario habla en __IDIOMA__: si es "consultar", el "tema" va en __IDIOMA__ (en español:
"¿qué es la gravedad?" -> "Gravedad", "¿qué es un imán?" -> "Imán"; nunca lo traduzcas al inglés).
Escribí el "tema" como el título del artículo de Wikipedia. Si la palabra tiene varios significados, elegí el
de ciencia, física o electricidad: "capacitor" -> "Condensador eléctrico", "pila" -> "Pila eléctrica",
"battery" -> "Electric battery", "Tesla" (persona) -> "Nikola Tesla", "Ohm" -> "Ley de Ohm".

El usuario dijo: "__COMANDO__"
"""

_PALABRAS_EN = {
    "the", "a", "an", "is", "it", "it's", "its", "how", "how's", "what", "what's", "you", "me", "my",
    "please", "move", "go", "forward", "back", "backward", "backwards", "turn", "left", "right", "around",
    "stop", "halt", "meter", "meters", "metre", "metres", "degrees", "weather", "rain", "raining",
    "hot", "cold", "outside", "today", "temperature", "tell", "joke", "one", "two", "three", "and", "to",
    "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
    "calculate", "solve", "derivative", "integral", "square", "root", "times", "plus", "minus", "percent",
    "equals", "zero", "sine", "cosine", "convert", "who", "was", "law", "explain", "per", "of",
}
_PALABRAS_ES = {
    "el", "la", "los", "las", "un", "una", "que", "qué", "es", "hace", "hay", "por", "favor", "me",
    "avanza", "avanzá", "avanzar", "retrocede", "retrocedé", "gira", "girá", "girar", "date", "vuelta",
    "izquierda", "derecha", "para", "pará", "quieto", "detente", "frená", "frena", "metro", "metros",
    "grados", "clima", "tiempo", "llover", "llueve", "calor", "frío", "hoy", "cuántos", "cuántas",
    "dos", "tres", "contame", "cuéntame", "chiste", "y", "de", "al", "adelante", "atrás",
    "hola", "buenos", "buenas", "días", "tardes", "noches",
    "cuánto", "cuanto", "calcula", "resuelve", "raíz", "cuadrada", "más", "menos", "igual", "cero", "deriva",
    "seno", "coseno", "convierte", "julios", "quién", "quien", "fue", "explícame", "explicame", "ley", "efecto",
}


# "Reinicia" se reconoce sin preguntarle a Gemma: es corto y Gemma a veces lo toma como "detener"
# Whisper lo escribe "introdúcete", "introducete", "introdúzcate"...; también vale "preséntate"
_PRESENTATE = re.compile(r"\bintrod[uú][cz]\w*|\bpres[eé]ntate\b|\bintroduce yourself\b", re.IGNORECASE)
_AGRADECE = re.compile(r"\bagradec\w*|\bagradecimiento", re.IGNORECASE)

PRESENTACION = (
    "¡Hola! Soy Aries, un laboratorio portátil diseñado y construido por Santiago Roa, Samuel Romero, "
    "Isaac Padilla, Mathias Badel y David Martínez para la feria Geoexpofísica. "
    "Fui creado mediante la integración de la física, la electricidad, la programación y la inteligencia "
    "artificial, demostrando cómo los conocimientos adquiridos en el aula pueden convertirse en soluciones "
    "tecnológicas innovadoras. "
    "¡Estoy aquí para demostrar que la ciencia también puede cobrar vida!"
)

AGRADECIMIENTO = (
    "Los creadores de Aries agradecen al profesor Camilo Espejo por impulsar a sus estudiantes a explorar, "
    "experimentar e innovar, y a la Universidad del Norte por brindar espacios para desarrollar sus ideas y "
    "aplicar sus conocimientos científicos y tecnológicos. "
    "Y yo, Aries, ¡estoy listo para mostrarles todo lo que puedo hacer! "
    "¡Nos vemos en la feria!"
)

_REINICIO = re.compile(
    r"\b(reinici\w*|resete\w*|reset|restart|empie(z|c)\w* de (nuevo|cero)|borr\w* (las |la )?gr[aá]fic\w*|clear the graphs?)\b",
    re.IGNORECASE,
)

_PREGUNTA_SABER = re.compile(
    r"^\W*(qui[eé]n\s+(es|fue|era)|qu[eé]\s+(es|son|fue|era)|who\s+(is|was|are)|what\s+(is|are|was))\s+"
    r"(?P<tema>[^?¿!.]+)",
    re.IGNORECASE,
)

# Preguntas de opinión ("el mejor equipo", "tu comida favorita"): Wikipedia no las contesta, se charlan
_OPINION = re.compile(
    r"\b(mejor(es)?|peor(es)?|m[aá]s\s+(grande|bonit|lind|fe[oa]|chever)|favorit[oa]s?|preferid[oa]s?|"
    r"best|worst|greatest|favou?rite)\b",
    re.IGNORECASE,
)

DISTANCIA_MAXIMA = 5  # metros por orden
_PIDE_MOVERSE = re.compile(
    r"\b(avan|retr|gir|gira|camin|mu[eé]v|muev|ve\b|vete|anda|adelante|delante|atr[aá]s|derecha|izquierda|"
    r"vuelta|metro|cent[ií]metro|cm\b|grado|forward|back|turn|move|go\b|left|right|spin|meter|degree)",
    re.IGNORECASE,
)
_ATRAS = re.compile(r"\bretr\w*|\batr[aá]s\b|\bback(wards?)?\b|\breverse\b", re.IGNORECASE)

# Distancias con unidad dentro del pedido ("30 centímetros", "1,5 metros", "20 cm", "2 meters")
_DISTANCIA = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(cent[ií]metros?|centimeters?|cm|mil[ií]metros?|millimeters?|mm|metros?|meters?|m)\b",
    re.IGNORECASE,
)
_FACTOR_UNIDAD = {"c": 0.01, "m": 1.0}


# "un metro 67", "1 metro con 30", "dos metros 50": metros y después centímetros (así se dice una estatura)
_METROS_Y_CM = re.compile(
    r"\b(un|uno|una|dos|tres|cuatro|cinco|\d+)\s+metros?\s+(?:con\s+)?(\d{1,2})\b(?!\s*(?:cm|cent|mil|mm))",
    re.IGNORECASE,
)
_PALABRAS_NUMERO = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}


def _distancia_en_metros(pedido: str) -> float | None:
    if combinada := _METROS_Y_CM.search(pedido):
        metros = combinada.group(1).lower()
        metros = _PALABRAS_NUMERO[metros] if metros in _PALABRAS_NUMERO else int(metros)
        return metros + int(combinada.group(2)) / 100
    encontrada = _DISTANCIA.search(pedido)
    if not encontrada:
        return None
    numero = float(encontrada.group(1).replace(",", "."))
    unidad = encontrada.group(2).lower()
    if unidad.startswith(("mil", "mm")):
        return numero / 1000
    return numero * _FACTOR_UNIDAD["c" if unidad.startswith("c") else "m"]


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
    # "¡Hola a Aries!" dejaba "a", y Gemma lo tomaba por "avanza"
    if not sin_saludo or re.fullmatch(r"(a|al|y|e|o|pues|que|oye|to|and|hey)", sin_saludo, re.IGNORECASE):
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
        metros = "half a meter" if n == 0.5 else f"{_numero(n)} meter{'' if uno else 's'}"
        if accion == "avanzar":
            return f"Moving forward {metros}."
        if accion == "retroceder":
            return f"Moving back {metros}."
        if accion == "girar":
            if n == 180:
                return "Turning around."
            return f"Turning {'right' if parametro >= 0 else 'left'} {_numero(n)} degrees."
        if accion == "detener":
            return "Stopping."
        if accion == "reiniciar":
            return "Done, I cleared the graphs. Starting from zero."
        if accion == "saludo":
            return f"Hi! I'm {NOMBRE_ROBOT}. How can I help you?"
        return ("Sorry, I didn't understand. I can move, turn, stop, do math, look things up on Wikipedia, "
                "or tell you the weather.")

    # En español el decimal va con coma ("1,5"): con punto la voz dice "uno punto cinco"
    metros = "medio metro" if n == 0.5 else f"{_numero(n).replace('.', ',')} metro{'' if uno else 's'}"
    if accion == "avanzar":
        return f"Avanzo {metros}."
    if accion == "retroceder":
        return f"Retrocedo {metros}."
    if accion == "girar":
        if n == 180:
            return "Doy media vuelta."
        return f"Giro {_numero(n)} grados a la {'derecha' if parametro >= 0 else 'izquierda'}."
    if accion == "detener":
        return "Me detengo."
    if accion == "reiniciar":
        return "Listo, borré las gráficas. Empiezo de cero."
    if accion == "saludo":
        return f"¡Hola! Soy {NOMBRE_ROBOT}, ¿en qué te puedo ayudar?"
    return ("Perdón, no entendí. Puedo moverme, girar, detenerme, hacer cuentas, buscar en Wikipedia "
            "o decirte el clima.")


def _extraer_json(texto: str) -> dict:
    """Gemma a veces rodea el JSON con texto o markdown; esto lo aísla."""
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta del modelo: {texto!r}")
    return json.loads(match.group(0))


def _clasificar(prompt: str) -> dict:
    """
    Groq decide qué tipo de pedido es (~1 s). Sin internet o si falla, Gemma (local); si tampoco, "desconocido".
    26/10/2026: Gemma iba primero, pero a veces se trababa 12 s (ReadTimeout) y al final decidía Groq igual.
    """
    respuesta = nube.clasificar(prompt)
    if respuesta is not None:
        return respuesta
    print("⚠️  Groq no clasificó: decide Gemma", flush=True)
    try:
        # num_predict: en modo JSON, Gemma a veces se queda generando espacios sin fin y traba a todos los
        # pedidos que vienen detrás. La respuesta real ocupa ~40 tokens.
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False, "format": "json", "keep_alive": "2h",
                  "options": {"num_predict": 150}},
            timeout=12,
        )
        resp.raise_for_status()
        return _extraer_json(resp.json()["response"])
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"⚠️  Gemma tampoco respondió ({type(e).__name__})", flush=True)
    return {"accion": "desconocido", "parametro": 0}


def _calcular(pedido: str, expresion_gemma: str, idioma: str) -> str:
    """Groq plantea la cuenta (también problemas en palabras), SymPy la hace. Sin Groq, la expresión de Gemma."""
    planteo = nube.plantear_cuenta(pedido, idioma)
    calculo = matematicas.calcular(planteo["expresion"], idioma) if planteo else None
    if calculo is not None:
        print(f'🧮 Cuenta (Groq + SymPy): {planteo["expresion"]}', flush=True)
        return matematicas.frase_resultado(calculo, idioma, planteo["unidad"], planteo["planteo"])
    print(f"🧮 Cuenta (Gemma + SymPy): {expresion_gemma}", flush=True)
    return matematicas.resolver(expresion_gemma, idioma)


_SOBRE_ARIES = re.compile(
    r"\b(te (construy|cre|hic|diseñ|program|arm)\w*|qui[eé]n eres|tus? (creador|equipo|dueñ)\w*|"
    r"who (built|made|created|designed|programmed) you|who are you|your (creators?|team|makers?)|"
    r"santiago roa|samuel romero|isaac padilla|mat[h]?[ií]as badel|david mart[ií]nez|"
    r"camilo (andr[eé]s )?espejo|espejo pab[oó]n|tu profesor|the professor)\b",
    re.IGNORECASE,
)


def _consultar(pedido: str, tema: str, idioma: str) -> str:
    # Sobre sí mismo, su equipo o el profesor no hay nada en Wikipedia: lo sabe por su personalidad (nube.py)
    if _SOBRE_ARIES.search(pedido):
        print("🤖 Pregunta sobre Aries o su equipo", flush=True)
        respuesta = nube.conversar(pedido, idioma)
        if respuesta:
            return respuesta
        if idioma == "en":
            return (f"I was built by {nube.EQUIPO.replace(' y ', ' and ')}, for the Electricity physics course "
                    f"taught by professor {nube.PROFESOR} at Universidad del Norte.")
        return (f"Me construyeron {nube.EQUIPO}, para el curso de Física Electricidad del profesor "
                f"{nube.PROFESOR}, en la Universidad del Norte.")
    return _consultar_saber(pedido, tema, idioma)


def _consultar_saber(pedido: str, tema: str, idioma: str) -> str:
    """
    Primero Wikipedia y Groq responde SOLO con eso: sin fuente, el modelo inventa (a cualquier persona la
    hacía profesor de la universidad). Sin artículo, Groq con la regla de no inventar; sin internet, lo guardado.
    """
    fuente = enciclopedia.contexto(tema, idioma, pregunta=pedido)
    respuesta = nube.responder_con_fuente(pedido, fuente, idioma, tema) if fuente else nube.conversar(pedido, idioma)
    if respuesta:
        origen = f'Wikipedia «{fuente["titulo"]}»{" (varios con ese nombre)" if fuente["varios"] else ""}' if fuente else "sin artículo"
        print(f'☁️  Groq responde "{tema}" con {origen}', flush=True)
        return respuesta
    enciclopedia.ultimo_articulo = None
    frase = enciclopedia.resumen(tema, idioma)
    print(f'📚 Wikipedia: tema "{tema}" -> artículo "{enciclopedia.ultimo_articulo or "(guardado o ninguno)"}"', flush=True)
    return frase


def _datos_ultimo_movimiento(idioma: str) -> tuple[str, str] | None:
    """(datos para el modelo, resumen corto para decir sin internet) del último registro, o None si no hay."""
    import fisica
    import registro

    archivos = registro.movimientos()
    medido = registro.leer_csv(archivos[-1]) if archivos else None
    if medido is None or len(medido["t_ms"]) < 3:
        return None
    c = fisica.calcular(medido)
    r = fisica.resumen(c)
    en = idioma == "en"

    def n(valor: float, decimales: int = 2) -> str:
        texto = f"{valor:.{decimales}f}"
        return texto if en else texto.replace(".", ",")

    comandos = ", ".join(e for _, e in medido["eventos"]) or ("none" if en else "ninguno")
    eficiencia = 100 * r["energia_cinetica_max"] / r["energia"] if r["energia"] > 0 else 0.0
    v_min = float(min(c["voltaje"]))
    if en:
        datos = (f"Commands: {comandos}. Time moving: {n(r['tiempo'], 1)} s. Displacement: {n(r['distancia'])} m. "
                 f"Distance traveled: {n(r['recorrido'])} m. Average speed: {n(r['v_media'])} m/s. Top speed: "
                 f"{n(r['v_max'])} m/s. Max acceleration: {n(r['a_max'])} m/s². Angle turned: {round(r['angulo'])} "
                 f"degrees. Max motor current: {n(r['corriente_max'])} A. Lowest battery voltage: {n(v_min)} V. "
                 f"Average electric power: {n(r['potencia_media'])} W. Electric energy used: {n(r['energia'], 1)} J. "
                 f"Max kinetic energy: {n(r['energia_cinetica_max'], 3)} J (mass {fisica.MASA} kg). "
                 f"Kinetic energy over electric energy: {n(eficiencia, 1)} percent.")
        corto = (f"In my last movement I traveled {n(r['recorrido'])} meters in {n(r['tiempo'], 1)} seconds, at an "
                 f"average speed of {n(r['v_media'])} meters per second, and I used {n(r['energia'], 1)} joules.")
    else:
        datos = (f"Comandos: {comandos}. Tiempo en movimiento: {n(r['tiempo'], 1)} s. Desplazamiento: "
                 f"{n(r['distancia'])} m. Distancia recorrida: {n(r['recorrido'])} m. Rapidez media: {n(r['v_media'])} m/s. "
                 f"Velocidad máxima: {n(r['v_max'])} m/s. Aceleración máxima: {n(r['a_max'])} m/s². Ángulo girado: "
                 f"{round(r['angulo'])} grados. Corriente máxima de los motores: {n(r['corriente_max'])} A. Voltaje "
                 f"mínimo de las pilas: {n(v_min)} V. Potencia eléctrica media: {n(r['potencia_media'])} W. Energía "
                 f"eléctrica gastada: {n(r['energia'], 1)} J. Energía cinética máxima: {n(r['energia_cinetica_max'], 3)} J "
                 f"(masa {n(fisica.MASA)} kg). Energía cinética sobre energía eléctrica: {n(eficiencia, 1)} por ciento.")
        corto = (f"En mi último movimiento recorrí {n(r['recorrido'])} metros en {n(r['tiempo'], 1)} segundos, a una "
                 f"rapidez media de {n(r['v_media'])} metros por segundo, y gasté {n(r['energia'], 1)} julios.")
    return datos, corto


def _explicar(pedido: str, idioma: str) -> str:
    """Los números salen del último registro (fisica.py); Groq solo explica la física con esos números."""
    datos = _datos_ultimo_movimiento(idioma)
    if datos is None:
        return ("I don't have any saved movement yet. Ask me to move, and then say stop." if idioma == "en"
                else "Todavía no tengo ningún movimiento guardado. Pídeme que me mueva y después dime para.")
    print(f"📈 Explicando el último movimiento: {datos[0]}", flush=True)
    return nube.explicar_medicion(pedido, datos[0], idioma) or datos[1]


def precargar() -> None:
    """Carga Gemma en la GPU de entrada; si no, el primer comando tarda ~15 s en responder."""
    requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": "", "keep_alive": "2h"}, timeout=60)


def donde_esta_gemma() -> str:
    """Dónde la cargó Ollama: tarjeta gráfica (NVIDIA o AMD, Ollama elige solo) o procesador."""
    try:
        cargados = requests.get(OLLAMA_URL.replace("/api/generate", "/api/ps"), timeout=5).json()["models"]
        gemma = next(m for m in cargados if m["name"].startswith(MODEL.split(":")[0]))
    except (requests.RequestException, KeyError, StopIteration, ValueError):
        return "sin saber dónde"
    en_video = gemma.get("size_vram", 0) / max(gemma.get("size", 1), 1)
    if en_video > 0.9:
        return "en la tarjeta gráfica"
    if en_video > 0:
        return f"{en_video:.0%} en la tarjeta gráfica y el resto en el procesador"
    return "en el procesador (va a responder más lento)"


def preguntar(comando_usuario: str, idioma: str | None = None) -> dict:
    """
    Envía el comando del usuario a Groq (o a Gemma sin internet) y devuelve un dict validado:
    {"accion": str, "parametro": float, "idioma": "es"|"en", "respuesta_hablada": str}

    idioma: si viene de Whisper (audio) se usa ese; si es None se detecta del texto.
    """
    if idioma not in ("es", "en"):
        idioma = detectar_idioma(comando_usuario)

    solo_saludo, pedido = separar_saludo(comando_usuario)
    if solo_saludo:
        return {"accion": "saludo", "parametro": 0.0, "idioma": idioma, "respuesta_hablada": frase_accion("saludo", 0, idioma)}

    if _REINICIO.search(pedido):
        return {"accion": "reiniciar", "parametro": 0.0, "idioma": idioma, "respuesta_hablada": frase_accion("reiniciar", 0, idioma)}

    # Discursos fijos de la feria: "Aries, introdúcete" y "Aries, agradece" (siempre en español)
    if _PRESENTATE.search(pedido):
        return {"accion": "presentacion", "parametro": 0.0, "idioma": "es", "respuesta_hablada": PRESENTACION}
    if _AGRADECE.search(pedido):
        return {"accion": "agradecimiento", "parametro": 0.0, "idioma": "es", "respuesta_hablada": AGRADECIMIENTO}

    prompt = SYSTEM_PROMPT.replace("__COMANDO__", pedido).replace("__IDIOMA__", "inglés" if idioma == "en" else "español")

    crudo = _clasificar(prompt)

    # No confiar a ciegas en el modelo: acción fuera de la lista o número inválido -> no se mueve
    accion = crudo.get("accion")
    try:
        parametro = float(crudo.get("parametro", 0))
    except (TypeError, ValueError):
        parametro = 0.0
    if accion not in ACCIONES_VALIDAS:
        accion = "desconocido"
    # Moverse solo si el pedido habla de moverse: sin internet Gemma a veces inventa "avanzar" para
    # frases que no lo piden. Entonces se charla en vez de mover el robot
    if accion in ("avanzar", "retroceder", "girar") and not _PIDE_MOVERSE.search(pedido):
        accion = "desconocido"
    # "retrocede" sale a veces "retrasa", "retrasión", "retos": Gemma lo tomaba por avanzar
    if accion == "avanzar" and _ATRAS.search(pedido):
        accion = "retroceder"
    # "avanza 30 centímetros": Gemma a veces devuelve 30 (metros). Si el pedido trae la unidad, manda ella
    if accion in ("avanzar", "retroceder") and (distancia := _distancia_en_metros(pedido)) is not None:
        parametro = distancia
    # "avanza 617": casi siempre es algo mal oído. En un salón no hay espacio para más de 5 metros
    if accion in ("avanzar", "retroceder") and abs(parametro) > DISTANCIA_MAXIMA:
        frase = (f"That's too far for me: I can move up to {DISTANCIA_MAXIMA} meters at a time." if idioma == "en"
                 else f"Eso es muy lejos para mí: puedo moverme hasta {DISTANCIA_MAXIMA} metros cada vez.")
        return {"accion": "conversar", "parametro": 0.0, "idioma": idioma, "respuesta_hablada": frase}
    # "¿Quién es el cantante X?" Gemma a veces lo toma por charla: una pregunta así siempre se busca
    pregunta_saber = _PREGUNTA_SABER.match(pedido)
    if accion == "desconocido" and pregunta_saber:
        accion = "consultar"
        crudo["tema"] = crudo.get("tema") or pregunta_saber.group("tema")
    if accion == "consultar" and _OPINION.search(pedido):
        accion = "desconocido"  # va a la charla con Groq
    if accion in SIN_MOVIMIENTO:
        parametro = 0.0

    if accion == "clima":
        frase = frase_clima(idioma)
    elif accion == "calcular":
        frase = _calcular(pedido, str(crudo.get("expresion", "")), idioma)
    elif accion == "consultar":
        frase = _consultar(pedido, str(crudo.get("tema", "")), idioma)
    elif accion == "explicar":
        frase = _explicar(pedido, idioma)
    elif accion == "desconocido" and (charla := nube.conversar(pedido, idioma)):
        print("☁️  Groq conversa", flush=True)
        accion, frase = "conversar", charla
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
