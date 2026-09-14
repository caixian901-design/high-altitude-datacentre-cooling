"""Figure generation for Paper A: high-altitude AI data centre cooling & PUE model.

All curves are computed from the analytical model in the manuscript:
  ISA pressure/temperature -> air density ratio -> air-side penalties -> PUE(f, h)
Figures are written as 300-dpi PNGs into ./figures.
"""
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

OUT = r"C:\Users\29102\Desktop\智算中心\论文\figures"
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.labelsize": 9.5,
    "axes.titlesize": 10,
    "legend.fontsize": 8,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": ":",
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

P0, T0, RS = 101.325, 288.15, 287.05
LAPSE, EXP = 0.0065, 5.25588


def pressure_kpa(h):
    return P0 * (1.0 - 2.25577e-5 * h) ** EXP


def temp_k(h):
    return T0 - LAPSE * h


def rho(h):
    return (pressure_kpa(h) * 1000.0) / (RS * temp_k(h))


RHO0 = rho(0.0)


def rho_r(h):
    return rho(h) / RHO0


# Model parameters (Table 1 of the manuscript)
COP_A0, COP_L = 8.0, 20.0
LAM_D, LAM_O = 0.055, 0.02
H_SITE = 2200.0
F_DESIGN = 0.8


def cop_air(h, gamma=2.0):
    return COP_A0 * rho_r(h) ** gamma


def pue(f, h, gamma=2.0):
    return 1.0 + (1.0 - f) / cop_air(h, gamma) + f / COP_L + LAM_D + LAM_O


ALT = np.linspace(0, 3500, 400)
alts = [0, 1000, 2000, 2200, 2500, 3000]

# ---------------------------------------------------------------- Fig. 1 schematic
fig, ax = plt.subplots(figsize=(7.0, 3.4))
ax.set_xlim(0, 100); ax.set_ylim(0, 52); ax.axis("off"); ax.grid(False)

def box(x, y, w, h, text, fc="#eef2f8", ec="#33507a", fs=8, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.2",
                                fc=fc, ec=ec, lw=1.0))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, weight=weight, wrap=True)

box(3, 20, 17, 12, "IT load\n$P_{IT}$ = 12 MW", fc="#dce6f5", weight="bold")

# liquid branch
box(28, 33, 20, 11, "Cold-plate liquid loop\n(CDU, N+1)", fc="#dff3e3", ec="#3c7a4a")
box(56, 33, 22, 11, "Dry cooler\n(40/50 $^\\circ$C warm water)", fc="#dff3e3", ec="#3c7a4a")
box(84, 33, 13, 11, "Altitude\nindependent", fc="#f6f6f6", ec="#888")

# air branch
box(28, 6, 20, 11, "Air-side loop\n(CRAH / heat exchanger)", fc="#fdeaea", ec="#a4443f")
box(56, 6, 22, 11, "Ambient air at altitude\n$\\rho_r$ = 0.805 @ 2,200 m", fc="#fdeaea", ec="#a4443f")
box(84, 6, 13, 11, "Capacity $-19.5\\%$\nFan $+54.3\\%$", fc="#f6f6f6", ec="#888")

ax.text(24.5, 40.5, "f = 0.8", fontsize=8.5, ha="center", color="#3c7a4a", weight="bold")
ax.text(24.5, 13.5, "1 - f = 0.2", fontsize=8.5, ha="center", color="#a4443f", weight="bold")

for (x0, y0, x1, y1) in [(20, 27, 28, 37), (20, 25, 28, 12)]:
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=11,
                                 lw=1.1, color="#444", connectionstyle="arc3,rad=-0.15"))
for (x0, y0, x1, y1) in [(48, 38.5, 56, 38.5), (48, 11.5, 56, 11.5), (78, 38.5, 84, 38.5), (78, 11.5, 84, 11.5)]:
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=11, lw=1.1, color="#444"))

ax.text(50, 0.5, r"PUE$(f,h)=1+\frac{1-f}{COP_a(h)}+\frac{f}{COP_l}+\lambda_d+\lambda_o$,   "
               r"$COP_a(h)=COP_{a,0}\,\rho_r(h)^{\gamma}$",
        ha="center", va="bottom", fontsize=9)
fig.savefig(os.path.join(OUT, "fig01_model_framework.png"))
plt.close(fig)

# ------------------------------------------------- Fig. 2 pressure and density vs altitude
fig, ax1 = plt.subplots(figsize=(3.6, 2.7))
ax1.plot(ALT, [pressure_kpa(h) for h in ALT], color="#1f4e79", lw=1.8, label="Pressure")
ax1.set_xlabel("Altitude (m)"); ax1.set_ylabel("Atmospheric pressure (kPa)", color="#1f4e79")
ax1.tick_params(axis="y", labelcolor="#1f4e79")
ax1.set_xlim(0, 3500); ax1.set_ylim(60, 105)

ax2 = ax1.twinx(); ax2.grid(False)
ax2.plot(ALT, [rho_r(h) for h in ALT], color="#c0392b", lw=1.8, ls="--", label="Density ratio")
ax2.set_ylabel(r"Air density ratio $\rho_r$", color="#c0392b")
ax2.tick_params(axis="y", labelcolor="#c0392b"); ax2.set_ylim(0.6, 1.02)

for h, lab in [(H_SITE, "site 2,200 m"), (3000, "3,000 m")]:
    ax1.axvline(h, color="#777", lw=0.8, ls=":")
    ax1.annotate(lab, xy=(h, 63), fontsize=7, rotation=90, color="#555", va="bottom", ha="right")
ax1.plot([H_SITE], [pressure_kpa(H_SITE)], "o", color="#1f4e79", ms=4)
ax2.plot([H_SITE], [rho_r(H_SITE)], "o", color="#c0392b", ms=4)
ax1.annotate(f"{pressure_kpa(H_SITE):.1f} kPa\n$\\rho_r$={rho_r(H_SITE):.3f}",
             xy=(H_SITE, pressure_kpa(H_SITE)), xytext=(1500, 88), fontsize=7,
             arrowprops=dict(arrowstyle="->", lw=0.8, color="#555"))
h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
ax1.legend(h1 + h2, l1 + l2, loc="lower left", framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig02_pressure_density_vs_altitude.png"))
plt.close(fig)

# ----------------------------------------------------- Fig. 3 air-side penalties vs altitude
fig, ax = plt.subplots(figsize=(3.6, 2.7))
ax.plot(ALT, [(1 - rho_r(h)) * 100 for h in ALT], color="#1f4e79", lw=1.8, label=r"Capacity loss $1-\rho_r$")
ax.plot(ALT, [(1 / rho_r(h) ** 2 - 1) * 100 for h in ALT], color="#c0392b", lw=1.8, label=r"Fan power $\rho_r^{-2}-1$")
ax.plot(ALT, [(1 - rho_r(h) ** 0.8) * 100 for h in ALT], color="#2e8b57", lw=1.8, ls="-.", label=r"Heat transfer $1-\rho_r^{0.8}$")
ax.axvline(H_SITE, color="#777", lw=0.8, ls=":")
vals = [(1 - rho_r(H_SITE)) * 100, (1 / rho_r(H_SITE) ** 2 - 1) * 100, (1 - rho_r(H_SITE) ** 0.8) * 100]
for v, c in zip(vals, ["#1f4e79", "#c0392b", "#2e8b57"]):
    ax.plot([H_SITE], [v], "o", color=c, ms=4)
    ax.annotate(f"{v:.1f}%", xy=(H_SITE, v), xytext=(H_SITE + 120, v + 2), fontsize=7, color=c)
ax.set_xlabel("Altitude (m)"); ax.set_ylabel("Penalty relative to sea level (%)")
ax.set_xlim(0, 3500); ax.set_ylim(0, 90)
ax.legend(loc="upper left", framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig03_airside_penalties.png"))
plt.close(fig)

# ------------------------------------------------------------------- Fig. 4 PUE vs f
fig, ax = plt.subplots(figsize=(3.6, 2.7))
fs = np.linspace(0, 1, 200)
colors = {0: "#2c3e50", 1000: "#2980b9", 2200: "#c0392b", 3000: "#8e44ad"}
for h in [0, 1000, 2200, 3000]:
    ax.plot(fs, [pue(f, h) for f in fs], lw=1.8, color=colors[h], label=f"h = {h:,} m")
ax.plot([F_DESIGN], [pue(F_DESIGN, H_SITE)], "o", color="#c0392b", ms=5, zorder=5)
ax.annotate(f"design point\nPUE = {pue(F_DESIGN, H_SITE):.3f}", xy=(F_DESIGN, pue(F_DESIGN, H_SITE)),
            xytext=(0.30, 1.20), fontsize=7, color="#c0392b",
            arrowprops=dict(arrowstyle="->", lw=0.8, color="#c0392b"))
ax.axhline(1.15, color="#666", lw=0.9, ls="--")
ax.text(0.02, 1.152, "design target 1.15", fontsize=7, color="#444")
ax.set_xlabel("Liquid-cooling fraction $f$"); ax.set_ylabel("PUE")
ax.set_xlim(0, 1); ax.set_ylim(1.11, 1.32)
ax.legend(loc="upper right", framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig04_pue_vs_liquid_fraction.png"))
plt.close(fig)

# --------------------------------------------------- Fig. 5 altitude PUE penalty vs f
fig, ax = plt.subplots(figsize=(3.6, 2.7))
for h, c in [(1000, "#2980b9"), (2200, "#c0392b"), (3000, "#8e44ad")]:
    ax.plot(fs, [pue(f, h) - pue(f, 0) for f in fs], lw=1.8, color=c, label=f"h = {h:,} m")
ax.plot([F_DESIGN], [pue(F_DESIGN, H_SITE) - pue(F_DESIGN, 0)], "o", color="#c0392b", ms=5)
ax.annotate("+0.014\n(79% mitigated)", xy=(F_DESIGN, pue(F_DESIGN, H_SITE) - pue(F_DESIGN, 0)),
            xytext=(0.42, 0.055), fontsize=7, color="#c0392b",
            arrowprops=dict(arrowstyle="->", lw=0.8, color="#c0392b"))
ax.annotate("+0.068\n(air only)", xy=(0, pue(0, H_SITE) - pue(0, 0)), xytext=(0.06, 0.088),
            fontsize=7, color="#c0392b", arrowprops=dict(arrowstyle="->", lw=0.8, color="#c0392b"))
ax.set_xlabel("Liquid-cooling fraction $f$"); ax.set_ylabel(r"Altitude PUE penalty $\Delta$PUE")
ax.set_xlim(0, 1); ax.set_ylim(0, 0.115)
ax.legend(loc="upper right", framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig05_altitude_penalty_mitigation.png"))
plt.close(fig)

# ------------------------------------------------------- Fig. 6 sensitivity to gamma
fig, ax = plt.subplots(figsize=(3.6, 2.7))
gam = np.linspace(1.0, 2.0, 100)
for f, c in [(0.0, "#c0392b"), (0.4, "#e67e22"), (0.8, "#2e8b57")]:
    ax.plot(gam, [pue(f, H_SITE, g) for g in gam], lw=1.8, color=c, label=f"f = {f:.1f}")
ax.axvspan(1.0, 2.0, color="#f0f0f0", zorder=0)
ax.annotate("f = 0.8 band:\n1.146 - 1.154", xy=(1.5, pue(0.8, H_SITE, 1.5)),
            xytext=(1.18, 1.185), fontsize=7, color="#2e8b57",
            arrowprops=dict(arrowstyle="->", lw=0.8, color="#2e8b57"))
ax.set_xlabel(r"Fan-penalty exponent $\gamma$"); ax.set_ylabel("PUE at 2,200 m")
ax.set_ylim(1.12, 1.28); ax.legend(loc="center right", framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig06_sensitivity_gamma.png"))
plt.close(fig)

# ------------------------------------------------------------ Fig. 7 free cooling
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))

t = np.linspace(0, 8760, 2000)
plateau = 7.5 + 12.5 * np.sin(2 * np.pi * (t - 2190) / 8760)
temperate = 16.0 + 11.0 * np.sin(2 * np.pi * (t - 2190) / 8760)
axes[0].plot(t / 730.0, plateau, color="#c0392b", lw=1.4, label="Plateau, 2,200 m")
axes[0].plot(t / 730.0, temperate, color="#2980b9", lw=1.4, label="Temperate, sea level")
axes[0].axhline(20, color="#444", lw=1.0, ls="--")
axes[0].text(0.5, 20.8, "air-side threshold 20 $^\\circ$C", fontsize=6.5, color="#444")
axes[0].axhline(32, color="#2e8b57", lw=1.0, ls="-.")
axes[0].text(0.5, 32.8, "dry-cooler threshold 32 $^\\circ$C", fontsize=6.5, color="#2e8b57")
axes[0].set_xlabel("Month"); axes[0].set_ylabel("Ambient temperature ($^\\circ$C)")
axes[0].set_xlim(0, 12); axes[0].set_ylim(-8, 36)
axes[0].legend(loc="upper left", fontsize=6.5)

def free_frac(tavg, amp, thr, n=200000):
    tt = np.linspace(0, 8760, n)
    temp = tavg + amp * np.sin(2 * np.pi * (tt - 2190) / 8760)
    return float(np.mean(temp < thr)) * 100

groups = ["Air-side\n(plateau)", "Air-side\n(temperate)", "Liquid / dry cooler"]
vals7 = [free_frac(7.5, 12.5, 20), free_frac(16.0, 11.0, 20), free_frac(7.5, 12.5, 32)]
cols = ["#c0392b", "#2980b9", "#2e8b57"]
bars = axes[1].bar(groups, vals7, color=cols, width=0.55)
for b, v in zip(bars, vals7):
    axes[1].text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.0f}%", ha="center", fontsize=7.5)
axes[1].set_ylabel("Annual free cooling (%)"); axes[1].set_ylim(0, 118)
axes[1].tick_params(axis="x", labelsize=7.5)
fig.savefig(os.path.join(OUT, "fig07_free_cooling.png"))
plt.close(fig)

# ------------------------------------------------------------- Fig. 8 design space
fig, ax = plt.subplots(figsize=(3.6, 2.7))
q = np.linspace(20, 120, 300)
for lim, c, ls in [(15, "#8e44ad", ":"), (20, "#c0392b", "--"), (25, "#e67e22", "-.")]:
    fmin = np.clip(1 - lim / q, 0, 1)
    ax.plot(q, fmin, lw=1.6, color=c, ls=ls, label=f"air limit {lim} kW/rack")
ax.fill_between(q, 0, np.clip(1 - 20 / q, 0, 1), color="#fdeaea", zorder=0)
ax.plot([45], [F_DESIGN], "*", color="#1f4e79", ms=13, zorder=5)
ax.annotate("design: 45 kW, f = 0.8\n(PUE = 1.154)", xy=(45, F_DESIGN), xytext=(52, 0.30), fontsize=7,
            arrowprops=dict(arrowstyle="->", lw=0.8, color="#1f4e79"))
for lvl, c in [(1.154, "#2e8b57"), (1.20, "#e67e22"), (1.268, "#c0392b")]:
    ax.axhline(lvl, color=c, lw=0.8, alpha=0.55)
    ax.text(104, lvl + 0.008, f"PUE {lvl:.3f}", fontsize=6.5, color=c)
ax.set_xlabel("Rack power (kW)"); ax.set_ylabel("Required liquid fraction $f_{min}$")
ax.set_xlim(20, 120); ax.set_ylim(0, 0.95)
ax.legend(loc="upper left", fontsize=6.5, framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig08_design_space.png"))
plt.close(fig)

# ------------------------------------------------- Fig. 9 energy saving vs CAPEX
fig, ax = plt.subplots(figsize=(3.6, 2.7))
E_IT = 12000 * 0.85 * 8760 / 1e6          # GWh/yr
d_pue = pue(0, H_SITE) - pue(F_DESIGN, H_SITE)
save_kwh = E_IT * 1e6 * d_pue * 5 / 1e6   # million kWh over 5 years
price = np.linspace(0.20, 0.80, 200)
ax.plot(price, save_kwh * price, color="#2e8b57", lw=2.0, label="5-yr energy saving (f: 0$\\to$0.8)")
for capex, c, ls in [(2000, "#8e44ad", ":"), (2500, "#c0392b", "--"), (3000, "#e67e22", "-.")]:
    prem = 12000 * F_DESIGN * capex / 1e6    # million CNY
    ax.axhline(prem, color=c, lw=1.4, ls=ls, label=f"CAPEX premium @ {capex} CNY/kW")
    be = prem / save_kwh
    if 0.20 <= be <= 0.80:
        ax.plot([be], [prem], "o", color=c, ms=5)
        ax.annotate(f"{be:.2f}", xy=(be, prem), xytext=(be - 0.02, prem + 2.5), fontsize=7, color=c)
ax.set_xlabel("Electricity price (CNY/kWh)"); ax.set_ylabel("Million CNY")
ax.set_xlim(0.20, 0.80); ax.set_ylim(0, 45)
ax.legend(loc="upper left", fontsize=6.5, framealpha=0.9)
fig.savefig(os.path.join(OUT, "fig09_energy_capex_breakeven.png"))
plt.close(fig)

# --------------------------------------------------------- Fig. 10 energy breakdown
fig, ax = plt.subplots(figsize=(3.6, 2.7))
f_d = F_DESIGN
cool_air = (1 - f_d) * 12000 / cop_air(H_SITE)
cool_liq = f_d * 12000 / COP_L
labels = ["IT equipment", "Cooling\n(air side)", "Cooling\n(liquid side)", "Power\ndistribution", "Lighting\n& auxiliary"]
vals10 = [12000, cool_air, cool_liq, LAM_D * 12000, LAM_O * 12000]
cols10 = ["#1f4e79", "#c0392b", "#2e8b57", "#e67e22", "#7f8c8d"]
bars = ax.barh(labels[::-1], vals10[::-1], color=cols10[::-1], height=0.6)
for b, v in zip(bars, vals10[::-1]):
    ax.text(v + 120, b.get_y() + b.get_height() / 2, f"{v:,.0f} kW", va="center", fontsize=7)
ax.set_xlabel("Power (kW)"); ax.set_xlim(0, 14200)
ax.text(0.98, 0.06, f"PUE = {pue(f_d, H_SITE):.3f}", transform=ax.transAxes, ha="right",
        fontsize=9, weight="bold", color="#c0392b")
fig.savefig(os.path.join(OUT, "fig10_energy_breakdown.png"))
plt.close(fig)

# --------------------------------------------------------------- console summary
print("figures written to", OUT)
for f in sorted(os.listdir(OUT)):
    print(" ", f, os.path.getsize(os.path.join(OUT, f)), "bytes")
print("\nkey model values:")
for h in alts:
    print(f"  h={h:5.0f} m  p={pressure_kpa(h):6.2f} kPa  rho_r={rho_r(h):.4f}  "
          f"capLoss={(1-rho_r(h))*100:5.2f}%  fanPen={(1/rho_r(h)**2-1)*100:6.2f}%  "
          f"PUE(f=0)={pue(0,h):.4f}  PUE(f=0.8)={pue(0.8,h):.4f}")
print(f"  design PUE (2,200 m, f=0.8) = {pue(F_DESIGN, H_SITE):.4f}")
print(f"  altitude penalty f=0 -> {pue(0,H_SITE)-pue(0,0):+.4f}, f=0.8 -> {pue(0.8,H_SITE)-pue(0.8,0):+.4f}")
print(f"  5-yr saving basis = {save_kwh:.1f} million kWh; break-even price @2500 CNY/kW = "
      f"{12000*F_DESIGN*2500/1e6/save_kwh:.3f} CNY/kWh")
