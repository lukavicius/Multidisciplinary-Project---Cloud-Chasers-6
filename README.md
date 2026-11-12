# CloudChasers: water balance and lysimeter research code

Code for a field research project on the water balance of three land-use plots in Alta Verapaz, Guatemala:

| Code | Plot |
|---|---|
| **CF** | Cloud forest |
| **AF** | Agroforestry |
| **CA** | Conventional agriculture (maize) |

The repository has three parts:

1. **Water balance analysis.** Evapotranspiration, canopy interception, fog deposition and infiltration per plot, from the field loggers and weather stations.
2. **Epiphyte lysimeter development.** ESP32 firmware for a low-cost weighing lysimeter (HX711 load cell, tipping bucket, DHT, RTC, SD), plus notebooks for load-cell calibration, drift tests and field analysis.
3. **Mayfly datalogger setup.** Firmware for the four EnviroDIY Mayfly loggers (tipping buckets and box temperature/humidity) and a notebook to check their output.

The data come from Mayfly, HOBO and LogTag loggers, a WeatherFlow Tempest station, an Ambient Weather station, fog traps, field infiltration tests and ERA5 reanalysis. All times are Guatemala local time (UTC−6) unless a script says otherwise.

---

## Repository layout

```
.
├── analysis/                       Dashboard launcher (reads logger files from the team Google Drive)
├── data retrieval/                 Download scripts for the Tempest and Ambient Weather APIs
├── datalogger/mayfly/              Mayfly firmware (mayfly1-4) + rain gauge analysis notebook
├── lysimeter - arduino code/       ESP32 lysimeter firmware and bench-test sketches
├── lysimeter - field analysis/     Load-cell calibration, drift tests, lysimeter field analysis, AF fog model
└── water balance/                  ET0, Kc, interception, fog, infiltration and plot-level water balance
```

---

## 1. Water balance (`water balance/`)

The notebooks and scripts each compute one term of the water balance. Roughly in the order they are run:

| File | What it does |
|---|---|
| `temp_rh_soilmoisture_TF.py` | Loads the dashboard exports (15 min, daily, raw), builds per-plot subsets for CF, AF and CA (e.g. AF air temperature and rain as the mean of Tempest and Ambient), and delineates rainfall events with their post-event drying periods. |
| `Evapotranspiration_FAO56_hourly.ipynb` | Hourly grass-reference ET₀ with FAO-56 Penman–Monteith. Writes `ET0_results_hourly.csv`. |
| `ET_coefficient_Kc_AF_CF.ipynb` | Crop coefficient K_c for AF (and CF) from the plot's species mix and mean climate, using the FAO-56 adjustment equations. |
| `ET_coefficient_Kc_curve_CA.ipynb` | FAO-56 K_c curve for the maize at CA (stage lengths from Table 11, K_c,ini from Fig. 29, Eq. 66 daily curve), including the post-harvest phase. |
| `Evapotranspiration_sensitivity_analysis.ipynb` | One-at-a-time sensitivity of ET_c = K_c · ET₀ to the uncertain inputs, per plot. |
| `interception.evapo_storage.change.ipynb` | Hourly potential wet-canopy evaporation E₀ with FAO-56 Penman–Monteith (r_s = 0), then a canopy interception bucket (S_max per plot) giving interception evaporation E_i, canopy storage change and modelled throughfall P_e for CF, AF and CA. |
| `fog.FIESTA_adapted.ipynb` | Flags fog hours at the CF tower (T − T_d ≤ 0.3 °C and no recent rain) and runs FIESTA with ERA5 wind to estimate hourly fog deposition. Compares the result with the fog traps and includes a sensitivity analysis on the fog threshold and wind speed. |
| `infiltration_curve.py` | Fits a Horton curve to the pour-by-pour infiltration tests and builds one f(θ) capacity line per plot. For AF and CA the line runs from the ambient point (mean first-pour rate) to the wet point (mean f_c at the wettest θ the sensor recorded). CF has no field tests, so its line uses literature values. |
| `water_balance_infiltration.py` | Applies each plot's f(θ) curve to hourly soil moisture: I = min(q_in, f(θ)·Δt). Runs this for the measured input (TF + SF, or P at CA) and for the modelled P_e, giving infiltration-excess runoff per plot. Imports `f_theta` from `infiltration_curve.py`. |

### Data flow

```
loggers + Tempest/Ambient ──► temp_rh_soilmoisture_TF.py
                          └─► Evapotranspiration_FAO56_hourly ──► ET0_results_hourly.csv
                                                                    ├─► ET_coefficient_Kc_*  ──► ET_c
                                                                    └─► sensitivity analysis
loggers + ERA5 wind ─────► interception.evapo_storage.change ──► E_i, ΔS_i, P_e (hourly, per plot)
CF tower + ERA5 ─────────► fog.FIESTA_adapted ──► fog deposition
infiltration test sheet ─► infiltration_curve.py ──► f(θ) per plot
                                    └──────────────► water_balance_infiltration.py ◄── P_e, TF, SF, θ
                                                         └─► infiltration, runoff (input to the plot water balance)
```

### Running

Most notebooks have one settings cell at the top (file names, period, plot parameters). Edit it, then **Run All**. The scripts run from the command line:

```bash
cd "water balance"
python infiltration_curve.py path/to/infiltration_tests.xlsx
python water_balance_infiltration.py
```

`infiltration_curve.py` writes to `infiltration_results/` next to the input Excel file. `water_balance_infiltration.py` writes to `water_balance_results/` next to the script.

---

## 2. Epiphyte lysimeter

A small weighing lysimeter that hangs an epiphyte sample from a load cell and logs its weight, so that rain, fog, drainage and evaporation can be separated.

### Firmware (`lysimeter - arduino code/`)

ESP32 sketches (Arduino IDE). Libraries: `RTClib`, `HX711` (bogde), Adafruit `DHT sensor library` + `Adafruit Unified Sensor`, `SD` (built in).

| Sketch | Purpose |
|---|---|
| `field_logger_v5_4_efficient_bridge_off.ino` | **Current deployment logger.** Deep sleep, wakes on each bucket tip (ext0) and every 15 min to read the DHT, HX711 and DS3231 and append to `/field_log.csv`. CPU at 80 MHz, radios off, and the load-cell bridge is switched off through a logic-level MOSFET (IRLZ44N or similar) in its ground line while asleep. |
| `field_logger_v5_3_efficient.ino` | v5.3: same as above without the bridge MOSFET. |
| `field_logger_v5_1.ino` | v5.1: first stable field version (fixes the v4 divide-by-zero crash loop, staggered power, HX711 timeouts, reset reason logged). |
| `tipping_bucket_deepsleep_sd.ino` | Stand-alone tipping-bucket logger: wakes on a tip, writes a timestamped row to `/tips_log.csv`, and buffers tips in RTC memory if the SD card fails. |
| `hx711_sd_samples_v5_1.ino` | Noise diagnostic: logs every individual HX711 sample every 10 s, to tell mechanical swinging apart from electrical noise. |
| `hx711_noise_tips_logger.ino` | Same diagnostic with tip counting added. |
| `impact_testing.ino` | Prints an averaged raw HX711 reading every second, for bench and impact tests. |
| `set_rtc_from_pc_time.ino` | Sets the DS3231 RTC to the PC clock at compile time. Upload once, then upload the logger. |

Default wiring (check against your board before deploying):

| Part | ESP32 pin |
|---|---|
| HX711 DT / SCK | GPIO32 / GPIO33 |
| DHT data | GPIO14 |
| Tipping bucket (reed switch to GND) | GPIO27 |
| Bridge MOSFET gate (v5.4) | GPIO26 (100 Ω series, 100 kΩ to GND) |
| SD card | CS 5, MOSI 23, MISO 19, CLK 18 |
| RTC (I²C) | SDA 21, SCL 22 |

**Before deploying a logger:**

1. Set the RTC with `set_rtc_from_pc_time.ino`.
2. Upload the logger with `TEST_MODE true`, open the Serial Monitor at 115200 baud and watch a few cycles. Check `field_log.csv` on the card.
3. Calibrate the load cell and enter `CAL_OFFSET` / `CAL_FACTOR`. Calibrate on the **same power supply** (the span moved about 3.5 % between USB and battery) and, for v5.4, with the same `BRIDGE_WARMUP_MS` you deploy with. With `CAL_FACTOR = 0` the raw ADC is still logged and the weight is `NaN` (`NO_CAL`).
4. Set `TEST_MODE false` (15-min cycles) and upload again.

### Analysis (`lysimeter - field analysis/`)

| File | What it does |
|---|---|
| `adc/load_cell_zero_drift-lys{1,2}.ipynb` | Overnight unloaded run: raw ADC zero over time, spike flagging (rolling median + MAD) and the share of drift explained by temperature. |
| `adc/load_cell_sensitivity_analysis-lys{1,2}.ipynb` | Compares calibration methods (single linear slope vs. temperature-corrected variants) using two sessions at different temperatures, and sets the accuracy floor from hysteresis, repeatability and zero return. |
| `lysimeter_evap/test/lysimeter_plots-lys{1,2}.ipynb` | Bench/test-period plots: logged variables, raw vs. temperature-corrected weight, fog periods. |
| `lysimeter_evap/field/lysimeter_field_analysis.ipynb` | Field water balance per 15-min interval: ET = P_epi − D_epi − ΔS_epi/Δt. |
| `lysimeter_evap/field/lysimeter_analysis-lys{1,2}.ipynb` | Reproduces the report *Epiphyte lysimeter: first field results*: calibration W = (ADC − ADC₀ − αΔT)·S / (1 + βΔT), alignment with Tempest and fog data, storm events, water balance, fog and evaporation, data-quality checks. Figures and tables go to `lysimeter_outputs/`. |
| `fog_epiphyte.py` | FIESTA fog interception at AF on a 15-min step, driven by the Tempest station (no fog trap at AF, so no validation). Writes `fog_AF_15min.csv`, which the lysimeter notebooks read. |
| `merge.ipynb` | Joins two lysimeter logger exports into one file (edit the hard-coded paths first). |

---

## 3. Mayfly dataloggers (`datalogger/mayfly/`)

Firmware for four EnviroDIY Mayfly v1.1 boards. Each logs battery voltage, box air temperature/humidity from the on-board SHT40, and tip counts from its tipping buckets every 15 minutes to `MAYFLYn.CSV` on the SD card.

| Sketch | Tipping buckets (pin) |
|---|---|
| `mayfly1/mayfly1.ino` | TB1 (D5), TB2 (D10), TB3 (D6), TB4 (D11) |
| `mayfly2/mayfly2.ino` | TB5 (D10), TB9 (D4) |
| `mayfly3/mayfly3.ino` | TB6 (D10), TB7 (D11) |
| `mayfly4/mayfly4.ino` | TB8 (D10) |

In `temp_rh_soilmoisture_TF.py`, Mayfly 1 is assigned to AF, Mayfly 2 to CA, and Mayflies 3 and 4 to CF.

Libraries: `Sodaq_DS3231`, `LowPower`, `EnableInterrupt`, `SD`, and `Adafruit SHT4x Library` (accept the prompt to also install Adafruit BusIO / Unified Sensor). Select the EnviroDIY Mayfly board in the Arduino IDE.

Notes:

- The RTC is only set from the compile time when it looks unset, not on every boot.
- The soil moisture sensors (EC-5 and 5TM) were removed in the current versions, so their columns are gone. CSVs from older firmware cannot be appended to new ones without matching the columns first.
- Check `LOG_INTERVAL_MIN` (15 for deployment, 1 for testing) before uploading.

`mayfly_analysis.ipynb` analyses one logger's tipping-bucket data. Set the file (wildcards like `MAYFLY4_*.CSV` work for split files) and the period in the INPUTS cell, then Run All.

---

## Data retrieval and dashboard

- `data retrieval/tempest_tzcorrected.py` downloads the last `DAYS_HISTORY` days from the WeatherFlow Tempest REST API and converts the timestamps to local time.
- `data retrieval/ambientw.ipynb` downloads Ambient Weather data and resamples it to 15 min (the API allows about one request per second).
- `analysis/analysis_tool.py` launches the team dashboard. It fetches the dashboard code (`readplot.py`) from the shared Google Drive and runs it, and the dashboard reads Mayfly, HOBO and Tempest files directly from Drive. See [`analysis/README.md`](analysis/README.md) for setup.

---

## Setup

Python 3.10 or newer. The analysis code uses:

```bash
pip install numpy pandas scipy matplotlib openpyxl requests jupyter
```

The dashboard has its own `analysis/requirements.txt`.

Firmware needs the Arduino IDE with the ESP32 board package (lysimeter) or the EnviroDIY Mayfly board package (Mayfly), plus the libraries listed above.

### Known gaps

- `cc_colors.py` (the CloudChasers colour palette and plot style) is imported by `water_balance_infiltration.py`, `fog.FIESTA_adapted.ipynb` and `interception.evapo_storage.change.ipynb`, but is not in this repository. They expect it in the parent folder (`codeWB/`).
- Several input paths point to a `codeWB/` layout (e.g. `../codeWB/interception/outputs_v2/`) or to absolute paths on one machine. Adjust them in each file's settings block.
- Raw logger data are not all included. Most come from the team Google Drive.

### Credentials

- `data retrieval/tempest_tzcorrected.py` and `data retrieval/ambientw.ipynb` ship with `"XXXX"` placeholders. Put your own Tempest token and Ambient Weather API/application keys there locally, and don't commit them.
- The dashboard needs `credentials.json` (from the project owner) and creates `token.json` on first login. Both are in `.gitignore`. Never share or commit them.
- `analysis_tool.py` runs whatever `readplot.py` and `requirements.txt` are in the Drive folder. Only trusted team members should have edit access to `analysis_tool_code`.

---

## Acknowledgments

This project was carried out by:

- _Tadas Lukavicius_ 
- _Mei Yue Wong_ 
- _Elena Deckert_
- _Diane Bilgischer_
- _Victoria Mauguit_
- _Jay van Dam_


