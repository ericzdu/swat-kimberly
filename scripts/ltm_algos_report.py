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
from swat_gym.ltm.windows import SEASONS, TEST, TRAIN  # noqa: E402

N_TRAIN, N_TEST = len(TRAIN), len(TEST)
TRAIN_SPAN, TEST_SPAN = f"{TRAIN[0]}–{TRAIN[-1] + SEASONS}", f"{TEST[0]}–{TEST[-1] + SEASONS}"
from datetime import date, timedelta  # noqa: E402
from swat_gym.ltm.env import plan_from_x  # noqa: E402
from swat_gym.ltm.practice import irr_months  # noqa: E402
from swat_gym.ltm.render import _passes  # noqa: E402
from swat_gym.ltm.practice import decisions, irr_cap, trial_season  # noqa: E402

CROP = {"barl": "barley", "sgbt": "sugarbeet", "wwht": "wheat", "pota": "potato"}

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


def schedule_panel(D, a, window, title, w=960, h=184, ymax=None):
    """Scheduled monthly depth on one window: each seed of ``a`` against measured practice."""
    ds = decisions("I")
    left, top = 70, 26
    n = len(ds)
    meas = schedule_mm(D["baseline_x"])
    seeds = [schedule_mm(r["test_x"][str(window)]) for r in D["algos"][a]]
    yt = F.ticks(0, ymax or max(max(meas), max(max(s) for s in seeds)) * 1.05, 4)
    ax = F.Axes(left, top, w - left - 20, h - top - 48, (0, n), (0, yt[-1]))
    name, col = ALGOS[a]
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", "mm/month")]
    gw = ax.w / n
    for i, (d, v) in enumerate(zip(ds, meas)):
        body.append(f'<rect x="{ax.x0 + i * gw + 1:.1f}" y="{ax.y(v):.1f}" width="{gw - 2:.1f}" '
                    f'height="{ax.y(0) - ax.y(v):.1f}" fill="#e4e3df"><title>{window + d.k} month {d.mon}, '
                    f'measured: {v:.0f} mm</title></rect>')
        body.append(F.text(ax.x0 + (i + 0.5) * gw, ax.y0 + ax.h + 12, "JFMAMJJASOND"[d.mon - 1], 10, "middle",
                           F.INK2))
        if i == 0 or ds[i - 1].k != d.k:
            x = ax.x0 + i * gw
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ax.y0}" y2="{ax.y0 + ax.h}" stroke="{F.INK2}" '
                        f'stroke-width="0.75"/>')
            body.append(F.text(x + 3, ax.y0 + ax.h + 27, f"{window + d.k} {CROP[trial_season(d.k).crop]}", 11,
                               color=F.INK2))
    dashes = ["", "6 3", "2 2", "8 3 2 3"]
    for j, s in enumerate(seeds):
        pts = " ".join(f"{ax.x0 + (i + 0.5) * gw:.1f},{ax.y(v):.1f}" for i, v in enumerate(s))
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.75" stroke-dasharray="{dashes[j % 4]}" '
                    f'points="{pts}"><title>{esc(name)}, seed {D["algos"][a][j]["seed"]}</title></polyline>')
    return F.svg(w, h, "".join(body), title)


def crop_ticks(ax, seas) -> str:
    """Crop name under each season tick (second row below the S1–S8 labels)."""
    return "".join(F.text(ax.x(k), ax.y0 + ax.h + 28, CROP[trial_season(k).crop], 10, "middle", F.INK2)
                   for k in seas)


def reaction_panel(D, a, title, w=470, h=214):
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
    ax = F.Axes(left, top, w - left - 14, h - top - 48, (0.5, len(seas) + 0.5), (0, yt[-1]))
    name, col = ALGOS[a]
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid([k for k in seas], yt, "", "mm/season", xfmt=lambda v: f"S{int(v)}"),
            crop_ticks(ax, seas)]
    for wn in wins:
        pts = " ".join(f"{ax.x(k):.1f},{ax.y(v):.1f}" for k, v in zip(seas, tot[wn]))
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.5" stroke-opacity="0.8" '
                    f'points="{pts}"><title>{esc(name)}, test window {wn}–{int(wn) + 8}</title></polyline>')
    return F.svg(w, h, "".join(body), title)


def overlay_panel(D, algos, title, w=960, h=274):
    """Seasonal scheduled depth of several algorithms on one axis: best-train seed of each, mean
    over the test windows (open-loop schedules are the same on every window)."""
    ds = decisions("I")
    seas = sorted({d.k for d in ds})
    tot = {}
    for a in algos:
        r = max(D["algos"][a], key=lambda r: r["picked_train_score"])
        per = [[sum(v for v, d in zip(schedule_mm(x), ds) if d.k == k) for k in seas]
               for x in r["test_x"].values()]
        tot[a] = list(np.mean(per, axis=0))
    left, top = 60, 26
    yt = F.ticks(0, max(v for t in tot.values() for v in t) * 1.08, 4)
    ax = F.Axes(left, top, w - left - 14, h - top - 48, (0.5, len(seas) + 0.5), (0, yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid([k for k in seas], yt, "", "mm/season", xfmt=lambda v: f"S{int(v)}"),
            crop_ticks(ax, seas)]
    for a in algos:
        name, col = ALGOS[a]
        pts = " ".join(f"{ax.x(k):.1f},{ax.y(v):.1f}" for k, v in zip(seas, tot[a]))
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{pts}">'
                    f'<title>{esc(name)}</title></polyline>')
        for k, v in zip(seas, tot[a]):
            body.append(f'<circle cx="{ax.x(k):.1f}" cy="{ax.y(v):.1f}" r="4" fill="{col}" stroke="#fff" '
                        f'stroke-width="1"><title>{esc(name)}, S{k}: {v:.0f} mm</title></circle>')
    return F.svg(w, h, "".join(body), title)


def compare_schedule(D, algos, title, w=960, h=264):
    """Monthly gross depth over the 8 seasons: measured practice as bars, each algorithm's
    best-train seed as a line (mean over the test windows; open loop is the same on every one)."""
    ds = decisions("I")
    n = len(ds)
    meas = schedule_mm(D["baseline_x"])
    lines = {}
    for a in algos:
        r = max(D["algos"][a], key=lambda r: r["picked_train_score"])
        lines[a] = list(np.mean([schedule_mm(x) for x in r["test_x"].values()], axis=0))
    left, top = 70, 26
    yt = F.ticks(0, max(max(meas), max(max(v) for v in lines.values())) * 1.05, 4)
    ax = F.Axes(left, top, w - left - 20, h - top - 48, (0, n), (0, yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", "mm/month (gross)")]
    gw = ax.w / n
    for i, (d, v) in enumerate(zip(ds, meas)):
        body.append(f'<rect x="{ax.x0 + i * gw + 1:.1f}" y="{ax.y(v):.1f}" width="{gw - 2:.1f}" '
                    f'height="{ax.y(0) - ax.y(v):.1f}" fill="#e4e3df"><title>S{d.k} month {d.mon}, '
                    f'measured: {v:.0f} mm</title></rect>')
        body.append(F.text(ax.x0 + (i + 0.5) * gw, ax.y0 + ax.h + 12, "JFMAMJJASOND"[d.mon - 1], 10, "middle",
                           F.INK2))
        if i == 0 or ds[i - 1].k != d.k:
            x = ax.x0 + i * gw
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ax.y0}" y2="{ax.y0 + ax.h}" stroke="{F.INK2}" '
                        f'stroke-width="0.75"/>')
            body.append(F.text(x + 3, ax.y0 + ax.h + 27, f"S{d.k} {CROP[trial_season(d.k).crop]}", 11,
                               color=F.INK2))
    for a in algos:
        name, col = ALGOS[a]
        pts = " ".join(f"{ax.x0 + (i + 0.5) * gw:.1f},{ax.y(v):.1f}" for i, v in enumerate(lines[a]))
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{pts}"/>')
        for i, (d, v) in enumerate(zip(ds, lines[a])):
            body.append(f'<circle cx="{ax.x0 + (i + 0.5) * gw:.1f}" cy="{ax.y(v):.1f}" r="3" fill="{col}">'
                        f'<title>{esc(name)}, S{d.k} month {d.mon}: {v:.0f} mm</title></circle>')
    return F.svg(w, h, "".join(body), title)


def event_timeline(D, a, window, title, w=960, row=124):
    """Every irrigation event, season by season (Apr 1 - Oct 31): the trial's measured events as
    stems up, labelled with their dates; algorithm ``a``'s best-train-seed passes as stems down
    (render._passes, the days the engine applies them). Planting and harvest marked."""
    r = max(D["algos"][a], key=lambda r: r["picked_train_score"])
    plan = plan_from_x("I", np.array(r["test_x"][str(window)]))
    name, col = ALGOS[a]
    left, top = 110, 8
    d0, d1 = date(2001, 4, 1).timetuple().tm_yday, date(2001, 10, 31).timetuple().tm_yday
    xw = w - left - 20
    X = lambda doy: left + (doy - d0) / (d1 - d0) * xw  # noqa: E731
    up, dn, mmax = 40, 40, 120.0
    body = [F.text(10, 16, title, 13, weight="bold")]
    for mon in range(4, 11):
        x = X(date(2001, mon, 1).timetuple().tm_yday)
        body.append(F.text(x + 2, 34, date(2001, mon, 1).strftime("%b"), 11, color=F.INK2))
    for k in range(1, 9):
        s_ = trial_season(k)
        year = window + k
        y0 = 40 + top + (k - 1) * row + up + 22     # baseline of this season's row
        doy = lambda m, d: date(2001, m, d).timetuple().tm_yday  # noqa: E731
        body.append(F.text(10, y0 + 4, f"{year} {CROP[s_.crop]}", 12, color=F.INK))
        for mon in range(4, 11):
            x = X(doy(mon, 1))
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y0 - up - 20}" y2="{y0 + dn}" stroke="#eeeeee"/>')
        body.append(f'<line x1="{left}" x2="{left + xw}" y1="{y0}" y2="{y0}" stroke="{F.INK2}" stroke-width="0.75"/>')
        for (m, d), lab in ((s_.plant, "plant"), (s_.harvest, "harvest")):
            x = X(doy(m, d))
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y0 - up - 18}" y2="{y0 + dn}" stroke="{F.INK}" '
                        f'stroke-width="1" stroke-dasharray="3 3"/>')
            body.append(F.text(x + 3, y0 + dn - 2, f"{lab} {m}/{d}", 10, color=F.INK))
        for m, d, mm in s_.irr_daily or ():
            x = X(doy(m, d))
            yt = y0 - up * min(mm, mmax) / mmax
            body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y0}" y2="{yt:.1f}" stroke="#8a8984" stroke-width="3">'
                        f'<title>{year}-{m:02d}-{d:02d}, measured: {mm:.0f} mm</title></line>')
            body.append(f'<text x="{x + 3:.1f}" y="{yt - 2:.1f}" font-size="9" fill="{F.INK2}" '
                        f'transform="rotate(-60 {x + 3:.1f} {yt - 2:.1f})">{m}/{d}</text>')
        months = irr_months(s_)
        amounts = dict(zip(months, plan.irr_mm[k - 1]))
        first_ev = min([date(year, *s_.plant)] + [date(year, m, d) for m, d, _ in (s_.irr_daily or ())])
        first = min(first_ev, date(year, months[0], 1))
        last = date(year, *s_.harvest) - timedelta(days=1)
        for mon in months:
            for d, mm in _passes(year, mon, amounts.get(mon, 0.0), first, last):
                x = X(doy(mon, d))
                body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y0}" y2="{y0 + dn * min(mm, mmax) / mmax:.1f}" '
                            f'stroke="{col}" stroke-width="2"><title>{year}-{mon:02d}-{d:02d}, {esc(name)}: '
                            f'{mm:.0f} mm</title></line>')
    return F.svg(w, 40 + top + 8 * row + 10, "".join(body), title)


DECOMP = [("measured_daily_eff100", "Measured daily events", "#7a7a7a"),
          ("default_eff100", "Measured monthly totals, 25 mm passes", "#b0aea8"),
          ("default_eff80", "Measured monthly totals, 25 mm passes", "#b0aea8"),
          ("cma_eff100", "CMA-ES schedule", ALGOS["cma"][1]),
          ("cma_eff80", "CMA-ES schedule", ALGOS["cma"][1])]


def decomp_bars(X, title, w=960, h=250):
    """Horizontal bars: mean NO3-N leached on the test windows for each decomposition arm."""
    left, top, rowh = 330, 30, 36
    vmax = max(X[k]["no3"] for k, _, _ in DECOMP) * 1.1
    xt = F.ticks(0, vmax, 5)
    ax = F.Axes(left, top, w - left - 90, rowh * len(DECOMP), (0, xt[-1]), (0, 1))
    body = [F.text(10, 16, title, 13, weight="bold")]
    for v in xt:
        x = ax.x(v)
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{top + ax.h}" stroke="#e5e5e5"/>')
        body.append(F.text(x, top + ax.h + 14, f"{v:g}", 11, "middle", F.INK2))
    body.append(F.text(ax.x0 + ax.w / 2, top + ax.h + 30, "NO\u2083-N leached, kg/ha/yr (test-window mean)", 11,
                       "middle", F.INK2))
    for i, (k, lab, col) in enumerate(DECOMP):
        e = X[k]
        y = top + i * rowh
        body.append(F.text(left - 8, y + 15, lab, 12, "end", F.INK))
        body.append(F.text(left - 8, y + 29, f"efficiency {e['eff']:.2f}, gross {e['water']:.0f} mm/yr, "
                                             f"rel. yield {e['ry']:.3f}", 10, "end", F.INK2))
        x1 = ax.x(e["no3"])
        body.append(f'<rect x="{ax.x0}" y="{y + 6:.1f}" width="{max(x1 - ax.x0, 1.5):.1f}" height="{rowh - 12}" '
                    f'rx="3" fill="{col}" fill-opacity="{1.0 if e["eff"] == 1.0 else 0.55}"><title>{esc(lab)}, '
                    f'eff {e["eff"]:.2f}: {e["no3"]:.2f} kg/ha/yr</title></rect>')
        body.append(F.text(x1 + 6, y + 22, f"{e['no3']:.1f}" if e["no3"] >= 10 else f"{e['no3']:.2f}", 12))
    return F.svg(w, top + ax.h + 40, "".join(body), title)


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
            f"{cfg['budget']:,} HRU-episode steps per seed (3 × the v6 runs), is selected on the {N_TRAIN} train "
            f"windows ({TRAIN_SPAN}) and scored on the {N_TEST} test windows ({TEST_SPAN}; effective sample size "
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
             f"Dot = mean paired difference over the {N_TEST} test windows, bar = ESS-based 95 % interval. "
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
                + "".join(schedule_panel(D, a, win, f"{'ABCDEFG'[i]}. {ALGOS[a][0]}" + ("" if FAMILY[a] in ALGOS[a][0] else f" ({FAMILY[a]})"), ymax=ymax)
                          for i, a in enumerate(algos)),
                "Scheduled gross depth for each irrigable month, by season (vertical lines). All panels "
                "share the y scale. Hover a line or bar for its values.")
    react = fig("Does the schedule change with the weather? Seasonal depth on each test window",
                "".join(reaction_panel(D, a, f"{'ABCDEFG'[i]}. {ALGOS[a][0]}") for i, a in enumerate(algos))
                + NS.line_legend([(ALGOS[a][0], ALGOS[a][1], "") for a in algos], "Panel H:")
                + overlay_panel(D, algos, "H. All algorithms together (mean over the test windows)"),
                "Best-train seed of each algorithm; one line per test window (seasons S1–S8 of that "
                "window). Open-loop schedules are identical on every window by construction; a closed-loop "
                "policy whose lines coincide has learned a fixed schedule. H puts A–G on one axis; for closed-loop policies each point is the mean over the test windows.")

    # where the leaching cut comes from (scripts/ltm_leach_decomp.py)
    dpath = RUNS / "ltm_leach_decomp.json"
    leach = ""
    if dpath.exists() and {"cma", "ppo"} <= set(algos):
        X = json.loads(dpath.read_text())
        m, d1, d8, c8, c1 = (X[k] for k in ("measured_daily_eff100", "default_eff100", "default_eff80",
                                             "cma_eff80", "cma_eff100"))
        leach = ("<h2>7. Same water, 99 % less leaching: where it comes from</h2>"
                 f"<p>CMA-ES uses the same gross water as measured practice ({c8['water']:.0f} vs "
                 f"{m['water']:.0f} mm/yr) and leaches {c8['no3']:.2f} instead of {m['no3']:.0f} kg NO₃-N/ha/yr. "
                 "Two things change between those arms besides the schedule. The measured replay applies the "
                 "trial's own daily events (17–58 mm each) at efficiency 1.0; every generated schedule is "
                 "split into passes of at most 25.4 mm and delivered at efficiency 0.80, so a fifth of the "
                 "gross water never reaches the soil. Figure 8 holds each factor fixed in turn.</p>"
                 + fig("Measured practice against the learned schedules, month by month",
                       NS.legend_row([("measured practice", "#e4e3df", "square")], "Bars:")
                       + NS.line_legend([(ALGOS[a][0], ALGOS[a][1], "") for a in ("cma", "ppo")], "Lines:")
                       + compare_schedule(D, ["cma", "ppo"], "Gross depth per irrigable month, seasons S1–S8"),
                       f"Best-train seed of each; PPO is the mean over the {N_TEST} test windows (it varies a little "
                       "by window). The bars are the trial's monthly totals, which default practice applies "
                       "as passes. Per season, CMA-ES takes water out of S1 (barley) and S4 (potato) and puts "
                       "it into S3 and S7 (wheat); the other seasons stay close to practice. Letters under "
                       "the bars are months. Only the decision months are shown: the trial's events outside "
                       f"them (measured daily replay {m['water'] * 8:,.0f} mm over 8 seasons vs "
                       f"{sum(schedule_mm(D['baseline_x'])):,.0f} mm in these bars) are not decisions.")
                 + fig("Every irrigation event: the trial's measured events against the CMA-ES passes",
                       NS.legend_row([("measured event (up, labelled month/day)", "#8a8984", "square"),
                                      ("CMA-ES pass (down)", ALGOS["cma"][1], "square")], "Stems:")
                       + event_timeline(D, "cma", 2012, "Trial weather (window 2012), seasons 2013–2020"),
                       "Stem length is depth, on one scale for both (0–120 mm): measured events are 17–116 mm, "
                       "CMA-ES passes at most 25.4 mm, so CMA-ES applies the same gross water in more, smaller "
                       "events. "
                       "Dashed lines are planting and harvest. The measured replay is at efficiency 1.0, the "
                       "passes at 0.80. Note the measured irrigation after barley and wheat harvest "
                       "(September and late August), outside the months the optimiser decides. Hover any stem "
                       "for its date and depth.")
                 + fig("NO₃-N leached, changing one factor at a time",
                       decomp_bars(X, "Test-window mean leaching by schedule, event size and efficiency"),
                       "Solid = efficiency 1.0, pale = 0.80. Leaching is simulated below the profile and not "
                       "validated on site.")
                 + "<ul>"
                 f"<li><b>Event size, same water and efficiency:</b> applying the trial's monthly totals as "
                 f"passes instead of its daily events cuts leaching {m['no3']:.0f} → {d1['no3']:.0f} "
                 f"(−{100 * (1 - d1['no3'] / m['no3']):.0f} %).</li>"
                 f"<li><b>Efficiency 1.0 → 0.80, same schedule:</b> {d1['no3']:.0f} → {d8['no3']:.2f}, "
                 f"but relative yield falls {d1['ry']:.3f} → {d8['ry']:.3f}: less water reaches the crop "
                 "and the profile never drains.</li>"
                 f"<li><b>Optimising the schedule at 0.80:</b> leaching stays at {c8['no3']:.2f}; what CMA-ES "
                 f"recovers is yield ({d8['ry']:.3f} → {c8['ry']:.3f}).</li>"
                 f"<li><b>The CMA-ES schedule at efficiency 1.0</b> (the same gross water, all of it reaching "
                 f"the soil) leaches {c1['no3']:.0f} kg/ha/yr, more than measured practice.</li></ul>"
                 "<p>So the 99 % is a property of the 0.80 efficiency assumption and pass-sized events, not "
                 "of the optimised timing. The optimiser's gain is yield at the same gross water and the "
                 "same (already low) leaching. A fair headline: <i>at 80 % efficiency the optimised schedule "
                 f"keeps leaching near zero while raising relative yield {100 * (c8['ry'] / d8['ry'] - 1):.0f} % "
                 "over the same monthly totals</i>.</p>")

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
             f"spread = standard deviation of each decision across the {N_TEST} test windows (unit-box scale, "
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
                f"all {N_TRAIN} train windows each generation.</li>"
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
            + leach
            + f"<h2>{8 if leach else 7}. Every seed</h2>" + t2 + settings + bounds
            + f"<p>Source: runs/{esc(args.tag)}.json and runs/{esc(args.tag)}/ (one stage file per algorithm "
              "and seed); swat_gym.ltm.algos, swat_gym.experiments.ltm_algos.</p>")
    Path(args.out).write_text("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Irrigation scheduling: "
                              "algorithms compared</title>" + style + "</head><body>" + body
                              + "</body></html>\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
