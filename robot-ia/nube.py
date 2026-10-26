"""
Cerebro grande de Aries en la nube (Groq): conversa, responde preguntas y explica la física de lo
que midió el robot. Es rápido (~1 s) pero necesita internet; si falla, cada función devuelve None
y brain.py usa lo local (Gemma, SymPy, Wikipedia guardada).

Los números nunca los inventa el modelo: las cuentas las hace SymPy (matematicas.py) y las
mediciones salen de los registros (fisica.py). Acá el modelo solo traduce y explica.

La clave va en robot-ia/.env (GROQ_API_KEY=...), que no se sube a git.
"""
import collections
import json
import os
import re
import time
from pathlib import Path

import requests

NOMBRE_ROBOT = "Aries"  # el mismo que en brain.py (no se importa de ahí: brain.py importa este módulo)

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELO = "openai/gpt-oss-120b"
TIEMPO_MAX_S = 8
RECUERDA_S = 120  # la charla recuerda lo último que se dijo durante este tiempo ("¿y por qué?")

EQUIPO = ("Santiago Roa, Samuel Romero Martínez, Isaac Padilla de la Hoz, Mathias Badel Gómez y David Martínez "
          "Sabalza")
PROFESOR = "Camilo Andrés Espejo Pabón"

PERSONALIDAD = {
    "es": (f"Eres {NOMBRE_ROBOT}, un robot laboratorio de física hecho por estudiantes de la Universidad del Norte "
           f"(Barranquilla, Colombia) para el curso de Física Electricidad, para la feria GeoExpoFísica 2026. Te "
           f"construyeron {EQUIPO}, y el profesor del curso es {PROFESOR}; si te preguntan por alguno de ellos "
           f"(aunque digan solo nombre y apellido, como 'Camilo Espejo' o 'Samuel Romero'), responde con eso. Mides con tus sensores posición, velocidad, "
           "aceleración, giro, voltaje, corriente y energía. Hablas en voz alta: responde en español, en máximo dos "
           "oraciones cortas, sin listas, sin emojis, sin símbolos ni fórmulas escritas (di 'metros por segundo', no "
           "'m/s'), con los decimales con coma. Eres amable, curioso y con un poco de humor. Nunca inventes datos "
           "sobre personas, lugares o hechos: si no estás seguro de quién es alguien, dilo y pide más detalles. "
           "No supongas que las personas por las que te preguntan tienen relación con la universidad. Si te piden "
           "una opinión o un gusto (el mejor equipo, tu comida favorita), no te niegues: di que es cuestión de "
           "gustos, nombra opciones conocidas y da una preferencia divertida de robot barranquillero. \"El mejor equipo\" "
           "sin más es de fútbol; el equipo de Barranquilla es el Junior. A tu universidad dile Uninorte o "
           "Universidad del Norte, nunca UN (esa sigla es de la Universidad Nacional)."),
    "en": (f"You are {NOMBRE_ROBOT}, a physics-lab robot built by students at Universidad del Norte (Barranquilla, "
           f"Colombia) for an Electricity physics course, for the GeoExpoFísica 2026 science fair. You were built by "
           f"{EQUIPO}, and the course professor is {PROFESOR}; if you are asked about any of them (even by first "
           f"and last name only, like 'Camilo Espejo' or 'Samuel Romero'), answer with that. Your sensors measure position, speed, acceleration, turning, "
           "voltage, current and energy. You speak out loud: answer in English, in at most two short sentences, no "
           "lists, no emojis, no symbols or written formulas (say 'meters per second', not 'm/s'). You are friendly, "
           "curious and a bit funny. Never make up facts about people, places or events: if you are not sure who "
           "someone is, say so and ask for more details. Do not assume the people you are asked about are related "
           "to the university. If you are asked for an opinion or a taste (the best team, your favorite food), do "
           "not refuse: say it is a matter of taste, name well-known options and give a fun robot-from-Barranquilla "
           "preference. 'The best team' with nothing else means soccer; Barranquilla's team is Junior. Call "
           "your university Uninorte or Universidad del Norte, never UN (that is Universidad Nacional)."),
}

_historia: collections.deque = collections.deque(maxlen=6)
_ultima_vez = 0.0
_clave: str | None = None


def _leer_clave() -> str | None:
    global _clave
    if _clave is None:
        _clave = os.environ.get("GROQ_API_KEY", "")
        archivo = Path(__file__).parent / ".env"
        if not _clave and archivo.exists():
            for linea in archivo.read_text(encoding="utf-8").splitlines():
                if linea.strip().startswith("GROQ_API_KEY="):
                    _clave = linea.split("=", 1)[1].strip()
    return _clave or None


def disponible() -> bool:
    return _leer_clave() is not None


def _llamar(mensajes: list[dict], json_salida: bool = False, max_tokens: int = 1500,
            temperatura: float = 0.5) -> str | None:
    # max_tokens incluye lo que el modelo "piensa" antes de responder: con poco, la respuesta sale cortada
    clave = _leer_clave()
    if not clave:
        return None
    cuerpo = {"model": MODELO, "messages": mensajes, "temperature": temperatura, "max_completion_tokens": max_tokens,
              "reasoning_effort": "low"}
    if json_salida:
        cuerpo["response_format"] = {"type": "json_object"}
    try:
        resp = requests.post(URL, headers={"Authorization": f"Bearer {clave}"}, json=cuerpo, timeout=TIEMPO_MAX_S)
        resp.raise_for_status()
        eleccion = resp.json()["choices"][0]
        texto = eleccion["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"☁️  Groq no respondió ({type(e).__name__}): se usa lo local", flush=True)
        return None
    if eleccion.get("finish_reason") == "length":
        print("☁️  La respuesta de Groq salió cortada: se usa lo local", flush=True)
        return None  # media frase dicha en voz alta suena peor que la respuesta de respaldo
    texto = " ".join((texto or "").split())
    if not json_salida:
        # Aunque se le pide, a veces escribe fórmulas ("V = R · I"): la voz no sabe leer los símbolos
        espanol = bool(re.search(r"[áéíóúñ¿¡]| (el|la|los|las|es|de|que) ", texto, re.IGNORECASE))
        igual, por = (" igual a ", " por ") if espanol else (" equals ", " times ")
        for simbolo, palabra in ((" = ", igual), (" · ", por), (" × ", por), ("·", por)):
            texto = texto.replace(simbolo, palabra)
    return texto or None


def conversar(texto: str, idioma: str) -> str | None:
    """Charla y preguntas de conocimiento ("¿por qué el cielo es azul?", "cuéntame un chiste")."""
    global _ultima_vez
    if time.time() - _ultima_vez > RECUERDA_S:
        _historia.clear()
    mensajes = [{"role": "system", "content": PERSONALIDAD["en" if idioma == "en" else "es"]}, *_historia,
                {"role": "user", "content": texto}]
    respuesta = _llamar(mensajes)
    if respuesta:
        _historia.extend([{"role": "user", "content": texto}, {"role": "assistant", "content": respuesta}])
        _ultima_vez = time.time()
    return respuesta


def responder_con_fuente(pregunta: str, fuente: dict, idioma: str, tema: str = "") -> str | None:
    """Responde una pregunta usando SOLO lo que dice Wikipedia (enciclopedia.contexto): así no inventa."""
    en = idioma == "en"
    if fuente.get("parecido"):
        # La búsqueda encontró un artículo con un nombre distinto: puede ser otra persona
        aviso = (f" The article is about «{fuente['titulo']}», but they asked about «{tema}». If they are not clearly "
                 f"the same, say you did not find «{tema}», briefly say who «{fuente['titulo']}» is, and ask if that "
                 f"is who they mean." if en else
                 f" El artículo es sobre «{fuente['titulo']}», pero preguntaron por «{tema}». Si no es claramente la "
                 f"misma persona o cosa, di que no encontraste a «{tema}», cuenta brevemente quién es "
                 f"«{fuente['titulo']}» y pregunta si se refieren a eso.")
    else:
        aviso = ""
    if fuente["varios"]:
        regla = ("This Wikipedia page lists several people or things with that name. Say briefly that there are "
                 "several and name each one in a few words, then ask which one they mean."
                 if en else
                 "Esta página de Wikipedia lista varias personas o cosas con ese nombre. Di brevemente que hay "
                 "varias, nombra cada una en pocas palabras y pregunta a cuál se refieren.")
    else:
        regla = ("Answer the question using ONLY the Wikipedia text below. If it does not answer the question, or it "
                 "is about a different person or thing than the one asked, say you did not find reliable information."
                 if en else
                 "Responde la pregunta usando SOLO el texto de Wikipedia de abajo. Si no responde la pregunta, o habla "
                 "de una persona o cosa distinta a la que preguntan, di que no encontraste información confiable.")
    sistema = (PERSONALIDAD["en" if en else "es"] + " " + regla + aviso +
               f"\n\nWikipedia, «{fuente['titulo']}»:\n{fuente['texto']}")
    return _llamar([{"role": "system", "content": sistema}, {"role": "user", "content": pregunta}])


_INSTRUCCIONES_CUENTA ="""Convierte el pedido matemático o de física en UNA expresión para SymPy y responde solo JSON:
{"expresion": "...", "unidad": "...", "planteo": "..."}
- "expresion": sintaxis de Python/SymPy. * multiplica, ** potencia, sqrt(), sin() cos() tan() con grados como 30*deg,
  pi, ecuaciones con un solo = y la incógnita x, diff(f, x), integrate(f, x). Usa SI (g = 9.81).
  Para convertir unidades: "<cantidad con unidades> to <unidades>" con nombres en inglés y singular (meter, kilometer,
  second, hour, kilogram, newton, joule, kilojoule, watt, kilowatt, kilowatthour, volt, ampere, milliampere, ohm,
  coulomb, tesla, hertz, calorie, horsepower).
- "unidad": la unidad del resultado dicha en palabras y en el idioma indicado ("metros", "julios" / "meters",
  "joules"); vacío si no tiene o si es una conversión de unidades.
- "planteo": en el idioma indicado, la ley o fórmula usada dicha SOLO con palabras, corta ("distancia igual a
  velocidad por tiempo", "velocidad igual a la raíz de dos por la gravedad por la altura"), sin símbolos ni
  asteriscos; vacío si es una cuenta directa.
Ejemplos:
"cuánto es 25 por 4" -> {"expresion": "25*4", "unidad": "", "planteo": ""}
"si un carro va a 20 metros por segundo durante 5 segundos, cuánto recorre" ->
  {"expresion": "20*5", "unidad": "metros", "planteo": "distancia igual a velocidad por tiempo"}
"qué corriente pasa por una resistencia de 10 ohmios con 5 voltios" ->
  {"expresion": "5/10", "unidad": "amperios", "planteo": "por la ley de Ohm, corriente igual a voltaje sobre resistencia"}
"resuelve x al cuadrado menos 4 igual a cero" -> {"expresion": "x**2 - 4 = 0", "unidad": "", "planteo": ""}
"cuántos julios son 5 kilovatios hora" -> {"expresion": "5*kilowatthour to joule", "unidad": "", "planteo": ""}"""


def plantear_cuenta(texto: str, idioma: str = "es") -> dict | None:
    """El pedido en palabras -> {"expresion", "unidad", "planteo"} para que SymPy haga la cuenta."""
    pedido = f"Idioma: {'inglés' if idioma == 'en' else 'español'}.\nPedido: {texto}"
    respuesta = _llamar([{"role": "system", "content": _INSTRUCCIONES_CUENTA}, {"role": "user", "content": pedido}],
                        json_salida=True)
    if not respuesta:
        return None
    try:
        datos = json.loads(respuesta)
    except ValueError:
        return None
    if not isinstance(datos, dict) or not str(datos.get("expresion", "")).strip():
        return None
    planteo = {k: str(datos.get(k, "")).strip() for k in ("expresion", "unidad", "planteo")}
    # Por si igual se le escapa un símbolo: la voz no sabe leer "2*g*h"
    planteo["planteo"] = " ".join(planteo["planteo"].replace("*", " por ").replace("/", " sobre ").split())
    return planteo


def clasificar(prompt: str) -> dict | None:
    """Decide la acción con el mismo prompt de brain.py (pide un JSON). Gemma queda de respaldo sin internet."""
    # Temperatura 0: la misma orden tiene que dar siempre la misma acción
    respuesta = _llamar([{"role": "user", "content": prompt}], json_salida=True, temperatura=0)
    try:
        datos = json.loads(respuesta) if respuesta else None
    except ValueError:
        return None
    return datos if isinstance(datos, dict) else None


def explicar_medicion(pedido: str, datos: str, idioma: str) -> str | None:
    """Explica la física de un registro del robot usando SOLO los números que se le pasan."""
    en = idioma == "en"
    instrucciones = PERSONALIDAD["en" if en else "es"] + (
        " Now explain the physics of your last movement to visitors at a science fair, in at most three short "
        "sentences. Do not just list numbers: pick the two or three most interesting ones and connect them with "
        "physics ideas (uniform or accelerated motion, kinetic energy, electric power as voltage times current, "
        "how little of the battery energy became motion and where the rest went, like heat and friction). "
        "Use ONLY the numbers given below, written with digits exactly as they are (like 2.70), never spelled out "
        "in words; do not calculate new numbers. At most 60 words."
        if en else
        " Ahora explica la física de tu último movimiento a visitantes de una feria de ciencias, en máximo tres "
        "oraciones cortas. No enumeres números: elige los dos o tres más interesantes y conéctalos con ideas de "
        "física (movimiento uniforme o acelerado, energía cinética, potencia eléctrica como voltaje por corriente, "
        "qué tan poca energía de las pilas se volvió movimiento y a dónde se fue el resto, como calor y fricción). "
        "Usa SOLO los números de abajo, escritos con cifras tal como están (como 2,70), nunca en letras; no "
        "calcules números nuevos. Máximo 60 palabras."
    ) + "\n\n" + datos
    return _llamar([{"role": "system", "content": instrucciones}, {"role": "user", "content": pedido}])
