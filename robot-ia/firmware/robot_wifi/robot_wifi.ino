// El ESP32 se conecta al WiFi y le manda comandos de texto al servidor de la PC.
// Por ahora el texto se escribe en el monitor serial; más adelante va a ser audio del INMP441.
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "secrets.h"

void conectarWifi() {
  Serial.printf("Conectando a WiFi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - inicio > 20000) {
      Serial.println("\nERROR: no se pudo conectar. Revisá nombre/contraseña y que la red sea de 2.4 GHz.");
      return;
    }
    Serial.print('.');
    delay(500);
  }
  Serial.printf("\nConectado. IP del ESP32: %s\n", WiFi.localIP().toString().c_str());
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

void enviarComando(const String &texto) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Sin WiFi, reintentando conexión...");
    conectarWifi();
    if (WiFi.status() != WL_CONNECTED) return;
  }

  HTTPClient http;
  http.begin(String(SERVIDOR_URL) + "/texto");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(30000);

  JsonDocument pedido;
  pedido["texto"] = texto;
  String cuerpo;
  serializeJson(pedido, cuerpo);

  unsigned long t0 = millis();
  int codigo = http.POST(cuerpo);
  unsigned long demora = millis() - t0;

  if (codigo != 200) {
    Serial.printf("ERROR HTTP %d: %s\n", codigo, codigo < 0 ? http.errorToString(codigo).c_str() : http.getString().c_str());
    http.end();
    return;
  }

  JsonDocument respuesta;
  DeserializationError err = deserializeJson(respuesta, http.getString());
  http.end();
  if (err) {
    Serial.printf("ERROR leyendo JSON: %s\n", err.c_str());
    return;
  }

  const char *accion = respuesta["accion"]["accion"] | "detener";
  float parametro = respuesta["accion"]["parametro"] | 0.0f;
  const char *frase = respuesta["accion"]["respuesta_hablada"] | "";

  Serial.printf("Robot dice: \"%s\"  (%lu ms)\n", frase, demora);
  ejecutarAccion(accion, parametro);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  conectarWifi();
  Serial.print("\nEscribí un comando y apretá Enter (ej: avanza dos metros)\n> ");
}

String lineaActual;

void loop() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\r' || c == '\n') {
      lineaActual.trim();
      if (lineaActual.length() > 0) {
        Serial.println();
        enviarComando(lineaActual);
        Serial.print("\n> ");
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
