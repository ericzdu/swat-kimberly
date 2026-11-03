#!/usr/bin/env python3
"""Algorithm comparison page (runs/ltm_algos_<strategy>.json -> runs/ltm_algos.html).

    uv run python scripts/ltm_algos_report.py                    # balanced
    uv run python scripts/ltm_algos_report.py --tag ltm_algos_balanced_smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import ltm_figures as F  # noqa: E402
import ltm_nutrient_summary as NS  # noqa: E402
from swat_gym.ltm.practice import decisions, irr_cap  # noqa: E402

RUNS = ROOT / "runs"
RESULTS_URL = "https://claude.ai/artifact/TtjHzAS9r4VMHsqkCRgwWx"
CALIB_URL = NS.__dict__.get("CALIB_URL", "https://claude.ai/artifact/T4YMKqwDrAnKx22HBfSRAW")
#: categorical slots 1-7 in fixed order (validated: dataviz validate_palette.js, light)
ALGOS = {"es": ("ES", "#2a78d6"), "ga": ("GA", "#eb6834"), "ppo": ("PPO", "#1baf7a"),
         "sac": ("SAC", "#eda100"), "cma": ("CMA-ES", "#e87ba4"), "ga_open": ("GA, open loop", "#008300"),
         "random": ("Random search", "#6250d6")}
CLOSED = ("es", "ga", "ppo", "sac")
FAMILY = {a: ("closed loop" if a in CLOSED else "open loop") for a in ALGOS}
DASH = {a: ("" if a in CLOSED else "6 4") for a in ALGOS}
BASE = {"measured": ("Measured practice", F.TRIAL, ""), "default": ("Default", F.DEFAULT, "6 4"),
        "auto": ("Auto-irrigation", F.DEFAULT, "2 3")}
TERMS = (("ry", "Relative yield", "", 3, True), ("no3", "NO₃-N leached", "kg/ha/yr", 1, False),
         ("water", "Gross irrigation", "mm/yr", 0, False), ("p", "P loss + buildup", "kg/ha/yr", 1, False),
         ("n2o", "N₂O (Tier 1)", "kg/ha/yr", 2, False))
esc = NS.esc


def kv(d: dict) -> str:
    """A settings dict as readable text."""
    return esc("; ".join(f"{k.replace('_', ' ')} {v}" for k, v in d.items()))


def f(x, nd=3, sign=False):
    return "–" if x is None else (f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}")


def ci(c, nd=3):
    lo, hi = c["ci95_ess"]
    return f"{f(c['mean'], nd, True)} [{f(lo, nd, True)}, {f(hi, nd, True)}]"


def verdict(c):
    lo, hi = c["ci95_ess"]
    return "better" if lo > 0 else "worse" if hi < 0 else "unresolved"


# -- figures ----------------------------------------------------------------------------------

def bars(D, key, title, unit, nd, w=960, h=260, lines=True):
    """One bar per algorithm (mean of seeds) with seed dots; baselines as horizontal lines."""
    algos = [a for a in ALGOS if a in D["algos"]]
    vals = {a: [r["test_means"][key] for r in D["algos"][a]] for a in algos}
    base = {b: D["baselines"][b][key] for b in BASE}
    allv = [v for vs in vals.values() for v in vs] + list(base.values()) + [0.0]
    yt = F.ticks(min(allv), max(allv) * 1.05 if max(allv) > 0 else 0.0)
    left, top = 70, 30
    ax = F.Axes(left, top, w - left - 170, h - top - 46, (0, len(algos)), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", unit, yfmt=lambda v: f"{v:g}")]
    gw = ax.w / len(algos)
    for i, a in enumerate(algos):
        name, col = ALGOS[a]
        m = float(np.mean(vals[a]))
        x0, bw = ax.x0 + i * gw + gw * 0.2, gw * 0.6
        y0, y1 = ax.y(0), ax.y(m)
        body.append(f'<rect x="{x0:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" height="{abs(y0 - y1):.1f}" '
                    f'rx="3" fill="{col}" fill-opacity="{1.0 if a in CLOSED else 0.55}">'
                    f'<title>{esc(name)}, mean of seeds: {m:,.{nd}f} {esc(unit)}</title></rect>')
        for j, v in enumerate(vals[a]):
            cx = x0 + bw * (j + 0.5) / len(vals[a])
            body.append(f'<circle cx="{cx:.1f}" cy="{ax.y(v):.1f}" r="3.5" fill="{F.INK}" stroke="#fff" '
                        f'stroke-width="1.5"><title>{esc(name)}, seed {D["algos"][a][j]["seed"]}: '
                        f'{v:,.{nd}f}</title></circle>')
        body.append(F.text(x0 + bw / 2, ax.y0 + ax.h + 15, name, 11, "middle", F.INK))
        body.append(F.text(x0 + bw / 2, ax.y0 + ax.h + 29, FAMILY[a], 10, "middle", F.INK2))
    if lines:
        placed = []
        for b, (lab, col, dash) in BASE.items():
            y = ax.y(base[b])
            body.append(f'<line x1="{ax.x0}" x2="{ax.x0 + ax.w}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" '
                        f'stroke-width="1.5" stroke-dasharray="{dash}"><title>{lab}: {base[b]:,.{nd}f}</title></line>')
            ty = y + 4
            while any(abs(ty - p) < 12 for p in placed):
                ty += 12
            placed.append(ty)
            body.append(F.text(ax.x0 + ax.w + 6, ty, f"{lab} {base[b]:,.{nd}f}", 11, color=F.INK2))
    body.append(f'<line x1="{ax.x0}" x2="{ax.x0 + ax.w}" y1="{ax.y(0):.1f}" y2="{ax.y(0):.1f}" '
                f'stroke="{F.INK2}" stroke-width="1"/>')
    return F.svg(w, h, "".join(body), title)


def curves(D, algos, title, ylim, w=960, h=300):
    """Train score of each algorithm's current pick against HRU runs spent: thin line per seed,
    thick line for the median across seeds."""
    left, top = 70, 30
    budget = D["config"]["budget"]
    xt = F.ticks(0, budget, 6)
    yt = F.ticks(*ylim, 6)
    ax = F.Axes(left, top, w - left - 150, h - top - 46, (0, xt[-1]), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid(xt, yt, "HRU-episode steps spent", "Train score",
                    xfmt=lambda v: f"{v / 1000:g}k", yfmt=lambda v: f"{v:.2f}")]
    grid = np.linspace(0, budget, 120)
    ends = []
    for a in algos:
        name, col = ALGOS[a]
        meds = []
        for r in D["algos"][a]:
            c = r["curve"]
            xs, ys = [p["hru_runs"] for p in c], [p["train_score"] for p in c]
            body.append(f'<polyline fill="none" stroke="{col}" stroke-width="1" stroke-opacity="0.45" '
                        f'stroke-dasharray="{DASH[a]}" points="'
                        + " ".join(f"{ax.x(x):.1f},{ax.y(min(max(y, yt[0]), yt[-1])):.1f}" for x, y in zip(xs, ys))
                        + f'"><title>{esc(name)}, seed {r["seed"]}</title></polyline>')
            meds.append(np.interp(grid, xs, ys, left=np.nan, right=ys[-1]))
        med = np.nanmedian(np.array(meds), axis=0)
        ok = ~np.isnan(med)
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.5" stroke-dasharray="{DASH[a]}" points="'
                    + " ".join(f"{ax.x(x):.1f},{ax.y(min(max(y, yt[0]), yt[-1])):.1f}" for x, y in zip(grid[ok], med[ok]))
                    + f'"><title>{esc(name)}, median of seeds; final {med[ok][-1]:.3f}</title></polyline>')
        ends.append([ax.y(min(max(med[ok][-1], yt[0]), yt[-1])), name, col, med[ok][-1]])
    ends.sort()
    for i in range(1, len(ends)):                       # direct labels, nudged apart
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 13)
    for y, name, col, v in ends:
        body.append(F.text(ax.x0 + ax.w + 8, y + 4, f"{name} {v:.3f}", 11, color=F.INK))
    return F.svg(w, h, "".join(body), title)


def forest(D, key, title, left_lab, right_lab, algos, w=960):
    rows = [(a, r) for a in algos for r in D["algos"][a] if key in r]
    left, top, row_h = 200, 52, 16
    allv = [x for _, r in rows for x in r[key]["score"]["ci95_ess"]] + [0.0]
    lo, hi = min(allv), max(allv)
    pad = 0.08 * (hi - lo or 1)
    xt = F.ticks(lo - pad, hi + pad, 7)
    nd = 2 if xt[1] - xt[0] >= 0.01 else 3
    H = top + row_h * len(rows) + 46
    ax = F.Axes(left, top, w - left - 30, row_h * len(rows), (xt[0], xt[-1]), (0, 1))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid(xt, None, "Score difference on the test windows", "", xfmt=lambda v: f"{v:+.{nd}f}"),
            F.text(ax.x(0) - 6, top - 8, left_lab, 11, "end", F.INK2),
            F.text(ax.x(0) + 6, top - 8, right_lab, 11, "start", F.INK2),
            f'<line x1="{ax.x(0):.1f}" x2="{ax.x(0):.1f}" y1="{top}" y2="{top + row_h * len(rows)}" '
            f'stroke="{F.INK}" stroke-width="1.5"/>']
    for i, (a, r) in enumerate(rows):
        name, col = ALGOS[a]
        y = top + i * row_h + row_h / 2
        c = r[key]["score"]
        lo_, hi_ = c["ci95_ess"]
        if i == 0 or rows[i - 1][0] != a:
            body.append(F.text(left - 10, y + 4, name, 12, "end"))
            if i:
                body.append(f'<line x1="20" x2="{ax.x0 + ax.w}" y1="{y - row_h / 2:.1f}" y2="{y - row_h / 2:.1f}" '
                            f'stroke="{F.GRID}" stroke-width="1"/>')
        tip = f"<title>{esc(name)}, seed {r['seed']}: {c['mean']:+.3f} [{lo_:+.3f}, {hi_:+.3f}]</title>"
        body.append(f'<line x1="{ax.x(lo_):.1f}" x2="{ax.x(hi_):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" '
                    f'stroke-width="2" stroke-linecap="round">{tip}</line>')
        body.append(f'<circle cx="{ax.x(c["mean"]):.1f}" cy="{y:.1f}" r="4" fill="{col}" stroke="#fff" '
                    f'stroke-width="1">{tip}</circle>')
    return F.svg(w, H, "".join(body), title)


def schedule_mm(x):
    """Decision vector -> scheduled gross depth per decision (mm), with each decision's label."""
    caps = irr_cap()
    return [float(v) * caps.get(d.mon, 0.0) for v, d in zip(x, decisions("I"))]


def schedule_panel(D, a, window, title, w=960, h=170, ymax=None):
    """Scheduled monthly depth on one window: each seed of ``a`` against measured practice."""
    ds = decisions("I")
    left, top = 70, 26
    n = len(ds)
    meas = schedule_mm(D["baseline_x"])
    seeds = [schedule_mm(r["test_x"][str(window)]) for r in D["algos"][a]]
    yt = F.ticks(0, ymax or max(max(meas), max(max(s) for s in seeds)) * 1.05, 4)
    ax = F.Axes(left, top, w - left - 20, h - top - 34, (0, n), (0, yt[-1]))
    name, col = ALGOS[a]
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", "mm/month")]
    gw = ax.w / n
    for i, (d, v) in enumerate(zip(ds, meas)):
        body.append(f'<rect x="{ax.x0 + i * gw + 1:.1f}" y="{ax.y(v):.1f}" width="{gw - 2:.1f}" '
                    f'height="{ax.y(0) - ax.y(v):.1f}" fill="#e4e3df"><title>{window + d.k} month {d.mon}, '
                    f'measured: {v:.0f} mm</title></rect>')
        if i == 0 or ds[i - 1].k != d.k:
            x = ax.x0 + i * gw
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ax.y0}" y2="{ax.y0 + ax.h}" stroke="{F.INK2}" '
                        f'stroke-width="0.75"/>')
            body.append(F.text(x + 3, ax.y0 + ax.h + 14, str(window + d.k), 11, color=F.INK2))
    dashes = ["", "6 3", "2 2", "8 3 2 3"]
    for j, s in enumerate(seeds):
        pts = " ".join(f"{ax.x0 + (i + 0.5) * gw:.1f},{ax.y(v):.1f}" for i, v in enumerate(s))
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.75" stroke-dasharray="{dashes[j % 4]}" '
                    f'points="{pts}"><title>{esc(name)}, seed {D["algos"][a][j]["seed"]}</title></polyline>')
    return F.svg(w, h, "".join(body), title)


def reaction_panel(D, a, title, w=470, h=200):
    """Seasonal scheduled depth on every test window, for the algorithm's best-train seed:
    one line per window. Identical lines = the schedule ignores the weather and soil state."""
    ds = decisions("I")
    r = max(D["algos"][a], key=lambda r: r["picked_train_score"])
    wins = sorted(r["test_x"], key=int)
    seas = sorted({d.k for d in ds})
    tot = {wn: [sum(v for v, d in zip(schedule_mm(r["test_x"][wn]), ds) if d.k == k) for k in seas]
           for wn in wins}
    left, top = 60, 26
    allv = [v for t in tot.values() for v in t]
    yt = F.ticks(0, max(allv) * 1.08, 4)
    ax = F.Axes(left, top, w - left - 14, h - top - 34, (0.5, len(seas) + 0.5), (0, yt[-1]))
    name, col = ALGOS[a]
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid([k for k in seas], yt, "", "mm/season", xfmt=lambda v: f"S{int(v)}")]
    for wn in wins:
        pts = " ".join(f"{ax.x(k):.1f},{ax.y(v):.1f}" for k, v in zip(seas, tot[wn]))
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.5" stroke-opacity="0.8" '
                    f'points="{pts}"><title>{esc(name)}, test window {wn}–{int(wn) + 8}</title></polyline>')
    return F.svg(w, h, "".join(body), title)


# -- page -------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="ltm_algos_balanced")
    ap.add_argument("--out", default=str(RUNS / "ltm_algos.html"))
    args = ap.parse_args()
    D = json.loads((RUNS / f"{args.tag}.json").read_text())
    cfg = D["config"]
    algos = [a for a in ALGOS if a in D["algos"]]
    closed = [a for a in algos if a in CLOSED]
    n_fig, n_tab = [0], [0]

    def fig(title, body, caption=""):
        n_fig[0] += 1
        return (f'<figure><div class="ftitle"><b>Figure {n_fig[0]}.</b> {title}</div>{body}'
                + (f"<figcaption>{caption}</figcaption>" if caption else "") + "</figure>")

    def tab(title, body, note=""):
        n_tab[0] += 1
        return (f'<div class="ttitle"><b>Table {n_tab[0]}.</b> {title}</div>'
                + (f'<div class="tnote">{note}</div>' if note else "") + body)

    mean = lambda a, k: float(np.mean([r["test_means"][k] for r in D["algos"][a]]))  # noqa: E731
    best_open = max((a for a in algos if a not in CLOSED), key=lambda a: mean(a, "score"), default=None)
    best_closed = max(closed, key=lambda a: mean(a, "score"), default=None)
    vs_cma = {a: [verdict(r["vs_cma_same_seed"]["score"]) for r in D["algos"][a] if "vs_cma_same_seed" in r]
              for a in algos if a != "cma"}
    adapt = [r["adaptivity"]["score"] for a in closed for r in D["algos"][a]]
    adapt_res = sum(verdict(c) != "unresolved" for c in adapt)
    adapt_max = max((abs(c["mean"]) for c in adapt), default=0.0)

    meas_s = D["baselines"]["measured"]["score"]
    find = ["<h2>Key findings</h2><ul>"]
    if best_closed and best_open:
        find.append(f"<li><b>Best closed-loop learner: {ALGOS[best_closed][0]}</b> "
                    f"(test score {mean(best_closed, 'score'):.3f}, mean of seeds). <b>Best open-loop "
                    f"search: {ALGOS[best_open][0]}</b> ({mean(best_open, 'score'):.3f}). Measured practice "
                    f"scores {meas_s:.3f}.</li>")
    for a in algos:
        if a == "cma" or a not in vs_cma:
            continue
        v = vs_cma[a]
        find.append(f"<li>{ALGOS[a][0]} against CMA-ES (same seed): better in {v.count('better')}, "
                    f"worse in {v.count('worse')}, unresolved in {v.count('unresolved')} of {len(v)} seeds.</li>")
    if adapt:
        spread = {a: np.mean([r["x_spread_across_test_windows"] for r in D["algos"][a]]) for a in closed}
        find.append(f"<li><b>Value of adapting.</b> Every closed-loop policy scores within {adapt_max:.3f} of "
                    f"its own frozen (open-loop) plan; {adapt_res} of {len(adapt)} differences are resolvable "
                    "(Figure 5). The policies do change their schedules between weather windows (mean spread "
                    + ", ".join(f"{ALGOS[a][0]} {spread[a]:.3f}" for a in closed)
                    + " on the unit-box scale; Figure 7), but the changes do not raise the score.</li>")
    first_best = [a for a in closed
                  if all(int(np.argmax([p["train_score"] for p in r["curve"]])) == 0 for r in D["algos"][a])]
    for a in first_best:
        find.append(f"<li><b>{ALGOS[a][0]} got worse with training.</b> For every seed the best snapshot was the "
                    "first one; later snapshots score lower on the train windows (Figure 2A), so the picked "
                    "policy is close to its starting point.</li>")
    find.append("</ul>")

    head = ("<h1>Irrigation scheduling: reinforcement learning and search algorithms compared</h1>"
            "<p>Exp 3 of the <a href=\"" + RESULTS_URL + "\">LTM experiments</a> (monthly irrigation depths "
            f"for all 8 seasons, {len(decisions('I'))} decisions, application efficiency "
            f"{cfg['irr_eff']:.0%}), rerun with seven algorithms on the <b>{cfg['strategy']}</b> strategy "
            f"(w = {cfg['w']:g}). Each algorithm gets {len(cfg['seeds'])} seeds and "
            f"{cfg['budget']:,} HRU-episode steps per seed (3 × the v6 runs), is selected on the 7 train "
            f"windows (1995–2009) and scored on the 7 test windows (2011–2025; effective sample size "
            f"{cfg['test_ess']:.2f}). The model and its calibration are on the "
            f"<a href=\"{CALIB_URL}\">calibration page</a>.</p>"
            "<p><b>Two families.</b> A <b>closed-loop</b> method trains a policy: a 64×64 neural network "
            "that reads the soil water, nitrate and P, last month's weather and the season before each "
            "monthly decision and outputs that month's depth (as a change from measured practice). This "
            "is the reinforcement-learning setting, and the only one that can react to the year it is in. "
            "An <b>open-loop</b> method searches directly for one fixed 40-month schedule and applies it in "
            "every weather window. Table 1 describes each algorithm.</p>")
    intro_rows = [
        ["PPO", "Closed loop", "Gradient-based deep RL (on-policy)",
         "Runs 16 episodes, then updates the policy by gradient ascent on the episode reward, using a "
         "learned value function to judge each decision; a clipped update keeps each step small.",
         "The standard deep-RL baseline; stable but needs many episodes."],
        ["SAC", "Closed loop", "Gradient-based deep RL (off-policy)",
         "Stores every decision in a replay buffer and repeatedly learns from it; maximises reward plus the "
         "policy's randomness (entropy), so it keeps exploring.",
         "Usually the most sample-efficient deep-RL method for continuous actions; sensitive to settings "
         "when the reward comes only at the end of the episode, as here."],
        ["ES", "Closed loop", "Evolution strategies (gradient-free)",
         "Tries 16 random perturbations of the network's weights, scores each by whole-episode reward and "
         "moves the weights toward the better ones (OpenAI-ES).",
         "The method used in the v6 experiments; needs no gradients or value function."],
        ["GA", "Closed loop", "Genetic algorithm (gradient-free)",
         "Keeps a population of 16 networks; each generation the best 4 are mutated with random noise to "
         "make the next generation, and the best one is kept unchanged.",
         "The simplest neuroevolution method; a check on whether ES's update rule matters."],
        ["CMA-ES", "Open loop", "Evolution strategy on the schedule",
         "Samples schedules from a multivariate normal distribution, then shifts and reshapes the "
         "distribution toward the best ones; starts from measured practice.",
         "The v6 'best fixed plan' optimiser; stops on its own once it converges."],
        ["GA, open loop", "Open loop", "Genetic algorithm on the schedule",
         "Keeps a population of 16 schedules; combines pairs of good schedules (blend crossover) and "
         "occasionally perturbs single months (mutation).",
         "A second open-loop optimiser, to check that CMA-ES's result is not specific to CMA-ES."],
        ["Random search", "Open loop", "Baseline",
         "Draws schedules uniformly at random and keeps the best.",
         "The floor: what the budget buys with no learning at all."],
    ]
    algo_table = tab("The seven algorithms",
                     NS.table(["Algorithm", "Family", "Kind", "How it learns or searches", "Why it is here"],
                              intro_rows, left=5),
                     f"Each gets {len(cfg['seeds'])} seeds and {cfg['budget']:,} simulated decision steps per "
                     "seed. All are selected on the train windows and scored on the test windows. Settings "
                     "are listed at the end of the page.")
    failed = ("<p><b>Failed jobs:</b> " + ", ".join(esc(k) for k in D["failed"]) + ". They are left out.</p>"
              if D.get("failed") else "")

    # Figure 1: scores; Figure 2: curves
    scores = fig("Test-window strategy score by algorithm",
                 bars(D, "score", "Balanced strategy score (higher is better)", "Score", 3),
                 "Bar = mean of the seeds, black dots = individual seeds. Solid bars are closed-loop "
                 "policies, pale bars open-loop schedules. Horizontal lines: the three practice baselines. "
                 "Hover for values.")
    ys = [p["train_score"] for a in algos for r in D["algos"][a] for p in r["curve"]]
    lo = float(np.percentile(ys, 2))
    ylim = (min(lo, meas_s), max(ys))
    curve_fig = fig("Learning curves on the train windows",
                    curves(D, closed, "A. Closed loop", ylim)
                    + curves(D, [a for a in algos if a not in CLOSED], "B. Open loop", ylim),
                    "Train score of each algorithm's current best solution against the budget spent. "
                    "Thin lines = seeds, thick = median across seeds; solid = closed loop, dashed = open "
                    "loop. ES and PPO/SAC are scored at 8 snapshots, the others after every generation. "
                    "Both panels share the y scale; scores below it are drawn at its floor.")
    terms = fig("Relative yield and the four sustainability terms by algorithm", "".join(
        bars(D, k, f"{'ABCDE'[i]}. {lab}" + (" (higher is better)" if hb else " (lower is better)"),
             unit or lab, nd, h=230)
        for i, (k, lab, unit, nd, hb) in enumerate(TERMS)),
        "Test-window means per ha per year. Leaching is not validated on site; N₂O is IPCC Tier 1 "
        "accounting, not simulated.")
    vs = fig("Each seed against CMA-ES and against measured practice",
             forest(D, "vs_cma_same_seed", "A. Algorithm − CMA-ES (same seed)", "← CMA-ES better",
                    "algorithm better →", [a for a in algos if a != "cma"])
             + forest(D, "vs_measured", "B. Algorithm − measured practice", "← practice better",
                      "algorithm better →", algos),
             "Dot = mean paired difference over the 7 test windows, bar = ESS-based 95 % interval. "
             "An interval crossing zero is unresolved.")
    adapt_fig = fig("Value of adapting: each closed-loop policy against its own frozen plan",
                    forest(D, "adaptivity", "Policy − frozen plan", "← frozen better",
                           "closed loop better →", closed),
                    "The frozen plan is the policy's mean decision on the train windows, applied open loop. "
                    "A policy that reacts to the soil state and weather would beat it.")
    # policies
    win = 2012
    ymax = max([max(schedule_mm(D["baseline_x"]))]
               + [max(schedule_mm(r["test_x"][str(win)])) for a in algos for r in D["algos"][a]]) * 1.05
    sched = fig("The learned schedules on the trial's weather (test window 2012, seasons 2013–2020)",
                NS.legend_row([("measured practice", "#e4e3df", "square")], "Bars:")
                + NS.line_legend([("seed 0", F.INK, ""), ("seed 100", F.INK, "6 3"), ("seed 200", F.INK, "2 2"),
                                  ("seed 300", F.INK, "8 3 2 3")], "Lines (one per seed):")
                + "".join(schedule_panel(D, a, win, f"{'ABCDEFG'[i]}. {ALGOS[a][0]} ({FAMILY[a]})", ymax=ymax)
                          for i, a in enumerate(algos)),
                "Scheduled gross depth for each irrigable month, by season (vertical lines). All panels "
                "share the y scale. Hover a line or bar for its values.")
    react = fig("Does the schedule change with the weather? Seasonal depth on each test window",
                "".join(reaction_panel(D, a, f"{'ABCDEFG'[i]}. {ALGOS[a][0]}") for i, a in enumerate(algos)),
                "Best-train seed of each algorithm; one line per test window (seasons S1–S8 of that "
                "window). Open-loop schedules are identical on every window by construction; a closed-loop "
                "policy whose lines coincide has learned a fixed schedule.")

    # tables
    rows = []
    for a in algos:
        rs = D["algos"][a]
        sc = [r["test_means"]["score"] for r in rs]
        v = vs_cma.get(a, [])
        ad = [r["adaptivity"]["score"]["mean"] for r in rs if "adaptivity" in r]
        rows.append([esc(ALGOS[a][0]), FAMILY[a], f"{np.mean(sc):.3f}", f"{min(sc):.3f} to {max(sc):.3f}",
                     f"{mean(a, 'ry'):.3f}", f"{mean(a, 'no3'):.1f}", f"{mean(a, 'water'):.0f}",
                     f"{v.count('better')} / {v.count('worse')} / {len(v)}" if v else "–",
                     f"{min(ad):+.3f} to {max(ad):+.3f}" if ad else "–",
                     f"{np.mean([r['x_spread_across_test_windows'] for r in rs]):.3f}" if ad else "0",
                     f"{np.mean([r['seconds'] for r in rs]) / 60:.0f}"])
    for b, (lab, _, _) in BASE.items():
        m = D["baselines"][b]
        rows.append([esc(lab), "practice", f"{m['score']:.3f}", "–", f"{m['ry']:.3f}", f"{m['no3']:.1f}",
                     f"{m['water']:.0f}", "–", "–", "–", "–"])
    t1 = tab("Test-window results by algorithm, balanced strategy",
             NS.table(["Algorithm", "Family", "Mean", "Range", "Relative yield", "NO₃-N, kg/ha/yr",
                       "Water, mm/yr", "Better / worse / seeds", "Policy − frozen",
                       "Schedule spread", "Minutes per seed"], rows,
                      groups=[("", 2), ("Strategy score", 2), ("Means of the seeds", 3),
                              ("Against CMA-ES", 1), ("Adaptation", 2), ("", 1)], left=2),
             "Better/worse = the same-seed paired difference's ESS interval excludes zero. Schedule "
             "spread = standard deviation of each decision across the 7 test windows (unit-box scale, "
             "mean over decisions); 0 means one fixed schedule.")
    seed_rows = []
    for a in algos:
        for r in D["algos"][a]:
            seed_rows.append([esc(ALGOS[a][0]), r["seed"], f"{r['picked_train_score']:.3f}",
                              f"{r['test_means']['score']:.3f}", ci(r["vs_measured"]["score"]),
                              ci(r["vs_cma_same_seed"]["score"]) if "vs_cma_same_seed" in r else "–",
                              ci(r["adaptivity"]["score"]) if "adaptivity" in r else "–",
                              f"{r['hru_runs']:,}", f"{r['seconds'] / 60:.0f}"])
    t2 = tab("Every seed", "<details><summary>Show the table</summary>" + NS.table(
        ["Algorithm", "Seed", "Train score", "Test score", "− measured [95 % CI]", "− CMA-ES [95 % CI]",
         "− frozen plan [95 % CI]", "HRU runs", "Minutes"], seed_rows, merge_first=True, left=2) + "</details>")

    hp = D["config"]["algos"]
    settings = ("<h2>Settings</h2><ul>"
                f"<li>Budget: {cfg['budget']:,} HRU-episode steps per seed, counting snapshot selection; "
                "a closed-loop episode costs 40 steps (one per decision), an open-loop evaluation one per "
                "window. CMA-ES finishes its last generation and may exceed the budget slightly.</li>"
                f"<li>ES: population {hp['es']['population']}, σ {hp['es']['sigma']}, Adam lr {hp['es']['lr']}, "
                "all 7 train windows each generation.</li>"
                f"<li>GA (closed loop): population {hp['ga']['population']}, top {hp['ga']['parents']} parents, "
                f"1 elite, mutation σ {hp['ga']['sigma']}, no crossover.</li>"
                f"<li>PPO: {kv(hp['sb3']['ppo'])}. SAC: {kv(hp['sb3']['sac'])}. Both: {hp['sb3']['n_envs']} "
                "environments in one engine run per step, γ = 1, sparse terminal reward, best of 8 snapshots "
                "on all train windows.</li>"
                f"<li>GA (open loop): {kv(hp['ga_open'])}. Random search: {kv(hp['random'])}.</li>"
                "<li>Every closed-loop policy acts as a residual around measured practice, so a zero output "
                "replays the trial; the open-loop CMA-ES and GA start from measured practice.</li></ul>")
    bounds = ("<h2>Bounds</h2><ul><li>One strategy (balanced) and one efficiency (80 %); the v6 page covers "
              "the others with ES and CMA-ES.</li><li>Hyperparameters are standard defaults, not tuned per "
              "algorithm; a tuned PPO or SAC could do better.</li>"
              f"<li>The test set's effective sample size is {cfg['test_ess']:.2f}: small differences are "
              "unresolved by design.</li><li>Leaching is not validated on site; N₂O is IPCC Tier 1 "
              "accounting.</li></ul>")
    style = ("<style>body{font-family:Calibri,sans-serif;background:#fff;color:#000;margin:24px;max-width:1000px}"
             "table{border-collapse:collapse;font-size:13px;margin:8px 0}"
             "th,td{border:1px solid #ccc;padding:2px 6px;text-align:right}th.l,td.l{text-align:left}"
             "th.grp{text-align:center}td.first{vertical-align:top}figure{margin:18px 0 24px 0}"
             ".ftitle,.ttitle{font-size:15px;margin:14px 0 6px 0}.tnote{font-size:13px;color:#333}"
             "figcaption{font-size:13px;color:#333;margin-top:4px}summary{cursor:pointer}</style>")
    body = (head + algo_table + failed + "".join(find)
            + "<h2>1. Scores</h2>" + scores + t1
            + "<h2>2. Learning</h2>" + curve_fig
            + "<h2>3. What each algorithm trades off</h2>" + terms
            + "<h2>4. Head to head</h2>" + vs
            + ("<h2>5. Does feedback help?</h2>" + adapt_fig if closed else "")
            + "<h2>6. The policies</h2>" + sched + react
            + "<h2>7. Every seed</h2>" + t2 + settings + bounds
            + f"<p>Source: runs/{esc(args.tag)}.json and runs/{esc(args.tag)}/ (one stage file per algorithm "
              "and seed); swat_gym.ltm.algos, swat_gym.experiments.ltm_algos.</p>")
    Path(args.out).write_text("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Irrigation scheduling: "
                              "algorithms compared</title>" + style + "</head><body>" + body
                              + "</body></html>\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
