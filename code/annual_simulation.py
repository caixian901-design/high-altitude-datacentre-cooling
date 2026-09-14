"""Annual hourly simulation of the cooling model using measured TMYx weather data.

Replaces the sinusoidal ambient-temperature approximation of the paper with
8760-hour EnergyPlus weather files (climate.onebuilding.org, TMYx 2011-2025) for
Xining (Qinghai plateau), Beijing and Shanghai.

Model per hour h:
  cop_air(T) = COP_AIR_FC * rho_r^gamma            if T <= T_AIR_FC   (air-side free cooling)
             = max(1.5, ETA_C * T_evap/(T_cond-T_evap))   otherwise    (chiller)
  cop_liq(T) = COP_LIQ_FC * rho_r^0.3               if T <= T_LIQ_FC   (dry cooler, pumped loop)
             = max(2.0, ETA_C * T_evap2/(T_cond-T_evap2))  otherwise   (chiller assist)
  PUE(f) = 1 + (1-f)/cop_air + f/cop_liq + LAM_D + LAM_O
"""
import csv
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIG = r"C:\Users\29102\Desktop\智算中心\figures"
WX = r"C:\Users\29102\dsh_fig\weather"
os.makedirs(FIG, exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.labelsize": 9,
    "legend.fontsize": 7.5, "xtick.labelsize": 8, "ytick.labelsize": 8,
    "axes.grid": True, "grid.alpha": 0.3, "grid.linestyle": ":",
    "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
})

P0, T0K, RS = 101.325, 288.15, 287.05
COP_AIR_FC, COP_LIQ_FC = 10.0, 20.0
ETA_C = 0.35
T_AIR_FC, T_LIQ_FC = 20.0, 32.0      # free-cooling thresholds (degC)
T_EVAP_AIR, T_EVAP_LIQ = 287.15, 288.15
LAM_D, LAM_O = 0.055, 0.02
GAMMA = 2.0
F_DESIGN = 0.8


def rho_r_at(elev_m):
    p = P0 * (1.0 - 2.25577e-5 * elev_m) ** 5.25588
    t = T0K - 0.0065 * elev_m
    rho = (p * 1000.0) / (RS * t)
    rho0 = (P0 * 1000.0) / (RS * T0K)
    return rho / rho0


def read_epw(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        rows = list(csv.reader(fh))
    loc = rows[0]
    elevation = float(loc[9])
    city = loc[1]
    lat, lon = float(loc[6]), float(loc[7])
    temps = []
    for r in rows[8:]:
        if len(r) < 10 or not r[6]:
            continue
        try:
            temps.append(float(r[6]))
        except ValueError:
            continue
    return dict(city=city, elevation=elevation, lat=lat, lon=lon,
                t=np.array(temps[:8760]))


def cop_air(T, rr):
    if T <= T_AIR_FC:
        return COP_AIR_FC * rr ** GAMMA
    t_cond = T + 5.0 + 273.15
    return max(1.5, ETA_C * T_EVAP_AIR / max(t_cond - T_EVAP_AIR, 3.0))


def cop_liq(T, rr):
    if T <= T_LIQ_FC:
        return COP_LIQ_FC * rr ** 0.3
    t_cond = T + 5.0 + 273.15
    return max(2.0, ETA_C * T_EVAP_LIQ / max(t_cond - T_EVAP_LIQ, 3.0))


def pue_annual(T, rr, f):
    ca = np.array([cop_air(t, rr) for t in T])
    cl = np.array([cop_liq(t, rr) for t in T])
    pue = 1.0 + (1.0 - f) / ca + f / cl + LAM_D + LAM_O
    return float(pue.mean())


sites = {
    "Xining (Qinghai plateau)": "xining",
    "Beijing": "beijing",
    "Shanghai": "shanghai",
}
data = {}
for label, key in sites.items():
    f_epw = glob.glob(os.path.join(WX, key, "*.epw"))[0]
    d = read_epw(f_epw)
    d["rho_r"] = rho_r_at(d["elevation"])
    data[label] = d
    print(f"{label:26s} elev={d['elevation']:7.1f} m  rho_r={d['rho_r']:.4f}  "
          f"Tmean={d['t'].mean():5.2f} C  Tmin={d['t'].min():6.2f}  Tmax={d['t'].max():5.2f}  n={len(d['t'])}")

fs = np.linspace(0, 1, 21)

# ------------------------------------------------------------------ Fig. 11 duration curves
fig, ax = plt.subplots(figsize=(3.8, 2.9))
for label, c in [("Xining (Qinghai plateau)", "#c0392b"), ("Beijing", "#2980b9"), ("Shanghai", "#16a085")]:
    t = np.sort(data[label]["t"])[::-1]
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
fig.savefig(os.path.join(FIG, "fig11_temperature_duration_curves.png"))
plt.close(fig)

# ------------------------------------------------------------------ Fig. 12 annual PUE vs f
fig, ax = plt.subplots(figsize=(3.8, 2.9))
table = []
for label, c in [("Xining (Qinghai plateau)", "#c0392b"), ("Beijing", "#2980b9"), ("Shanghai", "#16a085")]:
    d = data[label]
    pues = [pue_annual(d["t"], d["rho_r"], f) for f in fs]
    ax.plot(fs, pues, lw=1.8, color=c, label=f"{label} ({d['elevation']:.0f} m)")
    table.append((label, d, pues))
ax.axhline(1.15, color="#666", lw=0.9, ls="--")
ax.text(0.02, 1.155, "design target 1.15", fontsize=6.5, color="#444")
ax.plot([F_DESIGN], [pue_annual(data["Xining (Qinghai plateau)"]["t"], data["Xining (Qinghai plateau)"]["rho_r"], F_DESIGN)],
        "o", color="#c0392b", ms=5)
ax.set_xlabel("Liquid-cooling fraction $f$")
ax.set_ylabel("Annual average PUE (8760 h)")
ax.set_xlim(0, 1); ax.set_ylim(1.10, 1.40)
ax.legend(loc="upper right", framealpha=0.9)
fig.savefig(os.path.join(FIG, "fig12_annual_pue_tmy.png"))
plt.close(fig)

# ------------------------------------------------------------------ Fig. 13 free cooling + model check
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.7))

labels, air_fc, liq_fc = [], [], []
for label in sites:
    d = data[label]
    labels.append(label.split(" (")[0])
    air_fc.append(float((d["t"] <= T_AIR_FC).mean() * 100))
    liq_fc.append(float((d["t"] <= T_LIQ_FC).mean() * 100))

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
xs = np.linspace(2000, 9000, 400)
sin_mean = {}


def free_frac_sin(tavg, amp, thr, n=200000):
    tt = np.linspace(0, 8760, n)
    temp = tavg + amp * np.sin(2 * np.pi * (tt - 2190) / 8760)
    return float((temp < thr).mean() * 100)


sin_vals = [free_frac_sin(7.5, 12.5, 20), free_frac_sin(12.9, 14.6, 20), free_frac_sin(17.1, 11.8, 20)]
tmy_vals = air_fc
axes[1].scatter(sin_vals, tmy_vals, c=["#c0392b", "#2980b9", "#16a085"], s=42, zorder=5)
lim = [min(sin_vals + tmy_vals) - 6, max(sin_vals + tmy_vals) + 6]
axes[1].plot(lim, lim, color="#888", lw=0.9, ls="--")
for lbl, sx, ty in zip(labels, sin_vals, tmy_vals):
    axes[1].annotate(lbl, xy=(sx, ty), xytext=(sx - 5, ty + 4), fontsize=6.5)
axes[1].set_xlabel("Sinusoidal climate model (%)")
axes[1].set_ylabel("Measured TMYx weather (%)")
axes[1].set_xlim(lim); axes[1].set_ylim(lim)
axes[1].text(0.03, 0.92, "dashed line = perfect agreement", transform=axes[1].transAxes,
             fontsize=6.3, color="#666")
fig.savefig(os.path.join(FIG, "fig13_free_cooling_validation.png"))
plt.close(fig)

# ------------------------------------------------------------------ results table
print("\n=== Annual simulation results (TMYx 2011-2025, 8760 h) ===")
hdr = f"{'site':26s} {'elev':>6s} {'rho_r':>6s} {'Tmean':>6s} {'airFC%':>7s} {'liqFC%':>7s} {'PUE(f=0)':>9s} {'PUE(0.8)':>9s} {'PUE(1)':>7s}"
print(hdr)
rows = []
for label, d in data.items():
    p0 = pue_annual(d["t"], d["rho_r"], 0.0)
    p8 = pue_annual(d["t"], d["rho_r"], F_DESIGN)
    p1 = pue_annual(d["t"], d["rho_r"], 1.0)
    a = float((d["t"] <= T_AIR_FC).mean() * 100)
    l = float((d["t"] <= T_LIQ_FC).mean() * 100)
    print(f"{label:26s} {d['elevation']:6.0f} {d['rho_r']:6.3f} {d['t'].mean():6.2f} {a:7.1f} {l:7.1f} {p0:9.4f} {p8:9.4f} {p1:7.4f}")
    rows.append((label, d['elevation'], d['rho_r'], float(d['t'].mean()), a, l, p0, p8, p1))

# save a machine-readable table for the manuscript
with open(r"C:\Users\29102\dsh_fig\annual_sim_results.csv", "w", encoding="utf-8", newline="") as fh:
    wr = csv.writer(fh)
    wr.writerow(["site", "elevation_m", "rho_r", "Tmean_C", "air_free_cooling_pct",
                 "liquid_free_cooling_pct", "PUE_f0", "PUE_f0.8", "PUE_f1"])
    for r in rows:
        wr.writerow(r)
print("\nfigures: fig11, fig12, fig13 ; table: annual_sim_results.csv")
