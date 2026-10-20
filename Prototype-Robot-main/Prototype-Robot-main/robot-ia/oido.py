"""
Oído de Aries: convierte audio en texto con Whisper y detecta si es español o inglés.
Acepta la ruta de un archivo o un array float32 a 16 kHz.
"""
import numpy as np
import whisper

from brain import NOMBRE_ROBOT

# Con silencio o ruido Whisper "repite" el initial_prompt; esos fragmentos vienen con
# no_speech_prob alto (medido: ~0.8 en ruido vs <0.2 con voz real)
UMBRAL_SIN_VOZ = 0.5

# "small" con las PISTAS y la regla del idioma de abajo acierta casi igual que "turbo" en estas frases.
# "turbo" entiende algo mejor, pero junto con Gemma llena los 8 GB de la RTX 4070 y Windows empieza a
# usar la RAM: Gemma pasaba a tardar más de 2 minutos. Con más memoria de video se puede subir a "turbo".
MODELO = "small"

# initial_prompt: le muestra a Whisper cómo suelen ser las frases. Así escribe bien "Aries" (sin él a
# veces lo omite, y una frase sin el nombre se ignora) y las palabras de los comandos ("reinicia", "Ohm").
PISTAS = {
    "es": f"{NOMBRE_ROBOT}, avanza un metro. Gira a la derecha. Para. Reinicia. ¿Qué es la ley de Ohm? "
          "¿Cuánto es la raíz de 144?",
    "en": f"{NOMBRE_ROBOT}, move forward one meter. Turn right. Stop. Reset. What is Ohm's law? "
          "What's the square root of 144?",
}
# Para cambiar de español a inglés no basta con que la versión en inglés salga un poco más segura:
# en frases cortas en español, la "traducción" al inglés a veces gana por poco y Aries respondía en inglés
MARGEN_INGLES = 0.2
DUDA_INGLES = 0.15  # solo se prueba en inglés si la detección le dio al menos esta probabilidad

_modelo = None


def cargar() -> None:
    global _modelo
    if _modelo is None:
        _modelo = whisper.load_model(MODELO)


def _probabilidades(audio: np.ndarray) -> tuple[float, float]:
    """(probabilidad de español, de inglés). Whisper detecta ~100 idiomas; acá solo importan estos dos."""
    mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(audio), n_mels=_modelo.dims.n_mels).to(_modelo.device)
    _, probs = _modelo.detect_language(mel)
    return probs.get("es", 0.0), probs.get("en", 0.0)


def detectar_idioma(audio: str | np.ndarray) -> str:
    cargar()
    if isinstance(audio, str):
        audio = whisper.load_audio(audio)
    es, en = _probabilidades(audio)
    return "en" if en > es else "es"


def _transcribir_en(audio: np.ndarray, idioma: str) -> tuple[str, float]:
    """Devuelve (texto, confianza). La confianza es el avg_logprob medio: más cerca de 0, más seguro."""
    resultado = _modelo.transcribe(
        audio, language=idioma, initial_prompt=PISTAS[idioma], beam_size=5, condition_on_previous_text=False
    )
    segmentos = [s for s in resultado["segments"] if s["no_speech_prob"] <= UMBRAL_SIN_VOZ]
    if not segmentos:
        return "", float("-inf")
    texto = " ".join(s["text"].strip() for s in segmentos).strip()
    confianza = sum(s["avg_logprob"] for s in segmentos) / len(segmentos)
    return texto, confianza


def transcribir(audio: str | np.ndarray) -> tuple[str, str]:
    """Devuelve (texto, idioma). Texto vacío si no hubo voz."""
    cargar()
    if isinstance(audio, str):
        audio = whisper.load_audio(audio)
    prob_es, prob_en = _probabilidades(audio)
    idioma = "en" if prob_en > prob_es else "es"
    texto, confianza = _transcribir_en(audio, idioma)

    # Con acento, Whisper a veces toma el inglés por español y entonces lo traduce
    # ("How's the weather?" -> "¿Cómo es el aire?"). Si quedó la duda, se transcribe también en
    # inglés y gana solo si es claramente más segura (en el idioma real sale -0.27 contra -0.74)
    if idioma == "es" and prob_en >= DUDA_INGLES:
        texto_en, confianza_en = _transcribir_en(audio, "en")
        if texto_en and confianza_en > confianza + MARGEN_INGLES:
            return texto_en, "en"
    return texto, idioma
