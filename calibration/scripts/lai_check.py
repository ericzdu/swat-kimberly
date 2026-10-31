#!/usr/bin/env python3
"""Plot daily LAI against the cutting dates — the quickest way to see a cut actually happened.

The collaborator's own check (2026-10-08): alfalfa LAI should climb, drop vertically to zero at
each of the four cuttings, regrow, and stay at zero after the last one. A sawtooth with four
teeth is the whole test, and it catches things a seasonal ET total hides — a cut that did not
fire, a cut on the wrong day, or the stock engine's partial ``lai x (1 - 0.5 hi)`` decline
instead of the reset in ``engine_patches/lai_reset_on_cut.patch``.

Writes ``runs/et_raw/lai_check.html`` (one panel per year, cut dates marked) and prints a
pass/fail line per cutting: LAI must be above zero the day before and exactly zero on the day.

    uv run python scripts/lai_check.py              # alfalfa, the three target years
    uv run python scripts/lai_check.py --crops ALFA CSIL
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import et_calibrate as etc  # noqa: E402
import monoculture as mono  # noqa: E402
from swat_gym.fastrunner import FastRunner  # noqa: E402

OUT = ROOT / "runs" / "et_raw" / "lai_check.html"
YEARS = (2020, 2021, 2022)
LAI, CUT = "#2f6fba", "#d0642f"
MON_START = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def lai_svg(d: pd.DataFrame, cuts: dict[int, str], year: int) -> str:
    W, H, L, R, T, B = 620, 220, 40, 12, 14, 28
    ymax = max(1.0, float(d["lai"].max())) * 1.12
    xs = lambda j: L + (W - L - R) * (j - 1) / 365.0
    ys = lambda v: T + (H - T - B) * (1 - v / ymax)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    step = 1.0 if ymax > 3 else 0.5
    v = 0.0
    while v <= ymax:
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" stroke="#ddd"/>'
                   f'<text x="{L-5}" y="{ys(v)+4:.1f}" text-anchor="end" font-size="10">'
                   f'{v:.1f}</text>')
        v += step
    for m, j in enumerate(MON_START):
        out.append(f'<text x="{xs(j):.1f}" y="{H-B+13}" text-anchor="start" font-size="9">'
                   f'{MON[m]}</text>')
    # the cuttings, drawn under the curve so the drop stays readable
    for j, label in sorted(cuts.items()):
        out.append(f'<line x1="{xs(j):.1f}" x2="{xs(j):.1f}" y1="{T}" y2="{H-B}" '
                   f'stroke="{CUT}" stroke-width="1" stroke-dasharray="3 3"/>'
                   f'<text x="{xs(j)+3:.1f}" y="{T+10}" font-size="9" fill="{CUT}">{label}</text>')
    pts = " ".join(f"{xs(int(r.jday)):.1f},{ys(float(r.lai)):.1f}" for r in d.itertuples())
    out.append(f'<polyline points="{pts}" fill="none" stroke="{LAI}" stroke-width="1.6"/>')
    out.append(f'<text x="{L}" y="{T-3}" font-size="11">LAI — {year}</text>')
    out.append("</svg>")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crops", nargs="*", default=["ALFA"])
    ap.add_argument("--calib-start", type=int, default=2015)
    ap.add_argument("--calib-years", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    shared, _ = mono.load_et_fit()
    sw = shared.get("irr_sw_frac", mono.IRR_SW_FRAC)
    work = args.out.parent / "_work_lai"
    parts = ["<title>Alfalfa LAI Check</title>",
             "<style>body{background:#fff;color:#000;font-family:Calibri,Carlito,sans-serif;"
             "padding:16px 24px;max-width:760px;margin:0 auto}h1{font-size:20px;margin:0 0 4px}"
             "h2{font-size:16px;margin:20px 0 2px}p{font-size:14px;margin:2px 0 10px}"
             "td,th{font-size:13px;padding:2px 8px;text-align:right;border-bottom:1px solid #ddd}"
             "th:first-child,td:first-child{text-align:left}"
             "table{border-collapse:collapse}</style>",
             "<h1>Daily LAI against the cutting dates</h1>"]
    ok_all = True
    for code in args.crops:
        plt_name = mono.CROPS[code][0]
        tio = etc.CropFit._build(code, args.calib_start, args.calib_years,
                                 work / f"_tio_{plt_name}", sw)
        mono.apply_et_fit(tio, plt_name)
        r = FastRunner(txtinout=tio, keep={"hru_pw": {"daily"}}, editable=frozenset())
        r.run()
        pw = r.read("hru_pw_day.txt")
        r.close()

        cuts = {mono._doy(h): f"{h[0]}/{h[1]}" for h in mono.CROPS[code][2]}
        parts.append(f"<h2>{code} ({plt_name}) — {len(cuts)} cutting(s): "
                     f"{', '.join(cuts[k] for k in sorted(cuts))}</h2>")
        rows = ["<table><tr><th>year</th>"
                + "".join(f"<th>{cuts[k]}</th>" for k in sorted(cuts)) + "</tr>"]
        for y in YEARS:
            d = pw[pw["yr"] == y].sort_values("jday")
            parts.append(lai_svg(d, cuts, y))
            idx = d.set_index("jday")["lai"]
            cells = []
            yld = d.set_index("jday")["yield"]
            for j in sorted(cuts):
                before = float(idx.get(j - 1, 0.0))
                on = float(idx.get(j, float("nan")))
                # A drop to zero is only a *cutting* if biomass left the field. SWAT+ also zeroes
                # LAI at dormancy (alfalfa does this in early November here), with yield 0 and
                # biomass retained -- so testing LAI alone would call dormancy a harvest.
                harvested = float(yld.get(j, 0.0))
                good = on <= 1e-3 and before > 1e-3 and harvested > 0
                ok_all &= good
                cells.append(f"<td>{before:.2f} &rarr; {on:.2f}, {harvested:.0f} kg"
                             f"{'' if good else ' <b>!</b>'}</td>")
                print(f"{code} {y} cut {cuts[j]:>5}: LAI {before:6.3f} -> {on:6.3f}  "
                      f"yield {harvested:8.1f} kg/ha  "
                      f"{'cut ok' if good else 'NOT A HARVEST'}")
            rows.append(f"<tr><td>{y}</td>" + "".join(cells) + "</tr>")
        rows.append("</table>")
        parts.append("<p>LAI the day before each cut &rarr; LAI on the cut day, and the biomass "
                     "removed. A drop to zero with no yield is dormancy, not a cutting.</p>")
        parts.extend(rows)
    args.out.write_text("\n".join(parts))
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'all cuts reset LAI to 0' if ok_all else 'SOME CUTS DID NOT RESET LAI'}")
    print(f"wrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
