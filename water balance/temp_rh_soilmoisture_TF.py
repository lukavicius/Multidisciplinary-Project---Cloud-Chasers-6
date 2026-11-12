from pathlib import Path
import io
import numpy as np 
import scipy as sp
import pandas as pd 
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.stats import linregress
import matplotlib.dates as mdates
from zoneinfo import ZoneInfo

### define styles
# Most users should not need to change the style settings below.  The
# `figure.figsize` and `savefig.dpi` values control the size and resolution
# of the plots, not the underlying analysis.
plt.rcParams.update({
    # Figure
    'figure.figsize': (8, 5),
    'figure.dpi': 150,
    'savefig.dpi': 300,

    # Fonts
    'font.family': 'sans-serif',
    'font.size': 11,
    'axes.titlesize': 12,
    'axes.labelsize': 11,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 10,

    # Axes
    'axes.linewidth': 0.8,
    'axes.labelpad': 6,
    'xtick.major.width': 0.8,
    'ytick.major.width': 0.8,
    'xtick.major.size': 4,
    'ytick.major.size': 4,

    # Lines
    'lines.linewidth': 1.8,
    'lines.markersize': 5,

    # Grid
    'axes.grid': True,
    'grid.alpha': 0.25,
    'grid.linewidth': 0.6,

    # Legend
    'legend.frameon': False,

    # Layout
    'figure.autolayout': False,
})

COLORS = {
    'AF-primary': '#007A5E',
    'AF-secondary': '#5DBB8A',
    'CF-primary': '#2166AC',
    'CF-secondary': '#5AA0D8',
    'CA-primary': '#CC8A22',
    'CA-secondary': '#C2410C',
}

### input data, all downloaded from the dashboard
# CUSTOMIZE: replace these filenames when using a different download.  Keep
# the 15-minute file, daily file, and raw file matched to the same date range.
filename15 = 'loggers_20260924-20261020_15min.csv' #csv at 15-minute resolution
data_raw = pd.read_csv(filename15)
data_raw["timestamp"] = pd.to_datetime(data_raw["Timestamp"])

filename1D = 'loggers_20260924-20261020_1D.csv' #csv at daily resolution
daily_df = pd.read_csv(filename1D)

filename_Raw = 'loggers_20260924-20261020_raw.csv' #csv with raw timestamps of sensors

# Build subsets for CF, AF, and CA
# -------------------------------------------------------------------
# Derived Agroforestry variables
# -------------------------------------------------------------------

# Exposed air temperature: average of Tempest and Ambient
data_raw["AF_Exposed_Temp_C"] = data_raw[
    ["TEMPEST_Temp_C", "AMBIENT_Temp_C"]
].mean(axis=1, skipna=True)

# Sensor temperature: average of AF LogTags
data_raw["AF_Temp_C"] = data_raw[
    ["LOGTAG-AF1_Temp_C", "LOGTAG-AF2_Temp_C"]
].mean(axis=1, skipna=True)

# Exposed relative humidity: average of Tempest and Ambient
data_raw["AF_Exposed_RH_Pct"] = data_raw[
    ["TEMPEST_RH_Pct", "AMBIENT_RH_Pct"]
].mean(axis=1, skipna=True)

# Sensor relative humidity: average of AF LogTags
data_raw["AF_RH_Pct"] = data_raw[
    ["LOGTAG-AF1_RH_Pct", "LOGTAG-AF2_RH_Pct"]
].mean(axis=1, skipna=True)

# Exposed rainfall: average of Tempest and Ambient rain measurements
data_raw["AF_Rain_Precip_mm"] = data_raw[
    ["TEMPEST_Rain_Precip_mm", "AMBIENT_Rain_Precip_mm"]
].mean(axis=1, skipna=True)


# -------------------------------------------------------------------
# Derived Conventional Agriculture variables
# -------------------------------------------------------------------
# Temperature: average of CA LogTags
data_raw["CA_Temp_C"] = data_raw[
    ["LOGTAG-CA1_Temp_C", "LOGTAG-CA2_Temp_C"]
].mean(axis=1, skipna=True)

# Relative humidity: average of CA LogTags
data_raw["CA_RH_Pct"] = data_raw[
    ["LOGTAG-CA1_RH_Pct", "LOGTAG-CA2_RH_Pct"]
].mean(axis=1, skipna=True)

data_raw['CA_Rain_Precip_mm'] = data_raw[
    ["Mayfly2_CA-1-TF_Rain_mm", "Mayfly2_CA-2-TF_Rain_mm"]
].mean(axis=1, skipna=True)


# -------------------------------------------------------------------
# Build plot subsets
# -------------------------------------------------------------------

# Cloud Forest:
# Mayfly3, Mayfly4, HOBO, and TW LogTag columns
cf_columns = (
    ["Timestamp"]
    + data_raw.filter(
        regex=r"^(Mayfly3_|Mayfly4_|HOBO_|LOGTAG-TW1_|FOG_HOBO_CF_|FOG_LOGTAG-TW1)"
    ).columns.tolist()
    + [
        "Mayfly3_CF-1-TF_Throughfall_mm",
        "HOBO_CF-2-TF_Throughfall_mm",
        "CloudForest_stemflow_mm",
        "CloudForest_throughfall_mm",
    ]
)

# Agroforestry:
# Mayfly1, Tempest, Ambient, and AF LogTag columns
af_columns = (
    ["Timestamp"]
    + data_raw.filter(
        regex=r"^(Mayfly1_|TEMPEST_|AMBIENT_|LOGTAG-AF1_|LOGTAG-AF2_|FOG_TEMPEST_|FOG_AMBIENT_|FOG_LOGTAG-AF1_|FOG_LOGTAG-AF2)"
    ).columns.tolist()
    + [
        "Mayfly1_AF-1-TF_Throughfall_mm",
        "Mayfly1_AF-2-TF_Throughfall_mm",
        "Agroforestry_stemflow_mm",
        "Agroforestry_throughfall_mm",
        "AF_Exposed_Temp_C",
        "AF_Temp_C",
        "AF_Exposed_RH_Pct",
        "AF_RH_Pct",
        "AF_Rain_Precip_mm",
    ]
)

# Conventional Agriculture:
# Mayfly2 and CA LogTag columns
ca_columns = (
    ["Timestamp"]
    + data_raw.filter(
        regex=r"^(Mayfly2_|LOGTAG-CA1_|LOGTAG-CA2_|FOG_LOGTAG-CA1_|FOG_LOGTAG-CA2)"
    ).columns.tolist()
    + [
        "Mayfly2_CA-1-TF_Rain_mm",
        "Mayfly2_CA-2-TF_Rain_mm",
        "CA_Rain_Precip_mm",
        "CA_Temp_C",
        "CA_RH_Pct",
    ]
)

# Remove duplicate column names while preserving order
cf_columns = list(dict.fromkeys(cf_columns))
af_columns = list(dict.fromkeys(af_columns))
ca_columns = list(dict.fromkeys(ca_columns))

# Create the three plot-specific dataframes
CF = data_raw[cf_columns].copy()
AF = data_raw[af_columns].copy()
CA = data_raw[ca_columns].copy()

# Optional: inspect the resulting subsets
# print(f"CF subset: {CF.shape[0]} rows x {CF.shape[1]} columns")
# print(f"AF subset: {AF.shape[0]} rows x {AF.shape[1]} columns")
# print(f"CA subset: {CA.shape[0]} rows x {CA.shape[1]} columns")

### Delineate rainfall events (+ post-event drying period) for CF, AF, and CA
#
# Definitions:
# - Data are interpreted as Guatemala local time, UTC-6.
# - Analysis begins at 2026-10-02 00:00:00.
# - A dry gap is 4 hours = 16 consecutive 15-minute intervals.
# - Wet interval threshold is > 0 mm.
# - Events must have at least 1 mm total rain.
# - Missing rain values do not count as dry intervals.
# - Boundary events are retained and flagged as uncertain.
# - Each retained event is followed by a 12 h drying period (throughfall and
#   stemflow drip). The drying period ends early at the onset of the next
#   retained event if that onset is less than 12 h after the event end.

# -------------------------------------------------------------------
# Configuration
# CUSTOMIZE: change ANALYSIS_START and ANALYSIS_END to choose the period used
# for rainfall-event detection.  Use the local Guatemala time shown here.
# The end timestamp is included in the event analysis.
# -------------------------------------------------------------------

ANALYSIS_START = pd.Timestamp("2026-10-01 23:00:00")
ANALYSIS_END = pd.Timestamp("2026-10-17 23:00:00")
GUATEMALA_TZ = "Etc/GMT+6"  # Fixed UTC-6; Etc/GMT signs are reversed
DRY_GAP_HOURS = 4
DRYING_HOURS = 12
MIN_EVENT_RAIN_MM = 1.0
RAIN_THRESHOLD_MM = 0.0
EXPECTED_INTERVAL = pd.Timedelta(minutes=15)
DRY_GAP_INTERVALS = int(
    pd.Timedelta(hours=DRY_GAP_HOURS) / EXPECTED_INTERVAL
)
DRYING_PERIOD = pd.Timedelta(hours=DRYING_HOURS)

# -------------------------------------------------------------------
# Prepare timestamps and restrict the analysis period
# -------------------------------------------------------------------
data_raw = data_raw.copy()

data_raw["Timestamp"] = pd.to_datetime(data_raw["Timestamp"])

if data_raw["Timestamp"].dt.tz is None:
    data_raw["Timestamp"] = data_raw["Timestamp"].dt.tz_localize(
        GUATEMALA_TZ
    )
else:
    data_raw["Timestamp"] = data_raw["Timestamp"].dt.tz_convert(
        GUATEMALA_TZ
    )

data_raw = (
    data_raw.loc[
        data_raw["Timestamp"].between(
            ANALYSIS_START.tz_localize(GUATEMALA_TZ),
            ANALYSIS_END.tz_localize(GUATEMALA_TZ),
            inclusive="both",
        )
    ]
    .sort_values("Timestamp")
    .reset_index(drop=True)
)

# -------------------------------------------------------------------
# Construct the rain-gauge series
# -------------------------------------------------------------------
data_raw["AF_Rain_Precip_mm"] = data_raw[
    ["TEMPEST_Rain_Precip_mm", "AMBIENT_Rain_Precip_mm"]
].mean(axis=1, skipna=True)

data_raw["CA_Rain_Precip_mm"] = data_raw[
    ["Mayfly2_CA-1-TF_Rain_mm", "Mayfly2_CA-2-TF_Rain_mm"]
].mean(axis=1, skipna=True)

rain_gauges = {
    "CF": "HOBO_Rain_OpenSky_mm",
    "AF": "AF_Rain_Precip_mm",
    "CA": "CA_Rain_Precip_mm",
}

# -------------------------------------------------------------------
# Event-delineation function
# -------------------------------------------------------------------
def delineate_rain_events(
    plot_data,
    rain_column,
    plot_name,
    dry_gap_intervals=DRY_GAP_INTERVALS,
    min_event_rain_mm=MIN_EVENT_RAIN_MM,
    rain_threshold_mm=RAIN_THRESHOLD_MM,
    drying_period=DRYING_PERIOD,
):
    """Delineate non-overlapping rainfall events for one plot, each followed
    by a drying period."""

    work = plot_data.copy()

    # Ensure timestamps are datetime values.
    work["Timestamp"] = pd.to_datetime(
        work["Timestamp"],
        errors="coerce",
    )

    # Apply Guatemala time zone.
    if work["Timestamp"].dt.tz is None:
        work["Timestamp"] = work["Timestamp"].dt.tz_localize(
            GUATEMALA_TZ
        )
    else:
        work["Timestamp"] = work["Timestamp"].dt.tz_convert(
            GUATEMALA_TZ
        )

    # Keep valid timestamps from October 2, 2026 onward.
    work = (
        work.loc[
            work["Timestamp"].notna()
            & (
                work["Timestamp"]
                >= ANALYSIS_START.tz_localize(GUATEMALA_TZ)
            )
        ]
        .sort_values("Timestamp")
        .reset_index(drop=True)
    )

    if rain_column not in work.columns:
        raise KeyError(
            f"{plot_name}: rainfall column {rain_column!r} "
            "was not found."
        )

    rain = pd.to_numeric(
        work[rain_column],
        errors="coerce",
    )

    is_wet = rain.gt(rain_threshold_mm)
    is_known_dry = rain.notna() & rain.le(rain_threshold_mm)

    # True when the current row completes 16 consecutive known-dry intervals.
    dry_gap_complete = (
        is_known_dry.astype(int)
        .rolling(
            window=dry_gap_intervals,
            min_periods=dry_gap_intervals,
        )
        .sum()
        .eq(dry_gap_intervals)
    )

    # First row of each qualifying dry gap.
    dry_gap_start = (
        dry_gap_complete
        & ~dry_gap_complete.shift(fill_value=False)
    )

    # Wet rows that occur after a completed dry gap start a new event.
    event_starts = is_wet & (
        (work.index == 0)
        | dry_gap_complete.shift(fill_value=False)
    )

    start_indices = np.flatnonzero(event_starts.to_numpy())

    # ---------------------------------------------------------------
    # Pass 1: find retained events (unchanged event definition)
    # ---------------------------------------------------------------
    retained = []

    for event_number, start_index in enumerate(start_indices, start=1):
        # Locate the first qualifying dry gap after this event starts.
        following_gap_starts = np.flatnonzero(
            dry_gap_start.iloc[start_index + 1 :].to_numpy()
        )

        if len(following_gap_starts) > 0:
            gap_start_index = (
                start_index
                + 1
                + following_gap_starts[0]
            )
            end_index = gap_start_index - 1
            ends_at_boundary = False
        else:
            end_index = len(work) - 1
            ends_at_boundary = True

        event_rain = pd.to_numeric(
            work[rain_column].iloc[start_index : end_index + 1],
            errors="coerce",
        )

        total_rain = event_rain.sum(min_count=1)

        # Exclude candidates below the 1 mm minimum.
        if pd.isna(total_rain) or total_rain < min_event_rain_mm:
            continue

        retained.append(
            {
                "event_number": event_number,
                "start_index": start_index,
                "end_index": end_index,
                "ends_at_boundary": ends_at_boundary,
                "total_rain": total_rain,
            }
        )

    # ---------------------------------------------------------------
    # Pass 2: build event rows, drying rows, and summary
    # ---------------------------------------------------------------
    summary_rows = []
    event_frames = []

    timestamps = work["Timestamp"]
    last_timestamp = timestamps.iloc[-1] if len(work) else pd.NaT

    for k, ev in enumerate(retained):
        start_index = ev["start_index"]
        end_index = ev["end_index"]
        total_rain = ev["total_rain"]

        event_id = f"{plot_name}_{ev['event_number']:03d}"

        # ---- Event rows ----
        event_slice = work.iloc[
            start_index : end_index + 1
        ].copy()

        event_rain = pd.to_numeric(
            event_slice[rain_column],
            errors="coerce",
        )

        event_start = event_slice["Timestamp"].iloc[0]
        event_end = event_slice["Timestamp"].iloc[-1]

        duration_hours = (
            event_end - event_start
        ).total_seconds() / 3600

        peak_rain = event_rain.max()

        peak_intensity = (
            peak_rain / EXPECTED_INTERVAL.total_seconds() * 3600
            if pd.notna(peak_rain)
            else np.nan
        )

        # ---- Drying period rows ----
        nominal_drying_end = event_end + drying_period

        if k + 1 < len(retained):
            next_event_start = timestamps.iloc[
                retained[k + 1]["start_index"]
            ]
        else:
            next_event_start = pd.NaT

        in_drying = (
            (timestamps > event_end)
            & (timestamps <= nominal_drying_end)
        )
        if pd.notna(next_event_start):
            in_drying &= timestamps < next_event_start

        drying_slice = work.loc[in_drying].copy()

        drying_truncated_by_next_event = bool(
            pd.notna(next_event_start)
            and (next_event_start - event_end) < drying_period
        )
        drying_truncated_by_data_end = bool(
            pd.isna(next_event_start)
            and pd.notna(last_timestamp)
            and last_timestamp < nominal_drying_end
        )

        if len(drying_slice) > 0:
            drying_start = drying_slice["Timestamp"].iloc[0]
            drying_end = drying_slice["Timestamp"].iloc[-1]
            drying_duration_hours = (
                drying_end - event_end
            ).total_seconds() / 3600
            drying_rain = pd.to_numeric(
                drying_slice[rain_column],
                errors="coerce",
            ).sum(min_count=1)
        else:
            drying_start = pd.NaT
            drying_end = pd.NaT
            drying_duration_hours = 0.0
            drying_rain = np.nan

        # ---- Label and store rows ----
        event_slice.insert(0, "event_id", event_id)
        event_slice.insert(1, "period", "event")
        event_slice["hours_since_event_end"] = np.nan

        drying_slice.insert(0, "event_id", event_id)
        drying_slice.insert(1, "period", "drying")
        drying_slice["hours_since_event_end"] = (
            (drying_slice["Timestamp"] - event_end)
            .dt.total_seconds()
            / 3600
        )

        event_frames.extend([event_slice, drying_slice])

        summary_rows.append(
            {
                "event_id": event_id,
                "plot": plot_name,
                "rain_gauge": rain_column,
                "event_start": event_start,
                "event_end": event_end,
                "event_duration_hours": duration_hours,
                "event_total_rain_mm": total_rain,
                "event_peak_rain_15min_mm": peak_rain,
                "event_peak_intensity_mm_per_hr": peak_intensity,
                "n_rain_intervals": int(
                    event_rain.gt(rain_threshold_mm).sum()
                ),
                "n_missing_rain_intervals": int(
                    event_rain.isna().sum()
                ),
                "starts_at_analysis_boundary": start_index == 0,
                "ends_at_analysis_boundary": ev["ends_at_boundary"],
                "drying_start": drying_start,
                "drying_end": drying_end,
                "drying_duration_hours": drying_duration_hours,
                "drying_rain_mm": drying_rain,
                "drying_truncated_by_next_event": drying_truncated_by_next_event,
                "drying_truncated_by_data_end": drying_truncated_by_data_end,
            }
        )

    event_summary = pd.DataFrame(summary_rows)

    if event_frames:
        event_data = pd.concat(
            event_frames,
            ignore_index=True,
        )
    else:
        event_data = work.iloc[0:0].copy()
        event_data.insert(
            0,
            "event_id",
            pd.Series(dtype="string"),
        )
        event_data.insert(
            1,
            "period",
            pd.Series(dtype="string"),
        )
        event_data["hours_since_event_end"] = pd.Series(dtype="float")

    return event_summary, event_data


# -------------------------------------------------------------------
# Delineate events separately for each plot
# -------------------------------------------------------------------

CF_event_summary, CF_event_data = delineate_rain_events(
    CF,
    rain_gauges["CF"],
    "CF",
)

AF_event_summary, AF_event_data = delineate_rain_events(
    AF,
    rain_gauges["AF"],
    "AF",
)

CA_event_summary, CA_event_data = delineate_rain_events(
    CA,
    rain_gauges["CA"],
    "CA",
)


# Combined event summary and event-level data
event_summary = pd.concat(
    [
        CF_event_summary,
        AF_event_summary,
        CA_event_summary,
    ],
    ignore_index=True,
)

event_data = pd.concat(
    [
        CF_event_data,
        AF_event_data,
        CA_event_data,
    ],
    ignore_index=True,
)


# -------------------------------------------------------------------
# Inspect the resulting events
# -------------------------------------------------------------------

print("Events by plot:")
print(event_summary.groupby("plot").describe())

### Temperature
## plot mean diurnal temperatures
data_raw['time'] = (
    data_raw['timestamp'].dt.hour * 60
    + data_raw['timestamp'].dt.minute
)

# CUSTOMIZE: these dates control the temperature plot only.  The end date is
# the first time excluded from the plot (data at plot_end is not included).
plot_start = pd.Timestamp("2026-10-01 23:00:00", tz="Etc/GMT+6")
plot_end = pd.Timestamp("2026-10-17 23:00:00", tz="Etc/GMT+6")

temp_data = data_raw.loc[
    (data_raw["Timestamp"] >= plot_start) & (data_raw["Timestamp"] < plot_end)
].copy()

## CF exposed (hobo@ 2m)
diurnal_CF_exposed = (
    temp_data
    .dropna(subset=['HOBO_CF_Temp_2m_C_22227538'])
    .groupby('time')['HOBO_CF_Temp_2m_C_22227538']
    .mean()
)
## CF
diurnal_CF = (
    temp_data
    .dropna(subset=['LOGTAG-TW1_Temp_C'])
    .groupby('time')['LOGTAG-TW1_Temp_C']
    .mean()
)

## AF exposed (tempest and ambient)
temp_data['AF_Exposed_Temp_C'] = temp_data[
    ['TEMPEST_Temp_C', 'AMBIENT_Temp_C']
].mean(axis=1, skipna=True)

diurnal_AF_exposed = (
    temp_data
    .dropna(subset=['AF_Exposed_Temp_C'])
    .groupby('time')['AF_Exposed_Temp_C']
    .mean()
)

## AF
temp_data['AF_Temp_C'] = temp_data[
    ['LOGTAG-AF1_Temp_C', 'LOGTAG-AF2_Temp_C']
].mean(axis=1, skipna=True)
# Calculate mean temperature at each 15-minute time interval
diurnal_AF = (
    temp_data
    .dropna(subset=['AF_Temp_C'])
    .groupby('time')['AF_Temp_C']
    .mean()
)

## CA
temp_data['CA_Temp_C'] = temp_data[
    ['LOGTAG-CA1_Temp_C', 'LOGTAG-CA2_Temp_C']
].mean(axis=1, skipna=True)
# Calculate mean temperature at each 15-minute time interval
diurnal_CA = (
    temp_data
    .dropna(subset=['CA_Temp_C'])
    .groupby('time')['CA_Temp_C']
    .mean()
)

with plt.rc_context({
    "font.size": 8.5,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
}):
    fig, (ax1, ax_temp) = plt.subplots(
        1,
        2,
        figsize=(11, 5),
        sharey=True,
        gridspec_kw={"width_ratios": [2.4, 0.4], "wspace": 0.25},
    )

    # ------------------------------------------------------------------
    # Left panel: diurnal temperature
    # ------------------------------------------------------------------
    ax1.plot(
        diurnal_CF_exposed.index / 60,
        diurnal_CF_exposed.values,
        linewidth=1.3,
        label="CF Exposed",
        color=COLORS["CF-secondary"],
    )

    ax1.plot(
        diurnal_CF.index / 60,
        diurnal_CF.values,
        linewidth=1.3,
        linestyle="--",
        label="CF Under Canopy",
        color=COLORS["CF-primary"],
    )

    ax1.plot(
        diurnal_AF_exposed.index / 60,
        diurnal_AF_exposed.values,
        linewidth=1.3,
        label="AF Exposed",
        color=COLORS["AF-secondary"],
    )

    ax1.plot(
        diurnal_AF.index / 60,
        diurnal_AF.values,
        linewidth=1.3,
        linestyle="--",
        label="AF Under Canopy",
        color=COLORS["AF-primary"],
    )

    ax1.plot(
        diurnal_CA.index / 60,
        diurnal_CA.values,
        linewidth=1.3,
        label="CA",
        color=COLORS["CA-primary"],
    )

    ax1.set_xlabel("Time of day", fontsize=9)
    ax1.set_ylabel("Mean temperature (°C)", fontsize=9)
    ax1.set_xticks(range(0, 25, 2))
    ax1.set_xlim(0, 24)
    ax1.set_ylim(15, 26)

    ax1.tick_params(axis="both", labelsize=8)
    ax1.grid(alpha=0.25, linewidth=0.6, zorder=0)
    ax1.spines[["top", "right"]].set_visible(False)

    # ------------------------------------------------------------------
    # Elevation text box (no elevation lines or secondary axis)
    # ------------------------------------------------------------------
    elevation_text = (
        r"$\bf{Elevations}$" + "\n"
        "CA: 1690 m\n"
        "CF: 1650 m\n"
        "AF: 1420 m"
    )

    ax1.text(
        0.025,
        0.96,
        elevation_text,
        transform=ax1.transAxes,
        fontsize=8.5,
        ha="left",
        va="top",
        linespacing=1.4,
        color="black",
        bbox=dict(
            boxstyle="round,pad=0.4",
            facecolor="white",
            edgecolor="0.8",
            linewidth=0.6,
            alpha=0.9,
        ),
    )

    # ------------------------------------------------------------------
    # Legend for temperature curves only
    # ------------------------------------------------------------------
    lines1, labels1 = ax1.get_legend_handles_labels()

    legend_order = [
        "CF Under Canopy",
        "CF Exposed",
        "AF Under Canopy",
        "AF Exposed",
        "CA",
    ]

    all_handles = dict(zip(labels1, lines1))

    legend = ax1.legend(
        [all_handles[label] for label in legend_order],
        legend_order,
        loc="upper right",
        ncol=2,
        fontsize=9,
        handlelength=1.4,
        columnspacing=1.0,
        labelspacing=0.5,
        frameon=True,
        facecolor="white",
        edgecolor="0.7",
        framealpha=0.9,
    )

    legend.get_frame().set_linewidth(0.6)

    # ------------------------------------------------------------------
    # Right panel: temperature range and mean
    # ------------------------------------------------------------------
    series = {
        "CF": diurnal_CF,
        "AF": diurnal_AF,
        "CA": diurnal_CA,
    }

    colors = {
        "CF": COLORS["CF-primary"],
        "AF": COLORS["AF-primary"],
        "CA": COLORS["CA-primary"],
    }

    bar_spacing = 0.3
    x_positions = np.arange(len(series)) * bar_spacing

    for x, (name, s) in zip(x_positions, series.items()):
        lo = s.min()
        hi = s.max()
        mean = s.mean()

        ax_temp.bar(
            x,
            hi - lo,
            bottom=lo,
            width=0.2,
            color=colors[name],
            alpha=0.65,
            linewidth=0,
            zorder=2,
            align="center",
        )

        ax_temp.scatter(
            x,
            mean,
            color="white",
            edgecolor="black",
            linewidth=0.7,
            s=35,
            zorder=3,
        )

    ax_temp.set_xticks(x_positions)
    ax_temp.set_xticklabels(series.keys())

    half_width = 0.2 / 2
    ax_temp.set_xlim(
        x_positions[0] - half_width - 0.1,
        x_positions[-1] + half_width + 0.1,
    )

    ax_temp.set_ylim(15,26)
    ax_temp.set_xlabel("Site")
    ax_temp.tick_params(axis="both", labelsize=8)
    ax_temp.grid(axis="y", alpha=0.25, linewidth=0.6, zorder=0)
    ax_temp.grid(axis="x", visible=False)
    ax_temp.set_ylabel("Temperature (°C)", fontsize=9)
    ax_temp.spines[["top", "right"]].set_visible(False)

    mean_handle = Line2D(
        [],
        [],
        marker="o",
        linestyle="None",
        markerfacecolor="white",
        markeredgecolor="black",
        markersize=5,
        label="Mean\ntemperature",
    )

    ax_temp.legend(
        handles=[mean_handle],
        frameon=False,
        fontsize=7.5,
        loc="upper left",
    )

    # Hide duplicate temperature tick labels
    ax_temp.tick_params(axis="y", labelleft=False)

    fig.tight_layout(rect=(0, 0.08, 1, 1))
    # SAVE PLOT: change the filename or folder here if desired.  The file is
    # written to the folder from which this script is run.
    # fig.savefig("diurnal_temperature.png", dpi=300, bbox_inches="tight")
    # Close this standalone figure so it is not displayed by a later
    # plt.show() call.  The combined temperature/RH figure is shown below.
    plt.close(fig)
diff_CA_AF = diurnal_CA-diurnal_AF
diff_AF_shading = diurnal_AF_exposed-diurnal_AF
print(f'AF shading effect = {diurnal_AF_exposed.max()-diurnal_AF.max():.3f} deg ')
print(f'AF min temp difference = {diurnal_AF_exposed.min()-diurnal_AF.min()}')
print(f'AF max - CA max = {diurnal_AF.max()-diurnal_CA.max():.3f}')

### Relative humidity
# ------------------------------------------------------------------
# Prepare data and calculate mean diurnal relative humidity
# ------------------------------------------------------------------
data_raw["time"] = (
    data_raw["Timestamp"].dt.hour * 60
    + data_raw["Timestamp"].dt.minute
)

# CUSTOMIZE: these dates control the relative-humidity plot only.  Use the
# same period as the temperature plot if the two figures should be comparable.
plot_start = pd.Timestamp("2026-10-01 23:00:00", tz="Etc/GMT+6")
plot_end = pd.Timestamp("2026-10-17 23:00:00", tz="Etc/GMT+6")

rh_data = data_raw.loc[
    (data_raw["Timestamp"] >= plot_start)
    & (data_raw["Timestamp"] < plot_end)
].copy()

# AF exposed relative humidity
rh_data["AF_Exposed_RH_Pct"] = rh_data[
    ["TEMPEST_RH_Pct", "AMBIENT_RH_Pct"]
].mean(axis=1, skipna=True)

diurnal_AF_exposed_rh = (
    rh_data
    .dropna(subset=["AF_Exposed_RH_Pct"])
    .groupby("time")["AF_Exposed_RH_Pct"]
    .mean()
)

# AF under-canopy relative humidity
rh_data["AF_RH_Pct"] = rh_data[
    ["LOGTAG-AF1_RH_Pct", "LOGTAG-AF2_RH_Pct"]
].mean(axis=1, skipna=True)

diurnal_AF_rh = (
    rh_data
    .dropna(subset=["AF_RH_Pct"])
    .groupby("time")["AF_RH_Pct"]
    .mean()
)

# CA relative humidity
rh_data["CA_RH_Pct"] = rh_data[
    ["LOGTAG-CA1_RH_Pct", "LOGTAG-CA2_RH_Pct"]
].mean(axis=1, skipna=True)

diurnal_CA_rh = (
    rh_data
    .dropna(subset=["CA_RH_Pct"])
    .groupby("time")["CA_RH_Pct"]
    .mean()
)

# ------------------------------------------------------------------
# Plot diurnal relative humidity and range/mean summary
# ------------------------------------------------------------------
with plt.rc_context({
    "font.size": 8.5,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
}):
    fig, (ax1, ax_rh) = plt.subplots(
        1,
        2,
        figsize=(11, 5),
        sharey=True,
        gridspec_kw={"width_ratios": [2.4, 0.7], "wspace": 0.1},
    )

    # Left panel: diurnal relative humidity
    ax1.plot(
        diurnal_AF_exposed_rh.index / 60,
        diurnal_AF_exposed_rh.values,
        linewidth=1.3,
        label="AF Exposed",
        color=COLORS["AF-secondary"],
    )

    ax1.plot(
        diurnal_AF_rh.index / 60,
        diurnal_AF_rh.values,
        linewidth=1.3,
        linestyle="--",
        label="AF Under Canopy",
        color=COLORS["AF-primary"],
    )

    ax1.plot(
        diurnal_CA_rh.index / 60,
        diurnal_CA_rh.values,
        linewidth=1.3,
        label="CA",
        color=COLORS["CA-primary"],
    )

    ax1.set_xlabel("Time of day", fontsize=9)
    ax1.set_ylabel("Mean relative humidity (%)", fontsize=9)
    ax1.set_xticks(range(0, 25, 2))
    ax1.set_xlim(0, 24)
    ax1.set_ylim(40, 100)

    ax1.tick_params(axis="both", labelsize=8)
    ax1.grid(alpha=0.25, linewidth=0.6, zorder=0)
    ax1.spines[["top", "right"]].set_visible(False)

    ax1.legend(
        loc="lower left",
        fontsize=7.5,
        frameon=True,
        facecolor="white",
        edgecolor="0.7",
        framealpha=0.9,
    )

    # Right panel: relative-humidity range and mean
    series = {
        "AF Exposed": diurnal_AF_exposed_rh,
        "AF": diurnal_AF_rh,
        "CA": diurnal_CA_rh,
    }

    colors = {
        "AF Exposed": COLORS["AF-secondary"],
        "AF": COLORS["AF-primary"],
        "CA": COLORS["CA-primary"],
    }

    bar_spacing = 0.3
    x_positions = np.arange(len(series)) * bar_spacing

    for x, (name, series_data) in zip(x_positions, series.items()):
        lo = series_data.min()
        hi = series_data.max()
        mean = series_data.mean()

        ax_rh.bar(
            x,
            hi - lo,
            bottom=lo,
            width=0.2,
            color=colors[name],
            alpha=0.65,
            linewidth=0,
            zorder=2,
        )

        ax_rh.scatter(
            x,
            mean,
            color="white",
            edgecolor="black",
            linewidth=0.7,
            s=35,
            zorder=3,
        )

    ax_rh.set_xticks(x_positions)
    ax_rh.set_xticklabels(["AF Exposed", "AF", "CA"])
    ax_rh.set_xlim(
        x_positions[0] - 0.2,
        x_positions[-1] + 0.2,
    )
    ax_rh.set_ylim(70, 100)
    ax_rh.set_xlabel("Site", fontsize=9)
    ax_rh.set_ylabel("Relative humidity (%)", fontsize=9)

    ax_rh.tick_params(axis="both", labelsize=8)
    ax_rh.grid(axis="y", alpha=0.25, linewidth=0.6, zorder=0)
    ax_rh.grid(axis="x", visible=False)
    ax_rh.spines[["top", "right"]].set_visible(False)

    mean_handle = Line2D(
        [],
        [],
        marker="o",
        linestyle="None",
        markerfacecolor="white",
        markeredgecolor="black",
        markersize=5,
        label="Mean\nrelative humidity",
    )

    ax_rh.legend(
        handles=[mean_handle],
        frameon=False,
        fontsize=7.5,
        loc="lower left",
    )

    # Hide duplicate y-axis tick labels on the right panel
    ax_rh.tick_params(axis="y", labelleft=False)

    fig.tight_layout(rect=(0, 0.08, 1, 1))
    # SAVE PLOT: change the filename or folder here if desired.
    # fig.savefig("diurnal_relative_humidity.png", dpi=300, bbox_inches="tight")
    # Close this standalone figure so only the combined temperature/RH figure
    # appears in a popup window.
    plt.close(fig)

### Temperature and RH combined
with plt.rc_context({
    "font.size": 9,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
}):

    # ==============================================================
    # FIGURE LAYOUT
    # ==============================================================

    fig, axes = plt.subplots(
        2, 2,
        figsize=(11, 8),
        gridspec_kw={
            "width_ratios": [2.4, 0.5],
            "height_ratios": [1, 0.6],
            "wspace": 0.2,
            "hspace": 0.2,
        },
    )

    ax_temp, ax_temp_range = axes[0]
    ax_rh, ax_rh_range = axes[1]

    # ==============================================================
    # (a) DIURNAL TEMPERATURE
    # ==============================================================

    temperature_series = {
        "CF Exposed": (
            diurnal_CF_exposed,
            COLORS["CF-secondary"],
            "-"
        ),
        "CF Under Canopy": (
            diurnal_CF,
            COLORS["CF-primary"],
            "--"
        ),
        "AF Exposed": (
            diurnal_AF_exposed,
            COLORS["AF-secondary"],
            "-"
        ),
        "AF Under Canopy": (
            diurnal_AF,
            COLORS["AF-primary"],
            "--"
        ),
        "CA": (
            diurnal_CA,
            COLORS["CA-primary"],
            "-"
        ),
    }

    for name, (s, color, style) in temperature_series.items():
        ax_temp.plot(
            s.index / 60,
            s.values,
            linewidth=1.3,
            linestyle=style,
            label=name,
            color=color,
        )

    ax_temp.set_xlabel("Time of day")
    ax_temp.set_ylabel("Mean temperature (°C)")
    ax_temp.set_xticks(range(0, 25, 2))
    ax_temp.set_xlim(0, 24)
    ax_temp.set_ylim(15, 26)

    ax_temp.tick_params(axis="both", labelsize=8)
    ax_temp.grid(alpha=0.25, linewidth=0.6, zorder=0)
    ax_temp.spines[["top", "right"]].set_visible(False)

    # Elevation text box only (no elevation lines)
    elevation_text = (
        r"$\bf{Elevations}$" + "\n"
        "CA: 1690 m\n"
        "CF: 1650 m\n"
        "AF: 1420 m"
    )

    ax_temp.text(
        0.025,
        0.9,
        elevation_text,
        transform=ax_temp.transAxes,
        fontsize=10,
        ha="left",
        va="top",
        linespacing=1.4,
        color="black",
        bbox=dict(
            boxstyle="round,pad=0.4",
            facecolor="white",
            edgecolor="0.8",
            linewidth=0.6,
            alpha=0.9,
        ),
    )

    # Temperature legend
    lines, labels = ax_temp.get_legend_handles_labels()

    legend_order = [
        "CF Under Canopy",
        "CF Exposed",
        "AF Under Canopy",
        "AF Exposed",
        "CA",
    ]

    handles = dict(zip(labels, lines))

    ax_temp.legend(
        [handles[label] for label in legend_order],
        legend_order,
        loc="upper right",
        ncol=2,
        fontsize=9,
        handlelength=1.4,
        columnspacing=1.0,
        labelspacing=0.5,
        frameon=True,
        facecolor="white",
        edgecolor="0.7",
        framealpha=0.9,
    )

    # ==============================================================
    # (b) TEMPERATURE RANGE AND MEAN
    # ==============================================================

    temp_series = {
        "CF": diurnal_CF,
        "AF": diurnal_AF,
        "CA": diurnal_CA,
    }

    temp_colors = {
        "CF": COLORS["CF-primary"],
        "AF": COLORS["AF-primary"],
        "CA": COLORS["CA-primary"],
    }

    bar_spacing = 0.3
    x_positions = np.arange(len(temp_series)) * bar_spacing

    for x, (name, s) in zip(x_positions, temp_series.items()):

        lo = s.min()
        hi = s.max()
        mean = s.mean()

        ax_temp_range.bar(
            x,
            hi - lo,
            bottom=lo,
            width=0.2,
            color=temp_colors[name],
            alpha=0.65,
            linewidth=0,
            zorder=2,
        )

        ax_temp_range.scatter(
            x,
            mean,
            color="white",
            edgecolor="black",
            linewidth=0.7,
            s=35,
            zorder=3,
        )

    ax_temp_range.set_xticks(x_positions)
    ax_temp_range.set_xticklabels(temp_series.keys())
    ax_temp_range.set_xlim(
        x_positions[0] - 0.2,
        x_positions[-1] + 0.2,
    )

    ax_temp_range.set_ylim(15, 26)
    ax_temp_range.set_xlabel("Site")
    ax_temp_range.set_ylabel("Temperature (°C)")
    ax_temp_range.tick_params(axis="both", labelsize=8)
    ax_temp_range.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax_temp_range.grid(axis="x", visible=False)
    ax_temp_range.spines[["top", "right"]].set_visible(False)

    mean_temp_handle = Line2D(
        [],
        [],
        marker="o",
        linestyle="None",
        markerfacecolor="white",
        markeredgecolor="black",
        markersize=5,
        label="Mean temperature",
    )

    ax_temp_range.legend(
        handles=[mean_temp_handle],
        frameon=False,
        fontsize=9,
        loc="upper left",
    )

    # ==============================================================
    # (c) DIURNAL RELATIVE HUMIDITY
    # ==============================================================

    humidity_series = {
        "AF Exposed": (
            diurnal_AF_exposed_rh,
            COLORS["AF-secondary"],
            "-"
        ),
        "AF Under Canopy": (
            diurnal_AF_rh,
            COLORS["AF-primary"],
            "--"
        ),
        "CA": (
            diurnal_CA_rh,
            COLORS["CA-primary"],
            "-"
        ),
    }

    for name, (s, color, style) in humidity_series.items():
        ax_rh.plot(
            s.index / 60,
            s.values,
            linewidth=1.3,
            linestyle=style,
            label=name,
            color=color,
        )

    ax_rh.set_xlabel("Time of day")
    ax_rh.set_ylabel("Mean relative humidity (%)")
    ax_rh.set_xticks(range(0, 25, 2))
    ax_rh.set_xlim(0, 24)
    ax_rh.set_ylim(70, 100)

    ax_rh.tick_params(axis="both", labelsize=8)
    ax_rh.grid(alpha=0.25, linewidth=0.6, zorder=0)
    ax_rh.spines[["top", "right"]].set_visible(False)

    ax_rh.legend(
        loc="lower left",
        fontsize=9,
        frameon=True,
        facecolor="white",
        edgecolor="0.7",
        framealpha=0.9,
    )

    # ==============================================================
    # (d) RELATIVE HUMIDITY RANGE AND MEAN
    # ==============================================================

    rh_series = {
        "AF Exposed": diurnal_AF_exposed_rh,
        "AF": diurnal_AF_rh,
        "CA": diurnal_CA_rh,
    }

    rh_colors = {
        "AF Exposed": COLORS["AF-secondary"],
        "AF": COLORS["AF-primary"],
        "CA": COLORS["CA-primary"],
    }

    x_positions_rh = np.arange(len(rh_series)) * bar_spacing

    for x, (name, s) in zip(x_positions_rh, rh_series.items()):

        lo = s.min()
        hi = s.max()
        mean = s.mean()

        ax_rh_range.bar(
            x,
            hi - lo,
            bottom=lo,
            width=0.2,
            color=rh_colors[name],
            alpha=0.65,
            linewidth=0,
            zorder=2,
        )

        ax_rh_range.scatter(
            x,
            mean,
            color="white",
            edgecolor="black",
            linewidth=0.7,
            s=35,
            zorder=3,
        )

    ax_rh_range.set_xticks(x_positions_rh)
    ax_rh_range.set_xticklabels(rh_series.keys())
    ax_rh_range.set_xlim(
        x_positions_rh[0] - 0.2,
        x_positions_rh[-1] + 0.2,
    )

    ax_rh_range.set_ylim(70, 100)
    ax_rh_range.set_xlabel("Site")
    ax_rh_range.set_ylabel("Relative humidity (%)")
    ax_rh_range.tick_params(axis="both", labelsize=8)
    ax_rh_range.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax_rh_range.grid(axis="x", visible=False)
    ax_rh_range.spines[["top", "right"]].set_visible(False)

    mean_rh_handle = Line2D(
        [],
        [],
        marker="o",
        linestyle="None",
        markerfacecolor="white",
        markeredgecolor="black",
        markersize=5,
        label="Mean RH",
    )

    ax_rh_range.legend(
        handles=[mean_rh_handle],
        frameon=False,
        fontsize=9,
        loc="lower left",
    )

    # ==============================================================
    # FINAL FORMATTING
    # ==============================================================

    # Panel labels
    for ax, label in zip(
        [ax_temp, ax_temp_range, ax_rh, ax_rh_range],
        ["(a)", "(b)", "(c)", "(d)"],
    ):
        ax.text(
            0.005,
            0.999,
            label,
            transform=ax.transAxes,
            fontsize=10,
            fontweight="bold",
            va="top",
            ha="left",
        )

    fig.align_ylabels([ax_temp, ax_rh])

    fig.tight_layout()
    # SAVE PLOT: change the filename or folder here if desired.
    fig.savefig("diurnal_temperature_and_relative_humidity.png",
                dpi=300, bbox_inches="tight")
    plt.show()



### Soil water content
## Full time series
# -------------------------------------------------------------------
# Prepare data and set Guatemala timezone
# -------------------------------------------------------------------
gt_tz = ZoneInfo("America/Guatemala")

data_raw = pd.read_csv(filename15)
data_raw["Timestamp"] = pd.to_datetime(
    data_raw["Timestamp"], errors="coerce"
)

# Interpret or convert timestamps to Guatemala local time (UTC-6).
if data_raw["Timestamp"].dt.tz is None:
    # Assumes naive timestamps already represent Guatemala local time.
    data_raw["Timestamp"] = data_raw["Timestamp"].dt.tz_localize(gt_tz)
else:
    data_raw["Timestamp"] = data_raw["Timestamp"].dt.tz_convert(gt_tz)

# Remove missing timestamps, sort chronologically, and reset index.
plot_data = (
    data_raw.loc[data_raw["Timestamp"].notna()]
    .sort_values("Timestamp")
    .reset_index(drop=True)
)

# -------------------------------------------------------------------
# Filter to requested Guatemala local-time range
# -------------------------------------------------------------------
# CUSTOMIZE: change these dates to control the time-series soil-moisture and
# rainfall figure.  The end timestamp is excluded from the displayed range.
plot_start = pd.Timestamp("2026-09-24 23:00:00", tz=gt_tz)
plot_end = pd.Timestamp("2026-10-18 23:00:00", tz=gt_tz)

plot_data = plot_data.loc[
    (plot_data["Timestamp"] >= plot_start)
    & (plot_data["Timestamp"] < plot_end)
].copy()

print(
    "Plot range:",
    plot_data["Timestamp"].min(),
    "to",
    plot_data["Timestamp"].max()
)
print("Timezone:", plot_data["Timestamp"].dt.tz)
print("Number of rows:", len(plot_data))

# -------------------------------------------------------------------
# Derived rainfall variables and numeric conversion
# -------------------------------------------------------------------
plot_data["AF_Rain_Precip_mm"] = (
    plot_data[
        ["TEMPEST_Rain_Precip_mm", "AMBIENT_Rain_Precip_mm"]
    ]
    .apply(pd.to_numeric, errors="coerce")
    .mean(axis=1, skipna=True)
)

plot_data["CA_Rain_Precip_mm"] = (
    plot_data[
        ["Mayfly2_CA-1-TF_Rain_mm", "Mayfly2_CA-2-TF_Rain_mm"]
    ]
    .apply(pd.to_numeric, errors="coerce")
    .mean(axis=1, skipna=True)
)

columns_to_convert = [
    "Mayfly1_AF-10-SM_5TM_SoilMoisture_VWC_Pct",
    "Mayfly1_AF-30-SM_EC5_SoilMoisture_VWC_Pct",
    "Mayfly2_CA-10-SM_5TM_SoilMoisture_VWC_Pct",
    "Mayfly2_CA-30-SM_EC5_SoilMoisture_VWC_Pct",
    "AF_Rain_Precip_mm",
    "CA_Rain_Precip_mm",
]

for column in columns_to_convert:
    plot_data[column] = pd.to_numeric(
        plot_data[column], errors="coerce"
    )

# -------------------------------------------------------------------
# Plot colors
# -------------------------------------------------------------------
AF_COLOR = COLORS["AF-primary"]
CA_COLOR = COLORS["CA-primary"]
AF_SECONDARY_COLOR = COLORS["AF-secondary"]
CA_SECONDARY_COLOR = COLORS["CA-secondary"]

# -------------------------------------------------------------------
# Create figure
# -------------------------------------------------------------------
with plt.rc_context({
    "font.size": 8.5,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 7.5,
}):

    fig, (ax_soil, ax_rain) = plt.subplots(
        2, 1,
        figsize=(10, 5.5),
        sharex=True,
        gridspec_kw={
            "height_ratios": [3, 1],
            "hspace": 0.05,
        },
    )

    # ---------------------------------------------------------------
    # Soil moisture — upper panel
    # ---------------------------------------------------------------
    soil_series = [
        (
            "AF 10 cm soil moisture",
            "Mayfly1_AF-10-SM_5TM_SoilMoisture_VWC_Pct",
            AF_COLOR,
        ),
        (
            "CA 10 cm soil moisture",
            "Mayfly2_CA-10-SM_5TM_SoilMoisture_VWC_Pct",
            CA_COLOR,
        ),
        (
            "AF 30 cm soil moisture",
            "Mayfly1_AF-30-SM_EC5_SoilMoisture_VWC_Pct",
            AF_SECONDARY_COLOR,
        ),
        (
            "CA 30 cm soil moisture",
            "Mayfly2_CA-30-SM_EC5_SoilMoisture_VWC_Pct",
            CA_SECONDARY_COLOR,
        ),
    ]

    for label, column, color in soil_series:
        ax_soil.plot(
            plot_data["Timestamp"],
            plot_data[column],
            color=color,
            lw=1.3,
            label=label,
            zorder=2,
        )

    ax_soil.set_ylabel("Soil moisture (VWC, %)")
    ax_soil.spines[["top", "right"]].set_visible(False)
    ax_soil.tick_params(axis="both", labelsize=8)

    ax_soil.legend(
        loc="upper right",
        ncol=2,
        frameon=False,
        fontsize=7.5,
        handlelength=1.4,
        columnspacing=1.2,
        labelspacing=0.6,
    )

    # ---------------------------------------------------------------
    # Rainfall — lower panel
    # ---------------------------------------------------------------
    bar_width_days = 15 / (24 * 60)

    ax_rain.bar(
        plot_data["Timestamp"] - pd.Timedelta(minutes=3),
        plot_data["AF_Rain_Precip_mm"].fillna(0),
        width=bar_width_days * 0.42,
        color=AF_COLOR,
        label="AF rainfall",
        linewidth=0,
        zorder=2,
    )

    ax_rain.bar(
        plot_data["Timestamp"] + pd.Timedelta(minutes=3),
        plot_data["CA_Rain_Precip_mm"].fillna(0),
        width=bar_width_days * 0.42,
        color=CA_COLOR,
        label="CA rainfall",
        linewidth=0,
        zorder=2,
    )

    ax_rain.set_ylabel("Rainfall\n(mm per 15 min interval)")
    ax_rain.set_xlabel("Date")
    ax_rain.set_ylim(0, 5)
    ax_rain.spines[["top", "right"]].set_visible(False)
    ax_rain.tick_params(axis="both", labelsize=8)

    # ---------------------------------------------------------------
    # X-axis — explicitly format in Guatemala local time
    # ---------------------------------------------------------------
    ax_rain.xaxis.set_major_locator(
        mdates.DayLocator(interval=2, tz=gt_tz)
    )
    ax_rain.xaxis.set_major_formatter(
        mdates.DateFormatter("%d %b", tz=gt_tz)
    )

    # Fix exact start and end of the displayed range.
    ax_rain.set_xlim(plot_start, plot_end)

    # ---------------------------------------------------------------
    # Rainfall legend
    # ---------------------------------------------------------------
    ax_rain.legend(
        loc="upper right",
        ncol=2,
        frameon=False,
        fontsize=7.5,
        handlelength=1.4,
        columnspacing=1.2,
        labelspacing=0.6,
    )

    # ---------------------------------------------------------------
    # Layout and display
    # ---------------------------------------------------------------
    fig.tight_layout()

    # SAVE PLOT: change the filename or folder here if desired.
    fig.savefig(
        "soil_moisture_rainfall_guatemala_time.png",
        dpi=300,
        bbox_inches="tight",
    )
    plt.show()

## Diurnal SWC 
# -------------------------------------------------------------------
# Configuration
# CUSTOMIZE: START_TIME and END_TIME define the period used for the diurnal
# soil-moisture averages.  CA_GAP_START and CA_GAP_END exclude a known
# missing-data period; change or remove this gap only when you have checked
# the data quality for a new dataset.
# -------------------------------------------------------------------

gt_tz = ZoneInfo("America/Guatemala")

START_TIME = pd.Timestamp("2026-10-01 23:00:00", tz=gt_tz)
END_TIME = pd.Timestamp("2026-10-17 23:00:00", tz=gt_tz)

CA_GAP_START = pd.Timestamp("2026-10-07 09:00:00", tz=gt_tz)
CA_GAP_END = pd.Timestamp("2026-10-12 10:40:00", tz=gt_tz)

# -------------------------------------------------------------------
# Create combined rainfall columns in data_raw
# -------------------------------------------------------------------

data_raw["AF_Rain_Precip_mm"] = data_raw[
    ["TEMPEST_Rain_Precip_mm", "AMBIENT_Rain_Precip_mm"]
].mean(axis=1, skipna=True)

data_raw["CA_Rain_Precip_mm"] = data_raw[
    ["Mayfly2_CA-1-TF_Rain_mm", "Mayfly2_CA-2-TF_Rain_mm"]
].mean(axis=1, skipna=True)

# -------------------------------------------------------------------
# Soil moisture sensors
# -------------------------------------------------------------------

soil_series = [
    (
        "AF 10 cm",
        "Mayfly1_AF-10-SM_5TM_SoilMoisture_VWC_Pct",
        COLORS["AF-primary"],
    ),
    (
        "AF 30 cm",
        "Mayfly1_AF-30-SM_EC5_SoilMoisture_VWC_Pct",
        COLORS["AF-secondary"],
    ),
    (
        "CA 10 cm",
        "Mayfly2_CA-10-SM_5TM_SoilMoisture_VWC_Pct",
        COLORS["CA-primary"],
    ),
    (
        "CA 30 cm",
        "Mayfly2_CA-30-SM_EC5_SoilMoisture_VWC_Pct",
        COLORS["CA-secondary"],
    ),
]

soil_columns = [column for _, column, _ in soil_series]

# -------------------------------------------------------------------
# Prepare and filter data
# -------------------------------------------------------------------

diurnal_data = data_raw.loc[
    data_raw["Timestamp"].notna()
].copy()

diurnal_data["Timestamp"] = pd.to_datetime(
    diurnal_data["Timestamp"]
)

if diurnal_data["Timestamp"].dt.tz is None:
    diurnal_data["Timestamp"] = (
        diurnal_data["Timestamp"].dt.tz_localize(gt_tz)
    )
else:
    diurnal_data["Timestamp"] = (
        diurnal_data["Timestamp"].dt.tz_convert(gt_tz)
    )

# Keep only the requested period.
diurnal_data = diurnal_data.loc[
    diurnal_data["Timestamp"].between(
        START_TIME, END_TIME, inclusive="both"
    )
].copy()

# Exclude all observations during the CA gap.
gap_mask = diurnal_data["Timestamp"].between(
    CA_GAP_START, CA_GAP_END, inclusive="both"
)

diurnal_data = diurnal_data.loc[~gap_mask].copy()

# Convert soil moisture and rainfall columns to numeric.
rainfall_columns = [
    ("AF rainfall", "AF_Rain_Precip_mm", COLORS["AF-primary"]),
    ("CA rainfall", "CA_Rain_Precip_mm", COLORS["CA-primary"]),
]

all_columns = soil_columns + [
    column for _, column, _ in rainfall_columns
]

diurnal_data[all_columns] = diurnal_data[all_columns].apply(
    pd.to_numeric, errors="coerce"
)

# -------------------------------------------------------------------
# Calculate 15-minute time-of-day bins
# -------------------------------------------------------------------

floored_timestamp = diurnal_data["Timestamp"].dt.floor("15min")

diurnal_data["time_of_day"] = (
    floored_timestamp.dt.hour * 60
    + floored_timestamp.dt.minute
)

# -------------------------------------------------------------------
# Calculate mean diurnal soil moisture and standard deviation
# -------------------------------------------------------------------

soil_grouped = diurnal_data.groupby("time_of_day")[soil_columns]

cycle_mean = soil_grouped.mean()
cycle_std = soil_grouped.std()

# -------------------------------------------------------------------
# Calculate mean diurnal rainfall
# -------------------------------------------------------------------

rainfall_grouped = diurnal_data.groupby("time_of_day")[
    [column for _, column, _ in rainfall_columns]
]

rainfall_mean = rainfall_grouped.mean()

# -------------------------------------------------------------------
# Print analysis information
# -------------------------------------------------------------------

print(f"Analysis period: {START_TIME} to {END_TIME}")
print(f"Excluded CA gap: {CA_GAP_START} to {CA_GAP_END}")
print(f"Remaining observations: {len(diurnal_data)}")

print(
    f"Filtered data range: {diurnal_data['Timestamp'].min()} "
    f"to {diurnal_data['Timestamp'].max()}"
)

# -------------------------------------------------------------------
# Plot mean diurnal soil moisture and rainfall
# -------------------------------------------------------------------

with plt.rc_context({
    "font.size": 10,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
}):
    fig, ax = plt.subplots(figsize=(11, 5))

    # Soil moisture mean cycles with standard deviation shading.
    soil_handles = []

    time_hours = cycle_mean.index / 60

    for label, column, color in soil_series:
        mean = cycle_mean[column]
        std = cycle_std[column].fillna(0)

        line, = ax.plot(
            time_hours,
            mean,
            color=color,
            lw=2,
            label=label,
            zorder=3,
        )

        soil_handles.append(line)

    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xticklabels([
        f"{hour:02d}:00" for hour in range(0, 25, 2)
    ])

    ax.set_xlabel("Time of day")
    ax.set_ylabel("Soil moisture (VWC, %)")

    ax.grid(True, axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Rainfall on secondary y-axis.
    ax_rain = ax.twinx()

    rainfall_handles = []
    bar_width_hours = 12 / 60  # 12-minute bar width

    rainfall_hours = rainfall_mean.index / 60

    for label, column, color in rainfall_columns:
        bars = ax_rain.bar(
            rainfall_hours,
            rainfall_mean[column],
            width=bar_width_hours,
            color=color,
            alpha=0.35,
            label=label,
            zorder=1,
        )

        rainfall_handles.append(bars)

    ax_rain.set_ylabel("Mean rainfall (mm per 15-minute interval)")
    ax_rain.spines["top"].set_visible(False)

    # Combined legend.
    ax.legend(
        soil_handles + rainfall_handles,
        [h.get_label() for h in soil_handles]
        + [h.get_label() for h in rainfall_handles],
        ncol=3,
        loc="center left",
        frameon=False,
    )

    fig.tight_layout()
    # SAVE PLOT: change the filename or folder here if desired.
    fig.savefig("diurnal_soil_moisture_and_rainfall.png",
                dpi=300, bbox_inches="tight")
    plt.show()

### Throughfall analysis 
# CUSTOMIZE: update these column names if the throughfall columns in a new
# download have different names.  The text on the left ("AF"/"CF") is the
# plot label used in the calculations and should remain consistent.
# --- Throughfall column per plot in event_data (EDIT these to your 15-min column names) ---
tf_cols = {
    "AF": "Agroforestry_throughfall_mm",
    "CF": "CloudForest_throughfall_mm",
}

plot_colors = {
    "AF": COLORS["AF-primary"],
    "CF": COLORS["CF-primary"],
    "CA": COLORS["CA-primary"],
}

# --- Throughfall summed from event start to end of drying period ---
tf_frames = []
for name, col in tf_cols.items():
    tf = (
        event_data[event_data["event_id"].str.startswith(name + "_")]
        .groupby("event_id")[col]
        .sum(min_count=1)
        .rename("throughfall_mm")
        .reset_index()
    )
    tf_frames.append(tf)

ev = event_summary.merge(pd.concat(tf_frames), on="event_id")

# Gross rain over the same window (event + drying)
ev["gross_rain_mm"] = ev["event_total_rain_mm"] + ev["drying_rain_mm"].fillna(0)

# Drop events with missing values (and optionally truncated windows)
ev = ev.dropna(subset=["gross_rain_mm", "throughfall_mm"])
# CUSTOMIZE: this is an optional upper rainfall limit.  Increase it or remove
# this filter if large rainfall events should be included in the comparison.
ev = ev[ev['gross_rain_mm'] <= 40] # Keep only events where acc. gross rainfall <=40 mm to avoid skewing by large events
# ev = ev[~ev["drying_truncated_by_data_end"]]

groups = {name: ev[ev["plot"] == name] for name in tf_cols}
regs = {
    name: linregress(g["gross_rain_mm"], g["throughfall_mm"])
    for name, g in groups.items() if len(g) > 2
}

with plt.rc_context({
    "font.size": 8.5,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 7.5,
}):
    fig, ax = plt.subplots(figsize=(8, 5))

    # Scatter
    for name, g in groups.items():
        ax.scatter(
            g["gross_rain_mm"], g["throughfall_mm"],
            label=f"{name} event", color=plot_colors[name],
            s=24, alpha=0.75, edgecolors="none", zorder=2,
        )

    # Common limits for the 1:1 line (computed once, with padding)
    all_vals = np.concatenate([
        g[["gross_rain_mm", "throughfall_mm"]].to_numpy().ravel()
        for g in groups.values()
    ])
    lower = min(all_vals.min(), 0)
    upper = all_vals.max()
    pad = (upper - lower) * 0.05
    lo, hi = lower - pad, upper + pad

    ax.plot([lo, hi], [lo, hi], color="0.5", linestyle=":",
            linewidth=1.2, label="1:1 line", zorder=1)

    # Regression lines
    for name, reg in regs.items():
        g = groups[name]
        x = np.linspace(g["gross_rain_mm"].min(), g["gross_rain_mm"].max(), 100)
        ax.plot(
            x, reg.intercept + reg.slope * x,
            label=f"{name} regression, slope = {reg.slope:.2f} (n={g['gross_rain_mm'].count()})",
            color=plot_colors[name], linewidth=1.3, zorder=3,
        )

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")

    ax.set_xlabel("Gross rainfall (mm)")
    ax.set_ylabel("Throughfall (mm)")

    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.25, linewidth=0.6, zorder=0)
    ax.legend(loc="upper left", frameon=False,
              handlelength=1.4, labelspacing=0.6)

    fig.tight_layout()
    # SAVE PLOT: change the filename or folder here if desired.
    fig.savefig("throughfall_vs_gross_rainfall.png",
                dpi=300, bbox_inches="tight")
    plt.show()
    