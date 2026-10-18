// Include necessary libraries for I2C communication, sensors, and JSON formatting
#include <Wire.h>
#include <Adafruit_INA219.h>
#include <HX711_ADC.h>
#include <ArduinoJson.h>

// Define the ESP32 GPIO pins used for the HX711 Load Cell Amplifier
const int HX711_dout = 4;
const int HX711_sck = 5; 

// Define the ESP32 GPIO pin used to send the PWM signal to the 30A ESC
const int ESC_PIN = 18;  

// Initialize the Load Cell and INA219 sensor objects
HX711_ADC LoadCell(HX711_dout, HX711_sck);
Adafruit_INA219 ina219;

// Global variable to track the current PWM signal (1000 = motor off, 2000 = full throttle)
int currentPWM = 1000; 

void setup() {
  Serial.begin(115200); 
  delay(10);
  
  if (!ina219.begin()) {
    Serial.println("Failed to find INA219 chip");
    while (1) { delay(10); }
  }

  // Initialize and wake up the HX711 load cell amplifier
  LoadCell.begin();
  LoadCell.start(2000); // Allow 2000ms for the tare operation to stabilize
  LoadCell.setCalFactor(1.0); 
  
  // ESP32 Core v3.x.x PWM API: Attach pin directly with 50Hz frequency, 16-bit resolution
  ledcAttach(ESC_PIN, 50, 16); 
  ledcWrite(ESC_PIN, 3276); // Send 1000us minimum throttle pulse to arm the ESC
  delay(3000); 
}

void loop() {
  // 1. ACQUIRE PHYSICAL TELEMETRY
  LoadCell.update();
  float thrust_g = LoadCell.getData();
  float voltage_V = ina219.getBusVoltage_V();
  
  // 2. APPLY HARDWARE MODIFICATION SCALING (0.01 Ohm R010 Shunt)
  // Multiply raw current reading by 10.0 to compensate for 10x smaller shunt resistance
  float current_mA_raw = ina219.getCurrent_mA();
  float current_A_actual = (current_mA_raw * 10.0) / 1000.0; 
  float power_W_actual = voltage_V * current_A_actual;

  // 3. PACKAGE DATA FOR DIGITAL TWIN (UPLINK JSON)
  StaticJsonDocument<200> doc;
  doc["time"] = millis();                
  doc["thrust_g"] = thrust_g;            
  doc["voltage"] = voltage_V;            
  doc["current_A"] = current_A_actual;   
  doc["power_W"] = power_W_actual;       
  doc["pwm"] = currentPWM;               

  serializeJson(doc, Serial);
  Serial.println();

  // 4. PROCESS INCOMING COMMANDS (DOWNLINK JSON)
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n'); 
    StaticJsonDocument<200> cmdDoc;
    DeserializationError error = deserializeJson(cmdDoc, command);
    
    if (!error) {
      // Update Calibration Factor dynamically
      if (cmdDoc.containsKey("cal")) {
        float newCal = cmdDoc["cal"];
        LoadCell.setCalFactor(newCal);
      }
      
      // Execute Tare Command (Safety Lock: Only tare if motor is disarmed at 1000 PWM)
      if (cmdDoc.containsKey("tare") && cmdDoc["tare"] == 1) {
        if (currentPWM == 1000) {
          LoadCell.tare();
        }
      }
      
      // Update Motor PWM Duty Cycle
      if (cmdDoc.containsKey("pwm")) {
        int newPWM = cmdDoc["pwm"];
        if (newPWM >= 1000 && newPWM <= 2000) {
          currentPWM = newPWM;
          int dutyCycle = map(currentPWM, 1000, 2000, 3276, 6553);
          ledcWrite(ESC_PIN, dutyCycle); 
        }
      }
    }
  }
  
  delay(20); // ~50Hz telemetry loop
}