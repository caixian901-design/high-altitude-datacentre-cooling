"""Parameter scan: communication interval x liquid-cooling fraction x carbon intensity.

This is the experiment the training-load model makes possible.  It couples three
layers that are usually studied in isolation:

    training schedule   ->  IT power and duty cycle       (gpu_training_load.py)
    cooling design      ->  hourly PUE at plateau ambient  (cooling_model.py)
    electricity grid    ->  hourly carbon intensity        (CarbonIntensity)

and reports, for every combination, the four numbers a design decision actually
trades off:

    makespan   h        how long the job takes to finish
    PUE        -        mean of the facility over those hours
    energy     MWh      grid energy drawn for the whole job
    carbon     tCO2e    grid energy weighted by the *hourly* carbon intensity

Three facts about the feasible design space shape the whole scan:

1.  **I >= P is a hard floor.**  A job spread over P accelerators cannot
    synchronise less often than once per compute phase, so the schedule with
    I = P is the fastest one available at that parallelism and the design space
    is triangular.
2.  **Parallelism saturates.**  Amdahl's law caps cluster throughput at 1/s, so
    beyond a certain P extra accelerators stop buying speed -- while still
    buying energy consumption and carbon.
3.  **The plant is sized on peak but billed on mean.**  The collective phase is a
    lull in the heat load, so the longer a job spends communicating the lower its
    mean IT power, while the peak stays pinned at P_compute.

Outputs (written to ../data):

    gpu_scan_training.csv    full (P, I, f, CI-scenario) sweep
    gpu_scan_parallel.csv    headline makespan / PUE / carbon versus parallelism
    gpu_scan_deadline.csv    carbon-optimal schedule that meets each deadline
    gpu_scan_summary.json    machine-readable headline findings + all constants

Run from the repository root:

    python code/gpu_training_scan.py
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cooling_model as cm
import gpu_training_load as gtl

# ---------------------------------------------------------------------------
# Experiment definition
# ---------------------------------------------------------------------------
SITE = "xining"                       # 2 266 m, Qinghai plateau

# Parallelism, in accelerators dedicated to the job.  The reference model needs
# ~85 GB of weights plus optimizer state, so P >= 2 is the smallest parallelism
# at which it can be held at all; P = 1024 is where the Amdahl ceiling bites.
PARALLELISMS = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]

# Communication intervals, in steps between two collectives.  Only I >= P is
# physical; values below P are kept in the grid to mark the infeasible region.
INTERVALS = [1, 2, 4, 5, 10, 25, 32, 50, 100, 250, 500, 1000]

# Liquid-cooling fractions.  Paper A's density constraint forces f >= 0.519 for a
# 41.6 kW rack, so 0.0 / 0.2 / 0.4 are retained only as infeasible reference points.
FRACTIONS = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 0.9, 1.0]

CI_KEYS = ["const_030", "diel_030", "qhd_015", "coal_060"]

F_DESIGN = 0.8                        # Paper A reference liquid fraction
P_SWEEP = 32                          # parallelism fixed in the 3-way sweep
DEADLINES_H = [2.0, 2.5, 3.0, 4.0, 6.0, 9.0, 13.0, 18.0, 21.0]


def job_metrics(job: gtl.JobSpec, site: dict, parallelism: float, interval: int,
                f: float, ci: gtl.CarbonIntensity, ci_key: str = "") -> dict:
    """Couple one training schedule to the facility and to the grid.

    The job runs for ``makespan`` hours starting at hour 0 of the weather record
    with a constant IT load.  Facility power therefore tracks the hourly ambient
    temperature through the PUE, and carbon tracks both the load and the hourly
    grid intensity.  A partial final hour is charged pro rata, so the short
    high-parallelism jobs are not over-charged a whole hour.
    """
    rho = job.duty_cycle(parallelism, interval)
    makespan_h = job.makespan_s(parallelism, interval) / 3600.0
    p_it_w = job.it_power_w(rho)

    n_h = max(1, int(math.ceil(makespan_h - 1e-9)))
    e_grid_kwh = e_it_kwh = carbon_kg = pue_sum = 0.0
    for h in range(n_h):
        dt_h = min(1.0, makespan_h - h)
        if dt_h <= 0:
            break
        t_amb = float(site["t"][h % len(site["t"])])
        pue_h = cm.pue_instant(t_amb, site["rho_r"], f)
        p_grid_w = p_it_w * pue_h
        e_grid_kwh += p_grid_w * dt_h / 1000.0
        e_it_kwh += p_it_w * dt_h / 1000.0
        carbon_kg += p_grid_w * dt_h / 1000.0 * ci.at_hour(h)
        pue_sum += pue_h * dt_h

    speedup = job.speedup(parallelism, interval)
    carbon_kg_per_step = carbon_kg / job.n_steps
    # Cluster-normalised metric: the job occupies `parallelism` of the n_gpu
    # machines available, and while it runs nothing else is trained on them.  The
    # rate at which the whole facility converts electricity into delivered
    # training steps is therefore
    #     throughput [steps/s] = N / makespan  (this job)
    #     carbon per step      = carbon / N
    # both *per job*, but the site-level figures must divide by the fraction of
    # the cluster the job used, so they are reported per GPU as well.
    return dict(
        parallelism=parallelism,
        interval=interval,
        interval_over_p=interval / parallelism,
        feasible=int(interval >= parallelism),
        overhead_phi=job.overhead_fraction(parallelism, interval),
        duty_cycle=rho,
        makespan_h=makespan_h,
        speedup=speedup,
        speedup_per_accelerator=speedup / parallelism,
        throughput_steps_per_s=job.n_steps / (makespan_h * 3600.0),
        throughput_per_gpu_steps_per_s=job.n_steps / (makespan_h * 3600.0) / parallelism,
        p_it_mw=p_it_w / 1e6,
        p_grid_mw=p_it_w * (pue_sum / makespan_h) / 1e6,
        pue=pue_sum / makespan_h,
        it_energy_mwh=e_it_kwh / 1000.0,
        grid_energy_mwh=e_grid_kwh / 1000.0,
        energy_overhead_mwh=(e_grid_kwh - e_it_kwh) / 1000.0,
        carbon_t=carbon_kg / 1000.0,
        carbon_per_step_g=carbon_kg_per_step * 1000.0,
        cl_energy_kwh_per_step=e_grid_kwh / job.n_steps,
        liquid_fraction=f,
        ci_key=ci_key,
        ci_base=ci.base,
    )


SCAN_FIELDS = ["parallelism", "interval", "interval_over_p", "feasible",
               "overhead_phi", "duty_cycle", "makespan_h", "speedup",
               "speedup_per_accelerator", "throughput_steps_per_s",
               "throughput_per_gpu_steps_per_s", "p_it_mw", "p_grid_mw", "pue",
               "it_energy_mwh", "grid_energy_mwh", "energy_overhead_mwh",
               "carbon_t", "carbon_per_step_g", "cl_energy_kwh_per_step",
               "liquid_fraction", "ci_key", "ci_base"]


def fastest_grid_interval(parallelism: float) -> int:
    """Smallest interval *on the scanned grid* that satisfies the I >= P floor.

    The physics allows I = P exactly, but the scan evaluates a fixed grid of
    intervals so that the phase diagram has a comparable resolution everywhere.
    Every headline number therefore quotes the interval this returns.
    """
    for i in INTERVALS:
        if i >= parallelism:
            return i
    return INTERVALS[-1]


def main() -> int:
    job = gtl.default_job()
    site = cm.load_site(SITE, cm.WEATHER_DIR)
    rack_kw = gtl.rack_power_kw(job)
    f_min = gtl.min_liquid_fraction(rack_kw)
    print(f"site              : {site['label']} ({site['source']}, "
          f"{site['elevation']:.0f} m, rho_r = {site['rho_r']:.4f})")
    print(f"job               : {job.n_steps:,} steps x {job.t_step1_s:.1f} s, "
          f"{job.n_gpu:,} accelerators available, PCIe fabric")
    print(f"peak IT power     : {job.peak_power_w()/1e6:.2f} MW "
          f"({job.p_compute_w + job.p_other_w:.0f} W per accelerator, compute phase)")
    print(f"rack peak power   : {rack_kw:.1f} kW -> density-forced f_min = {f_min:.3f}")
    print(f"Amdahl ceiling    : {1/job.s_frac:.0f}x (serial fraction s = {job.s_frac})")
    print()

    # ================================================================ section 1
    print("=== Section 1: fastest feasible schedule vs parallelism "
          "(I = P, f = 0.80, diurnal 0.30 kg/kWh grid) ===")
    ci_head = gtl.CI_SCENARIOS["diel_030"]
    rows_par = []
    print(f"{'P':>5} {'phi':>7} {'rho':>6} {'S':>6} {'S/P':>7} {'T (h)':>7} "
          f"{'P_IT(MW)':>9} {'P_grid':>7} {'PUE':>6} {'E(MWh)':>8} {'C(t)':>7}")
    for p in PARALLELISMS:
        i = fastest_grid_interval(p)
        m = job_metrics(job, site, p, i, F_DESIGN, ci_head, "diel_030")
        rows_par.append(m)
        print(f"{p:5d} {m['overhead_phi']:7.4f} {m['duty_cycle']:6.3f} "
              f"{m['speedup']:6.2f} {m['speedup_per_accelerator']:7.3f} "
              f"{m['makespan_h']:7.2f} {m['p_it_mw']:9.3f} {m['p_grid_mw']:7.2f} "
              f"{m['pue']:6.4f} {m['grid_energy_mwh']:8.1f} {m['carbon_t']:7.2f}")
    cm.write_csv("gpu_scan_parallel.csv", SCAN_FIELDS,
                 [[r[k] for k in SCAN_FIELDS] for r in rows_par])

    # ================================================================ section 2
    n_pts = len(PARALLELISMS) * len(INTERVALS) * len(FRACTIONS) * len(CI_KEYS)
    print()
    print(f"=== Section 2: (P, I) x liquid fraction x carbon intensity "
          f"= {n_pts} points ===")
    rows_scan = []
    for ci_key in CI_KEYS:
        ci = gtl.CI_SCENARIOS[ci_key]
        for p in PARALLELISMS:
            for i in INTERVALS:
                for f in FRACTIONS:
                    rows_scan.append(job_metrics(job, site, p, i, f, ci, ci_key))
    cm.write_csv("gpu_scan_training.csv", SCAN_FIELDS,
                 [[r[k] for k in SCAN_FIELDS] for r in rows_scan])
    print(f"wrote {len(rows_scan)} rows -> data/gpu_scan_training.csv")

    idx = {(r["ci_key"], r["parallelism"], r["interval"], r["liquid_fraction"]): r
           for r in rows_scan}

    def cell(ci_key, p, i, f, key):
        return idx[(ci_key, p, i, f)][key]

    print()
    print(f"PUE vs liquid fraction (P = {P_SWEEP}; identical at every I, because "
          f"PUE is a property of f and the weather, not of the schedule)")
    print("    f  " + "".join(f"{f:>9.1f}" for f in FRACTIONS))
    print("  PUE  " + "".join(f"{cell('const_030', P_SWEEP, 100, f, 'pue'):9.4f}"
                              for f in FRACTIONS))
    print(f"  note: f < {f_min:.3f} violates the rack-density constraint "
          f"({rack_kw:.1f} kW rack, {cm.AIR_LIMIT_KW:.0f} kW air-side limit)")

    print()
    print(f"carbon (tCO2e), P = {P_SWEEP}, f = {F_DESIGN}; rows: I, cols: CI scenario")
    print(f"{'I':>6} " + "".join(f"{k:>13s}" for k in CI_KEYS))
    for i in INTERVALS:
        print(f"{i:6d} " + "".join(
            f"{cell(k, P_SWEEP, i, F_DESIGN, 'carbon_t'):13.3f}" for k in CI_KEYS))

    print()
    print(f"makespan (h) at P = {P_SWEEP}: depends only on P and I")
    print(f"{'I':>6} {'phi':>8} {'T (h)':>8} {'feasible':>12}")
    for i in INTERVALS:
        r = idx[("const_030", P_SWEEP, i, F_DESIGN)]
        print(f"{i:6d} {r['overhead_phi']:8.4f} {r['makespan_h']:8.3f} "
              f"{('yes' if r['feasible'] else 'NO (I < P)'):>12}")

    print()
    print("carbon penalty of the *fastest* schedule relative to the slowest "
          f"(P = {P_SWEEP}, f = {F_DESIGN})")
    print(f"{'CI scenario':26s} {'C(I=P) t':>9} {'C(I=1000) t':>12} {'penalty':>9} "
          f"{'kg/acc-h':>10}")
    for ci_key in CI_KEYS:
        c_fast = cell(ci_key, P_SWEEP, P_SWEEP, F_DESIGN, "carbon_t")
        c_slow = cell(ci_key, P_SWEEP, 1000, F_DESIGN, "carbon_t")
        rate = job.marginal_carbon_per_gpu_hour(gtl.CI_SCENARIOS[ci_key].base)
        print(f"{gtl.CI_SCENARIO_LABELS[ci_key]:26s} {c_fast:9.3f} {c_slow:12.3f} "
              f"{100*(c_fast/c_slow-1):8.1f}% {rate:10.4f}")

    # ================================================================ section 3
    # For each deadline, search the whole triangular (P, I) space and report the
    # carbon-minimal feasible schedule -- the definition of a green schedule.
    # Because Amdahl's law makes wide schedules both faster *and* more efficient,
    # a wide schedule is chosen whenever one is affordable at all; the interesting
    # regressions appear only when the accelerator budget is capped, which is
    # Section 5.
    print()
    print("=== Section 3: carbon-minimal schedule meeting each deadline "
          "(f = 0.80, diurnal 0.30 kg/kWh grid) ===")
    print(f"{'deadline':>9} {'P*':>5} {'I*':>7} {'phi':>7} {'T (h)':>7} "
          f"{'E(MWh)':>8} {'C diurnal':>10} {'C flat':>8} {'C RE':>8}")
    rows_dl = []
    for dl in DEADLINES_H:
        best = None
        for p in PARALLELISMS:
            for i in INTERVALS:
                if i < p:
                    continue                      # infeasible: I >= P required
                m = idx[("diel_030", p, i, F_DESIGN)]
                if m["makespan_h"] > dl:
                    continue
                if best is None or m["carbon_t"] < best["carbon_t"]:
                    best = m
        if best is None:
            print(f"{dl:9.1f}  no feasible (P, I) point in the scanned grid")
            continue
        p_star, i_star = best["parallelism"], best["interval"]
        rec = dict(deadline_h=dl, parallelism=p_star, interval=i_star,
                   makespan_h=best["makespan_h"],
                   overhead_phi=best["overhead_phi"], pue=best["pue"],
                   grid_energy_mwh=best["grid_energy_mwh"])
        for ci_key in CI_KEYS:
            rec[f"carbon_{ci_key}_t"] = cell(ci_key, p_star, i_star, F_DESIGN,
                                             "carbon_t")
        rows_dl.append(rec)
        print(f"{dl:9.1f} {p_star:5d} {i_star:7d} {best['overhead_phi']:7.4f} "
              f"{best['makespan_h']:7.2f} {best['grid_energy_mwh']:8.2f} "
              f"{rec['carbon_diel_030_t']:10.3f} {rec['carbon_const_030_t']:8.3f} "
              f"{rec['carbon_qhd_015_t']:8.3f}")
    if rows_dl:
        cm.write_csv("gpu_scan_deadline.csv", list(rows_dl[0].keys()),
                     [list(r.values()) for r in rows_dl])

    # ================================================================ section 4
    print()
    print("=== Section 4: energy-optimal vs carbon-optimal liquid fraction "
          f"(P = {P_SWEEP}, I = 100) ===")
    print(f"{'CI scenario':26s} {'f_E*':>6} {'f_C*':>6} {'agree':>7} "
          f"{'carbon spread':>14}")
    rows_find = []
    for ci_key in CI_KEYS:
        by_e = [(f, cell(ci_key, P_SWEEP, 100, f, "grid_energy_mwh"))
                for f in FRACTIONS]
        by_c = [(f, cell(ci_key, P_SWEEP, 100, f, "carbon_t")) for f in FRACTIONS]
        f_e = min(by_e, key=lambda x: x[1])[0]
        f_c = min(by_c, key=lambda x: x[1])[0]
        lo = min(x[1] for x in by_c)
        hi = max(x[1] for x in by_c)
        print(f"{gtl.CI_SCENARIO_LABELS[ci_key]:26s} {f_e:6.2f} {f_c:6.2f} "
              f"{('yes' if f_e == f_c else 'NO'):>7} {100*(hi/lo-1):13.1f}%")
        rows_find.append(dict(ci_key=ci_key, f_energy_optimal=f_e,
                              f_carbon_optimal=f_c, agree=f_e == f_c,
                              carbon_spread_pct=100 * (hi / lo - 1)))

    # ================================================================ section 5
    # The accelerator budget.  Sections 1-3 gave every schedule as many of the
    # cluster's 10 000 accelerators as it wanted, so wide always won.  Here the
    # budget is capped at a fraction of the cluster, which is the real decision:
    # sharing the machine between several jobs, or giving one job everything.
    print()
    print("=== Section 5: energy per delivered step vs accelerator budget "
          f"(f = 0.80, I = P fastest feasible, flat 0.30 kg/kWh grid) ===")
    print(f"{'P':>5} {'T (h)':>7} {'E(MWh)':>8} {'kWh/step':>10} "
          f"{'jobs in parallel':>17} {'kWh/(step x cluster)':>21}")
    rows_budget = []
    for p in PARALLELISMS:
        if p > job.n_gpu:
            continue
        i = fastest_grid_interval(p)
        m = idx[("const_030", p, i, F_DESIGN)]
        parallel_jobs = job.n_gpu // p
        e_per_step_cluster = m["cl_energy_kwh_per_step"] * parallel_jobs
        rows_budget.append(dict(parallelism=p, makespan_h=m["makespan_h"],
                                grid_energy_mwh=m["grid_energy_mwh"],
                                cl_energy_kwh_per_step=m["cl_energy_kwh_per_step"],
                                jobs_in_parallel=parallel_jobs,
                                cl_energy_kwh_per_step_all_jobs=e_per_step_cluster,
                                carbon_t=m["carbon_t"]))
        print(f"{p:5d} {m['makespan_h']:7.2f} {m['grid_energy_mwh']:8.2f} "
              f"{m['cl_energy_kwh_per_step']:10.4f} {parallel_jobs:17d} "
              f"{e_per_step_cluster:21.4f}")
    if rows_budget:
        cm.write_csv("gpu_scan_budget.csv", list(rows_budget[0].keys()),
                     [list(r.values()) for r in rows_budget])

    # ================================================================ summary
    summary = dict(
        model="GPU training load x high-altitude cooling x grid carbon intensity",
        site=site["label"], elevation_m=site["elevation"], rho_r=site["rho_r"],
        weather_source=site["source"],
        job=dict(n_steps=job.n_steps, t_step1_s=job.t_step1_s,
                 serial_fraction=job.s_frac, amdahl_ceiling=1.0 / job.s_frac,
                 t_bw_s=job.t_bw_s, t_lat_s=job.t_lat_s, t_exp=job.t_exp,
                 n_gpu_available=job.n_gpu,
                 peak_it_power_mw=job.peak_power_w() / 1e6,
                 rack_peak_kw=rack_kw, f_min_density=f_min,
                 useful_energy_mwh=job.baseline_energy_kwh() / 1000.0),
        marginal_carbon_kg_per_accelerator_kwh={
            k: job.marginal_carbon_per_gpu_hour(v.base)
            for k, v in gtl.CI_SCENARIOS.items()},
        parallel_frontier=dict(
            p=list(PARALLELISMS),
            interval=[r["interval"] for r in rows_par],
            overhead_phi=[round(r["overhead_phi"], 5) for r in rows_par],
            makespan_h=[round(r["makespan_h"], 4) for r in rows_par],
            pue=[round(r["pue"], 5) for r in rows_par],
            carbon_t=[round(r["carbon_t"], 4) for r in rows_par],
            speedup=[round(r["speedup"], 4) for r in rows_par],
            speedup_per_accelerator=[round(r["speedup_per_accelerator"], 5)
                                     for r in rows_par],
        ),
        liquid_fraction_objectives=rows_find,
    )
    out_json = os.path.join(cm.DATA_DIR, "gpu_scan_summary.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    # ================================================================ headline
    print()
    print("=== Headline numbers ===")
    fastest = min(rows_par, key=lambda r: r["makespan_h"])
    slowest = max(rows_par, key=lambda r: r["makespan_h"])
    print(f"fastest schedule   : P = {fastest['parallelism']:.0f}, "
          f"T = {fastest['makespan_h']:.2f} h, phi = {fastest['overhead_phi']:.2%}, "
          f"PUE = {fastest['pue']:.4f}, C = {fastest['carbon_t']:.2f} tCO2e")
    print(f"slowest schedule   : P = {slowest['parallelism']:.0f}, "
          f"T = {slowest['makespan_h']:.2f} h, phi = {slowest['overhead_phi']:.2%}, "
          f"PUE = {slowest['pue']:.4f}, C = {slowest['carbon_t']:.2f} tCO2e")
    print(f"carbon penalty of the narrowest schedule : "
          f"{100*(slowest['carbon_t']/fastest['carbon_t'] - 1):.0f}% more tCO2e "
          f"for the same job")
    print(f"PUE is identical for all of them     : {fastest['pue']:.4f} "
          f"-- so PUE does not rank these schedules, carbon does")
    print(f"peak IT power      : {job.peak_power_w()/1e6:.2f} MW, independent of P "
          f"-- only the duty cycle moves")
    print(f"duty cycle range   : {min(r['duty_cycle'] for r in rows_par):.3f} ... "
          f"{max(r['duty_cycle'] for r in rows_par):.3f}")
    if rows_budget:
        best_step = min(rows_budget, key=lambda r: r["cl_energy_kwh_per_step"])
        worst_step = max(rows_budget, key=lambda r: r["cl_energy_kwh_per_step"])
        print(f"energy per delivered step : {best_step['cl_energy_kwh_per_step']:.4f} "
              f"kWh/step at P = {best_step['parallelism']} vs "
              f"{worst_step['cl_energy_kwh_per_step']:.4f} kWh/step at "
              f"P = {worst_step['parallelism']} "
              f"({worst_step['cl_energy_kwh_per_step']/best_step['cl_energy_kwh_per_step']:.1f}x)")
    print()
    for path in (out_json,
                 os.path.join(cm.DATA_DIR, "gpu_scan_parallel.csv"),
                 os.path.join(cm.DATA_DIR, "gpu_scan_training.csv"),
                 os.path.join(cm.DATA_DIR, "gpu_scan_deadline.csv")):
        print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
