"""
Escucha continua con palabra de activación: Aries solo reacciona cuando escucha su nombre.

  "Aries, avanza dos metros"  -> lo hace directo
  "Hola Aries"                -> saluda y queda atento VENTANA_SEG segundos sin necesitar el nombre
  charla sin "Aries"          -> se ignora

Mientras Aries habla no escucha: el parlante va arriba del robot y, si no, se oiría a sí
mismo decir "Soy Aries" y se activaría en bucle.

Uso:
    python escucha.py                    # micrófono de la PC (el headset)
    python escucha.py --archivo x.wav    # prueba con una grabación
    python escucha.py --mudo             # sin voz, solo muestra en pantalla
"""
import argparse
import collections
import re
import subprocess
import time

import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad

import oido
import voz
from brain import NOMBRE_ROBOT, preguntar
from simulate import ejecutar_accion_simulada

TASA = 16000
BLOQUE = 512  # Silero VAD pide bloques de 512 muestras a 16 kHz (32 ms)
VENTANA_SEG = 8  # tiempo que queda atento después de responder
PREVIO_BLOQUES = 16  # ~0.5 s de audio antes de que el VAD detecte la voz, para no cortar la primera sílaba
MAX_FRASE_SEG = 15
MIN_FRASE_SEG = 0.3
COLA_ECO_SEG = 0.6  # espera tras hablar: el Bluetooth tiene retardo y el eco tarda en apagarse

# Formas en que Whisper puede escribir el nombre
_ALIAS_NOMBRE = re.compile(rf"\b({re.escape(NOMBRE_ROBOT)}|arias|harris|aris)\b", re.IGNORECASE)


class Oyente:
    """Recibe audio en bloques y entrega frases completas (del inicio al fin de cada habla)."""

    def __init__(self):
        self.vad = VADIterator(
            load_silero_vad(), threshold=0.5, sampling_rate=TASA, min_silence_duration_ms=700, speech_pad_ms=200
        )
        self.previo = collections.deque(maxlen=PREVIO_BLOQUES)
        self.frase: list[np.ndarray] | None = None
        self.t = 0.0  # segundos de audio procesados

    def reiniciar(self) -> None:
        self.vad.reset_states()
        self.previo.clear()
        self.frase = None

    def procesar(self, bloque: np.ndarray) -> np.ndarray | None:
        """Devuelve el audio de una frase cuando termina; si no, None."""
        self.t += len(bloque) / TASA
        evento = self.vad(torch.from_numpy(bloque))

        if self.frase is None:
            self.previo.append(bloque)
            if evento and "start" in evento:
                self.frase = list(self.previo)
            return None

        self.frase.append(bloque)
        largo = len(self.frase) * BLOQUE / TASA
        if (evento and "end" in evento) or largo > MAX_FRASE_SEG:
            audio = np.concatenate(self.frase)
            self.reiniciar()
            return audio if largo >= MIN_FRASE_SEG else None
        return None


class Aries:
    def __init__(self, reloj, mudo: bool = False):
        self.reloj = reloj
        self.mudo = mudo
        self.atento_hasta = -1.0

    def manejar_frase(self, audio: np.ndarray) -> bool:
        """Procesa una frase. Devuelve True si Aries respondió."""
        t0 = time.time()
        texto, idioma = oido.transcribir(audio)
        if not texto:
            return False

        texto = _ALIAS_NOMBRE.sub(NOMBRE_ROBOT, texto)
        con_nombre = bool(_ALIAS_NOMBRE.search(texto))
        atento = self.reloj() < self.atento_hasta

        if not (con_nombre or atento):
            print(f'   (ignorado, no dijo "{NOMBRE_ROBOT}"): {texto}', flush=True)
            return False

        accion = preguntar(texto, idioma)
        # Durante la ventana sin nombre, algo que no es un comando suele ser charla de otros: mejor callar
        if accion["accion"] == "desconocido" and not con_nombre:
            print(f"   (ignorado, no es un comando): {texto}", flush=True)
            return False

        print(f'🎙️  Oí ({idioma}): "{texto}"  [{time.time() - t0:.2f}s]', flush=True)
        ejecutar_accion_simulada(accion)
        if not self.mudo:
            voz.hablar(accion["respuesta_hablada"], accion["idioma"])
        self.atento_hasta = self.reloj() + VENTANA_SEG
        return True


class FuenteMicrofonoPC:
    """Micrófono por defecto de la PC vía ALSA/PipeWire."""

    def __init__(self):
        self.proc = None
        self._abrir()

    def _abrir(self) -> None:
        self.proc = subprocess.Popen(
            ["arecord", "-q", "-f", "S16_LE", "-r", str(TASA), "-c", "1", "-t", "raw"], stdout=subprocess.PIPE
        )

    def descartar_pendiente(self) -> None:
        """Tira el audio acumulado mientras Aries pensaba y hablaba (incluye su propio eco)."""
        self.proc.kill()
        self.proc.wait()
        self._abrir()

    def __iter__(self):
        while True:
            datos = self.proc.stdout.read(BLOQUE * 2)
            if len(datos) < BLOQUE * 2:
                return
            yield np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768.0


class FuenteArchivo:
    def __init__(self, ruta: str):
        self.audio = oido.whisper.load_audio(ruta)

    def descartar_pendiente(self) -> None:
        pass

    def __iter__(self):
        for i in range(0, len(self.audio) - BLOQUE + 1, BLOQUE):
            yield self.audio[i : i + BLOQUE]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archivo", help="usar una grabación en lugar del micrófono")
    parser.add_argument("--mudo", action="store_true", help="no hablar, solo mostrar")
    args = parser.parse_args()

    print("Cargando modelos...", flush=True)
    oido.cargar()
    if not args.mudo:
        voz.precargar()

    oyente = Oyente()
    fuente = FuenteArchivo(args.archivo) if args.archivo else FuenteMicrofonoPC()
    # Con archivo, el tiempo es el de la grabación; en vivo, el reloj real
    reloj = (lambda: oyente.t) if args.archivo else time.monotonic
    aries = Aries(reloj, mudo=args.mudo)

    print(f'👂 Escuchando. Di "Hola {NOMBRE_ROBOT}" o "{NOMBRE_ROBOT}, avanza dos metros". Ctrl+C para salir.', flush=True)
    try:
        for bloque in fuente:
            frase = oyente.procesar(bloque)
            if frase is None:
                continue
            if aries.manejar_frase(frase):
                if not args.mudo:
                    time.sleep(COLA_ECO_SEG)
                fuente.descartar_pendiente()
                oyente.reiniciar()
    except KeyboardInterrupt:
        pass
    print("\nChao.")


if __name__ == "__main__":
    main()
