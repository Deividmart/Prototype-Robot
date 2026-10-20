"""
Robot simulado: hace de ESP32 con motores, MPU6050 e INA219, para probar el registro
y las gráficas sin el robot armado. Se conecta al cerebro igual que el ESP32 de verdad y mueve
un modelo físico del robot (motores amarillos, pilas AA, rozamiento).

Uso, con el cerebro encendido en otra ventana:
    robot-env\\Scripts\\python.exe simular_robot.py
Después escribe comandos como en el monitor del ESP32: "avanza dos metros", "gira a la derecha".
"empujar" le da un empujón con la mano (sin motores). "salir" termina.
"""
import argparse
import json
import math
import random
import threading
import time

import simple_websocket

import numpy as np

from fisica import ANCHO_EJES, DIAMETRO_RUEDA, MASA, velocidad_ruedas

# Motor amarillo (TT 1:48) a 6 V: ~200 rpm sin carga y ~0,8 A con la rueda trabada
R_MOTOR = 7.5  # ohm
# El motor real resultó 1,22 veces más rápido que el modelo de fisica.py (calibración del 19/10/2026)
K_MOTOR = 0.287 / 1.22  # V·s/rad = N·m/A, contando la caja reductora
ROCE_MOTOR = 0.025  # N·m, rozamiento de la caja reductora
DIFERENCIA_MOTORES = 0.04  # el motor derecho rinde 4% menos: dos motores nunca son iguales
RODADURA = 0.04  # coeficiente de rozamiento de rodadura
V_PILAS = 6.2  # V, 4 pilas AA nuevas
R_PILAS = 0.6  # ohm, resistencia interna de las 4 pilas
INERCIA_GIRO = 0.002  # kg·m²
ROCE_GIRO = 0.02  # N·m, la rueda loca arrastra al girar en el lugar
R_RUEDA = DIAMETRO_RUEDA / 2
G = 9.81

# Control (lo mismo que va a hacer el firmware)
PWM_CRUCERO = 200
PWM_GIRO = 170
PWM_LENTO = 130  # cerca del final, para no pasarse
CORRECCION_RECTA = 3  # PWM por cada grado desviado: el giroscopio lo mantiene derecho
CORRECCION_MAX = 60  # tope: si una rueda patina, la otra no se para y el robot no pivotea
FRENO_LENTO_M = 0.10
FRENO_LENTO_GRADOS = 25
ANTICIPO_GIRO_S = 0.02  # el robot sigue girando un poco después de frenar
TIEMPO_MAX_S = 10  # ninguna acción dura más que esto, por seguridad
FRENO_S = 0.5  # al parar frena en corto y después deja las ruedas libres (se puede empujar)

DT = 0.001  # paso de la simulación
PERIODO_DATOS = 0.02  # 50 mediciones por segundo


class Robot:
    def __init__(self):
        self.lock = threading.Lock()
        self.t = 0.0
        self.v = 0.0  # m/s, hacia adelante
        self.w = 0.0  # rad/s, positivo = girando a la derecha
        self.a = 0.0
        self.avance = 0.0  # m que el firmware cree que anduvo (modelo del motor), en la tarea actual
        # El firmware manda el promedio de la aceleración desde la medición anterior, no una lectura suelta
        self.medido = (0.0, 0.0, 0.0)  # (t, v, v·ω) de la medición anterior
        self.pwm = [0, 0]
        self.voltaje = V_PILAS
        self.corriente = 0.0
        self.angulo_gyro = 0.0  # lo que el firmware integra del giroscopio, en grados
        self.sesgo_gyro = random.uniform(-0.4, 0.4)  # todo giroscopio tiene un pequeño error fijo
        self.tarea = None
        self.freno_hasta = -1.0
        self.empujon_hasta = -1.0

    # --- Sensores ---
    def leer_giroscopio(self) -> float:
        return math.degrees(self.w) + self.sesgo_gyro + random.gauss(0, 0.3)

    def medicion(self) -> dict:
        vibracion = 0.15 if self.pwm != [0, 0] else 0.0
        t0, v0, lat0 = self.medido
        lapso = self.t - t0
        lat = self.v * self.w
        a = (self.v - v0) / lapso if lapso > 0 else self.a
        a_lat = (lat + lat0) / 2
        self.medido = (self.t, self.v, lat)
        return {
            "tipo": "medicion",
            "t_ms": int(self.t * 1000),
            "acel": round(a + random.gauss(0, 0.05 + vibracion), 3),
            "acel_lat": round(a_lat + random.gauss(0, 0.05 + vibracion), 3),
            "giro": round(self.leer_giroscopio(), 2),
            "voltaje": round(self.voltaje + random.gauss(0, 0.004), 3),
            "corriente": round(self.corriente + random.gauss(0, 0.003), 4),
            "pwm_izq": self.pwm[0],
            "pwm_der": self.pwm[1],
        }

    # --- Órdenes que llegan del cerebro ---
    def ejecutar(self, accion: str, parametro: float) -> None:
        with self.lock:
            if accion not in ("avanzar", "retroceder", "girar", "detener"):
                return  # saludo, clima, reiniciar...: no cambian lo que están haciendo los motores
            self.angulo_gyro = 0.0
            self.avance = 0.0
            if accion in ("avanzar", "retroceder"):
                sentido = 1 if accion == "avanzar" else -1
                metros = abs(parametro) or 0.5
                self.tarea = {"tipo": "recta", "sentido": sentido, "metros": metros, "desde": self.t}
            elif accion == "girar":
                self.tarea = {"tipo": "giro", "grados": parametro or 90, "desde": self.t}
            else:  # detener
                self._parar()

    def empujar(self) -> None:
        with self.lock:
            self.empujon_hasta = self.t + 0.3

    def detener(self) -> None:
        with self.lock:
            self._parar()

    def _parar(self) -> None:
        self.tarea = None
        self.pwm = [0, 0]
        self.freno_hasta = self.t + FRENO_S

    # --- Firmware: decide el PWM de cada motor ---
    def _controlar(self) -> None:
        tarea = self.tarea
        if tarea is None:
            return
        if self.t - tarea["desde"] > TIEMPO_MAX_S:
            self._parar()
            return
        if tarea["tipo"] == "recta":
            falta = tarea["metros"] - self.avance
            if falta <= 0:
                self._parar()
                return
            # Desviado a la derecha (ángulo > 0): frena la rueda izquierda y apura la derecha, vaya adelante o atrás
            correccion = max(-CORRECCION_MAX, min(CORRECCION_MAX, CORRECCION_RECTA * self.angulo_gyro))
            base = (PWM_LENTO if falta < FRENO_LENTO_M else PWM_CRUCERO) * tarea["sentido"]
            self.pwm = [int(max(-255, min(255, base - correccion))), int(max(-255, min(255, base + correccion)))]
        else:
            giro = abs(math.degrees(self.w))
            falta = abs(tarea["grados"]) - abs(self.angulo_gyro) - giro * ANTICIPO_GIRO_S
            if falta <= 0:
                self._parar()
                return
            s = 1 if tarea["grados"] >= 0 else -1
            pwm = PWM_LENTO if falta < FRENO_LENTO_GRADOS else PWM_GIRO
            self.pwm = [pwm * s, -pwm * s]

    # --- Física ---
    def paso(self) -> None:
        with self.lock:
            self._controlar()
            self.angulo_gyro += self.leer_giroscopio() * DT

            v_ruedas = (self.v + self.w * ANCHO_EJES / 2, self.v - self.w * ANCHO_EJES / 2)
            fuerzas, corriente = [], 0.0
            for lado, (pwm, v_rueda) in enumerate(zip(self.pwm, v_ruedas)):
                w_rueda = v_rueda / R_RUEDA
                fraccion = pwm / 255
                # PWM 0: primero freno en corto (el motor frena con su propio voltaje), después rueda libre
                libre = pwm == 0 and self.t >= self.freno_hasta
                i_motor = 0.0 if libre else (fraccion * self.voltaje - K_MOTOR * w_rueda) / R_MOTOR
                rinde = 1 - DIFERENCIA_MOTORES if lado == 1 else 1
                torque = rinde * K_MOTOR * i_motor - ROCE_MOTOR * math.tanh(w_rueda / 0.5)
                fuerzas.append(torque / R_RUEDA)
                corriente += fraccion * i_motor  # con PWM, las pilas solo entregan corriente una fracción del tiempo

            empujon = 3.0 if self.t < self.empujon_hasta else 0.0
            rodadura = RODADURA * MASA * G * math.tanh(self.v / 0.02)
            self.a = (fuerzas[0] + fuerzas[1] + empujon - rodadura) / MASA
            alfa = ((fuerzas[0] - fuerzas[1]) * ANCHO_EJES / 2 - ROCE_GIRO * math.tanh(self.w / 0.1)) / INERCIA_GIRO
            self.v += self.a * DT
            self.w += alfa * DT
            self.corriente = corriente
            self.voltaje = V_PILAS - R_PILAS * corriente
            # Lo mismo que el firmware: estima cuánto anduvo con el voltaje y la corriente (no ve la v real)
            v_izq, v_der = velocidad_ruedas(np.array([self.pwm[0]]), np.array([self.pwm[1]]),
                                            np.array([self.voltaje]), np.array([self.corriente]))
            self.avance += abs(float(v_izq[0] + v_der[0]) / 2) * DT
            self.t += DT


def describir(accion: str, parametro: float) -> str:
    """Igual que ejecutarAccion() del firmware."""
    if accion in ("avanzar", "retroceder"):
        return f">> MOTORES: {accion} {parametro:.1f} m"
    if accion == "girar":
        return f">> MOTORES: girar {abs(parametro):.0f} grados ({'derecha' if parametro >= 0 else 'izquierda'})"
    if accion == "detener":
        return ">> MOTORES: detener"
    return ">> (sin movimiento)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--servidor", default="ws://127.0.0.1:5000/ws")
    args = parser.parse_args()

    try:
        ws = simple_websocket.Client.connect(args.servidor)
    except Exception as e:
        raise SystemExit(f"No me pude conectar a {args.servidor}: ¿está encendido el cerebro? ({e})")
    print("Conectado al servidor de Aries (robot SIMULADO)")

    robot = Robot()
    lock_envio = threading.Lock()
    activo = threading.Event()
    activo.set()

    def enviar(datos: dict) -> None:
        with lock_envio:
            ws.send(json.dumps(datos))

    def recibir() -> None:
        try:
            while activo.is_set():
                mensaje = ws.receive()
                if mensaje is None:
                    continue
                respuesta = json.loads(mensaje)
                accion = respuesta.get("accion", "detener")
                parametro = float(respuesta.get("parametro", 0))
                print(f'\nAries dice: "{respuesta.get("respuesta_hablada", "")}"\n{describir(accion, parametro)}\n> ', end="", flush=True)
                robot.ejecutar(accion, parametro)
        except simple_websocket.ConnectionClosed:
            pass
        robot.detener()
        if activo.is_set():
            print("\nSe perdió la conexión con el servidor. Freno por seguridad.", flush=True)
        activo.clear()

    def simular() -> None:
        siguiente = time.perf_counter()
        try:
            while activo.is_set():
                for _ in range(round(PERIODO_DATOS / DT)):
                    robot.paso()
                enviar(robot.medicion())
                siguiente += PERIODO_DATOS
                time.sleep(max(0.0, siguiente - time.perf_counter()))
        except simple_websocket.ConnectionClosed:
            activo.clear()

    threading.Thread(target=recibir, daemon=True).start()
    threading.Thread(target=simular, daemon=True).start()

    print('Escribe un comando y presiona Enter ("empujar" para empujarlo, "salir" para terminar)')
    try:
        while activo.is_set():
            linea = input("> ").strip()
            if linea.lower() in ("salir", "exit"):
                break
            if linea.lower() == "empujar":
                robot.empujar()
                print("(empujón con la mano)")
            elif linea:
                enviar({"texto": linea})
    except (EOFError, KeyboardInterrupt):
        pass
    activo.clear()
    ws.close()


if __name__ == "__main__":
    main()
