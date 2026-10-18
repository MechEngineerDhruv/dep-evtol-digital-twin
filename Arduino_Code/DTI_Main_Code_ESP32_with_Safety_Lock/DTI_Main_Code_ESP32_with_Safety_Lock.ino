#include <Wire.h>
#include <Adafruit_INA219.h>
#include <HX711_ADC.h>
#include <ArduinoJson.h>

const int HX711_dout = 4;
const int HX711_sck = 5; 
const int ESC_PIN = 18;  

HX711_ADC LoadCell(HX711_dout, HX711_sck);
Adafruit_INA219 ina219;

int currentPWM = 1000; 

void setup() {
  Serial.begin(115200); delay(10);
  
  if (!ina219.begin()) {
    Serial.println("Failed to find INA219 chip");
    while (1) { delay(10); }
  }

  LoadCell.begin();
  LoadCell.start(2000);
  LoadCell.setCalFactor(1.0); // Insert your actual calibration factor here
  
  ledcSetup(0, 50, 16); 
  ledcAttachPin(ESC_PIN, 0);
  ledcWrite(0, 3276); // Send minimum throttle to arm ESC
  delay(3000); 
}

void loop() {
  LoadCell.update();
  float thrust_g = LoadCell.getData();
  float voltage_V = ina219.getBusVoltage_V();
  float current_mA = ina219.getCurrent_mA();
  float power_W = ina219.getPower_mW() / 1000.0;

  StaticJsonDocument<200> doc;
  doc["time"] = millis();
  doc["thrust_g"] = thrust_g;
  doc["voltage"] = voltage_V;
  doc["current_A"] = current_mA / 1000.0;
  doc["power_W"] = power_W;
  doc["pwm"] = currentPWM;

  serializeJson(doc, Serial);
  Serial.println();

  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    int newPWM = command.toInt();
    
    // HARDWARE SAFETY LOCK: Max 1350 to protect INA219 from burning out
    if (newPWM >= 1000 && newPWM <= 1350) {
      currentPWM = newPWM;
      int dutyCycle = map(currentPWM, 1000, 2000, 3276, 6553);
      ledcWrite(0, dutyCycle); 
    }
  }
  delay(20); 
}