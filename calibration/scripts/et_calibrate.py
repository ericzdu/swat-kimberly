#!/usr/bin/env python3
"""Fit per-crop ET to the OpenET (eeMetric) reference on full-year monthly totals.

Target: ``data/et_reference.csv`` (built by ``scripts/et_reference.py``) — 7 crops x 3
crop-years (2020, 2021, 2022), each year at a *different* field.

**Objective (2026-09-24): January-December monthly totals, 36 points per crop.**

    obj = mean_year |PBIAS of the calendar-year total|
          + R2_WEIGHT x (1 - R2 of the 36 monthly points)
          + an irrigation-plausibility penalty
          + regularisation toward the workbook parameters

The collaborator asked for the comparison report on monthly totals covering the full year, 36
points per crop over three years, against targets R2 > 0.8 and |PBIAS| < 10 %. Those are now
what is *fitted*, not only what is reported — fitting a season window and reporting a calendar
year would let the two diverge silently. ``--window season`` restores the emerge->harvest
scoring the 2026-08-13/09-11/09-15 fits used, for comparison with the archives.

Mean of per-year absolute biases, not the bias of the pooled total: the three years are three
independent fields, so +8 % and -8 % is a worse fit than two +1 % years, and pooling scores them
the same.

Why a full year became scoreable at all
---------------------------------------
Until 2026-09-24 the model irrigated on the shipped ``irr_str9_unlim`` table — plant water
stress < 0.9 — which fires only once a crop is *growing*. So the sheet's pre-emergence
``irrigation start`` dates did nothing, bare soil was never wetted, and outside each crop's
window SWAT reported ET near precipitation while eeMetric reported a real field. Scoring the
calendar year would have scored that management gap, which is why the earlier fits scored the
season window instead.

Irrigation now follows the sheet's own start/end dates with a soil-water trigger
(``monoculture.build_irrigation_dtl``), including the alfalfa footnote's four cutting
blackouts, so the off-season and shoulder months are a fair comparison and the full year is the
honest thing to score.

The knobs
---------
**Per crop** (``plants.plt``), all regularised toward the workbook:

``lai_pot``
    BLAI, potential maximum LAI. Moves the peak; flat once the canopy closes.
``frac_hu1`` / ``frac_hu2`` / ``hu_lai_decl`` / ``dlai_rate``
    The canopy-development curve: when leaf area starts, when it reaches 95 % of maximum, when
    it begins to decline and how fast. Authorised on 2026-09-24 after measuring the gain on
    this objective (corn R2 0.76 -> 0.83, barley 0.76 -> 0.84, sugarbeet 0.79 -> 0.84, potato
    0.42 -> 0.72) — the deficit was concentrated in the month after emergence and the month
    before harvest, which is exactly what this curve controls. It is a departure from the
    2026-09-11 "workbook verbatim" rule; ``runs/et_raw/workbook_check.csv`` flags every column.

**Basin-wide** — one value for all seven crops, not per crop, because a per-crop value would
carry exactly the objection the collaborator raised against a per-crop ``pet_co``:

``esco`` (``hydrology.hyd``)
    Soil-evaporation compensation. It moves the *level* and not the month shape, and how much
    it moves depends entirely on whether the soil is wet: under the old stress-triggered
    irrigation the full 0.01-0.95 range was worth under 2 |PBIAS| points, but with the
    sheet's irrigation windows holding the soil near field capacity it is worth about 9.
    Equal-budget control at 0.01 against the fitted 0.48
    (``et_calibration_esco0.01_control.json``): mean |PBIAS| 17.5 % vs 8.3 %, mean R2 0.846
    both, transpiration/ET 0.60-0.91 vs 0.23-0.84. It buys the bias by moving ET from
    transpiration to bare-soil evaporation -- see the partition caveat below.
``irr_sw_frac`` (the irrigation decision table)
    Irrigate inside the sheet's window when soil water falls below this fraction of field
    capacity. **This is the knob that actually binds**, because the shortfall was never
    evaporative demand — it was water. 0.5 is the shipped value and the anchor.

**The partition caveat.** eeMetric measures total ET only, so nothing in this objective
constrains how much of it is transpiration. At the fitted settings the model reaches the
totals with transpiration at 0.23-0.84 of ET and 78-109 light irrigations a year; the
``esco`` 0.01 control reaches a believable 0.60-0.91 and undershoots by 17.5 %. At
``pet_co`` 1.0 this model can reproduce the eeMetric totals or a defensible partition, not
both. Do not quote the partition as calibrated, and re-check it before carrying these
parameters into yield or nitrogen work.

Held, not fitted: ``epco`` 1.0 (a compensation factor capped at 1.0 — measured, ``epco`` 2.0
gives ET identical to 1.0, so it can compensate for nothing) and ``pet_co`` 1.0 (collaborator's
instruction 2026-09-15: a basin-wide linear PET multiplier that needs no adjustment given full
daily weather). The 2026-09-11 fit reached the target only by letting ``pet_co`` act as a
per-crop crop coefficient at 1.18-1.59; that is archived as ``*_2026-09-11_petco.*``, not used.

The irrigation-plausibility penalty
-----------------------------------
A soil-water trigger can always hit an ET target by watering more, which would be the same
error ``pet_co`` was making — buying agreement with a quantity nobody measured. Measured
irrigation at this site (``data/irrigation_gracenet.csv``, 2013-2020) is 418-758 mm/yr. The
objective therefore charges for applying more than the wettest measured year, so a crop that
can only reach the target by over-watering is *reported as failing* rather than fitted to it.
The GRACEnet plots are not the eeMetric fields, so this is a plausibility bound on site
practice, not a measurement of those fields.

Two-level fit: an outer grid over the two basin-wide knobs, and inside each grid point a
per-crop fit of the five plant knobs (warm-started from the previous grid point, so the outer
loop is cheap). Alfalfa is fitted last — perennial, four cuttings, highest ET of the seven.

    uv run python scripts/et_reference.py            # build the target first
    uv run python scripts/port_dates.py              # and the sheet's dates + irrigation windows
    uv run python scripts/et_calibrate.py            # all 7, report only
    uv run python scripts/et_calibrate.py --apply    # persist the fit
"""
from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import monoculture as mono  # noqa: E402
from swat_gym.fastrunner import FastRunner  # noqa: E402
from swat_gym.params import get_value, set_value  # noqa: E402

TIO = ROOT / "model" / "TxtInOut"
REF = ROOT / "data" / "et_reference.csv"
FITTED = ROOT / "data" / "et_fitted.json"
IRR_MEASURED = ROOT / "data" / "irrigation_gracenet.csv"
OUT = ROOT / "runs" / "et_calibration"

#: Fit alfalfa last — see module docstring.
ORDER = ["BARL", "CSIL", "POTA", "PTBN", "WWHT", "SGBT", "ALFA"]

#: Per-crop knobs, (low, high), in the order the optimizer sees them.
#:
#: ``lai_pot``'s floor was raised from 0.5 to 2.0 on 2026-09-24, and ``--reg`` from 4 to 10, for
#: a reason that only appeared once irrigation stopped being the binding constraint: with water
#: freely available inside the sheet's window, the fit can hit an ET total either through the
#: canopy or through bare-soil evaporation, and eeMetric measures only the *total*, so the target
#: cannot tell them apart. Left alone it took the second route -- alfalfa landed at ``lai_pot``
#: 0.67 against a workbook BLAI of 5.0, which matches the ET total, is physically absurd, and
#: would destroy the yield channel. LAI is independently known here (it is the collaborator's
#: calibrated sheet value), so it is pinned by prior knowledge rather than by the data.
#: ``frac_eplant`` in the results reports which route each crop actually took.
BOUNDS = {
    "lai_pot": (2.0, 9.0),        # workbook BLAI spans 1.5-5.0; headroom both sides
    "frac_hu1": (0.01, 0.50),     # fraction of PHU at the first LAI point
    "frac_hu2": (0.30, 0.95),     # fraction of PHU at 95 % of maximum LAI
    "hu_lai_decl": (0.50, 1.00),  # fraction of PHU where LAI starts to decline
    "dlai_rate": (0.10, 10.0),    # how fast it declines after that
}
#: The ``plants.plt`` knobs; ``phu_mat`` goes through ``calibration.cal`` instead.
PLANT_KNOBS = tuple(BOUNDS)
#: Heat units to maturity (``monoculture.ET_PHU_KNOB``), fitted since 2026-09-25. Its box is per
#: crop — this fraction of the crop's anchor either side (the sheet's heat units; for alfalfa,
#: the engine's own default) — so it lives on ``CropFit.bounds``, not in :data:`BOUNDS`.
PHU_REL = (0.70, 1.30)
KNOBS = PLANT_KNOBS + (mono.ET_PHU_KNOB,)

#: Basin-wide knobs, (low, high). One value for all seven crops.
SHARED_BOUNDS = {
    "esco": (0.01, 0.95),
    "irr_sw_frac": (0.20, 0.95),
}
SHARED = tuple(SHARED_BOUNDS)

#: ``frac_hu2`` is the *second* point on the canopy curve, so it has to stay above the first.
#: The engine does not check this; at ``frac_hu2 <= frac_hu1`` it interpolates backwards and
#: reports a plausible-looking run.
FRAC_HU_GAP = 0.05

#: |PBIAS| points that one unit of (1 - R2) is charged. At 50, lifting monthly R2 from 0.75 to
#: 0.85 is worth 5 points of |PBIAS| — enough that month *shape* can win a trade against the
#: annual total, not enough to let the fit abandon the total.
R2_WEIGHT = 50.0

#: |PBIAS| points charged per 100 % of over-application above the measured ceiling.
IRR_PENALTY = 100.0

#: |PBIAS| points charged per day of error in the season's ET centroid (the ET-weighted mean
#: date of April-October, from the monthly totals; mean |error| over the three years). Added
#: 2026-09-25 because the collaborator's sugarbeet complaint -- peak ET too early -- is a timing
#: error that monthly R2 only half-sees: R2 also rewards getting the peak's *height* right, and a
#: curve shifted two weeks early can keep a respectable R2. A centroid is smooth in the knobs,
#: which a peak-month index is not, so Nelder-Mead can follow it. At 0.5 a 10-day shift costs
#: 5 points, the same as 0.1 of R2.
TIMING_WEIGHT = 0.5
#: Mid-month day of year for the centroid, non-leap.
_MID_DOY = {m: pd.Timestamp(2023, m, 15).dayofyear for m in range(1, 13)}


def et_centroid(monthly: pd.Series) -> dict[int, float]:
    """``{year: ET-weighted mean day of year over April-October}`` from ``(yr, mon)`` totals."""
    out = {}
    for yr, s in monthly.groupby(level=0):
        s = s.droplevel(0)
        s = s[(s.index >= 4) & (s.index <= 10)]
        tot = float(s.sum())
        out[int(yr)] = (float(sum(_MID_DOY[m] * v for m, v in s.items())) / tot
                        if tot > 0 else float("nan"))
    return out


def measured_irrigation_ceiling() -> float:
    """Wettest measured year, mm (``data/irrigation_gracenet.csv``, 2013-2020)."""
    d = pd.read_csv(IRR_MEASURED)
    return float(d.groupby("year")["mm"].sum().max())


def _rel(p: Path) -> str:
    """Repo-relative when it can be, absolute otherwise (``--outdir`` may be anywhere)."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _md(mon, day):
    """Month/day as a sortable integer, so a window compares in one operation."""
    return mon * 100 + day


def crop_window(code: str) -> tuple[int, int]:
    """(start, end) as month*100+day, from the workbook's emerge and last-harvest dates."""
    _, (em_m, em_d), harvests = mono.CROPS[code]
    hm, hd = harvests[-1]
    return _md(em_m, em_d), _md(hm, hd)


def scoring_window(code: str, window: str) -> tuple[int, int]:
    if window == "season":
        return crop_window(code)
    if window == "apr-oct":
        return _md(4, 1), _md(10, 31)
    return _md(1, 1), _md(12, 31)     # full-year, the default


def r_squared(sim: np.ndarray, obs: np.ndarray) -> float:
    if len(obs) < 2:
        return float("nan")
    ss_res = float(((obs - sim) ** 2).sum())
    ss_tot = float(((obs - obs.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def clip_crop(x, bounds: dict) -> tuple[float, ...]:
    """Clip to the crop's box (``CropFit.bounds``) and enforce ``frac_hu2 >= frac_hu1 + gap``."""
    v = dict(zip(KNOBS, (float(a) for a in np.atleast_1d(x))))
    for k in KNOBS:
        v[k] = float(np.clip(v[k], *bounds[k]))
    v["frac_hu2"] = max(v["frac_hu2"], v["frac_hu1"] + FRAC_HU_GAP)
    v["frac_hu2"] = float(np.clip(v["frac_hu2"], *bounds["frac_hu2"]))
    v["frac_hu1"] = min(v["frac_hu1"], v["frac_hu2"] - FRAC_HU_GAP)
    return tuple(v[k] for k in KNOBS)


class CropFit:
    """One crop's calibration: owns a runner and scores one parameter set."""

    def __init__(self, code: str, ref: pd.DataFrame, workroot: Path,
                 start: int, years: int, window: str = "full-year",
                 reg: float = 10.0, r2_weight: float = R2_WEIGHT,
                 irr_ceiling: float | None = None,
                 irr_penalty: float = IRR_PENALTY,
                 timing_weight: float = TIMING_WEIGHT) -> None:
        self.code = code
        self.reg = reg
        self.r2_weight = r2_weight
        self.timing_weight = timing_weight
        self.irr_ceiling = irr_ceiling
        self.irr_penalty = irr_penalty
        self.plt = mono.CROPS[code][0]
        self.dir = self._build(code, start, years, workroot / f"_tio_{self.plt}")

        self.ref = ref[ref["crop"] == self.plt].copy()
        self.ref["yr"] = self.ref["date"].dt.year
        self.ref["mon"] = self.ref["date"].dt.month
        self.ref["md"] = _md(self.ref["date"].dt.month, self.ref["date"].dt.day)
        self.years = tuple(int(y) for y in sorted(self.ref["yr"].unique()))
        self.window = scoring_window(code, window)
        self.obs = self._totals(self.ref, "et_mm")

        self._plants = (self.dir / "plants.plt").read_text()
        self._hyd = (self.dir / "hydrology.hyd").read_text()
        # The base lum.dtl this crop's irrigation table is appended to, reproducing exactly what
        # _build wrote: the fit varies `irr_sw_frac`, so the table is rebuilt per trial.
        self._dtl_base = mono.with_cutting_dtl(
            mono.prepare_dtl((TIO / "lum.dtl").read_text()), code)
        self.start = {k: get_value(self._plants, "plants.plt", self.plt, k) for k in PLANT_KNOBS}
        phu0 = mono.sheet_phu(self.dir, code)
        self.start[mono.ET_PHU_KNOB] = phu0
        self.bounds = {**BOUNDS, mono.ET_PHU_KNOB: (PHU_REL[0] * phu0, PHU_REL[1] * phu0)}
        self.obs_centroid = et_centroid(
            self.ref[self._mask(self.ref)].groupby(["yr", "mon"])["et_mm"].sum())
        # epco/pet_co are held; assert rather than trust that prepare_plants wrote them.
        for col, val in mono.ET_HYD_FIXED.items():
            got = get_value(self._hyd, "hydrology.hyd", "hyd1", col)
            if abs(got - val) > 1e-6:
                raise RuntimeError(f"{code}: hydrology.hyd {col}={got}, expected held {val}")
        # Only ET is needed, so print only daily hru_wb — a much smaller write per trial.
        self.runner = FastRunner(
            txtinout=self.dir, keep={"hru_wb": {"daily"}},
            editable=frozenset({"plants.plt", "hydrology.hyd", "lum.dtl", "calibration.cal"}))
        self._cache: dict[tuple, dict] = {}
        self.n_evals = 0

    @staticmethod
    def _build(code: str, start: int, years: int, dest: Path,
               sw_frac: float = mono.IRR_SW_FRAC, with_biomass: bool = True) -> Path:
        """A ready-to-run TxtInOut for one crop, identical to what monoculture.py runs.

        ``sw_frac`` writes the windowed irrigation table at that trigger. The directory is
        always left runnable on its own (``et_raw.py`` runs it with nothing editable); the fit
        overrides ``lum.dtl`` per trial instead of rebuilding.
        """
        plt_name = mono.CROPS[code][0]
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(TIO, dest)
        # with_fit=False: the fit must start from the *unfitted* parameters, or the
        # regularisation anchor (self.start) becomes the previous run's answer.
        # workbook_all: the ET runs use the collaborator's sheet verbatim for every crop
        # (decided 2026-09-11) -- the fitted columns are the fit's anchor, the rest is held.
        # with_biomass: the biomass/N-P fit (data/biomass_fitted.json) is applied even here --
        # its columns are not the ET fit's anchor, and the ET refit must see the fitted bm_e /
        # tmp_* (tmp_base moves heat-unit accumulation). biomass_calibrate.py passes False.
        mono.prepare_plants(dest, plt_name, with_fit=False, workbook_all=True,
                            with_biomass=with_biomass)
        harv_op = mono.write_harvest_op(dest, plt_name)
        mono.write_plant_ini(dest, plt_name)
        mono.write_time(dest, start, years)
        # add_sprinkler before the irrigation table, so `lum.dtl` here is exactly
        # build_irrigation_dtl(prepare_dtl(template), ...) and CropFit can reproduce it.
        mono.add_sprinkler(dest)
        # Irrigation follows the sheet's own start/end dates (and, for alfalfa, its
        # stop-a-week-before-each-cutting footnote) instead of the shipped plant-stress table.
        # Alfalfa's cuttings go into lum.dtl first, so the per-trial rebuild in CropFit is
        # build_irrigation_dtl(with_cutting_dtl(prepare_dtl(template))) -- the same order.
        dtl = dest / "lum.dtl"
        dtl.write_text(mono.with_cutting_dtl(dtl.read_text(), code))
        irr_auto = mono.write_irrigation_dtl(dest, code, sw_frac)
        mono.write_management(dest, plt_name, mono.CROPS[code], years, 0.0, harv_op, "auto",
                              irr_auto=irr_auto, cut_auto=mono.cutting_table_name(code))
        # Heat units to maturity at the anchor, so the directory runs on its own; the fit
        # rewrites calibration.cal per trial.
        mono.write_phu_cal(dest, plt_name, mono.sheet_phu(dest, code))
        return dest

    def _mask(self, df: pd.DataFrame) -> pd.Series:
        lo, hi = self.window
        md = df["md"] if "md" in df else _md(df["mon"], df["day"])
        return md.between(lo, hi) & df["yr"].isin(self.years)

    def _totals(self, df: pd.DataFrame, col: str) -> dict[int, float]:
        g = df[self._mask(df)].groupby("yr")[col].sum()
        return {int(y): float(g.get(y, np.nan)) for y in self.years}

    def score(self, shared: dict, **knobs) -> dict:
        key = tuple(round(knobs[k], 4) for k in KNOBS) + tuple(
            round(shared[k], 4) for k in SHARED)
        if key in self._cache:
            return self._cache[key]

        plants = self._plants
        for k in PLANT_KNOBS:
            plants = set_value(plants, "plants.plt", self.plt, k, knobs[k])
        hyd = set_value(self._hyd, "hydrology.hyd", "hyd1", "esco", shared["esco"])
        dtl, _ = mono.build_irrigation_dtl(self._dtl_base, self.code, shared["irr_sw_frac"])
        self.runner.run({"plants.plt": plants, "hydrology.hyd": hyd, "lum.dtl": dtl,
                         "calibration.cal": mono.build_phu_cal(self.plt,
                                                               knobs[mono.ET_PHU_KNOB])})
        self.n_evals += 1

        wb = self.runner.read("hru_wb_day.txt")
        sim = self._totals(wb, "et")
        pbias = {y: 100.0 * (sim[y] - self.obs[y]) / self.obs[y] for y in self.years}
        m = self._mask(wb)
        s = wb[m].groupby(["yr", "mon"])["et"].sum()
        o = self.ref[self._mask(self.ref)].groupby(["yr", "mon"])["et_mm"].sum()
        idx = s.index.intersection(o.index)
        irr_yr = float(wb[m]["irr"].sum()) / len(self.years)
        # Which route the crop took to its total: transpiration or bare-soil evaporation. The
        # target constrains only the sum, so this is reported, never fitted.
        et_sum = float(wb[m]["et"].sum())
        frac_eplant = float(wb[m]["eplant"].sum()) / et_sum if et_sum > 0 else float("nan")

        sim_c = et_centroid(s)
        timing = {y: sim_c[y] - self.obs_centroid[y] for y in self.years}
        res = {**knobs, **shared, **mono.ET_HYD_FIXED,
               "sim": sim, "obs": self.obs, "pbias": pbias,
               "score": float(np.mean([abs(v) for v in pbias.values()])),
               "r2_monthly": r_squared(s.loc[idx].to_numpy(), o.loc[idx].to_numpy()),
               "n_monthly": int(len(idx)), "irr_mm_yr": irr_yr,
               "frac_eplant": frac_eplant,
               # sim minus obs, days; negative = the model's season runs early
               "timing_days": timing,
               "timing_abs_days": float(np.mean([abs(v) for v in timing.values()]))}
        # Five knobs against three annual totals would be under-determined, and several of them
        # move ET the same direction; 36 monthly points identify the curve, and the penalty
        # breaks what ties remain toward the workbook. It is quadratic in each knob's fractional
        # move across its own range and denominated in the objective's own units: `reg` is the
        # |PBIAS| points a full-range move must buy back to be worth making.
        res["penalty"] = self.reg * float(sum(
            ((res[k] - self.start[k]) / (self.bounds[k][1] - self.bounds[k][0])) ** 2
            for k in KNOBS))
        res["r2_term"] = self.r2_weight * (1.0 - res["r2_monthly"])
        res["timing_term"] = self.timing_weight * res["timing_abs_days"]
        # Reaching the target by watering more than the site has ever been watered is not a fit.
        res["irr_term"] = (self.irr_penalty * max(0.0, irr_yr / self.irr_ceiling - 1.0)
                           if self.irr_ceiling else 0.0)
        res["obj"] = (res["score"] + res["r2_term"] + res["timing_term"] + res["irr_term"]
                      + res["penalty"])
        self._cache[key] = res
        return res

    def fit(self, shared: dict, x0=None, grid: int = 3, maxfev: int = 200) -> dict:
        """Fit the six per-crop knobs at fixed ``shared``. ``x0`` warm-starts the search."""
        best = None
        if x0 is None:
            # ET is flat in lai_pot once the canopy closes, so a local method started from the
            # workbook value can stall on that plateau; take a coarse look along it first.
            for lai in np.linspace(*BOUNDS["lai_pot"], grid):
                cand = dict(self.start, lai_pot=float(lai))
                r = self.score(shared, **dict(zip(KNOBS, clip_crop(
                    [cand[k] for k in KNOBS], self.bounds))))
                if best is None or r["obj"] < best["obj"]:
                    best = r
            x0 = np.array([best[k] for k in KNOBS])
        else:
            best = self.score(shared, **dict(zip(KNOBS, clip_crop(x0, self.bounds))))

        # Nelder-Mead is unbounded, so the objective clips and scores the clipped point; the
        # simplex can wander outside but is never *evaluated* outside.
        res = minimize(lambda x: self.score(
                           shared, **dict(zip(KNOBS, clip_crop(x, self.bounds))))["obj"],
                       np.asarray(x0, dtype=float), method="Nelder-Mead",
                       options={"xatol": 1e-3, "fatol": 1e-3, "maxfev": maxfev})
        polished = self.score(shared, **dict(zip(KNOBS, clip_crop(res.x, self.bounds))))
        return polished if polished["obj"] < best["obj"] else best

    def close(self) -> None:
        self.runner.close()


def shared_grid(args) -> list[dict]:
    """The outer grid over the basin-wide knobs."""
    if args.esco is not None and args.sw_frac is not None:
        return [{"esco": args.esco, "irr_sw_frac": args.sw_frac}]
    esco = ([args.esco] if args.esco is not None
            else list(np.linspace(*SHARED_BOUNDS["esco"], args.esco_grid)))
    sw = ([args.sw_frac] if args.sw_frac is not None
          else list(np.linspace(*SHARED_BOUNDS["irr_sw_frac"], args.sw_grid)))
    return [{"esco": float(e), "irr_sw_frac": float(s)}
            for e, s in itertools.product(esco, sw)]


def fit_all(fits: dict[str, CropFit], args) -> tuple[dict, dict, list[dict]]:
    """Two-level fit. Returns ``(best_shared, {code: result}, grid_trace)``."""
    grid = shared_grid(args)
    warm: dict[str, np.ndarray] = {}
    best_shared, best_per, best_mean = None, None, np.inf
    trace = []
    print(f"outer grid: {len(grid)} (esco, irr_sw_frac) point(s) x {len(fits)} crops\n")
    for i, shared in enumerate(grid, 1):
        per = {}
        for code, fit in fits.items():
            r = fit.fit(shared, x0=warm.get(code), grid=args.grid, maxfev=args.maxfev)
            per[code] = r
            warm[code] = np.array([r[k] for k in KNOBS])
        mean_obj = float(np.mean([r["obj"] for r in per.values()]))
        mean_score = float(np.mean([r["score"] for r in per.values()]))
        mean_r2 = float(np.mean([r["r2_monthly"] for r in per.values()]))
        over = [c for c, r in per.items() if r["irr_term"] > 0]
        trace.append({**shared, "mean_obj": mean_obj, "mean_abs_pbias": mean_score,
                      "mean_r2": mean_r2, "crops_over_irr_ceiling": len(over)})
        flag = "  <- best" if mean_obj < best_mean else ""
        print(f"  [{i:>2}/{len(grid)}] esco={shared['esco']:.3f} "
              f"irr_sw_frac={shared['irr_sw_frac']:.3f}  mean obj={mean_obj:7.2f}  "
              f"|PBIAS|={mean_score:5.2f}  R2={mean_r2:.3f}  over-irrigating={len(over)}{flag}",
              flush=True)
        if mean_obj < best_mean:
            best_shared, best_per, best_mean = shared, per, mean_obj

    # The grid runs on a deliberately small per-crop budget -- it only has to rank the two
    # basin-wide values, and the per-crop optimum moves little between neighbouring grid points.
    # The winner is then refitted properly, from both a cold start and the grid's answer, so the
    # reported fit is not limited by the budget that was chosen for ranking.
    if args.final_maxfev > args.maxfev:
        print(f"\npolishing at the winner with maxfev={args.final_maxfev} "
              f"(grid used {args.maxfev})", flush=True)
        for code, fit in fits.items():
            warm_x = np.array([best_per[code][k] for k in KNOBS])
            cand = [fit.fit(best_shared, x0=warm_x, maxfev=args.final_maxfev),
                    fit.fit(best_shared, x0=None, grid=args.grid, maxfev=args.final_maxfev)]
            best_per[code] = min(cand, key=lambda r: r["obj"])
    return best_shared, best_per, trace


def loyo(fits: dict[str, CropFit], shared: dict, args) -> int:
    """Leave-one-year-out: hold one target year, fit on the other two, score the held year."""
    rows = []
    print(f"\nleave-one-year-out at esco={shared['esco']:.3f} "
          f"irr_sw_frac={shared['irr_sw_frac']:.3f}")
    hdr = f"{'crop':<6}{'held':>6}{'train':>8}{'test':>8}   " + "".join(
        f"{k:>12}" for k in KNOBS)
    print(hdr)
    print("-" * len(hdr))
    for code, fit in fits.items():
        all_years = fit.years
        for held in all_years:
            fit.years = tuple(y for y in all_years if y != held)
            fit.obs = fit._totals(fit.ref, "et_mm")
            fit._cache.clear()
            best = fit.fit(shared, grid=args.grid, maxfev=args.maxfev)
            # Score the held-out year with the two-year fit.
            fit.years = all_years
            fit.obs = fit._totals(fit.ref, "et_mm")
            fit._cache.clear()
            full = fit.score(shared, **{k: best[k] for k in KNOBS})
            rows.append({"crop": code, "held": held, "train_pbias": best["score"],
                         "test_pbias": abs(full["pbias"][held]),
                         **{k: best[k] for k in KNOBS}, **shared})
            print(f"{code:<6}{held:>6}{rows[-1]['train_pbias']:>8.1f}"
                  f"{rows[-1]['test_pbias']:>8.1f}   "
                  + "".join(f"{best[k]:>12.3f}" for k in KNOBS), flush=True)
    out = args.outdir / "loyo.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nwrote {_rel(out)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crops", nargs="*", default=None, help=f"subset of {ORDER}")
    ap.add_argument("--calib-start", type=int, default=2015,
                    help="first simulated year for the fit (spin-up before the 2020-22 target)")
    ap.add_argument("--calib-years", type=int, default=8)
    ap.add_argument("--grid", type=int, default=3,
                    help="coarse lai_pot grid points before the local search (cold start only)")
    ap.add_argument("--maxfev", type=int, default=70,
                    help="Nelder-Mead budget per crop fit *during the outer grid*")
    ap.add_argument("--final-maxfev", type=int, default=400,
                    help="budget for the refit at the winning basin-wide values")
    ap.add_argument("--esco-grid", type=int, default=3, help="outer grid points for esco")
    ap.add_argument("--sw-grid", type=int, default=6,
                    help="outer grid points for irr_sw_frac")
    ap.add_argument("--esco", type=float, default=None, help="fix esco instead of gridding it")
    ap.add_argument("--sw-frac", type=float, default=None,
                    help="fix irr_sw_frac instead of gridding it")
    ap.add_argument("--reg", type=float, default=10.0,
                    help="|PBIAS| points a full-range parameter move must buy back; 0 "
                         "disables regularisation and lets the fit rail out")
    ap.add_argument("--r2-weight", type=float, default=R2_WEIGHT,
                    help="|PBIAS| points charged per unit of (1 - monthly R2)")
    ap.add_argument("--irr-penalty", type=float, default=IRR_PENALTY,
                    help="|PBIAS| points charged per 100 %% over the measured irrigation "
                         "ceiling; 0 removes the plausibility bound")
    ap.add_argument("--timing-weight", type=float, default=TIMING_WEIGHT,
                    help="|PBIAS| points charged per day of error in the April-October ET "
                         "centroid; 0 removes the timing term")
    ap.add_argument("--window", choices=("full-year", "season", "apr-oct"),
                    default="full-year",
                    help="full-year: Jan-Dec monthly totals, 36 points per crop (default)")
    ap.add_argument("--apply", action="store_true",
                    help="write the fit into data/et_fitted.json")
    ap.add_argument("--outdir", type=Path, default=OUT)
    ap.add_argument("--loyo", action="store_true",
                    help="leave-one-year-out check at the fitted basin-wide values: for each "
                         "of 2020/21/22, refit on the other two and score the held-out year")
    args = ap.parse_args()

    if not REF.is_file():
        print(f"missing {REF}; run scripts/et_reference.py first", file=sys.stderr)
        return 1
    ref = pd.read_csv(REF, parse_dates=["date"])

    codes = args.crops or ORDER
    bad = [c for c in codes if c not in mono.CROPS]
    if bad:
        raise SystemExit(f"unknown crops {bad}; have {sorted(mono.CROPS)}")
    codes = [c for c in ORDER if c in codes]  # alfalfa stays last whatever the input order

    ceiling = measured_irrigation_ceiling() if args.irr_penalty else None
    args.outdir.mkdir(parents=True, exist_ok=True)
    work = args.outdir / "_work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"fit window {args.calib_start}-{args.calib_start + args.calib_years}, "
          f"target 2020/2021/2022 scored over the {args.window} window\n"
          f"objective: mean |PBIAS| of the {args.window} total "
          f"+ {args.r2_weight:g} x (1 - monthly R2) + {args.timing_weight:g} x |ET centroid "
          f"error, days| + irrigation penalty + regularisation\n"
          f"held: {mono.ET_HYD_FIXED}; "
          f"measured irrigation ceiling: "
          + (f"{ceiling:.0f} mm/yr" if ceiling else "off") + "\n")

    t0 = time.time()
    fits = {code: CropFit(code, ref, work, args.calib_start, args.calib_years, args.window,
                          args.reg, args.r2_weight, ceiling, args.irr_penalty,
                          args.timing_weight)
            for code in codes}
    try:
        best_shared, per, trace = fit_all(fits, args)

        hdr = (f"\n{'crop':<6}{'|PBIAS|':>9}{'R2':>7}{'dT,d':>7}{'irr':>7}{'T/ET':>6}{'n':>6}   "
               + "".join(f"{k:>11}" for k in KNOBS) + "   per-year PBIAS %")
        print(hdr)
        print("-" * len(hdr))
        rows = []
        for code, fit in fits.items():
            best = per[code]
            base = fit.score(best_shared, **fit.start)
            py = "  ".join(f"{y}:{best['pbias'][y]:+6.1f}" for y in fit.years)
            print(f"{code:<6}{best['score']:>9.1f}{best['r2_monthly']:>7.3f}"
                  f"{best['timing_abs_days']:>7.1f}"
                  f"{best['irr_mm_yr']:>7.0f}{best['frac_eplant']:>6.2f}{fit.n_evals:>6}   "
                  + "".join(f"{best[k]:>11.3f}" for k in KNOBS) + f"   {py}")
            lo, hi = fit.window
            rows.append({
                "crop": code, "plants_plt": fit.plt,
                "window": f"{lo // 100}/{lo % 100}-{hi // 100}/{hi % 100}",
                "irrigation_windows": [f"{mono._md_str(a)}-{mono._md_str(b)}"
                                       for a, b in mono.irrigation_windows(code)],
                "start": fit.start,
                "fit": {k: best[k] for k in KNOBS},
                "bounds": fit.bounds,
                "at_bound": {k: bool(min(abs(best[k] - b) for b in fit.bounds[k])
                                     < 1e-3 * max(1.0, fit.bounds[k][1] - fit.bounds[k][0]))
                             for k in KNOBS},
                "score_start": base["score"], "score_fit": best["score"],
                "r2_start": base["r2_monthly"], "r2_fit": best["r2_monthly"],
                "timing_days_start": base["timing_days"], "timing_days_fit": best["timing_days"],
                "timing_abs_days_fit": best["timing_abs_days"],
                "n_monthly": best["n_monthly"],
                "irr_mm_yr": best["irr_mm_yr"], "irr_over_ceiling": best["irr_term"] > 0,
                "frac_eplant": best["frac_eplant"],
                "obs_mm": best["obs"], "sim_mm": best["sim"], "pbias_pct": best["pbias"],
                "meets_r2": bool(best["r2_monthly"] > 0.8),
                "meets_pbias": bool(best["score"] < 10.0),
                "evals": fit.n_evals,
            })

        print(f"\nbasin-wide: esco={best_shared['esco']:.3f} "
              f"irr_sw_frac={best_shared['irr_sw_frac']:.3f}  "
              + "  ".join(f"{k}={v:g}" for k, v in mono.ET_HYD_FIXED.items()) + " (held)")
        railed = [f"{r['crop']}:{k}" for r in rows for k in KNOBS if r["at_bound"][k]]
        if railed:
            print(f"! at a search bound (the fit wanted to keep going): {', '.join(railed)}")
        over = [r["crop"] for r in rows if r["irr_over_ceiling"]]
        if over:
            print(f"! irrigation above the measured {ceiling:.0f} mm/yr ceiling: "
                  f"{', '.join(over)} — reported, not fitted away")
        passed = [r["crop"] for r in rows if r["meets_r2"] and r["meets_pbias"]]
        print(f"\nmeets R2>0.8 and |PBIAS|<10 %: "
              f"{', '.join(passed) if passed else 'none'} "
              f"({len(passed)}/{len(rows)})")
        print(f"R2>0.8: {', '.join(r['crop'] for r in rows if r['meets_r2']) or 'none'}")
        print(f"|PBIAS|<10 %: "
              f"{', '.join(r['crop'] for r in rows if r['meets_pbias']) or 'none'}")

        if args.apply:
            # `et_fitted.json` is the SINGLE destination for the fit. `plants.plt` in the shared
            # template is deliberately NOT written: the regularisation penalty is anchored to
            # whatever the template holds at fit time, so writing the fit back into it makes
            # `--apply` non-idempotent -- a second run would anchor to its own output and drift.
            # `monoculture.apply_et_fit` applies it into each run copy.
            crops_fit = {r["plants_plt"]: r["fit"] for r in rows}
            if set(codes) != set(ORDER):
                # A subset refit replaces only its own crops; writing just `rows` would drop
                # every other crop's fit. The basin-wide values are shared by all seven, so a
                # subset may only be applied at the values the others were fitted at.
                shared_old, crops_old = mono.load_et_fit()
                moved = {k: (shared_old.get(k), best_shared[k]) for k in SHARED
                         if shared_old.get(k) is None
                         or abs(shared_old[k] - best_shared[k]) > 1e-9}
                if moved:
                    raise SystemExit(f"subset --apply at basin-wide values other than the "
                                     f"applied ones {moved}; pass --esco/--sw-frac to match")
                crops_fit = {**crops_old, **crops_fit}
            FITTED.write_text(json.dumps({
                "shared": {**best_shared, **mono.ET_HYD_FIXED},
                "crops": crops_fit,
            }, indent=2, default=float))
            print(f"\nwrote {FITTED.relative_to(ROOT)}")
            print("model/TxtInOut is unchanged; monoculture.py applies the fit per run")

        pd.DataFrame(trace).to_csv(args.outdir / "shared_grid.csv", index=False)
        out = args.outdir / "et_calibration.json"
        out.write_text(json.dumps({
            "objective": (f"mean |PBIAS| of the {args.window} total over 2020/2021/2022 "
                          f"+ {args.r2_weight} x (1 - R2 of the monthly totals) "
                          f"+ {args.timing_weight} x mean |Apr-Oct ET centroid error, days| "
                          f"+ irrigation-plausibility penalty + regularisation"),
            "targets": {"r2_monthly": "> 0.8", "abs_pbias_pct": "< 10"},
            "reference": "OpenET eeMetric, data/et_reference.csv",
            "window": args.window,
            "irrigation": ("sheet start/end dates, soil-water trigger "
                           "(monoculture.build_irrigation_dtl); alfalfa stops "
                           f"{mono.STOP_BEFORE_CUT_DAYS} d before each of 4 cuttings and "
                           f"restarts {mono.RESTART_AFTER_CUT_DAYS} d after"),
            "irr_ceiling_mm_yr": ceiling,
            "bounds": {**BOUNDS, mono.ET_PHU_KNOB: f"{PHU_REL} x anchor, per crop"},
            "shared_bounds": SHARED_BOUNDS, "timing_weight": args.timing_weight,
            "shared_fit": best_shared, "held": mono.ET_HYD_FIXED,
            "reg": args.reg, "r2_weight": args.r2_weight, "irr_penalty": args.irr_penalty,
            "calib_window": [args.calib_start, args.calib_start + args.calib_years],
            "runtime_s": round(time.time() - t0, 1),
            "engine_runs": sum(f.n_evals for f in fits.values()),
            "applied": bool(args.apply), "results": rows,
        }, indent=2, default=float))
        print(f"wrote {_rel(out)} and shared_grid.csv "
              f"({sum(f.n_evals for f in fits.values())} engine runs, "
              f"{time.time() - t0:.0f} s)")

        if args.loyo:
            loyo(fits, best_shared, args)
    finally:
        for f in fits.values():
            f.close()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
