"""
FIESTA fog interception at the AGROFORESTRY plot (AF) - 15 min
===============================================================
Same model as foginput.ipynb (CF), adapted to AF:
  * fog detection, rain filter and (optionally) wind from the TEMPEST station
  * AF site parameters (tree cover, LAI, tree/crop height ...) in SETTINGS
  * no fog trap at AF -> model estimate only, no validation

Run in VS Code:  python fog_AF.py
Outputs (next to this script): fog_AF_15min.csv, fog_AF_summary.csv, fog_AF_15min.png
"""
import io
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = Path(__file__).resolve().parent

# =====================================================================
# SETTINGS - edit here
# =====================================================================
DATA_FILE = HERE / "tempest.csv"
TIME_COL  = "timestamp"
TZ        = "America/Guatemala"
STEP      = "15min"              # model time step (data are logged every 15 min)
STEP_H    = pd.Timedelta(STEP) / pd.Timedelta("1h")

# Model window (local time): Friday 12:00 -> Sunday 05:00
START = "2026-10-08 12:00"
END   = "2026-10-29 16:00"          # last step included starts at 04:45

COL = dict(
    T        = "temperature",
    RH       = "humidity",
    rain     = "precip",
    wind_spd = "wind_avg",
    wind_dir = "wind_dir",
)

# --- Fog detection ---------------------------------------------------
# The Tempest RH sensor saturates at 98 %. At RH = 98 % the dew-point
# depression is ~0.32 degC, so the CF rule (T - Td <= 0.3 degC) would NEVER
# detect fog here. Fog is therefore defined as RH at the sensor maximum.
RH_FOG       = 98.0     # fog if mean RH of the step >= RH_FOG [%]
DRY_BUFFER_H = 2        # and no rain in this step nor the previous N hours
RAIN_MIN_MM  = 0.0      # rain per step above this counts as "rain" (Tempest haptic sensor can log tiny amounts)

# --- Wind used by FIESTA ---------------------------------------------
WIND_SOURCE = "csv"     # "csv"     = hourly 10 m wind from a downloaded Open-Meteo csv (WIND_FILE)
                        # "era5"    = ERA5 10 m reference wind via the Open-Meteo API (same as CF, needs internet)
                        # "tempest" = Tempest station wind (5.5 m, below the tree tops)
WIND_FILE   = HERE / "open-meteo-15.36N90.34W1628m.csv"   # EDIT: name of the downloaded Open-Meteo csv
LAT, LON    = 15.364401682593286, -90.34411492229958   # EDIT: AF plot coordinates
ERA5_MODEL  = "best_match"

# --- AF site parameters (EDIT - values below are placeholders) -------
TreeFrac   = 0.5        # fraction of the plot under tree canopy [0-1]
FracForest = TreeFrac   # fraction with trees used for leaf trapping (normally = TreeFrac)
LAI_AF     = 3.0        # leaf area index of the AF trees
lss_AF     = -0.7 * 0.3 * 10   # leaf self-shading (same form as CF)
H_TREE     = 8.0        # mean tree height at the edge [m]   (CF: 10 m)
H_EMERGENT = 2.0        # emergent part above the canopy [m] (CF: 2 m)
H_CROP     = 1.5        # height of the crop / understory between the trees [m] (FIESTA "grass", default 0.5 m)
CellSize   = 10000      # cell area [m2]; keep as at CF - with TreeFrac < 1 the result depends on it
Slope_deg  = 20         # plot slope [deg]
Aspect     = 90         # plot aspect [deg]: N=0, E=90, S=180, W=270

droplet_size = 7.5      # fog droplet size [um]
LWC          = 0.0002   # liquid water content [kg m-3]

# =====================================================================
# FIESTA (same equations as the CF notebook, heights made configurable)
# =====================================================================
def fog_settling_vel(d_um):
    g, rho_w, rho_a, mu = 9.81, 1000, 1.2, 1.85e-5
    d = d_um * 1e-6
    return g * d**2 * (rho_w - rho_a) / (18 * mu)


def forest_edge(tree_frac, cell_area):
    edge_frac = -0.0001 * (tree_frac * 100) ** 2 + 0.0144 * (tree_frac * 100)
    edge_len = edge_frac * np.sqrt(cell_area) * 4
    emergent_len = 0.15 * tree_frac * np.sqrt(cell_area) * 4
    return edge_len / 4, emergent_len / 4          # lengths facing the wind


def deposition_fraction(frac, lai, lss):
    return frac * (1 - np.exp(lss)) * lai


def wind_adjust(wind_dir, wind_spd, aspect):
    d = aspect - wind_dir
    return wind_spd * abs(np.cos(np.radians(d / 2)))


def fog_deposition_mm(wind_speed, wind_dir, fog=1, hours=1.0):
    u = wind_adjust(wind_dir, wind_speed, Aspect)
    red_forest, red_grass = 0.6053, 0.5030

    # edge and emergent impaction
    edge_flux = LWC * (u * red_forest * 3600) * EDGE_LEN * H_TREE
    emerg_flux = LWC * (u * 3600) * EMERG_LEN * H_EMERGENT

    ang_forest = math.atan((u * red_forest) / V_SETTLE)
    ang_grass = math.atan((u * red_grass) / V_SETTLE)
    depos_prop = math.cos(ang_forest) * TreeFrac + math.cos(ang_grass) * (1 - TreeFrac)
    impact_prop = 1 - depos_prop

    # settling on leaves
    settling_flux = LWC * (V_SETTLE * 3600) * CELL_TRUE_AREA
    depos = fog * settling_flux * depos_prop * DEP_FRAC

    # impaction on crop / understory ("grass" in FIESTA)
    grass_flux = LWC * (u * red_grass * 3600) * (1 - TreeFrac) * CellSize * H_CROP

    trap_area = 1 - np.exp((-0.7 * 0.3 * TreeFrac) / math.cos(ang_forest))
    impaction = fog * (edge_flux + emerg_flux + grass_flux) * impact_prop * trap_area   # AirRising = 1

    return (depos + impaction) / CELL_TRUE_AREA * hours     # mm


CELL_TRUE_AREA = CellSize / math.cos(math.radians(Slope_deg))
V_SETTLE = fog_settling_vel(droplet_size)
EDGE_LEN, EMERG_LEN = forest_edge(TreeFrac, CellSize)
DEP_FRAC = deposition_fraction(FracForest, LAI_AF, lss_AF)

# =====================================================================
# Data
# =====================================================================
def load_data():
    d = pd.read_csv(DATA_FILE, parse_dates=[TIME_COL]).set_index(TIME_COL).sort_index()
    spd, ang = d[COL["wind_spd"]], np.radians(d[COL["wind_dir"]])
    h = pd.DataFrame({
        "T_C":       d[COL["T"]].resample(STEP).mean(),
        "RH_pct":    d[COL["RH"]].resample(STEP).mean(),
        "rain_mm":   d[COL["rain"]].resample(STEP).sum(min_count=1),
        "wind_tempest_ms": spd.resample(STEP).mean(),
    })
    u = (spd * np.sin(ang)).resample(STEP).mean()
    v = (spd * np.cos(ang)).resample(STEP).mean()
    h["wdir_tempest_deg"] = (np.degrees(np.arctan2(u, v)) + 360) % 360
    h.index = h.index.tz_localize(TZ)
    return h


def read_open_meteo_csv(path):
    """Open-Meteo csv export: metadata lines, then one table per block (15-minutely,
    hourly, daily ...), each starting with a 'time,...' header and ending at a blank line.
    Returns the block that has wind_speed_10m (the finest one if several)."""
    meta = pd.read_csv(path, nrows=1, encoding="utf-8-sig")
    tz_file = meta["timezone"].iloc[0] if "timezone" in meta else TZ

    blocks, cur = [], None
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("time,"):
            cur = [line]
            blocks.append(cur)
        elif cur is not None and line.strip():
            cur.append(line)
        else:
            cur = None

    tables = []
    for b in blocks:
        t = pd.read_csv(io.StringIO("\n".join(b)))
        names, units = {}, {}
        for c in t.columns:                      # "wind_speed_10m (m/s)" -> "wind_speed_10m", "m/s"
            name, _, unit = c.partition(" (")
            names[c], units[name.strip()] = name.strip(), unit.rstrip(")")
        t = t.rename(columns=names)
        if "wind_speed_10m" not in t:            # e.g. a daily block (wind_speed_10m_max)
            continue
        for c in ("wind_speed_10m", "wind_gusts_10m"):
            if c in t and units[c] == "km/h":    # Open-Meteo default unit
                t[c] = t[c] / 3.6
            elif c in t and units[c] != "m/s":
                raise ValueError(f"{c} is in {units[c]}; download it in m/s or km/h")
        t["time"] = pd.to_datetime(t["time"]).dt.tz_localize(tz_file).dt.tz_convert(TZ)
        tables.append(t.set_index("time").sort_index())
    if not tables:
        raise ValueError(f"No 'wind_speed_10m' column found in {Path(path).name}")
    return min(tables, key=lambda t: t.index.to_series().diff().median())   # finest time step


def add_wind(h):
    if WIND_SOURCE == "tempest":
        h["wind_spd_ref"], h["wind_dir_ref"] = h["wind_tempest_ms"], h["wdir_tempest_deg"]
        print("Wind: Tempest station (5.5 m)")
        return h
    if WIND_SOURCE == "csv":
        om = read_open_meteo_csv(WIND_FILE)
        src = f"Open-Meteo csv {WIND_FILE.name}"
    else:
        import requests
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=dict(
            latitude=LAT, longitude=LON,
            start_date=h.index.min().strftime("%Y-%m-%d"), end_date=h.index.max().strftime("%Y-%m-%d"),
            hourly="wind_speed_10m,wind_direction_10m", wind_speed_unit="ms",
            timezone=TZ, models=ERA5_MODEL), timeout=60)
        r.raise_for_status()
        om = pd.DataFrame(r.json()["hourly"])
        om["time"] = pd.to_datetime(om["time"]).dt.tz_localize(TZ)
        om = om.set_index("time")
        src = f"ERA5 10 m ({ERA5_MODEL})"
    om = om.rename(columns={"wind_speed_10m": "wind_spd_ref",
                            "wind_direction_10m": "wind_dir_ref",
                            "wind_gusts_10m": "wind_gust_ref"})       # gusts kept for reference only
    om = om[[c for c in ("wind_spd_ref", "wind_dir_ref", "wind_gust_ref") if c in om]]
    h = h.join(om.reindex(h.index, method="ffill", limit=int(1 / STEP_H) - 1))   # hourly value held over the hour
    if "wind_dir_ref" not in h:
        h["wind_dir_ref"] = h["wdir_tempest_deg"]
        print("No wind direction in the wind file: using the Tempest wind direction")
    print(f"Wind: {src}, {om.index.min():%d %b %H:%M} to {om.index.max():%d %b %H:%M}")
    return h


def add_fog_and_model(h):
    wet = h["rain_mm"].fillna(0) > RAIN_MIN_MM
    dry = wet.rolling(int(DRY_BUFFER_H / STEP_H) + 1, min_periods=1).sum() == 0
    h["fog_flag"] = ((h["RH_pct"] >= RH_FOG) & dry).astype(float)
    h.loc[h["RH_pct"].isna(), "fog_flag"] = np.nan
    h["fiesta_fog_mm"] = [
        np.nan if (pd.isna(f) or pd.isna(ws)) else fog_deposition_mm(ws, wd, fog=int(f), hours=STEP_H)
        for f, ws, wd in zip(h["fog_flag"], h["wind_spd_ref"], h["wind_dir_ref"])
    ]
    return h


# =====================================================================
# Run
# =====================================================================
h = add_fog_and_model(add_wind(load_data()))         # buffer uses rain before the window too
w = h.loc[pd.Timestamp(START, tz=TZ): pd.Timestamp(END, tz=TZ) - pd.Timedelta(STEP)]

w.round(4).to_csv(HERE / "fog_AF_15min.csv")
n_h, n_fog = len(w) * STEP_H, w["fog_flag"].sum() * STEP_H     # hours
total = w["fiesta_fog_mm"].sum()
fog_no_wind = ((w["fog_flag"] == 1) & w["wind_spd_ref"].isna()).sum() * STEP_H
if fog_no_wind:
    print(f"WARNING: {fog_no_wind:.1f} fog hours have no wind data -> no deposition modelled for them")
fog = w["fog_flag"] == 1
summary = pd.DataFrame([dict(
    window=f"{START} - {END}", hours=n_h, fog_hours=n_fog, rain_mm=round(w["rain_mm"].sum(), 2),
    fog_modelled_mm=round(total, 4), fog_mm_per_fog_hour=round(total / n_fog, 4) if n_fog else np.nan,
    fog_hours_without_wind=fog_no_wind,
    wind_ref_mean_in_fog_ms=round(w.loc[fog, "wind_spd_ref"].mean(), 2),
    wind_tempest_mean_in_fog_ms=round(w.loc[fog, "wind_tempest_ms"].mean(), 2),
    wind_source=WIND_SOURCE, TreeFrac=TreeFrac, LAI=LAI_AF)])
summary.to_csv(HERE / "fog_AF_summary.csv", index=False)
print(summary.T.to_string(header=False))

# ---- figure: RH, rain, wind, modelled fog --------------------------
fig, axs = plt.subplots(4, 1, figsize=(6.3, 6.0), sharex=True,
                        gridspec_kw=dict(hspace=0.15, height_ratios=[1, 0.8, 0.8, 1]))
for ax in axs:
    for t in w.index[w["fog_flag"] == 1]:
        ax.axvspan(t, t + pd.Timedelta(STEP), color="#d6e6f5", lw=0, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
bw = 0.8 * pd.Timedelta(STEP)
axs[0].plot(w.index, w["RH_pct"], color="0.25", lw=1.2)
axs[0].axhline(RH_FOG, color="#2166AC", lw=1, ls="--")
axs[0].set_ylabel("RH (%)")
axs[1].bar(w.index, w["rain_mm"], width=bw, align="edge", color="0.35")
axs[1].set_ylabel("Rain\n(mm / 15 min)")
axs[2].plot(w.index, w["wind_spd_ref"], color="0.25", lw=1.2, label=f"Model input ({WIND_SOURCE})")
if WIND_SOURCE != "tempest":
    axs[2].plot(w.index, w["wind_tempest_ms"], color="0.6", lw=0.8, ls="--", label="Tempest (5.5 m)")
    axs[2].legend(fontsize=6, frameon=False, loc="upper left")
axs[2].set_ylim(bottom=0)
axs[2].set_ylabel(r"Wind (m s$^{-1}$)")
axs[3].bar(w.index, w["fiesta_fog_mm"], width=bw, align="edge", color="#2166AC")
axs[3].set_ylabel("Fog\n(mm / 15 min)")
if pd.Timestamp(END) - pd.Timestamp(START) <= pd.Timedelta("2D"):
    axs[3].xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=w.index.tz))
    axs[3].xaxis.set_major_formatter(plt.FuncFormatter(       # every hour; date shown at midnight
        lambda x, _: (t := mdates.num2date(x, tz=w.index.tz)).strftime("%d %b %H:%M" if t.hour == 0 else "%H:%M")))
    axs[3].tick_params(axis="x", labelrotation=90, labelsize=6)
else:                                                         # long window: one tick per day
    axs[3].xaxis.set_major_locator(mdates.DayLocator(tz=w.index.tz))
    axs[3].xaxis.set_major_formatter(mdates.DateFormatter("%d %b", tz=w.index.tz))
    axs[3].tick_params(axis="x", labelrotation=90, labelsize=7)
axs[3].set_xlim(pd.Timestamp(START, tz=TZ), pd.Timestamp(END, tz=TZ))
fig.align_ylabels(axs)
fig.savefig(HERE / "fog_AF_15min.png", dpi=300, bbox_inches="tight")
plt.show()