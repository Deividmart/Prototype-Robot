// Firmware de Aries: maneja los motores y los sensores, manda las mediciones a la PC por WiFi
// (WebSocket, 50 por segundo) y ejecuta las acciones que le devuelve el cerebro.
// También manda el audio del micrófono (si ENVIAR_AUDIO = 1) y acepta comandos escritos en el
// monitor serial.
//
// El robot no tiene encoders: la distancia se estima con el modelo del motor (voltaje y corriente
// del INA219) y los giros se miden con el giroscopio del MPU6050. fisica.py hace las mismas cuentas.
//
// La cara son 4 matrices 8x8 (MAX7219, módulo FC16): ojos que parpadean cuando espera, ojos
// contentos mientras habla y cara molesta mientras avanza o gira.
//
// Redes WiFi: además de la de secrets.h, el robot recuerda hasta 5 redes en su memoria y se conecta a la
// que tenga mejor señal. Se le enseña una por USB sin volver a cargar el firmware (Aries.bat lo hace solo):
//   wifi Nombre de la red|clave     guarda la red y reinicia      wifi lista     wifi borrar
#include <WiFi.h>
#include <Wire.h>
#include <WebSocketsClient.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <MD_Parola.h>
#include <MD_MAX72xx.h>
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID  // sin secrets.h (otra computadora): las redes se le enseñan con "wifi nombre|clave"
#define WIFI_SSID ""
#define WIFI_PASSWORD ""
#endif
#ifndef SERVIDOR_URL
#define SERVIDOR_URL "http://192.168.1.2:5000"
#endif
#include "soc/rtc_cntl_reg.h"  // detector de bajo voltaje (ver conectarWifi)

// 1 = manda el audio del INMP441 a la PC. 0 = sin micrófono: se le habla por el de la PC (iniciar.bat pc)
#ifndef ENVIAR_AUDIO
#define ENVIAR_AUDIO 0  // 20/10/2026: el robot quedó sin micrófono
#endif
#if ENVIAR_AUDIO
#include <ESP_I2S.h>
#endif

// --- Pines (ENSAMBLAJE.md) ---
// 21/10/2026: AIN1 y AIN2 pasaron de D18 y D5 a D32 y D15 (la señal no llegaba bien al lado A del TB6612)
const int PIN_PWMA = 19, PIN_AIN1 = 32, PIN_AIN2 = 15;  // motor A = rueda izquierda
const int PIN_PWMB = 17, PIN_BIN1 = 16, PIN_BIN2 = 4;  // motor B = rueda derecha
const int PIN_STBY = 23;
const int PIN_SDA = 21, PIN_SCL = 22;
const int PIN_SCK = 32, PIN_WS = 25, PIN_SD = 33;
const int PIN_VDD_MIC = 27;  // el micrófono consume ~1.4 mA: lo alimenta un pin
const int PIN_LR_MIC = 26;   // L/R del micrófono en 0 V (canal izquierdo): así todo el mic va a la fila al aire
const int PIN_DIN = 13, PIN_CLK = 14, PIN_CS = 27;  // matrices (SPI por software: 18/19/23 son de los motores)
// CS usa la pata del VDD del micrófono: sin micrófono (ENVIAR_AUDIO 0) queda libre

const uint8_t DIR_MPU = 0x68, DIR_INA = 0x40;

// --- Robot y motor: los mismos números que fisica.py ---
const float RADIO_RUEDA = 0.0305;      // m
const float R_MOTOR = 7.5;             // ohm
const float K_MOTOR = 0.287;           // V·s/rad
// Calibrado 19/10/2026 (pilas a ~4,1 V): pidieron 0,3 m y anduvo 0,55; pidieron 1,67 y anduvo 1,30.
// Encaja con real = 1,22 × modelo + 0,18 m: el factor (igual en fisica.py) y lo que sigue de largo al frenar
const float AJUSTE_DISTANCIA = 1.22;
const float DISTANCIA_FRENADO = 0.05;  // m: provisorio con las pilas de litio (con las AA cansadas era 0,18); recalibrar
const float R_SHUNT = 0.1;             // ohm, la resistencia R100 del INA219
const float G = 9.81;

// Cómo va montado el MPU6050 (ENSAMBLAJE.md): X hacia adelante, Y hacia la izquierda, Z hacia arriba.
// Con el comando "imu" del monitor serial se comprueba; si un signo sale al revés, se cambia acá.
const float SIGNO_ADELANTE = 1;
const float SIGNO_DERECHA = -1;
const float SIGNO_GIRO = -1;  // el giroscopio da + al girar a la izquierda; Aries usa + = derecha

// --- Control ---
const int PWM_CRUCERO = 200;
// En el aire 130-170 alcanza, pero en el piso las ruedas se quedaban pegadas (21/10/2026)
const int PWM_GIRO = 220;
const int PWM_LENTO = 180;              // cerca del final, para no pasarse
const int PWM_ARRANQUE = 255;           // empujón al empezar: vence el roce del piso (el "golpecito")
const uint32_t ARRANQUE_MS = 250;
// Pilas: 2 de litio 18650 en serie (7,4 V; 8,4 V recién cargadas). Los motores amarillos son de 6 V:
// el PWM se escala con el voltaje medido para que en promedio nunca les lleguen más de VOLTAJE_MOTOR_MAX
// (el empujón del arranque, que dura un cuarto de segundo, puede llegar a VOLTAJE_EMPUJON)
const float VOLTAJE_MOTOR_MAX = 6.0;
const float VOLTAJE_EMPUJON = 7.5;
// true con el portapilas de 2 pilas 18650; false si se vuelve a las 4 pilas AA
const bool PILAS_DE_LITIO = false;  // 22/10/2026: el equipo prefirió sin el bloqueo por pilas bajas
// El litio se arruina si baja de ~3 V por pila: quieto por debajo de esto, el robot no se mueve más
const float VOLTAJE_PILAS_MINIMO = 6.4;  // 3,2 V por pila
const float VOLTAJE_HAY_PILAS = 1.0;     // menos que esto: interruptor apagado, no son pilas bajas
const float CORRECCION_RECTA = 3;       // PWM por cada grado desviado: el giroscopio lo mantiene derecho
                                        // (con 6 el robot real serpenteaba)
// El motor derecho tiene más roce: con la misma potencia va más lento y el robot se tuerce a la derecha.
// Medido en el piso el 21/10/2026: con la derecha a 1,30 veces la izquierda va derecho (+1,7° en 1 s
// contra +52° sin compensar). El giroscopio corrige lo que falte
const float AJUSTE_DERECHA = 1.30;
const int CORRECCION_MAX = 60;          // tope: si una rueda patina, la otra no se para y el robot no pivotea
const float FRENO_LENTO_M = 0.10;
const float FRENO_LENTO_GRADOS = 25;
// Al cortar los motores sigue girando por inercia: corta antes, lo que giraría en este tiempo a la velocidad
// que lleva. 23/10/2026 con litio: seguía 0,11 a 0,13 s (se pasaba 20 a 30°: pedían 90 y giraba 108)
const float ANTICIPO_GIRO_S = 0.10;
const uint32_t TIEMPO_MAX_MS = 10000;   // ninguna acción dura más que esto, por seguridad
const uint32_t FRENO_MS = 500;          // al parar frena en corto y después deja las ruedas libres
const uint32_t PERIODO_CONTROL_MS = 10; // 100 veces por segundo
const int CICLOS_POR_MEDICION = 2;      // 50 mediciones por segundo a la PC
// Cuánto puede cambiar el PWM cada 10 ms. Con el ESP32 en las mismas pilas hacía falta arrancar suave
// (de a 8) porque el pico de corriente lo reiniciaba; desde que va con su propio USB, el arranque es
// casi inmediato (de 0 a 255 en 40 ms) y lleva un empujón (PWM_ARRANQUE)
const int RAMPA_PWM = 16;  // 0 a 255 en 160 ms: con el ESP32 en las pilas (VIN), arrancar de golpe lo reiniciaba

// --- Audio ---
const int TASA = 16000;
const int MUESTRAS = 512;  // 32 ms por paquete
// El INMP441 entrega 24 bits dentro de 32; al pasar a 16 bits este corrimiento define la ganancia:
// cada 1 menos duplica el volumen. Se calibra con el comando "nivel" (ver INSTALACION.md).
const int CORRIMIENTO = 12;

// --- Cara ---
const int MATRICES = 4;
const int BRILLO = 1;  // de 0 a 15: las matrices van a 3,3 V y con más brillo bajan las pilas y parpadean
const bool DE_CABEZA = true;  // la matriz va montada al revés: gira todo 180°

struct Medicion {
  uint32_t t_ms;
  float acel, acel_lat, giro, voltaje, corriente;
  int pwm_izq, pwm_der;
};

WebSocketsClient ws;
QueueHandle_t colaMediciones;
portMUX_TYPE candado = portMUX_INITIALIZER_UNLOCKED;
volatile bool conectado = false;

// Lo que llega del cerebro (lo escribe el WebSocket, lo lee la tarea de control)
struct {
  bool nueva;
  char accion[16];
  float parametro;
} orden = {false, "", 0};
// La orden vino del monitor serial ("mover avanzar 0.5"): prueba de los motores con la misma lógica que
// usa Aries, pero sin necesitar la PC
volatile bool ordenLocal = false;
Medicion ultima = {};  // para el comando "imu"

bool mostrarImu = false;
uint32_t ultimoImu = 0;
String lineaActual;
uint32_t felizHasta = 0;  // la cara pone ojos contentos hasta este momento

#if ENVIAR_AUDIO
I2SClass i2s;
int32_t crudo[MUESTRAS];
int16_t pcm[MUESTRAS];
bool mostrarNivel = false;
uint32_t ultimoNivel = 0;
#endif

// ====================== Sensores ======================

float sesgoAdelante = 0, sesgoDerecha = 0, sesgoGiro = 0;
bool hayMpu = false, hayIna = false;

void escribirRegistro8(uint8_t dir, uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  Wire.write(valor);
  Wire.endTransmission();
}

void escribirRegistro16(uint8_t dir, uint8_t reg, uint16_t valor) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  Wire.write(valor >> 8);
  Wire.write(valor & 0xFF);
  Wire.endTransmission();
}

bool leerRegistros(uint8_t dir, uint8_t reg, uint8_t *destino, uint8_t n) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(dir, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) destino[i] = Wire.read();
  return true;
}

bool existe(uint8_t dir) {
  Wire.beginTransmission(dir);
  return Wire.endTransmission() == 0;
}

void iniciarSensores() {
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  hayMpu = existe(DIR_MPU);
  hayIna = existe(DIR_INA);
  if (hayMpu) {
    escribirRegistro8(DIR_MPU, 0x6B, 0x01);  // despierto, reloj del giroscopio
    delay(100);
    escribirRegistro8(DIR_MPU, 0x1A, 0x03);  // filtro de 44 Hz: saca la vibración de los motores
    escribirRegistro8(DIR_MPU, 0x1B, 0x08);  // giroscopio ±500 °/s (girando en el lugar pasa los 250)
    escribirRegistro8(DIR_MPU, 0x1C, 0x08);  // acelerómetro ±4 g
  } else {
    Serial.println("AVISO: no encuentro el MPU6050 (0x68). Sin él no puede girar ni ir derecho.");
  }
  if (hayIna) {
    // 32 V, ±320 mV de shunt, promedio de 8 lecturas (suaviza el PWM de los motores), continuo
    escribirRegistro16(DIR_INA, 0x00, 0x3DDF);
  } else {
    Serial.println("AVISO: no encuentro el INA219 (0x40). Sin él no puede medir cuánto avanza.");
  }
}

// Aceleración hacia adelante y hacia la derecha (m/s²) y giro (°/s, + = derecha), sin descontar el sesgo
bool leerMpuCrudo(float &adelante, float &derecha, float &giro) {
  uint8_t b[14];
  if (!hayMpu || !leerRegistros(DIR_MPU, 0x3B, b, 14)) return false;
  int16_t ax = (b[0] << 8) | b[1];
  int16_t ay = (b[2] << 8) | b[3];
  int16_t gz = (b[12] << 8) | b[13];
  adelante = SIGNO_ADELANTE * ax / 8192.0f * G;
  derecha = SIGNO_DERECHA * ay / 8192.0f * G;
  giro = SIGNO_GIRO * gz / 65.5f;
  return true;
}

void leerMpu(float &adelante, float &derecha, float &giro) {
  static float a0 = 0, d0 = 0, g0 = 0;  // si una lectura falla, se repite la anterior
  if (leerMpuCrudo(a0, d0, g0)) {
    a0 -= sesgoAdelante;
    d0 -= sesgoDerecha;
    g0 -= sesgoGiro;
  }
  adelante = a0;
  derecha = d0;
  giro = g0;
}

// Un segundo quieto al encender: lo que marca el MPU así es su error (y la inclinación) y se descuenta
void calibrarMpu() {
  if (!hayMpu) return;
  Serial.println("Calibrando el MPU6050: no muevas el robot por 1 segundo...");
  float suma[3] = {0, 0, 0};
  int n = 0;
  for (int i = 0; i < 100; i++) {
    float a, d, g;
    if (leerMpuCrudo(a, d, g)) {
      suma[0] += a;
      suma[1] += d;
      suma[2] += g;
      n++;
    }
    delay(10);
  }
  if (n > 0) {
    sesgoAdelante = suma[0] / n;
    sesgoDerecha = suma[1] / n;
    sesgoGiro = suma[2] / n;
  }
  Serial.printf("Listo (sesgo del giroscopio: %.2f °/s)\n", sesgoGiro);
}

void leerIna(float &voltaje, float &corriente) {
  uint8_t b[2];
  if (hayIna && leerRegistros(DIR_INA, 0x01, b, 2)) {
    int16_t shunt = (b[0] << 8) | b[1];  // de a 10 µV
    corriente = shunt * 10e-6f / R_SHUNT;
  }
  if (hayIna && leerRegistros(DIR_INA, 0x02, b, 2)) {
    uint16_t bus = (b[0] << 8) | b[1];
    voltaje = (bus >> 3) * 0.004f;
  }
}

// ====================== Motores ======================

// pwm de -255 (atrás) a 255 (adelante); 0 = rueda libre
void motor(int lado, int pwm) {
  int in1 = lado == 0 ? PIN_AIN1 : PIN_BIN1;
  int in2 = lado == 0 ? PIN_AIN2 : PIN_BIN2;
  digitalWrite(in1, pwm > 0 ? HIGH : LOW);
  digitalWrite(in2, pwm < 0 ? HIGH : LOW);
  ledcWrite(lado == 0 ? PIN_PWMA : PIN_PWMB, abs(pwm));
}

// Freno en corto: el motor frena con su propio voltaje
void frenar(int lado) {
  digitalWrite(lado == 0 ? PIN_AIN1 : PIN_BIN1, HIGH);
  digitalWrite(lado == 0 ? PIN_AIN2 : PIN_BIN2, HIGH);
  ledcWrite(lado == 0 ? PIN_PWMA : PIN_PWMB, 0);
}

void iniciarMotores() {
  int salidas[] = {PIN_AIN1, PIN_AIN2, PIN_BIN1, PIN_BIN2, PIN_STBY};
  for (int pin : salidas) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  ledcAttach(PIN_PWMA, 20000, 8);  // 20 kHz: fuera del rango que se escucha
  ledcAttach(PIN_PWMB, 20000, 8);
  digitalWrite(PIN_STBY, HIGH);
}

// ====================== Control ======================

enum Tarea { NINGUNA, RECTA, GIRO };
volatile Tarea tarea = NINGUNA;  // volatile: la cara la lee desde el bucle
int sentido = 1;          // recta: 1 adelante, -1 atrás
float objetivo = 0;       // recta: metros; giro: grados (+ derecha)
float avance = 0;         // metros que estima haber andado en esta recta
volatile float rumbo = 0; // grados girados desde que empezó la tarea (giroscopio)
volatile float velocidad = 0;  // m/s según el modelo del motor, para la cara
volatile float voltajePilas = 0;    // el último que midió el INA219
volatile bool pilasBajas = false;   // cuando se activa, el robot no se mueve más hasta cambiar las pilas
uint32_t desde = 0;
uint32_t frenoHasta = 0;
int pwmIzq = 0, pwmDer = 0;

void parar() {
  if (tarea != NINGUNA)  // resumen para revisar desde el monitor serial
    Serial.printf("\n>> FIN: %.1f s, avance estimado %.2f m, giro %.0f grados\n",
                  (millis() - desde) / 1000.0f, avance, rumbo);
  tarea = NINGUNA;
  pwmIzq = pwmDer = 0;
  frenoHasta = millis() + FRENO_MS;
}

void empezar(const char *accion, float parametro) {
  bool mueve = strcmp(accion, "avanzar") == 0 || strcmp(accion, "retroceder") == 0 || strcmp(accion, "girar") == 0;
  if (mueve && pilasBajas) {
    Serial.println("PILAS BAJAS: no me muevo. Carga las pilas de litio.");
    return;
  }
  if (strcmp(accion, "avanzar") == 0 || strcmp(accion, "retroceder") == 0) {
    tarea = RECTA;
    sentido = strcmp(accion, "avanzar") == 0 ? 1 : -1;
    objetivo = fabs(parametro) > 0 ? fabs(parametro) : 0.5;
    // Lo que sigue de largo al frenar ya cuenta: para distancias muy cortas igual da un empujoncito
    objetivo = max(objetivo - DISTANCIA_FRENADO, 0.02f);
  } else if (strcmp(accion, "girar") == 0) {
    tarea = GIRO;
    objetivo = parametro != 0 ? parametro : 90;
  } else if (strcmp(accion, "detener") == 0) {
    parar();
    return;
  } else {
    return;  // saludo, clima, reiniciar...: no cambian lo que están haciendo los motores
  }
  avance = 0;
  rumbo = 0;
  desde = millis();
}

// Velocidad del centro del robot (m/s) según el modelo del motor: igual que velocidad_ruedas() de fisica.py
float velocidadRueda(float d, float voltaje, float iMotor) {
  if (d == 0) return 0;
  float omega = (fabs(d) * voltaje - R_MOTOR * iMotor) / K_MOTOR;
  if (omega < 0) omega = 0;  // con la rueda trabada no gira "para atrás"
  return copysignf(omega * RADIO_RUEDA * AJUSTE_DISTANCIA, d);
}

float velocidadModelo(float voltaje, float corriente) {
  float dIzq = pwmIzq / 255.0f, dDer = pwmDer / 255.0f;
  float suma = fabs(dIzq) + fabs(dDer);
  if (suma < 0.01f) return 0;
  float iMotor = corriente / suma;  // misma corriente en los dos motores
  return (velocidadRueda(dIzq, voltaje, iMotor) + velocidadRueda(dDer, voltaje, iMotor)) / 2;
}

void controlar(float giro) {
  uint32_t ahora = millis();
  // Sin conexión frena por seguridad, salvo las pruebas escritas en el monitor serial ("mover ...")
  if (tarea != NINGUNA && ((!conectado && !ordenLocal) || ahora - desde > TIEMPO_MAX_MS)) parar();

  if (tarea == RECTA) {
    float falta = objetivo - avance;
    if (falta <= 0) {
      parar();
    } else {
      // Desviado a la derecha (rumbo > 0): frena la izquierda y apura la derecha, vaya adelante o atrás
      float base = (falta < FRENO_LENTO_M ? PWM_LENTO : PWM_CRUCERO) * sentido;
      float baseIzq = base, baseDer = base * AJUSTE_DERECHA;
      if (fabs(baseDer) > 255) {  // si la derecha no da más, se baja la izquierda para que sigan parejas
        baseIzq *= 255 / fabs(baseDer);
        baseDer = copysignf(255, baseDer);
      }
      float correccion = constrain(CORRECCION_RECTA * rumbo, -CORRECCION_MAX, CORRECCION_MAX);
      pwmIzq = constrain((int)(baseIzq - correccion), -255, 255);
      pwmDer = constrain((int)(baseDer + correccion), -255, 255);
    }
  } else if (tarea == GIRO) {
    float falta = fabs(objetivo) - fabs(rumbo) - fabs(giro) * ANTICIPO_GIRO_S;
    if (falta <= 0) {
      parar();
    } else {
      int s = objetivo > 0 ? 1 : -1;
      int pwm = falta < FRENO_LENTO_GRADOS ? PWM_LENTO : PWM_GIRO;
      pwmIzq = pwm * s;
      pwmDer = -pwm * s;
    }
  }

  static int salidaIzq = 0, salidaDer = 0;  // lo que de verdad reciben los motores (con la rampa)
  // Con más de 6 V en las pilas se recorta el PWM: los motores reciben en promedio a lo sumo ese voltaje
  float v = voltajePilas;
  bool empujon = tarea != NINGUNA && ahora - desde < ARRANQUE_MS;
  float limite = v > 1 ? min(1.0f, (empujon ? VOLTAJE_EMPUJON : VOLTAJE_MOTOR_MAX) / v) : 1.0f;
  if (empujon) {  // empujón: a fondo (hasta VOLTAJE_EMPUJON), cada rueda en su sentido
    if (pwmIzq != 0) pwmIzq = pwmIzq > 0 ? PWM_ARRANQUE : -PWM_ARRANQUE;
    if (pwmDer != 0) pwmDer = pwmDer > 0 ? PWM_ARRANQUE : -PWM_ARRANQUE;
  }
  pwmIzq = (int)(pwmIzq * limite);
  pwmDer = (int)(pwmDer * limite);
  if (tarea != NINGUNA) {
    salidaIzq += constrain(pwmIzq - salidaIzq, -RAMPA_PWM, RAMPA_PWM);
    salidaDer += constrain(pwmDer - salidaDer, -RAMPA_PWM, RAMPA_PWM);
    pwmIzq = salidaIzq;  // las mediciones y el modelo del motor usan lo que de verdad se aplicó
    pwmDer = salidaDer;
    motor(0, pwmIzq);
    motor(1, pwmDer);
    return;
  }
  salidaIzq = salidaDer = 0;  // frenar es inmediato
  if ((int32_t)(frenoHasta - ahora) > 0) {
    frenar(0);
    frenar(1);
  } else {
    motor(0, 0);
    motor(1, 0);
  }
}

// Corre aparte del WiFi, 100 veces por segundo exactas: lee sensores, decide los motores y
// deja una medición para la PC cada 2 vueltas
void tareaControl(void *) {
  TickType_t siguiente = xTaskGetTickCount();
  const float dt = PERIODO_CONTROL_MS / 1000.0f;
  float voltaje = 0, corriente = 0;
  // Las aceleraciones de cada medición son el promedio desde la anterior: al arrancar y al frenar
  // el robot cambia de velocidad en milésimas y una lectura suelta no lo muestra bien
  float sumaAdelante = 0, sumaDerecha = 0;
  int ciclo = 0;
  while (true) {
    vTaskDelayUntil(&siguiente, pdMS_TO_TICKS(PERIODO_CONTROL_MS));
    float adelante, derecha, giro;
    leerMpu(adelante, derecha, giro);
    rumbo += giro * dt;
    sumaAdelante += adelante;
    sumaDerecha += derecha;

    char accion[16] = "";
    float parametro = 0;
    bool nueva = false;
    portENTER_CRITICAL(&candado);
    if (orden.nueva) {
      nueva = true;
      orden.nueva = false;
      strcpy(accion, orden.accion);
      parametro = orden.parametro;
    }
    portEXIT_CRITICAL(&candado);
    if (nueva) empezar(accion, parametro);

    if (++ciclo >= CICLOS_POR_MEDICION) {
      ciclo = 0;
      leerIna(voltaje, corriente);
      voltajePilas = voltaje;
      // Pilas bajas: se mide quieto (con los motores andando el voltaje baja un poco y no cuenta) y
      // tiene que durar 2 s seguidos, para que un bajón suelto no lo bloquee
      // Solo con litio (con 4 pilas AA, 5,5 V es normal). Reconocerlo solo por pasar de 6,6 V no alcanzaba:
      // unas de litio que ya venían descargadas (5 V entre las dos) nunca se protegían
      static uint32_t bajasDesde = 0;
      if (PILAS_DE_LITIO && tarea == NINGUNA && voltaje > VOLTAJE_HAY_PILAS && voltaje < VOLTAJE_PILAS_MINIMO) {
        if (bajasDesde == 0) bajasDesde = millis();
        if (!pilasBajas && millis() - bajasDesde > 2000) {
          pilasBajas = true;
          Serial.printf("\nPILAS BAJAS (%.2f V): el robot ya no se mueve. Carga las pilas de litio.\n", voltaje);
        }
      } else if (tarea == NINGUNA) {
        bajasDesde = 0;
        if (voltaje > VOLTAJE_PILAS_MINIMO + 0.3f) pilasBajas = false;  // pusieron pilas cargadas
      }
      // pwmIzq/pwmDer todavía son los que movieron los motores durante este intervalo
      velocidad = fabs(velocidadModelo(voltaje, corriente));
      if (tarea == RECTA) avance += velocidad * dt * CICLOS_POR_MEDICION;
      Medicion m = {millis(), sumaAdelante / CICLOS_POR_MEDICION, sumaDerecha / CICLOS_POR_MEDICION, giro,
                    voltaje, corriente, pwmIzq, pwmDer};
      sumaAdelante = sumaDerecha = 0;
      xQueueSend(colaMediciones, &m, 0);  // si la cola está llena (sin WiFi) se pierde: no importa
      portENTER_CRITICAL(&candado);
      ultima = m;
      portEXIT_CRITICAL(&candado);
    }
    controlar(giro);
  }
}

// ====================== WiFi y servidor ======================

// --- Redes guardadas en la memoria del ESP32 (sobreviven a apagarlo y a cargar firmware nuevo) ---
const int MAX_REDES = 5;
String redNombre[MAX_REDES + 1], redClave[MAX_REDES + 1];  // + 1: la de secrets.h, al final
int cantidadRedes = 0;

void cargarRedes() {
  Preferences mem;
  mem.begin("wifi", true);
  cantidadRedes = 0;
  for (int i = 0; i < MAX_REDES; i++) {
    String nombre = mem.getString(("n" + String(i)).c_str(), "");
    if (nombre.length() == 0) continue;
    redNombre[cantidadRedes] = nombre;
    redClave[cantidadRedes] = mem.getString(("c" + String(i)).c_str(), "");
    cantidadRedes++;
  }
  mem.end();
  bool repetida = false;
  for (int i = 0; i < cantidadRedes; i++) repetida |= redNombre[i] == WIFI_SSID;
  if (strlen(WIFI_SSID) > 0 && !repetida) {
    redNombre[cantidadRedes] = WIFI_SSID;
    redClave[cantidadRedes] = WIFI_PASSWORD;
    cantidadRedes++;
  }
}

// La nueva queda primera (la que se prueba si no se ve ninguna); si ya estaba, se le cambia la clave
void guardarRed(const String &nombre, const String &clave) {
  String nombres[MAX_REDES] = {nombre}, claves[MAX_REDES] = {clave};
  int n = 1;
  Preferences mem;
  mem.begin("wifi", false);
  for (int i = 0; i < MAX_REDES && n < MAX_REDES; i++) {
    String viejo = mem.getString(("n" + String(i)).c_str(), "");
    if (viejo.length() == 0 || viejo == nombre) continue;
    nombres[n] = viejo;
    claves[n] = mem.getString(("c" + String(i)).c_str(), "");
    n++;
  }
  mem.clear();
  for (int i = 0; i < n; i++) {
    mem.putString(("n" + String(i)).c_str(), nombres[i]);
    mem.putString(("c" + String(i)).c_str(), claves[i]);
  }
  mem.end();
}

void conectarWifi() {
  cargarRedes();
  if (cantidadRedes == 0) {
    Serial.println("No conozco ninguna red WiFi. Abre Aries.bat en la computadora y elige \"Conectar el robot a la WiFi\".");
    while (true) {  // espera a que le enseñen una por USB ("wifi nombre|clave" reinicia el robot)
      leerTeclado();
      actualizarCara();
      delay(20);
    }
  }
  // Al arrancar, el WiFi pide un pico de corriente que hace caer el voltaje un instante y el detector
  // de bajo voltaje ("Brownout") reiniciaba el ESP32 una y otra vez. Se apaga solo mientras conecta
  uint32_t detector = READ_PERI_REG(RTC_CNTL_BROWN_OUT_REG);
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  WiFi.mode(WIFI_STA);
  // Si el router lo rechaza, dice por qué (2 = autenticación vencida, 15 = contraseña mala,
  // 201 = no encuentra la red, 202 = autenticación fallida...)
  static bool avisoPuesto = false;
  if (!avisoPuesto) {
    avisoPuesto = true;
    WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
      Serial.printf("\n[WiFi] desconectado, motivo %d\n", info.wifi_sta_disconnected.reason);
    }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  }
  WiFi.setAutoReconnect(true);
  // Algunos routers cortan el saludo con el ESP32 en 802.11n: solo b/g es más compatible
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G);

  // Routers con la misma red en 2,4 y 5 GHz (FILA-MARTINEZ) a veces cortan el saludo del ESP32 (motivos
  // 2, 4, 15). Se buscan las redes conocidas y se conecta directo a la antena de 2,4 GHz con mejor señal
  // y su canal, y si falla se vuelve a intentar desde cero cada 12 s
  int canal = 0, elegida = 0;  // si no se ve ninguna, se prueba la última que le enseñaron
  uint8_t bssid[6];
  bool hayBssid = false;
  int n = WiFi.scanNetworks();
  int mejor = -1000;
  for (int i = 0; i < n; i++) {
    for (int r = 0; r < cantidadRedes; r++) {
      if (WiFi.SSID(i) == redNombre[r] && WiFi.RSSI(i) > mejor) {
        mejor = WiFi.RSSI(i);
        canal = WiFi.channel(i);
        memcpy(bssid, WiFi.BSSID(i), 6);
        hayBssid = true;
        elegida = r;
      }
    }
  }
  WiFi.scanDelete();
  const char *ssid = redNombre[elegida].c_str(), *clave = redClave[elegida].c_str();
  Serial.printf("Conectando a WiFi \"%s\"", ssid);
  if (hayBssid) Serial.printf(" (canal %d, señal %d dBm)", canal, mejor);
  else Serial.print(" (no veo ninguna red conocida: igual lo intento)");

  uint32_t inicio = millis(), intento = millis();
  if (hayBssid) WiFi.begin(ssid, clave, canal, bssid);
  else WiFi.begin(ssid, clave);
  // Al prender el WiFi el ESP32 pide un pico de corriente: con toda la potencia (y la matriz prendida)
  // el voltaje caía y se reiniciaba solo ("Brownout"). Para una casa o un salón alcanza con menos
  WiFi.setTxPower(WIFI_POWER_11dBm);  // con más potencia el pico de corriente cortaba el saludo con el router (motivos 2, 4, 15)

  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - intento > 12000) {  // otro intento desde cero
      intento = millis();
      WiFi.disconnect();
      delay(200);
      if (hayBssid) WiFi.begin(ssid, clave, canal, bssid);
      else WiFi.begin(ssid, clave);
      WiFi.setTxPower(WIFI_POWER_11dBm);
    }
    if (millis() - inicio > 60000) {
      Serial.println("\nERROR: no se pudo conectar. Revisa nombre/contraseña y que la red sea de 2.4 GHz.");
      WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, detector);
      return;
    }
    Serial.print('.');
    // Mientras tanto atiende el USB: así Aries.bat le puede enseñar otra red aunque esta no ande
    for (int i = 0; i < 25; i++) {
      leerTeclado();
      delay(20);
    }
  }
  Serial.printf("\nConectado. IP del ESP32: %s\n", WiFi.localIP().toString().c_str());
  // El detector se vuelve a encender: sin él, con las pilas muy bajas el ESP32 quedaba colgado (matriz
  // apagada, motores cortados, sin responder) en vez de reiniciarse y volver solo en unos segundos
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, detector);
}

// El cerebro (server.py) avisa por la red cada segundo "ARIES-CEREBRO 5000" (UDP, a todos). Así el robot
// lo encuentra aunque la PC cambie de dirección o la red sea otra (en la feria); SERVIDOR_URL queda de respaldo
const uint16_t PUERTO_ANUNCIO = 5001;
String hostCerebro;
uint16_t puertoCerebro = 5000;

bool buscarCerebro(uint32_t esperaMs) {
  WiFiUDP udp;
  if (!udp.begin(PUERTO_ANUNCIO)) return false;
  bool encontrado = false;
  for (uint32_t inicio = millis(); millis() - inicio < esperaMs && !encontrado; delay(20)) {
    if (udp.parsePacket() <= 0) continue;
    char texto[40] = "";
    udp.read(texto, sizeof(texto) - 1);
    int puerto = 0;
    if (sscanf(texto, "ARIES-CEREBRO %d", &puerto) == 1 && puerto > 0) {
      hostCerebro = udp.remoteIP().toString();
      puertoCerebro = puerto;
      encontrado = true;
    }
  }
  udp.stop();
  return encontrado;
}

// SERVIDOR_URL viene como "http://192.168.1.11:5000"
void separarUrl(const char *url, String &host, uint16_t &puerto) {
  String u(url);
  u.replace("http://", "");
  int barra = u.indexOf('/');
  if (barra >= 0) u = u.substring(0, barra);
  int dosPuntos = u.indexOf(':');
  host = dosPuntos >= 0 ? u.substring(0, dosPuntos) : u;
  puerto = dosPuntos >= 0 ? u.substring(dosPuntos + 1).toInt() : 80;
}

void describirAccion(const char *accion, float parametro) {
  if (strcmp(accion, "avanzar") == 0 || strcmp(accion, "retroceder") == 0) {
    Serial.printf(">> MOTORES: %s %.1f m\n", accion, fabs(parametro) > 0 ? fabs(parametro) : 0.5);
  } else if (strcmp(accion, "girar") == 0) {
    float grados = parametro != 0 ? parametro : 90;
    Serial.printf(">> MOTORES: girar %.0f grados (%s)\n", fabs(grados), grados >= 0 ? "derecha" : "izquierda");
  } else if (strcmp(accion, "detener") == 0) {
    Serial.println(">> MOTORES: detener");
  } else {
    Serial.println(">> (sin movimiento)");
  }
}

void alEventoWs(WStype_t tipo, uint8_t *datos, size_t largo) {
  switch (tipo) {
    case WStype_CONNECTED:
      conectado = true;
      Serial.println("Conectado al servidor de Aries");
      Serial.print("> ");
      break;

    case WStype_DISCONNECTED:
      // Sin servidor el robot no puede recibir "para": la tarea de control lo frena sola
      if (conectado) Serial.println("\nSe perdió la conexión con el servidor. Freno por seguridad.");
      conectado = false;
      break;

    case WStype_TEXT: {
      JsonDocument respuesta;
      if (deserializeJson(respuesta, datos, largo)) {
        Serial.println("ERROR: respuesta del servidor ilegible");
        return;
      }
      const char *accion = respuesta["accion"] | "detener";
      float parametro = respuesta["parametro"] | 0.0f;
      Serial.printf("\nAries dice: \"%s\"\n", (const char *)(respuesta["respuesta_hablada"] | ""));
      describirAccion(accion, parametro);
      // Contesta algo: ojos contentos mientras habla (la presentación y el agradecimiento duran ~25 s).
      // Piper dice unos 65 ms por letra y tarda ~1 s en empezar; "para" corta la voz y la cara
      if (!esMovimiento(accion)) {
        felizHasta = millis() + 1000 + 65 * strlen(respuesta["respuesta_hablada"] | "");
      } else if (strcmp(accion, "detener") == 0) {
        felizHasta = millis();
      }
      portENTER_CRITICAL(&candado);
      strlcpy(orden.accion, accion, sizeof(orden.accion));
      orden.parametro = parametro;
      orden.nueva = true;
      portEXIT_CRITICAL(&candado);
      ordenLocal = false;
      Serial.print("> ");
      break;
    }

    default:
      break;
  }
}

void enviarMedicion(const Medicion &m) {
  char texto[200];
  snprintf(texto, sizeof(texto),
           "{\"tipo\":\"medicion\",\"t_ms\":%lu,\"acel\":%.3f,\"acel_lat\":%.3f,\"giro\":%.2f,"
           "\"voltaje\":%.3f,\"corriente\":%.4f,\"pwm_izq\":%d,\"pwm_der\":%d}",
           (unsigned long)m.t_ms, m.acel, m.acel_lat, m.giro, m.voltaje, m.corriente, m.pwm_izq, m.pwm_der);
  ws.sendTXT(texto);
}

void enviarTexto(const String &texto) {
  if (!conectado) {
    Serial.println("Sin conexión con el servidor, espera a que reconecte.");
    return;
  }
  JsonDocument pedido;
  pedido["texto"] = texto;
  String cuerpo;
  serializeJson(pedido, cuerpo);
  ws.sendTXT(cuerpo);
}

// ====================== Micrófono ======================

#if ENVIAR_AUDIO
void iniciarMicrofono() {
  pinMode(PIN_LR_MIC, OUTPUT);
  digitalWrite(PIN_LR_MIC, LOW);
  pinMode(PIN_VDD_MIC, OUTPUT);
  digitalWrite(PIN_VDD_MIC, HIGH);
  delay(100);  // el INMP441 tarda un poco en arrancar

  i2s.setPins(PIN_SCK, PIN_WS, -1, PIN_SD);
  if (!i2s.begin(I2S_MODE_STD, TASA, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("ERROR: no se pudo iniciar el micrófono (I2S)");
    while (true) delay(1000);
  }
  Serial.println("Micrófono iniciado");
}

size_t leerAudio() {
  size_t leidas = i2s.readBytes((char *)crudo, sizeof(crudo)) / sizeof(int32_t);
  for (size_t i = 0; i < leidas; i++) {
    int32_t v = crudo[i] >> CORRIMIENTO;
    pcm[i] = (int16_t)constrain(v, -32768, 32767);
  }
  return leidas;
}

// Barra de volumen en dBFS (0 = máximo posible; la voz debería llegar entre -35 y -10)
void imprimirNivel(size_t n) {
  if (millis() - ultimoNivel < 200) return;
  ultimoNivel = millis();
  int pico = 0;
  for (size_t i = 0; i < n; i++) pico = max(pico, abs((int)pcm[i]));
  float dbfs = pico > 0 ? 20.0f * log10f(pico / 32767.0f) : -90.0f;
  int largo = constrain((int)((dbfs + 60.0f) * 40.0f / 60.0f), 0, 40);
  char barra[41];
  memset(barra, '#', largo);
  barra[largo] = '\0';
  Serial.printf("%6.1f dBFS |%-40s|%s\n", dbfs, barra, pico >= 32767 ? " SATURA" : "");
}
#endif

// ====================== Cara (matrices) ======================

MD_Parola pantalla(MD_MAX72XX::FC16_HW, PIN_DIN, PIN_CLK, PIN_CS, MATRICES);
// Lo que hay en pantalla: no se redibuja si no cambió (reescribir lo mismo hace titilar)
char textoEnPantalla[12] = "ARIES";
int ojosEnPantalla = -1;

bool esMovimiento(const char *accion) {
  return strcmp(accion, "avanzar") == 0 || strcmp(accion, "retroceder") == 0 || strcmp(accion, "girar") == 0 ||
         strcmp(accion, "detener") == 0;
}

void iniciarCara() {
  pantalla.begin();
  pantalla.setIntensity(BRILLO);
  pantalla.setTextAlignment(PA_CENTER);
  if (DE_CABEZA) {  // al revés de arriba abajo y de izquierda a derecha = girado 180°
    pantalla.setZoneEffect(0, true, PA_FLIP_UD);
    pantalla.setZoneEffect(0, true, PA_FLIP_LR);
  }
  pantalla.print("ARIES");
}

void mostrarTexto(const char *texto) {
  if (strcmp(texto, textoEnPantalla) == 0) return;
  strlcpy(textoEnPantalla, texto, sizeof(textoEnPantalla));
  ojosEnPantalla = -1;
  pantalla.print(texto);
}

// Un ojo de 8 columnas: 'n' normal (alto = filas encendidas, para parpadear), 'f' contento (^),
// 'm' molesto (ceño fruncido: el borde de arriba baja hacia el centro de la cara)
uint8_t columnaOjo(int i, int alto, char forma, bool izquierdo) {
  if (forma == 'm') {
    int desde = 1 + (izquierdo ? i : 7 - i) / 2;  // i crece hacia la derecha; el centro está entre los ojos
    uint8_t c = 0;
    for (int fila = desde; fila <= 6; fila++) c |= 1 << fila;
    return c;
  }
  if (forma == 'f') {
    const uint8_t arco[8] = {0x60, 0x30, 0x18, 0x0C, 0x0C, 0x18, 0x30, 0x60};
    return arco[i];
  }
  int desde = (8 - alto) / 2, hasta = desde + alto - 1;
  if ((i == 0 || i == 7) && alto >= 4) desde++, hasta--;  // esquinas redondeadas
  uint8_t c = 0;
  for (int fila = desde; fila <= hasta; fila++) c |= 1 << fila;  // bit 0 = fila de arriba
  return c;
}

void dibujarOjos(int alto, int mirada, char forma) {
  int clave = alto * 1000 + (mirada + 10) * 10 + (forma == 'f') + 2 * (forma == 'm');
  if (clave == ojosEnPantalla) return;
  ojosEnPantalla = clave;
  textoEnPantalla[0] = 0;
  MD_MAX72XX *m = pantalla.getGraphicObject();
  m->control(MD_MAX72XX::UPDATE, MD_MAX72XX::OFF);
  m->clear();
  const int ojos[2] = {4, 20};  // columna donde empieza cada ojo, contando desde la izquierda
  for (int ojo : ojos)
    for (int i = 0; i < 8; i++) {
      int columna = 31 - (ojo + mirada + i);  // la 0 es la de la derecha
      uint8_t c = columnaOjo(i, alto, forma, ojo == 4);
      if (DE_CABEZA) {
        columna = 31 - columna;
        uint8_t volteada = 0;
        for (int fila = 0; fila < 8; fila++)
          if (c & (1 << fila)) volteada |= 1 << (7 - fila);
        c = volteada;
      }
      m->setColumn(columna, c);
    }
  m->control(MD_MAX72XX::UPDATE, MD_MAX72XX::ON);
}

void actualizarCara() {
  static uint32_t ultimo = 0, finMovimiento = 0, proximoParpadeo = 3000, proximaMirada = 5000;
  static int mirada = 0, miradaObjetivo = 0;
  uint32_t ahora = millis();
  if (ahora - ultimo < 40) return;
  ultimo = ahora;

  // Al prender el interruptor de las pilas el pico de corriente desconfiguraba la matriz (va a 3,3 V,
  // su mínimo): se apagaban 2 paneles y el resto mostraba basura, y no se recuperaba porque se
  // configuraba solo al arrancar. Ahora se reconfigura y se redibuja cada segundo, y en el acto
  // cuando aparece el voltaje de las pilas (alguien prendió el interruptor)
  static uint32_t ultimaConfig = 0;
  static bool habiaPilas = false;
  bool hayPilas = voltajePilas > VOLTAJE_HAY_PILAS;
  if (ahora - ultimaConfig > 1000 || hayPilas != habiaPilas) {
    if (hayPilas != habiaPilas) delay(50);  // que pase el pico antes de reconfigurar
    habiaPilas = hayPilas;
    ultimaConfig = ahora;
    MD_MAX72XX *m = pantalla.getGraphicObject();
    m->control(MD_MAX72XX::SHUTDOWN, MD_MAX72XX::OFF);
    m->control(MD_MAX72XX::TEST, MD_MAX72XX::OFF);
    m->control(MD_MAX72XX::DECODE, MD_MAX72XX::OFF);
    m->control(MD_MAX72XX::SCANLIMIT, 7);
    m->control(MD_MAX72XX::INTENSITY, BRILLO);
    m->update();  // vuelve a mandar el dibujo completo
  }

  // Mientras avanza o gira pone cara molesta (antes mostraba la velocidad o los grados) y la deja un
  // momento al terminar
  Tarea t = tarea;
  if (t != NINGUNA) finMovimiento = ahora;
  if (t != NINGUNA || ahora - finMovimiento < 1500) {
    dibujarOjos(8, 0, 'm');
    return;
  }

  if (pilasBajas) {  // aviso en la cara: hay que cargar las pilas
    mostrarTexto("BAT");
    return;
  }
  // Sin conexión con la PC antes se mostraban ojos cerrados (una línea quieta) y parecía que la matriz
  // no andaba: ahora los ojos parpadean y miran igual, conectado o no
  if ((int32_t)(felizHasta - ahora) > 0) {
    dibujarOjos(8, 0, 'f');
    return;
  }
  // Mira de reojo de vez en cuando
  if ((int32_t)(ahora - proximaMirada) >= 0) {
    const int opciones[] = {-3, 0, 0, 3};
    miradaObjetivo = opciones[random(4)];
    proximaMirada = ahora + random(2500, 6000);
  }
  if (mirada != miradaObjetivo) mirada += mirada < miradaObjetivo ? 1 : -1;
  // Parpadeo: se cierra y se abre en 200 ms
  int alto = 8;
  int32_t fase = ahora - proximoParpadeo;
  if (fase >= 0) {
    const int pasos[] = {6, 3, 1, 3, 6};
    if (fase < 200) alto = pasos[fase / 40];
    else proximoParpadeo = ahora + random(800, 2200);  // parpadea cada 0,8 a 2,2 s
  }
  dibujarOjos(alto, mirada, 'n');
}

// ====================== Monitor serial ======================

void imprimirImu() {
  if (millis() - ultimoImu < 200) return;
  ultimoImu = millis();
  portENTER_CRITICAL(&candado);
  Medicion m = ultima;
  portEXIT_CRITICAL(&candado);
  Serial.printf("adelante %+6.2f m/s²  derecha %+6.2f m/s²  giro %+7.1f °/s  pilas %.2f V  motores %4.0f mA\n",
                m.acel, m.acel_lat, m.giro, m.voltaje, m.corriente * 1000);
}

void leerTeclado() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      lineaActual.trim();
      if (lineaActual.equalsIgnoreCase("imu")) {
        mostrarImu = !mostrarImu;
        Serial.println(mostrarImu ? "\nMostrando los sensores. Escribe \"imu\" otra vez para ocultarlos."
                                  : "\nSensores ocultos.");
#if ENVIAR_AUDIO
      } else if (lineaActual.equalsIgnoreCase("nivel")) {
        mostrarNivel = !mostrarNivel;
        Serial.println(mostrarNivel ? "\nMostrando el volumen. Escribe \"nivel\" otra vez para ocultarlo."
                                    : "\nVolumen oculto.");
#endif
      } else if (lineaActual.equalsIgnoreCase("wifi lista")) {
        cargarRedes();
        Serial.printf("\nREDES CONOCIDAS: %d\n", cantidadRedes);
        for (int i = 0; i < cantidadRedes; i++) Serial.printf("RED: %s\n", redNombre[i].c_str());
        Serial.printf("WIFI ACTUAL: %s\n", WiFi.status() == WL_CONNECTED ? WiFi.SSID().c_str() : "(sin conexión)");
      } else if (lineaActual.equalsIgnoreCase("wifi borrar")) {
        Preferences mem;
        mem.begin("wifi", false);
        mem.clear();
        mem.end();
        Serial.println("\nREDES BORRADAS (queda solo la de secrets.h, si hay)");
      } else if (lineaActual.startsWith("wifi ") && lineaActual.indexOf('|') > 5) {
        // "wifi Nombre de la red|clave": el nombre puede tener espacios; la clave va después de la primera |
        int barra = lineaActual.indexOf('|');
        String nombre = lineaActual.substring(5, barra), clave = lineaActual.substring(barra + 1);
        nombre.trim();
        guardarRed(nombre, clave);
        Serial.printf("\nWIFI GUARDADA: %s. Reinicio para conectarme...\n", nombre.c_str());
        delay(300);
        ESP.restart();
      } else if (lineaActual.startsWith("mover ")) {
        // Prueba sin la PC: "mover avanzar 0.5", "mover retroceder 0.3", "mover girar 90", "mover detener"
        char accion[16] = "";
        float parametro = 0;
        sscanf(lineaActual.c_str() + 6, "%15s %f", accion, &parametro);
        Serial.println();
        describirAccion(accion, parametro);
        portENTER_CRITICAL(&candado);
        strlcpy(orden.accion, accion, sizeof(orden.accion));
        orden.parametro = parametro;
        orden.nueva = true;
        portEXIT_CRITICAL(&candado);
        ordenLocal = true;
      } else if (lineaActual.length() > 0) {
        Serial.println();
        enviarTexto(lineaActual);
      }
      lineaActual = "";
    } else if (c == 8 || c == 127) {  // borrar (backspace)
      if (lineaActual.length() > 0) {
        lineaActual.remove(lineaActual.length() - 1);
        Serial.print("\b \b");
      }
    } else {
      lineaActual += c;
      Serial.print(c);  // eco: muestra lo que vas escribiendo
    }
  }
}

// ====================== Arranque y bucle ======================

void setup() {
  Serial.begin(115200);
  delay(500);
  iniciarMotores();  // primero: que los motores queden quietos pase lo que pase
  iniciarCara();
  iniciarSensores();
  calibrarMpu();

  colaMediciones = xQueueCreate(16, sizeof(Medicion));
  // Prioridad más alta que el bucle (WiFi, audio): el control no se atrasa aunque la red se trabe
  xTaskCreatePinnedToCore(tareaControl, "control", 4096, nullptr, 3, nullptr, 1);

  pantalla.displayClear();  // la matriz apagada mientras arranca el WiFi (ver conectarWifi)
  conectarWifi();
#if ENVIAR_AUDIO
  iniciarMicrofono();
#else
  Serial.println("Sin micrófono en el robot: háblale por el de la PC (iniciar.bat pc)");
#endif

  separarUrl(SERVIDOR_URL, hostCerebro, puertoCerebro);  // por si no se anuncia (cerebro viejo)
  if (buscarCerebro(4000)) {
    Serial.printf("Encontré el cerebro en la red: %s\n", hostCerebro.c_str());
  } else {
    Serial.println("El cerebro no se anunció: uso la dirección de secrets.h");
  }
  Serial.printf("Servidor: ws://%s:%u/ws\n", hostCerebro.c_str(), puertoCerebro);
  ws.begin(hostCerebro, puertoCerebro, "/ws");
  ws.onEvent(alEventoWs);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(15000, 3000, 2);  // detecta si el servidor dejó de responder

  Serial.println("Escribe un comando y presiona Enter (\"imu\" muestra los sensores)");
}

void loop() {
  ws.loop();
  // Sin conexión hace rato: puede que la PC haya cambiado de dirección. Se escucha el anuncio otra vez
  static uint32_t ultimaBusqueda = 0;
  if (!conectado && millis() - ultimaBusqueda > 10000) {
    ultimaBusqueda = millis();
    String antes = hostCerebro;
    if (buscarCerebro(1500) && hostCerebro != antes) {
      Serial.printf("\nEl cerebro cambió de dirección: ahora %s\n", hostCerebro.c_str());
      ws.disconnect();
      ws.begin(hostCerebro, puertoCerebro, "/ws");
    }
  }
  leerTeclado();

  Medicion m;
  while (xQueueReceive(colaMediciones, &m, 0) == pdTRUE) {
    if (conectado) enviarMedicion(m);
  }
  if (mostrarImu) imprimirImu();
  actualizarCara();

#if ENVIAR_AUDIO
  // Se lee siempre (aunque no haya servidor) para que "nivel" funcione y el audio no quede viejo
  size_t n = leerAudio();
  if (n > 0) {
    if (conectado) ws.sendBIN((uint8_t *)pcm, n * sizeof(int16_t));
    if (mostrarNivel) imprimirNivel(n);
  }
#else
  delay(2);
#endif
}
