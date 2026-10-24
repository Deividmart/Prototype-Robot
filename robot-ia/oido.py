"""
Oído de Aries: convierte audio en texto con Whisper y detecta si es español o inglés.
Acepta la ruta de un archivo o un array float32 a 16 kHz.

Dos motores, se elige solo:
  - "openai": Whisper original en la tarjeta gráfica NVIDIA (CUDA).
  - "rapido": faster-whisper en el procesador. Para PCs con tarjeta AMD (o sin tarjeta): PyTorch en
    Windows solo usa NVIDIA, y el Whisper original en el procesador tarda varios segundos por frase.
    Gemma sí usa la AMD: eso lo maneja Ollama solo.
Con ARIES_WHISPER=openai o ARIES_WHISPER=rapido se fuerza uno.
"""
import os

import numpy as np
import whisper

from brain import NOMBRE_ROBOT


def _elegir_motor() -> str:
    forzado = os.environ.get("ARIES_WHISPER", "").lower()
    if forzado in ("openai", "rapido"):
        return forzado
    try:
        import torch

        if torch.cuda.is_available():
            return "openai"
    except ImportError:
        pass
    try:
        import faster_whisper  # noqa: F401

        return "rapido"
    except ImportError:
        return "openai"  # sin faster-whisper: el original en el procesador (lento, pero anda)


MOTOR = _elegir_motor()
# En el procesador "small" tarda ~4 s por frase (medido en un Ryzen de 16 núcleos) y "base" ~1,3 s con
# las mismas frases bien escritas gracias a las PISTAS. Con ARIES_WHISPER_MODELO=small se cambia.
MODELO_RAPIDO = os.environ.get("ARIES_WHISPER_MODELO", "base")
HILOS_RAPIDO = 4  # más hilos no lo aceleraban (la mitad del tiempo se va en pasar datos entre ellos)

# Con silencio o ruido Whisper "repite" el initial_prompt; esos fragmentos vienen con
# no_speech_prob alto (medido: ~0.8 en ruido vs <0.2 con voz real)
UMBRAL_SIN_VOZ = 0.5

# "small" con las PISTAS y la regla del idioma de abajo acierta casi igual que "turbo" en estas frases.
# "turbo" entiende algo mejor, pero junto con Gemma llena los 8 GB de la RTX 4070 y Windows empieza a
# usar la RAM: Gemma pasaba a tardar más de 2 minutos. Con más memoria de video se puede subir a "turbo".
MODELO = "small"

# initial_prompt: le muestra a Whisper cómo suelen ser las frases. Así escribe bien "Aries" (sin él a
# veces lo omite, y una frase sin el nombre se ignora) y las palabras de los comandos ("reinicia", "Ohm").
# Con ruido o silencio Whisper a veces "inventa" las pistas tal cual: por eso son una descripción y no
# órdenes ("Aries, avanza un metro" inventado movía al robot), y escucha.py descarta lo que sea copia de ellas.
PISTAS = {
    "es": f"Le hablan a {NOMBRE_ROBOT}, un robot de física, y le dicen avanza, retrocede, gira a la derecha, "
          "para o reinicia; también le preguntan por la ley de Ohm o la raíz de 144.",
    "en": f"People talk to {NOMBRE_ROBOT}, a physics robot, and tell it move forward, move back, turn right, "
          "stop or reset; they also ask about Ohm's law or the square root of 144.",
}
# Para cambiar de español a inglés no basta con que la versión en inglés salga un poco más segura:
# en frases cortas en español, la "traducción" al inglés a veces gana por poco y Aries respondía en inglés
MARGEN_INGLES = 0.2
DUDA_INGLES = 0.15  # solo se prueba en inglés si la detección le dio al menos esta probabilidad

_modelo = None


def cargar() -> None:
    global _modelo
    if _modelo is not None:
        return
    if MOTOR == "rapido":
        from faster_whisper import WhisperModel

        # int8: en el procesador va unas 4 veces más rápido que el original, casi sin perder acierto
        _modelo = WhisperModel(MODELO_RAPIDO, device="cpu", compute_type="int8", cpu_threads=HILOS_RAPIDO)
    else:
        _modelo = whisper.load_model(MODELO)


def descripcion() -> str:
    """Para el mensaje de arranque del servidor."""
    if MOTOR == "rapido":
        return f"{MODELO_RAPIDO}, en el procesador con faster-whisper"
    return f"{MODELO}, en la tarjeta gráfica" if str(_modelo.device).startswith("cuda") else f"{MODELO}, en el procesador"


def _probabilidades(audio: np.ndarray) -> tuple[float, float]:
    """(probabilidad de español, de inglés). Whisper detecta ~100 idiomas; acá solo importan estos dos."""
    if MOTOR == "rapido":
        _, _, todas = _modelo.detect_language(audio.astype(np.float32))
        probs = dict(todas)
    else:
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
    if MOTOR == "rapido":
        crudos, _ = _modelo.transcribe(
            audio.astype(np.float32), language=idioma, initial_prompt=PISTAS[idioma], beam_size=5,
            condition_on_previous_text=False,
        )
        # Mismo formato que el Whisper original
        segmentos = [{"text": s.text, "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob}
                     for s in crudos]
    else:
        segmentos = _modelo.transcribe(
            audio, language=idioma, initial_prompt=PISTAS[idioma], beam_size=5, condition_on_previous_text=False
        )["segments"]
    segmentos = [s for s in segmentos if s["no_speech_prob"] <= UMBRAL_SIN_VOZ]
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
