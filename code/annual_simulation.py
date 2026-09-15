"""Annual hourly simulation of the cooling model using measured TMYx weather data.

Replaces the sinusoidal ambient-temperature approximation of the paper with
8760-hour EnergyPlus weather files (climate.onebuilding.org, TMYx 2011-2025) for
Xining (Qinghai plateau), Beijing and Shanghai.

Since v2 the atmosphere, the COP models and the PUE expression live in
``cooling_model.py`` and are imported here, so that the annual tables and the
GPU-load study of ``gpu_training_scan.py`` are guaranteed to use identical
physics.  This script is the driver: it loads the three sites, produces
figures 11-13 and the machine-readable annual table.

Model per hour h:
  cop_air(T) = COP_AIR_FC * rho_r^gamma            if T <= T_AIR_FC   (air-side free cooling)
             = max(1.5, ETA_C * T_evap/(T_cond-T_evap))   otherwise    (chiller)
  cop_liq(T) = COP_LIQ_FC * rho_r^0.3               if T <= T_LIQ_FC   (dry cooler, pumped loop)
             = max(2.0, ETA_C * T_evap2/(T_cond-T_evap2))  otherwise   (chiller assist)
  PUE(f) = 1 + (1-f)/cop_air + f/cop_liq + LAM_D + LAM_O

Weather location: set the HDC_WEATHER environment variable, or place the .epw
files in <repository>/weather/<site>/.  When a file is missing the sinusoidal
fallback climate is used and the console says so, so the script always runs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import cooling_model as cm

FIG = cm.FIGURE_DIR
cm.apply_style()

P0, T0K, RS = cm.P0_KPA, cm.T0_K, cm.RS
COP_AIR_FC, COP_LIQ_FC = cm.COP_AIR_FC, cm.COP_LIQ_FC
ETA_C = cm.ETA_C
T_AIR_FC, T_LIQ_FC = cm.T_AIR_FC, cm.T_LIQ_FC
LAM_D, LAM_O = cm.LAM_D, cm.LAM_O
GAMMA = cm.GAMMA
F_DESIGN = cm.F_DESIGN

rho_r_at = cm.rho_r_at
cop_air = cm.cop_air
cop_liq = cm.cop_liq
pue_annual = cm.pue_annual

PLOT_ORDER = [("Xining (Qinghai plateau)", "#c0392b"),
              ("Beijing", "#2980b9"),
              ("Shanghai", "#16a085")]

# ---------------------------------------------------------------------------
# Load the three sites
# ---------------------------------------------------------------------------
data = {}
for key, meta in cm.SITES.items():
    d = cm.load_site(key)
    data[meta["label"]] = d
    print(f"{d['label']:26s} elev={d['elevation']:7.1f} m  rho_r={d['rho_r']:.4f}  "
          f"Tmean={np.mean(d['t']):5.2f} C  Tmin={min(d['t']):6.2f}  "
          f"Tmax={max(d['t']):5.2f}  n={len(d['t'])}  [{d['source']}]")

fs = np.linspace(0, 1, 21)

# ------------------------------------------------------------------ Fig. 11 duration curves
fig, ax = plt.subplots(figsize=(3.8, 2.9))
for label, c in PLOT_ORDER:
    t = np.sort(np.asarray(data[label]["t"]))[::-1]
    hours = np.arange(1, len(t) + 1)
    ax.plot(hours / 1000.0, t, lw=1.6, color=c, label=label)
ax.axhline(T_AIR_FC, color="#444", lw=1.0, ls="--")
ax.text(0.3, T_AIR_FC + 1.0, "air-side free cooling threshold 20 $^\\circ$C", fontsize=6.4, color="#444")
ax.axhline(T_LIQ_FC, color="#2e8b57", lw=1.0, ls="-.")
ax.text(0.3, T_LIQ_FC + 1.0, "dry-cooler threshold 32 $^\\circ$C", fontsize=6.4, color="#2e8b57")
ax.set_xlabel("Hours per year exceeded (thousands)")
ax.set_ylabel("Dry-bulb temperature ($^\\circ$C)")
ax.set_xlim(0, 8.76); ax.set_ylim(-25, 42)
ax.legend(loc="upper right", framealpha=0.9)
cm.save(fig, "fig11_temperature_duration_curves.png")

# ------------------------------------------------------------------ Fig. 12 annual PUE vs f
fig, ax = plt.subplots(figsize=(3.8, 2.9))
for label, c in PLOT_ORDER:
    d = data[label]
    pues = [pue_annual(d["t"], d["rho_r"], f) for f in fs]
    ax.plot(fs, pues, lw=1.8, color=c, label=f"{label} ({d['elevation']:.0f} m)")
ax.axhline(1.15, color="#666", lw=0.9, ls="--")
ax.text(0.02, 1.155, "design target 1.15", fontsize=6.5, color="#444")
xining = data["Xining (Qinghai plateau)"]
ax.plot([F_DESIGN], [pue_annual(xining["t"], xining["rho_r"], F_DESIGN)],
        "o", color="#c0392b", ms=5)
ax.set_xlabel("Liquid-cooling fraction $f$")
ax.set_ylabel("Annual average PUE (8760 h)")
ax.set_xlim(0, 1); ax.set_ylim(1.10, 1.40)
ax.legend(loc="upper right", framealpha=0.9)
cm.save(fig, "fig12_annual_pue_tmy.png")

# ------------------------------------------------------------------ Fig. 13 free cooling + model check
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.7))

labels, air_fc, liq_fc = [], [], []
for label, _ in PLOT_ORDER:
    d = data[label]
    t = np.asarray(d["t"])
    labels.append(label.split(" (")[0])
    air_fc.append(float((t <= T_AIR_FC).mean() * 100))
    liq_fc.append(float((t <= T_LIQ_FC).mean() * 100))

x = np.arange(len(labels)); w = 0.36
axes[0].bar(x - w / 2, air_fc, w, color="#c0392b", label="air-side (20 $^\\circ$C)")
axes[0].bar(x + w / 2, liq_fc, w, color="#2e8b57", label="liquid / dry cooler (32 $^\\circ$C)")
for xi, v in zip(x - w / 2, air_fc):
    axes[0].text(xi, v + 1.5, f"{v:.1f}%", ha="center", fontsize=6.5)
for xi, v in zip(x + w / 2, liq_fc):
    axes[0].text(xi, v + 1.5, f"{v:.1f}%", ha="center", fontsize=6.5)
axes[0].set_xticks(x); axes[0].set_xticklabels(labels, fontsize=7.5)
axes[0].set_ylabel("Annual free cooling (%)"); axes[0].set_ylim(0, 118)
axes[0].legend(loc="lower left", fontsize=6.5, framealpha=0.9)

# model cross-check: sinusoidal (paper Section 3.4) vs TMYx
def free_frac_sin(tavg, amp, thr, n=200000):
    tt = np.linspace(0, 8760, n)
    temp = tavg + amp * np.sin(2 * np.pi * (tt - 2190) / 8760)
    return float((temp < thr).mean() * 100)


sin_vals = [free_frac_sin(cm.SINUSOID[k]["t_mean"], cm.SINUSOID[k]["amp"], T_AIR_FC)
            for k in cm.SITES]
tmy_vals = air_fc
axes[1].scatter(sin_vals, tmy_vals, c=[c for _, c in PLOT_ORDER], s=42, zorder=5)
lim = [min(sin_vals + tmy_vals) - 6, max(sin_vals + tmy_vals) + 6]
axes[1].plot(lim, lim, color="#888", lw=0.9, ls="--")
for lbl, sx, ty in zip(labels, sin_vals, tmy_vals):
    axes[1].annotate(lbl, xy=(sx, ty), xytext=(sx - 5, ty + 4), fontsize=6.5)
axes[1].set_xlabel("Sinusoidal climate model (%)")
axes[1].set_ylabel("Measured TMYx weather (%)")
axes[1].set_xlim(lim); axes[1].set_ylim(lim)
axes[1].text(0.03, 0.92, "dashed line = perfect agreement", transform=axes[1].transAxes,
             fontsize=6.3, color="#666")
cm.save(fig, "fig13_free_cooling_validation.png")

# ------------------------------------------------------------------ results table
print("\n=== Annual simulation results (TMYx 2011-2025, 8760 h) ===")
print(f"{'site':26s} {'elev':>6s} {'rho_r':>6s} {'Tmean':>6s} {'airFC%':>7s} "
      f"{'liqFC%':>7s} {'PUE(f=0)':>9s} {'PUE(0.8)':>9s} {'PUE(1)':>7s}")
rows = []
for label, _ in PLOT_ORDER:
    d = data[label]
    t = np.asarray(d["t"])
    p0 = pue_annual(t, d["rho_r"], 0.0)
    p8 = pue_annual(t, d["rho_r"], F_DESIGN)
    p1 = pue_annual(t, d["rho_r"], 1.0)
    a = float((t <= T_AIR_FC).mean() * 100)
    l = float((t <= T_LIQ_FC).mean() * 100)
    print(f"{label:26s} {d['elevation']:6.0f} {d['rho_r']:6.3f} {t.mean():6.2f} "
          f"{a:7.1f} {l:7.1f} {p0:9.4f} {p8:9.4f} {p1:7.4f}")
    rows.append((label, d["elevation"], d["rho_r"], float(t.mean()), a, l, p0, p8, p1))

path = cm.write_csv("annual_sim_results.csv",
                    ["site", "elevation_m", "rho_r", "Tmean_C",
                     "air_free_cooling_pct", "liquid_free_cooling_pct",
                     "PUE_f0", "PUE_f0.8", "PUE_f1"], rows)
print(f"\ntable: {path}")
print("figures: fig11, fig12, fig13")
