/*
  HX711 MULTI-SAMPLE-SIZE TEST - CONTINUOUS, PRINTS EVERY 1 SECOND
  ----------------------------------------------------------------------
  Runs forever, no reset/EN button needed. Every 1 second, takes a fresh
  averaged raw reading at each sample size listed below and prints it.

  Temperature and humidity are read ONCE at startup only.

  Wiring:
    HX711: DT->GPIO16, SCK->GPIO17, VCC->confirmed-working voltage, GND->GND bus
    DHT22: out->GPIO14, +->3V3 bus, -->GND bus

  Libraries needed: HX711 (by Bogdan Necula), DHT sensor library (Adafruit)
  + Adafruit Unified Sensor (dependency)
*/

#include <HX711.h>
#include <DHT.h>

#define HX711_DT_PIN  16
#define HX711_SCK_PIN 17
#define DHT_PIN       14
#define DHT_TYPE      DHT22 // DHT11 for lysimeter 2,3 and 4

HX711 scale;
DHT dht(DHT_PIN, DHT_TYPE);

const int sampleSizes[] = {10};
const int numSampleSizes = sizeof(sampleSizes) / sizeof(sampleSizes[0]);
const unsigned long printInterval = 1000; // 1 second

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("=== HX711 CONTINUOUS TEST (every 1s) ===");

  scale.begin(HX711_DT_PIN, HX711_SCK_PIN);
  delay(500);

  if (!scale.is_ready()) {
    Serial.println("ERROR: HX711 not found/responding. Check DT/SCK/VCC/GND wiring.");
    while (1) delay(1000);
  }
  Serial.println("HX711 found.");

  // ---- Temperature and humidity, once only ----
  dht.begin();
  delay(2000);
  float startTemp = dht.readTemperature();
  float startHum = dht.readHumidity();
  Serial.println();
  Serial.println("--- Startup conditions ---");
  if (isnan(startTemp) || isnan(startHum)) {
    Serial.println("DHT22 read FAILED at startup (check wiring on GPIO14).");
  } else {
    Serial.print("Temperature: ");
    Serial.print(startTemp, 1);
    Serial.print(" C   Humidity: ");
    Serial.print(startHum, 1);
    Serial.println(" %");
  }
  Serial.println("---------------------------");
  Serial.println();

  Serial.println("Printing readings every 1 second, forever. No reset needed.");
  Serial.println();
}

void loop() {
  static unsigned long lastPrint = 0;
  if (millis() - lastPrint >= printInterval) {
    lastPrint = millis();

    if (!scale.is_ready()) {
      Serial.println("HX711 not ready.");
      return;
    }

    Serial.print("Reading -> ");
    for (int i = 0; i < numSampleSizes; i++) {
      long value = scale.read_average(sampleSizes[i]);
      Serial.print("n=");
      Serial.print(sampleSizes[i]);
      Serial.print(": ");
      Serial.print(value);
      if (i < numSampleSizes - 1) Serial.print("   |   ");
    }
    Serial.println();
  }
}

