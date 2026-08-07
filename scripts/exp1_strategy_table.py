#!/usr/bin/env python3
"""Score Exp 1 strategies on TEST_YEARS → profit / yield / water / leaching table.

Writes ``runs/paper_tables/table_exp1_strategies.{json,md,png}``.

Reuse ``--cache`` JSON from a prior partial run to skip measured/default/fixed/controller.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

from swat_gym.env import N_YEARS, SPINUP, time_sim
from swat_gym.experiments._focused import _row, mean
from swat_gym.experiments.exp1_controller import rollout_controller
from swat_gym.experiments.exp1_irrigation import score_month_plan
from swat_gym.fastrunner import FastRunner
from swat_gym.monthly import default_monthly_i_free, evaluate_monthly_i
from swat_gym.monthly_env import MonthlySwatEnv
from swat_gym.rewarders import average, profit as profit_fn
from swat_gym.windows import TEST_YEARS, TRAIN_YEARS

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = RUNS / "paper_tables"


def _agg(rows: list[dict], yields: list[float]) -> dict:
    return {
        "profit": float(np.mean([r["profit"] for r in rows])),
        "irrigation_mm": float(np.mean([r["irrigation_mm"] for r in rows])),
        "no3_kg": float(np.mean([r["no3"] for r in rows])),
        "yield_mg": float(np.mean(yields)),
        "n": len(rows),
    }


def score_measured(test, prices, no3_price):
    rows, ylds = [], []
    with FastRunner() as runner:
        for sy in test:
            runner.run({"time.sim": time_sim(sy, N_YEARS + SPINUP)})
            d = profit_fn(runner, prices, no3_price=no3_price)
            y = runner.yields()
            rows.append(_row(d, sy))
            ylds.append(float(y["yld(t)"].sum()) if len(y) else 0.0)
            print(f"  measured {sy} profit={d['profit']:.0f}", flush=True)
    return _agg(rows, ylds)


def score_openloop(x, test, prices, no3_price, label: str, max_n=None):
    rows, ylds = [], []
    with FastRunner() as runner:
        for sy in test:
            d = evaluate_monthly_i(x, runner, prices=prices, start_year=sy,
                                   no3_price=no3_price, max_n=max_n)
            y = runner.yields()
            rows.append(_row(d, sy))
            ylds.append(float(y["yld(t)"].sum()) if len(y) else 0.0)
            print(f"  {label} {sy} profit={d['profit']:.0f}", flush=True)
    return _agg(rows, ylds)


def score_controller(abc, test, prices, no3_price):
    rows, ylds = [], []
    with FastRunner() as runner:
        for sy in test:
            d = rollout_controller(abc, runner, start_year=sy, prices=prices,
                                   no3_price=no3_price)
            y = runner.yields()
            rows.append(_row(d, sy))
            ylds.append(float(y["yld(t)"].sum()) if len(y) else 0.0)
            print(f"  controller {sy} profit={d['profit']:.0f}", flush=True)
    return _agg(rows, ylds)


def score_policy(model, test, prices, no3_price, label: str = "policy"):
    rows, ylds, plans = [], [], {}
    with MonthlySwatEnv(stochastic_weather=False, prices=prices, no3_price=no3_price,
                        arm="I", max_n=None) as env:
        for sy in test:
            obs, _ = env.reset(start_year=sy)
            done = False
            info: dict = {}
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, term, trunc, info = env.step(action)
                done = bool(term or trunc)
            y = env.runner.yields()
            rows.append(_row(info, sy))
            ylds.append(float(y["yld(t)"].sum()) if len(y) else 0.0)
            plans[sy] = env.month_mm.copy()
            print(f"  {label} {sy} profit={info['profit']:.0f}", flush=True)
    return _agg(rows, ylds), plans


def write_outputs(payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "table_exp1_strategies.json").write_text(json.dumps(payload, indent=2))
    strategies = payload["strategies"]
    rep = payload["representative_seed"]

    headers = [
        "Strategy", "Profit ($/ha)", "Yield (Mg/ha)", "Water (mm)",
        "NO₃ leaching (kg N/ha)",
    ]
    best_p = max(s["profit"] for s in strategies)
    best_y = max(s["yield_mg"] for s in strategies)
    best_w = min(s["irrigation_mm"] for s in strategies)
    best_n = min(s["no3_kg"] for s in strategies)

    def fmt(v, digits, is_best):
        s = f"{v:,.{digits}f}"
        return f"**{s}**" if is_best else s

    lines = [
        "**Table. Exp 1 strategies on held-out test windows (2013–2017 means).**",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for s in strategies:
        lines.append("| " + " | ".join([
            s["strategy"],
            fmt(s["profit"], 0, abs(s["profit"] - best_p) < 1e-6),
            fmt(s["yield_mg"], 1, abs(s["yield_mg"] - best_y) < 1e-9),
            fmt(s["irrigation_mm"], 0, abs(s["irrigation_mm"] - best_w) < 1e-6),
            fmt(s["no3_kg"], 2, abs(s["no3_kg"] - best_n) < 1e-9),
        ]) + " |")
    lines += [
        "",
        "Means over five test start years. Yield is rotation-total dry matter (Mg/ha). "
        f"PPO/frozen use representative seed {rep}. Bold = best in column "
        "(highest profit/yield; lowest water/leaching).",
        "",
    ]
    (OUT / "table_exp1_strategies.md").write_text("\n".join(lines))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "paper_tables", ROOT / "scripts" / "paper_tables.py")
    paper_tables = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(paper_tables)
    save_table_png = paper_tables.save_table_png
    rows = []
    for s in strategies:
        row = [
            s["strategy"],
            f"{s['profit']:,.0f}",
            f"{s['yield_mg']:.1f}",
            f"{s['irrigation_mm']:,.0f}",
            f"{s['no3_kg']:.2f}",
        ]
        if abs(s["profit"] - best_p) < 1e-6:
            row[1] += "*"
        if abs(s["yield_mg"] - best_y) < 1e-9:
            row[2] += "*"
        if abs(s["irrigation_mm"] - best_w) < 1e-6:
            row[3] += "*"
        if abs(s["no3_kg"] - best_n) < 1e-9:
            row[4] += "*"
        rows.append(row)
    save_table_png(
        OUT / "table_exp1_strategies.png",
        "Exp 1 strategies — test means (2013–2017)",
        headers,
        rows,
        note="* = best in column (max profit/yield; min water/leaching). "
             f"PPO seed {rep}; frozen plan selected on train.",
    )
    print(f"-> {OUT / 'table_exp1_strategies.json'}", flush=True)
    print(f"-> {OUT / 'table_exp1_strategies.md'}", flush=True)
    print(f"-> {OUT / 'table_exp1_strategies.png'}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-openloop", action="store_true",
                    help="reuse open-loop/controller numbers baked into this script "
                         "from the earlier successful partial run")
    args = ap.parse_args()

    prices = average()
    no3_price = 0.0
    test = list(TEST_YEARS)
    train = list(TRAIN_YEARS)
    full = json.loads((RUNS / "exp1_irrigation.json").read_text())
    ctrl = json.loads((RUNS / "exp1_controller.json").read_text())
    rep = int(full["representative_seed"])
    fixed_x = np.asarray(full["fixed_x"], dtype=float)
    default_x = default_monthly_i_free()
    abc = ctrl["abc"]

    if args.skip_openloop:
        # The cached numbers that used to live here were produced under the nitrogen-cap
        # confound (open-loop arms capped at 400 kg N/ha, policy arm uncapped) and are wrong
        # by up to 1,600 $/ha. Rather than ship a stale cache, refuse.
        raise SystemExit(
            "--skip-openloop is disabled: its cached rows predate the max_n fix "
            "(see runs/archive/capped_20260806/README.md). Re-score from scratch.")
    else:
        print("=== measured ===", flush=True)
        measured = score_measured(test, prices, no3_price)
        print("=== monthly default ===", flush=True)
        default = score_openloop(default_x, test, prices, no3_price, "default")
        print("=== CMA open-loop ===", flush=True)
        fixed = score_openloop(fixed_x, test, prices, no3_price, "fixed")
        print("=== controller ===", flush=True)
        controller = score_controller(abc, test, prices, no3_price)

    print(f"=== PPO seed {rep} ===", flush=True)
    model = PPO.load(str(RUNS / f"exp1_irrigation_ppo_s{rep}.zip"))
    policy, _ = score_policy(model, test, prices, no3_price, "policy")

    print("=== frozen (train-selected) ===", flush=True)
    with MonthlySwatEnv(stochastic_weather=False, prices=prices, no3_price=no3_price,
                        arm="I", max_n=None) as env:
        plans_tr = {}
        for sy in train:
            obs, _ = env.reset(start_year=sy)
            done = False
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, _, term, trunc, _ = env.step(action)
                done = bool(term or trunc)
            plans_tr[sy] = env.month_mm.copy()
            print(f"  collected train plan {sy}", flush=True)

    fz_tr = {
        sy: score_month_plan(mm, train, prices, no3_price, None)
        for sy, mm in plans_tr.items()
    }
    best = max(fz_tr, key=lambda sy: mean(fz_tr[sy]))
    print(f"  best frozen train window={best} "
          f"train_profit={mean(fz_tr[best]):.0f}", flush=True)
    from swat_gym.monthly import encode_monthly_depths
    frozen = score_openloop(encode_monthly_depths(plans_tr[best]), test, prices,
                            no3_price, "frozen")

    strategies = [
        {"strategy": "Measured practice", **measured},
        {"strategy": "Generated monthly default", **default},
        {"strategy": "CMA-ES open-loop", **fixed},
        {"strategy": "CMA feedback controller", **controller},
        {"strategy": f"PPO policy (seed {rep})", **policy},
        {"strategy": "Frozen plan (train-selected)", **frozen},
    ]
    payload = {
        "test_years": test,
        "representative_seed": rep,
        "best_frozen_train_year": int(best),
        "strategies": strategies,
    }
    write_outputs(payload)


if __name__ == "__main__":
    main()
