"""
Infiltration capacity curve per plot  -  f(theta)
=================================================

INPUT: one Excel file, one row per pour. Required columns:
    Plot | LocationID | VisitDate | PourNum | Theta_before (m3/m3) | Time_s
(A Rate_mm_hr column may be present; it is ignored and recomputed from Time_s.)
Decimal commas ("0,161") and mixed date formats are handled. Empty template rows are skipped.

METHOD
  1. Rate per pour:      f_i = DEPTH_MM / t_i * 3600                              [mm/h]
  2. Horton per visit:   f(t) = fc + (f0 - fc) * exp(-k t)
       t = cumulative time at the MIDPOINT of each pour (pour 2 starts after pour 1 ends).
       If the fit fails, OR the curve has not levelled off by the last pour
       (exp(-k * t_last) > STEADY_TOL), fc = rate of the last pour (conservative).
  3. Per plot (field plots, e.g. AF, CA):
       ambient point  (theta_a, f_a)        = (mean theta_before, mean first-pour rate)
       wet point      (theta_max, fc_plot)  = (wettest observed sensor value, mean fc)
     Per plot (literature plots, e.g. CF):
       dry point      (theta_dry, f_dry)    from literature
       wet point      (theta_max, fc)       fc from literature, theta_max from the sensor
  4. Curve: straight line between the two points (linear in moisture deficit, Green-Ampt-like)
       f(theta) = fc_plot + (f_a - fc_plot) * (theta_max - theta) / (theta_max - theta_a)
       f = fc_plot  for theta >= theta_max
       f = f_a      for theta <= theta_a   (field plots only: no extrapolation below the data)
  5. Water balance: I(t) = min(q_in(t), f(theta(t)))  -> use f_theta(theta, plot_params)

OUTPUT (folder "infiltration_results/" next to the Excel file):
  - infiltration_results.xlsx  (sheets: per_visit, per_plot)
  - horton_<plot>.png          (Horton fits per visit, field plots)
  - curve_<plot>.png           (final f(theta) curve)

RUN:  python infiltration_curve.py  [path/to/file.xlsx]
"""

from pathlib import Path
import sys
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, to_hex, to_rgb
from scipy.optimize import curve_fit, OptimizeWarning

# 3 pours vs 3 Horton parameters -> covariance can't be estimated; that's expected
warnings.filterwarnings("ignore", category=OptimizeWarning)

# ============================================================================ SETTINGS
EXCEL_FILE = "infiltration_data_entry_template.xlsx"   # your single input file
SHEET = "Data"                    # sheet name or index
HEADER_ROW = 3                    # Excel row (1-based) holding the column headers
DEPTH_MM = 25.3                   # water depth per pour (mm)
STEADY_TOL = 0.10                 # Horton: max fraction of the decline still left at the last pour

# Wettest observed 10 cm soil moisture per plot (m3/m3) = wet anchor of the curve.
# Read automatically from the logger file: maximum of each plot's OWN sensor.
# Not true saturation - update when the record gets longer.
LOGGER_FILE = "water_balance_results/loggers_20261002-20261017_1h(6).csv"
SENSOR_COLS = {
    "CA": "Mayfly2_CA-10-SM_5TM_SoilMoisture_VWC_Pct",
    "CF": "HOBO_CF_SM_10cm_Pct_22253660",
    "AF": "Mayfly1_AF-10-SM_5TM_SoilMoisture_VWC_Pct",
}
THETA_MAX_OVERRIDE = {}     # e.g. {"CF": 0.358} to force a value from a longer record


def theta_max_from_loggers(path):
    path = Path(path)
    if not path.is_absolute():
        try:
            path = Path(__file__).parent / path      # look next to this script
        except NameError:
            pass
    log = pd.read_csv(path)
    tmax = {}
    for plot, col in SENSOR_COLS.items():
        s = pd.to_numeric(log[col], errors="coerce")
        if s.median() > 1:                           # sensor in % -> m3/m3
            s = s / 100
        tmax[plot] = round(float(s.max()), 4)
        print(f"THETA_MAX {plot}: {tmax[plot]:.4f}  (max of {col}, {s.count()} hours, "
              f"at {log.loc[s.idxmax(), log.columns[0]]})")
    tmax.update(THETA_MAX_OVERRIDE)
    return tmax


THETA_MAX = theta_max_from_loggers(LOGGER_FILE)

# Plots WITHOUT field infiltration tests: both anchor points from literature.
#   dry point: (theta_dry, f_dry)     wet point: (THETA_MAX[plot], fc)
# CF: Horton Group C typical values (InfoWorks): fc = 6.3 mm/h, f_dry = 125 mm/h at theta = 0.
LITERATURE = {
    "CF": {"fc": 6.3, "f_dry": 125.0, "theta_dry": 0.0},
}

# Site colours (same as the other CloudChasers figures)
SITE = {
    "CF": {"primary": "#2166AC", "secondary": "#5AA0D8"},   # Cloud forest
    "AF": {"primary": "#007A5E", "secondary": "#5DBB8A"},   # Agroforestry
    "CA": {"primary": "#CC8A22", "secondary": "#C2410C"},   # CA
}
DEFAULT_SITE = {"primary": "#52514e", "secondary": "#8a8984"}   # any plot not listed above
INK, INK_2, INK_3, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
COL_THETA = "Theta_before (m3/m3)"

plt.rcParams.update({
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelsize": 10, "axes.labelcolor": INK_2, "axes.edgecolor": INK_3, "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "xtick.color": INK_3, "ytick.color": INK_3, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
    "legend.frameon": False, "legend.fontsize": 9, "lines.solid_capstyle": "round",
    "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.facecolor": "white",
})


# ============================================================================ FUNCTIONS
def site(plot):
    return SITE.get(plot, DEFAULT_SITE)


def site_shades(plot, n):
    """n distinguishable shades of one plot's colour (dark primary -> primary -> secondary)."""
    s = site(plot)
    if n <= 2:
        return [s["primary"], s["secondary"]][:n]
    dark = to_hex(np.array(to_rgb(s["primary"])) * 0.55)
    cmap = LinearSegmentedColormap.from_list("site", [dark, s["primary"], s["secondary"]])
    return [to_hex(cmap(x)) for x in np.linspace(0, 1, n)]


def to_float(s):
    """Handles '0,161' and '0.161'."""
    return pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False).str.strip(),
                         errors="coerce")


def horton(t, fc, f0, k):
    return fc + (f0 - fc) * np.exp(-k * t)


def fit_horton(t_h, f):
    """Fit Horton to one visit (t_h in hours). Returns fc, f0, k, method."""
    try:
        (fc, f0, k), _ = curve_fit(horton, t_h, f,
                                   p0=[f[-1] * 0.9, f[0] * 1.5, 10.0],
                                   bounds=([0, 0, 1e-3], [f.min(), np.inf, 1e3]),
                                   maxfev=20000)
    except Exception:
        return f[-1], np.nan, np.nan, "last_pour (fit failed)"
    if np.exp(-k * t_h[-1]) > STEADY_TOL:          # curve not levelled off yet
        return f[-1], f0, k, "last_pour (not steady)"
    return fc, f0, k, "horton"


def f_theta(theta, p):
    """Infiltration capacity (mm/h) at soil moisture theta for one plot (p = row of per_plot)."""
    theta = np.asarray(theta, dtype=float)
    f = p["fc_plot"] + (p["f_a"] - p["fc_plot"]) * (p["theta_max"] - theta) / (p["theta_max"] - p["theta_a"])
    f = np.where(theta >= p["theta_max"], p["fc_plot"], f)
    if p["source"] == "field":                      # no extrapolation below the measured range
        f = np.where(theta <= p["theta_a"], p["f_a"], f)
    return f


def load_data(path):
    df = pd.read_excel(path, sheet_name=SHEET, header=HEADER_ROW - 1, dtype={"VisitDate": str})
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["Plot"].notna() & df["Time_s"].notna()].copy()        # drop empty template rows
    df["Plot"] = df["Plot"].astype(str).str.strip()
    df[COL_THETA] = to_float(df[COL_THETA])
    df["Time_s"] = to_float(df["Time_s"])
    df["PourNum"] = to_float(df["PourNum"]).astype(int)
    df["VisitDate"] = df["VisitDate"].astype(str).str.replace(" 00:00:00", "", regex=False).str.strip()
    df["rate"] = DEPTH_MM / df["Time_s"] * 3600
    return df


def fit_visits(df):
    visits = []
    for (plot, loc, date), g in df.groupby(["Plot", "LocationID", "VisitDate"], sort=False):
        g = g.sort_values("PourNum")
        t_mid_s = (g["Time_s"].cumsum() - g["Time_s"] / 2).values   # midpoint of each pour
        f = g["rate"].values
        fc, f0, k, method = fit_horton(t_mid_s / 3600, f)
        visits.append(dict(Plot=plot, LocationID=loc, VisitDate=date,
                           theta=g[COL_THETA].iloc[0], n_pours=len(g),
                           f1=f[0], f_last=f[-1], fc=fc, f0=f0, k_per_h=k, fc_method=method,
                           _t=t_mid_s, _f=f))
    return pd.DataFrame(visits)


def build_plots(pv):
    plots = []
    for plot, g in pv.groupby("Plot", sort=False):
        if plot not in THETA_MAX:
            print(f"WARNING: no THETA_MAX for plot {plot} - skipped. Add it in SETTINGS.")
            continue
        plots.append(dict(Plot=plot, source="field", n_visits=len(g),
                          theta_a=g["theta"].mean(), f_a=g["f1"].mean(), f_a_sd=g["f1"].std(),
                          theta_min=g["theta"].min(), theta_max_test=g["theta"].max(),
                          fc_plot=g["fc"].mean(), fc_sd=g["fc"].std(),
                          theta_max=THETA_MAX[plot]))
    for plot, lit in LITERATURE.items():
        if plot in set(pv["Plot"]):
            continue                                    # field data takes priority
        if plot not in THETA_MAX:
            print(f"WARNING: no THETA_MAX for plot {plot} - skipped. Add it in SETTINGS.")
            continue
        plots.append(dict(Plot=plot, source="literature", n_visits=0,
                          theta_a=lit["theta_dry"], f_a=lit["f_dry"], f_a_sd=np.nan,
                          theta_min=np.nan, theta_max_test=np.nan,
                          fc_plot=lit["fc"], fc_sd=np.nan, theta_max=THETA_MAX[plot]))
    pp = pd.DataFrame(plots)
    pp["slope_mm_h_per_theta"] = (pp["fc_plot"] - pp["f_a"]) / (pp["theta_max"] - pp["theta_a"])
    bad = pp[pp["theta_max"] <= pp["theta_a"]]
    for _, r in bad.iterrows():
        print(f"WARNING: plot {r['Plot']}: THETA_MAX ({r['theta_max']}) is not above the "
              f"ambient theta ({r['theta_a']:.3f}) - curve is invalid.")
    return pp


def titles(fig, ax, title, subtitle):
    """Bold left-aligned title with a muted subtitle line underneath."""
    ax.set_title(title, pad=24)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK_2, va="bottom")


def dodge(ys, min_gap):
    """Push label y-positions apart so no two are closer than min_gap (keeps order)."""
    order = np.argsort(ys)
    out = np.array(ys, dtype=float)
    for a, b in zip(order[:-1], order[1:]):
        if out[b] - out[a] < min_gap:
            out[b] = out[a] + min_gap
    return out


def plot_horton(plot, g, out_dir):
    fig, ax = plt.subplots(figsize=(8, 5))
    t_end = max(v[-1] for v in g["_t"]) / 60 * 1.12           # minutes
    ends = []
    colors = site_shades(plot, len(g))                          # shades of the plot's colour
    markers = ["o", "s", "^", "D", "v", "P"]                    # + marker shape per visit
    for i, (_, v) in enumerate(g.iterrows()):
        c = colors[i]
        t_min = v["_t"] / 60
        if v["fc_method"] == "horton":                 # draw curve only where it is used
            tt = np.linspace(0, t_end, 300)
            ax.plot(tt, horton(tt / 60, v["fc"], v["f0"], v["k_per_h"]), lw=2, color=c, zorder=2)
        else:                                          # fc = last pour: dashed level line
            ax.plot([0, t_end], [v["fc"]] * 2, ls="--", lw=1.5, color=c, zorder=2)
        tag = "" if v["fc_method"] == "horton" else " (last pour)"
        ax.plot(t_min, v["_f"], markers[i % len(markers)], ms=8, color=c, mec="white", mew=2, zorder=3,
                label=f"{v['LocationID']}  ·  {v['VisitDate']}")
        ends.append((v["fc"], f"fc {v['fc']:.0f}{tag}"))

    ymax = max(max(g["f0"].max(), 0), max(f.max() for f in g["_f"])) * 1.08
    ax.set_ylim(0, ymax)
    ax.set_xlim(0, t_end)
    # direct labels at the right end of each curve: the steady-state rate fc
    ys = dodge([e[0] for e in ends], ymax * 0.045)
    for (_, txt), y in zip(ends, ys):
        ax.annotate(txt, xy=(t_end, y), xytext=(6, 0), textcoords="offset points",
                    annotation_clip=False, va="center", fontsize=9, color=INK_2)
    ax.set_xlabel("Cumulative time since first pour (min)")
    ax.set_ylabel("Infiltration rate f (mm/h)")
    ax.legend(loc="upper right", title="Visit", title_fontsize=9, alignment="left")
    fig.savefig(out_dir / f"horton_{plot}.png")
    plt.close(fig)

def plot_curve(p, g, out_dir, width_in=6.0, height_in=3.8):
    """Report version: no title (caption in LaTeX), vector PDF + 300 dpi PNG."""
    plot = p["Plot"]
    field = p["source"] == "field"
    c_line, c_pts = site(plot)["primary"], site(plot)["secondary"]

    with plt.rc_context({
        "font.size": 9, "axes.labelsize": 9.5, "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5, "legend.fontsize": 8, "pdf.fonttype": 42,
    }):
        fig, ax = plt.subplots(figsize=(width_in, height_in))
        x_hi = max(p["theta_max"] + 0.1, 0.3)
        lo, hi = p["theta_a"], p["theta_max"]

        # solid between anchors, dashed where the curve is held constant
        seg = np.linspace(lo, hi, 50)
        ax.plot(seg, f_theta(seg, p), lw=2.2, color=c_line, zorder=3,
                label=r"$f(\theta)$ used in water balance")
        for a, b in ((0, lo), (hi, x_hi)):
            if b > a:
                s = np.linspace(a, b, 50)
                ax.plot(s, f_theta(s, p), lw=1.8, ls=(0, (4, 3)), color=c_line, zorder=3)
        ax.plot([], [], lw=1.8, ls=(0, (4, 3)), color=c_line,
                label="held constant (outside anchors)")

        if field:
            ax.axvspan(p["theta_min"], p["theta_max_test"], color=INK_3, alpha=0.12, lw=0,
                       label=r"$\theta$ range of field tests")
            ax.plot(g["theta"], g["f1"], "o", ms=6.5, color=c_pts, mec="white", mew=1.5,
                    zorder=4, label=r"first-pour rate $f_1$, per test")
            ax.errorbar(p["theta_a"], p["f_a"], yerr=p["f_a_sd"], fmt="none", ecolor=INK,
                        elinewidth=1.1, capsize=3.5, zorder=4)
            a_lbl, w_lbl = r"ambient (mean $\pm$ SD)", r"wet ($\theta_{max}$, mean $f_c$)"
        else:
            a_lbl, w_lbl = "dry (literature)", r"wet ($\theta_{max}$, literature $f_c$)"
        ax.plot(p["theta_a"], p["f_a"], "s", ms=7.5, color=INK, mec="white", mew=1.5,
                zorder=5, clip_on=False)
        ax.plot(p["theta_max"], p["fc_plot"], "D", ms=7.5, color=INK, mec="white", mew=1.5,
                zorder=5, clip_on=False)

        a_left = p["theta_a"] > 0.25 * x_hi
        for x, y, name, dx, ha in ((p["theta_a"], p["f_a"], a_lbl, -8 if a_left else 8,
                                    "right" if a_left else "left"),
                                   (p["theta_max"], p["fc_plot"], w_lbl, 8, "left")):
            ax.annotate(f"{name}\n" + rf"$\theta$ = {x:.3f},  $f$ = {y:.0f} mm h$^{{-1}}$",
                        xy=(x, y), xytext=(dx, 12), textcoords="offset points", ha=ha,
                        fontsize=7.5, color=INK, zorder=6,
                        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))

        top = max(p["f_a"] + (p["f_a_sd"] if field and pd.notna(p["f_a_sd"]) else 0),
                  g["f1"].max() if field else 0, p["fc_plot"])
        ax.set_xlim(0, x_hi)
        ax.set_ylim(0, top * 1.15)
        ax.set_xlabel(r"Soil moisture $\theta$ (m$^3$ m$^{-3}$)")
        ax.set_ylabel(r"Infiltration capacity $f$ (mm h$^{-1}$)")
        ax.legend(loc="upper right", frameon=False)
        ax.spines[["top", "right"]].set_visible(False)

       
        fig.tight_layout()
        fig.savefig(out_dir / f"curve_{plot}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)

# ============================================================================ MAIN
def main(path):
    path = Path(path)
    out_dir = path.parent / "infiltration_results"
    out_dir.mkdir(exist_ok=True)

    df = load_data(path)
    pv = fit_visits(df)
    pp = build_plots(pv)

    for _, p in pp.iterrows():
        g = pv[pv["Plot"] == p["Plot"]]
        if p["source"] == "field":
            plot_horton(p["Plot"], g, out_dir)
        plot_curve(p, g, out_dir)

    with pd.ExcelWriter(out_dir / "infiltration_results.xlsx") as xw:
        pv.drop(columns=["_t", "_f"]).round(4).to_excel(xw, sheet_name="per_visit", index=False)
        pp.round(4).to_excel(xw, sheet_name="per_plot", index=False)

    pd.set_option("display.width", 220)
    print("\nPer visit:\n", pv.drop(columns=["_t", "_f"]).round(3).to_string(index=False))
    print("\nPer plot:\n", pp.round(3).to_string(index=False))
    print(f"\nResults written to: {out_dir}")
    return pp


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else EXCEL_FILE)