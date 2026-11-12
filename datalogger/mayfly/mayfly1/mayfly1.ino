/*
 * data_mayfly1.ino
 *
 * Mayfly v1.1 environmental logger - final pin map:
 *   (on-board SHT40) - box air temp/humidity (I2C, no pin needed)
 *   D4  - now unused (was the external DHT11)
 *   D5  - Tipping Bucket 1
 *   D6  - Tipping Bucket 3
 *   D7  - now unused (was the SDI-12 data line for the 5TM)
 *   D10 - Tipping Bucket 2
 *   D11 - Tipping Bucket 4
 *
 * REQUIRES: "Adafruit SHT4x Library" (Arduino Library Manager) - accept
 *           the prompt to also install Adafruit BusIO / Unified Sensor.
 *
 * Change in this version: both soil moisture sensors (EC-5 via ADS1115,
 * and 5TM via SDI-12) have been removed. CSV header columns for both
 * are dropped accordingly - this is a schema change, so this version's
 * CSV is not directly appendable to older files without reconciling
 * columns first.
 *
 * REMEMBER: LOG_INTERVAL_MIN is still 1 for testing - set to 15 for
 * real deployment.
 */

#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <LowPower.h>
#include <Sodaq_DS3231.h>
#include "Adafruit_SHT4x.h"
#include <EnableInterrupt.h>

// --- Hardware Pin Definitions (Mayfly v1.1) ---
const int SW_3V_PIN    = 18;
const int BAT_VOLT_PIN = A6;
const int SD_SS_PIN    = 12;

const int LOG_INTERVAL_MIN = 15; // TESTING - set back to 15 for real deployment
const char* LOG_FILENAME = "MAYFLY1.CSV"; // 8.3-safe

// --- Tipping buckets, named, debounced ---
const int TB_PINS[4] = {5, 10, 6, 11}; // Bucket 1=D5, 2=D10, 3=D6, 4=D11
const char* TB_NAMES[4] = {"Tipping Bucket 1", "Tipping Bucket 2", "Tipping Bucket 3", "Tipping Bucket 4"};
volatile unsigned long tbPulseCount[4]    = {0, 0, 0, 0};
volatile unsigned long tbLastPulseTime[4] = {0, 0, 0, 0};
const unsigned long TB_DEBOUNCE_MS = 50;

void tbISR(uint8_t idx) {
  unsigned long n = millis();
  if (n - tbLastPulseTime[idx] >= TB_DEBOUNCE_MS) {
    tbLastPulseTime[idx] = n;
    tbPulseCount[idx]++;
  }
}
void isrTB1() { tbISR(0); } // D5
void isrTB2() { tbISR(1); } // D10
void isrTB3() { tbISR(2); } // D6
void isrTB4() { tbISR(3); } // D11

void muteBucketInterrupts() {
  disableInterrupt(TB_PINS[0]);
  disableInterrupt(TB_PINS[1]);
  disableInterrupt(TB_PINS[2]);
  disableInterrupt(TB_PINS[3]);
}

void unmuteBucketInterrupts() {
  enableInterrupt(TB_PINS[0], isrTB1, FALLING);
  enableInterrupt(TB_PINS[1], isrTB2, FALLING);
  enableInterrupt(TB_PINS[2], isrTB3, FALLING);
  enableInterrupt(TB_PINS[3], isrTB4, FALLING);
}

Adafruit_SHT4x sht4 = Adafruit_SHT4x();
bool sht4Ready = false;
File logFile;

float readBatteryVoltage() {
  int rawADC = analogRead(BAT_VOLT_PIN);
  float pinVoltage = (rawADC / 1023.0) * 3.3;
  return pinVoltage * 4.7;
}

float calculateBatteryPercentage(float volts) {
  if (volts >= 4.20) return 100.0;
  if (volts <= 3.40) return 0.0;
  return ((volts - 3.40) / (4.20 - 3.40)) * 100.0;
}

// Reads the on-board SHT40. Outputs are NAN (and the function returns
// false) if the sensor isn't found or the read fails, so the existing
// "ERR" handling in the CSV row still applies.
bool readBoxAir(float &tempC, float &humidity) {
  tempC = NAN;
  humidity = NAN;

  if (!sht4Ready) {
    sht4Ready = sht4.begin();
    if (!sht4Ready) return false;
    sht4.setPrecision(SHT4X_HIGH_PRECISION);
    sht4.setHeater(SHT4X_NO_HEATER);
  }

  sensors_event_t humEvent, tempEvent;
  humEvent.relative_humidity = NAN;
  tempEvent.temperature = NAN;
  sht4.getEvent(&humEvent, &tempEvent);

  tempC = tempEvent.temperature;
  humidity = humEvent.relative_humidity;
  return !(isnan(tempC) || isnan(humidity));
}

void powerOnSensors() {
  muteBucketInterrupts();
  digitalWrite(SW_3V_PIN, HIGH);
  delay(1500);
  delay(200);
  noInterrupts();
  for (int i = 0; i < 4; i++) tbLastPulseTime[i] = millis();
  interrupts();
  unmuteBucketInterrupts();
}

void powerOffSensors() {
  muteBucketInterrupts();
  delay(50);
  digitalWrite(SW_3V_PIN, LOW);
  delay(50);
  unmuteBucketInterrupts();
}

void ensureHeader() {
  if (!SD.exists(LOG_FILENAME)) {
    File f = SD.open(LOG_FILENAME, FILE_WRITE);
    if (f) {
      f.println(F("Timestamp,Battery_V,Battery_Pct,BoxAirTemp_C,BoxAirHum_Pct,TippingBucket1_Count,TippingBucket2_Count,TippingBucket3_Count,TippingBucket4_Count"));
      f.close();
      Serial.print(F("Created ")); Serial.print(LOG_FILENAME); Serial.println(F(" with header."));
    } else {
      Serial.println(F("[SD ERROR] Could not create header file"));
    }
  }
}

void sleepEightSeconds() {
  noInterrupts();
  unsigned long preSleep = millis();
  for (int i = 0; i < 4; i++) {
    tbLastPulseTime[i] = preSleep - TB_DEBOUNCE_MS - 1;
  }
  interrupts();

  LowPower.powerDown(SLEEP_8S, ADC_OFF, BOD_OFF);
}

long secondsSinceMidnight(DateTime &dt) {
  return (long)dt.hour() * 3600L + (long)dt.minute() * 60L + dt.second();
}

void sleepForMinutes(int minutes) {
  DateTime startTime = rtc.now();
  long startSec = secondsSinceMidnight(startTime);
  long targetSec = (long)minutes * 60L;

  while (true) {
    sleepEightSeconds();
    DateTime nowTime = rtc.now();
    long nowSec = secondsSinceMidnight(nowTime);
    long elapsed = nowSec - startSec;
    if (elapsed < 0) elapsed += 86400L;
    if (elapsed >= targetSec) break;
  }
}

void formatTimestamp(char* buf, size_t bufSize, DateTime &now) {
  snprintf(buf, bufSize, "%04d-%02d-%02d %02d:%02d:%02d",
           now.year(), now.month(), now.date(),
           now.hour(), now.minute(), now.second());
}

void performLoggingCycle() {
  powerOnSensors();

  bool sdReady = SD.begin(SD_SS_PIN);
  if (sdReady) {
    ensureHeader();
  } else {
    Serial.println(F("[SD ERROR] SD.begin() failed this cycle"));
  }

  DateTime now = rtc.now();
  char timestamp[20];
  formatTimestamp(timestamp, sizeof(timestamp), now);

  float vBat = readBatteryVoltage();
  float batPct = calculateBatteryPercentage(vBat);

  float boxAirTempC, boxAirHumidity;
  readBoxAir(boxAirTempC, boxAirHumidity);

  unsigned long tbCounts[4];
  noInterrupts();
  for (int i = 0; i < 4; i++) {
    tbCounts[i] = tbPulseCount[i];
    tbPulseCount[i] = 0;
  }
  interrupts();

  char vBatStr[8], batPctStr[8], boxTStr[8], boxHStr[8];
  dtostrf(vBat, 4, 2, vBatStr);
  dtostrf(batPct, 3, 0, batPctStr);

  if (isnan(boxAirTempC) || isnan(boxAirHumidity)) {
    strcpy(boxTStr, "ERR");
    strcpy(boxHStr, "ERR");
  } else {
    dtostrf(boxAirTempC, 4, 1, boxTStr);
    dtostrf(boxAirHumidity, 4, 1, boxHStr);
  }

  char dataLine[180];
  snprintf(dataLine, sizeof(dataLine),
           "%s,%s,%s,%s,%s,%lu,%lu,%lu,%lu",
           timestamp, vBatStr, batPctStr, boxTStr, boxHStr,
           tbCounts[0], tbCounts[1], tbCounts[2], tbCounts[3]);

  if (sdReady) {
    logFile = SD.open(LOG_FILENAME, FILE_WRITE);
    if (logFile) {
      logFile.println(dataLine);
      logFile.flush();
      logFile.close();
      Serial.print(F("[SD RECORDED] "));
      Serial.println(dataLine);
    } else {
      Serial.print(F("[SD ERROR] open() failed, Serial only: "));
      Serial.println(dataLine);
    }
  } else {
    Serial.print(F("[SD ERROR] not available this cycle, Serial only: "));
    Serial.println(dataLine);
  }

  powerOffSensors();
}

void setup() {
  Serial.begin(57600);
  while (!Serial && millis() < 3000);

  pinMode(SW_3V_PIN, OUTPUT);

  Wire.begin();
  rtc.begin();

  // Only stamp the RTC from compile time if it looks like it's never
  // been set (implausible year) - otherwise trust its own running
  // time, which survives reboots via its coin-cell backup.
  DateTime rtcCheck = rtc.now();
  if (rtcCheck.year() < 2024) {
    DateTime compiled = DateTime(__DATE__, __TIME__);
    rtc.setDateTime(compiled);
    Serial.println(F("RTC time looked unset - initialized from compile time."));
  }

  powerOnSensors();

  for (int i = 0; i < 4; i++) pinMode(TB_PINS[i], INPUT_PULLUP);
  unmuteBucketInterrupts();
  delay(50);
  noInterrupts();
  for (int i = 0; i < 4; i++) { tbPulseCount[i] = 0; tbLastPulseTime[i] = 0; }
  interrupts();

  powerOffSensors();

  Serial.println(F("===================================================="));
  Serial.println(F(" data_mayfly1 - first reading:"));
  Serial.println(F("===================================================="));
  performLoggingCycle();

  Serial.println(F("Setup complete. Entering deep sleep logging loop..."));
  Serial.flush();
}

void loop() {
  sleepForMinutes(LOG_INTERVAL_MIN);
  performLoggingCycle();
  Serial.flush();
}