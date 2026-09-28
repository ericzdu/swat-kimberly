"""The growers' own irrigation, distilled into a rule that can be run on any weather.

Why a rule and not the log
--------------------------
The ``measured`` row (:func:`~swat_gym.experiments._focused.score_measured`) replays the logged
2013-2019 schedule, unchanged, on every weather window. That is one fixed schedule on weather it
was never a response to: the growers were watering *their* seasons, and a verbatim replay on
someone else's strips out whatever responsiveness they had. Running the log on its own weather
is not an option for a held-out comparison either — only one window (start 2012) lines up with
it, and that window is the buffer between the train and test splits.

This row asks instead: *if the growers' behaviour is a rule, what rule, and what does it earn
elsewhere?* The rule is the feedback controller of :mod:`exp1_controller` — same three
parameters, same monthly soil-water and precipitation state — so the grower row and the
profit-optimised controller row differ **only in what (a, b, c) was fitted to**: the growers'
monthly depths here, profit on the training windows there. It is never optimised for profit.

The fit, and the one thing to disclose about it
-----------------------------------------------
Fitted on the logged window (start 2012: spin-up 2012, scored 2013-2019) to the 42 logged
monthly totals, April-September, under the generated calendar every other arm uses. The loss is
squared monthly error plus a penalty holding the rotation total within :data:`GATE_TOL` of the
logged total — the rule 5 gate, applied to this row. October's 43 mm (2.2 % of the total) falls
outside the monthly action space and cannot be matched in time; the total gate makes the rule
put that water somewhere rather than lose it, exactly as the generated default does.

**2013-2019 overlaps the test windows' calendar years.** Rule 7 forbids that for any arm that
is *searched*; this row is not. It is fitted to behaviour, never scored against profit during
the fit, and is reported as a reference row beside the replayed log — never as a learned arm.
The artefact records the fit years so the disclosure travels with the numbers.

    uv run python -m swat_gym.experiments.exp1_grower_rule --evals 220
    uv run python -m swat_gym.experiments.exp1_grower_rule --from-fit runs/exp1_grower_rule.json \\
        --no3-price 16 --out runs/exp1_grower_rule_n16.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ..env import DEFAULT_PLAN, N_YEARS, decode_year
from ..fastrunner import FastRunner
from ..monthly import N_GROWING, year_events
from ..rewarders import average
from ..schedule import GROWING_MONTHS, _md
from ..windows import TRAIN_YEARS, TEST_YEARS, assert_no_leakage
from ._focused import ROOT, _row, mean
from ._optimize import minimise
from .exp1_controller import _decode_abc, rollout_controller

OUT = ROOT / "runs" / "exp1_grower_rule.json"
IRR_CSV = ROOT / "data" / "irrigation_gracenet.csv"

#: The only window whose calendar years are the logged ones: 2012 spin-up, 2013-2019 scored.
FIT_START = 2012
FIT_YEARS = list(range(FIT_START + 1, FIT_START + 1 + N_YEARS))

#: Rule 5's tolerance on applied water, applied to the fitted rule on its own weather.
GATE_TOL = 0.01

#: Weight on the total-water penalty, per mm² of excess beyond :data:`GATE_TOL`. Large enough
#: that the fit cannot trade the gate for monthly timing: a 10 mm excess costs 1e5 mm², against
#: a monthly SSE on the order of 1e5 at a poor fit.
TOTAL_PENALTY = 1e3

#: Same start point as the controller's profit fit, so the two fits differ only in the target.
X0 = np.array([0.2, 0.3, 0.3])


def logged_monthly_mm() -> np.ndarray:
    """The logged irrigation as ``(N_YEARS, N_GROWING)`` monthly totals, April-September."""
    df = pd.read_csv(IRR_CSV)
    df = df[df.year.isin(FIT_YEARS)]
    mon = pd.to_datetime(df["date"]).dt.month
    out = np.zeros((N_YEARS, N_GROWING))
    for (yr, m), mm in df.groupby([df.year, mon])["mm"].sum().items():
        if m in GROWING_MONTHS:
            out[FIT_YEARS.index(yr), GROWING_MONTHS.index(m)] = mm
    return out


def logged_total_mm() -> float:
    """Every logged millimetre in the scored years, including October's."""
    df = pd.read_csv(IRR_CSV)
    return float(df[df.year.isin(FIT_YEARS)]["mm"].sum())


def rendered_monthly_mm(month_mm: np.ndarray) -> np.ndarray:
    """Decided monthly volumes -> the monthly totals the engine is actually handed.

    Goes through :func:`~swat_gym.monthly.year_events`, the renderer every arm shares, so water
    decided for a month after harvest is compared where it actually lands (carried back into
    the season), not where it was asked for.
    """
    month_mm = np.asarray(month_mm, dtype=float).reshape(N_YEARS, N_GROWING)
    out = np.zeros_like(month_mm)
    for y in range(N_YEARS):
        crop = decode_year(DEFAULT_PLAN[y]).crop
        for doy, mm in year_events(month_mm[y], crop):
            m = _md(doy)[0]
            if m in GROWING_MONTHS:
                out[y, GROWING_MONTHS.index(m)] += mm
    return out


def fit_loss(rendered: np.ndarray, target: np.ndarray, total: float) -> float:
    """Squared monthly error, plus a penalty once the total leaves the rule 5 tolerance."""
    sse = float(((rendered - target) ** 2).sum())
    excess = max(0.0, abs(float(rendered.sum()) - total) - GATE_TOL * total)
    return sse + TOTAL_PENALTY * excess ** 2


def fit_diagnostics(sim: dict, target: np.ndarray, total: float) -> dict:
    """How much of the growers' behaviour three parameters capture, on the logged weather."""
    rendered = rendered_monthly_mm(np.asarray(sim["month_mm"]))
    resid = rendered - target
    ss_tot = float(((target - target.mean()) ** 2).sum())
    applied = float(sim["irrigation_mm"])
    err = (applied - total) / total
    return {
        "target_monthly_mm": target.round(1).tolist(),
        "fitted_monthly_mm": rendered.round(1).tolist(),
        "target_annual_mm": target.sum(axis=1).round(1).tolist(),
        "fitted_annual_mm": rendered.sum(axis=1).round(1).tolist(),
        "rmse_monthly_mm": float(np.sqrt((resid ** 2).mean())),
        "r2_monthly": float(1.0 - (resid ** 2).sum() / ss_tot) if ss_tot > 0 else float("nan"),
        "logged_total_mm": total,
        "simulated_total_mm": applied,
        "total_err_pct": 100.0 * err,
        "gate_pass": bool(abs(err) <= GATE_TOL),
    }


def fit(runner: FastRunner, *, evals: int, seed: int, prices) -> tuple[np.ndarray, int, list]:
    """CMA-ES over (a, b, c) against the logged months. Profit is computed and ignored."""
    target, total = logged_monthly_mm(), logged_total_mm()

    def obj(abc):
        try:
            sim = rollout_controller(abc, runner, start_year=FIT_START, prices=prices,
                                     max_n=None)
        except Exception:
            return 1e12
        return fit_loss(rendered_monthly_mm(np.asarray(sim["month_mm"])), target, total)

    return minimise(obj, X0, evals=evals, seed=seed, desc="grower-rule fit")


def main(argv=None) -> dict:
    assert_no_leakage()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evals", type=int, default=220,
                    help="CMA-ES evaluations; each is one 42-month rollout (43 engine runs). "
                         "The controller's 3-parameter profit fit converges by ~220")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--from-fit", type=Path, default=None,
                    help="reuse the (a, b, c) fitted in this artefact and only re-score. The "
                         "fit is independent of --no3-price, so frontier points should reuse it")
    ap.add_argument("--no3-price", type=float, default=0.0,
                    help="$/kg N on leached nitrate for *scoring*; must match the arm this row "
                         "is compared against. The fit itself never sees a price")
    ap.add_argument("--water-price", type=float, default=None,
                    help="$/mm/ha override for DEFAULT_WATER (sourced composite)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    prices = average()
    if args.water_price is not None:
        prices = replace(prices, water=args.water_price,
                         label=f"{prices.label}@w={args.water_price:g}")
    train, test = list(TRAIN_YEARS), list(TEST_YEARS)
    target, total = logged_monthly_mm(), logged_total_mm()
    t0 = time.time()

    with FastRunner() as runner:
        if args.from_fit is not None:
            src = json.loads(args.from_fit.read_text())
            best = np.asarray(src["abc"], dtype=float)
            n_evals, history = src["n_evals"], src["history"]
            print(f"reusing fit from {args.from_fit.name}: {src['decoded']}", flush=True)
        else:
            best, n_evals, history = fit(runner, evals=args.evals, seed=args.seed,
                                         prices=prices)
        fit_runs = runner.n_runs

        sim = rollout_controller(best, runner, start_year=FIT_START, prices=prices, max_n=None)
        diag = fit_diagnostics(sim, target, total)
        print(f"fit: applied {diag['simulated_total_mm']:.1f} mm vs logged {total:.1f} "
              f"({diag['total_err_pct']:+.2f} %), monthly RMSE {diag['rmse_monthly_mm']:.1f} mm, "
              f"R² {diag['r2_monthly']:.2f}", flush=True)

        summary = {
            "abc": list(map(float, best)), "decoded": dict(zip("abc", _decode_abc(best))),
            "fit": diag, "fit_window_start": FIT_START, "fit_years": FIT_YEARS,
            "fit_note": ("fitted to logged grower behaviour on 2013-2019 weather, which "
                         "overlaps the test windows' calendar years; never fitted to profit, "
                         "so a reference row, not a learned arm"),
            "n_evals": n_evals, "history": history, "fit_engine_runs": fit_runs,
            "max_n": None, "no3_price": args.no3_price, "prices": prices.label,
            "train_years": train, "test_years": test,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)

        # Rule 5: validate against the measured total before scoring anything with it.
        if not diag["gate_pass"]:
            summary["scored"] = False
            args.out.write_text(json.dumps(summary, indent=2))
            print(f"GATE FAILED: fitted rule applies {diag['total_err_pct']:+.2f} % of the "
                  f"logged total (tolerance ±{100 * GATE_TOL:g} %). Not scored.", flush=True)
            print(f"-> {args.out}")
            sys.exit(3)

        def score(windows):
            return [_row(rollout_controller(best, runner, start_year=sy, prices=prices,
                                            no3_price=args.no3_price, max_n=None), sy)
                    for sy in windows]

        train_rows, test_rows = score(train), score(test)

    summary.update({
        "scored": True,
        "train": mean(train_rows), "test": mean(test_rows),
        "per_window_train": train_rows, "per_window_test": test_rows,
        "seconds": round(time.time() - t0, 1),
    })
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"grower rule  train {summary['train']:.0f}  test {summary['test']:.0f} $/ha")
    print(f"params a,b,c = {summary['decoded']}")
    print(f"-> {args.out}")
    return summary


if __name__ == "__main__":
    main()
