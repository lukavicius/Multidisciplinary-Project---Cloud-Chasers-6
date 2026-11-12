/*
 * data_mayfly3.ino
 *
 * Mayfly v1.1 minimal logger - battery + box air + two tipping buckets:
 *   (on-board SHT40) - box air temp/humidity (I2C, no pin needed)
 *   D10 - Tipping Bucket 6
 *   D11 - Tipping Bucket 7
 *
 * No EC-5, no 5TM/SDI-12.
 *
 * REQUIRES: "Adafruit SHT4x Library" (Arduino Library Manager) - accept
 *           the prompt to also install Adafruit BusIO / Unified Sensor.
 *
 * Change in this version: box air temperature and humidity are now
 * logged from the Mayfly's built-in SHT40 (BoxAirTemp_C, BoxAirHum_Pct
 * columns, same names as the other loggers).
 *
 * Same underlying design as the other loggers (RTC only reset if
 * unset, RTC-based sleep timing robust against interrupt wakeups,
 * bucket debounce muted/reset around sleep and power transitions,
 * SD.begin() re-run every cycle, fixed-buffer CSV rows).
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
const int ADS_PWR      = 22;
const int BAT_VOLT_PIN = A6;
const int SD_SS_PIN    = 12;

const int LOG_INTERVAL_MIN = 15; // TESTING - set back to 15 for real deployment
const char* LOG_FILENAME = "MAYFLY3.CSV"; // 8.3-safe

// --- Tipping buckets: D10=Bucket 6, D11=Bucket 7 ---
const int TB_PINS[2] = {10, 11};
const char* TB_NAMES[2] = {"Tipping Bucket 7", "Tipping Bucket 6"};
volatile unsigned long tbPulseCount[2]    = {0, 0};
volatile unsigned long tbLastPulseTime[2] = {0, 0};
const unsigned long TB_DEBOUNCE_MS = 50;

void tbISR(uint8_t idx) {
  unsigned long n = millis();
  if (n - tbLastPulseTime[idx] >= TB_DEBOUNCE_MS) {
    tbLastPulseTime[idx] = n;
    tbPulseCount[idx]++;
  }
}
void isrTB6() { tbISR(0); } // D10
void isrTB7() { tbISR(1); } // D11

void muteBucketInterrupts() {
  disableInterrupt(TB_PINS[0]);
  disableInterrupt(TB_PINS[1]);
}

void unmuteBucketInterrupts() {
  enableInterrupt(TB_PINS[0], isrTB6, FALLING);
  enableInterrupt(TB_PINS[1], isrTB7, FALLING);
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
// false) if the sensor isn't found or the read fails, so the CSV row
// can write "ERR" for those fields.
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
  digitalWrite(ADS_PWR, HIGH);
  delay(200); // rail settle time before trusting the bucket pins again
  noInterrupts();
  for (int i = 0; i < 2; i++) tbLastPulseTime[i] = millis();
  interrupts();
  unmuteBucketInterrupts();
}

void powerOffSensors() {
  muteBucketInterrupts();
  delay(50);
  digitalWrite(SW_3V_PIN, LOW);
  digitalWrite(ADS_PWR, LOW);
  delay(50);
  unmuteBucketInterrupts();
}

void ensureHeader() {
  if (!SD.exists(LOG_FILENAME)) {
    File f = SD.open(LOG_FILENAME, FILE_WRITE);
    if (f) {
      f.println(F("Timestamp,Battery_V,Battery_Pct,BoxAirTemp_C,BoxAirHum_Pct,TippingBucket6_Count,TippingBucket7_Count"));
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
  for (int i = 0; i < 2; i++) {
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

  unsigned long tbCounts[2];
  noInterrupts();
  for (int i = 0; i < 2; i++) {
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

  char dataLine[120];
  snprintf(dataLine, sizeof(dataLine),
           "%s,%s,%s,%s,%s,%lu,%lu",
           timestamp, vBatStr, batPctStr, boxTStr, boxHStr,
           tbCounts[0], tbCounts[1]);

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
  pinMode(ADS_PWR, OUTPUT);

  Wire.begin();
  rtc.begin();

  DateTime rtcCheck = rtc.now();
  if (rtcCheck.year() < 2024) {
    DateTime compiled = DateTime(__DATE__, __TIME__);
    rtc.setDateTime(compiled);
    Serial.println(F("RTC time looked unset - initialized from compile time."));
  }

  powerOnSensors();

  for (int i = 0; i < 2; i++) pinMode(TB_PINS[i], INPUT_PULLUP);
  unmuteBucketInterrupts();
  delay(50);
  noInterrupts();
  for (int i = 0; i < 2; i++) { tbPulseCount[i] = 0; tbLastPulseTime[i] = 0; }
  interrupts();

  powerOffSensors();

  Serial.println(F("===================================================="));
  Serial.println(F(" data_mayfly3 - first reading:"));
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