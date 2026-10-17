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

_modelo = None


def cargar() -> None:
    global _modelo
    if _modelo is None:
        _modelo = whisper.load_model("small")


def detectar_idioma(audio: str | np.ndarray) -> str:
    """Whisper detecta ~100 idiomas; con clips cortos a veces elige portugués o italiano, así que se limita a es/en."""
    cargar()
    if isinstance(audio, str):
        audio = whisper.load_audio(audio)
    mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(audio), n_mels=_modelo.dims.n_mels).to(_modelo.device)
    _, probs = _modelo.detect_language(mel)
    return "en" if probs.get("en", 0) > probs.get("es", 0) else "es"


def _transcribir_en(audio: np.ndarray, idioma: str) -> tuple[str, float]:
    """Devuelve (texto, confianza). La confianza es el avg_logprob medio: más cerca de 0, más seguro."""
    # initial_prompt le enseña a Whisper cómo se escribe el nombre del robot (sin él, "Aries" sale "Arias")
    resultado = _modelo.transcribe(audio, language=idioma, initial_prompt=f"{NOMBRE_ROBOT}.")
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
    idioma = detectar_idioma(audio)
    texto, confianza = _transcribir_en(audio, idioma)

    # Con acento, Whisper suele tomar el inglés por español y entonces lo traduce
    # ("How's the weather?" -> "¿Cómo es el aire?"). Se transcribe también en inglés y gana
    # la versión más segura: en el idioma real la confianza sale mucho más alta (-0.27 vs -0.74).
    if idioma == "es":
        texto_en, confianza_en = _transcribir_en(audio, "en")
        if texto_en and confianza_en > confianza:
            return texto_en, "en"
    return texto, idioma
