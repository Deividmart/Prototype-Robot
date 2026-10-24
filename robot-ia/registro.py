"""
Registro de los movimientos del robot: guarda las mediciones en datos/, un CSV por registro.

El ESP32 manda por el WebSocket, unas 50 veces por segundo, una medición así:
  {"tipo": "medicion", "t_ms": 12345, "acel": 0.12, "acel_lat": 0.0, "giro": -1.5,
   "voltaje": 5.92, "corriente": 0.41, "pwm_izq": 200, "pwm_der": 200}

  t_ms        milisegundos desde que se encendió el ESP32
  acel        aceleración hacia adelante (MPU6050), m/s²
  acel_lat    aceleración hacia la derecha (MPU6050), m/s²: la centrípeta cuando gira
  giro        velocidad angular (MPU6050), °/s, positivo = a la derecha (igual que la acción "girar")
  voltaje     voltaje de las pilas de los motores (INA219), V
  corriente   corriente que sale de las pilas hacia los motores (INA219), A
  pwm_*       lo que el ESP32 le pide a cada motor, de -255 (atrás) a 255 (adelante)

Cómo se registra:
  - Empieza con el primer avanzar/retroceder/girar, o cuando se mueve sin motores (lo empujaron).
  - Sigue registrando todo, con todos los movimientos que vengan, hasta que digan "Aries, para":
    entonces espera a que el robot quede quieto y cierra el archivo.
  - "Aries, reinicia" descarta el registro en curso y deja las gráficas en blanco.
  - Cada comando queda anotado en la columna "evento", en el momento en que se mandó.
"""
import collections
import csv
import threading
import time
from pathlib import Path

import numpy as np

import fisica
from fisica import COLUMNAS

CARPETA = Path(__file__).parent / "datos"
# graficas.py mira este archivo: si es más nuevo que el último registro, deja las gráficas en blanco
MARCA_REINICIO = "reinicio.txt"
QUIETO_TRAS_PARAR_S = 1.0  # después de "para", cuánto tiempo quieto antes de cerrar el archivo
MUESTRAS_PREVIAS = 25  # ~0.5 s antes de arrancar, para que la gráfica muestre el reposo inicial
ACCIONES_CON_MOVIMIENTO = {"avanzar", "retroceder", "girar"}
ENCABEZADO = COLUMNAS + ["evento"]
# Sin motores, se considera que lo movieron con la mano si acelera o gira más que esto
EMPUJON_ACEL = 1.0  # m/s²
EMPUJON_GIRO = 20.0  # °/s

_I_PWM = (COLUMNAS.index("pwm_izq"), COLUMNAS.index("pwm_der"))
_I_ACEL = COLUMNAS.index("acel")
_I_GIRO = COLUMNAS.index("giro")


class Registro:
    def __init__(self, carpeta: Path = CARPETA):
        self.carpeta = carpeta
        self.ultimo: tuple[Path, dict] | None = None  # (archivo, resumen) del último registro terminado
        self._lock = threading.Lock()
        self._previas: collections.deque[list] = collections.deque(maxlen=MUESTRAS_PREVIAS)
        self._anterior: list[float] | None = None
        self._archivo = None
        self._escritor = None
        self._ruta: Path | None = None
        self._evento: str | None = None  # se escribe en la próxima medición
        self._empezar = False  # hay que abrir un registro con la próxima medición
        self._parando = False  # dijeron "para": se cierra cuando quede quieto
        self._reiniciado = False  # dijeron "reinicia": si sigue moviéndose, el registro nuevo arranca ya
        self._quieto_desde: float | None = None

    def nueva_accion(self, accion: dict) -> None:
        """Lo llama el servidor cada vez que le manda una acción al robot."""
        tipo = accion.get("accion")
        with self._lock:
            if tipo == "reiniciar":
                self._descartar()
            elif tipo == "detener":
                if self._archivo is not None or self._empezar:
                    self._evento = "detener"
                    self._parando = True
            elif tipo in ACCIONES_CON_MOVIMIENTO:
                self._evento = f"{tipo} {accion.get('parametro', 0):g}"
                self._parando = False
                if self._archivo is None:
                    self._empezar = True

    def agregar(self, medicion: dict) -> None:
        """Lo llama el servidor con cada medición que manda el ESP32."""
        try:
            fila = [medicion[c] for c in COLUMNAS]
            numeros = [float(x) for x in fila]
        except (KeyError, TypeError, ValueError):
            return

        with self._lock:
            # Si el reloj del ESP32 volvió atrás, se reinició: sus contadores también arrancan de 0
            if self._anterior is not None and numeros[0] < self._anterior[0]:
                self._reiniciar()
            se_mueve = self._se_mueve(numeros)
            self._anterior = numeros

            if self._archivo is None:
                if not self._empezar and not se_mueve:
                    self._previas.append(fila + [""])
                    self._reiniciado = False  # quedó quieto: lo próximo que lo mueva ya no es el reinicio
                    return
                if not self._empezar:
                    self._evento = "reinicio" if self._reiniciado else "empujón"
                self._abrir()

            self._escritor.writerow(fila + [self._evento or ""])
            self._evento = None
            self._archivo.flush()  # para que graficas.py lo vea en vivo

            if not self._parando:
                return
            t = numeros[0] / 1000
            if se_mueve:
                self._quieto_desde = None
            elif self._quieto_desde is None:
                self._quieto_desde = t
            elif t - self._quieto_desde >= QUIETO_TRAS_PARAR_S:
                self._cerrar()

    def cerrar(self) -> None:
        """Termina el registro en curso y olvida las mediciones previas (se desconectó el robot)."""
        with self._lock:
            self._reiniciar()

    def _reiniciar(self) -> None:
        self._cerrar()
        self._previas.clear()
        self._anterior = None

    def _se_mueve(self, numeros: list[float]) -> bool:
        if any(numeros[i] != 0 for i in _I_PWM):
            return True
        return abs(numeros[_I_ACEL]) > EMPUJON_ACEL or abs(numeros[_I_GIRO]) > EMPUJON_GIRO

    def _abrir(self) -> None:
        self.carpeta.mkdir(exist_ok=True)
        nombre = time.strftime("%Y-%m-%d_%H%M%S")
        self._ruta = self.carpeta / f"{nombre}.csv"
        n = 2
        while self._ruta.exists():  # dos registros en el mismo segundo: no se pisa el anterior
            self._ruta = self.carpeta / f"{nombre}_{n}.csv"
            n += 1
        self._archivo = open(self._ruta, "w", newline="", encoding="utf-8")
        self._escritor = csv.writer(self._archivo)
        self._escritor.writerow(ENCABEZADO)
        self._escritor.writerows(self._previas)
        self._previas.clear()
        self._empezar = self._reiniciado = False
        self._quieto_desde = None
        print(f'📈 Registrando: {self._ruta.name} (sigue hasta que digan "Aries, para")', flush=True)

    def _descartar(self) -> None:
        """'Aries, reinicia': borra el registro en curso y deja las gráficas en blanco."""
        if self._archivo is not None:
            self._archivo.close()
            self._archivo = None
            self._ruta.unlink(missing_ok=True)
        self._evento = None
        self._empezar = self._parando = False
        self._reiniciado = True
        self.carpeta.mkdir(exist_ok=True)
        (self.carpeta / MARCA_REINICIO).write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        print("🧹 Gráficas reiniciadas: el próximo movimiento empieza un registro nuevo", flush=True)

    def _cerrar(self) -> None:
        self._evento = None
        self._empezar = self._parando = False
        if self._archivo is None:
            return
        self._archivo.close()
        self._archivo = None
        ruta = self._ruta
        medido = leer_csv(ruta)
        if medido is None or len(medido["t_ms"]) < 3:
            return
        r = fisica.resumen(fisica.calcular(medido))
        self.ultimo = (ruta, r)
        print(
            f"💾 Registro guardado: {ruta.name} | desplazamiento {r['distancia']:.2f} m, recorrido "
            f"{r['recorrido']:.2f} m, {round(r['angulo'])}°, {r['tiempo']:.1f} s en movimiento, "
            f"energía {r['energia']:.1f} J",
            flush=True,
        )


class LectorCSV:
    """Lee un registro de a poco: cada vez que se llama a leer() solo procesa las líneas nuevas.
    Así las gráficas en vivo no releen todo el archivo 4 veces por segundo."""

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._posicion = 0
        self._encabezado: list[str] | None = None
        self._indices: list[int] = []  # dónde está cada una de COLUMNAS en el archivo
        self._i_evento: int | None = None
        self._filas: list[list[float]] = []
        self._eventos: list[tuple[float, str]] = []

    def leer(self) -> dict | None:
        """Devuelve {columna: array, ..., "eventos": [(t_ms, texto)]} o None si todavía no hay datos."""
        with open(self.ruta, "rb") as f:
            f.seek(self._posicion)
            nuevo = f.read()
        corte = nuevo.rfind(b"\n")  # la última línea puede estar a medio escribir: se deja para después
        if corte >= 0:
            self._posicion += corte + 1
            for fila in csv.reader(nuevo[: corte + 1].decode("utf-8").splitlines()):
                self._procesar(fila)
        if not self._filas:
            return None
        m = np.array(self._filas)
        datos = {c: m[:, i] for i, c in enumerate(COLUMNAS)}
        datos["eventos"] = list(self._eventos)
        return datos

    def _procesar(self, fila: list[str]) -> None:
        # Las columnas se buscan por nombre: así se leen también los registros viejos (con encoders)
        if self._encabezado is None:
            self._encabezado = fila
            if all(c in fila for c in COLUMNAS):
                self._indices = [fila.index(c) for c in COLUMNAS]
                self._i_evento = fila.index("evento") if "evento" in fila else None
            return
        if not self._indices or len(fila) != len(self._encabezado):
            return
        try:
            numeros = [float(fila[i]) for i in self._indices]
        except ValueError:
            return
        self._filas.append(numeros)
        if self._i_evento is not None and fila[self._i_evento]:
            self._eventos.append((numeros[0], fila[self._i_evento]))


def leer_csv(ruta: Path) -> dict | None:
    """Lee un registro guardado completo (ver LectorCSV.leer)."""
    return LectorCSV(ruta).leer()


def movimientos(carpeta: Path = CARPETA) -> list[Path]:
    """Los registros guardados, del más viejo al más nuevo."""
    if not carpeta.exists():
        return []
    return sorted(carpeta.glob("*.csv"), key=lambda p: p.stat().st_mtime)


def ultimo_reinicio(carpeta: Path = CARPETA) -> float:
    """Cuándo dijeron "Aries, reinicia" por última vez (0 si nunca)."""
    try:
        return (carpeta / MARCA_REINICIO).stat().st_mtime
    except OSError:
        return 0.0
