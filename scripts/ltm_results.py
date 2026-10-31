#!/usr/bin/env python3
"""Write runs/ltm_results.html: results of the LTM experiments (v6: relative-yield score,
4 ES seeds, 100k HRU-episode steps per seed and per CMA-ES search; OPEN_ITEMS L19, L20).

Every number is read from a file this repo wrote (no transcription): runs/ltm_exp*.json,
runs/ltm_exp*/es_*.json and fixed_*.json (learning curves), runs/ltm_validation.json,
data/ltm/yield.csv. Replaces the profit-era page (in git history before 2026-10-31).

Styling per the user's instruction: barebones, white background, Calibri only.

    uv run python scripts/ltm_results.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import ltm_figures as F  # noqa: E402
import ltm_nutrient_summary as NS  # noqa: E402
import ltm_results_detail as DT  # noqa: E402
from swat_gym.ltm import econ  # noqa: E402
from swat_gym.ltm.practice import TRIAL_ROTATION  # noqa: E402

RUNS = ROOT / "runs"
OUT = RUNS / "ltm_results.html"
#: result file -> label; Exp 3 once per irrigation efficiency (OPEN_ITEMS L13)
EXPS = {"ltm_exp1": "Exp 1 rotation", "ltm_exp2": "Exp 2 nitrogen",
        "ltm_exp3": "Exp 3 irrigation, 80 %", "ltm_exp3_eff55": "Exp 3 irrigation, 55 %",
        "ltm_exp3_eff90": "Exp 3 irrigation, 90 %"}
STRATS = ("yield", "balanced", "sustainability")
STRAT_COL = F.STRAT_COL
CROP = {"barl": "barley", "sgbt": "sugarbeet", "wwht": "spring wheat", "pota": "potato",
        "alfa": "alfalfa", "corn": "corn silage", "barley": "barley", "sugarbeet": "sugarbeet",
        "wheat": "spring wheat", "potato": "potato"}
TERM_LABEL = {"ry": "Relative yield", "no3": "NO₃-N leached, kg/ha/yr", "water": "Gross irrigation, mm/yr",
              "p": "P loss + buildup, kg/ha/yr", "n2o": "N₂O (Tier 1), kg/ha/yr", "profit": "Profit, $/ha/yr"}


def esc(x) -> str:
    return html.escape(str(x))


def table(head: list[str], rows: list[list]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def f(x, nd=2, sign=False) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "–"
    return f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"


def ci(c: dict, nd: int = 3) -> str:
    lo, hi = c["ci95_ess"]
    return f"{f(c['mean'], nd, True)} [{f(lo, nd, True)}, {f(hi, nd, True)}]"


def rot(crops) -> str:
    return " → ".join(CROP.get(c, c) for c in crops)


def load() -> dict:
    return {t: json.loads((RUNS / f"{t}.json").read_text()) for t in EXPS}


def stage(tag: str, name: str) -> dict:
    return json.loads((RUNS / tag / name).read_text())["result"]


def baseline(tag: str) -> str:
    """Exp 1 is quoted against default (CLAUDE.md), the others against measured practice."""
    return "default" if tag == "ltm_exp1" else "measured"


# -- figures ----------------------------------------------------------------------------------
def legend_row(items, heading: str = "", w: int = 960) -> str:
    x = 70 + (7 * len(heading) + 12 if heading else 0)
    head = F.text(70, 16, heading, 12, color=F.INK2, weight="bold") if heading else ""
    return F.svg(w, 24, head + F.legend(items, x, 16), heading or "legend")


def mark(x, y, shape, col, tip, r=5.0) -> str:
    t = f"<title>{esc(tip)}</title>"
    if shape == "ring":
        return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="#fff" stroke="{col}" '
                f'stroke-width="2">{t}</circle>')
    if shape == "square":
        return (f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" '
                f'fill="{col}" stroke="#fff" stroke-width="1">{t}</rect>')
    if shape == "diamond":
        return (f'<path d="M{x:.1f},{y - r - 1.5:.1f} L{x + r + 1.5:.1f},{y:.1f} L{x:.1f},'
                f'{y + r + 1.5:.1f} L{x - r - 1.5:.1f},{y:.1f} Z" fill="{col}" stroke="#fff" '
                f'stroke-width="1">{t}</path>')
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}" stroke="#fff" '
            f'stroke-width="1">{t}</circle>')


#: arms in the bar figures: key -> (legend label, colour); ES bars are the mean of the seeds
ARMS = {"measured": ("Measured practice", F.TRIAL), "default": ("Default", F.DEFAULT),
        "auto": ("Auto-irrigation (Exp 3)", "#1baf7a"), "fixed": ("Best fixed plan", "#2a78d6"),
        "es": ("ES policy, mean of seeds", "#eb6834")}


def arm_values(D: dict, t: str, s: str, key: str) -> tuple[dict, list[float]]:
    """{arm: test mean of ``key``} (auto only for Exp 3) and the per-seed ES values."""
    S = D[t]["strategies"][s]
    seeds = [(sd, v["test_means"][key]) for sd, v in S["es"].items()]
    out = {a: S["test_means"][a][key] for a in ("measured", "default", "auto", "fixed")
           if a in S["test_means"]}
    out["es"] = float(np.mean([v for _, v in seeds]))
    return out, seeds


def group_bars(title: str, D: dict, s: str, key: str, ylab: str, unit: str, nd: int = 3,
               w: int = 960, h: int = 250) -> str:
    """One group per experiment, one bar per arm (negative values hang below zero); the ES
    seeds as black dots on the ES bar. Hover via <title>."""
    left, top = 70, 30
    vals = {t: arm_values(D, t, s, key) for t in EXPS}
    allv = [v for arms, seeds in vals.values() for v in list(arms.values()) + [x for _, x in seeds]]
    lo, hi = min(allv + [0.0]), max(allv + [0.0])
    pad = 0.06 * (hi - lo or 1)
    yt = F.ticks(lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0), 6)
    n = len(EXPS)
    gw = (w - left - 20) / n
    ax = F.Axes(left, top, gw * n, h - top - 40, (0, n), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid(None, yt, "", ylab, yfmt=lambda v: f"{v:,.{max(0, nd - 1)}f}")]
    k = len(ARMS)
    bw = (gw - 24 - 2 * (k - 1)) / k
    y0 = ax.y(0)
    for i, t in enumerate(EXPS):
        arms, seeds = vals[t]
        gx = left + i * gw + 12
        body.append(F.text(left + i * gw + gw / 2, top + ax.h + 15, EXPS[t], 11, "middle", F.INK2))
        for j, (arm, (label, col)) in enumerate(ARMS.items()):
            if arm not in arms:
                continue
            v = arms[arm]
            x, yv = gx + j * (bw + 2), ax.y(v)
            body.append(f'<rect x="{x:.1f}" y="{min(yv, y0):.1f}" width="{bw:.1f}" '
                        f'height="{max(abs(y0 - yv), 0.5):.1f}" fill="{col}">'
                        f'<title>{esc(EXPS[t])}, {esc(label)}: {v:,.{nd}f} {esc(unit)}</title></rect>')
            if arm == "es":
                for q, (sd, sv) in enumerate(seeds):
                    body.append(mark(x + bw / 2 + (q - 1.5) * 3, ax.y(sv), "dot", F.INK,
                                     f"{EXPS[t]}, ES seed {sd}: {sv:,.{nd}f} {unit}", 3))
    body.append(f'<line x1="{left}" x2="{left + gw * n:.1f}" y1="{y0:.1f}" y2="{y0:.1f}" '
                f'stroke="{F.INK2}" stroke-width="1"/>')
    return F.svg(w, h, "".join(body), title)


def arm_legend() -> str:
    return (legend_row([(lab, col, "square") for lab, col in ARMS.values()], "Arm (colour):")
            + legend_row([("ES seeds, one dot each", F.INK, "dot")], "Dots:"))


def forest(D: dict, key: str, title: str, left_lab: str, right_lab: str) -> str:
    """Per seed: mean difference with its ESS 95 % interval, one row per experiment x strategy."""
    rows = [(t, s) for t in EXPS for s in STRATS]
    left, top, row_h, w = 290, 52, 26, 960
    pw = w - left - 30
    allv = [x for t, s in rows for v in D[t]["strategies"][s]["es"].values()
            for x in v[key]["score"]["ci95_ess"]]
    lo, hi = min(allv + [0.0]), max(allv + [0.0])
    pad = 0.08 * (hi - lo or 1)
    xt = F.ticks(lo - pad, hi + pad, 7)
    H = top + row_h * len(rows) + 46
    ax = F.Axes(left, top, pw, row_h * len(rows), (xt[0], xt[-1]), (0, 1))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid(xt, None, "Score difference on the test windows", "", xfmt=lambda v: f"{v:+.2f}"),
            F.text(ax.x(0) - 6, top - 8, left_lab, 11, "end", F.INK2),
            F.text(ax.x(0) + 6, top - 8, right_lab, 11, "start", F.INK2),
            f'<line x1="{ax.x(0):.1f}" x2="{ax.x(0):.1f}" y1="{top}" y2="{top + row_h * len(rows)}" '
            f'stroke="{F.INK}" stroke-width="1.5"/>']
    for r, (t, s) in enumerate(rows):
        yc = top + r * row_h + row_h / 2
        body.append(F.text(left - 10, yc + 4, f"{EXPS[t]}, {s}", 12, "end"))
        if r and rows[r - 1][0] != t:
            body.append(f'<line x1="20" x2="{ax.x0 + pw}" y1="{yc - row_h / 2:.1f}" '
                        f'y2="{yc - row_h / 2:.1f}" stroke="{F.GRID}" stroke-width="1"/>')
        for q, (sd, v) in enumerate(D[t]["strategies"][s]["es"].items()):
            c = v[key]["score"]
            yy = yc + (q - 1.5) * 4.5
            a, b = c["ci95_ess"]
            tip = f"<title>{esc(EXPS[t])}, {s}, seed {sd}: {c['mean']:+.3f} [{a:+.3f}, {b:+.3f}]</title>"
            body.append(f'<line x1="{ax.x(a):.1f}" x2="{ax.x(b):.1f}" y1="{yy:.1f}" y2="{yy:.1f}" '
                        f'stroke="{STRAT_COL[s]}" stroke-width="2" stroke-linecap="round">{tip}</line>')
            body.append(f'<circle cx="{ax.x(c["mean"]):.1f}" cy="{yy:.1f}" r="3.5" fill="{STRAT_COL[s]}" '
                        f'stroke="#fff" stroke-width="1">{tip}</circle>')
    return F.svg(w, H, "".join(body), title)


def curve_panel(tag: str, s: str, panel: str, w: int = 470, h: int = 250) -> str:
    """ES train fitness (population median) per generation for each seed, against the best
    fixed plan's train score."""
    D = json.loads((RUNS / f"{tag}.json").read_text())
    seeds = list(D["strategies"][s]["es"])
    runs = [stage(tag, f"es_{s}_s{sd}.json") for sd in seeds]
    fixed_train = (D["strategies"][s]["fixed"]["train_score"] if tag == "ltm_exp1"
                   else -stage(tag, f"fixed_{s}.json")["history"][-1]["best_f"])
    ys = [x["fit_median"] for r in runs for x in r["fitness"]] + [fixed_train]
    lo, hi = min(ys), max(ys)
    pad = 0.08 * (hi - lo or 1)
    yt = F.ticks(lo - pad, hi + pad, 5)
    gmax = max(len(r["fitness"]) for r in runs)
    left, top = 60, 30
    ax = F.Axes(left, top, w - left - 16, h - top - 44, (0, gmax), (yt[0], yt[-1]))
    xt = F.ticks(0, gmax, 5)
    body = [F.text(left, 16, f"{panel}. {EXPS[tag]}", 13, weight="bold"),
            ax.grid(xt, yt, "ES generation", "Train score", xfmt=lambda v: f"{v:g}",
                    yfmt=lambda v: f"{v:.2f}"),
            f'<line x1="{ax.x0}" x2="{ax.x0 + ax.w}" y1="{ax.y(fixed_train):.1f}" '
            f'y2="{ax.y(fixed_train):.1f}" stroke="{F.INK}" stroke-width="1.5" stroke-dasharray="6 4">'
            f'<title>best fixed plan, train: {fixed_train:.3f}</title></line>']
    for r, sd in zip(runs, seeds):
        pts = " ".join(f"{ax.x(x['generation']):.1f},{ax.y(x['fit_median']):.1f}" for x in r["fitness"])
        body.append(f'<polyline fill="none" stroke="{STRAT_COL[s]}" stroke-width="1.5" points="{pts}">'
                    f'<title>seed {sd}</title></polyline>')
    return F.svg(w, h, "".join(body), f"ES learning curve {tag} {s}")


def bias_table() -> str:
    v = json.loads((RUNS / "ltm_validation.json").read_text())
    rows = [[h["year"], CROP.get(h["crop"], h["crop"]), f(h.get("biomass_pct_err"), 0, True),
             f(h.get("yield_pct_err"), 0, True)] for h in v["harvest"] if h["treatment"] == "52A"]
    y = pd.read_csv(ROOT / "data" / "ltm" / "yield.csv")
    pot = y[(y.treatment == "52A") & (y.crop == "potato")].yield_fresh_mg_ha.mean()
    pot_dm = pot * econ.POTA_DM
    sim = next(h["sim_yield_dm_t"] for h in v["harvest"] if h["treatment"] == "52A" and h["crop"] == "potato")
    sb = v["sugarbeet_root_dm"]
    note = (f"Potato tuber: measured {pot:.1f} Mg/ha fresh × {econ.POTA_DM:.3f} DM = {pot_dm:.1f} t DM/ha "
            f"vs {sim:.1f} simulated ({(sim / pot_dm - 1) * 100:+.0f} %). Sugarbeet root DM "
            f"(2018/2020 vs the trial's multi-year mean): 52A {sb['52A']['pct_err']:+.1f} %, fertilizer only "
            f"{sb['fert']['pct_err']:+.1f} %, control {sb['control']['pct_err']:+.1f} %. Alfalfa and corn "
            "silage have no measurement on this field.")
    return table(["Year", "Crop (52A)", "Biomass error", "Yield error"], rows) + f"<p>{esc(note)}</p>"


# -- page ---------------------------------------------------------------------------------------
def main() -> None:
    D = load()
    cfg = D["ltm_exp1"]["config"]
    n_fig, n_tab = [0], [0]
    STRATEGIES_W = {s: D["ltm_exp1"]["strategies"][s]["w"] for s in STRATS}

    def fig(title, body, caption=""):
        n_fig[0] += 1
        return (f'<figure><div class="ftitle"><b>Figure {n_fig[0]}.</b> {title}</div>{body}'
                + (f"<figcaption>{caption}</figcaption>" if caption else "") + "</figure>")

    def tab(title, body):
        n_tab[0] += 1
        return f'<div class="ttitle"><b>Table {n_tab[0]}.</b> {title}</div>{body}'

    # findings, computed
    pf = [(t, s, v["policy_vs_fixed"]["score"]) for t in EXPS for s in STRATS
          for v in D[t]["strategies"][s]["es"].values()]
    n_pf = len(pf)
    es_worse = sum(c["resolvable"] and c["mean"] < 0 for _, _, c in pf)
    es_better = sum(c["resolvable"] and c["mean"] > 0 for _, _, c in pf)
    adapt = [v["adaptivity_value"]["score"] for t in EXPS for s in STRATS
             for v in D[t]["strategies"][s]["es"].values()]
    adapt_max = max(abs(c["mean"]) for c in adapt)
    adapt_res = sum(c["resolvable"] for c in adapt)
    fx = [(t, s, D[t]["strategies"][s]["fixed_vs_" + baseline(t)]["score"]) for t in EXPS for s in STRATS]
    fx_better = sum(c["resolvable"] and c["mean"] > 0 for _, _, c in fx)
    e2y = D["ltm_exp2"]["strategies"]["yield"]["test_means"]
    picked_last = sum(stage(t, f"es_{s}_s{sd}.json")["picked_snapshot"] == len(stage(t, f"es_{s}_s{sd}.json")["curve"]) - 1
                      for t in EXPS for s in STRATS for sd in D[t]["strategies"][s]["es"])
    gens = {t: stage(t, "es_yield_s0.json")["generations"] for t in EXPS}
    e1s = D["ltm_exp1"]["strategies"]
    same_rot = sum(v["frozen_crops"] == e1s[s]["fixed"]["crops"] for s in ("balanced", "sustainability")
                   for v in e1s[s]["es"].values())

    head = (
        "<h1>Long-term manure experiments: results (v6)</h1>"
        "<p>Can a learned, closed-loop management policy beat the trial's practice and the best "
        "fixed plan? Three levers on the calibrated SWAT+ model of the Kimberly long-term manure "
        "trial (52A plot): crop rotation (Exp 1), nitrogen, manure vs synthetic (Exp 2), and monthly "
        "irrigation (Exp 3, at 55, 80 and 90 % application efficiency).</p>"
        "<p><b>Score.</b> Three fixed strategies, w = 1 (yield), 0.5 (balanced) and 0 "
        "(sustainability): score = w · ry/ry<sub>meas</sub> − (1 − w) · mean of the four "
        "sustainability terms (NO₃-N leached, gross irrigation, P loss + buildup, N₂O), each divided "
        "by measured practice's train mean. ry is relative harvested yield. At w = 0 an episode "
        "below default practice's yield loses 10 × the shortfall. Profit is reported, not scored.</p>"
        f"<p><b>Methods.</b> A closed-loop policy (64×64 network trained by OpenAI-ES, "
        f"{cfg['seeds']} seeds) against the best open-loop plan: CMA-ES for N and I, every valid "
        f"repeating rotation (exhaustive) for R. Each ES seed and each CMA-ES search gets "
        f"{cfg['budget']:,} HRU-episode steps. Plans are selected on 7 train windows (1995–2009) and "
        f"scored on 7 test windows (2011–2025), which share no calendar year; the windows overlap, so "
        f"the effective sample size is {cfg['test_ess']:.2f} and intervals are ESS-based (rule 7). "
        "Exp 1 is quoted against <i>default</i> (the trial rotation under the same auto-irrigation), "
        "the others against <i>measured</i> practice.</p>"
        "<h2>Key findings</h2><ul>"
        f"<li><b>The learned policy never beats the best fixed plan.</b> Of {n_pf} seed × strategy "
        f"× experiment comparisons, ES is resolvably worse in {es_worse}, resolvably better in "
        f"{es_better}, and unresolved in the rest (Figure 3A). In Exp 1 it matches the exhaustive "
        f"search's test score for balanced and sustainability; {same_rot} of 8 of those seeds pick the "
        "identical rotation (Figure 5).</li>"
        f"<li><b>Adapting to the soil state adds nothing measurable.</b> Each policy scores within "
        f"{adapt_max:.3f} of its own frozen (open-loop) plan; {adapt_res} of {len(adapt)} differences "
        "are resolvable (Figure 3B). At this budget the closed loop learns one good schedule, not a "
        "state-dependent rule.</li>"
        f"<li><b>Search itself pays.</b> The best fixed plan beats the baseline resolvably in "
        f"{fx_better} of {len(fx)} experiment × strategy cases (Table 1), e.g. Exp 1 balanced "
        f"{D['ltm_exp1']['strategies']['balanced']['test_means']['default']['score']:.3f} → "
        f"{D['ltm_exp1']['strategies']['balanced']['test_means']['fixed']['score']:.3f}.</li>"
        f"<li><b>ES is under-trained at this budget.</b> Exp 2 and Exp 3 get only {gens['ltm_exp2']} "
        f"and {gens['ltm_exp3']} generations per seed (Exp 1, whose episodes are short: "
        f"{gens['ltm_exp1']}), and {picked_last} of {len(pf)} seeds picked their last snapshot: "
        "train fitness was still rising when the budget ran out (Figure 4).</li>"
        f"<li><b>Exp 2's yield strategy is degenerate.</b> Every arm scores "
        f"{e2y['measured']['score']:.3f}: in this model the crops are not N-limited under 52A manure, "
        "so N decisions cannot change yield and both optimizers see a flat objective. The fixed plan "
        "is therefore measured practice (CMA-ES keeps its starting point on ties).</li></ul>")

    # Table 1: headline
    rows = []
    for t in EXPS:
        for s in STRATS:
            S = D[t]["strategies"][s]
            tm = S["test_means"]
            es = [v["test_means"]["score"] for v in S["es"].values()]
            pfs = [v["policy_vs_fixed"]["score"] for v in S["es"].values()]
            ads = [v["adaptivity_value"]["score"]["mean"] for v in S["es"].values()]
            rows.append([esc(EXPS[t]) if s == STRATS[0] else "", s, f(tm["measured"]["score"], 3),
                         f(tm["default"]["score"], 3), f(tm["auto"]["score"], 3) if "auto" in tm else "–",
                         f"<b>{f(tm['fixed']['score'], 3)}</b>",
                         f"{f(np.mean(es), 3)} ({f(min(es), 3)} to {f(max(es), 3)})",
                         f"{sum(c['resolvable'] and c['mean'] < 0 for c in pfs)} / "
                         f"{sum(c['resolvable'] and c['mean'] > 0 for c in pfs)} / {len(pfs)}",
                         f"{f(min(ads), 3, True)} to {f(max(ads), 3, True)}",
                         ci(S["fixed_vs_" + baseline(t)]["score"])])
    t1 = tab("Test-window strategy scores per experiment and strategy",
             table(["Experiment", "Strategy", "Measured", "Default", "Auto-irr.", "Best fixed",
                    "ES mean (range of 4 seeds)", "ES vs fixed: worse / better / seeds (resolvable)",
                    "Adaptivity (policy − frozen)", "Fixed − baseline [ESS 95 % CI]"], rows)
             + "<p>Baseline: default for Exp 1, measured for the others. <i>Default</i> is measured "
               "practice through the lever's plan generator (Exp 1: trial rotation, auto-irrigated); "
               "<i>auto</i> is trial management with auto-irrigation at the case efficiency.</p>")

    f1 = fig("Test-window strategy score of every arm, by strategy", arm_legend() + "".join(
        group_bars(f"{'ABC'[i]}. {s.capitalize()} strategy (w = {STRATEGIES_W[s]:g})", D, s, "score",
                   "Strategy score", "")
        for i, s in enumerate(STRATS)),
        "One group per experiment, one bar per arm; higher is better. Each panel has its own y "
        "scale (sustainability scores are negative: smaller bars are better). Auto-irrigation "
        "exists only in Exp 3. Black dots are the four ES seeds. Hover a bar or dot for its value.")
    f_terms = fig("Relative yield and the four sustainability terms, balanced strategy", arm_legend() + "".join(
        group_bars(f"{'ABCDE'[i]}. {TERM_LABEL[k]}", D, "balanced", k, TERM_LABEL[k].split(",")[0],
                   TERM_LABEL[k].split(", ")[1] if ", " in TERM_LABEL[k] else "", nd)
        for i, (k, nd) in enumerate((("ry", 3), ("no3", 1), ("water", 0), ("p", 1), ("n2o", 2)))),
        "Test-window means per ha per year under the balanced strategy (w = 0.5). Higher relative "
        "yield is better; lower is better for the four terms. Leaching is not validated on site, and "
        "N₂O is IPCC Tier 1 accounting. The other strategies' values are in Table 2.")
    strat_leg = legend_row([(s, STRAT_COL[s], "dot") for s in STRATS], "Strategy (colour):")
    f2 = fig("Learned policy against the best fixed plan, and the value of adapting, per seed",
             strat_leg
             + forest(D, "policy_vs_fixed", "A. Learned policy − best fixed plan",
                      "← fixed plan better", "policy better →")
             + forest(D, "adaptivity_value", "B. Learned policy − its own frozen plan (value of adapting)",
                      "← frozen better", "closed loop better →"),
             "Dot = mean paired difference over the 7 test windows; bar = ESS-based 95 % interval. "
             "Four rows per line, one per seed. An interval that crosses zero is unresolved.")
    curve_leg = (F.svg(960, 24, F.text(70, 16, "Lines:", 12, color=F.INK2, weight="bold")
                       + f'<line x1="120" x2="150" y1="12" y2="12" stroke="{STRAT_COL["balanced"]}" stroke-width="2"/>'
                       + F.text(156, 16, "ES population median, one line per seed", 12)
                       + f'<line x1="420" x2="450" y1="12" y2="12" stroke="{F.INK}" stroke-width="1.5" '
                         'stroke-dasharray="6 4"/>' + F.text(456, 16, "best fixed plan (train)", 12),
                       "curve legend"))
    f3 = fig("ES learning curves, balanced strategy (train windows)",
             curve_leg + "".join(curve_panel(t, "balanced", "ABCDE"[i]) for i, t in enumerate(EXPS)),
             "Train score of the ES population median per generation. Each panel has its own y scale. "
             "The curves are still rising at the end of the budget and stay below the fixed plan's "
             "train score, except Exp 1 where the rotation space is small.")

    # Exp 1 rotations
    e1 = D["ltm_exp1"]["strategies"]
    rot_rows = [("Trial rotation (default)", list(TRIAL_ROTATION))]
    for s in STRATS:
        rot_rows.append((f"Best fixed, {s}", e1[s]["fixed"]["crops"]))
        for sd, v in e1[s]["es"].items():
            rot_rows.append((f"ES frozen, {s}, seed {sd}", v["frozen_crops"]))
    names = {k: CROP[k] for k in F.CROP_COL}
    f4 = fig("Exp 1: rotations chosen", F.rotations(rot_rows, names),
             f"Best fixed = highest mean train score among {e1['yield']['fixed']['n_candidates']} valid "
             "repeating rotations. ES frozen = each seed's per-season majority crop on the train windows. "
             "Every Exp 1 plan is auto-irrigated at 80 %. Rotation results inherit each crop's yield bias "
             "(Table 4).")

    # Table 2: terms per arm
    def terms_rows(t):
        out = []
        for s in STRATS:
            S = D[t]["strategies"][s]
            tm = dict(S["test_means"])
            es_keys = list(S["es"])
            tm["ES (mean of seeds)"] = {k: float(np.mean([S["es"][sd]["test_means"][k] for sd in es_keys]))
                                        for k in S["es"][es_keys[0]]["test_means"]}
            for arm, m in tm.items():
                out.append([s, arm, f(m["score"], 3), f(m["ry"], 3), f(m["no3"], 1), f(m["water"], 0),
                            f(m["p"], 1), f(m["n2o"], 2), f(m["profit"], 0)])
        return out
    t2 = tab("Test-window means of every term, by experiment, strategy and arm", "".join(
        f"<details><summary>{esc(EXPS[t])}</summary>"
        + table(["Strategy", "Arm", "Score", "Rel. yield", "NO₃-N kg/ha/yr", "Water mm/yr",
                 "P kg/ha/yr", "N₂O kg/ha/yr", "Profit $/ha/yr"], terms_rows(t)) + "</details>"
        for t in EXPS) + "<p>Click an experiment to expand. Profit is reported only; it is not in "
                         "the score.</p>")

    # Table 3: Exp 3 efficiencies
    rows = []
    for s in STRATS:
        for t in ("ltm_exp3_eff55", "ltm_exp3", "ltm_exp3_eff90"):
            S = D[t]["strategies"][s]
            c = S["fixed_vs_measured"]
            rows.append([s if t == "ltm_exp3_eff55" else "", esc(EXPS[t].split(", ")[1]),
                         f(S["test_means"]["fixed"]["water"], 0), f(S["test_means"]["measured"]["water"], 0),
                         ci(c["ry"]), ci(c["no3"], 1), ci(c["water"], 0), ci(c["score"])])
    t3 = tab("Exp 3 across irrigation efficiencies: best fixed plan − measured practice",
             table(["Strategy", "Efficiency", "Fixed water mm/yr", "Measured water mm/yr",
                    "Δ rel. yield", "Δ NO₃-N kg/ha/yr", "Δ water mm/yr", "Δ score"], rows)
             + "<p>Measured practice is replayed at efficiency 1.0 in every case (OPEN_ITEMS L13), so "
               "its row is the same; generated schedules run at the case efficiency.</p>")

    t4 = tab("Crop yield bias of the model, 52A (simulated vs measured)", bias_table())

    intros = {
        "ltm_exp1": "Rotation. <i>Measured</i> is the trial (its rotation, measured irrigation at "
                    "efficiency 1.0). <i>Default</i> is the trial rotation auto-irrigated at 80 %, the "
                    "baseline Exp 1 is quoted against. Each best fixed plan is a repeating rotation, "
                    "auto-irrigated at 80 %, with 52A manure each fall except into standing alfalfa.",
        "ltm_exp2": "Manure vs synthetic N, on the trial rotation with measured irrigation. "
                    "<i>Default</i> passes measured practice through the plan generator and is identical "
                    "to measured here, so their lines coincide. The yield strategy's objective is flat "
                    "(N cannot change yield in this model): CMA-ES keeps its starting point when no candidate "
                    "is strictly better, so its best fixed plan is measured practice and its lines "
                    "coincide with measured and default.",
    }
    for t_, e_ in (("ltm_exp3", 80), ("ltm_exp3_eff55", 55), ("ltm_exp3_eff90", 90)):
        intros[t_] = (f"Monthly irrigation depths at {e_} % application efficiency, on the trial "
                      "rotation, manure and N. <i>Measured</i> replays the trial's daily events at "
                      f"efficiency 1.0; <i>default</i> applies the trial's monthly totals as generated "
                      f"passes at {e_} %.")
    detail = ("<h2>Part 2: the plans inside the model, trial weather 2013–2020</h2>"
              "<p>Each experiment's measured practice, default and best fixed plan per strategy, re-run on "
              "the trial's own weather (window 2012, one of the seven test windows) with the figures of "
              "the calibration page. Colour and line type identify the plan: greys for practice, and the "
              "strategy's colour and line type (yield solid, balanced dashed, sustainability dotted) for "
              "its best fixed plan. The ES policies are left out: each scores within 0.008 of its frozen "
              "plan (Figure 3B). Measured values are the 52A plot's.</p>"
              "<p><b>One difference from the calibration page.</b> The trial tilled its 2014 sugarbeet in "
              "unharvested; the experiments' measured practice harvests it on the trial's 2018 harvest "
              "date instead (practice.SGBT_2014_HARVEST_FROM), so that no weather window loses a crop by "
              "construction. From 2014 on, measured practice here therefore differs from the calibration "
              "page (for example 1,415 vs 1,389 kg NO₃-N/ha leached over 2013–2020, and a 2014 beet "
              "harvest instead of none). Irrigation is identical.</p>"
              + "".join(f"<h2>{8 + i}. {esc(EXPS[t_])}</h2>" + DT.section(t_, EXPS[t_], D, fig, intros[t_])
                        for i, t_ in enumerate(EXPS)))

    bounds = ("<h2>Bounds on these results</h2><ul>"
              "<li>Crop parameters are Ai-SWAT-Plus's, copied verbatim and not fitted here; potato "
              "under-yields and spring wheat uses winter-wheat parameters. Rotation results inherit "
              "each crop's bias (Table 4).</li>"
              "<li>Leaching is not validated on this site. N₂O is IPCC Tier 1 accounting; SWAT+ does "
              "not simulate it.</li>"
              f"<li>The test set's effective sample size is {cfg['test_ess']:.2f}: intervals are wide "
              "and a difference that is small relative to them is reported as unresolved.</li>"
              "<li>Each fixed plan comes from one CMA-ES run (seed 0); ES has four seeds.</li></ul>")

    style = ("<style>body{font-family:Calibri,sans-serif;background:#fff;color:#000;margin:24px;"
             "max-width:1000px}table{border-collapse:collapse;font-size:13px;margin:8px 0}"
             "th,td{border:1px solid #ccc;padding:2px 6px;text-align:right}"
             "th:first-child,td:first-child{text-align:left}figure{margin:18px 0 24px 0}"
             ".ftitle,.ttitle{font-size:15px;margin:14px 0 6px 0}"
             "figcaption{font-size:13px;color:#333;margin-top:4px}summary{cursor:pointer;margin:6px 0}"
             "</style>")
    body = (head + "<h2>1. Scores</h2>" + t1 + f1 + f_terms
            + "<h2>2. Policy against fixed plan, and the value of adapting</h2>" + f2
            + "<h2>3. Why ES falls short: budget</h2>" + f3
            + "<h2>4. Exp 1: rotations</h2>" + f4
            + "<h2>5. Every term</h2>" + t2
            + "<h2>6. Exp 3: irrigation efficiency</h2>" + t3
            + "<h2>7. Crop yield bias</h2>" + t4 + detail + bounds
            + "<p>Source files: runs/ltm_exp1.json, ltm_exp2.json, ltm_exp3.json, ltm_exp3_eff55.json, "
              "ltm_exp3_eff90.json and their stage directories; runs/ltm_validation.json.</p>")
    OUT.write_text("<!DOCTYPE html><html><head><meta charset='utf-8'><title>LTM experiments: results (v6)"
                   "</title>" + style + "</head><body>" + body + NS.HOVER_JS + "</body></html>\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
