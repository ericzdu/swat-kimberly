"""The experiments' plans inside the model, figure by figure (imported by scripts/ltm_results.py).

For each experiment, five plans are re-simulated on the trial's own weather (window 2012:
spin-up 2012, seasons 2013-2020, itself one of the test windows): measured 52A practice,
default, and the best fixed plan of each strategy, read from runs/ltm_exp*.json. Daily 0-kg
probes (inert: tests/test_ltm.py) give soil NO3-N and solution P; the monthly HRU loss table is
switched on for this run only. Plans are compared with each other only: the comparison with the
trial's measurements is on the calibration page (scripts/ltm_nutrient_summary.py).
"""
from __future__ import annotations

from collections import namedtuple
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

import ltm_figures as F
import ltm_nutrient_summary as NS
from swat_gym.ltm import practice
from swat_gym.ltm import runner as rmod
from swat_gym.ltm.env import plan_from_x
from swat_gym.ltm.practice import MAP, MAP_N, MAP_P, N_PRODUCT, measured_x
from swat_gym.ltm.render import PROBE, EpisodePlan, season_irr_eff
from swat_gym.ltm.windows import SEASONS

START = 2012
YEARS = list(range(START + 1, START + SEASONS + 1))
LEVER = {"ltm_exp1": "R", "ltm_exp2": "N", "ltm_exp3": "I", "ltm_exp3_eff55": "I", "ltm_exp3_eff90": "I"}
EFF = {"ltm_exp1": 0.80, "ltm_exp2": 0.80, "ltm_exp3": 0.80, "ltm_exp3_eff55": 0.55, "ltm_exp3_eff90": 0.90}
STRATS = ("yield", "balanced", "sustainability")
#: plan -> (label, colour, dasharray): practice in greys, each strategy's fixed plan in its
#: strategy colour and line type
ARM = {"measured": ("Measured practice", F.TRIAL, ""), "default": ("Default", F.DEFAULT, ""),
       "yield": ("Best fixed, yield", F.STRAT_COL["yield"], ""),
       "balanced": ("Best fixed, balanced", F.STRAT_COL["balanced"], "9 4"),
       "sustainability": ("Best fixed, sustainability", F.STRAT_COL["sustainability"], "2 3")}
CROP = {"barl": "barley", "sgbt": "sugarbeet", "wwht": "spring wheat", "pota": "potato",
        "alfa": "alfalfa", "corn": "corn silage"}
Probe = namedtuple("Probe", "k mon day")


def daily_probes() -> tuple:
    out = []
    for k in range(1, SEASONS + 1):
        d = date(START + k, 1, 1)
        while d.year == START + k:
            out.append(Probe(k, d.month, d.day))
            d += timedelta(days=1)
    return tuple(out)


def plans_of(tag: str, D: dict) -> dict[str, EpisodePlan]:
    practice.set_irr_eff(EFF[tag])          # generated schedules and auto-irrigation
    lever = LEVER[tag]
    S = D[tag]["strategies"]
    plans = {"measured": EpisodePlan(), "default": plan_from_x(lever, measured_x(lever))}
    for s in STRATS:
        fx = S[s]["fixed"]
        plans[s] = (EpisodePlan(crops=tuple(fx["crops"]), irr_auto=True) if lever == "R"
                    else plan_from_x(lever, np.asarray(fx["x"])))
    pr = daily_probes()
    return {a: replace(p, probes=pr) for a, p in plans.items()}


def simulate(plans: dict[str, EpisodePlan]) -> dict[str, dict]:
    rmod.KEEP = {**rmod.KEEP, "hru_ls": {"yearly", "monthly"}}      # monthly leaching, this run only
    if "hru_ls_mon.txt" not in rmod.TABLES:
        rmod.TABLES = (*rmod.TABLES, "hru_ls_mon.txt")
    with rmod.LtmRunner(len(plans), batched="mixed") as r:
        return dict(zip(plans, r.run(list(plans.values()), START)))


def tables(plan: EpisodePlan, o: dict) -> dict:
    """Monthly irrigation (gross) and leaching, yearly inputs/harvest/uptake, daily soil."""
    wb, ls, nb, mg = o["hru_wb_mon.txt"], o["hru_ls_mon.txt"], o["hru_nb_mon.txt"], o["mgt"]
    month = lambda d: pd.to_datetime(dict(year=d.yr, month=d.mon, day=1))  # noqa: E731
    w = wb[wb.yr.isin(YEARS)]
    eff = w.yr.map(lambda y: season_irr_eff(plan, y - START))
    irr = pd.Series((w.irr / eff).to_numpy(), index=month(w))
    l = ls[ls.yr.isin(YEARS)]
    leach = pd.Series(l.percn.to_numpy(), index=month(l))
    n = nb[nb.yr.isin(YEARS)].groupby("yr")[["fertn", "fertp", "nuptake", "puptake"]].sum()
    f = mg[(mg.operation == "FERT") & mg.yr.isin(YEARS)]
    urea = f[(f.name == N_PRODUCT) & (f.op_var > 0)].groupby("yr").op_var.sum()
    mapk = f[f.name == MAP].groupby("yr").op_var.sum()
    syn_n = pd.Series({y: urea.get(y, 0.0) + MAP_N * mapk.get(y, 0.0) for y in YEARS})
    syn_p = pd.Series({y: MAP_P * mapk.get(y, 0.0) for y in YEARS})
    hv = mg[mg.operation.isin(["HARV/KILL", "HARVEST"]) & mg.yr.isin(YEARS)]
    pr = mg[(mg.name == PROBE) & (mg.op_var == 0.0) & mg.yr.isin(YEARS)].copy()
    pr["date"] = pd.to_datetime(dict(year=pr.yr, month=pr.mon, day=pr.day))
    pr = pr.drop_duplicates("date").set_index("date")
    return {
        "irr": irr, "leach": leach,
        "syn_n": [float(syn_n[y]) for y in YEARS], "syn_p": [float(syn_p[y]) for y in YEARS],
        "man_n": [max(0.0, float(n.fertn.get(y, 0.0)) - float(syn_n[y])) for y in YEARS],
        "man_p": [max(0.0, float(n.fertp.get(y, 0.0)) - float(syn_p[y])) for y in YEARS],
        "n_up": [float(n.nuptake.get(y, 0.0)) for y in YEARS],
        "p_up": [float(n.puptake.get(y, 0.0)) for y in YEARS],
        "biomass": [float(hv[hv.yr == y].plant_bioms.max() / 1000) if (hv.yr == y).any() else 0.0
                    for y in YEARS],
        "yield": [float(hv[hv.yr == y].op_var.sum() / 1000) for y in YEARS],
        "no3": pr.soil_no3, "solp": pr.soil_solp,
        "crops": list(plan.crops),
    }


def input_bars(title: str, T: dict, el: str, unit: str, w: int = 960, h: int = 270) -> str:
    """Per year one bar per plan: manure solid, synthetic pale on top (same colour)."""
    left, top = 70, 30
    tot = [m + s for a in ARM for m, s in zip(T[a][f"man_{el}"], T[a][f"syn_{el}"])]
    yt = F.ticks(0, max(tot + [1e-9]) * 1.05)
    gw = (w - left - 20) / len(YEARS)
    ax = F.Axes(left, top, gw * len(YEARS), h - top - 40, (0, len(YEARS)), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", f"{el.upper()} applied, kg/ha")]
    k = len(ARM)
    bw = (gw - 16 - 2 * (k - 1)) / k
    for i, y in enumerate(YEARS):
        for j, (a, (lab, col, _)) in enumerate(ARM.items()):
            x, base = left + i * gw + 8 + j * (bw + 2), 0.0
            for src, op in (("man", 1.0), ("syn", 0.4)):
                v = T[a][f"{src}_{el}"][i]
                if v > 0:
                    y0, y1 = ax.y(base), ax.y(base + v)
                    body.append(f'<rect x="{x:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{y0 - y1:.1f}" '
                                f'fill="{col}" fill-opacity="{op}" stroke="{col}" stroke-width="0.75">'
                                f'<title>{y}, {NS.esc(lab)}, {"manure" if src == "man" else "synthetic"}: '
                                f'{v:,.0f} {unit}</title></rect>')
                    base += v
        body.append(F.text(left + i * gw + gw / 2, ax.y(0) + 15, str(y), 11, "middle", F.INK2))
    body.append(f'<line x1="{left}" x2="{left + gw * len(YEARS):.1f}" y1="{ax.y(0):.1f}" '
                f'y2="{ax.y(0):.1f}" stroke="{F.INK2}" stroke-width="1"/>')
    return F.svg(w, h, "".join(body), title)


def section(tag: str, label: str, D: dict, fig, intro: str) -> str:
    plans = plans_of(tag, D)
    outs = simulate(plans)
    T = {a: tables(plans[a], outs[a]) for a in plans}

    lines = NS.line_legend([(lab, col, dash) for lab, col, dash in ARM.values()], "Plan:")
    squares = NS.legend_row([(lab, col, "square") for lab, col, _ in ARM.values()], "Plan:")

    def ser(key):
        return [(lab, col, T[a][key], dash) for a, (lab, col, dash) in ARM.items()]

    rot = label.startswith("Exp 1")
    ylabels = [str(y) if rot else f"{y} {CROP[T['measured']['crops'][i]]}" for i, y in enumerate(YEARS)]

    def bars(key, title, ylab, unit):
        vals = {a: T[a][key] for a in ARM}
        ymax = max([max(v) for v in vals.values()] + [1e-9])
        return NS.year_bars(title, ylabels, [(ARM[a][0], ARM[a][1], vals[a]) for a in ARM],
                            [None] * len(YEARS), ylab, unit, ymax)

    crop_note = (" Crops differ between plans here; Figure 5 shows each rotation." if rot else "")
    out = [f"<p>{intro}</p>"]
    out.append(fig(f"{label}: nitrogen and phosphorus applied each year, by plan",
                   squares + NS.legend_row([("solid = manure", F.INK2, "square"),
                                            ("pale = synthetic fertilizer", "#c9c8c4", "square")], "Source:")
                   + input_bars("A. Nitrogen applied", T, "n", "kg N/ha")
                   + input_bars("B. Phosphorus applied", T, "p", "kg P/ha"),
                   "Five bars per year, left to right in legend order. Hover a segment for its value."))
    out.append(fig(f"{label}: gross irrigation on the trial's weather, by plan",
                   lines + NS.line_panel("A. Monthly gross irrigation", ser("irr"), "Gross mm/month", "mm", step=True)
                   + NS.line_panel("B. Cumulative gross irrigation since Jan 2013",
                                   [(lab, col, s.cumsum(), dash) for lab, col, s, dash in ser("irr")],
                                   "Gross mm, cumulative", "mm", step=True),
                   "Hover for every plan's value."))
    out.append(fig(f"{label}: monthly NO₃-N leached below the profile, by plan",
                   lines + NS.line_panel("NO₃-N leached", ser("leach"), "kg N/ha/month", "kg/ha", step=True),
                   "Hover for every plan's value."))
    out.append(fig(f"{label}: biomass and harvested yield, by plan",
                   squares + bars("biomass", "A. Above-ground biomass at harvest", "Biomass, t/ha", "t/ha")
                   + bars("yield", "B. Harvested yield, dry matter", "Yield DM, t/ha", "t/ha"),
                   ("Alfalfa: largest standing biomass at a cut (A) and all cuts of the year (B)." if rot
                    else "") + crop_note))
    out.append(fig(f"{label}: plant N and P uptake, by plan",
                   squares + bars("n_up", "A. N uptake", "N uptake, kg/ha", "kg/ha")
                   + bars("p_up", "B. P uptake", "P uptake, kg/ha", "kg/ha"),
                   crop_note.strip()))
    out.append(fig(f"{label}: soil nitrate-N and solution P, daily, by plan",
                   lines
                   + NS.line_panel("A. Soil NO₃-N, whole profile (0–1520 mm)", ser("no3"),
                                   "kg/ha (0–1520 mm)", "kg/ha", h=340, fine=True)
                   + NS.line_panel("B. Soil solution P, whole profile (0–1520 mm)", ser("solp"),
                                   "kg/ha (0–1520 mm)", "kg/ha", h=340, fine=True),
                   "Hover for every plan's value."))
    return "".join(out)
