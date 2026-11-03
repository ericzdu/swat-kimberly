#!/usr/bin/env python3
"""Water and nutrient summary of the LTM scenario, for comparison with the trial's own data.

Runs model/ltm/TxtInOut (three HRUs: 52A, fert, control) under three irrigation cases:

* measured   -- the trial's daily irrigation events, replayed at practice.MEASURED_IRR_EFF (1.0)
* auto100    -- auto-irrigation (practice.AUTO_IRR: 1-inch pass when profile plant-available
                water < sw_frac x FC, inside each season's window) at efficiency 1.0, the
                efficiency the trigger was fitted at (scripts/ltm_fit_auto_irr.py)
* auto080    -- the same rule at practice.BASE_IRR_EFF (0.80), the experiments' base case

The 2012 spin-up (beans, auto-irrigated at 0.80) is identical in every case; outputs cover
2013-2020 (print.prt skips the spin-up year). Every case adds a 0-kg elem_n probe on every day
(inert: checked against the measured case without daily probes, `probe_check` below); a
probe runs before that day's other ops, so its soil values are the start-of-day state.

Outputs (runs/ltm_nutrient_summary.html + runs/ltm_nutrient_summary/*.csv):
yearly applied N and P; monthly irrigation (gross = what reaches the soil / efficiency);
monthly NO3-N leached (hru_ls percn); biomass and yield at harvest (mgt_out HARV/KILL);
N and P uptake (hru_nb_yr); daily profile soil NO3-N and solution P (probe rows of mgt_out,
kg/ha over the whole 0-1520 mm profile, also as a profile-mean mg/kg).

    uv run python scripts/ltm_nutrient_summary.py
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_ltm as B  # noqa: E402
import ltm_figures as F  # noqa: E402
from swat_gym.fastrunner import FastRunner  # noqa: E402
from swat_gym.ltm.econ import POTA_DM  # noqa: E402
from swat_gym.ltm.practice import (AUTO_IRR, BASE_IRR_EFF, MEASURED_IRR_EFF,  # noqa: E402
                                   auto_op)
from swat_gym.ltm.render import EpisodePlan, render  # noqa: E402
from swat_gym.ltm.runner import EDITABLE, _irr_table, read_mgt, read_table  # noqa: E402

TIO = B.TIO
DATA = B.DATA
OUT_HTML = ROOT / "runs" / "ltm_nutrient_summary.html"
OUT_DIR = ROOT / "runs" / "ltm_nutrient_summary"
HRU = {1: "52A", 2: "fert", 3: "control"}
TRT_LABEL = {"52A": "52A (manure)", "fert": "Fertilizer only", "control": "Control"}
#: case -> (label, efficiency of the 2013-2020 irrigation; None = measured replay)
CASES = {"measured": ("Measured irrigation (eff 1.0)", None),
         "auto100": ("Auto-irrigation, eff 1.0", 1.0),
         "auto080": ("Auto-irrigation, eff 0.80", BASE_IRR_EFF)}
#: the companion page: the experiments run on this model (scripts/ltm_results.py)
RESULTS_URL = "https://claude.ai/artifact/TtjHzAS9r4VMHsqkCRgwWx"
CASE_COL = dict(zip(CASES, ("#2a78d6", "#eb6834", "#1baf7a")))   # ltm_figures slots 1-3
TRT_SHORT = {"52A": "52A", "fert": "Fert", "control": "Ctrl"}
#: line type per treatment where all treatments share one graph
TRT_DASH = {"52A": "", "fert": "9 4", "control": "2 3"}
#: applied-input sources: ltm_figures slot 4 (amber) and the trial grey
SRC_COL = {"manure": "#eda100", "synthetic": "#52514e"}
FIRST, LAST = B.START + 1, B.END
SPIN_EFF = BASE_IRR_EFF                    #: the 2012 beans' auto-irrigation (build_ltm)
TRIAL_IRR = "ltm_trial_irr"                #: lum.dtl table auto-irrigating 2013-2020
TOL = 1e-6


# -- inputs per case ------------------------------------------------------------------------
def sched_text(scheds: dict[str, list], autos: list[str]) -> str:
    """management.sch in build_ltm.write_management's layout."""
    lines = ["management.sch: written by swat-kimberly build_ltm.py",
             "name                                       numb_ops  numb_auto            op_typ       mon       day        hu_sch          op_data1          op_data2      op_data3  "]
    for tag, ops in scheds.items():
        lines.append(f"{'ltm_' + tag:<34}{len(ops):>6}{len(autos):>11}  ")
        lines += [f"{'':>48}{a:<18}" for a in autos]
        lines += [o[2] for o in ops]
    return "\n".join(lines) + "\n"


def base_schedules() -> dict[str, list]:
    """build_ltm's schedules, checked against the built model (they must not have drifted)."""
    fert_p = json.loads((TIO.parent / "build.json").read_text())["fert_p"]
    scheds, _, _ = B.schedules(fert_p, probes=True)
    if sched_text(scheds, [B.BEAN_IRR]) != (TIO / "management.sch").read_text():
        raise SystemExit("model/ltm/TxtInOut/management.sch differs from build_ltm.schedules(): "
                         "rebuild with scripts/build_ltm.py first")
    return scheds


def trial_windows() -> list[tuple[int, int, int]]:
    """Auto-irrigation windows of the trial seasons (as the env's EpisodePlan(irr_auto))."""
    _, _, auto = render(EpisodePlan(irr_auto=True), B.START, "x")
    return [w for w in auto if w[0] >= FIRST]


def daily_probes(scheds: dict[str, list]) -> dict[str, list]:
    have = set(B.probe_dates())
    days = [date(B.START, 1, 1) + timedelta(days=i)
            for i in range((date(LAST, 12, 31) - date(B.START, 1, 1)).days + 1)]
    extra = [B._op("probe", d, None) for d in days if d not in have]
    return {t: sorted(ops + extra, key=lambda o: (o[0], o[1])) for t, ops in scheds.items()}


def case_edits(scheds: dict[str, list], eff: float | None, probes: bool = True) -> dict[str, str]:
    if probes:
        scheds = daily_probes(scheds)
    if eff is None:
        return {"management.sch": sched_text(scheds, [B.BEAN_IRR])}
    if AUTO_IRR["sw_frac"] is None:
        raise SystemExit("auto-irrigation trigger not fitted: run scripts/ltm_fit_auto_irr.py")
    scheds = {t: [o for o in ops if o[2].split()[0] != "irrm"] for t, ops in scheds.items()}
    dtl = (TIO / "lum.dtl").read_text()
    head, count, rest = dtl.split("\n", 2)
    table = _irr_table(TRIAL_IRR, trial_windows(), AUTO_IRR["sw_frac"], auto_op(eff))
    dtl = f"{head}\n{int(count.strip()) + 1}\n{rest}".rstrip("\n") + "\n" + table
    irr = (TIO / "irr.ops").read_text().rstrip("\n").split("\n")
    if not any(ln.split()[:1] == [auto_op(eff)] for ln in irr):
        irr.append(f"{auto_op(eff):<22}{AUTO_IRR['mm']:>8.5f}{eff:>14.5f}"
                   + f"{0.0:>14.5f}" * 5 + "  ltm_auto_irrigation_pass")
    return {"management.sch": sched_text(scheds, [B.BEAN_IRR, TRIAL_IRR]),
            "lum.dtl": dtl, "irr.ops": "\n".join(irr) + "\n"}


def run_case(fr: FastRunner, edits: dict[str, str]) -> dict[str, pd.DataFrame]:
    fr.run(edits)
    w = fr.workdir
    out = {t: read_table(w / f"{t}.txt") for t in ("hru_wb_day", "hru_ls_day", "hru_nb_yr")}
    for t, df in out.items():
        df["treatment"] = df.unit.map(HRU)
        if "day" in t:
            df["date"] = pd.to_datetime(dict(year=df.yr, month=df.mon, day=df.day))
    mg = read_mgt(w / "mgt_out.txt")
    mg["treatment"] = mg.hru.map(HRU)
    mg["date"] = pd.to_datetime(dict(year=mg.yr, month=mg.mon, day=mg.day))
    out["mgt"] = mg
    return out


def probe_check(base: dict, noprobe: dict) -> dict:
    """Max |difference| between the measured case with and without daily probes."""
    rep = {}
    for t, cols in (("hru_wb_day", ["irr", "perc", "et", "sw_final"]),
                    ("hru_ls_day", ["percn", "lchlabp", "surqsolp"]),
                    ("hru_nb_yr", ["fertn", "fertp", "nuptake", "puptake", "act_nit_n"])):
        rep[t] = float(np.abs(base[t][cols].to_numpy() - noprobe[t][cols].to_numpy()).max())
    hv = [m[m.operation == "HARV/KILL"][["plant_bioms", "op_var"]].to_numpy()
          for m in (base["mgt"], noprobe["mgt"])]
    rep["harvest"] = float(np.abs(hv[0] - hv[1]).max())
    rep["inert"] = all(v <= TOL for v in rep.values())
    return rep


def soil_mass_kg_ha() -> float:
    """Dry soil mass of the whole profile, kg/ha (soils.sol layer depths and bulk density)."""
    lines = (TIO / "soils.sol").read_text().splitlines()
    nly = int(lines[2].split()[1])
    top, mass = 0.0, 0.0
    for ln in lines[3:3 + nly]:
        dp, bd = (float(x) for x in ln.split()[:2])
        mass += bd * 1000 * (dp - top) / 1000 * 1e4      # g/cm3 -> kg/m3, mm -> m, m2/ha
        top = dp
    return mass


# -- tables ---------------------------------------------------------------------------------
def gross_irr(wb: pd.DataFrame, eff: float | None) -> pd.Series:
    """Applied (gross) water: hru_wb irr is what reaches the soil (amount x efficiency)."""
    e = np.where(wb.yr <= B.START, SPIN_EFF, MEASURED_IRR_EFF if eff is None else eff)
    return wb.irr / e


def applied_inputs() -> pd.DataFrame:
    """N and P each treatment received per year, from data/ltm/management.csv (fertiliser P
    as build_ltm's policy for the years Table S1 gives only a range)."""
    fert_p = json.loads((TIO.parent / "build.json").read_text())["fert_p"]
    m = pd.read_csv(DATA / "management.csv")
    rows = []
    for (trt, yr), g in m[m.year.between(FIRST, LAST)].groupby(["treatment", "year"]):
        man = g[(g.op == "manure") & (trt == "52A")]
        fe = g[g.op == "fert"]
        p_syn = 0.0
        for r in fe.itertuples():
            if pd.isna(r.p_kg_ha):
                p_syn += {"lo": r.p_kg_ha_lo, "hi": r.p_kg_ha_hi,
                          "mid": (r.p_kg_ha_lo + r.p_kg_ha_hi) / 2}[fert_p]
            else:
                p_syn += r.p_kg_ha
        rows.append(dict(treatment=trt, year=yr,
                         manure_n_kg_ha=float((man.min_n_kg_ha + man.org_n_kg_ha).sum()),
                         manure_p_kg_ha=float(man.p_kg_ha.sum()),
                         synthetic_n_kg_ha=float(fe.n_kg_ha.sum()), synthetic_p_kg_ha=p_syn))
    return pd.DataFrame(rows)


def build_tables(res: dict[str, dict]) -> dict[str, pd.DataFrame]:
    yearly, monthly, daily, harvest = [], [], [], []
    up = pd.read_csv(DATA / "uptake.csv").set_index("year")
    crop_of = {v: k for k, v in B.CROP_PLANT.items()}
    for case, (_, eff) in CASES.items():
        o = res[case]
        nb = o["hru_nb_yr"]
        yearly.append(nb[["treatment", "yr", "fertn", "fertp", "nuptake", "puptake"]]
                      .rename(columns={"yr": "year", "fertn": "swat_applied_n_kg_ha",
                                       "fertp": "swat_applied_p_kg_ha",
                                       "nuptake": "n_uptake_kg_ha", "puptake": "p_uptake_kg_ha"})
                      .assign(case=case))
        wb, ls = o["hru_wb_day"], o["hru_ls_day"]
        d = pd.DataFrame({"treatment": wb.treatment, "date": wb.date,
                          "irr_gross_mm": gross_irr(wb, eff), "irr_to_soil_mm": wb.irr,
                          "precip_mm": wb.precip, "perc_mm": wb.perc})
        d = d.merge(ls[["treatment", "date", "percn"]].rename(columns={"percn": "no3n_leached_kg_ha"}),
                    on=["treatment", "date"])
        d["month"] = d.date.dt.to_period("M").dt.to_timestamp()
        monthly.append(d.groupby(["treatment", "month"], as_index=False)
                       [["irr_gross_mm", "irr_to_soil_mm", "precip_mm", "perc_mm",
                         "no3n_leached_kg_ha"]].sum().assign(case=case))
        mg = o["mgt"]
        pr = mg[(mg.name == B.PROBE) & (mg.op_var == 0.0) & mg.yr.between(FIRST, LAST)]
        pr = pr.drop_duplicates(["treatment", "date"])
        daily.append(pr[["treatment", "date", "soil_no3", "soil_solp", "soil_water"]]
                     .rename(columns={"soil_no3": "soil_no3n_kg_ha", "soil_solp": "soil_solp_kg_ha",
                                      "soil_water": "soil_water_mm"}).assign(case=case))
        hv = mg[(mg.operation == "HARV/KILL") & mg.yr.between(FIRST, LAST)]
        for r in hv.itertuples():
            meas = r.treatment == "52A" and r.yr in up.index
            harvest.append(dict(case=case, treatment=r.treatment, year=r.yr, date=r.date.date(),
                                crop=crop_of[r.name], sim_biomass_t_ha=r.plant_bioms / 1000,
                                sim_yield_dm_t_ha=r.op_var / 1000,
                                meas_biomass_t_ha=float(up.biomass_mg_ha[r.yr]) if meas else np.nan))
    yearly = pd.concat(yearly).merge(applied_inputs(), on=["treatment", "year"], how="left")
    daily = pd.concat(daily)
    mass = soil_mass_kg_ha()
    daily["soil_no3n_mg_kg_profile"] = daily.soil_no3n_kg_ha / mass * 1e6
    daily["soil_solp_mg_kg_profile"] = daily.soil_solp_kg_ha / mass * 1e6
    return {"yearly": yearly, "monthly": pd.concat(monthly), "daily": daily,
            "harvest": pd.DataFrame(harvest)}


def measured_soil() -> pd.DataFrame:
    """Dated measured soil values per treatment: 52A profile NO3 / Olsen P series (W1) and the
    spring-2020 0-60 cm NO3 of all three (P1 Table 5; dated 2020-04-01 as ltm_validate does)."""
    ss = pd.read_csv(DATA / "soil_series.csv")
    m = ss[(ss["plot"] == "mean") & ss.date.notna()].copy()
    t5 = ss[(ss["var"] == "no3_mg_kg_0_60") & (ss.year == 2020)].copy()
    t5["date"] = "2020-04-01"
    m = pd.concat([m, t5])
    m["date"] = pd.to_datetime(m.date)
    return m[["treatment", "date", "var", "value", "sd", "source"]]


# -- figures --------------------------------------------------------------------------------
X0 = pd.Timestamp(FIRST, 1, 1)


def xnum(ts) -> float:
    return (pd.Timestamp(ts) - X0).days


def year_ticks() -> tuple[list[float], dict]:
    t = [xnum(pd.Timestamp(y, 1, 1)) for y in range(FIRST, LAST + 2)]
    return t, {v: str(FIRST + i) for i, v in enumerate(t)}


SHAPES = {"profile_no3_mg_kg": ("measured profile NO₃-N (depth not stated)", "dot"),
          "no3_mg_kg_0_60": ("measured NO₃-N 0–60 cm, spring 2020", "square"),
          "olsen_p_mg_kg_0_30": ("measured Olsen P 0–30 cm", "dot"),
          "olsen_p_mg_kg_30_60": ("measured Olsen P 30–60 cm", "ring")}


def marker(x, y, shape, tip) -> str:
    t = f"<title>{html.escape(tip)}</title>"
    if shape == "dot":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{F.INK}" stroke="#fff" stroke-width="2">{t}</circle>'
    if shape == "ring":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#fff" stroke="{F.INK}" stroke-width="2">{t}</circle>'
    return f'<rect x="{x - 4.5:.1f}" y="{y - 4.5:.1f}" width="9" height="9" fill="{F.INK}" stroke="#fff" stroke-width="2">{t}</rect>'


def line_panel(title: str, series: list[tuple], ylab: str, unit: str,
               points: list[tuple] = (), step: bool = False,
               w: int = 960, h: int = 230, fine: bool = False) -> str:
    """Lines over 2013-2020, optional measured markers. A series is (label, colour, values) or
    (label, colour, values, dasharray); a point is (date, value, shape, tip[, text label]).
    ``fine``: quarterly gridlines with month labels and more y ticks. Hover: a crosshair reads
    every series at the nearest x (the chart's JSON in data-*, HOVER_JS)."""
    left, top = 70, 30
    xt, xlab = year_ticks()
    ymax = max([float(s[2].max()) for s in series] + [p[1] for p in points] + [1e-9])
    yt = F.ticks(0, ymax * 1.05, 8 if fine else 5)
    ax = F.Axes(left, top, w - left - 20, h - top - 40, (xt[0], xt[-1]), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold")]
    if fine:      # quarterly minor grid, labelled Apr / Jul / Oct
        for y in range(FIRST, LAST + 1):
            for mon, lab in ((4, "Apr"), (7, "Jul"), (10, "Oct")):
                x = ax.x(xnum(pd.Timestamp(y, mon, 1)))
                body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{ax.y0}" y2="{ax.y0 + ax.h}" '
                            f'stroke="#f1f0ed" stroke-width="1"/>')
                body.append(F.text(x, ax.y0 + ax.h + 13, lab, 9, "middle", F.INK2))
    body.append(ax.grid(xt, yt, "", ylab, xfmt=lambda v: xlab.get(v, "")))
    xs_all = None
    hover = []
    for label, col, s, *rest in series:
        dash = rest[0] if rest else ""
        xs = [xnum(i) for i in s.index]
        if step:      # monthly totals drawn as steps across each month
            ends = [xnum(i + pd.offsets.MonthBegin(1)) for i in s.index]
            pts = []
            for a, b, v in zip(xs, ends, s.values):
                pts += [(ax.x(a), ax.y(v)), (ax.x(b), ax.y(v))]
        else:
            pts = [(ax.x(a), ax.y(v)) for a, v in zip(xs, s.values)]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        body.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round"{da} '
                    f'points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>')
        xs_all = xs
        hover.append({"label": label, "color": col, "y": [round(float(v), 3) for v in s.values]})
    for ts, v, shape, tip, *lab in points:
        x, y = ax.x(xnum(ts)), ax.y(v)
        body.append(marker(x, y, shape, tip))
        if lab:
            body.append(F.text(x + 8, y + 4, lab[0], 10, color=F.INK))
    data = {"x0": X0.strftime("%Y-%m-%d"), "x": xs_all, "monthly": step, "unit": unit,
            "px": [ax.x0, ax.w, ax.y0, ax.h, ax.xd[0], ax.xd[1]], "s": hover}
    return (f'<div class="chart" data-chart=\'{html.escape(json.dumps(data))}\'>'
            + F.svg(w, h, "".join(body), title) + "</div>")


def legend_row(items: list[tuple[str, str, str]], heading: str = "") -> str:
    """One legend row; items are (label, colour, shape in dot/ring/square)."""
    x = 70 + (7 * len(heading) + 12 if heading else 0)
    head = F.text(70, 16, heading, 12, color=F.INK2, weight="bold") if heading else ""
    return F.svg(960, 24, head + F.legend(items, x, 16), heading or "legend")


def line_legend(items: list[tuple[str, str, str]], heading: str) -> str:
    """Legend row of line samples; items are (label, colour, dasharray)."""
    out = [F.text(70, 16, heading, 12, color=F.INK2, weight="bold")]
    cx = 70 + 7 * len(heading) + 12
    for label, col, dash in items:
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{cx}" x2="{cx + 30}" y1="12" y2="12" stroke="{col}" '
                   f'stroke-width="2.5"{da}/>')
        out.append(F.text(cx + 36, 16, label, 12))
        cx += 48 + 6.3 * len(label)
    return F.svg(960, 24, "".join(out), heading)


def input_bars(title: str, data: dict[str, dict[str, list[float]]], ylab: str, unit: str,
               w: int = 960, h: int = 270) -> str:
    """Per year, one stacked bar per treatment (manure + synthetic), labelled under the bar."""
    left, top = 70, 30
    years = list(range(FIRST, LAST + 1))
    totals = [m + s for d in data.values() for m, s in zip(d["manure"], d["synthetic"])]
    yt = F.ticks(0, max(totals + [1e-9]) * 1.05)
    gw = (w - left - 20) / len(years)
    ax = F.Axes(left, top, gw * len(years), h - top - 52, (0, len(years)), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", ylab)]
    bw = (gw - 16 - 4) / 3
    for i, y in enumerate(years):
        gx = left + i * gw + 8
        for j, trt in enumerate(HRU.values()):
            x, base = gx + j * (bw + 2), 0.0
            for src in ("manure", "synthetic"):
                v = data[trt][src][i]
                if v > 0:
                    y0, y1 = ax.y(base), ax.y(base + v)
                    body.append(f'<rect x="{x:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{y0 - y1:.1f}" '
                                f'fill="{SRC_COL[src]}" stroke="#fff" stroke-width="1">'
                                f'<title>{y} {esc(TRT_LABEL[trt])}, {src}: {v:,.0f} {esc(unit)}</title></rect>')
                    base += v
            if base == 0:
                body.append(F.text(x + bw / 2, ax.y(0) - 3, "0", 9, "middle", F.INK2))
            body.append(F.text(x + bw / 2, ax.y(0) + 12, TRT_SHORT[trt], 9, "middle", F.INK2))
        body.append(F.text(left + i * gw + gw / 2, ax.y(0) + 28, str(y), 11, "middle", F.INK2))
    body.append(f'<line x1="{left}" x2="{left + gw * len(years):.1f}" y1="{ax.y(0):.1f}" '
                f'y2="{ax.y(0):.1f}" stroke="{F.INK2}" stroke-width="1"/>')
    return F.svg(w, h, "".join(body), title)


def scatter_panel(title: str, pts: list[tuple[float, float, str]], unit: str,
                  w: int = 470, h: int = 400) -> str:
    """Simulated (y) vs measured (x), 1:1 line, each point labelled; labels nudged apart."""
    left, top = 64, 30
    vmax = max(max(a, b) for a, b, _ in pts)
    t = F.ticks(0, vmax * 1.1)
    side = min(w - left - 20, h - top - 50)
    ax = F.Axes(left, top, side, side, (0, t[-1]), (0, t[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid(t, t, f"Measured, {unit}", f"Simulated, {unit}"),
            f'<line x1="{ax.x(0):.1f}" y1="{ax.y(0):.1f}" x2="{ax.x(t[-1]):.1f}" y2="{ax.y(t[-1]):.1f}" '
            f'stroke="{F.INK2}" stroke-width="1" stroke-dasharray="5 4"/>',
            F.text(ax.x(t[-1]) - 4, ax.y(t[-1]) + 14, "1:1", 11, "end", F.INK2)]
    xy = [(ax.x(m), ax.y(s)) for m, s, _ in pts]
    for (x, y), (m, s, lab) in zip(xy, pts):
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{CASE_COL["measured"]}" '
                    f'stroke="#fff" stroke-width="2"><title>{esc(lab)}: measured {m:,.2f}, '
                    f'simulated {s:,.2f} {esc(unit)}</title></circle>')
    # labels: the nearest spot (8 directions, growing radius) whose box clears every point,
    # every placed label and the plot edge; a leader line when it had to move away
    boxes: list[tuple[float, float, float, float]] = []
    dirs = [(1, 0), (1, -1), (1, 1), (0, -1), (0, 1), (-1, -1), (-1, 1), (-1, 0)]
    for (x, y), (_, _, lab) in sorted(zip(xy, pts), key=lambda q: q[0][0]):
        bw, bh = 5.3 * len(lab), 12
        for r in range(10, 140, 6):
            for dx, dy in dirs:
                bx = x + dx * r - (bw if dx < 0 else bw / 2 if dx == 0 else 0)
                by = y + dy * r - bh / 2
                box = (bx, by, bx + bw, by + bh)
                if (box[0] < ax.x0 or box[2] > ax.x0 + ax.w or box[1] < ax.y0
                        or box[3] > ax.y0 + ax.h):
                    continue
                if any(box[0] - 6 < px < box[2] + 6 and box[1] - 6 < py < box[3] + 6 for px, py in xy):
                    continue
                if any(box[0] < b[2] + 2 and b[0] < box[2] + 2 and box[1] < b[3] + 1
                       and b[1] < box[3] + 1 for b in boxes):
                    continue
                break
            else:
                continue
            break
        boxes.append(box)
        if r > 10:
            cx = min(max(x, box[0]), box[2]); cy = min(max(y, box[1]), box[3])
            body.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" '
                        f'stroke="{F.INK2}" stroke-width="0.75"/>')
        body.append(F.text(box[0], box[3] - 2, lab, 10, color=F.INK))
    return F.svg(w, h, "".join(body), title)


def fit_stats(pts: list[tuple[float, float, str]]) -> str:
    m = np.array([p[0] for p in pts]); s = np.array([p[1] for p in pts])
    return (f"n = {len(m)}, PBIAS {100 * (s.sum() - m.sum()) / m.sum():+.1f} %, "
            f"RMSE {np.sqrt(np.mean((s - m) ** 2)):.2f}")


def bar_panel(title: str, s: pd.Series, col: str, ylab: str, ymax: float,
              w: int = 960, h: int = 200) -> str:
    """Monthly bars; hover via <title> on each bar."""
    left, top = 70, 30
    xt, xlab = year_ticks()
    yt = F.ticks(0, ymax * 1.05)
    ax = F.Axes(left, top, w - left - 20, h - top - 40, (xt[0], xt[-1]), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"),
            ax.grid(xt, yt, "", ylab, xfmt=lambda v: xlab.get(v, ""))]
    for m, v in s.items():
        if v <= 0:
            continue
        a, b = ax.x(xnum(m)), ax.x(xnum(m + pd.offsets.MonthBegin(1)))
        y = ax.y(v)
        body.append(f'<rect x="{a + 1:.1f}" y="{y:.1f}" width="{max(b - a - 2, 1):.1f}" '
                    f'height="{ax.y(0) - y:.1f}" fill="{col}">'
                    f'<title>{m:%b %Y}: {v:,.0f} mm</title></rect>')
    return F.svg(w, h, "".join(body), title)


def year_bars(title: str, labels: list[str], series: list[tuple[str, str, list[float]]],
              meas: list[float | None], ylab: str, unit: str, ymax: float,
              w: int = 960, h: int = 230) -> str:
    """Grouped bars, one group per year (one bar per case), measured values as dots above
    their group. Hover via <title> on each mark."""
    left, top = 70, 30
    yt = F.ticks(0, ymax * 1.05)
    n, k = len(labels), len(series)
    gw = (w - left - 20) / n
    ax = F.Axes(left, top, gw * n, h - top - 40, (0, n), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", ylab)]
    bw = (gw - 24 - 2 * (k - 1)) / k
    for i, lab in enumerate(labels):
        gx = left + i * gw + 12
        body.append(F.text(left + i * gw + gw / 2, top + ax.h + 15, lab, 11, "middle", F.INK2))
        for j, (name, col, vals) in enumerate(series):
            v = vals[i]
            y = ax.y(v)
            body.append(f'<rect x="{gx + j * (bw + 2):.1f}" y="{y:.1f}" width="{bw:.1f}" '
                        f'height="{max(ax.y(0) - y, 0):.1f}" rx="3" fill="{col}">'
                        f'<title>{esc(lab)}, {esc(name)}: {v:,.2f} {esc(unit)}</title></rect>')
        if meas[i] is not None and not np.isnan(meas[i]):
            body.append(marker(left + i * gw + gw / 2, ax.y(meas[i]), "dot",
                               f"{lab}, measured: {meas[i]:,.2f} {unit}"))
    body.append(f'<line x1="{left}" x2="{left + gw * n:.1f}" y1="{ax.y(0):.1f}" '
                f'y2="{ax.y(0):.1f}" stroke="{F.INK2}" stroke-width="1"/>')
    return F.svg(w, h, "".join(body), title)


def year_bars_all(title: str, labels: list[str], vals: dict, meas: list[float | None],
                  ylab: str, unit: str, ymax: float, w: int = 960, h: int = 270) -> str:
    """Every treatment and case together: per year, three treatment groups (52A, Fert, Ctrl)
    of one bar per case, labelled under each group; measured dots above the 52A group."""
    left, top = 70, 30
    yt = F.ticks(0, ymax * 1.05)
    n, trts, cases = len(labels), list(HRU.values()), list(CASES)
    gw = (w - left - 20) / n
    ax = F.Axes(left, top, gw * n, h - top - 52, (0, n), (yt[0], yt[-1]))
    body = [F.text(left, 16, title, 13, weight="bold"), ax.grid(None, yt, "", ylab)]
    sub_gap, bar_gap = 4, 1
    sw = (gw - 12 - sub_gap * (len(trts) - 1)) / len(trts)
    bw = (sw - bar_gap * (len(cases) - 1)) / len(cases)
    for i, lab in enumerate(labels):
        for j, t in enumerate(trts):
            sx = left + i * gw + 6 + j * (sw + sub_gap)
            for k, c in enumerate(cases):
                v = vals[(c, t)][i]
                y = ax.y(v)
                body.append(f'<rect x="{sx + k * (bw + bar_gap):.1f}" y="{y:.1f}" width="{bw:.1f}" '
                            f'height="{max(ax.y(0) - y, 0):.1f}" fill="{CASE_COL[c]}">'
                            f'<title>{esc(lab)}, {esc(TRT_LABEL[t])}, {esc(CASES[c][0])}: '
                            f'{v:,.2f} {esc(unit)}</title></rect>')
            body.append(F.text(sx + sw / 2, ax.y(0) + 12, TRT_SHORT[t], 9, "middle", F.INK2))
            if t == "52A" and meas[i] is not None and not np.isnan(meas[i]):
                body.append(marker(sx + sw / 2, ax.y(meas[i]), "dot",
                                   f"{lab}, 52A measured: {meas[i]:,.2f} {unit}"))
        body.append(F.text(left + i * gw + gw / 2, ax.y(0) + 28, lab, 11, "middle", F.INK2))
    body.append(f'<line x1="{left}" x2="{left + gw * n:.1f}" y1="{ax.y(0):.1f}" '
                f'y2="{ax.y(0):.1f}" stroke="{F.INK2}" stroke-width="1"/>')
    return F.svg(w, h, "".join(body), title)


HOVER_JS = """
<div id="tip" style="position:fixed;display:none;background:#fff;border:1px solid #c9c8c4;
padding:4px 8px;font-size:12px;pointer-events:none"></div>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('.chart').forEach(div => {
  const d = JSON.parse(div.dataset.chart), svg = div.querySelector('svg');
  const [x0, w, y0, h, a, b] = d.px, ns = 'http://www.w3.org/2000/svg';
  const cross = document.createElementNS(ns, 'line');
  cross.setAttribute('stroke', '#52514e'); cross.setAttribute('y1', y0);
  cross.setAttribute('y2', y0 + h); cross.style.display = 'none'; svg.appendChild(cross);
  const base = new Date(d.x0 + 'T00:00:00Z');
  svg.addEventListener('mousemove', ev => {
    const r = svg.getBoundingClientRect(), sx = svg.viewBox.baseVal.width / r.width;
    const px = (ev.clientX - r.left) * sx;
    if (px < x0 || px > x0 + w) { cross.style.display = 'none'; tip.style.display = 'none'; return; }
    const xv = a + (px - x0) / w * (b - a);
    let i = 0, best = Infinity;
    d.x.forEach((v, j) => { const dd = d.monthly ? (xv >= v ? xv - v : Infinity) : Math.abs(v - xv);
      if (dd < best) { best = dd; i = j; } });
    const X = x0 + (d.x[i] - a) / (b - a) * w;
    cross.setAttribute('x1', X); cross.setAttribute('x2', X); cross.style.display = '';
    const dt = new Date(base.getTime() + d.x[i] * 864e5);
    const lab = d.monthly ? dt.toLocaleDateString('en-US', {month: 'short', year: 'numeric', timeZone: 'UTC'})
                          : dt.toISOString().slice(0, 10);
    tip.innerHTML = '<b>' + lab + '</b>' + d.s.map(s => '<br><span style="color:' + s.color +
      '">&#9632;</span> ' + s.label + ': ' + s.y[i].toFixed(2) + ' ' + d.unit).join('');
    tip.style.display = 'block'; tip.style.left = (ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 10) + 'px';
  });
  svg.addEventListener('mouseleave', () => { cross.style.display = 'none'; tip.style.display = 'none'; });
});
</script>
"""


# -- page -----------------------------------------------------------------------------------
def esc(x) -> str:
    return html.escape(str(x))


def num(x, nd=1) -> str:
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{nd}f}"


def table(head: list[str], rows: list[list], groups: list[tuple[str, int]] = (),
          merge_first: bool = False, left: int = 1) -> str:
    """``groups``: a header row above ``head`` of (label, column span); "" leaves a gap.
    ``merge_first``: runs of the same first-column value become one cell. The first ``left``
    columns are left-aligned (text), the rest right-aligned (numbers)."""
    top = ("<tr>" + "".join(f'<th colspan="{n}" class="grp">{esc(g)}</th>' for g, n in groups)
           + "</tr>") if groups else ""
    th = "".join(f'<th{" class=l" if j < left else ""}>{esc(h)}</th>' for j, h in enumerate(head))
    out = []
    for i, r in enumerate(rows):
        cells = [f'<td{" class=l" if j < left else ""}>{c}</td>' for j, c in enumerate(r)]
        if merge_first:
            if i and rows[i - 1][0] == r[0]:
                cells = cells[1:]
            else:
                n = 1
                while i + n < len(rows) and rows[i + n][0] == r[0]:
                    n += 1
                cells[0] = f'<td rowspan="{n}" class="l first">{r[0]}</td>'
        out.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead>{top}<tr>{th}</tr></thead><tbody>{''.join(out)}</tbody></table>"


def case_legend() -> str:
    return legend_row([(CASES[c][0], CASE_COL[c], "square") for c in CASES], "Irrigation case:")


def page(T: dict, meas: pd.DataFrame, check: dict, mass: float, auto_check: dict) -> str:
    Y, M, D, H = T["yearly"], T["monthly"], T["daily"], T["harvest"]
    years = list(range(FIRST, LAST + 1))
    parts = []
    n_fig, n_tab = [0], [0]

    def fig(title: str, body: str, caption: str = "") -> str:
        """A numbered figure: title above (legend and panels inside ``body``), caption below."""
        n_fig[0] += 1
        return (f'<figure><div class="ftitle"><b>Figure {n_fig[0]}.</b> {title}</div>{body}'
                + (f"<figcaption>{caption}</figcaption>" if caption else "") + "</figure>")

    def tab(title: str, body: str, note: str = "") -> str:
        """A numbered table: title above, an optional one-line note under it."""
        n_tab[0] += 1
        return (f'<div class="ttitle"><b>Table {n_tab[0]}.</b> {title}</div>'
                + (f'<div class="tnote">{note}</div>' if note else "") + body)

    y0 = Y[Y.case == "measured"]
    tot = y0.groupby("treatment")[["manure_n_kg_ha", "synthetic_n_kg_ha", "manure_p_kg_ha",
                                   "synthetic_p_kg_ha"]].sum()
    syn52 = y0[(y0.treatment == "52A") & (y0.synthetic_n_kg_ha > 0)].sort_values("year")
    fert = y0[y0.treatment == "fert"]

    # 1. treatments ----------------------------------------------------------------------------
    rows = [[esc(TRT_LABEL[t]), desc_m, desc_f] + [num(tot.loc[t, c], 0) for c in tot.columns]
            for t, desc_m, desc_f in (
                ("52A", "52 Mg/ha DM dairy manure every fall (Oct 20), plowed in",
                 "small urea top-ups in " + ", ".join(str(r.year) for r in syn52.itertuples())
                 + "; no fertilizer P"),
                ("fert", "none", "urea + MAP every year at agronomic rates"),
                ("control", "none", "none"))]
    parts.append(
        "<h2>1. The three treatments</h2>"
        "<p>The trial's south field holds plots that have been managed side by side since fall "
        "2012. They grow the same crops on the same dates, get the same fall tillage and the same "
        "irrigation events, and differ <b>only in what nutrients go on</b>:</p><ul>"
        "<li><b>52A (manure)</b>: 52 Mg/ha dry matter of dairy manure every fall, the trial's "
        f"heaviest annual rate. Over 2013–2020 that is {tot.loc['52A', 'manure_n_kg_ha']:,.0f} kg N/ha "
        f"and {tot.loc['52A', 'manure_p_kg_ha']:,.0f} kg P/ha, far more than the crops remove, so soil "
        "N and P build up. It got synthetic N only in "
        + ", ".join(f"{r.year} ({r.synthetic_n_kg_ha:.0f} kg/ha)" for r in syn52.itertuples())
        + ", and no fertilizer P.</li>"
        "<li><b>Fertilizer only</b>: no manure. Urea and monoammonium phosphate every year at "
        f"agronomic rates: {fert.synthetic_n_kg_ha.min():.0f}–{fert.synthetic_n_kg_ha.max():.0f} kg N/ha "
        f"and {fert.synthetic_p_kg_ha.min():.0f}–{fert.synthetic_p_kg_ha.max():.0f} kg P/ha a year "
        f"({tot.loc['fert', 'synthetic_n_kg_ha']:,.0f} kg N and {tot.loc['fert', 'synthetic_p_kg_ha']:,.0f} "
        "kg P in total). This is conventional practice.</li>"
        "<li><b>Control</b>: no manure and no fertilizer. Crops live on the soil's own N and P, "
        "so it shows what the field supplies unaided.</li></ul>"
        "<p>In the model each treatment is one HRU. The three HRUs share the soil, its initial "
        "state, the weather, crops, operations and irrigation, so every difference between them "
        "in this page comes from the nutrient inputs.</p>"
        + tab("What each treatment receives, and its 2013–2020 nutrient totals",
              table(["Treatment", "Manure", "Synthetic fertilizer", "From manure", "From fertilizer",
                     "From manure", "From fertilizer"], rows,
                    groups=[("", 3), ("N applied 2013–2020, kg/ha", 2),
                            ("P applied 2013–2020, kg/ha", 2)], left=3)))

    # 2. applied N and P -----------------------------------------------------------------------
    def inputs(el):
        return {t: {"manure": y0[y0.treatment == t].sort_values("year")[f"manure_{el}_kg_ha"].tolist(),
                    "synthetic": y0[y0.treatment == t].sort_values("year")[f"synthetic_{el}_kg_ha"].tolist()}
                for t in HRU.values()}
    src_legend = (legend_row([("Manure", SRC_COL["manure"], "square"),
                              ("Synthetic fertilizer", SRC_COL["synthetic"], "square")], "Source:")
                  + F.svg(960, 24, F.text(70, 16, "Bars in each year, left to right:", 12, color=F.INK2,
                                          weight="bold")
                          + F.text(282, 16, "52A  ·  Fert = fertilizer only  ·  Ctrl = control", 12),
                          "bar order"))
    rows = []
    for trt in ("52A", "fert"):
        for r in y0[y0.treatment == trt].sort_values("year").itertuples():
            rows.append([esc(TRT_LABEL[trt]), r.year, num(r.manure_n_kg_ha), num(r.synthetic_n_kg_ha),
                         num(r.swat_applied_n_kg_ha), num(r.manure_p_kg_ha), num(r.synthetic_p_kg_ha),
                         num(r.swat_applied_p_kg_ha)])
    gap = float(np.max(np.abs(y0.manure_n_kg_ha + y0.synthetic_n_kg_ha - y0.swat_applied_n_kg_ha))
                + np.max(np.abs(y0.manure_p_kg_ha + y0.synthetic_p_kg_ha - y0.swat_applied_p_kg_ha)))
    applied_note = ("Total is what the model applied (hru_nb <code>fertn</code>/<code>fertp</code>); "
                    + ("it equals manure + fertilizer in every year. " if gap < 0.05 else
                       f"it differs from manure + fertilizer by up to {gap:.1f} kg/ha. ")
                    + "The control receives nothing and is left out.")
    parts.append(
        "<h2>2. Yearly applied N and P</h2>"
        "<p>Same in every irrigation case. Manure is applied in the fall (Oct 20) and counted in "
        "its calendar year. Manure N is mineral + organic N; manure P is total P.</p>"
        + fig("Nitrogen and phosphorus applied each year, all treatments",
              src_legend
              + input_bars("A. Nitrogen applied", inputs("n"), "N applied, kg/ha", "kg N/ha")
              + input_bars("B. Phosphorus applied", inputs("p"), "P applied, kg/ha", "kg P/ha"),
              "Each year has three stacked bars: 52A, fertilizer only (Fert) and control (Ctrl). "
              "Amber is manure, grey is synthetic fertilizer. The control receives nothing (0). "
              "Hover a bar segment for its value.")
        + tab("N and P applied each year, by source",
              table(["Treatment", "Year", "Manure", "Fertilizer", "Total",
                     "Manure", "Fertilizer", "Total"], rows,
                    groups=[("", 2), ("N applied, kg/ha", 3), ("P applied, kg/ha", 3)],
                    merge_first=True, left=2), applied_note)
        + "<p>The fall-2012 manure (52A) falls in the spin-up year and is not in this table.</p>")

    # 3. monthly irrigation --------------------------------------------------------------------
    ymax = M.irr_gross_mm.max()
    yt_ = M.assign(year=M.month.dt.year).groupby(["case", "year", "treatment"]).irr_gross_mm.sum()
    same_auto = all(np.ptp(yt_[(c, y)].to_numpy()) < 0.5 for c in CASES if c != "measured"
                    for y in years)
    auto_note = ("In this run auto-irrigation also fired identically on all three plots."
                 if same_auto else "Their auto-irrigation differs by plot; see the table and CSV.")
    bars = [bar_panel(f"{'ABC'[i]}. {CASES[c][0]}", M[(M.case == c) & (M.treatment == "52A")]
                      .set_index("month").irr_gross_mm, CASE_COL[c], "Gross mm/month", ymax)
            for i, c in enumerate(CASES)]
    irr52 = {c: M[(M.case == c) & (M.treatment == "52A")].set_index("month").irr_gross_mm for c in CASES}
    together = (case_legend()
                + line_panel("A. Monthly gross irrigation", [(CASES[c][0], CASE_COL[c], irr52[c])
                                                             for c in CASES],
                             "Gross mm/month", "mm", step=True)
                + line_panel("B. Cumulative gross irrigation since Jan 2013",
                             [(CASES[c][0], CASE_COL[c], irr52[c].cumsum()) for c in CASES],
                             "Gross mm, cumulative", "mm", step=True))
    yr = M.assign(year=M.month.dt.year).groupby(["case", "treatment", "year"]).irr_gross_mm.sum()
    same_irr = all(np.ptp([yr[(c, t, y)] for t in HRU.values()]) < 0.5 for c in CASES for y in years)
    irr_trts = ["52A"] if same_irr else list(HRU.values())
    rows = [([] if same_irr else [esc(TRT_LABEL[t])]) + [esc(CASES[c][0])]
            + [num(yr[(c, t, y)], 0) for y in years] + [num(sum(yr[(c, t, y)] for y in years), 0)]
            for t in irr_trts for c in CASES]
    parts.append(
        "<h2>3. Monthly irrigation</h2>"
        "<p>Gross applied water (mm/month). SWAT+ puts amount × efficiency into the soil; "
        "gross = hru_wb <code>irr</code> ÷ efficiency. The figures show 52A; the fertilizer-only "
        "and control plots get the same measured events. " + auto_note + "</p>"
        + fig("Gross irrigation on 52A, all three irrigation cases together", together,
              "A: monthly depth; B: running total. Hover for every case's value in that month.")
        + fig("Monthly gross irrigation on 52A, each irrigation case separately", "".join(bars),
              "Same data as the figure above, one case per panel on a shared y scale. Hover a bar "
              "for its value.")
        + tab("Gross irrigation applied each year, mm"
              + (" (the same on all three treatments)" if same_irr else ""),
              table(([] if same_irr else ["Treatment"]) + ["Irrigation case"]
                    + [str(y) for y in years] + ["2013–2020"], rows, merge_first=not same_irr,
                    left=1 if same_irr else 2))
        + f"<p>Check: auto-irrigation at eff 1.0 applies {auto_check['sim_mm']:,.1f} mm to 52A "
          f"over 2013–2020; scripts/ltm_fit_auto_irr.py recorded {auto_check['fit_mm']:,.1f} mm "
          f"(model/ltm/auto_irr.json). Measured events total {auto_check['meas_mm']:,.1f} mm.</p>")

    # 4. monthly leached N ---------------------------------------------------------------------
    trt_legend = line_legend([(TRT_LABEL[t], F.INK, TRT_DASH[t]) for t in HRU.values()],
                             "Treatment (line type, panel D):")
    panels = []
    for i, t in enumerate(HRU.values()):
        ser = [(CASES[c][0], CASE_COL[c], M[(M.case == c) & (M.treatment == t)].set_index("month")
                .no3n_leached_kg_ha) for c in CASES]
        panels.append(line_panel(f"{'ABC'[i]}. {TRT_LABEL[t]}", ser, "kg N/ha/month", "kg/ha", step=True))
    panels.append(line_panel(
        "D. All treatments and irrigation cases together",
        [(f"{TRT_SHORT[t]} · {CASES[c][0]}", CASE_COL[c],
          M[(M.case == c) & (M.treatment == t)].set_index("month").no3n_leached_kg_ha, TRT_DASH[t])
         for t in HRU.values() for c in CASES], "kg N/ha/month", "kg/ha", step=True, h=320, fine=True))
    lr = M.assign(year=M.month.dt.year).groupby(["case", "treatment", "year"]).no3n_leached_kg_ha.sum()
    rows = [[esc(TRT_LABEL[t]), esc(CASES[c][0])] + [num(lr[(c, t, y)]) for y in years]
            + [num(sum(lr[(c, t, y)] for y in years))] for t in HRU.values() for c in CASES]
    parts.append(
        "<h2>4. Monthly NO₃-N leached</h2>"
        "<p>NO₃-N leaving the bottom of the 1.52 m profile (hru_ls <code>percn</code>), "
        "summed by month. <b>Leaching is not validated on this site</b>: there is no on-site "
        "measurement.</p>"
        + fig("Monthly NO₃-N leached below the profile, by treatment", case_legend() + trt_legend
              + "".join(panels),
              "A–C: one panel per treatment, each with its own y scale. D: all nine lines on one "
              "scale; colour is the irrigation case and line type the treatment. Hover for every "
              "line's value.")
        + tab("NO₃-N leached below the 1.52 m profile each year, kg N/ha",
              table(["Treatment", "Irrigation case"] + [str(y) for y in years] + ["2013–2020"],
                    rows, merge_first=True, left=2)))

    # 5. biomass and yield ---------------------------------------------------------------------
    hv = H.set_index(["case", "treatment", "year"])
    up = pd.read_csv(DATA / "uptake.csv").set_index("year")
    yl = pd.read_csv(DATA / "yield.csv")
    meas_y = yl[yl.year > 0].groupby(["year", "crop"]).yield_dm_mg_ha.mean()
    yi = Y.set_index(["case", "treatment", "year"])
    ylabels = [f"{y} {hv.loc[('measured', '52A', y)].crop}" for y in years]
    bio_pts, yld_pts = [], []
    for y in years:
        r0 = hv.loc[("measured", "52A", y)]
        if not np.isnan(r0.meas_biomass_t_ha):
            bio_pts.append((float(r0.meas_biomass_t_ha), float(r0.sim_biomass_t_ha), f"{y} {r0.crop}"))
        my = meas_y.get((y, r0.crop), np.nan)
        if not np.isnan(my):
            yld_pts.append((float(my), float(r0.sim_yield_dm_t_ha), f"{y} {r0.crop}"))
    pot_meas = yl[(yl.treatment == "52A") & (yl.crop == "potato")].yield_fresh_mg_ha.mean()
    pot_sim = float(hv.loc[("measured", "52A", int(yl[yl.crop == "potato"].year.max()))].sim_yield_dm_t_ha)
    sb_meas = json.loads((ROOT / "runs" / "ltm_validation.json").read_text())["sugarbeet_root_dm"]
    sb_yrs = [y for y in years if hv.loc[("measured", "52A", y)].crop == "sugarbeet"
              and hv.loc[("measured", "52A", y)].sim_yield_dm_t_ha > 0 and y >= 2018]
    sb_err = {t: 100 * (np.mean([hv.loc[("measured", t, y)].sim_yield_dm_t_ha for y in sb_yrs])
                        / sb_meas[t]["meas_t"] - 1) for t in HRU.values()}
    bias_note = (f"<p><b>Crops the scatter does not cover.</b> Potato tuber: measured "
                 f"{pot_meas:.1f} Mg/ha fresh × {POTA_DM:.3f} dry matter = {pot_meas * POTA_DM:.1f} t DM/ha "
                 f"against {pot_sim:.1f} simulated ({(pot_sim / (pot_meas * POTA_DM) - 1) * 100:+.0f} %). "
                 f"Sugarbeet root dry matter, simulated {'/'.join(map(str, sb_yrs))} against the trial's "
                 "multi-year mean: "
                 + ", ".join(f"{TRT_LABEL[t]} {sb_err[t]:+.0f} %" for t in HRU.values())
                 + ". Alfalfa and corn silage, which only the rotation experiment uses, have no "
                 "measurement on this field. These biases carry into any result that changes the "
                 "crop mix.</p>")
    scatter = (legend_row([("52A, measured irrigation, one point per crop-year", CASE_COL["measured"], "dot")],
                          "Points:")
               + scatter_panel("A. Above-ground biomass at harvest", bio_pts, "t/ha")
               + scatter_panel("B. Harvested grain yield, dry matter", yld_pts, "t/ha"))

    def year_figs(get, meas_col, ylab, unit):
        """One panel per treatment on a shared y scale; measured dots on 52A only."""
        vals = {(c, t): [float(get(c, t, y)) for y in years] for c in CASES for t in HRU.values()}
        mvals = [float(up[meas_col][y]) if y in up.index else None for y in years]
        ymax = max([max(v) for v in vals.values()] + [m for m in mvals if m is not None])
        legend = case_legend() + legend_row([("measured, 52A", F.INK, "dot")], "Measured:")
        return legend + "".join(
            year_bars(f"{'ABC'[i]}. {TRT_LABEL[t]}", ylabels,
                      [(CASES[c][0], CASE_COL[c], vals[(c, t)]) for c in CASES],
                      mvals if t == "52A" else [None] * len(years), ylab, unit, ymax)
            for i, t in enumerate(HRU.values())) + year_bars_all(
            "D. All treatments and irrigation cases together", ylabels, vals, mvals, ylab, unit, ymax)

    short = {"measured": "measured irr.", "auto100": "auto eff 1.0", "auto080": "auto eff 0.80"}
    sim_heads = ["Measured"] + [f"Sim., {short[c]}" for c in CASES]
    meas_note = "Measured values exist for 52A only (– where none). Sim. = simulated."
    rows = []
    for t in HRU.values():
        for y in years:
            r0 = hv.loc[("measured", t, y)]
            my = meas_y.get((y, r0.crop), np.nan) if t == "52A" else np.nan
            rows.append([esc(TRT_LABEL[t]), y, esc(r0.crop), num(r0.meas_biomass_t_ha, 2)]
                        + [num(hv.loc[(c, t, y)].sim_biomass_t_ha, 2) for c in CASES]
                        + [num(float(my), 2)]
                        + [num(hv.loc[(c, t, y)].sim_yield_dm_t_ha, 2) for c in CASES])
    parts.append(
        "<h2>5. Biomass and yield at harvest</h2>"
        "<p>Above-ground biomass on the harvest/kill day (mgt_out <code>plant_bioms</code>) and "
        "the harvested dry yield (<code>op_var</code>), t/ha. Measured biomass exists for 52A "
        "only (2013–2019); measured dry yield only for its grain years. The 2014 sugarbeet was not "
        "harvested (tilled in), so its yield is 0. "
        "<b>Crop parameters are Ai-SWAT-Plus's, copied verbatim and not fitted here</b>: "
        "potato under-yields, and spring wheat uses Ai-SWAT-Plus <code>wwht</code>.</p>"
        + fig("Simulated against measured biomass and grain yield, 52A", scatter,
              f"Points on the dashed 1:1 line would be a perfect match; below it the model "
              f"under-predicts. A: {fit_stats(bio_pts)} t/ha. B: {fit_stats(yld_pts)} t/ha. "
              "Hover a point for its values.")
        + bias_note
        + fig("Simulated biomass at harvest by treatment and irrigation case",
              year_figs(lambda c, t, y: hv.loc[(c, t, y)].sim_biomass_t_ha, "biomass_mg_ha",
                        "Biomass, t/ha", "t/ha"),
              "A–C: one panel per treatment on a shared y scale; measured 52A biomass as black "
              "dots. D: all three treatments side by side in each year (52A, Fert = fertilizer "
              "only, Ctrl = control), one bar per irrigation case. Hover a bar or dot for its value.")
        + tab("Above-ground biomass at harvest and harvested yield, measured and simulated",
              table(["Treatment", "Year", "Crop"] + sim_heads + sim_heads, rows,
                    groups=[("", 3), ("Biomass at harvest, t/ha", 4),
                            ("Harvested yield, dry matter, t/ha", 4)], merge_first=True,
                    left=3),
              meas_note + " Measured yield is for the grain years only."))

    # 6. uptake --------------------------------------------------------------------------------
    same = [y for y in years
            if all(np.ptp([yi.loc[(c, t, y)].n_uptake_kg_ha for t in HRU.values()]) < 0.05
                   and np.ptp([hv.loc[(c, t, y)].sim_biomass_t_ha for t in HRU.values()]) < 0.005
                   for c in CASES)]
    same_note = (f"<p>Simulated biomass and N uptake are the same on all three treatments in "
                 f"{', '.join(map(str, same))} (every irrigation case): in those years the crops "
                 "are not N-limited even on the control.</p>" if same else "")
    rows = []
    for t in HRU.values():
        for y in years:
            mn = up.n_up_kg_ha.get(y) if t == "52A" else None
            mp = up.p_up_kg_ha.get(y) if t == "52A" else None
            rows.append([esc(TRT_LABEL[t]), y, esc(hv.loc[("measured", t, y)].crop), num(mn)]
                        + [num(yi.loc[(c, t, y)].n_uptake_kg_ha) for c in CASES] + [num(mp)]
                        + [num(yi.loc[(c, t, y)].p_uptake_kg_ha) for c in CASES])
    cap = ("A–C: one panel per treatment on a shared y scale; measured 52A uptake as black dots. "
           "D: all three treatments side by side in each year (52A, Fert = fertilizer only, "
           "Ctrl = control), one bar per irrigation case. Hover a bar or dot for its value.")
    parts.append(
        "<h2>6. N and P uptake</h2>"
        "<p>Plant N and P uptake over the calendar year (hru_nb <code>nuptake</code>/"
        "<code>puptake</code>), kg/ha. Each year has one crop. Measured uptake is 52A only, "
        "2013–2019.</p>" + same_note
        + fig("Plant N uptake by treatment and irrigation case",
              year_figs(lambda c, t, y: yi.loc[(c, t, y)].n_uptake_kg_ha, "n_up_kg_ha",
                        "N uptake, kg/ha", "kg/ha"), cap)
        + fig("Plant P uptake by treatment and irrigation case",
              year_figs(lambda c, t, y: yi.loc[(c, t, y)].p_uptake_kg_ha, "p_up_kg_ha",
                        "P uptake, kg/ha", "kg/ha"), cap)
        + tab("Plant N and P uptake per year, measured and simulated",
              table(["Treatment", "Year", "Crop"] + sim_heads + sim_heads, rows,
                    groups=[("", 3), ("N uptake, kg/ha", 4), ("P uptake, kg/ha", 4)],
                    merge_first=True, left=3), meas_note))

    # 7 + 8. daily soil ------------------------------------------------------------------------
    def soil(col_kg, col_mg, vars_, name, unit_note):
        def series(col, t, c, dash=False):
            s = D[(D.case == c) & (D.treatment == t)].set_index("date")[col]
            if dash:
                return (f"{TRT_SHORT[t]} · {CASES[c][0]}", CASE_COL[c], s, TRT_DASH[t])
            return (CASES[c][0], CASE_COL[c], s)

        def points(t_sel, labelled):
            mm = meas[meas.treatment.isin(t_sel) & meas["var"].isin(vars_)]
            return [(r.date, r.value, SHAPES[r.var][1],
                     f"{r.date:%Y-%m-%d} {TRT_LABEL[r.treatment]}, {SHAPES[r.var][0]}: {r.value:.1f} mg/kg")
                    + ((TRT_SHORT[r.treatment],) if labelled and r.var == "no3_mg_kg_0_60" else ())
                    for r in mm.itertuples()]

        meas_legend = legend_row([(SHAPES[v][0], F.INK, SHAPES[v][1]) for v in vars_], "Measured:")
        every = [series(col_kg, t, c, True) for t in HRU.values() for c in CASES]
        every_mg = [series(col_mg, t, c, True) for t in HRU.values() for c in CASES]
        out = [fig(f"{name}, daily: whole profile by treatment (kg/ha)",
                   case_legend() + trt_legend + "".join(
                       line_panel(f"{'ABC'[i]}. {TRT_LABEL[t]}", [series(col_kg, t, c) for c in CASES],
                                  "kg/ha (0–1520 mm)", "kg/ha")
                       for i, t in enumerate(HRU.values()))
                   + line_panel("D. All treatments and irrigation cases together", every,
                                "kg/ha (0–1520 mm)", "kg/ha", h=380, fine=True),
                   "A–C: one panel per treatment, each with its own y scale. D: all nine lines on "
                   "one scale; colour is the irrigation case and line type the treatment. D's "
                   "gridlines are quarterly. Hover for every line's value on a date.")]
        out.append(fig(f"{name}, daily: profile mean by treatment (mg/kg), with measured values",
                       case_legend() + trt_legend + meas_legend + "".join(
                           line_panel(f"{'ABC'[i]}. {TRT_LABEL[t]}", [series(col_mg, t, c) for c in CASES],
                                      "mg/kg", "mg/kg", points=points([t], False))
                           for i, t in enumerate(HRU.values()))
                       + line_panel("D. All treatments and irrigation cases together, with measured "
                                    "values", every_mg, "mg/kg", "mg/kg",
                                    points=points(list(HRU.values()), True), h=380, fine=True),
                       "A–C: one panel per treatment, each with its own y scale. D: all nine lines "
                       "on one scale (colour = irrigation case, line type = treatment), quarterly "
                       "gridlines. " + unit_note))
        return "".join(out)

    parts.append(
        "<h2>7. Soil nitrate-N, daily</h2>"
        "<p>Read from a 0-kg probe on every day (mgt_out <code>soil_no3</code>, the start-of-day "
        "state). SWAT+ reports only the <b>whole-profile total (0–1520 mm)</b>; no output on "
        "disk gives soil NO₃ by layer. The mg/kg panels divide that total by the profile's dry "
        f"soil mass ({mass / 1e6:,.2f} × 10⁶ kg/ha, soils.sol bulk density × depth). That is a "
        "1.52 m mean, so it is <b>not depth-matched</b> to the measured samples (depth not "
        "stated, or 0–60 cm). Compare shape and timing, not level.</p>"
        + soil("soil_no3n_kg_ha", "soil_no3n_mg_kg_profile",
               ["profile_no3_mg_kg", "no3_mg_kg_0_60"], "Soil NO₃-N",
               "Measured: 52A profile NO₃-N (depth not stated) and spring-2020 0–60 cm NO₃-N for all "
               "three treatments (labelled 52A / Fert / Ctrl)."))
    parts.append(
        "<h2>8. Soil soluble P, daily</h2>"
        "<p>SWAT+ solution (labile) P from the same probes (mgt_out <code>soil_solp</code>), "
        "whole profile. Measured values are <b>Olsen P</b> (NaHCO₃-extractable) at 0–30 and "
        "30–60 cm. That is a different pool and depth from SWAT solution P, so compare trends "
        "only.</p>"
        + soil("soil_solp_kg_ha", "soil_solp_mg_kg_profile",
               ["olsen_p_mg_kg_0_30", "olsen_p_mg_kg_30_60"], "Soil solution P",
               "Measured Olsen P exists for 52A only. The three irrigation cases give almost the same "
               "solution P, so their lines lie on top of each other (the last drawn, green, shows)."))

    files = "".join(f"<li><code>runs/ltm_nutrient_summary/{n}.csv</code></li>"
                    for n in ("yearly", "monthly", "daily", "harvest", "measured_soil"))
    status = "inert" if check["inert"] else "NOT inert"
    head = ("<h1>Kimberly LTM model: framework and calibration</h1>"
            "<p>This page shows the calibrated SWAT+ model of the USDA-ARS long-term manure trial "
            "at Kimberly, Idaho (south field, 2013–2020 after a 2012 bean spin-up), run through "
            "this repository's framework: the official rev 62 engine driven from Python, one HRU "
            "per treatment, the trial's operations replayed day by day, and 0-kg probe operations "
            "that read the soil's nitrate, phosphorus and water every day. It compares the model "
            "with the trial's measurements of <b>crop biomass and yield</b>, <b>plant N and P "
            "uptake</b>, <b>soil nitrate</b> and <b>soil phosphorus</b>.</p>"
            "<p><b>What is calibrated.</b> One soil parameter, the active-humus fraction, is fitted "
            "to the control's measured N mineralisation. Crop parameters come from the Ai-SWAT-Plus "
            "crop calibration unchanged; nothing is fitted to the yields or soil data shown here, "
            "so these comparisons are an independent check. Leaching has no on-site measurement.</p>"
            f"<p><b>Companion page.</b> The <a href=\"{RESULTS_URL}\">experiment results</a> use "
            "this model's 52A plot as the environment for the three management experiments "
            "(rotation, nitrogen, irrigation). This page covers the model and its agreement with the "
            "trial; that page covers only what the experiments found, and refers back here.</p>"
            "<p>Weather is gridMET at the field. Three irrigation cases, all on the measured rotation, "
            "fertilizer and manure:</p><ul>"
            "<li><b>Measured irrigation</b>: the trial's daily events, replayed at efficiency 1.0.</li>"
            f"<li><b>Auto-irrigation, eff 1.0</b>: one 25.4 mm pass whenever profile plant-available "
            f"water is below {AUTO_IRR['sw_frac']:.4f} × its field-capacity value, inside each crop's "
            "irrigation window. The trigger was fitted at this efficiency to apply the trial's "
            "2013–2020 total.</li>"
            "<li><b>Auto-irrigation, eff 0.80</b>: the same rule at the experiments' base efficiency. "
            "Only 80 % of each pass reaches the soil, so it pumps more gross water.</li></ul>"
            f"<p>Daily probes: {status} (max |Δ| vs no daily probes: "
            + ", ".join(f"{k} {v:.2g}" for k, v in check.items() if k != "inert")
            + f"). Data files:</p><ul>{files}</ul>")
    style = ("<style>body{font-family:Calibri,sans-serif;background:#fff;color:#000;margin:24px;"
             "max-width:1000px}table{border-collapse:collapse;font-size:13px;margin:8px 0}"
             "th,td{border:1px solid #ccc;padding:2px 6px;text-align:right}"
             "th.l,td.l{text-align:left}code{font-family:Calibri,sans-serif}"
             "figure{margin:18px 0 24px 0}.ftitle,.ttitle{font-size:15px;margin:14px 0 6px 0}"
             "figcaption{font-size:13px;color:#333;margin-top:4px}"
             ".tnote{font-size:13px;color:#333;margin-bottom:4px}"
             "th.grp{text-align:center;border-bottom:1px solid #999}"
             "td.first{vertical-align:top}"
             "</style>")
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>LTM water and nutrient summary</title>" + style + "</head><body>"
            + head + "".join(parts) + HOVER_JS + "</body></html>\n")


def main() -> None:
    scheds = base_schedules()
    res = {}
    with FastRunner(TIO, trim_outputs=False, editable=EDITABLE) as fr:
        for case, (_, eff) in CASES.items():
            res[case] = run_case(fr, case_edits(scheds, eff))
            print(f"ran {case}")
        noprobe = run_case(fr, case_edits(scheds, None, probes=False))
    check = probe_check(res["measured"], noprobe)
    print("probe check:", check)
    if not check["inert"]:
        raise SystemExit("daily probes changed the simulation; not writing the summary")

    T = build_tables(res)
    meas = measured_soil()
    mass = soil_mass_kg_ha()
    m = T["monthly"]
    irr = pd.read_csv(DATA / "irrigation_daily.csv", parse_dates=["date"])
    auto_check = {
        "sim_mm": float(m[(m.case == "auto100") & (m.treatment == "52A")].irr_gross_mm.sum()),
        "fit_mm": float(json.loads((TIO.parent / "auto_irr.json").read_text())["auto_mm"]),
        "meas_mm": float(irr[irr.date.dt.year.between(FIRST, LAST)].irr_mm.sum())}
    print("auto-irrigation check:", auto_check)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in T.items():
        df.to_csv(OUT_DIR / f"{name}.csv", index=False, float_format="%.4f")
    meas.to_csv(OUT_DIR / "measured_soil.csv", index=False)
    OUT_HTML.write_text(page(T, meas, check, mass, auto_check))
    print(f"wrote {OUT_HTML.relative_to(ROOT)} and {OUT_DIR.relative_to(ROOT)}/*.csv")


if __name__ == "__main__":
    main()
