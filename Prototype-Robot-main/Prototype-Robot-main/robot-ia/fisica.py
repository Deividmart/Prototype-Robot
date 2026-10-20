"""
Física de Aries: convierte lo que miden los sensores del robot en magnitudes físicas
(posición, velocidad, aceleración, ángulo, velocidad angular, potencia, energía).

El robot no tiene encoders. La velocidad sale de juntar dos fuentes:
  - el acelerómetro (MPU6050): integrar a da v, al instante, pero con un error que crece con el tiempo;
  - el modelo del motor (INA219): con el voltaje de las pilas, la corriente y el PWM se despeja qué
    tan rápido gira cada rueda (V = I·R + K·ω). No acumula error, pero es más ruidoso.
Mientras los motores andan, la velocidad del acelerómetro se corrige de a poco hacia la del modelo;
cuando el robot queda quieto (acelerómetro y giroscopio en calma) se sabe que v = 0.

Las constantes del robot están acá arriba: mídanlas y cámbienlas para que los cálculos den bien.
Las del motor también están en el firmware (robot_wifi.ino): si cambian acá, cámbienlas allá.
"""
import numpy as np

# --- Constantes del robot (medirlas) ---
DIAMETRO_RUEDA = 0.061  # m, con el caucho
ANCHO_EJES = 0.13  # m, distancia entre el centro de las dos ruedas (medirla)
MASA = 0.40  # kg, el robot completo con pilas (pesarlo)

# --- Motor amarillo (TT 1:48), iguales en el firmware ---
R_MOTOR = 7.5  # ohm
K_MOTOR = 0.287  # V·s/rad (= N·m/A), contando la caja reductora
# Calibración: pidan "avanza un metro", midan con una cinta lo que anduvo de verdad y pongan
# acá (y en el firmware) distancia real / 1 m
# 19/10/2026, pilas a ~4,1 V: pidieron 0,3 m y anduvo 0,55; pidieron 1,67 y anduvo 1,30. Encaja con
# real = 1,22 × modelo + 0,18 m: el factor va acá; los 0,18 m son lo que sigue de largo al frenar
# (el firmware corta antes, ver DISTANCIA_FRENADO en robot_wifi.ino)
AJUSTE_DISTANCIA = 1.22
R_RUEDA = DIAMETRO_RUEDA / 2

VENTANA_SUAVIZADO_S = 0.2
TAU_FUSION_S = 0.3  # cuánto tarda la velocidad del acelerómetro en acercarse a la del modelo
# Con motores, la velocidad no se aleja del modelo más que esto: si levantan o inclinan el robot,
# el acelerómetro mide parte de la gravedad y la integral se dispararía
DIF_MAX_MODELO = 0.15  # m/s
# Sin motores y sin quedar en calma (frenando, empujado, levantado), se integra como mucho este
# tiempo; después la velocidad cae a cero
LIBRE_MAX_S = 1.5
# El robot no pasa de ~0,6 m/s ni empujado con la mano: más que esto es el acelerómetro sacudido
V_MAX = 1.0  # m/s
TAU_DETENCION_S = 0.3
QUIETO_ACEL = 0.35  # m/s²: por debajo de esto (y del giro) el robot está en calma
QUIETO_GIRO = 8.0  # °/s
QUIETO_S = 0.25  # tiempo en calma para dar la velocidad por cero

# Lo que manda el ESP32 en cada medición, en este orden (ver registro.py)
COLUMNAS = ["t_ms", "acel", "acel_lat", "giro", "voltaje", "corriente", "pwm_izq", "pwm_der"]


def _suavizar(y: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Promedio móvil centrado de VENTANA_SUAVIZADO_S segundos."""
    if len(y) < 3:
        return y.copy()
    n = int(round(VENTANA_SUAVIZADO_S / float(np.median(np.diff(t)))))
    if n < 2:
        return y.copy()
    n |= 1  # impar, para que quede centrado
    relleno = np.pad(y, n // 2, mode="edge")
    return np.convolve(relleno, np.ones(n) / n, mode="valid")


def _derivar(y: np.ndarray, t: np.ndarray) -> np.ndarray:
    return np.gradient(y, t) if len(y) >= 2 else np.zeros_like(y)


def _integrar(y: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Integral acumulada por trapecios (empieza en 0)."""
    return np.concatenate([[0.0], np.cumsum((y[1:] + y[:-1]) / 2 * np.diff(t))])


def velocidad_ruedas(pwm_izq, pwm_der, voltaje, corriente) -> tuple[np.ndarray, np.ndarray]:
    """
    Velocidad (m/s) de cada rueda según el modelo del motor; positiva hacia adelante.
    El firmware hace la misma cuenta para saber cuándo llegó a la distancia pedida.

    Con PWM, cada motor recibe en promedio d·V (d = pwm/255) y las pilas solo entregan corriente
    una fracción d del tiempo: I_pilas = |d_izq|·I + |d_der|·I, suponiendo la misma corriente I
    en los dos motores. Despejando de d·V = I·R + K·ω sale ω, y v = ω·r.
    """
    d_izq = np.asarray(pwm_izq, dtype=float) / 255
    d_der = np.asarray(pwm_der, dtype=float) / 255
    voltaje = np.asarray(voltaje, dtype=float)
    suma = np.abs(d_izq) + np.abs(d_der)
    i_motor = np.divide(np.asarray(corriente, dtype=float), suma, out=np.zeros_like(suma), where=suma > 0.01)

    def rueda(d: np.ndarray) -> np.ndarray:
        # Si la corriente se come todo el voltaje la rueda está trabada: no gira "para atrás"
        omega = np.maximum(np.abs(d) * voltaje - R_MOTOR * i_motor, 0.0) / K_MOTOR
        return np.sign(d) * omega * R_RUEDA * AJUSTE_DISTANCIA

    return rueda(d_izq), rueda(d_der)


def _en_calma(t: np.ndarray, a: np.ndarray, giro: np.ndarray, motor: np.ndarray) -> np.ndarray:
    """True donde el robot lleva QUIETO_S segundos sin motores, sin acelerar y sin girar."""
    calma = (np.abs(a) < QUIETO_ACEL) & (np.abs(giro) < QUIETO_GIRO) & ~motor
    quieto = np.zeros(len(t), dtype=bool)
    desde = None
    for k in range(len(t)):
        if calma[k]:
            desde = t[k] if desde is None else desde
            quieto[k] = t[k] - desde >= QUIETO_S
        else:
            desde = None
    return quieto


def _fusionar(t: np.ndarray, a: np.ndarray, v_modelo: np.ndarray, motor: np.ndarray, quieto: np.ndarray) -> np.ndarray:
    """Integra la aceleración y la corrige con el modelo del motor (motores andando) o con v = 0 (quieto)."""
    v = np.zeros(len(t))
    libre_desde = None  # desde cuándo se mueve sin motores
    for k in range(1, len(t)):
        dt = t[k] - t[k - 1]
        vk = v[k - 1] + (a[k] + a[k - 1]) / 2 * dt
        if motor[k]:
            libre_desde = None
            vk += (v_modelo[k] - vk) * min(1.0, dt / TAU_FUSION_S)
            vk = min(max(vk, v_modelo[k] - DIF_MAX_MODELO), v_modelo[k] + DIF_MAX_MODELO)
        elif quieto[k]:
            libre_desde = None
            vk = 0.0
        else:
            libre_desde = t[k] if libre_desde is None else libre_desde
            if t[k] - libre_desde > LIBRE_MAX_S:
                # Ya no se integra: lo que mide ahora es sobre todo la gravedad (lo inclinaron o lo sostienen)
                vk = v[k - 1] * np.exp(-dt / TAU_DETENCION_S)
        v[k] = min(max(vk, -V_MAX), V_MAX)
    return v


def calcular(m: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Recibe las columnas medidas y devuelve las magnitudes físicas, todas en función del tiempo."""
    t = (m["t_ms"] - m["t_ms"][0]) / 1000
    giro = m["giro"]
    motor = (m["pwm_izq"] != 0) | (m["pwm_der"] != 0)

    # El firmware le resta al acelerómetro lo que marcaba quieto al encender, pero si después lo
    # apoyan un poco inclinado aparece un resto: se descuenta lo que marca sin motores (la mediana
    # ignora los ratos en que lo empujan o frena)
    quieto_motor = np.count_nonzero(~motor) >= 5
    sesgo = float(np.median(m["acel"][~motor])) if quieto_motor else 0.0
    sesgo_lat = float(np.median(m["acel_lat"][~motor])) if quieto_motor else 0.0
    a = m["acel"] - sesgo
    a_suave = _suavizar(a, t)

    v_izq, v_der = velocidad_ruedas(m["pwm_izq"], m["pwm_der"], m["voltaje"], m["corriente"])
    v_modelo = _suavizar((v_izq + v_der) / 2, t)
    quieto = _en_calma(t, a_suave, giro, motor)
    v = _fusionar(t, a, v_modelo, motor, quieto)

    x = _integrar(v, t)
    # Recorrido: todo lo que anduvo, sin importar el sentido (avanzar 2 m y volver 2 m = 4 m, aunque x = 0)
    recorrido = _integrar(np.abs(v), t)
    potencia = m["voltaje"] * m["corriente"]

    return {
        "t": t,
        "moviendo": motor | ~quieto,
        "x": x,
        "recorrido": recorrido,
        "v": v,
        "v_modelo": v_modelo,
        "a_mpu": a_suave,
        "a_mod": _derivar(_suavizar(v_modelo, t), t),
        "a_lat": _suavizar(m["acel_lat"] - sesgo_lat, t),
        "omega": giro,
        # El ángulo sale solo del giroscopio: el modelo del motor no sirve para esto porque supone la
        # misma corriente en las dos ruedas, y para ir derecho el robot les da PWM distinto
        "angulo": _integrar(giro, t),
        "voltaje": m["voltaje"],
        "corriente": m["corriente"],
        "potencia": potencia,
        "energia": _integrar(potencia, t),
    }


def resumen(c: dict[str, np.ndarray]) -> dict[str, float]:
    """Los números principales de un movimiento (lo que calcula calcular())."""
    # El registro también guarda los ratos quieto: el tiempo que cuenta es solo el que se movió
    tiempo = float(np.sum(np.diff(c["t"])[c["moviendo"][1:]]))
    recorrido = float(c["recorrido"][-1])
    v_max = float(np.max(np.abs(c["v"])))
    energia = float(c["energia"][-1])
    return {
        "duracion": float(c["t"][-1]),  # todo lo grabado, con los ratos quieto incluidos
        "tiempo": tiempo,
        "distancia": float(c["x"][-1]),  # desplazamiento: dónde terminó respecto de donde empezó
        "recorrido": recorrido,
        "v_media": recorrido / tiempo if tiempo > 0 else 0.0,  # rapidez media mientras se movía
        "v_max": v_max,
        "a_max": float(np.max(np.abs(c["a_mpu"]))),
        "angulo": float(c["angulo"][-1]),
        "corriente_max": float(np.max(c["corriente"])),
        "energia": energia,
        "potencia_media": energia / tiempo if tiempo > 0 else 0.0,
        "energia_cinetica_max": 0.5 * MASA * v_max**2,
    }
