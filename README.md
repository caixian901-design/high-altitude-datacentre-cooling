# Cooling architecture and PUE modelling for high-altitude AI data centres

Simulation code, derived data and figures for the preprint:

> **X. Cai**, *Cooling Architecture Optimization and PUE Modelling for Hyperscale AI Data
> Centres in High-Altitude Low-Pressure Environments: A Case Study on the Qinghai–Tibetan
> Plateau*, preprint, 2026. doi:[10.5281/zenodo.22743562](https://doi.org/10.5281/zenodo.22743562)

[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.22743562-blue)](https://doi.org/10.5281/zenodo.22743562)
[![License: MIT](https://img.shields.io/badge/code%20license-MIT-green)](LICENSE)
[![License: CC BY 4.0](https://img.shields.io/badge/content%20license-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/)

---

## What this repository contains

| Path | Contents |
|---|---|
| `manuscript.pdf` | The preprint, 22 pages, 13 figures, 6 tables |
| `manuscript.md` | Markdown source of the preprint |
| `code/` | The three Python scripts that produce every number and figure |
| `data/annual_sim_results.csv` | Derived output of the full-year simulation |
| `figures/` | The 13 figures cited in the preprint, 300 dpi |

---

## The problem

Most of Qinghai Province lies between 2 000 m and 3 000 m above sea level, where
atmospheric pressure is only 70–80 kPa and air density is roughly 80 % of its sea-level
value. China's "East Data, West Computing" (东数西算) initiative is directing AI computing
capacity into exactly this region, because of its cold climate, low electricity price and
high renewable share.

For a fan-driven cooling loop at fixed fan speed the volumetric flow is approximately
density-independent, so the **mass** flow — and therefore the heat removable at a given air
temperature rise — scales with the air density ratio ρ_r. Fan power scales approximately as
ρ_r⁻². At 2 200 m (ρ_r ≈ 0.805) that means about **19.5 % less air-side cooling capacity and
54.3 % more fan power** than at sea level for the same heat rejection.

At the same time, ambient temperature falls with altitude, so free-cooling availability
*improves*. The two effects oppose each other. This repository reproduces the analysis that
quantifies the balance.

---

## Key results

| Quantity | Value |
|---|---|
| Air-side cooling capacity loss at 2 200 m | −19.5 % |
| Fan-power penalty at 2 200 m | +54.3 % |
| PUE penalty of an air-only design at 2 200 m | +0.068 |
| PUE penalty at 80 % liquid cooling | +0.014 |
| Design-point PUE (*f* = 0.8, 2 200 m) | **1.154** |
| Air-side free-cooling availability: Xining / Beijing / Shanghai | 91.7 / 65.3 / 54.7 % |
| Air-only annual PUE: Xining / Beijing / Shanghai | **1.230** / 1.200 / 1.209 |
| Liquid fraction at which the plateau becomes most efficient | *f* ≈ 0.96 |

**The counter-intuitive result.** The plateau site has the highest free-cooling availability
of the three yet the *worst* annual PUE under air cooling. The reduced mass flow per unit of
fan volumetric delivery outweighs the climate benefit, and the plateau only becomes the most
efficient of the three sites once liquid cooling covers about 96 % of the IT load.

A rack-density constraint further shows that a 45 kW rack requires *f* ≥ 0.56–0.67
irrespective of energy price, so in low-tariff plateau regions the optimum liquid fraction is
governed by rack power density rather than by energy cost.

---

## Reproducing the results

### Requirements

```bash
python >= 3.11
numpy
scipy
matplotlib
pandas
```

```bash
pip install numpy scipy matplotlib pandas
```

### Weather data

The annual simulation is driven by measured TMYx 2011–2025 hourly weather files in
EnergyPlus EPW format, for three sites:

| Site | Elevation | Source |
|---|---|---|
| Xining, Qinghai | 2 266 m | climate.onebuilding.org |
| Beijing | 35 m | climate.onebuilding.org |
| Shanghai | 3 m | climate.onebuilding.org |

Place the `.epw` files in a `weather/` directory before running
`code/annual_simulation.py`. The weather files are not redistributed here — they are
freely downloadable from the original source.

### Run

```bash
python code/annual_simulation.py    # full-year hourly simulation, three sites
python code/make_figures.py         # regenerates every figure in the preprint
python code/crossover.py            # liquid fraction at which the plateau wins
```

### Cross-check values

The preprint reports the intermediate values needed to verify every table. At 2 200 m the
model gives:

```
p                  = 77.54 kPa
rho_r              = 0.8052
capacity loss      = 19.48 %
fan-power penalty  = 54.23 %
heat-transfer loss = 15.9 %
```

---

## Method summary

1. **Atmosphere.** Pressure and temperature follow the International Standard Atmosphere,
   `p(h) = p0 (1 − 2.25577e-5 h)^5.25588`; density follows the ideal-gas relation
   `rho = p / (Rs T)` with `Rs = 287.05 J kg⁻¹ K⁻¹`.
2. **Air-side degradation.** At fixed volumetric flow, removable heat scales as ρ_r and fan
   power as ρ_r⁻².
3. **PUE.** Expressed explicitly in terms of the liquid-cooling fraction *f*, the
   altitude-dependent air-side COP, and fixed distribution and auxiliary losses:
   `PUE(f, h) = 1 + (1 − f)/COP_a(h) + f/COP_l + λ_d + λ_o`, with `COP_a(h) = COP_a0 · ρ_r^γ`.
4. **Annual simulation.** 8 760 hourly steps per site, with temperature-dependent Carnot COP
   and free-cooling thresholds of 20 °C (air-side) and 32 °C (dry cooler).

Everything is computed from these equations. **No data are digitised by hand and no figure is
drawn by hand.**

---

## Citing

If you use this code or these results, please cite the preprint — see
[`CITATION.cff`](CITATION.cff), or use the "Cite this repository" button in the GitHub
sidebar.

---

## Licence

- **Code** (`code/`): MIT — see [`LICENSE`](LICENSE)
- **Manuscript, figures and data**: CC BY 4.0

---

## Contact

**Xian Cai** — caixian901@gmail.com — ORCID [0009-0007-5083-7078](https://orcid.org/0009-0007-5083-7078)
School of Intelligent Science and Engineering, Qinghai Minzu University, Xining, Qinghai, China

Homepage: https://caixian901-design.github.io
