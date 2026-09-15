"""Crossover analysis: at what liquid fraction does the plateau site become best?

Uses the shared facility model in ``cooling_model.py`` and the measured TMYx
weather series, and prints the crossover between Xining (2 266 m) and Beijing plus
the site comparison at the design liquid fraction.

Set HDC_WEATHER to point at the weather directory if the .epw files are not in
<repository>/weather/<site>/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import cooling_model as cm

LAM_D, LAM_O, F_DESIGN = cm.LAM_D, cm.LAM_O, cm.F_DESIGN
WX = cm.WEATHER_DIR

sites = {}
for key in ("xining", "beijing", "shanghai"):
    d = cm.load_site(key)
    t = np.asarray(d["t"])
    sites[d["label"]] = dict(
        elev=d["elevation"], rr=d["rho_r"],
        ca=np.array([cm.cop_air(x, d["rho_r"]) for x in t]),
        cl=np.array([cm.cop_liq(x, d["rho_r"]) for x in t]),
        t=t, source=d["source"])

SHORT = {"Xining (Qinghai plateau)": "Xining",
         "Beijing": "Beijing",
         "Shanghai": "Shanghai"}


def mean_pue(s: dict, f: float) -> float:
    return float((1.0 + (1.0 - f) / s["ca"] + f / s["cl"] + LAM_D + LAM_O).mean())


print("weather: " + ", ".join(f"{SHORT[k]} [{v['source']}]" for k, v in sites.items()))
print()
print("f      Xining   Beijing  Shanghai   best      delta(Xn-Bj)")
grid = np.arange(0.60, 1.001, 0.025)
prev = None
cross = None
for f in grid:
    v = {SHORT[k]: mean_pue(s, f) for k, s in sites.items()}
    best = min(v, key=v.get)
    d = v["Xining"] - v["Beijing"]
    print(f"{f:.3f}  {v['Xining']:.4f}  {v['Beijing']:.4f}  {v['Shanghai']:.4f}   "
          f"{best:8s}  {d:+.4f}")
    if prev is not None and prev[1] > 0 >= d:
        cross = (prev[0], f)
    prev = (f, d)

print("\ncrossover (Xining becomes better than Beijing) between f = "
      + (f"{cross[0]:.3f} and {cross[1]:.3f}" if cross else "not found in range"))

f = F_DESIGN
vals = {SHORT[k]: mean_pue(s, f) for k, s in sites.items()}
print(f"\nAt the design fraction f = {f}: "
      + ", ".join(f"{k} {v:.4f}" for k, v in vals.items()))
for k, s in sites.items():
    print(f"  {SHORT[k]:9s} elev={s['elev']:6.0f} m  rho_r={s['rr']:.3f}  "
          f"mean COP_air={s['ca'].mean():5.2f}  mean COP_liq={s['cl'].mean():5.2f}")
print(f"\nweather directory used: {WX}")
print(f"air-side capacity loss at 2 200 m : {(1 - cm.rho_r_at(2200.0)) * 100:.2f}%")
print(f"fan-power penalty at 2 200 m      : {(1 / cm.rho_r_at(2200.0) ** 2 - 1) * 100:.2f}%")
