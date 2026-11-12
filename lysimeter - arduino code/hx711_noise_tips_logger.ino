/*
  HX711 NOISE DIAGNOSTIC + TIPPING BUCKET - LOGS EVERY RAW SAMPLE TO SD
  ----------------------------------------------------
  Same read path as the logger v5 and hx711_sd_test_v5, but every row also
  contains ALL individual raw samples (s1..sN), so you can see the SHAPE of
  the noise instead of just its size:

    smooth slow wave in s1..sN   -> the hanging weight is swinging / vibrating
    random sample-to-sample jitter -> electronics (supply, wiring, moisture)

  One row every 10 s, appended to /hx711_samples_log.csv, runs on batteries.

  Columns:
    elapsed_sec, timestamp, temperature_C, humidity_pct, tips_10s, tips_total,
    n_valid, window_ms, avg_raw, min_raw, max_raw, spread, sd_raw, status,
    s1 ... sN

    tips_10s   = bucket tips counted since the previous row (one row / 10 s)
    tips_total = all tips since power-on / reset
    Tips are counted by an interrupt, so none are missed while the HX711
    samples are being read.

    window_ms  = time the N samples took (about N / 11.8 s on your board), so
                 sample k happened at about (k-1) * window_ms / (N-1).
    sd_raw     = standard deviation of the valid samples, in counts.
    s1..sN     = the raw values exactly as read ("NaN" = read timed out).
                 Rejected values (-1, 0, full scale) are shown but excluded
                 from avg/min/max/sd and flagged HX_RAW_SUSPECT.

  SUGGESTED RUNS (write down the clock time of each; same 5 kg every time):
    A. no load, 2 min                       -> electronics noise floor
    B. 5 kg hanging as before, 3 min         -> normal
    C. 5 kg with the swing damped, 3 min     -> rigid hanger / hand-steadied / tied
    D. optional: 100 uF + 100 nF across the HX711 VCC/GND, 5 kg, 3 min

  LED: 1 short blink = row written, 3 short blinks = SD missing / write failed.

  SD CARD PULLED: rows are kept in RAM (up to 60 = 10 min) and the card is
  re-mounted every 10 s. When it is put back, all waiting rows are written in
  order and checked by reading the file size back. Longer outages drop the oldest rows.

  Wiring: HX711 DT->GPIO32, SCK->GPIO33 | DHT out->GPIO14 | RTC SDA 21, SCL 22
          Tipping bucket reed switch: GPIO27 to GND (internal pull-up used)
          SD CS->5, MOSI 23, MISO 19, CLK 18

  Libraries: HX711 (Bogdan Necula), DHT sensor library + Adafruit Unified
             Sensor, RTClib, SD (built-in)
*/

#include <Wire.h>
#include <RTClib.h>
#include <SPI.h>
#include <SD.h>
#include <HX711.h>
#include <DHT.h>
#include <math.h>
#include "esp_system.h"
#include "esp_task_wdt.h"
 
// ===================== PINS =====================
#define HX711_DT_PIN   32
#define HX711_SCK_PIN  33
#define DHT_PIN        14
#define DHT_TYPE       DHT22   // DHT11 for lysimeters 2, 3 and 4
#define SD_CS_PIN      5
#define I2C_SDA        21
#define I2C_SCL        22
#define LED_PIN        2
#define BUCKET_PIN     27      // reed switch to GND, INPUT_PULLUP, FALLING edge

// ===================== SETTINGS =====================
#define USE_RTC               true 
#define LED_FEEDBACK          true
#define LOG_INTERVAL_MS       10000UL   // one row every 10 seconds
#define N_SAMPLES             40        // ~3.4 s window at ~11.8 samples/s
#define HX_SETTLE_MS          500
#define HX_READY_TIMEOUT_MS   400
#define TIP_DEBOUNCE_MS       200      // ignore re-triggers closer than this
#define PENDING_MAX           60       // rows kept in RAM while the SD card is missing (60 rows = 10 min)
#define HX_DISCARD            4        // conversions dropped after power-up (settling transient), same as logger v5.1
const bool POWER_CYCLE_HX711 = true;

const char *logFileName = "/hx711_tips_log.csv";   // new name: columns differ from the old file

// ===================== TIPPING BUCKET =====================
volatile uint32_t tipTotal = 0;
uint32_t lastRowTips = 0;
RTC_DATA_ATTR uint32_t rtcTips = 0;          // survives a software restart
RTC_DATA_ATTR uint32_t rtcMagic = 0;
#define RTC_MAGIC 0xC10DC4A5
volatile int64_t  lastTipUs = 0;
portMUX_TYPE tipMux = portMUX_INITIALIZER_UNLOCKED;

void IRAM_ATTR onTip() {
  int64_t now = esp_timer_get_time();
  if (now - lastTipUs < (int64_t)TIP_DEBOUNCE_MS * 1000LL) return;
  lastTipUs = now;
  tipTotal = tipTotal + 1;
}

uint32_t readTipTotal() {
  portENTER_CRITICAL(&tipMux);
  uint32_t v = tipTotal;
  portEXIT_CRITICAL(&tipMux);
  return v;
}

HX711 scale;
DHT dht(DHT_PIN, DHT_TYPE);
RTC_DS3231 rtc;
bool rtcReady = false;
bool sdOK = false;

// ===================== HELPERS =====================
void addFlag(String &flags, const char *f) {
  if (flags.length()) flags += ' ';
  flags += f;
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
  if (!LED_FEEDBACK) return;
  pinMode(LED_PIN, OUTPUT);
  for (int i = 0; i < count; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(onMs);
    digitalWrite(LED_PIN, LOW);
    if (i < count - 1) delay(offMs);
  }
}

String makeHeader() {
  String h = "elapsed_sec,timestamp,temperature_C,humidity_pct,tips_10s,tips_total,n_valid,window_ms,"
             "avg_raw,min_raw,max_raw,spread,sd_raw,status";
  for (int i = 1; i <= N_SAMPLES; i++) {
    h += ",s";
    h += i;
  }
  return h;
}

// ===================== TIME =====================
String getTimestamp(String &flags) {
#if USE_RTC
  for (int a = 0; a < 4 && !rtcReady; a++) {
    rtcReady = rtc.begin();
    if (!rtcReady) delay(50);
  }
  if (!rtcReady) {
    addFlag(flags, "RTC_FAIL");
    return "RTC_FAIL";
  }
  DateTime now = rtc.now();
  if (now.year() < 2026 || now.year() > 2035) {
    addFlag(flags, "RTC_TIME_SUSPECT");
    return "RTC_TIME_SUSPECT";
  }
  char buf[24];
  snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d",
           now.year(), now.month(), now.day(),
           now.hour(), now.minute(), now.second());
  return String(buf);
#else
  (void)flags;
  return "NO_RTC";
#endif
}

// ===================== SENSORS (one at a time) =====================
bool sampleDHTOnce(float &t, float &h) {
  dht.begin();
  t = dht.readTemperature();
  h = dht.readHumidity();
  return !isnan(t) && !isnan(h);
}

// Collects N_SAMPLES raw conversions back to back (no averaging here).
int collectSamples(long *raw, bool *ok, int &timeouts, unsigned long &windowMs) {
  timeouts = 0;
  int got = 0;

  if (POWER_CYCLE_HX711) {
    scale.power_up();
    delay(HX_SETTLE_MS);
    // first conversions after power-up are unsettled: read and drop them
    for (int d = 0; d < HX_DISCARD; d++) {
      if (scale.wait_ready_timeout(HX_READY_TIMEOUT_MS)) scale.read();
    }
  }

  unsigned long t0 = millis();
  for (int i = 0; i < N_SAMPLES; i++) {
    if (scale.wait_ready_timeout(HX_READY_TIMEOUT_MS)) {
      raw[i] = scale.read();
      ok[i] = true;
      got++;
    } else {
      raw[i] = 0;
      ok[i] = false;
      timeouts++;
    }
  }
  windowMs = millis() - t0;

  if (POWER_CYCLE_HX711) scale.power_down();
  return got;
}

// ===================== SD (last, sensors already off) =====================
// Rows wait in RAM until they are verified on the card, so pulling the card
// and putting it back loses nothing (up to PENDING_MAX rows = 10 minutes).
String pendingRows[PENDING_MAX];
int pTail = 0;          // oldest waiting row
int pendingCount = 0;
uint32_t droppedRows = 0;

void queueRow(const String &line) {
  if (pendingCount == PENDING_MAX) {          // buffer full: drop the oldest row
    pTail = (pTail + 1) % PENDING_MAX;
    pendingCount--;
    droppedRows++;
  }
  pendingRows[(pTail + pendingCount) % PENDING_MAX] = line;
  pendingCount++;
}

// Raw SPI check, independent of the SD library: does a card answer CMD0?
bool sdCardResponds() {
  SPI.end();
  SPI.begin(18, 19, 23, SD_CS_PIN);            // SCK, MISO, MOSI, SS
  pinMode(SD_CS_PIN, OUTPUT);
  digitalWrite(SD_CS_PIN, HIGH);
  SPI.beginTransaction(SPISettings(400000, MSBFIRST, SPI_MODE0));
  for (int i = 0; i < 10; i++) SPI.transfer(0xFF);   // 80 clocks with CS high
  digitalWrite(SD_CS_PIN, LOW);
  SPI.transfer(0xFF);
  const uint8_t cmd0[6] = {0x40, 0x00, 0x00, 0x00, 0x00, 0x95};
  for (int i = 0; i < 6; i++) SPI.transfer(cmd0[i]);
  uint8_t r = 0xFF;
  for (int i = 0; i < 10 && r == 0xFF; i++) r = SPI.transfer(0xFF);
  digitalWrite(SD_CS_PIN, HIGH);
  SPI.transfer(0xFF);
  SPI.endTransaction();
  return r == 0x01;                            // 0x01 = card present, idle
}

// Fresh mount every time, with escalating recovery: normal -> SPI bus reset
// at lower speed -> SPI bus reset at 400 kHz-ish speed.
bool sdBegin() {
  const uint32_t freq[3] = {4000000, 1000000, 400000};
  for (int a = 0; a < 3; a++) {
    SD.end();
    if (a > 0) {
      SPI.end();
      SPI.begin(18, 19, 23, SD_CS_PIN);
    }
    delay(a ? 150 : 20);
    if (SD.begin(SD_CS_PIN, SPI, freq[a]) && SD.cardType() != CARD_NONE) return true;
  }
  SD.end();
  return false;
}

// Last resort when a card answers on the bus but the SD library will not mount
// it (stuck state after hot-swap). The tip total survives in RTC memory.
void saveAndRestart() {
  rtcTips = readTipTotal();
  rtcMagic = RTC_MAGIC;
  Serial.println("[SD] card answers but will not mount -> restarting ESP32 (tip total kept)");
  Serial.flush();
  delay(100);
  ESP.restart();
}
int stuckCount = 0;

// Writes ALL waiting rows, then remounts and checks the file really grew.
// Only if that check passes are the rows removed from RAM.
bool flushPending() {
  if (pendingCount == 0) return true;
  if (!sdBegin()) {
    if (sdCardResponds()) {
      if (++stuckCount >= 2) saveAndRestart();
    } else {
      stuckCount = 0;                          // no card in the slot: just wait
    }
    return false;
  }
  stuckCount = 0;

  if (!SD.exists(logFileName)) {
    File h = SD.open(logFileName, FILE_WRITE);
    if (!h) { SD.end(); return false; }
    h.println(makeHeader());
    h.close();
  }

  File f = SD.open(logFileName, FILE_APPEND);
  if (!f) { SD.end(); return false; }
  size_t before = f.size();
  size_t expected = 0;
  bool good = true;
  int n = pendingCount;
  for (int i = 0; i < n && good; i++) {
    const String &r = pendingRows[(pTail + i) % PENDING_MAX];
    size_t w = f.println(r);
    if (w < r.length() + 1) good = false;      // println adds at least a newline
    expected += w;
  }
  f.flush();
  if (f.getWriteError()) good = false;
  f.close();
  if (!good) { SD.end(); return false; }

  // Verify: remount and read the size back from the card itself
  if (!sdBegin()) return false;
  File v = SD.open(logFileName, FILE_READ);
  if (!v) { SD.end(); return false; }
  size_t after = v.size();
  v.close();
  SD.end();
  if (after < before + expected) return false;

  pTail = (pTail + n) % PENDING_MAX;           // verified: forget these rows
  pendingCount -= n;
  return true;
}

// ===================== SETUP =====================
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== HX711 NOISE DIAGNOSTIC (all raw samples to SD) ===");
  Serial.printf("Reset reason: %s | %d samples per row, one row / %lu s\n",
                resetTag(), N_SAMPLES, LOG_INTERVAL_MS / 1000UL);

#if USE_RTC
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setTimeOut(100);
#endif

  if (esp_reset_reason() == ESP_RST_SW && rtcMagic == RTC_MAGIC) {
    tipTotal = rtcTips;                        // restart caused by SD recovery: keep the count
    lastRowTips = rtcTips;
    Serial.printf("Tip total restored after restart: %lu\n", (unsigned long)rtcTips);
  }
  rtcMagic = 0;

  // Watchdog: if anything ever hangs (e.g. SD library), restart after 60 s
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t wc = {60000, 0, true};
  if (esp_task_wdt_reconfigure(&wc) != ESP_OK) esp_task_wdt_init(&wc);
#else
  esp_task_wdt_init(60, true);
#endif
  esp_task_wdt_add(NULL);

  scale.begin(HX711_DT_PIN, HX711_SCK_PIN);
  if (!POWER_CYCLE_HX711) {
    scale.power_up();
    delay(HX_SETTLE_MS);
  }

  pinMode(BUCKET_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(BUCKET_PIN), onTip, FALLING);

  dht.begin();
  delay(2000);   // DHT warm-up before the first read

  sdOK = sdBegin();
  SD.end();
  Serial.println(sdOK ? "SD card OK." : "SD card NOT detected (rows are kept in RAM, retry every cycle).");
  if (!sdOK) blinkLED(3, 100, 100);
  Serial.println();
}

// ===================== LOOP =====================
void loop() {
  esp_task_wdt_reset();
  static unsigned long nextRun = 0;
  static bool firstRow = true;

  if ((long)(millis() - nextRun) < 0) return;
  nextRun = millis() + LOG_INTERVAL_MS;   // fixed period, no drift

  String flags = "";
  if (firstRow) addFlag(flags, resetTag());

  // 1) RTC, 2) DHT, 3) HX711 -- one after the other
  String ts = getTimestamp(flags);

  float t, h;
  bool dhtOK = sampleDHTOnce(t, h);
  if (!dhtOK) addFlag(flags, "DHT_FAIL");

  long raw[N_SAMPLES];
  bool ok[N_SAMPLES];
  int timeouts;
  unsigned long windowMs;
  collectSamples(raw, ok, timeouts, windowMs);

  // Statistics over valid samples only
  int nValid = 0, suspect = 0;
  long mn = 0, mx = 0;
  double sum = 0, sumSq = 0;
  for (int i = 0; i < N_SAMPLES; i++) {
    if (!ok[i]) continue;
    long r = raw[i];
    if (r == -1 || r == 0 || r >= 8388607L || r <= -8388608L) {
      suspect++;
      continue;
    }
    if (nValid == 0 || r < mn) mn = r;
    if (nValid == 0 || r > mx) mx = r;
    sum += r;
    sumSq += (double)r * (double)r;
    nValid++;
  }
  double mean = nValid ? sum / nValid : 0;
  double var  = nValid > 1 ? (sumSq - nValid * mean * mean) / (nValid - 1) : 0;
  if (var < 0) var = 0;
  double sd = sqrt(var);

  if (nValid < N_SAMPLES) addFlag(flags, (String("HX_") + nValid + "of" + N_SAMPLES).c_str());
  if (suspect > 0)        addFlag(flags, "HX_RAW_SUSPECT");
  if (timeouts > 0)       addFlag(flags, "HX_TIMEOUT");
  String status = flags.length() ? flags : String("OK");

  // Tips since the previous row (snapshot taken now, after the HX711 window)
  uint32_t tipsNow = readTipTotal();
  uint32_t tipsInterval = tipsNow - lastRowTips;
  lastRowTips = tipsNow;

  // Build the CSV row
  String line;
  line.reserve(64 + N_SAMPLES * 9);
  line += millis() / 1000UL;
  line += ',';
  line += ts;
  line += ',';
  line += dhtOK ? String(t, 1) : String("NaN");
  line += ',';
  line += dhtOK ? String(h, 1) : String("NaN");
  line += ',';
  line += tipsInterval;
  line += ',';
  line += tipsNow;
  line += ',';
  line += nValid;
  line += ',';
  line += windowMs;
  line += ',';
  line += nValid ? String((long)(mean + (mean >= 0 ? 0.5 : -0.5))) : String("NaN");
  line += ',';
  line += nValid ? String(mn) : String("NaN");
  line += ',';
  line += nValid ? String(mx) : String("NaN");
  line += ',';
  line += nValid ? String(mx - mn) : String("NaN");
  line += ',';
  line += nValid ? String(sd, 1) : String("NaN");
  line += ',';
  line += status;
  for (int i = 0; i < N_SAMPLES; i++) {
    line += ',';
    if (ok[i]) line += raw[i];
    else       line += "NaN";
  }

  // Short summary on Serial (the full row goes to the SD card)
  Serial.printf("%s | tips=%lu (total %lu) | n=%d avg=%ld min=%ld max=%ld spread=%ld sd=%.1f window=%lums | %s\n",
                ts.c_str(), (unsigned long)tipsInterval, (unsigned long)tipsNow, nValid, (long)mean, mn, mx, mx - mn, sd, windowMs, status.c_str());

  // 4) SD last: queue the row, then try to write everything that is waiting
  queueRow(line);
  int waitingBefore = pendingCount;
  bool writeOK = flushPending();
  if (writeOK) {
    if (!sdOK) Serial.printf("[SD] card back - wrote %d buffered row(s).\n", waitingBefore);
    sdOK = true;
  } else {
    sdOK = false;
    Serial.printf("[SD] card missing / write failed - %d row(s) waiting in RAM (%lu dropped).\n",
                  pendingCount, (unsigned long)droppedRows);
  }

  if (writeOK) blinkLED(1, 100, 0);
  else         blinkLED(3, 100, 100);

  firstRow = false;
}
