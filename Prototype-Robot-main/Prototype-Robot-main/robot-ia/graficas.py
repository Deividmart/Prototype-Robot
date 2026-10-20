"""
Gráficas de los movimientos de Aries (los registros que guarda registro.py en datos/).

Uso:
    python graficas.py               en vivo: muestra el registro que se está grabando
    python graficas.py --ultimo      abre el último registro guardado
    python graficas.py datos/x.csv   abre un registro guardado
    python graficas.py --lista       lista los registros guardados con sus números principales

En la ventana:
  - El menú de la izquierda elige qué gráfica ver en grande, o todas juntas.
  - ◀ Anterior / Siguiente ▶ recorren los registros guardados; ● En vivo vuelve al que se está grabando.
  - Las líneas punteadas marcan cada comando ("avanza 2 m", "gira 90°", "para").
Al abrir un registro guardado también se guarda la imagen al lado (x.png), lista para el informe.
"""
import argparse
import math
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backend_bases import NavigationToolbar2
from matplotlib.gridspec import GridSpec
from matplotlib.widgets import Button, RadioButtons

import fisica
from registro import LectorCSV, leer_csv, movimientos, ultimo_reinicio

# Las flechas de matplotlib solo deshacen el zoom (no cambian de registro) y confunden: se quitan,
# igual que el botón de ajustar márgenes. Quedan la casa, mover, lupa y guardar imagen.
NavigationToolbar2.toolitems = tuple(
    item for item in NavigationToolbar2.toolitems if item[0] not in ("Back", "Forward", "Subplots")
)

# Paleta validada para daltonismo: cada magnitud tiene su color y lo conserva en todas las vistas
AZUL = "#2a78d6"
NARANJA = "#eb6834"
AGUA = "#1baf7a"
AMARILLO = "#eda100"
MAGENTA = "#e87ba4"
VERDE = "#008300"
VIOLETA = "#6250d6"
ROJO = "#e34948"
GRANATE = "#d55181"
AZUL_OSCURO = "#104281"
COLOR_MODELO = NARANJA  # en los paneles que comparan el sensor con el modelo del motor
COLOR_MPU = VIOLETA

FONDO = "#fcfcfb"
FONDO_MENU = "#f3f2ee"
TINTA = "#0b0b0b"
TINTA_SUAVE = "#52514e"
APAGADO = "#898781"
GRILLA = "#e1e0d9"
EJE = "#c3c2b7"

# clave: (título, símbolo, unidad, rango mínimo del eje, [(columna, nombre de la serie, color)], valor a marcar)
# El rango mínimo evita que el ruido de un sensor quieto se vea como un movimiento enorme.
MAGNITUDES = {
    "posicion": ("Posición", "x", "m", 0.2, [("x", "", AZUL)], "final"),
    "velocidad": ("Velocidad", "v", "m/s", 0.2,
                  [("v", "acelerómetro + motor", AGUA), ("v_modelo", "solo modelo del motor", COLOR_MODELO)], "max"),
    "aceleracion": ("Aceleración", "a", "m/s²", 1.0,
                    [("a_mpu", "acelerómetro", COLOR_MPU), ("a_mod", "modelo del motor", COLOR_MODELO)], "max"),
    "vel_angular": ("Velocidad angular", "ω", "°/s", 40, [("omega", "", MAGENTA)], "max"),
    "angulo": ("Ángulo girado", "θ", "°", 20,
               [("angulo", "", COLOR_MPU)], "final"),
    "centripeta": ("Aceleración centrípeta", "aᶜ", "m/s²", 1.0, [("a_lat", "", VERDE)], "max"),
    "voltaje": ("Voltaje de las pilas", "V", "V", 1.0, [("voltaje", "", AMARILLO)], "min"),
    "corriente": ("Corriente de los motores", "I", "A", 0.2, [("corriente", "", ROJO)], "max"),
    "potencia": ("Potencia eléctrica", "P", "W", 1.0, [("potencia", "", GRANATE)], "max"),
    "energia": ("Energía eléctrica gastada", "E", "J", 1.0, [("energia", "", AZUL_OSCURO)], "final"),
    "recorrido": ("Distancia recorrida", "d", "m", 0.2, [("recorrido", "", "#0f6e4f")], "final"),
}
# La vista "Todas": una fila por tema (movimiento, rotación, electricidad)
GRILLA_TODAS = ["posicion", "velocidad", "aceleracion",
                "vel_angular", "angulo", "centripeta",
                "voltaje", "corriente", "potencia"]
OPCIONES = ["todas"] + list(MAGNITUDES)

# Zona de las gráficas (a la derecha del menú, debajo del encabezado)
ZONA = {"left": 0.205, "right": 0.985, "top": 0.83, "bottom": 0.075}
PUNTOS_MAX = 4000  # en registros largos se dibuja 1 de cada n puntos: la ventana sigue rápida

plt.rcParams.update({
    "figure.facecolor": FONDO,
    "axes.facecolor": FONDO,
    "axes.edgecolor": EJE,
    "axes.labelcolor": TINTA_SUAVE,
    "axes.titlecolor": TINTA,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRILLA,
    "grid.linewidth": 0.8,
    "xtick.color": EJE,
    "ytick.color": EJE,
    "xtick.labelcolor": TINTA_SUAVE,
    "ytick.labelcolor": TINTA_SUAVE,
    "legend.frameon": False,
    "legend.labelcolor": TINTA_SUAVE,
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
})


def cuando(nombre_archivo: str) -> tuple[str, str]:
    """'2026-10-17_191631' -> ('19:16:31', '17/10/2026')"""
    try:
        fecha, hora = nombre_archivo.split("_")[:2]
        anio, mes, dia = fecha.split("-")
        return f"{hora[:2]}:{hora[2:4]}:{hora[4:6]}", f"{dia}/{mes}/{anio}"
    except ValueError:
        return nombre_archivo, ""


def texto_evento(evento: str) -> str:
    """'avanzar 2' -> 'avanza 2 m', 'girar -45' -> 'gira 45° izq.', 'detener' -> 'para'"""
    tipo, *resto = evento.split()
    valor = resto[0] if resto else ""
    if tipo == "avanzar":
        return f"avanza {valor} m"
    if tipo == "retroceder":
        return f"retrocede {valor} m"
    if tipo == "girar":
        grados = float(valor or 0)
        return f"gira {abs(grados):g}° {'der.' if grados >= 0 else 'izq.'}"
    if tipo == "detener":
        return "para"
    if tipo == "reinicio":
        return "reinicio (desde cero)"
    return evento


def _reducir(t: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    paso = max(1, math.ceil(len(t) / PUNTOS_MAX))
    return t[::paso], y[::paso]


def _dibujar_panel(ax, c: dict, eventos: list, clave: str, grande: bool, con_eje_x: bool, con_eventos: bool) -> None:
    titulo, simbolo, unidad, rango_min, series, marca = MAGNITUDES[clave]
    t = c["t"]
    for columna, etiqueta, color in series:
        tr, yr = _reducir(t, c[columna])
        ax.plot(tr, yr, color=color, linewidth=2.4 if grande else 1.8, label=etiqueta or None,
                solid_capstyle="round", solid_joinstyle="round", zorder=3)
        if len(series) == 1 and clave != "voltaje":
            ax.fill_between(tr, yr, 0, color=color, alpha=0.10, linewidth=0, zorder=2)

    ax.set_title(titulo, fontsize=15 if grande else 10.5)
    ax.set_ylabel(f"{simbolo} ({unidad})", fontsize=12 if grande else 9)
    if con_eje_x:
        ax.set_xlabel("tiempo (s)", fontsize=12 if grande else 9)
    ax.tick_params(labelsize=11 if grande else 8.5)

    abajo, arriba = ax.get_ylim()
    if arriba - abajo < rango_min:
        centro = (arriba + abajo) / 2
        abajo, arriba = centro - rango_min / 2, centro + rango_min / 2
    ax.set_ylim(abajo, arriba + (arriba - abajo) * 0.15)  # espacio arriba para etiquetas
    if abajo <= 0 <= arriba:
        ax.axhline(0, color=EJE, linewidth=1, zorder=1)
    ax.set_xlim(t[0], t[-1] + (t[-1] - t[0]) * (0.02 if grande else 0))

    # Una línea punteada por cada comando, en el momento en que se dio
    for t_evento, texto in eventos:
        ax.axvline(t_evento, color=APAGADO, linewidth=1, linestyle=(0, (4, 3)), zorder=1)
        if con_eventos:
            ax.annotate(texto, (t_evento, 1), xycoords=("data", "axes fraction"), xytext=(3, -3),
                        textcoords="offset points", rotation=90, va="top", ha="left",
                        fontsize=10 if grande else 7.5, color=TINTA_SUAVE)

    if len(series) > 1:
        ax.legend(loc="upper right", fontsize=11 if grande else 8, handlelength=1.4)

    if grande:
        # Marca el dato que más importa de esta magnitud: el pico, el mínimo o el valor final
        columna, _, color = series[0]
        y = c[columna]
        i = {"max": int(np.argmax(np.abs(y))), "min": int(np.argmin(y)), "final": len(y) - 1}[marca]
        texto = {"max": "pico", "min": "mínimo", "final": "final"}[marca]
        espacio = "" if unidad == "°" else " "
        ax.plot(t[i], y[i], "o", markersize=10, color=color, markeredgecolor=FONDO, markeredgewidth=2.5, zorder=5)
        ax.annotate(f"{texto}: {y[i]:.2f}{espacio}{unidad}", (t[i], y[i]), xytext=(0, 16), textcoords="offset points",
                    ha="right" if t[i] > (t[0] + t[-1]) / 2 else "left", fontsize=12, color=TINTA,
                    fontweight="bold", zorder=6,
                    bbox={"boxstyle": "round,pad=0.3", "facecolor": FONDO, "edgecolor": GRILLA})


class Visor:
    def __init__(self):
        self.fig = plt.figure(figsize=(15, 9))
        self.fig.canvas.manager.set_window_title("Aries - gráficas de los movimientos")
        self.ejes = []
        self.seleccion = "todas"
        self.medido = None
        self.nombre = ""
        self.estado = ""
        self.vivo = True  # sigue al registro que se está grabando; False = viendo uno guardado
        self.indice: int | None = None  # cuál registro guardado se está viendo
        self.refrescar = False  # pide al bucle en vivo que vuelva a dibujar

        # Encabezado
        self.txt_titulo = self.fig.text(0.012, 0.955, "", fontsize=19, fontweight="bold", color=TINTA)
        self.txt_comandos = self.fig.text(0.012, 0.918, "", fontsize=10.5, color=APAGADO)
        self.txt_resumen = self.fig.text(0.012, 0.878, "", fontsize=11.5, color=TINTA_SUAVE)
        self.txt_estado = self.fig.text(0.985, 0.955, "", fontsize=12, fontweight="bold", ha="right")

        # Menú para elegir la gráfica
        ax_menu = self.fig.add_axes((0.012, 0.27, 0.15, 0.54), facecolor=FONDO_MENU)
        ax_menu.set_title("Elige la gráfica", fontsize=12, loc="left", pad=10)
        for lado in ax_menu.spines.values():
            lado.set_visible(False)
        self.etiquetas = ["Todas juntas"] + [MAGNITUDES[k][0] for k in MAGNITUDES]
        colores = [TINTA] + [MAGNITUDES[k][4][0][2] for k in MAGNITUDES]
        self.menu = RadioButtons(
            ax_menu, self.etiquetas, active=0,
            label_props={"color": colores, "fontsize": [10.5] * len(self.etiquetas)},
            radio_props={"facecolor": colores, "edgecolor": colores, "s": [80] * len(self.etiquetas)},
        )
        self.menu.on_clicked(self._elegir)

        # Botones para recorrer los registros guardados
        self.btn_anterior = Button(self.fig.add_axes((0.012, 0.185, 0.073, 0.05)), "◀ Anterior",
                                   color=FONDO_MENU, hovercolor=GRILLA)
        self.btn_siguiente = Button(self.fig.add_axes((0.089, 0.185, 0.073, 0.05)), "Siguiente ▶",
                                    color=FONDO_MENU, hovercolor=GRILLA)
        self.btn_vivo = Button(self.fig.add_axes((0.012, 0.125, 0.15, 0.05)), "● En vivo",
                               color=FONDO_MENU, hovercolor=GRILLA)
        for boton in (self.btn_anterior, self.btn_siguiente, self.btn_vivo):
            boton.label.set_fontsize(10.5)
        self.btn_vivo.label.set_color(ROJO)
        self.btn_anterior.on_clicked(lambda _: self.navegar(-1))
        self.btn_siguiente.on_clicked(lambda _: self.navegar(1))
        self.btn_vivo.on_clicked(lambda _: self.volver_en_vivo())

        self.fig.text(0.012, 0.105, "Barra de abajo:\nLupa: acercar una zona\nCasa: volver a la vista normal\n"
                      "Disquete: guardar imagen", fontsize=8.5, color=APAGADO, va="top", linespacing=1.5)

    # --- Botones ---
    def _elegir(self, etiqueta: str) -> None:
        self.seleccion = OPCIONES[self.etiquetas.index(etiqueta)]
        self.redibujar()
        self.fig.canvas.draw_idle()

    def navegar(self, paso: int) -> None:
        lista = movimientos()
        if not lista:
            return
        if self.indice is None:
            # Desde "en vivo": si se está viendo el último registro, se mueve desde ese;
            # si la pantalla está en blanco (esperando o reiniciada), "◀" abre el último
            ultimo = len(lista) - 1
            self.indice = ultimo + paso if self.medido is not None else ultimo
        else:
            self.indice += paso
        self.indice = max(0, min(len(lista) - 1, self.indice))
        self.vivo = False
        self.abrir(lista[self.indice], f"Guardado · {self.indice + 1} de {len(lista)}")
        self.fig.canvas.draw_idle()

    def volver_en_vivo(self) -> None:
        self.vivo = True
        self.indice = None
        self.refrescar = True

    # --- Contenido ---
    def abrir(self, ruta: Path, estado: str) -> None:
        medido = leer_csv(ruta)
        if medido is not None and len(medido["t_ms"]) >= 3:
            self.mostrar(medido, ruta.stem, estado)

    def esperar(self, reiniciado: bool = False) -> None:
        for ax in self.ejes:
            ax.remove()
        self.ejes = []
        self.medido = None
        if reiniciado:
            self.txt_titulo.set_text("Gráficas reiniciadas")
            self.txt_comandos.set_text('Dijeron "Aries, reinicia". El próximo movimiento empieza un registro nuevo desde cero.')
        else:
            self.txt_titulo.set_text("Esperando el primer movimiento...")
            self.txt_comandos.set_text("")
        self.txt_resumen.set_text('Enciende el cerebro (iniciar.bat) y dile a Aries que se mueva, por ejemplo '
                                  '"avanza un metro". Se registra todo hasta que digas "Aries, para".')
        self.txt_estado.set_text("")

    def mostrar(self, medido: dict, nombre_archivo: str, estado: str = "") -> None:
        self.medido, self.nombre, self.estado = medido, nombre_archivo, estado
        self.redibujar()

    def redibujar(self) -> None:
        if self.medido is None:
            return
        for ax in self.ejes:
            ax.remove()
        self.ejes = []

        c = fisica.calcular(self.medido)
        r = fisica.resumen(c)
        t0 = self.medido["t_ms"][0]
        eventos = [((t - t0) / 1000, texto_evento(e)) for t, e in self.medido.get("eventos", [])]

        hora, fecha = cuando(self.nombre)
        self.txt_titulo.set_text(f"Registro de las {hora}")
        comandos = " → ".join(texto for _, texto in eventos[-8:]) or "—"
        if len(eventos) > 8:
            comandos = "… → " + comandos
        self.txt_comandos.set_text(f"{fecha}   ·   Comandos: {comandos}")
        self.txt_resumen.set_text(
            f"Desplazamiento {r['distancia']:.2f} m    Recorrido {r['recorrido']:.2f} m    "
            f"Ángulo {round(r['angulo'])}°    En movimiento {r['tiempo']:.1f} s    "
            f"Rapidez media {r['v_media']:.2f} m/s    Vel. máx {r['v_max']:.2f} m/s    "
            f"Acel. máx {r['a_max']:.2f} m/s²    Energía {r['energia']:.1f} J"
        )
        if self.estado == "registrando":
            self.txt_estado.set_text('● REGISTRANDO  (di "Aries, para" para terminar)')
            self.txt_estado.set_color(ROJO)
        elif self.estado == "terminado":
            self.txt_estado.set_text("✓ Terminado")
            self.txt_estado.set_color(VERDE)
        else:
            self.txt_estado.set_text(self.estado)
            self.txt_estado.set_color(APAGADO)

        if self.seleccion == "todas":
            gs = GridSpec(3, 3, figure=self.fig, hspace=0.55, wspace=0.3, **ZONA)
            for i, clave in enumerate(GRILLA_TODAS):
                ax = self.fig.add_subplot(gs[i // 3, i % 3])
                _dibujar_panel(ax, c, eventos, clave, grande=False, con_eje_x=i // 3 == 2, con_eventos=i == 0)
                self.ejes.append(ax)
        else:
            gs = GridSpec(1, 1, figure=self.fig, **ZONA)
            ax = self.fig.add_subplot(gs[0])
            _dibujar_panel(ax, c, eventos, self.seleccion, grande=True, con_eje_x=True, con_eventos=True)
            self.ejes.append(ax)


def ejecutar(visor: Visor) -> None:
    """Mantiene la ventana abierta; en vivo, la actualiza con lo que se va grabando."""
    lector: LectorCSV | None = None
    mostrado = None
    while plt.fignum_exists(visor.fig.number):
        if visor.refrescar:
            visor.refrescar = False
            mostrado = None
        if visor.vivo:
            lista = movimientos()
            ruta = lista[-1] if lista else None
            try:
                modificado = ruta.stat().st_mtime if ruta else 0.0
            except OSError:
                modificado = 0.0
            reinicio = ultimo_reinicio()
            if ruta is None or reinicio >= modificado:
                estado_pantalla = ("esperando", reinicio)
                if estado_pantalla != mostrado:
                    visor.esperar(reiniciado=reinicio > 0 and ruta is not None)
                    mostrado = estado_pantalla
            else:
                estado = "registrando" if time.time() - modificado < 2 else "terminado"
                if (ruta, modificado, estado) != mostrado:
                    if lector is None or lector.ruta != ruta:
                        lector = LectorCSV(ruta)
                    medido = lector.leer()
                    if medido is not None and len(medido["t_ms"]) >= 3:
                        visor.mostrar(medido, ruta.stem, estado)
                        mostrado = (ruta, modificado, estado)
        plt.pause(0.25)


def mostrar_archivo(ruta: Path) -> None:
    medido = leer_csv(ruta)
    if medido is None or len(medido["t_ms"]) < 3:
        sys.exit(f"{ruta} no tiene datos suficientes.")
    visor = Visor()
    lista = movimientos()
    visor.vivo = False
    visor.indice = next((i for i, p in enumerate(lista) if p.resolve() == ruta.resolve()), None)
    total = f" · {visor.indice + 1} de {len(lista)}" if visor.indice is not None else ""
    visor.mostrar(medido, ruta.stem, f"Guardado{total}")
    imagen = ruta.with_suffix(".png")
    visor.fig.savefig(imagen, dpi=150)
    print(f"Imagen guardada en {imagen}")
    ejecutar(visor)


def listar() -> None:
    lista = movimientos()
    if not lista:
        print("Todavía no hay registros guardados en datos/.")
        return
    print(f"{'registro':<20} {'despl.':>7} {'recorr.':>8} {'ángulo':>7} {'t mov.':>7} {'energía':>8}  comandos")
    for ruta in lista:
        medido = leer_csv(ruta)
        if medido is None or len(medido["t_ms"]) < 3:
            continue
        r = fisica.resumen(fisica.calcular(medido))
        comandos = ", ".join(texto_evento(e) for _, e in medido["eventos"])
        print(f"{ruta.stem:<20} {r['distancia']:>6.2f}m {r['recorrido']:>7.2f}m {round(r['angulo']):>6}° "
              f"{r['tiempo']:>6.1f}s {r['energia']:>7.1f}J  {comandos}")


def main():
    parser = argparse.ArgumentParser(description="Gráficas de los movimientos de Aries")
    parser.add_argument("archivo", nargs="?", help="CSV de un registro guardado")
    parser.add_argument("--lista", action="store_true", help="listar los registros guardados")
    parser.add_argument("--ultimo", action="store_true", help="abrir el último registro guardado")
    args = parser.parse_args()

    if args.lista:
        listar()
    elif args.archivo:
        mostrar_archivo(Path(args.archivo))
    elif args.ultimo:
        lista = movimientos()
        if not lista:
            sys.exit("Todavía no hay registros guardados en datos/.")
        mostrar_archivo(lista[-1])
    else:
        visor = Visor()
        visor.esperar()
        print("Gráficas en vivo. Cierra la ventana para salir.")
        ejecutar(visor)


if __name__ == "__main__":
    main()
