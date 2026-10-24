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
import queue
import re
import subprocess
import sys
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
# Como Siri: "Aries" lo despierta y después se le habla normal. Cada respuesta le da otros VENTANA_SEG
# segundos atento sin necesitar el nombre; "gracias" o "eso es todo" lo vuelve a dormir.
VENTANA_SEG = 15
PREVIO_BLOQUES = 16  # ~0.5 s de audio antes de que el VAD detecte la voz, para no cortar la primera sílaba
MAX_FRASE_SEG = 15
MIN_FRASE_SEG = 0.3
COLA_ECO_SEG = 0.6  # espera tras hablar: el Bluetooth tiene retardo y el eco tarda en apagarse

# Formas en que Whisper puede escribir el nombre
_ALIAS_NOMBRE = re.compile(rf"\b({re.escape(NOMBRE_ROBOT)}|arias|harris|aris)\b", re.IGNORECASE)
# Solo el nombre ("Aries", "oye Aries", "hey Aries?"): se despierta y espera el pedido
_SOLO_NOMBRE = re.compile(rf"^\W*((oye|ey|hey|ok|okay|eh)\W+)?{re.escape(NOMBRE_ROBOT)}\W*$", re.IGNORECASE)
# Para terminar la conversación
_DESPEDIDA = re.compile(
    r"^\W*(muchas\s+)?gracias|^\W*(eso\s+es\s+todo|nada\s+m[aá]s|adi[oó]s|chao|hasta\s+luego)|"
    r"^\W*(thanks|thank\s+you|that'?s\s+all|bye|goodbye)",
    re.IGNORECASE,
)
# Mientras habla solo se escucha esto: corta la frase y frena el robot
_CALLAR = re.compile(
    rf"^\W*((oye|ey|hey)\W+)?({re.escape(NOMBRE_ROBOT)}\W+)?(p[aá]ra(le)?|pare|det[eé]nte|c[aá]llate|silencio|basta|"
    r"ya|stop|shut\s+up|quiet|enough)\W*$",
    re.IGNORECASE,
)
MAX_CALLAR_SEG = 2.5  # "para" es corto: frases más largas son su propia voz o charla de fondo

_SE_MUEVE = {"avanzar", "retroceder", "girar"}
_VERBO_MOVIMIENTO = re.compile(
    r"\b(avanz|retroc|gir|camin|mueve|mu[eé]vete|ve\b|anda|adelante|atr[aá]s|derecha|izquierda|vuelta|"
    r"forward|back|turn|move|go\b|left|right|spin)",
    re.IGNORECASE,
)


def _repetida(texto: str) -> bool:
    """Whisper, con ruido o silencio largo, a veces repite una frase 3 o más veces: eso no lo dijo nadie."""
    frases = [re.sub(r"\W+", " ", f).strip().lower() for f in re.split(r"[.?!¿¡]", texto)]
    frases = [f for f in frases if f]
    return any(frases.count(f) >= 3 for f in set(frases))


def _normalizar(texto: str) -> str:
    return re.sub(r"\W+", " ", texto).strip().lower()


def _copia_de_pista(texto: str) -> bool:
    """Whisper con ruido a veces escribe un pedazo de sus pistas (oido.PISTAS): nadie lo dijo."""
    t = _normalizar(texto)
    return len(t.split()) >= 5 and any(t in _normalizar(p) for p in oido.PISTAS.values())


def _sin_movimiento(accion: str, frase: str, idioma: str) -> dict:
    """Respuesta que no pasa por el cerebro (despertarse, despedirse): el robot no se mueve."""
    return {"accion": accion, "parametro": 0.0, "idioma": idioma, "respuesta_hablada": frase}


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
        self.atento_hasta = float("-inf")
        self.dormir = False  # la próxima respuesta cierra la conversación ("gracias")
        # Idioma de la conversación: lo marca la última frase con el nombre. Sin el nombre solo se acepta
        # ese idioma (la charla de fondo en inglés no se cuela en una conversación en español)
        self.idioma_charla = "es"

    def decidir(self, audio: np.ndarray) -> dict | None:
        """Transcribe una frase hablada y decide la acción. None si hay que ignorarla."""
        t0 = time.time()
        texto, idioma = oido.transcribir(audio)
        if not texto:
            return None

        if re.search(r"[^\x00-ɏ -⁯¿¡]", texto):  # letras chinas, coreanas...: es ruido
            print(f"   (ignorado, salió con letras de otro alfabeto: era ruido): {texto}", flush=True)
            return None
        if _copia_de_pista(texto):
            print(f"   (ignorado, Whisper copió sus pistas: lo inventó con ruido): {texto}", flush=True)
            return None
        if _repetida(texto):
            print(f"   (ignorado, Whisper repitió frases: suele inventarlas con ruido): {texto}", flush=True)
            return None
        texto = _ALIAS_NOMBRE.sub(NOMBRE_ROBOT, texto)
        con_nombre = bool(_ALIAS_NOMBRE.search(texto))
        # Cuenta desde que empezó a hablar: una frase larga que arrancó dentro de la ventana vale
        empezo = self.reloj() - (time.time() - t0) - len(audio) / TASA
        atento = empezo < self.atento_hasta

        if not (con_nombre or atento):
            print(f'   (ignorado, no dijo "{NOMBRE_ROBOT}"): {texto}', flush=True)
            return None
        if not con_nombre and idioma != self.idioma_charla:
            print(f"   (ignorado, otro idioma que la conversación): {texto}", flush=True)
            return None

        print(f'🎙️  Oí ({idioma}): "{texto}"  [{time.time() - t0:.2f}s]', flush=True)
        if _SOLO_NOMBRE.match(texto):
            # "Aries" solo suena igual en los dos idiomas: contesta en el de la conversación
            return _sin_movimiento("escuchando", "Yes?" if self.idioma_charla == "en" else "¿Sí? Dime.",
                                   self.idioma_charla)
        if con_nombre:
            self.idioma_charla = idioma
        if _DESPEDIDA.match(_ALIAS_NOMBRE.sub("", texto)):
            self.dormir = True
            return _sin_movimiento("despedida", "You're welcome! Call me if you need me." if idioma == "en"
                                   else "¡Con gusto! Si me necesitas, di Aries.", idioma)

        accion = preguntar(texto, idioma)
        # En la conversación (sin decir el nombre) se acepta todo; solo se calla si no supo qué responder,
        # que suele ser charla de otras personas cerca
        if accion["accion"] == "desconocido" and not con_nombre:
            print(f"   (ignorado, no supe qué responder): {texto}", flush=True)
            return None
        # Sin el nombre, moverse pide un verbo de movimiento: charla cercana como "try something like
        # that" la tomaba como "otra vez" y el robot arrancaba solo
        # ...y no puede ser una pregunta: "¿pero avanza?" es la gente comentando, no una orden
        if accion["accion"] in _SE_MUEVE and not con_nombre and (
            not _VERBO_MOVIMIENTO.search(texto) or "?" in texto or "¿" in texto
        ):
            print(f"   (ignorado, no pidió moverse): {texto}", flush=True)
            return None
        return accion

    def pide_callar(self, audio: np.ndarray) -> bool:
        """Mientras habla: ¿le dijeron "para" (o "Aries, para", "cállate", "stop")?"""
        if len(audio) > MAX_CALLAR_SEG * TASA:
            return False
        texto, _ = oido.transcribir(audio)
        texto = _ALIAS_NOMBRE.sub(NOMBRE_ROBOT, texto or "")
        if _CALLAR.match(texto):
            print(f'✋ Oí "{texto}" mientras hablaba: me callo y freno', flush=True)
            return True
        return False

    def decidir_texto(self, texto: str) -> dict:
        """Comando escrito (monitor serial del ESP32): no hace falta decir el nombre."""
        accion = preguntar(_ALIAS_NOMBRE.sub(NOMBRE_ROBOT, texto))
        print(f'⌨️  Escribieron: "{texto}"', flush=True)
        return accion

    def responder(self, accion: dict, enviar_al_robot=None) -> None:
        """Manda la acción al robot (si hay uno conectado) y la dice en voz alta."""
        if enviar_al_robot is None:
            ejecutar_accion_simulada(accion)
        else:
            enviar_al_robot(accion)
            print(f'📡 Al robot: {accion["accion"]} {accion["parametro"]:g}', flush=True)
            print(f'🔊 Aries dice: "{accion["respuesta_hablada"]}"', flush=True)
        # Primero se manda la acción: así el robot se mueve mientras habla
        if not self.mudo:
            voz.hablar(accion["respuesta_hablada"], accion["idioma"])
        if self.dormir:
            self.dormir = False
            self.atento_hasta = float("-inf")
            print(f'💤 Fin de la conversación: para seguir, di "{NOMBRE_ROBOT}"', flush=True)
        else:
            self.atento_hasta = self.reloj() + VENTANA_SEG
            print(f"👂 Te escucho {VENTANA_SEG} s sin que digas el nombre", flush=True)


class _MicrofonoLinux:
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


class _MicrofonoWindows:
    """Micrófono predeterminado de Windows (Configuración > Sonido > Entrada)."""

    def __init__(self):
        import sounddevice as sd

        self.cola: queue.Queue[np.ndarray] = queue.Queue()
        self.stream = sd.InputStream(
            samplerate=TASA, channels=1, dtype="float32", blocksize=BLOQUE,
            callback=lambda datos, *_: self.cola.put(datos[:, 0].copy()),
        )
        self.stream.start()

    def descartar_pendiente(self) -> None:
        """Tira el audio acumulado mientras Aries pensaba y hablaba (incluye su propio eco)."""
        while not self.cola.empty():
            self.cola.get_nowait()

    def __iter__(self):
        while True:
            yield self.cola.get()


FuenteMicrofonoPC = _MicrofonoWindows if sys.platform == "win32" else _MicrofonoLinux


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
            accion = aries.decidir(frase)
            if accion is not None:
                aries.responder(accion)
                if not args.mudo:
                    time.sleep(COLA_ECO_SEG)
                fuente.descartar_pendiente()
                oyente.reiniciar()
    except KeyboardInterrupt:
        pass
    print("\nChao.")


if __name__ == "__main__":
    main()
