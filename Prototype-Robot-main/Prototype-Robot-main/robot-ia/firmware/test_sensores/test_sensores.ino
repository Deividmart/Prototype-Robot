// Prueba del MPU6050 (acelerómetro y giroscopio) y del INA219 (voltaje y corriente de las pilas).
// Los dos van por I2C en los mismos cables: SDA -> D21, SCL -> D22.
#include <Wire.h>

const int PIN_SDA = 21;
const int PIN_SCL = 22;
const uint8_t DIR_MPU = 0x68;  // 0x69 si el pin AD0 del MPU está en alto
const uint8_t DIR_INA = 0x40;
const float SHUNT_OHM = 0.1;  // la resistencia R100 del módulo INA219
const float G = 9.81;

bool hayMpu = false;
bool hayIna = false;

bool existe(uint8_t dir) {
  Wire.beginTransmission(dir);
  return Wire.endTransmission() == 0;
}

void escribir(uint8_t dir, uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  Wire.write(valor);
  Wire.endTransmission();
}

bool leer(uint8_t dir, uint8_t reg, uint8_t *datos, size_t n) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(dir, n) != n) return false;
  for (size_t i = 0; i < n; i++) datos[i] = Wire.read();
  return true;
}

int16_t leer16(uint8_t dir, uint8_t reg) {
  uint8_t b[2] = {0, 0};
  leer(dir, reg, b, 2);
  return (int16_t)((b[0] << 8) | b[1]);
}

void buscarDispositivos() {
  Serial.println("Buscando dispositivos I2C...");
  int encontrados = 0;
  for (uint8_t dir = 1; dir < 127; dir++) {
    if (existe(dir)) {
      Serial.printf("   encontrado en 0x%02X%s\n", dir,
                    dir == 0x68 || dir == 0x69 ? " (MPU6050)" : dir >= 0x40 && dir <= 0x4F ? " (INA219)" : "");
      encontrados++;
    }
  }
  if (encontrados == 0) {
    Serial.println("   NADA. Revisa SDA -> D21, SCL -> D22, VCC -> 3V3 y GND de los dos módulos.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Wire.begin(PIN_SDA, PIN_SCL);
  buscarDispositivos();

  hayMpu = existe(DIR_MPU);
  if (hayMpu) {
    escribir(DIR_MPU, 0x6B, 0x00);  // despertar (arranca dormido)
    escribir(DIR_MPU, 0x1A, 0x03);  // filtro pasa bajos de ~44 Hz: quita la vibración de los motores
    escribir(DIR_MPU, 0x1B, 0x00);  // giroscopio: ±250 °/s
    escribir(DIR_MPU, 0x1C, 0x00);  // acelerómetro: ±2 g
    uint8_t quien = 0;
    leer(DIR_MPU, 0x75, &quien, 1);
    Serial.printf("MPU6050 OK (WHO_AM_I = 0x%02X%s)\n", quien, quien == 0x68 ? "" : ", es un clon: debería funcionar igual");
  } else {
    Serial.println("AVISO: no encuentro el MPU6050 en 0x68.");
  }

  hayIna = existe(DIR_INA);
  if (hayIna) {
    escribir(DIR_INA, 0x00, 0x80);  // reinicio a la configuración de fábrica (hasta 32 V y 3,2 A)
    Serial.println("INA219 OK");
  } else {
    Serial.println("AVISO: no encuentro el INA219 en 0x40.");
  }

  Serial.println("\nInclina el robot y empújalo hacia ADELANTE: el eje que cambie es el de \"adelante\".");
  Serial.println("Gíralo a la DERECHA sobre la mesa: el giro Z debería marcar un número (anota el signo).\n");
}

void loop() {
  if (hayMpu) {
    float ax = leer16(DIR_MPU, 0x3B) / 16384.0 * G;
    float ay = leer16(DIR_MPU, 0x3D) / 16384.0 * G;
    float az = leer16(DIR_MPU, 0x3F) / 16384.0 * G;
    float gx = leer16(DIR_MPU, 0x43) / 131.0;
    float gy = leer16(DIR_MPU, 0x45) / 131.0;
    float gz = leer16(DIR_MPU, 0x47) / 131.0;
    Serial.printf("acel X %6.2f Y %6.2f Z %6.2f m/s² | giro X %7.1f Y %7.1f Z %7.1f °/s", ax, ay, az, gx, gy, gz);
  }
  if (hayIna) {
    float shunt = leer16(DIR_INA, 0x01) * 0.00001;          // V, de a 10 µV
    float bus = ((uint16_t)leer16(DIR_INA, 0x02) >> 3) * 0.004;  // V, de a 4 mV
    Serial.printf(" | pilas %5.2f V, %6.1f mA", bus + shunt, shunt / SHUNT_OHM * 1000);
  }
  Serial.println();
  delay(200);
}
