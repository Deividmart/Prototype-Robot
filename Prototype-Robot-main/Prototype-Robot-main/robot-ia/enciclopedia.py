"""
Busca en Wikipedia (gratis, sin API key) lo que le preguntan a Aries ("¿qué es la ley de Ohm?",
"who was Faraday?") y arma un resumen corto para decirlo en voz alta.

Gemma solo extrae el tema; el contenido sale de Wikipedia, así el robot no inventa datos.

Lo que ya buscó queda guardado en datos/wikipedia.json: si en la feria se cae el internet (o
Wikipedia pide esperar por muchas consultas seguidas), lo que se ensayó antes igual funciona.
"""
import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import requests

# Wikimedia pide identificarse: sin User-Agent propio puede bloquear las consultas
CABECERAS = {"User-Agent": "AriesRobot/1.0 (robot laboratorio de fisica, Universidad del Norte)"}
ORACIONES = 2  # cuántas oraciones del resumen dice (más se hace largo de escuchar)
MAX_CARACTERES = 380
FRESCO_SEG = 7 * 24 * 3600  # después de esto se vuelve a consultar (si no hay internet, se usa igual)
ARCHIVO_CACHE = Path(__file__).parent / "datos" / "wikipedia.json"

_lock = threading.Lock()
ultimo_articulo: str | None = None  # el artículo que se leyó en la última consulta (para mostrarlo en pantalla)


class Esperar(Exception):
    """Wikipedia respondió 429: demasiadas consultas seguidas."""


def _cargar_cache() -> dict:
    try:
        return json.loads(ARCHIVO_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_cache(cache: dict) -> None:
    try:
        ARCHIVO_CACHE.parent.mkdir(exist_ok=True)
        ARCHIVO_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # sin cache igual responde


def _get(url: str, **params) -> dict:
    resp = requests.get(url, params=params or None, headers=CABECERAS, timeout=5)
    if resp.status_code == 429:
        raise Esperar()
    resp.raise_for_status()
    return resp.json()


def _buscar_titulos(consulta: str, idioma: str, cuantos: int) -> list[str]:
    """Busca artículos. Si el buscador principal está limitado (429) prueba con el de títulos, que
    tiene otro límite; si los dos lo están, devuelve [] y se sigue con lo que haya."""
    try:
        datos = _get(f"https://{idioma}.wikipedia.org/w/api.php", action="query", list="search",
                     srsearch=consulta, srlimit=cuantos, format="json", utf8=1)
        return [r["title"] for r in datos.get("query", {}).get("search", [])]
    except Esperar:
        pass
    try:
        datos = _get(f"https://{idioma}.wikipedia.org/w/rest.php/v1/search/title",
                     q=consulta.replace('intitle:"', "").strip('"'), limit=cuantos)
        return [p["title"] for p in datos.get("pages", [])]
    except Esperar:
        return []


_VACIAS = {"de", "del", "la", "el", "los", "las", "y", "en", "un", "una", "the", "of", "and", "a", "an"}


def _palabras(texto: str) -> set[str]:
    sin_tildes = unicodedata.normalize("NFD", texto.lower()).encode("ascii", "ignore").decode()
    return {p for p in re.findall(r"[a-z0-9]+", sin_tildes) if p not in _VACIAS and len(p) > 1}


def _relacionado(titulo: str, tema: str) -> bool:
    """Un resultado de búsqueda sirve solo si comparte alguna palabra con el tema ("Gravity Falls" no es "gravedad")."""
    return bool(_palabras(titulo) & _palabras(tema))


def _buscados(tema: str, idioma: str) -> list[str]:
    """Si no hay artículo con el nombre exacto: los de la búsqueda que tienen que ver con el tema."""
    return [t for t in _buscar_titulos(tema, idioma, 3) if _relacionado(t, tema)]


def _desambiguar(tema: str, idioma: str) -> list[str]:
    """Con un nombre ambiguo ("Mercurio"), los artículos que se llaman igual con aclaración
    ("Mercurio (planeta)"), primero los de Colombia, que es donde está el robot."""
    parecidos = [t for t in _buscar_titulos(f'intitle:"{tema}"', idioma, 10)
                 if t.lower().startswith(tema.lower()) and t.lower() != tema.lower()]
    return sorted(parecidos, key=lambda t: not re.search(r"colombia|barranquilla", t, re.IGNORECASE))


def _resumen_de(titulo: str, idioma: str) -> dict | None:
    try:
        return _get(f"https://{idioma}.wikipedia.org/api/rest_v1/page/summary/"
                    f"{requests.utils.quote(titulo.replace(' ', '_'))}")
    except requests.HTTPError:
        return None  # 404: no hay artículo con ese nombre


def _para_hablar(texto: str) -> str:
    """Saca lo que suena mal en voz alta (paréntesis, pronunciaciones) y lo deja corto."""
    texto = re.sub(r"/[^/]*[ˈˌːəɹɪʊæɛɔʃʒθðŋɐʁ][^/]*/", "", texto)  # pronunciación en AFI
    # "(pronunciación en inglés: /.../)": a veces Wikipedia corta el paréntesis, así que se borra solo hasta los dos puntos
    texto = re.sub(r"\(\s*(pronunciación|pronunciation|AFI|IPA)[^:()]*:?\s*\)?", "", texto, flags=re.IGNORECASE)
    anterior = None
    while anterior != texto:  # paréntesis anidados
        anterior = texto
        texto = re.sub(r"\s*\([^()]*\)", "", texto)
    texto = re.sub(r"\s*\[[^\]]*\]", "", texto)
    texto = re.sub(r"\s+([,.;:])", r"\1", re.sub(r"\s+", " ", texto)).strip()
    # Corta en oraciones sin partir números como "3.5"
    oraciones = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])", texto)
    # Una oración que termina en ":" anuncia una fórmula o una lista que no se puede decir
    oraciones = [o for o in oraciones if not o.endswith(":")]
    corto = " ".join(oraciones[:ORACIONES])
    if len(corto) > MAX_CARACTERES and oraciones:
        corto = oraciones[0]  # mejor una oración entera que dos cortadas
    if len(corto) > MAX_CARACTERES:
        corto = corto[:MAX_CARACTERES].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return corto


def _buscar(tema: str, idioma: str) -> str | None:
    """La frase para el tema, o None si no hay artículo. Deja pasar Esperar y los errores de red."""
    en = idioma == "en"
    ambiguo = None
    # Primero el artículo con el nombre exacto: casi siempre es el bueno y es una sola consulta
    # (Wikipedia limita a quien consulta mucho seguido). Solo si no existe, se busca.
    candidatos = [tema[:1].upper() + tema[1:]]
    buscado = False
    while candidatos:
        titulo = candidatos.pop(0)
        datos = _resumen_de(titulo, idioma)
        if datos is None:
            if not buscado and ambiguo is None:
                buscado = True
                candidatos += [t for t in _buscados(tema, idioma) if t != titulo]
            continue
        if datos.get("type") == "disambiguation":
            if ambiguo is None:
                # Los demás resultados de la búsqueda suelen ser otra cosa ("El Mercurio", un periódico):
                # después de un nombre ambiguo solo valen los que se llaman igual, con aclaración
                ambiguo = titulo
                candidatos = _desambiguar(tema, idioma)[:3]
            continue
        if ambiguo and not titulo.lower().startswith(tema.lower()):
            continue
        extracto = _para_hablar(datos.get("extract", ""))
        if extracto:
            global ultimo_articulo
            ultimo_articulo = titulo
            return f"According to Wikipedia: {extracto}" if en else f"Según Wikipedia: {extracto}"
    if ambiguo:
        return (f"{ambiguo} can mean several things. Could you be more specific?" if en
                else f"{ambiguo} puede significar varias cosas. ¿Me dices cuál?")
    return None


def _intro(titulo: str, idioma: str) -> dict | None:
    """La introducción del artículo en texto plano (en una página de desambiguación, la lista de opciones)."""
    datos = _get(f"https://{idioma}.wikipedia.org/w/api.php", action="query", prop="extracts|pageprops",
                 exintro=1, explaintext=1, redirects=1, titles=titulo, format="json", utf8=1)
    for pagina in datos.get("query", {}).get("pages", {}).values():
        if "missing" in pagina or not pagina.get("extract"):
            return None
        return {"titulo": pagina["title"], "texto": pagina["extract"][:1500],
                "varios": "disambiguation" in pagina.get("pageprops", {})}
    return None


_PALABRAS_PREGUNTA = {"quien", "que", "es", "fue", "era", "son", "who", "what", "is", "was", "are", "aries",
                      "dime", "sabes", "conoces", "tell", "me", "about", "do", "you", "know", "hablame", "cuentame"}


def _precisar(tema: str, pregunta: str, idioma: str) -> dict | None:
    """Con varios del mismo nombre, si la pregunta trae una pista ("el cantante Álvaro Díaz"), busca ese."""
    pistas = _palabras(pregunta) - _palabras(tema) - _PALABRAS_PREGUNTA
    if not pistas:
        return None
    for titulo in _buscar_titulos(f"{tema} {' '.join(sorted(pistas))}", idioma, 3):
        if _palabras(tema) <= _palabras(titulo):  # el artículo tiene que llevar el nombre completo
            datos = _intro(titulo, idioma)
            if datos and not datos["varios"]:
                return datos
    return None


def contexto(tema: str, idioma: str = "es", pregunta: str = "") -> dict | None:
    """
    Lo que dice Wikipedia sobre el tema, para que Groq responda con eso y no invente:
    {"titulo", "texto", "varios"} ("varios": es una página con varias personas o cosas del mismo nombre).
    None si no hay internet o no hay artículo. Lo que encuentra queda guardado para usarlo sin internet.
    """
    idioma = "en" if idioma == "en" else "es"
    tema = (tema or "").strip()
    if not tema:
        return None
    datos = _contexto_del_tema(tema, idioma)
    if datos and datos["varios"] and pregunta:
        # La pista depende de esta pregunta ("el cantante..."): se busca siempre y no se guarda bajo el tema solo
        try:
            precisado = _precisar(tema, pregunta, idioma)
        except (Esperar, requests.RequestException):
            precisado = None
        if precisado:
            return precisado
    return datos


def _contexto_del_tema(tema: str, idioma: str) -> dict | None:
    clave = f"ctx:{idioma}:{tema.lower()}"
    with _lock:
        guardado = _cargar_cache().get(clave)
    if guardado and time.time() - guardado["cuando"] < FRESCO_SEG:
        return guardado["datos"]
    try:
        datos = _intro(tema, idioma)
        if datos is None:
            parecidos = _buscados(tema, idioma)
            datos = _intro(parecidos[0], idioma) if parecidos else None
            if datos:
                # Lo encontró la búsqueda con otro nombre ("Juan Pedro Pérez-Gómez" por "Juan Pérez Gómez"):
                # puede ser otra persona, y quien responde tiene que aclararlo
                datos["parecido"] = _palabras(datos["titulo"]) != _palabras(tema)
    except Esperar:
        # La API de búsqueda pidió esperar: el resumen corto va por otro lado y suele seguir andando
        try:
            corto = _resumen_de(tema[:1].upper() + tema[1:], idioma)
        except (Esperar, requests.RequestException):
            corto = None
        datos = ({"titulo": corto["title"], "texto": corto.get("extract", ""),
                  "varios": corto.get("type") == "disambiguation"} if corto else None)
    except requests.RequestException:
        return guardado["datos"] if guardado else None
    if datos:
        with _lock:
            cache = _cargar_cache()
            cache[clave] = {"cuando": time.time(), "datos": datos}
            _guardar_cache(cache)
    return datos


def resumen(tema: str, idioma: str = "es") -> str:
    """Frase lista para decir sobre el tema, o una disculpa si no se pudo."""
    en = idioma == "en"
    idioma = "en" if en else "es"
    tema = (tema or "").strip()
    if not tema:
        return "What would you like me to look up?" if en else "¿Sobre qué quieres que busque?"

    clave = f"{idioma}:{tema.lower()}"
    with _lock:
        cache = _cargar_cache()
    guardado = cache.get(clave)
    if guardado and time.time() - guardado["cuando"] < FRESCO_SEG:
        return guardado["frase"]

    try:
        frase = _buscar(tema, idioma)
    except (Esperar, requests.RequestException) as e:
        if guardado:  # sin internet o con Wikipedia ocupada, lo que ya sabía sirve
            return guardado["frase"]
        if isinstance(e, Esperar):
            return ("Wikipedia asked me to wait a moment. Ask me again in a minute." if en
                    else "Wikipedia me pidió esperar un momento. Pregúntame otra vez en un minuto.")
        return ("I can't look that up right now, it looks like there's no internet connection." if en
                else "Ahora no puedo buscar eso, parece que no hay conexión a internet.")

    if frase is None:
        return f"I didn't find anything about {tema}." if en else f"No encontré nada sobre {tema}."
    with _lock:
        cache = _cargar_cache()
        cache[clave] = {"cuando": time.time(), "frase": frase}
        _guardar_cache(cache)
    return frase


if __name__ == "__main__":
    for tema, idioma in [("ley de Ohm", "es"), ("Universidad del Norte", "es"), ("Canberra", "es"),
                         ("Mercurio", "es"), ("Torre Eiffel", "es"), ("Ohm's law", "en"), ("asdkjhqwe", "es")]:
        print(f"[{idioma}] {tema}: {resumen(tema, idioma)}\n")
