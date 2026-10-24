// Prueba de motores (TB6612) y encoders: mueve cada rueda adelante y atrás y cuenta las ranuras.
// Levanta el robot para que las ruedas giren en el aire. Escribe cualquier cosa + Enter para repetir.

// TB6612: motor A = rueda izquierda, motor B = rueda derecha
const int PIN_PWMA = 19;
const int PIN_AIN1 = 18;
const int PIN_AIN2 = 5;
const int PIN_PWMB = 17;  // TX2
const int PIN_BIN1 = 16;  // RX2
const int PIN_BIN2 = 4;
const int PIN_STBY = 23;
// Sensores de ranura (salida D0). 34 y 35 solo sirven de entrada: justo lo que hace falta
const int PIN_ENC_IZQ = 34;
const int PIN_ENC_DER = 35;

const int PWM_PRUEBA = 200;  // de 0 a 255
const int RANURAS_DISCO = 20;

volatile long pulsos[2] = {0, 0};
volatile unsigned long ultimoPulso[2] = {0, 0};

// La salida del sensor rebota un poco en cada borde de ranura: se ignora lo que llega antes de 2 ms
void IRAM_ATTR contar(int lado) {
  unsigned long ahora = micros();
  if (ahora - ultimoPulso[lado] > 2000) {
    pulsos[lado]++;
    ultimoPulso[lado] = ahora;
  }
}
void IRAM_ATTR contarIzq() { contar(0); }
void IRAM_ATTR contarDer() { contar(1); }

// velocidad de -255 (atrás) a 255 (adelante); 0 = freno
void motor(int lado, int velocidad) {
  int in1 = lado == 0 ? PIN_AIN1 : PIN_BIN1;
  int in2 = lado == 0 ? PIN_AIN2 : PIN_BIN2;
  int pwm = lado == 0 ? PIN_PWMA : PIN_PWMB;
  if (velocidad == 0) {
    digitalWrite(in1, HIGH);  // los dos en alto = freno en corto
    digitalWrite(in2, HIGH);
  } else {
    digitalWrite(in1, velocidad > 0 ? HIGH : LOW);
    digitalWrite(in2, velocidad > 0 ? LOW : HIGH);
  }
  ledcWrite(pwm, abs(velocidad));
}

void probar(int lado, int velocidad) {
  const char *nombre = lado == 0 ? "IZQUIERDA" : "DERECHA";
  Serial.printf("\nRueda %s hacia %s...\n", nombre, velocidad > 0 ? "ADELANTE" : "ATRAS");
  long inicio[2] = {pulsos[0], pulsos[1]};
  motor(lado, velocidad);
  delay(2000);
  motor(lado, 0);
  delay(500);

  long propios = pulsos[lado] - inicio[lado];
  long otros = pulsos[1 - lado] - inicio[1 - lado];
  Serial.printf("   encoder %s: %ld ranuras (%.1f vueltas, %.0f rpm)\n", nombre, propios,
                (float)propios / RANURAS_DISCO, propios / (float)RANURAS_DISCO / 2.0f * 60.0f);
  if (propios == 0) {
    Serial.printf("   AVISO: el encoder %s no contó nada. Revisa su D0 -> GPIO %d, VCC -> 3V3 y que el disco pase por la ranura.\n",
                  nombre, lado == 0 ? PIN_ENC_IZQ : PIN_ENC_DER);
  }
  if (otros > 3) {
    Serial.printf("   AVISO: contó el encoder de la OTRA rueda (%ld). ¿Están cruzados los cables D0 de los encoders?\n", otros);
  }
}

void secuencia() {
  digitalWrite(PIN_STBY, HIGH);
  probar(0, PWM_PRUEBA);
  probar(0, -PWM_PRUEBA);
  probar(1, PWM_PRUEBA);
  probar(1, -PWM_PRUEBA);
  digitalWrite(PIN_STBY, LOW);  // driver apagado: las ruedas quedan libres
  Serial.println("\nSi una rueda giró al revés de lo que decía, invierte los 2 cables de ese motor en el TB6612.");
  Serial.println("Si giró la rueda que no era, intercambia los motores (AO1/AO2 <-> BO1/BO2).");
  Serial.println("Escribe algo y presiona Enter para repetir.");
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  int salidas[] = {PIN_AIN1, PIN_AIN2, PIN_BIN1, PIN_BIN2, PIN_STBY};
  for (int pin : salidas) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  ledcAttach(PIN_PWMA, 20000, 8);  // 20 kHz: fuera del rango que se escucha
  ledcAttach(PIN_PWMB, 20000, 8);
  pinMode(PIN_ENC_IZQ, INPUT);
  pinMode(PIN_ENC_DER, INPUT);
  attachInterrupt(PIN_ENC_IZQ, contarIzq, RISING);
  attachInterrupt(PIN_ENC_DER, contarDer, RISING);

  Serial.println("Prueba de motores y encoders. LEVANTA EL ROBOT: las ruedas van a girar.");
  Serial.println("Empieza en 3 segundos...");
  delay(3000);
  secuencia();
}

void loop() {
  if (Serial.available()) {
    while (Serial.available()) Serial.read();
    secuencia();
  }
}
