#include <Wire.h>
#include <Adafruit_INA219.h>
#include <HX711_ADC.h>
#include <ArduinoJson.h>
#include <Servo.h> // Replaces ledc commands for ESP8266

// ESP8266 NodeMCU Pins
const int HX711_dout = 12; // D6
const int HX711_sck = 14;  // D5
const int ESC_PIN = 2;     // D4

// Objects
HX711_ADC LoadCell(HX711_dout, HX711_sck);
Adafruit_INA219 ina219;
Servo esc;

// Variables
long t;
int currentPWM = 1000; // 1000 = Off, 2000 = Max

void setup() {
  Serial.begin(115200); delay(10);
  
  // Initialize INA219 (Defaults to SDA=D2/GPIO4, SCL=D1/GPIO5)
  if (!ina219.begin()) {
    Serial.println("Failed to find INA219 chip");
    while (1) { delay(10); }
  }

  // Initialize HX711
  LoadCell.begin();
  LoadCell.start(2000);
  LoadCell.setCalFactor(<YOUR_CALIBRATION_FACTOR>); // Replace this!
  
  // Initialize ESC
  esc.attach(ESC_PIN, 1000, 2000); // Attach ESC to pin D4
  esc.writeMicroseconds(1000);     // Send minimum throttle to arm ESC
  delay(3000);                     // Wait for ESC to arm
}

void loop() {
  // 1. Read Sensors
  LoadCell.update();
  float thrust_g = LoadCell.getData();
  float voltage_V = ina219.getBusVoltage_V();
  float current_mA = ina219.getCurrent_mA();
  float power_W = ina219.getPower_mW() / 1000.0;

  // 2. Format JSON Payload (ESP8266 has enough RAM for this)
  StaticJsonDocument<200> doc;
  doc["time"] = millis();
  doc["thrust_g"] = thrust_g;
  doc["voltage"] = voltage_V;
  doc["current_A"] = current_mA / 1000.0;
  doc["power_W"] = power_W;
  doc["pwm"] = currentPWM;

  // 3. Transmit Data
  serializeJson(doc, Serial);
  Serial.println();

  // 4. Read incoming commands from Python (Bidirectional Loop)
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    int newPWM = command.toInt();
    if (newPWM >= 1000 && newPWM <= 2000) {
      currentPWM = newPWM;
      esc.writeMicroseconds(currentPWM); // Direct microsecond control for ESP8266
    }
  }

  delay(20); // ~50Hz sampling rate
}