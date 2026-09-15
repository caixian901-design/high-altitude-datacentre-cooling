"""Facility cooling / PUE model of Paper A, shared by every script in this repo.

This module is the single source of truth for the atmosphere, the air-side and
liquid-side COP models, the PUE expression and the rack-density constraint.  It
was factored out of ``annual_simulation.py`` so that the GPU training-load layer
(``gpu_training_load.py`` / ``gpu_training_scan.py``) couples to *exactly* the
same physics that produced the published annual tables -- a second copy of the
coefficients would be a silent source of inconsistency.

Model (per hour h):

    COP_air(T) = COP_AIR_FC * rho_r**gamma            T <= T_AIR_FC  (free cooling)
               = max(1.5, ETA_C * T_evap_a/(T_c - T_evap_a))   otherwise (chiller)
    COP_liq(T) = COP_LIQ_FC * rho_r**0.3              T <= T_LIQ_FC  (dry cooler)
               = max(2.0, ETA_C * T_evap_l/(T_c - T_evap_l))   otherwise
    PUE(f, T)  = 1 + (1-f)/COP_air(T) + f/COP_liq(T) + lambda_d + lambda_o

Weather, when present, is the measured TMYx 2011-2025 EPW series for Xining,
Beijing and Shanghai; otherwise a sinusoidal climate model with the Paper A
parameters is used so that every script still runs end to end.
"""
from __future__ import annotations

import csv
import glob
import math
import os

# ---------------------------------------------------------------------------
# Portable paths.  Everything is relative to the repository root by default, so
# the code runs unchanged on a fresh clone or on a CI runner; override with the
# environment variables below when the data live elsewhere.
# ---------------------------------------------------------------------------
REPO_ROOT = os.environ.get(
    "HDC_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEATHER_DIR = os.environ.get("HDC_WEATHER", os.path.join(REPO_ROOT, "weather"))
DATA_DIR = os.environ.get("HDC_DATA", os.path.join(REPO_ROOT, "data"))
FIGURE_DIR = os.environ.get("HDC_FIGURES", os.path.join(REPO_ROOT, "figures"))

for _d in (DATA_DIR, FIGURE_DIR):
    os.makedirs(_d, exist_ok=True)

# ---------------------------------------------------------------------------
# Model coefficients (Table 1 of the manuscript)
# ---------------------------------------------------------------------------
P0_KPA, T0_K, RS = 101.325, 288.15, 287.05     # ISA sea-level pressure/temperature, R_s
LAPSE, ISA_EXP = 0.0065, 5.25588               # ISA lapse rate, barometric exponent

COP_AIR_FC, COP_LIQ_FC = 10.0, 20.0            # free-cooling reference COPs
ETA_C = 0.35                                   # Carnot fraction of the chillers
T_AIR_FC, T_LIQ_FC = 20.0, 32.0                # free-cooling thresholds        [degC]
T_EVAP_AIR, T_EVAP_LIQ = 287.15, 288.15        # evaporating temperatures       [K]
T_COND_APPROACH = 5.0                          # condenser approach            [K]
LAM_D, LAM_O = 0.055, 0.02                     # distribution / auxiliary losses
GAMMA = 2.0                                    # air-side fan-penalty exponent
F_DESIGN = 0.8                                 # reference liquid fraction
AIR_LIMIT_KW = 20.0                            # max heat removable per rack, air only

# Short names and measured elevations of the three TMYx sites
SITES: dict[str, dict] = {
    "xining":   dict(label="Xining (Qinghai plateau)", key="xining",   colour="#c0392b"),
    "beijing":  dict(label="Beijing",                  key="beijing",  colour="#2980b9"),
    "shanghai": dict(label="Shanghai",                 key="shanghai", colour="#16a085"),
}

# Sinusoidal fallback climate (Paper A Section 3.4): annual mean, amplitude
SINUSOID = {
    "xining":   dict(t_mean=7.5,  amp=12.5, elev_m=2266.0),
    "beijing":  dict(t_mean=12.9, amp=14.6, elev_m=35.0),
    "shanghai": dict(t_mean=17.1, amp=11.8, elev_m=3.0),
}

HOURS_PER_YEAR = 8760


# ---------------------------------------------------------------------------
# Atmosphere
# ---------------------------------------------------------------------------
def pressure_kpa(elev_m: float) -> float:
    """ISA atmospheric pressure at elevation [kPa]."""
    return P0_KPA * (1.0 - 2.25577e-5 * elev_m) ** ISA_EXP


def temp_k(elev_m: float) -> float:
    """ISA atmospheric temperature at elevation [K]."""
    return T0_K - LAPSE * elev_m


def rho_at(elev_m: float) -> float:
    """Air density from the ideal-gas relation [kg/m3]."""
    return (pressure_kpa(elev_m) * 1000.0) / (RS * temp_k(elev_m))


RHO0 = rho_at(0.0)


def rho_r_at(elev_m: float) -> float:
    """Air density ratio relative to sea level (the model's key altitude parameter)."""
    return rho_at(elev_m) / RHO0


# ---------------------------------------------------------------------------
# COP models
# ---------------------------------------------------------------------------
def cop_air(t_c: float, rr: float) -> float:
    """Air-side COP at ambient temperature t_c [degC] and density ratio rr."""
    if t_c <= T_AIR_FC:
        return COP_AIR_FC * rr ** GAMMA
    t_cond = t_c + T_COND_APPROACH + 273.15
    return max(1.5, ETA_C * T_EVAP_AIR / max(t_cond - T_EVAP_AIR, 3.0))


def cop_liq(t_c: float, rr: float) -> float:
    """Liquid-side (dry cooler / warm-water) COP at t_c [degC] and density ratio rr."""
    if t_c <= T_LIQ_FC:
        return COP_LIQ_FC * rr ** 0.3
    t_cond = t_c + T_COND_APPROACH + 273.15
    return max(2.0, ETA_C * T_EVAP_LIQ / max(t_cond - T_EVAP_LIQ, 3.0))


def pue_instant(t_c: float, rr: float, f: float,
                cop_a: float | None = None, cop_l: float | None = None) -> float:
    """Instantaneous PUE at ambient t_c, density ratio rr and liquid fraction f."""
    ca = cop_air(t_c, rr) if cop_a is None else cop_a
    cl = cop_liq(t_c, rr) if cop_l is None else cop_l
    return 1.0 + (1.0 - f) / ca + f / cl + LAM_D + LAM_O


def pue_annual(temps, rr: float, f: float) -> float:
    """Annual mean PUE over an hourly dry-bulb temperature series [degC]."""
    s = 0.0
    for t in temps:
        s += pue_instant(float(t), rr, f)
    return s / len(temps)


def pue_profile(temps, rr: float, f: float) -> list[float]:
    """Hourly PUE over an hourly temperature series."""
    return [pue_instant(float(t), rr, f) for t in temps]


def altitude_penalty(f: float, elev_m: float) -> float:
    """PUE penalty of a site relative to sea level at the same liquid fraction."""
    return pue_instant(15.0, rho_r_at(elev_m), f) - pue_instant(15.0, 1.0, f)


def min_liquid_fraction(rack_kw: float, air_limit_kw: float = AIR_LIMIT_KW) -> float:
    """Liquid fraction forced by rack density: f >= 1 - air_limit/rack_kw."""
    if rack_kw <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - air_limit_kw / rack_kw))


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def find_epw(site_key: str, weather_dir: str | None = None) -> str | None:
    """Locate the TMYx EPW file for a site, or None when it is not downloaded."""
    wd = weather_dir or WEATHER_DIR
    hits = glob.glob(os.path.join(wd, site_key, "*.epw"))
    return hits[0] if hits else None


def read_epw(path: str) -> dict:
    """Read the dry-bulb temperature series and header of an EnergyPlus EPW file."""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        rows = list(csv.reader(fh))
    loc = rows[0]
    temps = []
    for r in rows[8:]:
        if len(r) < 10 or not r[6]:
            continue
        try:
            temps.append(float(r[6]))
        except ValueError:
            continue
    return dict(city=loc[1], elevation=float(loc[9]),
                lat=float(loc[6]), lon=float(loc[7]),
                t=temps[:HOURS_PER_YEAR])


def synthetic_temps(site_key: str, n: int = HOURS_PER_YEAR) -> list[float]:
    """Sinusoidal climate fallback in the spirit of Paper A Section 3.4.

    Used only when the measured EPW file is absent, so that every script in the
    repository still produces a complete set of figures on a fresh clone.
    """
    p = SINUSOID[site_key]
    return [p["t_mean"] + p["amp"] * math.sin(2 * math.pi * (h - 2190) / HOURS_PER_YEAR)
            for h in range(n)]


def load_site(site_key: str, weather_dir: str | None = None) -> dict:
    """Return a site record with elevation, density ratio, hourly temperatures.

    ``source`` tells the caller whether measured weather was found.  Never raise
    when the weather is missing: fall back to the sinusoidal model and say so.
    """
    epw = find_epw(site_key, weather_dir)
    if epw:
        d = read_epw(epw)
        return dict(site=site_key, label=SITES[site_key]["label"],
                    elevation=d["elevation"], t=d["t"],
                    rho_r=rho_r_at(d["elevation"]), source="TMYx EPW",
                    city=d["city"])
    p = SINUSOID[site_key]
    return dict(site=site_key, label=SITES[site_key]["label"],
                elevation=p["elev_m"], t=synthetic_temps(site_key),
                rho_r=rho_r_at(p["elev_m"]), source="sinusoidal fallback",
                city=SITES[site_key]["label"])


def load_all_sites(weather_dir: str | None = None) -> dict[str, dict]:
    return {k: load_site(k, weather_dir) for k in SITES}


# ---------------------------------------------------------------------------
# Plot style shared by every figure script
# ---------------------------------------------------------------------------
def apply_style(font_size: float = 9.0, label_size: float = 9.5) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": font_size,
        "axes.labelsize": label_size,
        "axes.titlesize": label_size + 0.5,
        "legend.fontsize": font_size - 1.0,
        "xtick.labelsize": font_size - 0.5,
        "ytick.labelsize": font_size - 0.5,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": ":",
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
    })


def save(fig, name: str, figure_dir: str | None = None) -> str:
    """Save a figure as a 300-dpi PNG and return its path."""
    import matplotlib.pyplot as plt
    out = os.path.join(figure_dir or FIGURE_DIR, name)
    fig.savefig(out)
    plt.close(fig)
    return out


def write_csv(name: str, header: list[str], rows, data_dir: str | None = None) -> str:
    """Write a machine-readable table and return its path."""
    out = os.path.join(data_dir or DATA_DIR, name)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(header)
        wr.writerows(rows)
    return out


if __name__ == "__main__":
    for key in SITES:
        s = load_site(key)
        print(f"{s['label']:26s} elev={s['elevation']:7.1f} m  rho_r={s['rho_r']:.4f}  "
              f"Tmean={sum(s['t'])/len(s['t']):5.2f} C  n={len(s['t'])}  [{s['source']}]")
    print()
    print("PUE vs liquid fraction at 2 200 m (f from 0 to 1):")
    print("  f      PUE")
    for f in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        print(f"  {f:.1f}  {pue_instant(7.5, rho_r_at(2200.0), f):.4f}")
