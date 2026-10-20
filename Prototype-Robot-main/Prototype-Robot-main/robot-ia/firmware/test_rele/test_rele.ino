// Prueba del módulo relé: lo prende y lo apaga cada segundo.
const int PIN_RELE = 13;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELE, OUTPUT);
  Serial.println("Prueba de rele en GPIO 13");
}

void loop() {
  digitalWrite(PIN_RELE, HIGH);
  Serial.println("GPIO 13 = HIGH");
  delay(1000);
  digitalWrite(PIN_RELE, LOW);
  Serial.println("GPIO 13 = LOW");
  delay(1000);
}
