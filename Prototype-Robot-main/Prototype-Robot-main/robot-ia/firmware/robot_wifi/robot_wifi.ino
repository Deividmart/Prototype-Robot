// Firmware de Aries: maneja los motores y los sensores, manda las mediciones a la PC por WiFi
// (WebSocket, 50 por segundo) y ejecuta las acciones que le devuelve el cerebro.
// También manda el audio del micrófono (si ENVIAR_AUDIO = 1) y acepta comandos escritos en el
// monitor serial.
//
// El robot no tiene encoders: la distancia se estima con el modelo del motor (voltaje y corriente
// del INA219) y los giros se miden con el giroscopio del MPU6050. fisica.py hace las mismas cuentas.
//
// La cara son 4 matrices 8x8 (MAX7219, módulo FC16): ojos que parpadean cuando espera, ojos
// cerrados si no hay conexión con la PC, la velocidad en vivo al avanzar y los grados al girar.
#include <WiFi.h>
#include <Wire.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <MD_Parola.h>
#include <MD_MAX72xx.h>
#include "secrets.h"

// 1 = manda el audio del INMP441 a la PC. 0 = sin micrófono: se le habla por el de la PC (iniciar.bat pc)
#ifndef ENVIAR_AUDIO
#define ENVIAR_AUDIO 1
#endif
#if ENVIAR_AUDIO
#include <ESP_I2S.h>
#endif

// --- Pines (ENSAMBLAJE.md) ---
const int PIN_PWMA = 19, PIN_AIN1 = 18, PIN_AIN2 = 5;  // motor A = rueda izquierda
const int PIN_PWMB = 17, PIN_BIN1 = 16, PIN_BIN2 = 4;  // motor B = rueda derecha
const int PIN_STBY = 23;
const int PIN_SDA = 21, PIN_SCL = 22;
const int PIN_SCK = 32, PIN_WS = 25, PIN_SD = 33;
const int PIN_VDD_MIC = 27;  // el micrófono consume ~1.4 mA: lo alimenta un pin
const int PIN_LR_MIC = 26;   // L/R del micrófono en 0 V (canal izquierdo): así todo el mic va a la fila al aire
const int PIN_DIN = 13, PIN_CLK = 14, PIN_CS = 15;  // matrices (SPI por software: 18/19/23 son de los motores)

const uint8_t DIR_MPU = 0x68, DIR_INA = 0x40;

// --- Robot y motor: los mismos números que fisica.py ---
const float RADIO_RUEDA = 0.0305;      // m
const float R_MOTOR = 7.5;             // ohm
const float K_MOTOR = 0.287;           // V·s/rad
// Calibrado 19/10/2026 (pilas a ~4,1 V): pidieron 0,3 m y anduvo 0,55; pidieron 1,67 y anduvo 1,30.
// Encaja con real = 1,22 × modelo + 0,18 m: el factor (igual en fisica.py) y lo que sigue de largo al frenar
const float AJUSTE_DISTANCIA = 1.22;
const float DISTANCIA_FRENADO = 0.18;  // m: corta antes, porque después de frenar todavía avanza esto
const float R_SHUNT = 0.1;             // ohm, la resistencia R100 del INA219
const float G = 9.81;

// Cómo va montado el MPU6050 (ENSAMBLAJE.md): X hacia adelante, Y hacia la izquierda, Z hacia arriba.
// Con el comando "imu" del monitor serial se comprueba; si un signo sale al revés, se cambia acá.
const float SIGNO_ADELANTE = 1;
const float SIGNO_DERECHA = -1;
const float SIGNO_GIRO = -1;  // el giroscopio da + al girar a la izquierda; Aries usa + = derecha

// --- Control ---
const int PWM_CRUCERO = 200;
const int PWM_GIRO = 170;
const int PWM_LENTO = 130;              // cerca del final, para no pasarse
const float CORRECCION_RECTA = 3;       // PWM por cada grado desviado: el giroscopio lo mantiene derecho
                                        // (con 6 el robot real serpenteaba)
const int CORRECCION_MAX = 60;          // tope: si una rueda patina, la otra no se para y el robot no pivotea
const float FRENO_LENTO_M = 0.10;
const float FRENO_LENTO_GRADOS = 25;
const float ANTICIPO_GIRO_S = 0.02;     // al frenar sigue girando un poco: corta un poco antes
const uint32_t TIEMPO_MAX_MS = 10000;   // ninguna acción dura más que esto, por seguridad
const uint32_t FRENO_MS = 500;          // al parar frena en corto y después deja las ruedas libres
const uint32_t PERIODO_CONTROL_MS = 10; // 100 veces por segundo
const int CICLOS_POR_MEDICION = 2;      // 50 mediciones por segundo a la PC

// --- Audio ---
const int TASA = 16000;
const int MUESTRAS = 512;  // 32 ms por paquete
// El INMP441 entrega 24 bits dentro de 32; al pasar a 16 bits este corrimiento define la ganancia:
// cada 1 menos duplica el volumen. Se calibra con el comando "nivel" (ver INSTALACION.md).
const int CORRIMIENTO = 12;

// --- Cara ---
const int MATRICES = 4;
const int BRILLO = 1;  // de 0 a 15: las matrices van a 3,3 V y con más brillo bajan las pilas y parpadean

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
uint32_t desde = 0;
uint32_t frenoHasta = 0;
int pwmIzq = 0, pwmDer = 0;

void parar() {
  tarea = NINGUNA;
  pwmIzq = pwmDer = 0;
  frenoHasta = millis() + FRENO_MS;
}

void empezar(const char *accion, float parametro) {
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
  if (tarea != NINGUNA && (!conectado || ahora - desde > TIEMPO_MAX_MS)) parar();

  if (tarea == RECTA) {
    float falta = objetivo - avance;
    if (falta <= 0) {
      parar();
    } else {
      // Desviado a la derecha (rumbo > 0): frena la izquierda y apura la derecha, vaya adelante o atrás
      int base = (falta < FRENO_LENTO_M ? PWM_LENTO : PWM_CRUCERO) * sentido;
      float correccion = constrain(CORRECCION_RECTA * rumbo, -CORRECCION_MAX, CORRECCION_MAX);
      pwmIzq = constrain((int)(base - correccion), -255, 255);
      pwmDer = constrain((int)(base + correccion), -255, 255);
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

  if (tarea != NINGUNA) {
    motor(0, pwmIzq);
    motor(1, pwmDer);
  } else if ((int32_t)(frenoHasta - ahora) > 0) {
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

void conectarWifi() {
  Serial.printf("Conectando a WiFi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t inicio = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - inicio > 20000) {
      Serial.println("\nERROR: no se pudo conectar. Revisa nombre/contraseña y que la red sea de 2.4 GHz.");
      return;
    }
    Serial.print('.');
    delay(500);
  }
  Serial.printf("\nConectado. IP del ESP32: %s\n", WiFi.localIP().toString().c_str());
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
      if (!esMovimiento(accion)) felizHasta = millis() + 2000;  // contesta algo: pone ojos contentos
      portENTER_CRITICAL(&candado);
      strlcpy(orden.accion, accion, sizeof(orden.accion));
      orden.parametro = parametro;
      orden.nueva = true;
      portEXIT_CRITICAL(&candado);
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
  pantalla.print("ARIES");
}

void mostrarTexto(const char *texto) {
  if (strcmp(texto, textoEnPantalla) == 0) return;
  strlcpy(textoEnPantalla, texto, sizeof(textoEnPantalla));
  ojosEnPantalla = -1;
  pantalla.print(texto);
}

// Un ojo de 8 columnas: 'n' normal (alto = filas encendidas, para parpadear), 'f' contento (^)
uint8_t columnaOjo(int i, int alto, char forma) {
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
  int clave = alto * 1000 + (mirada + 10) * 10 + (forma == 'f');
  if (clave == ojosEnPantalla) return;
  ojosEnPantalla = clave;
  textoEnPantalla[0] = 0;
  MD_MAX72XX *m = pantalla.getGraphicObject();
  m->control(MD_MAX72XX::UPDATE, MD_MAX72XX::OFF);
  m->clear();
  const int ojos[2] = {4, 20};  // columna donde empieza cada ojo, contando desde la izquierda
  for (int ojo : ojos)
    for (int i = 0; i < 8; i++) m->setColumn(31 - (ojo + mirada + i), columnaOjo(i, alto, forma));  // la 0 es la de la derecha
  m->control(MD_MAX72XX::UPDATE, MD_MAX72XX::ON);
}

void actualizarCara() {
  static uint32_t ultimo = 0, finMovimiento = 0, proximoParpadeo = 3000, proximaMirada = 5000;
  static int mirada = 0, miradaObjetivo = 0;
  static char texto[12] = "";
  uint32_t ahora = millis();
  if (ahora - ultimo < 40) return;
  ultimo = ahora;

  Tarea t = tarea;
  if (t != NINGUNA) {
    // Muestra la medición en vivo, 5 veces por segundo (más rápido no se alcanza a leer)
    static uint32_t ultimoNumero = 0;
    if (ahora - ultimoNumero >= 200 || !texto[0]) {
      ultimoNumero = ahora;
      if (t == RECTA) {
        snprintf(texto, sizeof(texto), "%.2f", velocidad);  // m/s
        char *punto = strchr(texto, '.');
        if (punto) *punto = ',';
      } else {
        snprintf(texto, sizeof(texto), "%d\xB0", (int)roundf(fabs(rumbo)));
      }
    }
  }
  if (t != NINGUNA) finMovimiento = ahora;
  if (t != NINGUNA || ahora - finMovimiento < 1500) {  // al terminar deja el último número un rato
    if (texto[0]) {
      mostrarTexto(texto);
      return;
    }
  }
  texto[0] = '\0';

  if (!conectado) {  // dormido hasta que la PC se conecte
    dibujarOjos(2, 0, 'n');
    return;
  }
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
    else proximoParpadeo = ahora + random(2000, 5000);
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

  conectarWifi();
#if ENVIAR_AUDIO
  iniciarMicrofono();
#else
  Serial.println("Sin micrófono en el robot: háblale por el de la PC (iniciar.bat pc)");
#endif

  String host;
  uint16_t puerto;
  separarUrl(SERVIDOR_URL, host, puerto);
  Serial.printf("Servidor: ws://%s:%u/ws\n", host.c_str(), puerto);
  ws.begin(host, puerto, "/ws");
  ws.onEvent(alEventoWs);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(15000, 3000, 2);  // detecta si el servidor dejó de responder

  Serial.println("Escribe un comando y presiona Enter (\"imu\" muestra los sensores)");
}

void loop() {
  ws.loop();
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
