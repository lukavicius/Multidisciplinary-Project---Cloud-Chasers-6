/*
  TIPPING BUCKET LOGGER - deep sleep, wake on tip, saves to SD
  ------------------------------------------------------------
  - Sleeps in deep sleep; wakes ONLY when the bucket tips (reed switch pulls
    GPIO27 to GND -> EXT0 wake-up).
  - Every tip is written to the SD card with a timestamp (DS3231 RTC).
  - Temperature and humidity are read ONCE at power-on and saved as a START row.
  - Tip total is kept in RTC memory (survives deep sleep, resets on power loss).
  - If the SD card is missing or fails, tips are kept in RTC memory (up to
    PENDING_MAX) and written as soon as the card works again.
  - Every wake-up mounts the card fresh and checks the file size afterwards,
    so pulling and re-inserting the card is safe.

  File: /tips_log.csv
  Columns: timestamp,event,tips_total,temperature_C,humidity_pct,status
    event = START (power-on, with temperature/humidity) or TIP

  Wiring:
    Tipping bucket: yellow -> GPIO27, blue -> GND
    DHT:  out -> GPIO14, + -> 3V3, - -> GND
    RTC:  SDA 21, SCL 22
    SD:   CS 5, MOSI 23, MISO 19, CLK 18

  Libraries: DHT sensor library (Adafruit) + Adafruit Unified Sensor, RTClib, SD (built-in)
*/

#include <Wire.h>
#include <RTClib.h>
#include <SPI.h>
#include <SD.h>
#include <DHT.h>
#include "driver/rtc_io.h"
#include "esp_sleep.h"
#include "esp_timer.h"
#include "esp_system.h"

// ===================== PINS =====================
#define TIPPING_BUCKET_PIN 27       // must be an RTC-capable pin (27 is)
#define DHT_PIN            14
#define DHT_TYPE           DHT11    // DHT22 for lysimeter 1, DHT11 for lysimeter 2,3 and 4
#define SD_CS_PIN          5
#define I2C_SDA            21
#define I2C_SCL            22

// ===================== SETTINGS =====================
#define SERIAL_DEBUG       true     // false = no Serial output at all (saves a little more)
#define CPU_MHZ            80
#define TIP_DEBOUNCE_MS    150      // ignore re-triggers within this window (contact bounce)
#define IDLE_AWAKE_MS      1000     // stay awake this long after the last activity
#define RELEASE_TIMEOUT_MS 5000     // max wait for the reed to open again before sleeping
#define STUCK_RETRY_SEC    60       // if the reed is stuck closed, retry after this long
#define PENDING_MAX        60       // tips kept in RTC memory while the SD card is unavailable
#define LOG_FILE           "/tips_log.csv"

#if SERIAL_DEBUG
  #define LOG(...)   Serial.print(__VA_ARGS__)
  #define LOGLN(...) Serial.println(__VA_ARGS__)
#else
  #define LOG(...)
  #define LOGLN(...)
#endif

DHT dht(DHT_PIN, DHT_TYPE);
RTC_DS3231 rtc;
bool rtcReady = false;

// ===================== DATA KEPT IN RTC MEMORY =====================
struct Rec {
  uint32_t epoch;     // seconds since 1970 (0 = no valid time)
  uint32_t total;     // tip total at that moment
  float    t, h;      // temperature / humidity (START rows only)
  uint8_t  kind;      // 0 = TIP, 1 = START
  uint8_t  dhtOK;     // START rows: 1 = DHT read worked
};
RTC_DATA_ATTR uint32_t tipTotal = 0;
RTC_DATA_ATTR uint8_t  pendN = 0;
RTC_DATA_ATTR Rec      pend[PENDING_MAX];

// ===================== TIP INTERRUPT =====================
volatile uint32_t isrTips = 0;
volatile int64_t  lastTipUs = 0;

void IRAM_ATTR onTip() {
  int64_t now = esp_timer_get_time();
  if (now - lastTipUs < (int64_t)TIP_DEBOUNCE_MS * 1000LL) return;
  lastTipUs = now;
  isrTips = isrTips + 1;
}

// ===================== TIME =====================
bool initRTC() {
  for (int a = 0; a < 4 && !rtcReady; a++) {
    rtcReady = rtc.begin();
    if (!rtcReady) delay(50);
  }
  return rtcReady;
}

uint32_t nowEpoch() {
  if (!rtcReady) return 0;
  DateTime n = rtc.now();
  if (n.year() < 2026 || n.year() > 2035) return 0;
  return n.unixtime();
}

// ===================== QUEUE =====================
void queueRec(uint8_t kind, uint32_t total, float t, float h, uint8_t dhtOK) {
  if (pendN >= PENDING_MAX) {                       // buffer full: drop the oldest
    memmove(&pend[0], &pend[1], sizeof(Rec) * (PENDING_MAX - 1));
    pendN = PENDING_MAX - 1;
  }
  Rec &r = pend[pendN++];
  r.epoch = nowEpoch();
  r.total = total;
  r.t = t;
  r.h = h;
  r.kind = kind;
  r.dhtOK = dhtOK;
}

// ===================== SD =====================
bool sdBegin() {
  for (int a = 0; a < 3; a++) {
    if (SD.begin(SD_CS_PIN, SPI, 4000000)) return true;
    SD.end();
    delay(100);
  }
  return false;
}

String formatRec(const Rec &r) {
  char buf[24];
  String ts;
  if (r.epoch == 0) {
    ts = "NO_TIME";
  } else {
    DateTime d(r.epoch);
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d",
             d.year(), d.month(), d.day(), d.hour(), d.minute(), d.second());
    ts = buf;
  }
  String line = ts;
  line += r.kind ? ",START," : ",TIP,";
  line += r.total;
  line += ',';
  if (r.kind && r.dhtOK) { line += String(r.t, 1); line += ','; line += String(r.h, 1); }
  else                   { line += "NaN,NaN"; }
  line += ',';
  String st = "";
  if (r.epoch == 0) st += "RTC_FAIL";
  if (r.kind && !r.dhtOK) { if (st.length()) st += ' '; st += "DHT_FAIL"; }
  line += st.length() ? st : String("OK");
  return line;
}

// Writes everything queued; keeps the queue if anything fails.
bool flushPending() {
  if (pendN == 0) return true;
  if (!sdBegin()) { LOGLN("[SD] card not detected, keeping tips in memory."); SD.end(); return false; }

  bool fresh = !SD.exists(LOG_FILE);
  File f = SD.open(LOG_FILE, FILE_APPEND);
  if (!f) { SD.end(); return false; }

  size_t before = f.size();
  size_t written = 0;
  if (fresh) written += f.println("timestamp,event,tips_total,temperature_C,humidity_pct,status");
  for (uint8_t i = 0; i < pendN; i++) written += f.println(formatRec(pend[i]));
  f.flush();
  f.close();
  SD.end();

  // Verify with a fresh mount: the library may report success after the card was pulled
  if (!sdBegin()) { SD.end(); return false; }
  File v = SD.open(LOG_FILE, FILE_READ);
  bool ok = v && (v.size() >= before + written);
  if (v) v.close();
  SD.end();

  if (ok) {
    LOG("[SD] wrote "); LOG(pendN); LOGLN(" row(s).");
    pendN = 0;
  } else {
    LOGLN("[SD] write not confirmed, keeping tips in memory.");
  }
  return ok;
}

// ===================== SLEEP =====================
static void goToSleep(bool stuckClosed) {
  LOGLN("Going to deep sleep...");
#if SERIAL_DEBUG
  Serial.flush();
#endif
  detachInterrupt(digitalPinToInterrupt(TIPPING_BUCKET_PIN));
  if (stuckClosed) {
    // Reed is held closed: EXT0 on LOW would wake us instantly, so use a timer instead.
    esp_sleep_enable_timer_wakeup((uint64_t)STUCK_RETRY_SEC * 1000000ULL);
  } else {
    rtc_gpio_pullup_en((gpio_num_t)TIPPING_BUCKET_PIN);     // keep the pull-up in deep sleep
    rtc_gpio_pulldown_dis((gpio_num_t)TIPPING_BUCKET_PIN);
    esp_sleep_enable_ext0_wakeup((gpio_num_t)TIPPING_BUCKET_PIN, 0);   // wake when pin goes LOW
  }
  esp_deep_sleep_start();
}

// ===================== SETUP =====================
void setup() {
  setCpuFrequencyMhz(CPU_MHZ);
#if SERIAL_DEBUG
  Serial.begin(115200);
  delay(300);
  Serial.println();
#endif

  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  bool tipWake   = (cause == ESP_SLEEP_WAKEUP_EXT0);
  bool timerWake = (cause == ESP_SLEEP_WAKEUP_TIMER);
  bool powerOn   = !tipWake && !timerWake;

  // Release the RTC pin and set it up as a normal input
  rtc_gpio_deinit((gpio_num_t)TIPPING_BUCKET_PIN);
  pinMode(TIPPING_BUCKET_PIN, INPUT_PULLUP);

  // Time stamp of the waking tip must be taken first
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setTimeOut(100);
  initRTC();

  // Debounce: ignore contact bounce right after the waking edge
  lastTipUs = esp_timer_get_time() - (tipWake ? 0 : (int64_t)(TIP_DEBOUNCE_MS + 1) * 1000LL);
  attachInterrupt(digitalPinToInterrupt(TIPPING_BUCKET_PIN), onTip, FALLING);

  if (tipWake) {
    tipTotal++;
    queueRec(0, tipTotal, NAN, NAN, 0);
    LOG("New tip detected! Total tips: "); LOGLN(tipTotal);
  }

  if (powerOn) {
    LOGLN("=== TIPPING BUCKET LOGGER (deep sleep, SD) ===");
    tipTotal = 0;
    pendN = 0;
    dht.begin();
    delay(2000);   // DHT needs a moment before its first reading is reliable
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    bool ok = !isnan(t) && !isnan(h);
    if (ok) { LOG("Temperature: "); LOG(t, 1); LOG(" C   Humidity: "); LOG(h, 1); LOGLN(" %"); }
    else    { LOGLN("DHT read FAILED at startup."); }
    queueRec(1, 0, t, h, ok ? 1 : 0);
  }

  // ---- Stay awake briefly: catch quick extra tips, write them, wait for the reed to open ----
  uint32_t handled = 0;
  bool flushTried = false;
  unsigned long lastActivity = millis();
  unsigned long releaseStart = millis();

  while (true) {
    // new tips seen by the interrupt
    uint32_t seen = isrTips;
    while (handled != seen) {
      handled++;
      tipTotal++;
      queueRec(0, tipTotal, NAN, NAN, 0);
      LOG("New tip detected! Total tips: "); LOGLN(tipTotal);
      lastActivity = millis();
    }

    bool closed = (digitalRead(TIPPING_BUCKET_PIN) == LOW);
    unsigned long now = millis();
    if (closed && (now - releaseStart) > RELEASE_TIMEOUT_MS) break;   // stuck closed
    if (!closed) releaseStart = now;
    if (!closed && (now - lastActivity) > IDLE_AWAKE_MS) {
      if (pendN > 0) {
        flushTried = true;
        flushPending();                       // SD write (tips during it are still counted)
        if (pendN > 0) break;                 // card unavailable: tips stay in memory, go to sleep
      }
      if (isrTips == handled) break;          // quiet, nothing pending: sleep
      lastActivity = millis();                // a tip arrived during the write: handle it first
    }
    delay(5);
  }

  if (!flushTried) flushPending();            // stuck-closed case: still try to save
  goToSleep(digitalRead(TIPPING_BUCKET_PIN) == LOW);
}

void loop() {
  // never reached: the board sleeps at the end of setup()
}
