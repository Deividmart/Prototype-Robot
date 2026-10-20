"""
Consulta el clima real con Open-Meteo (gratis, sin API key) y arma una frase para que el robot la diga.
Gemma no sabe el clima actual: si le preguntás directo, lo inventa. Por eso los datos salen de acá.
"""
import time

import requests

CIUDAD = "Barranquilla"
LATITUD = 10.9685
LONGITUD = -74.7813

URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SEG = 600

# Códigos WMO que devuelve Open-Meteo: (español, inglés)
DESCRIPCIONES = {
    0: ("está despejado", "it's clear"),
    1: ("está mayormente despejado", "it's mostly clear"),
    2: ("está parcialmente nublado", "it's partly cloudy"),
    3: ("está nublado", "it's cloudy"),
    45: ("hay niebla", "it's foggy"), 48: ("hay niebla", "it's foggy"),
    51: ("hay llovizna", "there's light drizzle"), 53: ("hay llovizna", "there's drizzle"),
    55: ("hay llovizna intensa", "there's heavy drizzle"),
    56: ("hay llovizna helada", "there's freezing drizzle"), 57: ("hay llovizna helada", "there's freezing drizzle"),
    61: ("está lloviendo suave", "it's raining lightly"), 63: ("está lloviendo", "it's raining"),
    65: ("está lloviendo fuerte", "it's raining heavily"),
    66: ("hay lluvia helada", "there's freezing rain"), 67: ("hay lluvia helada", "there's freezing rain"),
    71: ("está nevando", "it's snowing"), 73: ("está nevando", "it's snowing"),
    75: ("está nevando fuerte", "it's snowing heavily"), 77: ("está nevando", "it's snowing"),
    80: ("hay chubascos", "there are showers"), 81: ("hay chubascos", "there are showers"),
    82: ("hay chubascos fuertes", "there are heavy showers"),
    85: ("hay nevadas", "there are snow showers"), 86: ("hay nevadas fuertes", "there are heavy snow showers"),
    95: ("hay tormenta", "there's a thunderstorm"),
    96: ("hay tormenta con granizo", "there's a thunderstorm with hail"),
    99: ("hay tormenta con granizo", "there's a thunderstorm with hail"),
}

_cache = {"hasta": 0.0, "datos": None}


def obtener_clima() -> dict:
    if _cache["datos"] is not None and time.time() < _cache["hasta"]:
        return _cache["datos"]

    resp = requests.get(
        URL,
        params={
            "latitude": LATITUD,
            "longitude": LONGITUD,
            "current": "temperature_2m,apparent_temperature,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "America/Bogota",
            "forecast_days": 1,
        },
        timeout=5,
    )
    resp.raise_for_status()
    datos = resp.json()

    _cache["datos"] = datos
    _cache["hasta"] = time.time() + CACHE_SEG
    return datos


def frase_clima(idioma: str = "es") -> str:
    """Frase lista para decir en voz alta (números redondeados y sin símbolos, pensando en el TTS)."""
    en = idioma == "en"
    try:
        datos = obtener_clima()
    except requests.RequestException:
        if en:
            return "I couldn't check the weather right now, it looks like there's no internet connection."
        return "No pude consultar el clima ahora, parece que no hay conexión a internet."

    actual = datos["current"]
    hoy = datos["daily"]

    temp = round(actual["temperature_2m"])
    sensacion = round(actual["apparent_temperature"])
    estado_es, estado_en = DESCRIPCIONES.get(actual["weather_code"], ("el cielo está variable", "the sky is changing"))
    maxima = round(hoy["temperature_2m_max"][0])
    lluvia = hoy["precipitation_probability_max"][0]
    siente_mas = sensacion - temp >= 3

    if en:
        frase = f"In {CIUDAD} it's {temp} degrees Celsius"
        if siente_mas:
            frase += f", but it feels like {sensacion}"
        frase += f". {estado_en.capitalize()}. Today's high is {maxima} degrees"
        if lluvia is not None:
            frase += f", with a {lluvia} percent chance of rain"
            if lluvia >= 60:
                frase += ", so you'd better bring an umbrella"
        return frase + "."

    frase = f"En {CIUDAD} hay {temp} grados y {estado_es}"
    if siente_mas:
        frase += f", con sensación térmica de {sensacion}"
    frase += f". Hoy la máxima es de {maxima} grados"
    if lluvia is not None:
        frase += f" y hay {lluvia} por ciento de probabilidad de lluvia"
        if lluvia >= 60:
            frase += ", mejor lleva paraguas"
    return frase + "."


if __name__ == "__main__":
    print(frase_clima("es"))
    print(frase_clima("en"))
