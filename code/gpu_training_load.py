"""GPU training-load model: compute phase vs communication phase.

This module adds an IT-load layer on top of the facility cooling / PUE model of
Paper A.  It answers a question the cooling model alone cannot answer:

    When a distributed training job is pushed to finish sooner -- by spreading it
    over more accelerators, which means shorter compute phases and proportionally
    more synchronisation -- what happens to PUE, to energy and to carbon?

Modelling idea
--------------
A data-parallel training job performs N optimizer steps.  Run at parallelism P,
the accelerators synchronise every I steps, so the job executes

    C = N / I          synchronisation events

and its wall clock (makespan) is

    T(P, I) = N t_c(P) + C t_m(P)

where t_c(P) is the wall time of one compute phase and t_m(P) the *exposed*
(not overlapped) time added by one collective.  Two independent mechanisms then
compete:

*   **Compute saturates (Amdahl).**  There is a serial part to every step --
    the optimizer update, the embedding and loss, the host-side launch pipeline.
    With a serial fraction s the aggregate training throughput is

        Theta(P) = 1 / (s + (1-s)/P)      [steps/s]
        t_c(P)  = 1 / Theta(P)

    so throughput asymptotes to 1/s: past a point, extra accelerators stop
    buying any speed-up at all.

*   **Collectives get cheaper in bandwidth but dearer in hops.**  A ring
    collective moves a payload that shrinks as 1/P, but the latency term grows
    with the number of ranks in the ring, and so does fabric contention:

        t_m(P) = t_bw / P + t_lat * P**t_exp

The competition between the two makes the *communication share* of wall clock
non-monotonic in P, which is the non-obvious part of the result:

    phi(P, I) = C t_m(P) / T_0(P)        communication share of wall clock
    T(P, I)   = T_0(P) (1 + phi)         T_0 = N t_c(P)
    rho       = 1 / (1 + phi)            compute duty cycle
    P_IT      = n_gpu [ rho P_compute + (1-rho) P_comm + P_other ]
    E         = P_IT * T                 job energy

phi is the fraction of wall-clock time the accelerators spend *not* computing,
which is exactly the quantity a cooling designer needs, and it is why the three
swept parameters of `gpu_training_scan.py` are (I, f, CI): the first sets phi, the
second sets how efficiently the site converts power into heat rejection, and the
third sets what a joule costs in carbon.

One physical constraint ties P and I together: a job spread over P accelerators
cannot synchronise less often than once per compute phase, so **I >= P** is a hard
floor and the schedule with I = P is the fastest one available at that
parallelism.  The scan therefore treats (P, I) as a triangular design space.

Consequences that matter for a cooling design
---------------------------------------------
1.  **Peak and mean decouple.**  Accelerators idle during a collective, so the
    *mean* heat load falls as communication grows -- but the *peak* load does not,
    because it is set by P_compute during the compute phase.  A plant sized on
    mean IT power is deceptively cheap; a plant is built on peak.

2.  **Faster costs joules, and the exchange rate is fixed by physics.**
    Overhead time is spent at P_comm, so

        E_gpu = P_c N t_c  +  P_comm C t_m
                 useful work    overhead

    and the marginal carbon cost of buying one accelerator-hour of makespan is
    P_comm x CI, independent of P, of I and of the cooling design.  A shorter
    makespan and a smaller carbon bill are therefore in direct conflict, and no
    amount of liquid cooling changes the exchange rate -- liquid cooling only
    shrinks the PUE multiplier applied to both terms.

3.  **The same PUE is not the same carbon.**  Stretching a job over more
    wall-clock hours is free in carbon only if grid carbon intensity is constant.
    The Qinghai plateau grid has a very large hydro + solar + wind share and hence
    a large daily intensity swing, so a long job cannot be confined to the
    low-carbon window and the *same* IT energy carries a *different* carbon
    footprint.  That is the mechanism by which PUE-optimal and carbon-optimal
    schedules come apart, and it is the reason the sweep has a CI axis at all.

Everything here is derived from the equations above.  No digitised data, no
hand-set results.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Hardware presets: exposed collective time t_m(P) = t_bw/P + t_lat, in seconds,
# for the three interconnect classes a national-scale AI cluster actually uses.
# The values correspond to an all-reduce of a large-model gradient across the
# given fabric: 0.4-1.1 s of bandwidth-limited transfer, plus 30-400 ms of
# latency floor.  Substitute your own measurement with
# JobSpec(t_bw_s=..., t_lat_s=...).
# ---------------------------------------------------------------------------
INTERCONNECT_PRESETS: dict[str, dict] = {
    "nvlink": dict(t_bw_s=0.40, t_lat_s=0.030, label="NVLink, intra-node",
                   colour="#2e8b57"),
    "pcie": dict(t_bw_s=0.70, t_lat_s=0.090, label="PCIe, inter-node",
                 colour="#e67e22"),
    "eth200g": dict(t_bw_s=1.10, t_lat_s=0.400, label="200 GbE, cross-rack",
                    colour="#c0392b"),
}


@dataclass(frozen=True)
class JobSpec:
    """One training job on one cluster, expressed so that every time is physical.

    Defaults describe the Paper A case study: a 10 000-accelerator cluster whose
    IT power is ~12 MW, running a 100 000-step job on a PCIe-class fabric.
    """

    n_steps: int = 100_000          # compute steps in the job (the work)
    t_step1_s: float = 1.0          # wall time of one step on one accelerator [s]
    s_frac: float = 0.04            # serial fraction of a step; throughput -> 1/s
    t_bw_s: float = 0.70            # bandwidth part of one collective at P = 1 [s]
    t_lat_s: float = 0.090          # latency part of one collective at P = 1   [s]
    t_exp: float = 0.5              # latency grows as P**t_exp (ring hops, contention)
    p_fit: float = 2.0              # parallelism needed just to hold the model
    n_gpu: int = 10_000             # accelerators in the cluster
    p_compute_w: float = 700.0      # accelerator power, compute phase           [W]
    p_comm_w: float = 320.0         # accelerator power, collective phase        [W]
    p_other_w: float = 340.0        # CPU + memory + NIC + storage per accel.    [W]

    # ----------------------------------------------------------------- scaling
    def throughput_steps_per_s(self, parallelism: float) -> float:
        """Gross cluster training throughput at parallelism P [steps/s].

        Amdahl-limited: 1/(s + (1-s)/P).  It asymptotes to 1/s as P grows, which
        is the physical statement that beyond some point extra accelerators buy no
        further speed-up on a job of fixed size.
        """
        if parallelism < 1:
            raise ValueError("parallelism must be >= 1")
        s = self.s_frac
        return 1.0 / (s + (1.0 - s) / parallelism)

    def t_c_s(self, parallelism: float = 1.0) -> float:
        """Wall time of one compute phase (step) at parallelism P."""
        return 1.0 / self.throughput_steps_per_s(parallelism)

    def t_m_s(self, parallelism: float = 1.0) -> float:
        """Exposed time added by one collective at parallelism P [s].

        Bandwidth-dominated at low P (payload shrinks as 1/P, and with it the
        whole ring all-reduce); hop- and contention-dominated at high P (the ring
        is longer and the fabric is busier).
        """
        return self.t_bw_s / parallelism + self.t_lat_s * parallelism ** self.t_exp

    def g(self, parallelism: float = 1.0) -> float:
        """Serialisation ratio g(P) = t_m/t_c: one collective in compute phases."""
        return self.t_m_s(parallelism) / self.t_c_s(parallelism)

    # -------------------------------------------------------------------- time
    def n_collectives(self, interval: int) -> int:
        """C(I) = ceil(N / I): synchronisation events over the whole job."""
        if interval < 1:
            raise ValueError("communication interval must be >= 1 step")
        return -(-self.n_steps // interval)      # ceil division

    def baseline_s(self, parallelism: float = 1.0) -> float:
        """T_0 = N t_c(P): makespan if collectives were free."""
        return self.n_steps * self.t_c_s(parallelism)

    def overhead_fraction(self, parallelism: float = 1.0, interval: int = 1) -> float:
        """phi = C t_m / T_0: share of wall-clock time lost to communication."""
        t0 = self.baseline_s(parallelism)
        return self.n_collectives(interval) * self.t_m_s(parallelism) / t0

    def makespan_s(self, parallelism: float = 1.0, interval: int = 1) -> float:
        """T(P, I) = N t_c(P) + C(I) t_m(P), in seconds."""
        t0 = self.baseline_s(parallelism)
        return t0 * (1.0 + self.overhead_fraction(parallelism, interval))

    def duty_cycle(self, parallelism: float = 1.0, interval: int = 1) -> float:
        """rho = T_0/T: fraction of wall-clock time the accelerators compute."""
        return 1.0 / (1.0 + self.overhead_fraction(parallelism, interval))

    def speedup(self, parallelism: float = 1.0, interval: int = 1) -> float:
        """S(P, I) = T(1, inf)/T(P, I): speed-up against ideal serial execution."""
        return self.n_steps * self.t_step1_s / self.makespan_s(parallelism, interval)

    def interval_for_parallelism(self, parallelism: float = 1.0) -> int:
        """I(P) = ceil(P): one collective per compute phase, the native granularity.

        A job spread over P workers cannot synchronise less often than once per
        compute phase, so I >= P is the physical floor and ``I = P`` is the finest
        granularity available.
        """
        return max(1, int(math.ceil(parallelism)))

    def interval_for_deadline(self, deadline_h: float, parallelism: float = 1.0) -> int:
        """Largest synchronisation interval that still meets a wall-clock deadline.

        Searched over the *feasible* schedule space I in [P, N], because a job on
        P accelerators cannot synchronise less often than once per compute phase.
        The function C(I) = ceil(N/I) is a step function, so the search is done by
        bisection on the monotone feasibility predicate rather than by solving the
        continuous relaxation.  Raises ValueError when the deadline is infeasible.
        """
        t_max = deadline_h * 3600.0
        i_lo = self.interval_for_parallelism(parallelism)     # fastest schedule
        t_min = self.makespan_s(parallelism, i_lo)
        if t_max < t_min:
            raise ValueError(
                f"deadline {deadline_h:.2f} h is below the fastest possible "
                f"makespan {t_min/3600:.2f} h at P = {parallelism:g} (I = {i_lo})")
        if t_max >= self.makespan_s(parallelism, self.n_steps):
            return self.n_steps                              # I = N is feasible
        lo, hi = i_lo, self.n_steps
        while hi - lo > 1:                                   # largest feasible I
            mid = (lo + hi) // 2
            if self.makespan_s(parallelism, mid) <= t_max:
                lo = mid
            else:
                hi = mid
        return lo

    # ------------------------------------------------------------------- power
    def it_power_w(self, rho: float) -> float:
        """Mean IT power (accelerators + servers) at a compute duty cycle rho."""
        per_gpu = rho * self.p_compute_w + (1.0 - rho) * self.p_comm_w + self.p_other_w
        return self.n_gpu * per_gpu

    def peak_power_w(self) -> float:
        """Peak IT power: every accelerator simultaneously in the compute phase."""
        return self.n_gpu * (self.p_compute_w + self.p_other_w)

    def it_energy_kwh(self, parallelism: float = 1.0, interval: int = 1) -> float:
        """Total IT energy of the job, in kWh."""
        rho = self.duty_cycle(parallelism, interval)
        return self.it_power_w(rho) * self.makespan_s(parallelism, interval) / 3.6e6

    def baseline_energy_kwh(self) -> float:
        """Useful (communication-free) IT energy of the job, in kWh."""
        return (self.n_gpu * (self.p_compute_w + self.p_other_w)
                * self.n_steps * self.t_step1_s / 3.6e6)

    def marginal_carbon_per_gpu_hour(self, ci_kg_per_kwh: float) -> float:
        """kgCO2e paid per accelerator-hour of makespan bought.

        One accelerator-hour of communication overhead draws P_comm, so the
        exchange rate is P_comm x CI -- independent of P, I and of the cooling
        design.  This is the quantitative form of "PUE-optimal need not be
        carbon-optimal": the cooling plant cannot move this exchange rate, it only
        scales both terms by the PUE.
        """
        return self.p_comm_w * ci_kg_per_kwh / 1000.0        # W -> kW

    def replace(self, **kw) -> "JobSpec":
        return JobSpec(**{**self.__dict__, **kw})


def default_job() -> JobSpec:
    """10 000 accelerators running a 100 000-step job on a PCIe-class fabric."""
    return JobSpec()


def job_for_interconnect(name: str, **kw) -> JobSpec:
    """A JobSpec whose collective cost follows a named interconnect preset."""
    if name not in INTERCONNECT_PRESETS:
        raise KeyError(f"unknown interconnect {name!r}; "
                       f"choose from {sorted(INTERCONNECT_PRESETS)}")
    pre = {k: v for k, v in INTERCONNECT_PRESETS[name].items()
           if k in ("t_bw_s", "t_lat_s")}
    return default_job().replace(**pre, **kw)


def interconnect_presets() -> dict[str, dict]:
    return INTERCONNECT_PRESETS


# ---------------------------------------------------------------------------
# Grid carbon intensity
# ---------------------------------------------------------------------------
@dataclass
class CarbonIntensity:
    """Hourly grid carbon intensity in kgCO2e/kWh.

    mode
      'constant'  : no temporal structure -- a fully firm, dispatchable grid
      'diurnal'   : daily cycle only -- the signature of a high-solar grid
      'seasonal'  : annual cycle only
      'both'      : daily + annual
    """

    base: float = 0.30              # annual mean intensity         [kgCO2e/kWh]
    diurnal_amp: float = 0.0        # half of the daily peak-to-trough
    seasonal_amp: float = 0.0       # half of the annual peak-to-trough
    mode: str = "constant"
    peak_hour: float = 20.0         # local hour of *maximum* intensity

    def at_hour(self, hour: float) -> float:
        """Intensity at an absolute hour offset from the job start."""
        v = float(self.base)
        if self.mode in ("diurnal", "both"):
            # daily minimum at midday (solar peak), maximum at peak_hour
            v += self.diurnal_amp * math.cos(2.0 * math.pi * (hour - self.peak_hour) / 24.0)
        if self.mode in ("seasonal", "both"):
            # annual minimum in spring (hydro + wind), maximum in winter
            v += self.seasonal_amp * math.cos(2.0 * math.pi * (hour - 30.0 * 24.0) / 8760.0)
        return max(v, 0.0)

    def profile(self, n_hours: int) -> list[float]:
        return [self.at_hour(h) for h in range(n_hours)]

    @property
    def label(self) -> str:
        amp = f", +/-{self.diurnal_amp:.2f} daily" if self.diurnal_amp else ""
        return f"{self.base:.2f} kg/kWh {self.mode}{amp}"


# Grid flavours used in the scan.  ``qhd_015`` reflects Qinghai's very large
# hydro + solar + wind share, which both lowers the annual mean and steepens the
# daily profile; ``coal_060`` is the counterfactual that shows when the
# conclusions invert.
CI_SCENARIOS: dict[str, CarbonIntensity] = {
    "const_030": CarbonIntensity(0.30, 0.00, 0.00, "constant"),
    "diel_030": CarbonIntensity(0.30, 0.10, 0.00, "diurnal"),
    "qhd_015": CarbonIntensity(0.15, 0.07, 0.02, "both"),
    "coal_060": CarbonIntensity(0.60, 0.14, 0.04, "both"),
}

CI_SCENARIO_LABELS: dict[str, str] = {
    "const_030": "0.30 kg/kWh, flat grid",
    "diel_030": "0.30 kg/kWh, diurnal swing",
    "qhd_015": "0.15 kg/kWh, Qinghai high-RE",
    "coal_060": "0.60 kg/kWh, coal-heavy",
}


# ---------------------------------------------------------------------------
# Coupling to the facility model
# ---------------------------------------------------------------------------
def facility_power_w(job: JobSpec, rho: float, pue: float) -> float:
    """Total grid power drawn by the site at compute duty cycle rho and PUE."""
    return job.it_power_w(rho) * pue


def carbon_kg(facility_power_w: float, duration_s: float, ci_kg_per_kwh: float) -> float:
    """Carbon released by a constant load over a duration at a constant CI."""
    return facility_power_w * duration_s / 3.6e6 * ci_kg_per_kwh


def min_liquid_fraction(rack_kw: float, air_limit_kw: float = 20.0) -> float:
    """Liquid-cooling fraction forced by rack density (Paper A, Section 3.5).

    The air-side loop can carry at most ``air_limit_kw`` per rack, so
    f >= 1 - air_limit / rack_kw.  A 45 kW rack therefore needs f >= 0.56
    irrespective of energy price -- the design-space constraint of Paper A.
    """
    if rack_kw <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - air_limit_kw / rack_kw))


def rack_power_kw(job: JobSpec, servers_per_rack: int = 5,
                  gpus_per_server: int = 8) -> float:
    """Peak rack power in kW: a rack holds complete servers in the compute phase.

    Peak, not mean, is the design driver.  The collective phase is a lull, so a
    plant sized on the annual mean heat load will be undersized -- which is the
    point of separating rho from the peak in this model.
    """
    per_gpu_kw = (job.p_compute_w + job.p_other_w) / 1000.0
    return per_gpu_kw * gpus_per_server * servers_per_rack


if __name__ == "__main__":      # ad-hoc sanity check
    job = default_job()
    print(f"peak IT power (all accelerators computing) : {job.peak_power_w()/1e6:7.2f} MW")
    print(f"useful IT energy of the job (P = 1)        : {job.baseline_energy_kwh()/1e3:7.1f} MWh")
    print(f"rack peak power (5 x 8 accelerators)       : "
          f"{rack_power_kw(job):7.1f} kW -> f_min = {min_liquid_fraction(rack_power_kw(job)):.3f}")
    print(f"marginal carbon of speed, flat grid 0.30   : "
          f"{job.marginal_carbon_per_gpu_hour(0.30):7.3f} kgCO2e per accelerator-kWh")
    print()
    print(f"{'P':>6} {'t_c (s)':>8} {'t_m (s)':>8} {'I':>6} {'phi':>7} {'rho':>6} "
          f"{'S':>7} {'S/P':>7} {'T (h)':>7} {'E (MWh)':>9}")
    for p in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024):
        i = job.interval_for_parallelism(p)
        print(f"{p:6d} {job.t_c_s(p):8.4f} {job.t_m_s(p):8.4f} {i:6d} "
              f"{job.overhead_fraction(p, i):7.4f} {job.duty_cycle(p, i):6.3f} "
              f"{job.speedup(p, i):7.2f} {job.speedup(p, i)/p:7.3f} "
              f"{job.makespan_s(p, i)/3600:7.2f} {job.it_energy_kwh(p, i)/1e3:9.1f}")
    print()
    for p in (16, 64, 256):
        i0 = job.interval_for_parallelism(p)
        print(f"P = {p:4d}: fastest (I = {i0:3d}) {job.makespan_s(p, i0)/3600:6.2f} h, "
              f"communication-free (I = N) {job.makespan_s(p, job.n_steps)/3600:6.2f} h")
    print()
    for dl in (3.0, 4.0, 5.0, 6.0, 10.0):
        try:
            i = job.interval_for_deadline(dl, parallelism=64)
        except ValueError as exc:
            print(f"P = 64, deadline {dl:6.1f} h -> infeasible ({exc})")
            continue
        print(f"P = 64, deadline {dl:6.1f} h -> I* = {i:6d} steps, "
              f"T = {job.makespan_s(64, i)/3600:6.2f} h, "
              f"phi = {job.overhead_fraction(64, i):7.2%}, "
              f"E = {job.it_energy_kwh(64, i)/1e3:6.1f} MWh")
