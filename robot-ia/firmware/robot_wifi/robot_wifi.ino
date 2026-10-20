// Firmware de Aries: se conecta al WiFi, manda el audio del micrófono a la PC por WebSocket
// y ejecuta las acciones que le devuelve (los motores todavía se simulan por serial).
// También acepta comandos escritos en el monitor serial.
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <ESP_I2S.h>
#include "secrets.h"

// 0 = sin micrófono: solo comandos escritos (sirve para probar sin el INMP441 conectado)
#ifndef ENVIAR_AUDIO
#define ENVIAR_AUDIO 1
#endif

const int PIN_SCK = 32;
const int PIN_WS = 25;
const int PIN_SD = 33;
const int PIN_VDD_MIC = 27;  // el pin 3V3 queda tapado en la protoboard; el mic consume ~1.4 mA

const int TASA = 16000;
const int MUESTRAS = 512;  // 32 ms por paquete
// El INMP441 entrega 24 bits dentro de 32; al pasar a 16 bits este corrimiento define la ganancia:
// cada 1 menos duplica el volumen. Con 12, una voz normal a ~30 cm queda entre -35 y -15 dBFS.
// Se calibra con el comando "nivel" del monitor serial (ver INSTALACION.md).
const int CORRIMIENTO = 12;

WebSocketsClient ws;
I2SClass i2s;
int32_t crudo[MUESTRAS];
int16_t pcm[MUESTRAS];
bool conectado = false;
bool mostrarNivel = false;
unsigned long ultimoNivel = 0;
String lineaActual;

void conectarWifi() {
  Serial.printf("Conectando a WiFi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long inicio = millis();
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

// SERVIDOR_URL viene como "http://192.168.80.39:5000"
void separarUrl(const char *url, String &host, uint16_t &puerto) {
  String u(url);
  u.replace("http://", "");
  int barra = u.indexOf('/');
  if (barra >= 0) u = u.substring(0, barra);
  int dosPuntos = u.indexOf(':');
  host = dosPuntos >= 0 ? u.substring(0, dosPuntos) : u;
  puerto = dosPuntos >= 0 ? u.substring(dosPuntos + 1).toInt() : 80;
}

// Reemplaza al control de motores hasta que estén conectados
void ejecutarAccion(const char *accion, float parametro) {
  if (strcmp(accion, "avanzar") == 0) {
    Serial.printf(">> MOTORES: avanzar %.1f m\n", parametro);
  } else if (strcmp(accion, "retroceder") == 0) {
    Serial.printf(">> MOTORES: retroceder %.1f m\n", parametro);
  } else if (strcmp(accion, "girar") == 0) {
    Serial.printf(">> MOTORES: girar %.0f grados (%s)\n", fabs(parametro), parametro >= 0 ? "derecha" : "izquierda");
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
      // Sin servidor el robot no puede recibir "para": se frena solo por seguridad
      if (conectado) {
        Serial.println("\nSe perdió la conexión con el servidor. Freno por seguridad.");
        ejecutarAccion("detener", 0);
      }
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
      const char *frase = respuesta["respuesta_hablada"] | "";
      Serial.printf("\nAries dice: \"%s\"\n", frase);
      ejecutarAccion(accion, parametro);
      Serial.print("> ");
      break;
    }

    default:
      break;
  }
}

void iniciarMicrofono() {
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

// Medio segundo de prueba al arrancar: detecta cables mal puestos sin necesitar el servidor
void probarMicrofono() {
  int32_t minimo = INT32_MAX, maximo = INT32_MIN;
  for (int b = 0; b < 16; b++) {
    size_t n = i2s.readBytes((char *)crudo, sizeof(crudo)) / sizeof(int32_t);
    for (size_t i = 0; i < n; i++) {
      minimo = min(minimo, crudo[i]);
      maximo = max(maximo, crudo[i]);
    }
  }
  if (minimo == maximo && minimo == 0) {
    Serial.println("AVISO: el micrófono no manda nada (todo en 0).");
    Serial.println("       Revisa VDD->D27, SD->D33, SCK->D32, WS->D25 y GND.");
  } else if (minimo == maximo) {
    Serial.printf("AVISO: el micrófono manda siempre el mismo valor (%ld).\n", (long)minimo);
    Serial.println("       Revisa SD->D33, y que GND y L/R estén a tierra.");
  } else {
    Serial.println("Micrófono OK: está mandando sonido. Escribe \"nivel\" para ver el volumen.");
  }
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

void leerTeclado() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      lineaActual.trim();
      if (lineaActual.equalsIgnoreCase("nivel")) {
        mostrarNivel = !mostrarNivel;
        Serial.println(mostrarNivel ? "\nMostrando el volumen. Escribe \"nivel\" otra vez para ocultarlo."
                                    : "\nVolumen oculto.");
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

void setup() {
  Serial.begin(115200);
  delay(1000);
  conectarWifi();

#if ENVIAR_AUDIO
  iniciarMicrofono();
  probarMicrofono();
#else
  Serial.println("Modo sin micrófono: solo comandos escritos");
#endif

  String host;
  uint16_t puerto;
  separarUrl(SERVIDOR_URL, host, puerto);
  Serial.printf("Servidor: ws://%s:%u/ws\n", host.c_str(), puerto);
  ws.begin(host, puerto, "/ws");
  ws.onEvent(alEventoWs);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(15000, 3000, 2);  // detecta si el servidor dejó de responder

  Serial.println("Di \"Hola Aries\" o escribe un comando y presiona Enter");
}

void loop() {
  ws.loop();
  leerTeclado();
#if ENVIAR_AUDIO
  // Se lee siempre (aunque no haya servidor) para que "nivel" funcione y el audio no quede viejo
  size_t n = leerAudio();
  if (n > 0) {
    if (conectado) ws.sendBIN((uint8_t *)pcm, n * sizeof(int16_t));
    if (mostrarNivel) imprimirNivel(n);
  }
#endif
}
