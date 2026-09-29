"""The environment: an action vector in, a profit out, with SWAT+ supplying the dynamics.

Two modes, because the two experiments ask different questions.

**Open-loop** (:func:`evaluate`) -- one vector describes the whole rotation, one engine run
returns one reward. This is Experiment 1's lever ablation: it finds the best *fixed* schedule,
which is the bar a policy has to beat.

**Annual replay** (:class:`SwatEnv`) -- a `gymnasium` env with one decision per year. SWAT+ has
no checkpoint/restart, so state at year *t* is obtained by re-running years 0..*t* with the
actions chosen so far: O(T) engine runs per episode, tractable only because T is 7.

Stochastic weather comes free
-----------------------------
``port_agrimet.py`` now writes **1995-2025** into the weather files, so an episode samples an
8-year weather window by rewriting ``time.sim`` alone -- no weather file is touched. That is
what makes a policy worth learning: with a single deterministic trace there is nothing to react
to, and a sequential policy cannot beat an optimized fixed schedule.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .constrainers import MAX_N_LOADING, repair, violations
from .fastrunner import EDITABLE, FastRunner
from .rewarders import Prices, nass, profit
from .schedule import CROPS, MANURE_SOURCES, YearAction, build

#: Decision years per episode. The window is 8 calendar years: one spin-up that ``print.prt``
#: ``nyskip`` discards, then seven scored years — the same shape as the measured rotation.
N_YEARS = 7
SPINUP = 1

#: Per-year action dimensions, all in [0, 1].
#: 0-2 crop scores (argmax) | 3 manure rate | 4 manure day | 5 manure source (binned)
#: 6 mineral rate 1 | 7 mineral day 1 | 8 mineral rate 2 | 9 mineral day 2
#: 10 irrigation start | 11 irrigation interval | 12 irrigation depth
#:
#: Mineral *source* is not a dimension: see :data:`swat_gym.schedule.MINERAL_SOURCE`.
#:
#: **Two mineral applications, and never more.** Exp 1c swept application count k = 1..7 at
#: constant dimensionality (`runs/exp1c_cadence_e500.json`): k >= 3 lost 310-835 $/ha against
#: k = 1, while k = 1 and k = 2 finished 69 $/ha apart -- inside a noise floor of roughly
#: 200-300 $/ha, which the curve's own non-monotonicity (k=3 < k=4, k=5 < k=6) reveals. Two
#: independent applications *nest* both survivors: the optimizer reaches k = 1 by driving the
#: second rate to zero. Going finer was measured, not assumed, to be worse.
ACTION_DIM = 13

#: Which action dimensions each experiment is allowed to move. Everything else is held at
#: :data:`DEFAULT_PLAN`, so an arm's gain is attributable to its lever alone.
#:
#: Two arms, one per experiment, plus the do-nothing control. ``N`` merges manure with mineral
#: fertiliser because they are one decision -- how much N, from which source, when -- competing
#: under one :data:`MAX_N_LOADING` cap.
#:
#: **The combination arms are gone, twice over.** ``M``/``MR`` went first: ``all`` at 63
#: parameters scored *below* its own 42-parameter subset ``MR`` on an equal evaluation budget,
#: an under-convergence artefact rather than a finding. ``R`` (rotation) and ``all`` (the Exp 4
#: joint search) went on **2026-09-09** with the scope reduction to two levers. The rotation is
#: still *simulated* -- ``DEFAULT_PLAN`` encodes the measured corn/barley/alfalfa sequence and
#: dimensions 0-2 still decode to a crop -- it is simply no longer a *decision variable*. That
#: is what converts the +49.5 % alfalfa yield bias from a differential error between arms into
#: a common-mode one shared by all of them.
ARMS = {
    "baseline": (),
    "N": (3, 4, 5, 6, 7, 8, 9),
    "I": (10, 11, 12),
}

#: The default a free lever is measured *against*, and therefore load-bearing: an arm's reported
#: gain is only meaningful if the thing it improves on is realistic management. These values
#: reproduce the measured GRACEnet practice — manure ~45 Mg/ha on 10 April, irrigation every
#: 7 days from ~10 May.
#:
#: **Irrigation depth is calibrated to the measured total, not chosen round.** The grid emits
#: 120 events over the rotation (19 on corn, 14 on barley, 18 on alfalfa), so reproducing the
#: measured 3,938.8 mm needs 32.82 mm/event — index 0.8206 on the 0-40 mm range — rather than
#: the 30.0 that was here. Combined with the :data:`~swat_gym.schedule.IRR_EFF` fix (0.85 -> 1.0)
#: this closes a 22 % under-irrigation of every generated row against the human bar; the two
#: defects compounded, delivering 3,060.0 mm where the docstring claimed ~570 mm/yr.
#:
#: An earlier version used the midpoint of every range. That irrigated 172 mm/yr, a third of
#: the measured rate, and handed the `I` arm a spurious +3,660 $/ha of headroom that was really
#: just the distance from a bad default back to normal practice.
#: Mineral N sits at **zero**, which is measured practice: the shipped ``management.sch`` has
#: four ``fert`` operations and all four are GRACEnet manure. So the `N` arm's gain is scored
#: against a field that buys no nitrogen, which is the real counterfactual here.
DEFAULT_ACTION = np.array([
    0.9, 0.1, 0.1,   # crop scores -> corn
    0.50,            # manure 45 Mg/ha
    0.4595,          # manure day 100 (10 April, the measured date)
    0.00,            # manure source gn2013
    0.00,            # mineral rate 1 — 0 kg/ha, measured practice applies none
    0.4231,          # mineral day 1 — 120
    0.00,            # mineral rate 2 — 0 kg/ha
    0.5385,          # mineral day 2 — 152
    0.375,           # irrigation start day 130
    0.2222,          # irrigation interval 7 d
    0.8206,          # irrigation depth 32.82 mm -> 3,938.8 mm/rotation, the measured total
])

#: Per-year default plan. The rotation is the **measured** one — corn, barley, three years of
#: alfalfa, corn, barley — and since 2026-09-09 it is *fixed*: every arm runs on the field's
#: real rotation, so no arm's result depends on trading alfalfa area against the annuals.
MEASURED_ROTATION = ("corn", "barl", "alfa", "alfa", "alfa", "corn", "barl")


#: Measured GRACEnet manure, per rotation year: ``(Mg/ha, source)``.
#:
#: **Why this is not a flat 45 Mg/ha of one source.** `DEFAULT_PLAN` is the "measured practice"
#: baseline every other arm is scored against, so it has to *nest* measured practice — the same
#: requirement the irrigation nesting gate enforces for water. It did not for nitrogen. A
#: uniform 45 Mg/ha of `gn2013` in all four fertilisable years delivers **2,340 kg N/ha** over
#: the rotation against the field's measured **2,090**, because `MANURE_N_FRAC` varies fourfold
#: across the four manures (0.0130 / 0.0195 / 0.0041 / 0.0041). Every generated arm therefore
#: carried +250 kg N/ha (+12 %) that measured practice never received, and every "vs measured"
#: comparison was a nitrogen contrast as much as an irrigation one.
#:
#: Masses and sources from `GraceNet crop and manure amounts.xlsx`, sheet
#: `Manure Nutrient Properties`. The alfalfa years received none. Date is 10 April in all four
#: years, which `DEFAULT_ACTION[4]` already encodes.
MEASURED_MANURE: tuple[tuple[float, str | None], ...] = (
    (43.8, "gn2013"),   # 2013 corn
    (48.0, "gn2014"),   # 2014 barley
    (0.0, None),        # 2015 alfalfa
    (0.0, None),        # 2016 alfalfa
    (0.0, None),        # 2017 alfalfa
    (88.3, "gn2018"),   # 2018 corn
    (54.3, "gn2019"),   # 2019 barley
)


def _encode_manure(mass_mg: float, source: str | None) -> tuple[float, float]:
    """``(mass, source)`` -> the two unit-box genes `decode_year` reads at v[3] and v[5]."""
    lo, hi = _RANGES[3]
    v3 = (mass_mg - lo) / (hi - lo)
    # decode_year buckets v[5] by ``int(clip(v,0,0.999) * len(MANURE_SOURCES))``; aim at the
    # centre of the bucket so float error cannot tip it into a neighbour.
    idx = MANURE_SOURCES.index(source) if source else 0
    return v3, (idx + 0.5) / len(MANURE_SOURCES)


def _default_plan() -> np.ndarray:
    plan = np.tile(DEFAULT_ACTION, (N_YEARS, 1))
    for i, crop in enumerate(MEASURED_ROTATION):
        plan[i, 0:3] = 0.1
        plan[i, CROPS.index(crop)] = 0.9
        mass, src = MEASURED_MANURE[i]
        plan[i, 3], plan[i, 5] = _encode_manure(mass, src)
    return plan



#: Application-timing floor, day of year. **32 (1 February), widened from 60.**
#:
#: Both previous runs put timing hard against a lower bound: Exp 1's optimum sat at DOY 61-67
#: with the floor at 60, and Exp 1c chose month 4 with the window starting at month 4. An
#: optimum on a boundary is not an optimum, it is a statement that the search wanted to go
#: further, so the range is widened to find out where it actually lands.
#:
#: If it pins at 32 as well, that is a **model-behaviour finding, not agronomy** — a February
#: broadcast onto frozen southern-Idaho ground is not a recommendation, and a persistent
#: preference for ever-earlier N would point at the mineralisation or uptake timing in the
#: calibration rather than at a management insight.
TIMING_FLOOR = 32.0

_RANGES = {
    3: (0.0, 90.0),               # manure Mg/ha
    4: (TIMING_FLOOR, 180.0),     # manure day of year
    # Top of each mineral range is MAX_N_LOADING itself, so a single application can reach the
    # cap on its own and the constraint is what stops it rather than the parameterisation. If
    # the arm optimum lands *at* the cap the experiment is measuring the cap, not the agronomy
    # — exactly the diagnostic the constrainer docstring asks for, and what happened last run.
    6: (0.0, 400.0),              # mineral application 1, kg N/ha
    7: (TIMING_FLOOR, 240.0),     # mineral application 1, day of year
    8: (0.0, 400.0),              # mineral application 2, kg N/ha
    9: (TIMING_FLOOR, 240.0),     # mineral application 2, day of year
    10: (100.0, 180.0),           # irrigation start day of year
    11: (3.0, 21.0),              # irrigation interval, days
    12: (0.0, 40.0),              # irrigation depth, mm/event
}

#: Built here rather than beside :func:`_default_plan` because the per-year
#: measured manure encoding needs ``_RANGES``.
DEFAULT_PLAN = _default_plan()

WEATHER_YEARS = (1995, 2025)

#: Observation width. **11, widened from 7, and the widening is the point.**
#:
#: The old vector was ``[t, prev-crop one-hot, stand age, last yield, last NO3]`` — nothing
#: about the state of the soil. Next year's weather is not knowable when the year's decision is
#: made, so **carryover is the only channel through which a policy can be adaptive at all**, and
#: a fertiliser policy that cannot see carryover nitrogen or stored water was being asked to
#: react to something it had no way of observing. Exp 1's PPO null (−696 $/ha against CMA-ES,
#: adaptivity share ~0) was therefore a measurement of this vector, not of RL.
#:
#: The four added signals are all read off tables :data:`swat_gym.printprt.GYM_OUTPUTS` already
#: prints, so this costs no extra engine time:
#:
#: * ``strsn`` — last year's N-stress days. The most direct "was nitrogen limiting" signal
#:   the model produces, and the variable Exp 1's mechanism is written in.
#: * ``strsw`` — last year's water-stress days, the same service for the `I` arm.
#: * ``sw_final`` — soil water carried into the new year, mm.
#: * ``n_surplus`` — cumulative N applied/fixed/mineralised less uptake and losses. SWAT+'s
#:   yearly tables carry **no soil mineral-N pool**, so this is a balance residual, not a state
#:   variable read off the model. It has the right sign and the right order of magnitude for
#:   "am I accumulating nitrogen"; it is not a soil test.
#:
#: Widened for all three experiments together rather than for Exp 1 alone, so the environment
#: stays one environment and the three results stay comparable.
OBS_DIM = 11


def _lerp(x: float, lo: float, hi: float) -> float:
    return lo + float(np.clip(x, 0.0, 1.0)) * (hi - lo)


def decode_year(vec: Sequence[float]) -> YearAction:
    v = np.asarray(vec, dtype=float)
    src_i = min(int(np.clip(v[5], 0.0, 0.999) * len(MANURE_SOURCES)), len(MANURE_SOURCES) - 1)
    # Both mineral applications go through `fert_splits`, including zero-rate ones: the
    # schedule skips a zero rate rather than emitting an op, so a plan that wants one
    # application simply drives the other rate to zero and pays for one pass, not two.
    splits = tuple(
        (int(round(_lerp(v[doy_i], *_RANGES[doy_i]))), _lerp(v[rate_i], *_RANGES[rate_i]))
        for rate_i, doy_i in ((6, 7), (8, 9))
    )
    return YearAction(
        crop=CROPS[int(np.argmax(v[0:3]))],
        manure_mg=_lerp(v[3], *_RANGES[3]),
        manure_doy=int(round(_lerp(v[4], *_RANGES[4]))),
        manure_src=MANURE_SOURCES[src_i],
        fert_splits=splits,
        irr_start_doy=int(round(_lerp(v[10], *_RANGES[10]))),
        irr_interval=int(round(_lerp(v[11], *_RANGES[11]))),
        irr_depth=_lerp(v[12], *_RANGES[12]),
    )


def decode(flat: Sequence[float], *, constrain: bool = True,
           max_n: float | None = MAX_N_LOADING) -> list[YearAction]:
    """Flat vector (``N_YEARS * ACTION_DIM``) -> a feasible plan.

    ``max_n`` is threaded rather than fixed because Exp 1 saturated the cap in every
    fertilisable year, so the headline was a statement about ``MAX_N_LOADING`` — a policy
    choice in our own code — rather than about nitrogen. Passing ``None`` disables it, which is
    what the {400, uncapped} sweep needs to find out whether 400 was ever binding.
    """
    a = np.asarray(flat, dtype=float).reshape(N_YEARS, ACTION_DIM)
    plan = [decode_year(row) for row in a]
    return repair(plan, max_n=max_n) if constrain else plan


def arm_dims(arm: str) -> tuple[int, ...]:
    """Dimensions an arm owns."""
    if arm not in ARMS:
        raise KeyError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")
    return ARMS[arm]


def arm_vector(free: Sequence[float], arm: str) -> np.ndarray:
    """Expand an arm's free parameters into a full action vector.

    Dimensions the arm does not own stay at :data:`DEFAULT_PLAN`, so every arm is scored
    against the same measured-practice baseline and gains are attributable to the lever.
    """
    dims = arm_dims(arm)
    full = DEFAULT_PLAN.copy()
    if dims:
        full[:, list(dims)] = np.asarray(free, dtype=float).reshape(N_YEARS, len(dims))
    return full.ravel()


def default_free(arm: str) -> np.ndarray:
    """The arm's free parameters at their default values — its optimisation start point."""
    dims = arm_dims(arm)
    return DEFAULT_PLAN[:, list(dims)].ravel() if dims else np.zeros(0)


def time_sim(start_year: int, n_years: int = N_YEARS + SPINUP) -> str:
    """A ``time.sim`` selecting one weather window out of the ported record."""
    return (
        "time.sim: written by swat_gym.env\n"
        "day_start  yrc_start   day_end   yrc_end      step  \n"
        f"{0:>10}{start_year:>11}{0:>10}{start_year + n_years - 1:>10}{0:>10}  \n"
    )


def _edits(plan: list[YearAction], start_year: int) -> dict[str, str]:
    e = build(plan)
    e["time.sim"] = time_sim(start_year, len(plan) + SPINUP)
    return e


def evaluate(flat: Sequence[float], runner: FastRunner, *, prices: Prices | None = None,
             start_year: int = 2012, constrain: bool = True, no3_price: float = 0.0,
             max_n: float | None = MAX_N_LOADING) -> dict:
    """Open-loop: score one complete rotation plan with a single engine run."""
    prices = prices or nass(2024)
    plan = decode(flat, constrain=constrain, max_n=max_n)
    runner.run(_edits(plan, start_year))
    out = profit(runner, prices, no3_price=no3_price)
    out["plan"] = [(a.crop, round(a.manure_mg, 1),
                    [(d, round(kg, 1)) for d, kg in a.fert_splits], a.irr_depth)
                   for a in plan]
    out["start_year"] = start_year
    out["infeasible"] = violations(plan, max_n=max_n)
    return out


class SwatEnv:
    """Annual-cadence environment over the calibrated Kimberly field.

    Implements the `gymnasium` API without inheriting from it, so the package imports cleanly
    when gymnasium is absent; :meth:`to_gym` wraps it when the RL extra is installed.
    """

    #: Per-step reward is a year's profit in $/ha, order 2,000. Handed to PPO unscaled that
    #: puts the value target around 1e7 and the critic spends its budget on magnitude rather
    #: than on ranking actions. Scaling only changes the units of the *learning signal*;
    #: ``info["cum_profit"]`` stays in dollars, and evaluation reads that.
    REWARD_SCALE = 1e-3

    def __init__(self, runner: FastRunner | None = None, *, prices: Prices | None = None,
                 stochastic_weather: bool = True, train_years: Sequence[int] | None = None,
                 no3_price: float = 0.0, seed: int | None = None,
                 reward_scale: float | None = None, arm: str,
                 max_n: float | None = MAX_N_LOADING) -> None:
        self._own = runner is None
        self.runner = runner or FastRunner(editable=EDITABLE)
        self.prices = prices or nass(2024)
        self.max_n = max_n
        #: The policy may only move its experiment's dimensions; the rest stay at
        #: :data:`DEFAULT_PLAN`. Without this the RL side of an experiment is not the same
        #: experiment as the CMA-ES side, and the two rows are not comparable.
        self.free_dims = arm_dims(arm)
        self.arm = arm
        self.stochastic_weather = stochastic_weather
        self.no3_price = no3_price
        self.reward_scale = self.REWARD_SCALE if reward_scale is None else reward_scale
        lo, hi = WEATHER_YEARS
        self.train_years = list(train_years) if train_years is not None else list(
            range(lo, hi - N_YEARS - SPINUP + 2)
        )
        self.rng = np.random.default_rng(seed)
        self.reset()

    # -- gymnasium-ish API ---------------------------------------------------------------

    def reset(self, *, seed: int | None = None, start_year: int | None = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if start_year is not None:
            self.start_year = start_year
        elif self.stochastic_weather:
            self.start_year = int(self.rng.choice(self.train_years))
        else:
            self.start_year = 2012
        self.plan: list[YearAction] = []
        self.cum_profit = 0.0
        self.last = dict.fromkeys(
            ("yield", "no3", "strsn", "strsw", "sw", "n_surplus"), 0.0)
        return self._obs(), {}

    def expand(self, action: Sequence[float]) -> np.ndarray:
        """A policy's free parameters -> a full year action vector.

        Defaults come from ``DEFAULT_PLAN[t]``, not from :data:`DEFAULT_ACTION`, because the
        default *rotation* varies by year. An `N` or `I` policy therefore runs on the measured
        crop sequence rather than on continuous corn.
        """
        a = np.asarray(action, dtype=float)
        t = min(len(self.plan), N_YEARS - 1)
        full = DEFAULT_PLAN[t].copy()
        full[list(self.free_dims)] = a
        return full

    def step(self, action: Sequence[float]):
        self.plan.append(decode_year(self.expand(action)))
        # Repair the whole prefix each step: extending an alfalfa stand is a constraint on the
        # plan, not on a single year, so it can only be enforced with the prefix in hand.
        plan = repair(self.plan, max_n=self.max_n)
        self.runner.run(_edits(plan, self.start_year))
        d = profit(self.runner, self.prices, no3_price=self.no3_price)

        reward = (d["profit"] - self.cum_profit) * self.reward_scale
        self.cum_profit = d["profit"]
        self.last = self._carryover(d)
        self.plan = plan
        terminated = len(self.plan) >= N_YEARS
        return self._obs(), reward, terminated, False, {"cum_profit": self.cum_profit, **d}

    def _carryover(self, d: dict) -> dict:
        """What the *next* decision is allowed to see — see :data:`OBS_DIM`.

        Every figure is last-year-or-earlier. The engine has just re-run years 0..t, so the
        yearly tables carry one row per decided year and ``.iloc[-1]`` is the year just scored.
        """
        y = self.runner.yields()
        pw = self.runner.read("hru_pw_yr.txt")
        wb = self.runner.read("hru_wb_yr.txt")
        nb = self.runner.read("basin_nb_yr.txt")
        # Rotation-cumulative, because carryover is what has built up, not what one year did.
        surplus = float(
            (nb["fertn"] + nb["fixn"] + nb["act_nit_n"] + nb["no3atmo"] + nb["nh4atmo"]
             - nb["nuptake"] - nb["denit"]).sum() - pw["percn"].sum()
        )
        return {
            "yield": float(y["yld(t)"].iloc[-1]) if len(y) else 0.0,
            "no3": d["no3_leached_kg"],
            "strsn": float(pw["strsn"].iloc[-1]),
            "strsw": float(pw["strsw"].iloc[-1]),
            "sw": float(wb["sw_final"].iloc[-1]),
            "n_surplus": surplus,
        }

    def _obs(self) -> np.ndarray:
        t = len(self.plan)
        prev = self.plan[-1].crop if self.plan else None
        onehot = [1.0 if prev == c else 0.0 for c in CROPS]
        stand = 0
        for a in reversed(self.plan):
            if a.crop == "alfa":
                stand += 1
            else:
                break
        # Divisors are order-of-magnitude scalings, not normalisations: they put every element
        # near [0, 1] so the policy's first layer is not dominated by whichever signal happens
        # to be measured in the largest unit.
        return np.array(
            [t / N_YEARS, *onehot, stand / N_YEARS,
             self.last["yield"] / 30.0,
             self.last["no3"] / 10.0,
             self.last["strsn"] / 50.0,
             self.last["strsw"] / 50.0,
             self.last["sw"] / 300.0,
             self.last["n_surplus"] / 200.0],
            dtype=np.float32,
        )

    def close(self) -> None:
        if self._own:
            self.runner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- gymnasium adapter ---------------------------------------------------------------

    def to_gym(self):
        """Wrap as a real ``gymnasium.Env`` (requires the ``rl`` extra)."""
        import gymnasium as gym
        from gymnasium import spaces

        outer = self

        class _Gym(gym.Env):
            metadata = {"render_modes": []}
            observation_space = spaces.Box(-np.inf, np.inf, (OBS_DIM,), dtype=np.float32)
            # Only the arm's own dimensions are exposed, so PPO spends its budget on the
            # lever under test instead of on dimensions that are pinned anyway.
            action_space = spaces.Box(0.0, 1.0, (len(outer.free_dims),), dtype=np.float32)

            def reset(self, *, seed=None, options=None):
                return outer.reset(seed=seed)

            def step(self, action):
                return outer.step(action)

            def close(self):
                outer.close()

        return _Gym()
