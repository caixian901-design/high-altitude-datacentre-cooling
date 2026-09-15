"""Figures for the GPU training-load / cooling / carbon trade-off study.

Companion to `make_figures.py` (Paper A).  Every curve is read back from the CSV
tables written by `gpu_training_scan.py`, so no number in any figure is typed by
hand.

    fig14_tradeoff_makespan_carbon.png   THE headline figure: makespan vs carbon
                                         with PUE overlaid, showing that PUE is
                                         flat while carbon moves 13x
    fig15_phase_overhead.png             communication share over the triangular
                                         (parallelism, interval) design space
    fig16_carbon_landscape.png           the three-way sweep: carbon across
                                         liquid fraction, grid scenario and
                                         schedule, with the density constraint
    fig17_carbon_aware_scheduling.png    same energy, different carbon: the grid
                                         time profile and the start-hour choice
    fig18_energy_vs_pue.png              same job, ten schedules: identical PUE,
                                         grid energy 15x apart

Run from the repository root:

    python code/make_figures_gpu.py
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import cooling_model as cm
import gpu_training_load as gtl

cm.apply_style()

DATA = cm.DATA_DIR

CI_COLOURS = {
    "const_030": "#2c3e50",
    "diel_030": "#c0392b",
    "qhd_015": "#2e8b57",
    "coal_060": "#8e44ad",
}
CI_SHORT = {
    "const_030": "flat 0.30",
    "diel_030": "diurnal 0.30",
    "qhd_015": "Qinghai 0.15",
    "coal_060": "coal 0.60",
}
F_REF = 0.8          # reference liquid fraction (the density-forced design point)


def read_csv(name: str) -> list[dict]:
    """Read a scan table, converting every field to float where possible."""
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}; run code/gpu_training_scan.py first")
    out = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rec = {}
            for k, v in row.items():
                if k == "ci_key":
                    rec[k] = v
                else:
                    try:
                        rec[k] = float(v)
                    except (TypeError, ValueError):
                        rec[k] = v
            out.append(rec)
    return out


def pareto(points) -> list[tuple[float, float]]:
    """Lower-left Pareto frontier of (x, y): nothing else is better in both."""
    pts = sorted(set(points))
    out, best = [], float("inf")
    for x, y in pts:
        if y < best - 1e-12:
            out.append((x, y))
            best = y
    return out


def effective_pue(site: dict, f: float) -> float:
    """Annual mean PUE over the measured weather record, at liquid fraction f."""
    return sum(cm.pue_instant(float(t), site["rho_r"], f) for t in site["t"]) / len(site["t"])


def main() -> int:
    par = read_csv("gpu_scan_parallel.csv")
    scan = read_csv("gpu_scan_training.csv")
    site = cm.load_site("xining", cm.WEATHER_DIR)
    job = gtl.default_job()
    f_min = gtl.min_liquid_fraction(gtl.rack_power_kw(job))

    # ======================================================================
    # Fig. 14 -- THE trade-off curve
    # ======================================================================
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.95))

    # ---- (a) every feasible schedule, coloured by liquid fraction.
    # Carbon relative to the f = 0.8 design, because the *sign* of the cooling
    # benefit flips with the schedule: a short job gets a bigger share of its
    # energy from the cooling plant, a long job's pumping energy accumulates.
    ax = axes[0]
    ref = {(r["parallelism"], r["interval"]): r["carbon_t"] for r in scan
           if r["ci_key"] == "diel_030" and abs(r["liquid_fraction"] - F_REF) < 1e-9}
    fs, xs, ys, cs = [], [], [], []
    for r in scan:
        if r["ci_key"] != "diel_030" or r["feasible"] != 1:
            continue
        key = (r["parallelism"], r["interval"])
        if key not in ref:
            continue
        fs.append(r["liquid_fraction"])
        xs.append(r["makespan_h"])
        ys.append(r["carbon_t"])
        cs.append(100.0 * (r["carbon_t"] / ref[key] - 1.0))

    lim = max(abs(min(cs)), abs(max(cs)))
    sc = ax.scatter(xs, ys, c=cs, cmap="coolwarm", vmin=-lim, vmax=lim,
                    s=13, linewidths=0.15, edgecolors="#333", zorder=4)
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label(f"carbon relative to $f$ = {F_REF} (%)", fontsize=7)

    front = pareto([(r["makespan_h"], r["carbon_t"]) for r in scan
                    if r["ci_key"] == "diel_030" and r["feasible"] == 1])
    ax.plot([p[0] for p in front], [p[1] for p in front], "k--", lw=1.2, zorder=3,
            label="Pareto frontier")
    d = min(par, key=lambda r: r["makespan_h"])
    s = max(par, key=lambda r: r["makespan_h"])
    ax.annotate(f"$P$ = 1024\n{d['makespan_h']:.2f} h, {d['carbon_t']:.1f} tCO$_2$e",
                xy=(d["makespan_h"], d["carbon_t"]), xytext=(4.6, 9.0), fontsize=6.2,
                color="#1f4e79",
                arrowprops=dict(arrowstyle="->", lw=0.7, color="#1f4e79"))
    ax.annotate(f"$P$ = 2\n{s['makespan_h']:.1f} h, {s['carbon_t']:.1f} tCO$_2$e",
                xy=(s["makespan_h"], s["carbon_t"]), xytext=(13.2, 52.0), fontsize=6.2,
                color="#1f4e79",
                arrowprops=dict(arrowstyle="->", lw=0.7, color="#1f4e79"))
    ax.set_xlabel("Makespan (h)")
    ax.set_ylabel("Carbon per job (tCO$_2$e)")
    ax.set_xlim(0, 23)
    ax.set_ylim(0, 70)
    ax.legend(loc="upper left", fontsize=6.5, framealpha=0.92)
    ax.set_title(r"(a) every feasible schedule ($I \geq P$)", fontsize=9)

    # ---- (b) the same x-axis, with mean PUE overlaid: the decoupling
    ax = axes[1]
    for ci_key in CI_COLOURS:
        pts = sorted((r["makespan_h"], r["carbon_t"]) for r in par
                     if r["ci_key"] == ci_key)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "-o", ms=3.0, lw=1.5,
                color=CI_COLOURS[ci_key], label=CI_SHORT[ci_key])
    ax.set_xlabel("Makespan (h)")
    ax.set_ylabel("Carbon per job (tCO$_2$e)")
    ax.set_xlim(0, 23)
    ax.set_ylim(0, 70)
    ax.legend(loc="upper left", fontsize=6.3,
              title="grid carbon intensity (kgCO$_2$e/kWh)", title_fontsize=6.3,
              framealpha=0.92)

    ax2 = ax.twinx()
    ax2.grid(False)
    pue_flat = par[0]["pue"]
    ax2.plot([r["makespan_h"] for r in par], [r["pue"] for r in par],
             color="#e67e22", lw=2.2, ls=":", zorder=5,
             label="mean PUE (right axis)")
    ax2.set_ylabel("Mean PUE", color="#e67e22")
    ax2.tick_params(axis="y", labelcolor="#e67e22")
    pue_all = [r["pue"] for r in scan]
    ax2.set_ylim(min(pue_all) - 0.005, max(pue_all) + 0.005)
    ax2.text(12.0, pue_flat - 0.017,
             f"PUE = {pue_flat:.4f} for all ten schedules\n"
             f"carbon spans {s['carbon_t']/d['carbon_t']:.1f}$\\times$",
             color="#e67e22", fontsize=6.4, ha="center")
    ax.set_title("(b) PUE is flat, carbon is not", fontsize=9)

    fig.tight_layout()
    cm.save(fig, "fig14_tradeoff_makespan_carbon.png")
    print("fig14: makespan vs carbon, PUE overlaid")

    # ======================================================================
    # Fig. 15 -- phase diagram of the communication share
    # ======================================================================
    ps = sorted({r["parallelism"] for r in scan})
    ivs = sorted({r["interval"] for r in scan})
    grid = np.full((len(ivs), len(ps)), np.nan)
    for r in scan:
        if r["ci_key"] == "const_030" and abs(r["liquid_fraction"] - F_REF) < 1e-9:
            grid[ivs.index(r["interval"]), ps.index(r["parallelism"])] = r["overhead_phi"]

    fig, ax = plt.subplots(figsize=(4.3, 3.1))
    masked = np.ma.masked_where(np.array([[iv < p for p in ps] for iv in ivs]), grid)
    mesh = ax.pcolormesh(np.array(ps, dtype=float), np.array(ivs, dtype=float),
                         masked * 100.0, cmap="YlOrRd", shading="nearest",
                         vmin=0, vmax=70)
    cb = fig.colorbar(mesh, ax=ax, pad=0.02)
    cb.set_label("Communication share $\\varphi$ (% of wall clock)", fontsize=7.5)

    ax.plot(ps, ps, "k-", lw=1.6, zorder=5)
    ax.text(150, 3.0, "infeasible\n$I < P$", fontsize=6.8, color="#555", ha="center")
    ax.text(9.0, 1600, "design space\n$I \\geq P$", fontsize=6.8, color="#555",
            ha="center")
    ax.annotate("", xy=(32, 32), xytext=(9, 9),
                arrowprops=dict(arrowstyle="->", lw=1.0, color="#7a3b00",
                                connectionstyle="arc3,rad=-0.3"), zorder=6)
    ax.text(4.6, 60, "$\\varphi$ falls as $I$ grows\n(fewer collectives)", fontsize=6.2,
            color="#7a3b00")
    ax.plot([32], [32], "o", color="#1f4e79", ms=6, zorder=6)
    ax.annotate("reference design\n$P$ = 32, $I$ = 32", xy=(32, 32), xytext=(90, 90),
                fontsize=6.2, color="#1f4e79",
                arrowprops=dict(arrowstyle="->", lw=0.7, color="#1f4e79"))
    ax.set_xscale("log", base=2)
    ax.set_yscale("log", base=2)
    ax.set_xlabel("Parallelism $P$ (accelerators)")
    ax.set_ylabel("Communication interval $I$ (steps)")
    fig.tight_layout()
    cm.save(fig, "fig15_phase_overhead.png")
    print("fig15: (P, I) phase diagram with the feasibility floor")

    # ======================================================================
    # Fig. 16 -- carbon landscape across the three swept parameters
    # ======================================================================
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.9))

    ax = axes[0]
    for ci_key in CI_COLOURS:
        pts = sorted((r["liquid_fraction"], r["carbon_t"]) for r in scan
                     if r["ci_key"] == ci_key and r["parallelism"] == 32
                     and r["interval"] == 100)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "-o", ms=3.0, lw=1.5,
                color=CI_COLOURS[ci_key], label=CI_SHORT[ci_key])
    ax.axvspan(0.0, f_min, color="#d9d9d9", zorder=0)
    ax.axvline(f_min, color="#555", lw=1.1, ls="--")
    ax.annotate(f"rack-density constraint\n$f \\geq$ {f_min:.2f}",
                xy=(f_min, 0.30), xycoords=("data", "axes fraction"),
                xytext=(0.06, 0.56), textcoords="axes fraction", fontsize=6.3,
                color="#333",
                arrowprops=dict(arrowstyle="->", lw=0.7, color="#555"))
    ax.set_xlabel("Liquid-cooling fraction $f$")
    ax.set_ylabel("Carbon per job (tCO$_2$e)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 20)
    ax.legend(loc="upper right", fontsize=6.4, framealpha=0.92)
    ax.set_title(r"(a) carbon vs $f$ at $P$ = 32, $I$ = 100", fontsize=9)

    # (b) overhead of the *fastest feasible* schedule, computed directly from the
    # model as I = P rather than read off the scan grid (whose interval grid would
    # make this curve zig-zag between grid values).
    ax = axes[1]
    p_grid = [1, 2, 4, 8, 16, 32, 64, 128, 256]
    ys16 = [job.overhead_fraction(p, max(1, int(round(p)))) * 100 for p in p_grid]
    ax.plot(p_grid, ys16, "-o", ms=3.4, lw=1.6, color="#1f4e79")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Parallelism $P$ (accelerators)")
    ax.set_ylabel("$\\varphi$ = communication share (\\% of wall clock)")
    ax.set_ylim(0, 52)
    for p, y in zip(p_grid, ys16):
        if p in (2, 16, 64, 256):
            ax.annotate(f"{y:.1f}%", xy=(p, y), xytext=(0, 5),
                        textcoords="offset points", fontsize=6.2, ha="center",
                        color="#1f4e79")
    ax.set_title(r"(b) overhead of the fastest schedule ($I = P$)", fontsize=9)

    fig.tight_layout()
    cm.save(fig, "fig16_carbon_landscape.png")
    print("fig16: carbon landscape and overhead scaling")

    # ======================================================================
    # Fig. 17 -- carbon-aware scheduling: same energy, different carbon
    # ======================================================================
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.8))

    hours = np.arange(0, 72)
    ax = axes[0]
    for ci_key in ("const_030", "diel_030", "qhd_015"):
        ci = gtl.CI_SCENARIOS[ci_key]
        ax.plot(hours, [ci.at_hour(h) for h in hours], lw=1.6,
                color=CI_COLOURS[ci_key], label=CI_SHORT[ci_key])
    ax.set_xlabel("Hour from job start")
    ax.set_ylabel("Grid carbon intensity (kgCO$_2$e/kWh)")
    ax.set_xlim(0, 71)
    ax.legend(loc="upper right", fontsize=6.4, framealpha=0.92)
    ax.set_title("(a) the grid has a time profile", fontsize=9)

    # (b) a fixed energy budget, spent at different start hours: the plant and
    # the kWh are identical, only the timing changes.
    ax = axes[1]
    e_kwh = par[0]["grid_energy_mwh"] * 1000.0        # P = 1024 fastest point
    durations = [1.22, 3.0, 6.0, 12.0, 24.0]
    ci = gtl.CI_SCENARIOS["diel_030"]
    flat = gtl.CI_SCENARIOS["const_030"]
    times = np.linspace(0, 24, 200, endpoint=False)

    def carbon_of(start_h: float, dur_h: float, ci_obj) -> float:
        """kgCO2e per job when the fixed energy budget is spent over dur_h hours."""
        n = max(1, int(np.ceil(dur_h - 1e-9)))
        c = 0.0
        for h in range(n):
            dt = min(1.0, dur_h - h)
            if dt <= 0:
                break
            c += e_kwh * dt / dur_h * ci_obj.at_hour(start_h + h)
        return c / 1000.0                              # tCO2e

    curves = {dur: [carbon_of(t, dur, ci) for t in times] for dur in durations}
    for dur in durations:
        ax.plot(times, curves[dur], lw=1.5, label=f"{dur:g} h")

    flat_val = carbon_of(0.0, durations[0], flat)
    ax.axhline(flat_val, color="#2c3e50", lw=1.1, ls="--")
    ax.text(21.5, flat_val * 1.04, "flat grid", fontsize=6.0, color="#2c3e50",
            ha="right", va="bottom")

    # quantify the scheduling opportunity: best and worst start hour, 12 h job
    ref_dur = 12.0
    ys_ref = curves[ref_dur]
    i_best = int(np.argmin(ys_ref))
    i_worst = int(np.argmax(ys_ref))
    ax.axvspan(times[max(i_best - 1, 0)], times[min(i_best + 1, len(times) - 1)],
               color="#2e8b57", alpha=0.13, zorder=0)
    swing = 100.0 * (ys_ref[i_worst] / ys_ref[i_best] - 1.0)
    ax.annotate(f"12 h job: starting at {times[i_best]:.0f}:00 instead of "
                f"{times[i_worst]:.0f}:00 costs {swing:.0f}% more carbon",
                xy=(times[i_worst], ys_ref[i_worst]),
                xytext=(0.03, 0.34), textcoords="axes fraction", fontsize=6.1,
                color="#2e8b57", ha="left", va="bottom",
                arrowprops=dict(arrowstyle="->", lw=0.7, color="#2e8b57",
                                connectionstyle="arc3,rad=0.22"))

    ax.set_xlabel("Job start hour (local time)")
    ax.set_ylabel("Carbon per job (tCO$_2$e)")
    ax.set_xlim(0, 24)
    ax.set_ylim(0, max(max(v) for v in curves.values()) * 1.20)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), fontsize=6.0,
              ncol=5, title="job duration", title_fontsize=6.2, frameon=False,
              columnspacing=1.1, handlelength=1.4)
    ax.set_title(f"(b) same energy ({e_kwh/1000:.1f} MWh), different carbon",
                 fontsize=9)

    fig.tight_layout()
    cm.save(fig, "fig17_carbon_aware_scheduling.png")
    print("fig17: carbon-aware scheduling")

    # ======================================================================
    # Fig. 18 -- energy versus PUE for the ten schedules
    # ======================================================================
    fig, ax = plt.subplots(figsize=(4.5, 3.0))
    rows = sorted([r for r in par if r["ci_key"] == "diel_030"],
                  key=lambda r: r["parallelism"])
    ax.bar([str(int(r["parallelism"])) for r in rows],
           [r["grid_energy_mwh"] for r in rows],
           color="#2980b9", width=0.62)
    ax.set_xlabel("Parallelism $P$ (accelerators)")
    ax.set_ylabel("Grid energy per job (MWh)", color="#1f4e79")
    ax.tick_params(axis="y", labelcolor="#1f4e79")
    ax.tick_params(axis="x", labelsize=7)
    for i, r in enumerate(rows):
        ax.text(i, r["grid_energy_mwh"] + 5, f"{r['makespan_h']:.1f} h",
                ha="center", fontsize=5.8, color="#1f4e79")
    ax.text(0.97, 0.58,
            f"mean PUE = {rows[0]['pue']:.4f}\nfor all ten bars\n"
            f"(the plant does not change;\nthe duty cycle does)",
            transform=ax.transAxes, ha="right", fontsize=6.4, color="#c0392b")
    ax.set_ylim(0, max(r["grid_energy_mwh"] for r in rows) * 1.15)
    ax.set_title("Same job, ten schedules", fontsize=9)
    fig.tight_layout()
    cm.save(fig, "fig18_energy_vs_pue.png")
    print("fig18: energy per job across schedules")

    # ======================================================================
    print()
    print("key values printed on the figures:")
    d = min([r for r in par if r["ci_key"] == "diel_030"],
            key=lambda r: r["makespan_h"])
    s = max([r for r in par if r["ci_key"] == "diel_030"],
            key=lambda r: r["makespan_h"])
    print(f"  fastest : P={d['parallelism']:.0f}  T={d['makespan_h']:.2f} h  "
          f"carbon={d['carbon_t']:.2f} t  PUE={d['pue']:.4f}")
    print(f"  slowest : P={s['parallelism']:.0f}  T={s['makespan_h']:.2f} h  "
          f"carbon={s['carbon_t']:.2f} t  PUE={s['pue']:.4f}")
    print(f"  carbon ratio {s['carbon_t']/d['carbon_t']:.1f}x ; "
          f"PUE ratio {s['pue']/d['pue']:.4f}")
    print()
    print("PUE vs f (annual mean, measured TMYx weather):")
    for f in (0.0, 0.5, 0.519, 0.8, 1.0):
        print(f"  f = {f:.3f}  PUE = {effective_pue(site, f):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
