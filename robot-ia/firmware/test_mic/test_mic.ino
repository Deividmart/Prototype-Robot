// Prueba del micrófono INMP441: muestra el nivel de sonido como una barra por serial.
#include <ESP_I2S.h>

const int PIN_SCK = 32;
const int PIN_WS = 25;
const int PIN_SD = 33;

const int SAMPLE_RATE = 16000;
const int BLOQUE = 512;

I2SClass i2s;
int32_t muestras[BLOQUE];

void setup() {
  Serial.begin(115200);
  delay(1000);

  i2s.setPins(PIN_SCK, PIN_WS, -1, PIN_SD);
  if (!i2s.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("ERROR: no se pudo iniciar I2S");
    while (true) delay(1000);
  }
  Serial.println("Microfono listo. Habla cerca del INMP441...");
}

void loop() {
  size_t leidos = i2s.readBytes((char *)muestras, sizeof(muestras)) / sizeof(int32_t);
  if (leidos == 0) return;

  // El INMP441 entrega 24 bits alineados a la izquierda dentro de 32 bits
  int32_t pico = 0;
  for (size_t i = 0; i < leidos; i++) {
    int32_t v = abs(muestras[i] >> 8);
    if (v > pico) pico = v;
  }

  int largo = map(constrain(pico, 0, 2000000), 0, 2000000, 0, 50);
  Serial.printf("%8ld |", (long)pico);
  for (int i = 0; i < largo; i++) Serial.print('#');
  Serial.println();
}
