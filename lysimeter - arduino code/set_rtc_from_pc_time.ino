/*
  Set time on the HW-450 "ChronoDor" RTC module
  (this board uses a DS3231 chip internally -- RTC_DS3231 is correct)
  
  This version sets the RTC to your PC's current clock automatically,
  using the compiler's __DATE__ and __TIME__ macros -- no manual typing
  of numbers needed. These get filled in with your computer's clock at
  the moment the sketch is COMPILED (just before/during upload), so:
        
    - Make sure your PC's clock (and timezone) is actually correct before
      uploading -- this reads your PC's system clock, not an internet time
      server. 
    - There's a small lag between compile time and the moment the RTC
      actually receives the command (compile + upload + boot), typically
      a few seconds. Fine for this project, but don't expect sub-second
      accuracy.  
    - Every time you re-upload this exact sketch, it will reset the RTC
      to whatever your PC's clock says AT THAT MOMENT -- so only upload
      it when you actually want to (re)sync the time, not as your normal
      deployment sketch.
*/
 
#include <Wire.h>
#include <RTClib.h>
    
RTC_DS3231 rtc; // HW-450 / ChronoDor is DS3231-based, this is the right class
    
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
        
  Wire.begin(21, 22); // SDA, SCL
   
  if (!rtc.begin()) { 
    Serial.println("ERROR: RTC not found. Check SDA/SCL/VCC/GND wiring.");
    while (1) delay (1000);
  }
  Serial.println("RTC found.");
   
  Serial.print("Coin cell backup status: ");
  Serial.println(rtc.lostPower() ? "LOST POWER (check coin cell)" : "OK");
   
  // ---- Set the time from your PC's clock at compile time ----
  // DateTime(__DATE__, __TIME__) parses the compiler-generated strings
  // (e.g. "Sep 28 2026" and "20:16:03") straight into a DateTime.
  rtc.adjust(DateTime(__DATE__, __TIME__));
  Serial.println("Time has been set from PC compile time.");
  Serial.print("Compile timestamp used: ");
  Serial.print(__DATE__);
  Serial.print(" ");
  Serial.println(__TIME__);

  DateTime now = rtc.now();
  Serial.printf("RTC now reads: %04d-%02d-%02d %02d:%02d:%02d\n",
                 now.year(), now.month(), now.day(),
                 now.hour(), now.minute(), now.second());
}
  
void loop() {
  DateTime now = rtc.now();
  Serial.printf("%04d-%02d-%02d %02d:%02d:%02d\n",
                 now.year(), now.month(), now.day(),
                 now.hour(), now.minute(), now.second());
  delay(2000);
}
