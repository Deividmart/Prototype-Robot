void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("ESP32 arriba y funcionando!");
}

void loop() {
  Serial.println("tic");
  delay(1000);
}
