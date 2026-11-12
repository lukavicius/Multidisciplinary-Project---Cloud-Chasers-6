/*
  FIELD DEPLOYMENT LOGGER v5
  --------------------------
  Deep-sleep logger: tipping bucket (ext0 wake) + scheduled batch readings
  of DHT, HX711 load cell, DS3231 RTC, written to SD.

  What changed vs v4
  - CRASH FIX: v4 computed (avgRaw - 0) / 0 with INTEGER types. On the ESP32
    that is an IntegerDivideByZero panic -> "Rebooting..." -> SW_CPU_RESET
    loop, every time the HX711 returned a reading (or a floating DT pin
    looked "ready"). Calibration is now float, and a factor of 0 means
    "not calibrated": raw is still logged, weight is NaN, status says NO_CAL.
  - Staggered power: nothing runs at the same time any more.
        RTC (I2C) -> DHT (optionally power-gated) -> HX711 (powered down
        again afterwards) -> SD card last.
    The SD card (biggest current spikes) is only initialised after the
    sensors have been shut down.
  - HX711 reads can no longer hang forever (timeout on every sample), and
    suspicious raw values (-1, 0, +/- full scale = floating/unpowered DT)
    are rejected and flagged.
  - DHT and HX711 have separate sample counts. The slow DHT only needs a few
    samples, the HX711 is fast. Awake time per cycle drops from ~22 s to ~8 s.
  - First boot no longer sleeps for two intervals (nextLogUs is set to "now").
  - Tip wake waits for the contact to release before sleeping, so one tip is
    not counted twice.
  - ext0 pull-up is kept alive during deep sleep (RTC_PERIPH domain on).
  - Reset reason (POWERON / BROWNOUT / PANIC / WDT) is logged in the status
    column of the first row after any boot, so crashes show up in the data.
  - One append per row: size check + write error check, SD init retried at a
    lower SPI speed (more tolerant of breadboard wiring).

  Revision v5.3 (ENERGY EFFICIENCY -- shorter and cheaper wake-ups)
  - CPU runs at 80 MHz instead of 240 MHz (CPU_MHZ). Wi-Fi and Bluetooth are
    never started, so the radio draws nothing. At 80 MHz an awake ESP32 draws
    roughly 30-40 mA instead of 50-60 mA. Everything here (I2C, SPI, DHT,
    HX711, deep sleep) works at 80 MHz.
  - Serial is completely off in deployment (SERIAL_DEBUG follows TEST_MODE):
    no UART start-up, no printing, no flush. It also makes the tip-wake path
    (one wake per bucket tip, which happens a lot in rain) shorter.
  - DHT: ONE reading per wake in deployment (DHT_SAMPLES 1), with a single
    retry after DHT_SAMPLE_GAP_MS only if that reading fails. The old
    3 samples x 2.2 s gaps kept the CPU awake ~4.4 s per wake for almost no
    benefit: a DHT11 only resolves 1 degC / 1 %RH and the values change slowly.
  - Awake time per wake drops from about 8 s to about 3.5 s (the HX711
    settling and conversions are now the biggest part, ~2 s).
  - NOT changed on purpose (these protect data quality): HX_SETTLE_MS,
    HX_DISCARD, HX_SAMPLES, the 250 ms start-up delay, SD handling.
  - Most of the remaining energy is spent while ASLEEP, by the board itself
    (regulator, USB chip, LEDs, SD module, bridge). See the notes next to
    BRIDGE / hardware in the chat: software cannot remove that.

  Revision v5.1 (from the bench measurements)
  - HX711 stays powered DOWN in deep sleep: SCK is driven HIGH and the pad is
    held (gpio_hold_en + gpio_deep_sleep_hold_en). Without the hold, the pin
    floats in deep sleep, the HX711 wakes up and keeps the bridge powered
    (possibly ~15 mA), which would flatten a battery over weeks. The hold is
    released at the start of every log cycle, with the pin already HIGH so
    nothing glitches. A tip wake leaves the hold untouched.
  - HX711 settling: the first conversions after power-up read high (about
    +0.5 % of the reading, i.e. ~+2000 counts at 5 kg, ~+30 g). Now waits
    HX_SETTLE_MS and discards HX_DISCARD (4) conversions before sampling.
    Use the SAME procedure when calibrating, or the calibration is ~0.1 % off.
  - HX711 pins set to DT=GPIO16, SCK=GPIO17 (your bench wiring, see below).

  BEFORE DEPLOYING
    1. TEST_MODE true, upload, Serial Monitor 115200, watch several cycles.
    2. Check field_log.csv on the card.
    3. TEST_MODE false for 15-min cycles.
    4. Set CAL_OFFSET / CAL_FACTOR from your HX711 calibration, measured on the
       SAME power supply you will deploy with (the span moved ~3.5 % between
       USB and battery in the bench tests).

  VERIFY THE PINS BELOW AGAINST YOUR REAL WIRING. v4's header comment listed
  DHT->GPIO4 and HX711 DT/SCK->16/17, but its #defines used 14 and 32/33.
  v5 followed the #defines (32/33); v5.1 uses 16/17, as in all the bench
  sketches. If your logger unit is really wired to 32/33, change them back.

  Libraries: RTClib, DHT sensor library + Adafruit Unified Sensor, HX711
             (bogde), SD (built-in)
*/

#include <Wire.h>
#include <RTClib.h>
#include <SPI.h>
#include <SD.h>
#include <DHT.h>
#include <HX711.h>
#include <math.h>
#include <sys/time.h>
#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "esp_sleep.h"
#include "esp_system.h"

// ===================== SWITCHES =====================
#define TEST_MODE   true    // true = bench test (30 s cycles). SET FALSE BEFORE DEPLOYING.
#define USE_RTC     true
#define CPU_MHZ     80       // 80 is plenty; 240 would draw ~20 mA more while awake
#define SERIAL_DEBUG TEST_MODE   // Serial output only in test mode (saves time and energy)

#if !SERIAL_DEBUG
// Silent stand-in for Serial: every Serial.xxx() call below compiles to nothing.
struct NullSerial {
  void begin(unsigned long) {}
  void flush() {}
  size_t println(const char *) { return 0; }
  template <typename... A> int printf(const char *, A...) { return 0; }
};
static NullSerial NullSer;
#define Serial NullSer
#endif

// ===================== PINS =====================
#define SD_CS_PIN            5     // SD: MOSI 23, MISO 19, CLK 18
#define I2C_SDA              21
#define I2C_SCL              22
#define DHT_PIN              14
#define DHT_TYPE             DHT11 // change to DHT22 if that is what you have
#define DHT_PWR_PIN          -1    // -1 = DHT always powered. Or an RTC-capable GPIO
                                   // (e.g. 25) wired to the DHT's + pin: it is then
                                   // powered only while sampling (draws ~1 mA, fine
                                   // for a GPIO).
#define HX711_DT_PIN         32
#define HX711_SCK_PIN        33    // held HIGH in deep sleep = HX711 powered down
#define TIPPING_BUCKET_PIN   GPIO_NUM_27
#define LED_PIN              2

// ===================== CALIBRATION =====================
const long  CAL_OFFSET = 0;
const float CAL_FACTOR = 0.0f;     // 0 = not calibrated -> weight logged as NaN

// ===================== TIMING =====================
#if TEST_MODE
  #define WAKE_INTERVAL_SEC  30
  #define DHT_SAMPLES        2
  #define HX_SAMPLES         3
  #define LED_SELFCHECK      true
#else
  #define WAKE_INTERVAL_SEC  900
  #define DHT_SAMPLES        1
  #define HX_SAMPLES         10
  #define LED_SELFCHECK      false
#endif
#define DHT_SAMPLE_GAP_MS    2200
#define DHT_POWERUP_MS       2000
#define HX_SETTLE_MS         500
#define HX_DISCARD           4     // conversions dropped after power-up (settling transient)
#define HX_READY_TIMEOUT_MS  400
#define TIP_DEBOUNCE_US      200000LL

// ===================== STATE =====================
RTC_DS3231 rtc;
DHT dht(DHT_PIN, DHT_TYPE);
HX711 scale;

const char *logFileName = "/field_log.csv";
const char *CSV_HEADER =
  "boot_session,elapsed_sec,timestamp,avg_temperature_C,avg_humidity_pct,"
  "avg_raw_adc,avg_weight_g,total_tips,status";

// Survive deep sleep (cleared by any real reset: power loss, brownout, panic).
RTC_DATA_ATTR unsigned long totalTipCount    = 0;
RTC_DATA_ATTR bool          firstBootDone    = false;
RTC_DATA_ATTR int64_t       nextLogUs        = 0;
RTC_DATA_ATTR int64_t       lastTipUs        = 0;
RTC_DATA_ATTR int64_t       lastGoodRtcEpoch = 0;
RTC_DATA_ATTR int64_t       lastGoodRtcUs    = 0;
RTC_DATA_ATTR uint32_t      bootSession      = 0;
RTC_DATA_ATTR int64_t       bootStartUs      = 0;

// ===================== HELPERS =====================
int64_t nowUs() {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (int64_t)tv.tv_sec * 1000000LL + tv.tv_usec;
}

void addFlag(String &flags, const char *f) {
  if (flags.length()) flags += ' ';
  flags += f;
}

String fmtF(float v, int dec) {
  return isnan(v) ? String("NaN") : String(v, dec);
}

const char *resetTag() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "BOOT_POWERON";
    case ESP_RST_BROWNOUT: return "BOOT_BROWNOUT";
    case ESP_RST_PANIC:    return "BOOT_PANIC";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:      return "BOOT_WDT";
    case ESP_RST_SW:       return "BOOT_SW";
    default:               return "BOOT_OTHER";
  }
}

void blinkLED(int count, int onMs, int offMs) {
  pinMode(LED_PIN, OUTPUT);
  for (int i = 0; i < count; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(onMs);
    digitalWrite(LED_PIN, LOW);
    if (i < count - 1) delay(offMs);
  }
}

// ===================== SLEEP =====================
void armWakeSources(uint64_t sleepUs) {
  if (sleepUs < 1000000ULL) sleepUs = 1000000ULL;      // avoid wake storms
  esp_sleep_enable_ext0_wakeup(TIPPING_BUCKET_PIN, 0);  // tip = contact to GND
  rtc_gpio_pullup_en(TIPPING_BUCKET_PIN);
  rtc_gpio_pulldown_dis(TIPPING_BUCKET_PIN);
  esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON); // keep pull-up alive
  esp_sleep_enable_timer_wakeup(sleepUs);
}

void goToSleepUntilNextLog() {
  int64_t remaining = nextLogUs - nowUs();
  if (remaining < 0) remaining = 0;
  armWakeSources((uint64_t)remaining);

  // Keep the HX711 powered down during deep sleep: PD_SCK HIGH for >60 us puts
  // it (and the load cell bridge) to sleep, but the pin floats in deep sleep
  // unless it is driven and held.
  pinMode(HX711_SCK_PIN, OUTPUT);
  digitalWrite(HX711_SCK_PIN, HIGH);
  gpio_hold_en((gpio_num_t)HX711_SCK_PIN);
  gpio_deep_sleep_hold_en();   // applies to every pad held with gpio_hold_en (also the DHT supply pin, LOW)

  Serial.printf("Sleeping for %.1fs until next scheduled log.\n\n", remaining / 1000000.0);
  Serial.flush();
  esp_deep_sleep_start();
}

// ===================== TIP WAKE (fast path) =====================
void handleTipWake() {
  if (nowUs() - lastTipUs > TIP_DEBOUNCE_US) totalTipCount++;

  // Wait for the contact to open again, otherwise the active-low wake source
  // would fire immediately and the same tip could be counted twice.
  rtc_gpio_deinit(TIPPING_BUCKET_PIN);
  pinMode((int)TIPPING_BUCKET_PIN, INPUT_PULLUP);
  uint32_t start = millis();
  while (digitalRead((int)TIPPING_BUCKET_PIN) == LOW && millis() - start < 1000) delay(5);

  lastTipUs = nowUs();
  goToSleepUntilNextLog();     // nextLogUs untouched on purpose: schedule never slips
}

// ===================== TIME =====================
// Returns true if the timestamp is a real RTC reading (or RTC disabled).
bool getTimestamp(String &ts, String &flags) {
#if USE_RTC
  bool rtcOK = false;
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setTimeOut(100);
  for (int a = 0; a < 4 && !rtcOK; a++) {
    rtcOK = rtc.begin();
    if (!rtcOK) delay(50);
  }

  char buf[24];
  if (rtcOK) {
    DateTime now = rtc.now();
    if (now.year() >= 2026 && now.year() <= 2035) {
      snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d",
               now.year(), now.month(), now.day(),
               now.hour(), now.minute(), now.second());
      ts = buf;
      lastGoodRtcEpoch = now.unixtime();
      lastGoodRtcUs = nowUs();
      return true;
    }
    addFlag(flags, "RTC_TIME_SUSPECT");
  } else {
    addFlag(flags, "RTC_FAIL");
  }

  // Fallback: extrapolate from the last good RTC reading using the ESP32 clock.
  if (lastGoodRtcEpoch > 0) {
    int64_t estEpoch = lastGoodRtcEpoch + (nowUs() - lastGoodRtcUs) / 1000000LL;
    DateTime est((uint32_t)estEpoch);
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d",
             est.year(), est.month(), est.day(),
             est.hour(), est.minute(), est.second());
    ts = String(buf) + "_EST";
    addFlag(flags, "TIME_ESTIMATED");
  } else {
    ts = "RTC_FAIL";
  }
  return false;
#else
  (void)flags;
  ts = "NO_RTC";
  return true;
#endif
}

// ===================== SENSORS (one at a time) =====================
int sampleDHT(float &avgT, float &avgH) {
  float tSum = 0, hSum = 0;
  int good = 0;

#if DHT_PWR_PIN >= 0
  gpio_deep_sleep_hold_dis();
  gpio_hold_dis((gpio_num_t)DHT_PWR_PIN);
  pinMode(DHT_PWR_PIN, OUTPUT);
  digitalWrite(DHT_PWR_PIN, HIGH);
  delay(DHT_POWERUP_MS);
#endif

  dht.begin();
  for (int i = 0; i < DHT_SAMPLES; i++) {
    float t = NAN, h = NAN;
    bool ok = false;
    for (int attempt = 0; attempt < 2 && !ok; attempt++) {
      if (attempt) delay(DHT_SAMPLE_GAP_MS);       // retry only after a failed read
      t = dht.readTemperature();
      h = dht.readHumidity();
      ok = !isnan(t) && !isnan(h);
    }
    if (ok) {
      tSum += t;
      hSum += h;
      good++;
    }
    if (i < DHT_SAMPLES - 1) delay(DHT_SAMPLE_GAP_MS);
  }

#if DHT_PWR_PIN >= 0
  digitalWrite(DHT_PWR_PIN, LOW);
  gpio_hold_en((gpio_num_t)DHT_PWR_PIN);
#endif

  avgT = good ? tSum / good : NAN;
  avgH = good ? hSum / good : NAN;
  return good;
}

int sampleHX711(long &avgRaw, int &suspect) {
  long sum = 0;
  int good = 0;
  suspect = 0;

  scale.begin(HX711_DT_PIN, HX711_SCK_PIN);
  scale.power_up();
  delay(HX_SETTLE_MS);

  // The first HX_DISCARD conversions after power-up are dropped: they read
  // high (settling transient, ~+0.5 % of the reading on the first two).
  for (int i = 0; i < HX_DISCARD + HX_SAMPLES; i++) {
    if (!scale.wait_ready_timeout(HX_READY_TIMEOUT_MS)) continue;   // never blocks forever
    long raw = scale.read();
    if (i < HX_DISCARD) continue;
    // -1 / 0 / full-scale = floating DT, unpowered chip or broken wiring.
    if (raw == -1 || raw == 0 || raw >= 8388607L || raw <= -8388608L) {
      suspect++;
      continue;
    }
    sum += raw;
    good++;
  }

  scale.power_down();   // also switches off the bridge excitation
  avgRaw = good ? sum / good : 0;
  return good;
}

// ===================== SD (last, with sensors already off) =====================
bool sdBegin() {
  for (int a = 0; a < 3; a++) {
    if (SD.begin(SD_CS_PIN, SPI, 4000000)) return true;
    SD.end();
    delay(100);
  }
  return false;
}

bool appendRow(const char *line) {
  if (!SD.exists(logFileName)) {
    File h = SD.open(logFileName, FILE_WRITE);
    if (!h) return false;
    h.println(CSV_HEADER);
    h.close();
  }
  File f = SD.open(logFileName, FILE_APPEND);
  if (!f) return false;
  size_t before = f.size();
  size_t n = f.println(line);
  f.flush();
  size_t after = f.size();
  bool ok = (n > 0) && (after >= before + n) && !f.getWriteError();
  f.close();
  return ok;
}

// ===================== FULL LOG CYCLE =====================
// SCK was driven HIGH and held through deep sleep (HX711 powered down). Put the
// same level in the normal GPIO registers first, then release the hold, so the
// pin never glitches LOW (which would wake the HX711 early). The HX711 only
// powers up later, in sampleHX711(), when power_up() pulls SCK LOW.
void releaseSleepHolds() {
  pinMode(HX711_SCK_PIN, OUTPUT);
  digitalWrite(HX711_SCK_PIN, HIGH);
  gpio_hold_dis((gpio_num_t)HX711_SCK_PIN);
  gpio_deep_sleep_hold_dis();
}

void runLogCycle() {
  releaseSleepHolds();
  delay(250);

  String flags = "";
  bool justBooted = !firstBootDone;

  if (justBooted) {
    Serial.println("=== FIRST BOOT ===");
    bootSession++;
    bootStartUs = nowUs();
    nextLogUs = nowUs();            // first log happens now; schedule advances below
    firstBootDone = true;
    addFlag(flags, resetTag());
    Serial.printf("[TIME] boot_session %lu started (%s).\n",
                  (unsigned long)bootSession, resetTag());
  }

  Serial.printf("Woke for scheduled logging. TotalTips so far: %lu\n", totalTipCount);
  Serial.println("Taking batch of readings...");

  // 1) RTC (I2C, tiny current)
  String ts;
  bool rtcReadOK = getTimestamp(ts, flags);

  // 2) DHT, then 3) HX711 -- strictly one after the other
  float avgTemp, avgHum;
  int dhtGood = sampleDHT(avgTemp, avgHum);

  long avgRaw;
  int hxSuspect;
  int hxGood = sampleHX711(avgRaw, hxSuspect);

  float avgWeight = NAN;
  if (hxGood > 0) {
    if (CAL_FACTOR != 0.0f) avgWeight = ((float)avgRaw - (float)CAL_OFFSET) / CAL_FACTOR;
    else addFlag(flags, "NO_CAL");
  }

  if (dhtGood < DHT_SAMPLES) {
    addFlag(flags, (String("DHT_") + dhtGood + "of" + DHT_SAMPLES).c_str());
  }
  if (hxGood < HX_SAMPLES) {
    addFlag(flags, (String("HX_") + hxGood + "of" + HX_SAMPLES).c_str());
  }
  if (hxSuspect > 0) addFlag(flags, "HX_RAW_SUSPECT");

  String status = flags.length() ? flags : String("OK");
  uint32_t elapsedSec = (uint32_t)((nowUs() - bootStartUs) / 1000000LL);

  String sTemp = dhtGood ? fmtF(avgTemp, 1) : String("NaN");
  String sHum  = dhtGood ? fmtF(avgHum, 1)  : String("NaN");
  String sRaw  = hxGood  ? String(avgRaw)   : String("NaN");
  String sWgt  = fmtF(avgWeight, 1);

  char line[220];
  snprintf(line, sizeof(line), "%lu,%lu,%s,%s,%s,%s,%s,%lu,%s",
           (unsigned long)bootSession, (unsigned long)elapsedSec, ts.c_str(),
           sTemp.c_str(), sHum.c_str(), sRaw.c_str(), sWgt.c_str(),
           totalTipCount, status.c_str());
  Serial.println(line);

  // 4) SD last
  bool writeOK = false;
  if (sdBegin()) {
    writeOK = appendRow(line);
    if (!writeOK) Serial.println("[SD] ERROR: row not written / size did not grow.");
    SD.end();
  } else {
    Serial.println("[SD] ERROR: card not detected.");
  }

  // LED self-check (TEST_MODE only)
  if (LED_SELFCHECK) {
    if (!writeOK)         blinkLED(3, 120, 150);  // SD failed, row NOT saved
    else if (!rtcReadOK)  blinkLED(2, 120, 150);  // saved, RTC problem
    else                  blinkLED(1, 700, 0);    // all good
  }

  // Advance from the previous target (not from "now") so the schedule never drifts.
  nextLogUs += (int64_t)WAKE_INTERVAL_SEC * 1000000LL;
  if (nextLogUs < nowUs()) nextLogUs = nowUs() + (int64_t)WAKE_INTERVAL_SEC * 1000000LL;

  goToSleepUntilNextLog();
}

// ===================== ARDUINO ENTRY POINTS =====================
void setup() {
  setCpuFrequencyMhz(CPU_MHZ);   // first thing: everything after runs slower and cheaper
  Serial.begin(115200);
#if SERIAL_DEBUG
  delay(50);
#endif

  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    handleTipWake();     // never returns
  }
  runLogCycle();         // never returns
}

void loop() {
  // Unused: deep sleep restarts setup() each time.
}
