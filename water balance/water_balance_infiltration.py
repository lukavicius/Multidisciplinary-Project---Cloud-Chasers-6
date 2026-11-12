"""
Hourly infiltration per plot  -  I(t) = min[ q_in(t), f_plot(theta(t)) * dt ]      [mm per hour]
================================================================================================
For each plot, the hourly water reaching the soil is compared with the infiltration capacity
f(theta) of that plot (curve from infiltration_curve.py), for TWO inputs, using the same capacity:

  plot  meas  (measured input)                               Pe  (modelled input)
  CF    TF + SF (gauges, CF-2 override 11-12 Oct)             P_e
  AF    TF + SF                                               P_e
  CA    P of the CA rain gauge, gaps filled with CF rain x0.92 P_e

  theta(t)  = plot's 10 cm sensor at the START of the hour (previous record), % -> m3/m3
  f(t)      = f_theta(theta(t), plot curve)            [mm/h]
  I(t)      = min(q_in(t), f(t) * dt)                  [mm]
  excess(t) = q_in(t) - I(t)                           [mm]  infiltration-excess runoff

Rules:
  - q_in = 0                           -> I = 0 (nothing to infiltrate, theta not needed)
  - theta gaps up to MAX_GAP_H         -> interpolated
  - no theta, q_in <= fc_plot          -> I = q_in (below the lowest possible capacity)
  - no theta, q_in > fc_plot           -> I = NaN
  - no input value                     -> I = NaN

INPUTS
  - water (P, TF, SF, Pe): ONLY ../codeWB/interception/outputs_v2/interception_output_<plot>_hourly.csv.
    These contain the CF-2 override and the gap-filled CA P, so measured input and P_e are consistent.
    CA_P_SOURCE = "logger" rebuilds CA P from the logger instead (same rule), for checking.
  - soil moisture: LOGGER_FILE, one column per plot (THETA_COLS), reindexed on the interception hours
  - curves: CURVE_FILE, sheet per_plot

OUTPUTS (folder water_balance_results/ next to this script)
  - infiltration_hourly.csv     long format: Timestamp, Plot, input (meas/Pe), q_in_mm, theta_used,
                                f_cap_mm_h, I_mm, excess_mm, f_limited, status
  - infiltration_summary.csv    per plot and input: totals, runoff, hours limited by f, max input, min f
  - infiltration_Pe_for_WB.csv  infiltration term for wb_terms_by_plot.py: CF, AF, CA = P_e (no runoff
                                assumed), I_cap_<plot> = I limited by f(theta) with P_e input, runoff_<plot>
  - infiltration_<plot>.png     (a) measured input vs f(theta), (b) P_e vs f(theta), log axis

RUN:  python water_balance_infiltration.py
"""

from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

from infiltration_curve import f_theta

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "codeWB"))
from cc_colors import SITE, INK, INK2, apply_style        # CloudChasers colour code

# ============================================================================ SETTINGS
LOGGER_FILE = HERE / "water_balance_results/loggers_20261002-20261017_1h(6).csv"
CURVE_FILE = HERE / "infiltration_results/infiltration_results.xlsx"      # from infiltration_curve.py
WATER_FILE = HERE / "../codeWB/interception/outputs_v2/interception_output_{plot}_hourly.csv"
OUT_DIR = HERE / "water_balance_results"

COL_TIME = "Timestamp"
PLOTS = ["CF", "AF", "CA"]
THETA_COLS = {
    "CF": "HOBO_CF_SM_10cm_Pct_22253660",
    "AF": "Mayfly1_AF-10-SM_5TM_SoilMoisture_VWC_Pct",
    "CA": "Mayfly2_CA-10-SM_5TM_SoilMoisture_VWC_Pct",
}
S_MAX = {"CF": 3.5, "AF": 1.2, "CA": 0.5}           # canopy storage of the interception model (mm)

# CA P: "interception" (default, from the interception file) or "logger" (rebuilt here)
CA_P_SOURCE = "interception"
CA_GAUGES = ("Mayfly2_CA-1-TF_Rain_mm", "ConvAgriculture_rain_mm")   # before / after CA_SWITCH
CA_SWITCH = "2026-10-12 00:00"
CA_FILL_COL = "HOBO_Rain_OpenSky_mm"                # CF open-sky gauge
CA_FILL_FACTOR = 0.92

DT_H = 1.0                                          # timestep (h)
MAX_GAP_H = 6                                       # interpolate theta gaps up to this many hours

INPUT_LABEL = {
    ("CF", "meas"): r"$TF + SF$ measured",
    ("AF", "meas"): r"$TF + SF$ measured",
    ("CA", "meas"): r"$P$ measured (CA gauge, gaps from CF $\times$0.92)",
}


# ============================================================================ FUNCTIONS
def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False).str.strip(), errors="coerce")


def label(plot, inp):
    if inp == "Pe":
        return rf"$P_e$ modelled ($S_{{max}}$ = {S_MAX[plot]:g} mm)"
    return INPUT_LABEL[(plot, inp)]


def print_curve_params(curve_path):
    """f(theta) parameters per plot, to check against the soil data."""
    pp = pd.read_excel(curve_path, sheet_name="per_plot").set_index("Plot")
    print("f(theta) parameters per plot (infiltration_curve.py):")
    print("  K_s: not a model parameter - f(theta) is a line between two anchor points;")
    print("       fc_plot (wet end) is the closest analogue and an upper bound for K_fs.")
    for plot, p in pp.iterrows():
        dry = "first-pour rate" if p["source"] == "field" else "literature f0"
        wet = "Horton fc" if p["source"] == "field" else "literature fc"
        print(f"  {plot} ({p['source']}, {int(p['n_visits'])} visits): "
              f"dry ({dry}) f = {p['f_a']:.1f} mm/h at theta = {p['theta_a']:.3f};  "
              f"wet ({wet}) fc = {p['fc_plot']:.1f} mm/h at theta_max = {p['theta_max']:.4f};  "
              f"slope {p['slope_mm_h_per_theta']:.0f} mm/h per m3/m3")
    print()
    return pp


def read_logger(path):
    log = pd.read_csv(path, sep=None, engine="python")
    log.columns = [str(c).strip() for c in log.columns]
    log[COL_TIME] = pd.to_datetime(log[COL_TIME], errors="coerce")
    log = log.dropna(subset=[COL_TIME]).sort_values(COL_TIME)
    if log[COL_TIME].duplicated().any():
        raise ValueError(f"{Path(path).name}: duplicated timestamps")
    return log.set_index(COL_TIME)


def read_water(plot):
    f = Path(str(WATER_FILE).format(plot=plot)).resolve()
    w = pd.read_csv(f, parse_dates=[COL_TIME])
    if w[COL_TIME].duplicated().any():
        raise ValueError(f"{f.name}: duplicated timestamps")
    return w.set_index(COL_TIME)


def theta_series(log, col, index):
    """theta at the START of each hour (m3/m3), reindexed on the interception hours."""
    th = num(log[col])
    if th.median() > 1:                                           # sensor in % -> m3/m3
        th = th / 100
    th = th.interpolate(limit=int(MAX_GAP_H / DT_H), limit_area="inside")
    return th.shift(1).reindex(index)                             # previous record = start of hour


def ca_p_from_logger(log, index):
    """CA P rebuilt from the logger: CA gauges, NaN hours filled with the CF open-sky gauge x factor."""
    before = log.index < pd.Timestamp(CA_SWITCH)
    p = num(log[CA_GAUGES[0]]).where(before, num(log[CA_GAUGES[1]]))
    fill = p.isna() & num(log[CA_FILL_COL]).notna()
    p = p.where(~fill, num(log[CA_FILL_COL]) * CA_FILL_FACTOR)
    print(f"  CA: P from logger, {int(fill.reindex(index).sum())} hours filled with "
          f"{CA_FILL_COL} x {CA_FILL_FACTOR}")
    return p.reindex(index)


def infiltration(q, theta, p):
    """Hourly infiltration for input q (mm per hour) and theta (m3/m3); p = curve row of the plot."""
    q = pd.Series(q, dtype=float)
    d = pd.DataFrame({"q_in_mm": q, "theta_used": theta})
    f = pd.Series(f_theta(theta.to_numpy(dtype=float), p), index=q.index)
    d["f_cap_mm_h"] = f.where(theta.notna())
    d["I_mm"] = np.minimum(q, d["f_cap_mm_h"] * DT_H)
    d.loc[q == 0, "I_mm"] = 0.0
    below_fc = d["f_cap_mm_h"].isna() & (q > 0) & (q <= p["fc_plot"] * DT_H)
    d.loc[below_fc, "I_mm"] = q[below_fc]
    d["excess_mm"] = q - d["I_mm"]
    d["f_limited"] = d["excess_mm"] > 1e-9
    d["status"] = np.select(
        [q.isna(), q == 0, below_fc, d["I_mm"].isna(), d["f_limited"]],
        ["no input data", "no input", "no theta, q_in < fc", "input but no theta", "limited by f(theta)"],
        "limited by input")
    return d


def summarise(h):
    rows = []
    for (plot, inp), g in h.groupby(["Plot", "input"], sort=False):
        v = g[g["q_in_mm"].notna()]
        wet = v[v["q_in_mm"] > 0]
        q, x = v["q_in_mm"].sum(), v["excess_mm"].sum()
        rows.append({
            "Plot": plot, "input": inp, "input_label": label(plot, inp),
            "first": v[COL_TIME].min(), "last": v[COL_TIME].max(), "hours": len(v),
            "input_mm": q, "I_mm": v["I_mm"].sum(), "runoff_mm": x,
            "runoff_pct_of_input": 100 * x / q if q > 0 else np.nan,
            "hours_limited_by_f": int(v["f_limited"].sum()),
            "hours_I_missing": int(v["I_mm"].isna().sum()),
            "max_input_mm_h": v["q_in_mm"].max(),
            "min_f_mm_h": v["f_cap_mm_h"].min(),
            "min_f_during_input_mm_h": wet["f_cap_mm_h"].min(),
        })
    return pd.DataFrame(rows)


# ============================================================================ FIGURE
RED, GAP = "#d03b3b", "#ecebe6"
apply_style()
plt.rcParams.update({"savefig.dpi": 300, "savefig.bbox": "tight", "savefig.facecolor": "white"})


def gap_spans(ax, t, missing):
    """Shade runs of consecutive hours without theta (each hour centred on its timestamp)."""
    half = pd.Timedelta(minutes=30)
    run = (missing != missing.shift()).cumsum()
    for _, r in t[missing].groupby(run[missing]):
        ax.axvspan(r.iloc[0] - half, r.iloc[-1] + half, color=GAP, lw=0, zorder=0)


def make_figure(h, plot, out, width_in=6.3, height_in=5.0):
    g = h[h["Plot"] == plot]
    width = pd.Timedelta(minutes=55)
    primary = SITE[plot]["primary"]
    colours = {"meas": primary, "Pe": tuple(np.array(matplotlib.colors.to_rgb(primary)) * 0.55)}
    top = 3 * np.nanmax([g["f_cap_mm_h"].max(), g["q_in_mm"].max()])

    with plt.rc_context({"font.size": 8.5, "axes.labelsize": 9, "xtick.labelsize": 8,
                         "ytick.labelsize": 8, "legend.fontsize": 7.5}):
        fig, axes = plt.subplots(2, 1, figsize=(width_in, height_in), sharex=True, sharey=True,
                                 gridspec_kw={"hspace": 0.42})
        for ax, inp, tag in zip(axes, ["meas", "Pe"], ["(a)", "(b)"]):
            d = g[g["input"] == inp].reset_index(drop=True)
            t, c = d[COL_TIME], colours[inp]
            missing = d["theta_used"].isna()
            gap_spans(ax, t, missing)

            wet = d[d["q_in_mm"] > 0]
            ax.bar(wet[COL_TIME], wet["I_mm"], width=width, color=c, lw=0, zorder=2)
            ex = wet[wet["excess_mm"] > 1e-9]
            ax.bar(ex[COL_TIME], ex["excess_mm"], bottom=ex["I_mm"], width=width, color=RED, lw=0, zorder=2)
            ax.plot(ex[COL_TIME], ex["q_in_mm"] * 1.6, "v", ms=4, color=RED, zorder=4, clip_on=False)
            ax.plot(t, d["f_cap_mm_h"], color=INK, lw=1.2, zorder=3)

            ax.set_yscale("log")
            ax.set_ylim(0.05, top)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:g}"))
            ax.set_ylabel(r"mm h$^{-1}$")

            n_ex, x_sum = len(ex), d["excess_mm"].sum()
            ax.text(0.99, 0.04, f"input {d['q_in_mm'].sum():.1f} mm · runoff {x_sum:.1f} mm ({n_ex} h)",
                    transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=INK2, zorder=5,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.9))

            handles = [plt.Rectangle((0, 0), 1, 1, color=c), plt.Rectangle((0, 0), 1, 1, color=RED),
                       plt.Line2D([], [], color=INK, lw=1.2)]
            labels = [f"{label(plot, inp)}, infiltrated",
                      "infiltration-excess runoff" + ("" if n_ex else " (none)"),
                      r"infiltration capacity $f(\theta)$"]
            if missing.any():
                handles.append(plt.Rectangle((0, 0), 1, 1, color=GAP))
                labels.append(r"no $\theta$ data")
            ax.legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2,
                      frameon=False, handlelength=1.4, columnspacing=1.2, borderaxespad=0)
            ax.text(-0.1, 1.01, tag, transform=ax.transAxes, fontweight="bold", va="bottom", color=INK)

        axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=2))
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        fig.savefig(out, dpi=300)
        plt.close(fig)


# ============================================================================ MAIN
def main():
    pp = print_curve_params(CURVE_FILE)
    pp.index = pp.index.astype(str).str.strip().str.upper()
    log = read_logger(LOGGER_FILE)
    OUT_DIR.mkdir(exist_ok=True)

    hourly = []
    for plot in PLOTS:
        w = read_water(plot)
        theta = theta_series(log, THETA_COLS[plot], w.index)
        if plot == "CA":
            meas = ca_p_from_logger(log, w.index) if CA_P_SOURCE == "logger" else w["P"]
        else:
            meas = w["TF"] + w["SF"].fillna(0.0)
        print(f"  {plot}: {w.index.min()} -> {w.index.max()}, {len(w)} h, "
              f"{int(theta.isna().sum())} h without theta")
        for inp, q in (("meas", meas), ("Pe", w["Pe"])):
            d = infiltration(q.reset_index(drop=True), theta.reset_index(drop=True), pp.loc[plot])
            d.insert(0, COL_TIME, w.index)
            d.insert(1, "Plot", plot)
            d.insert(2, "input", inp)
            hourly.append(d)
    h = pd.concat(hourly, ignore_index=True)
    summary = summarise(h)

    cols = ["Timestamp", "Plot", "input", "q_in_mm", "theta_used", "f_cap_mm_h", "I_mm", "excess_mm",
            "f_limited", "status"]
    h[cols].round(4).to_csv(OUT_DIR / "infiltration_hourly.csv", index=False)
    summary.round(3).to_csv(OUT_DIR / "infiltration_summary.csv", index=False)

    # infiltration term for the water balance (wb_terms_by_plot.py): I = P_e (no runoff assumed)
    pe = h[h["input"] == "Pe"]
    wide = lambda v: pe.pivot(index=COL_TIME, columns="Plot", values=v)[PLOTS]
    pd.concat([wide("q_in_mm"), wide("I_mm").add_prefix("I_cap_"), wide("excess_mm").add_prefix("runoff_")],
              axis=1).round(4).to_csv(OUT_DIR / "infiltration_Pe_for_WB.csv")

    for plot in PLOTS:
        make_figure(h, plot, OUT_DIR / f"infiltration_{plot}.png")

    # runoff hours, for the text
    ex = h[h["f_limited"]]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    show = summary.drop(columns="input_label")
    print("\nSummary per plot and input:\n", show.round(2).to_string(index=False))
    if len(ex):
        print("\nHours limited by f(theta):\n",
              ex[["Timestamp", "Plot", "input", "q_in_mm", "f_cap_mm_h", "excess_mm"]].round(2).to_string(index=False))
    print(f"\nResults written to: {OUT_DIR}")
    return h, summary


if __name__ == "__main__":
    main()
