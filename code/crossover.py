"""Crossover analysis: at what liquid fraction does the plateau site become best?"""
import csv, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

WX = r"C:\Users\29102\dsh_fig\weather"
P0, T0K, RS = 101.325, 288.15, 287.05
COP_AIR_FC, COP_LIQ_FC, ETA_C = 10.0, 20.0, 0.35
T_AIR_FC, T_LIQ_FC = 20.0, 32.0
T_EVAP_AIR, T_EVAP_LIQ = 287.15, 288.15
LAM_D, LAM_O, GAMMA = 0.055, 0.02, 2.0


def rho_r_at(e):
    p = P0 * (1 - 2.25577e-5 * e) ** 5.25588
    return ((p * 1000) / (RS * (T0K - 0.0065 * e))) / ((P0 * 1000) / (RS * T0K))


def read_epw(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        rows = list(csv.reader(fh))
    e = float(rows[0][9])
    t = np.array([float(r[6]) for r in rows[8:] if len(r) > 6 and r[6]][:8760])
    return e, rho_r_at(e), t


def cop_air(T, rr):
    if T <= T_AIR_FC:
        return COP_AIR_FC * rr ** GAMMA
    tc = T + 5.0 + 273.15
    return max(1.5, ETA_C * T_EVAP_AIR / max(tc - T_EVAP_AIR, 3.0))


def cop_liq(T, rr):
    if T <= T_LIQ_FC:
        return COP_LIQ_FC * rr ** 0.3
    tc = T + 5.0 + 273.15
    return max(2.0, ETA_C * T_EVAP_LIQ / max(tc - T_EVAP_LIQ, 3.0))


sites = {}
for key, label in [("xining", "Xining"), ("beijing", "Beijing"), ("shanghai", "Shanghai")]:
    f = glob.glob(os.path.join(WX, key, "*.epw"))[0]
    e, rr, t = read_epw(f)
    ca = np.array([cop_air(x, rr) for x in t]); cl = np.array([cop_liq(x, rr) for x in t])
    sites[label] = dict(elev=e, rr=rr, ca=ca, cl=cl, t=t)

print("f      Xining   Beijing  Shanghai   best      delta(Xn-Bj)")
grid = np.arange(0.60, 1.001, 0.025)
prev = None
cross = None
for f in grid:
    v = {k: float((1 + (1 - f) / s["ca"] + f / s["cl"] + LAM_D + LAM_O).mean()) for k, s in sites.items()}
    best = min(v, key=v.get)
    d = v["Xining"] - v["Beijing"]
    print(f"{f:.3f}  {v['Xining']:.4f}  {v['Beijing']:.4f}  {v['Shanghai']:.4f}   {best:8s}  {d:+.4f}")
    if prev is not None and prev[1] > 0 >= d:
        cross = (prev[0], f)
    prev = (f, d)

print("\ncrossover (Xining becomes better than Beijing) between f =",
      f"{cross[0]:.3f} and {cross[1]:.3f}" if cross else "not found in range")

# engineering conclusion at the design fraction
f = 0.8
vals = {k: float((1 + (1 - f) / s["ca"] + f / s["cl"] + LAM_D + LAM_O).mean()) for k, s in sites.items()}
print(f"\nAt the design fraction f = 0.8: " + ", ".join(f"{k} {v:.4f}" for k, v in vals.items()))
for k, s in sites.items():
    print(f"  {k:9s} elev={s['elev']:6.0f} m  rho_r={s['rr']:.3f}  "
          f"mean COP_air={s['ca'].mean():5.2f}  mean COP_liq={s['cl'].mean():5.2f}")
