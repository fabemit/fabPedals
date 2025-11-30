/*
 * fabemit Arduino Pro Micro Sim Pedals
 * -------------------------------------
 * Board Used: 
 * Arduino Pico Micro 32u4 Dev Board.
 *
 * Digital I/O and Analog Pins:

 * D0 (RX): Digital I/O, UART Receive, External Interrupt
 * D1 (TX): Digital I/O, UART Transmit, External Interrupt
 * D2 (SDA): Digital I/O, I²C SDA, External Interrupt
 * D3 (SCL): Digital I/O, I²C SCL, PWM, External Interrupt
 * D4 (A6): Digital I/O, Analog Input A6
 * D5: Digital I/O, PWM
 * D6: Digital I/O, PWM
 * D7: Digital I/O, External Interrupt
 * D8 (A8): Digital I/O, Analog Input A8
 * D9 (A9): Digital I/O, Analog Input A9, PWM
 * D10 (A10): Digital I/O, Analog Input A10, PWM
 * D11: Digital I/O (often associated with MOSI on some ICSP layouts)
 * D12: Digital I/O (often associated with MISO on some ICSP layouts)
 * D13: Digital I/O (often associated with SCK on some ICSP layouts)
 * D14 (MISO): Digital I/O, SPI MISO, PWM
 * D15 (SCK): Digital I/O, SPI SCK
 * D16 (MOSI): Digital I/O, SPI MOSI
 * D18 (A0): Digital I/O, Analog Input A0
 * D19 (A1): Digital I/O, Analog Input A1
 * D20 (A2): Digital I/O, Analog Input A2
 * D21 (A3): Digital I/O, Analog Input A3 
 * Power and Control Pins:
 * VCC: Regulated 5V or 3.3V power output (matches the board's operating voltage)
 * RAW (or VIN): Unregulated voltage input (5V up to 12V recommended)
 * GND: Ground (common reference for power and signals)
 * RST: Reset pin (connect to GND to restart the board)
 *
 * This is intended to be used with a HX711 load cell amplifier pcb.
 *
 * * - COMMANDS (Serial Monitor) - 
 * 'h' = High Sensitivity (128)
 * 'l' = Low Sensitivity (64)
 * 'r' = Reset/Tare Brake
 * 's' = Show current settings
 * 'd' = toggle debug mode
 *
 * * -I/O pins-
 * Digital pin 8 = Bind Mode
 * Digital pin 9 = Physical Button to Reset Zero Value
 *   
 * * Required Libraries (Install via Sketch > Include Library > Manage Libraries):
 * 1. "Joystick" by Matthew Heironimus (Version 2.0 or higher)
 * 2. "HX711" by Bogdan Necula
 */

// ------------------- INITIALISATION -------------------
#include <EEPROM.h>
#include <HX711.h>
#include <Joystick.h>

// ------------------- PIN DEFINITIONS -------------------
#define THROTTLE_PIN  A0 // D18
#define CLUTCH_PIN    A1 // D19
#define LOADCELL_DOUT 4  // Arduino pin 6 connect to HX711 DOUT
#define LOADCELL_SCK  5  // Arduino pin 5 connect to HX711 CLK
#define BIND_BTN_PIN  8  // The arduino pin to check to enable binding mode
#define ZERO_BTN_PIN  9  // The arduino pin to ZERO the load cell

// ------------------- CALIBRATION (EDIT THESE) -------------------
// Open Serial Monitor to see raw values, then update these.

// Throttle
const int THROTTLE_MIN = 515;   // Raw value released
const int THROTTLE_MAX = 29;   // Raw value pressed

// Clutch
const int CLUTCH_MIN = 20;    // Raw value released
const int CLUTCH_MAX = 463;   // Raw value pressed

// Brake (Load Cell)
// Note: HX711 values can be very large.
long BRAKE_MIN = -1300;    // Raw value released
long BRAKE_MAX = 400000;  // Raw value pressed

// ------------------- GLOBALS -------------------
HX711 brakeScale;
Joystick_ Joystick(
  JOYSTICK_DEFAULT_REPORT_ID + 1, 
  JOYSTICK_TYPE_GAMEPAD,
  2, 0,                  // 2 Buttons, 0 Hat Switches
  false, false, true,    // X (No), Y (No), Z (Yes - Clutch)
  false, false, false,   // Rx, Ry, Rz
  false, true,           // Rudder, Throttle (Yes)
  false, true, false     // Accelerator, Brake (Yes), Steering
);

// ------------------- VARIABLES -------------------
bool debugMode = true; // Set to false to disable Serial output
int sensitivityAddress = 0; // EEPROM address
long lastBrakeValue = 0;    // Store last known brake value

void setup() {
  Serial.begin(9600);
  Serial.println("=== fabemit Sim Racing Pedals ===");
  Serial.println("Press 'r' to reset brake zero point");
  Serial.println("Press 'd' to toggle debug mode");
  Serial.println();

  // 1. PIN SETUP
  pinMode(THROTTLE_PIN, INPUT);
  pinMode(CLUTCH_PIN, INPUT);
  pinMode(BIND_BTN_PIN, INPUT_PULLUP);
  pinMode(ZERO_BTN_PIN, INPUT_PULLUP);
  pinMode(LED_BUILTIN, OUTPUT);

  // 2. LOAD CELL SETUP
  int sensitivity = EEPROM.read(sensitivityAddress);
  if (sensitivity != 64 && sensitivity != 128) {
    sensitivity = 64; // Default to low
    EEPROM.write(sensitivityAddress, sensitivity);
  }
  
  brakeScale.begin(LOADCELL_DOUT, LOADCELL_SCK);
  brakeScale.set_gain(sensitivity);
  brakeScale.set_scale(); // Raw mode
  // Wait for stabilization
  delay(100);
  brakeScale.tare(); 

  // 3. JOYSTICK SETUP
  Joystick.setThrottleRange(0, 1023);
  Joystick.setBrakeRange(0, 1023);
  Joystick.setZAxisRange(0, 1023);
  Joystick.begin(false); // False = Manual sendState() for better control

  Serial.print("Pedals Ready. Sensitivity: ");
  Serial.println(sensitivity);
}

void loop() {
  // --- 1. HANDLE SERIAL COMMANDS ---
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    handleCommand(cmd);
  }

  // --- 2. HANDLE PHYSICAL BUTTONS ---
  if (digitalRead(ZERO_BTN_PIN) == LOW) {
    Serial.println("Taring Brake...");
    brakeScale.tare();
    delay(200); // Debounce
  }
  
  if (digitalRead(BIND_BTN_PIN) == LOW) {
    runBindMode();
  }

  // --- 3. READ SENSORS ---
  
  // Throttle & Clutch (Read EVERY loop for max speed)
  int rawThrottle = analogRead(THROTTLE_PIN);
  int rawClutch = analogRead(CLUTCH_PIN);

  // Brake (Only read if hardware is ready, otherwise use last value)
  // This prevents the load cell speed from slowing down the other pedals
  if (brakeScale.is_ready()) {
    lastBrakeValue = brakeScale.read(); // Use read() for raw data
  }

  // --- 4. PROCESS & MAP VALUES ---
  
  // Map(value, fromLow, fromHigh, toLow, toHigh)
  int outThrottle = map(rawThrottle, THROTTLE_MIN, THROTTLE_MAX, 0, 1023);
  int outClutch   = map(rawClutch, CLUTCH_MIN, CLUTCH_MAX, 0, 1023);
  int outBrake    = map(lastBrakeValue, BRAKE_MIN, BRAKE_MAX, 0, 1023);

  // Constrain to keep within 0-1023 bounds
  outThrottle = constrain(outThrottle, 0, 1023);
  outClutch   = constrain(outClutch, 0, 1023);
  outBrake    = constrain(outBrake, 0, 1023);

  // --- 5. SEND DATA ---
  Joystick.setThrottle(outThrottle);
  Joystick.setZAxis(outClutch);
  Joystick.setBrake(outBrake);
  Joystick.sendState();

  // --- 6. DEBUG OUTPUT ---
  printDebug(rawThrottle, rawClutch, lastBrakeValue); 
}

void handleCommand(char cmd) {
  if (cmd == 'h' || cmd == 'H') {
    brakeScale.set_gain(128);
    EEPROM.write(sensitivityAddress, 128);
    Serial.println("High Sensitivity Set");
  } else if (cmd == 'l' || cmd == 'L') {
    brakeScale.set_gain(64);
    EEPROM.write(sensitivityAddress, 64);
    Serial.println("Low Sensitivity Set");
  } else if (cmd == 'r' || cmd == 'R') {
    brakeScale.tare();
    Serial.println("Brake Reset");
  } else if (cmd == 's' || cmd == 'S') {
    Serial.print("Sensitivity: ");
    Serial.println(EEPROM.read(sensitivityAddress));
  } else if (cmd == 'd' || cmd == 'D') {
      // Toggle debug mode
      debugMode = !debugMode;
      Serial.print("Debug mode: ");
      Serial.println(debugMode ? "OFF" : "ON");
  }
}

void runBindMode() {
  Serial.println("Simulating Pedals for Binding...");
  // Press
  Joystick.setThrottle(1023); Joystick.sendState(); delay(500);
  Joystick.setThrottle(0);    Joystick.sendState(); delay(500);
  
  Joystick.setBrake(1023);    Joystick.sendState(); delay(500);
  Joystick.setBrake(0);       Joystick.sendState(); delay(500);
  
  Joystick.setZAxis(1023);    Joystick.sendState(); delay(500);
  Joystick.setZAxis(0);       Joystick.sendState(); delay(500);
  Serial.println("Done.");
}

void printDebug(int t, int c, long b) {
  if (!debugMode) {
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 100) { // Limit print speed
    Serial.print("Thr:"); Serial.print(t);
    Serial.print(" Clu:"); Serial.print(c);
    Serial.print(" Brk:"); Serial.println(b);
    lastPrint = millis();
  }
 }
}
