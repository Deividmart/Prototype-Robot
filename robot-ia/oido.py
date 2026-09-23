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


def transcribir(audio: str | np.ndarray) -> tuple[str, str]:
    """Devuelve (texto, idioma). Texto vacío si no hubo voz."""
    cargar()
    idioma = detectar_idioma(audio)
    # initial_prompt le enseña a Whisper cómo se escribe el nombre del robot (sin él, "Aries" sale "Arias")
    resultado = _modelo.transcribe(audio, language=idioma, initial_prompt=f"{NOMBRE_ROBOT}.")
    texto = " ".join(
        s["text"].strip() for s in resultado["segments"] if s["no_speech_prob"] <= UMBRAL_SIN_VOZ
    ).strip()
    return texto, idioma
