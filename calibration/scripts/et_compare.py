#!/usr/bin/env python3
"""Overlay two ``runs/et_raw`` directories so a change can be *seen*, not just tabulated.

Built 2026-10-08 to verify the restore after a SWAT+ editor round-trip replaced the model
template. A scorecard that agrees to two decimals can still hide a month-shape difference, so
this draws both simulated series against the same observations and reports the largest monthly
divergence per crop.

    uv run python scripts/et_compare.py                      # restored vs runs/et_raw_2026-09-25
    uv run python scripts/et_compare.py --ref runs/et_raw_2026-09-15 --out /tmp/cmp.html
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["BARL", "CSIL", "WWHT", "ALFA", "SGBT", "PTBN", "POTA"]
NAMES = {"BARL": "Spring barley", "CSIL": "Corn silage", "WWHT": "Winter wheat",
         "ALFA": "Alfalfa", "SGBT": "Sugarbeet", "PTBN": "Pinto bean", "POTA": "Potato"}
OBS, REF, NOW = "#d0642f", "#9aa0a6", "#2f6fba"
MON = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]


def series_svg(g: pd.DataFrame) -> str:
    """obs, reference sim (thick grey) and current sim (thin blue) on one axis."""
    W, H, L, R, T, B = 620, 230, 44, 10, 14, 28
    ymax = float(np.ceil(max(g.obs_mm.max(), g.sim_ref.max(), g.sim_now.max()) / 50) * 50)
    years = sorted(g.yr.unique())
    slots, x_of = [], {}
    for i, y in enumerate(years):
        for m in sorted(g[g.yr == y].mon):
            x_of[(y, m)] = len(slots); slots.append((y, m))
        if i < len(years) - 1:
            slots.append(None)
    n = len(slots)
    xs = lambda k: L + (W - L - R) * (k + 0.5) / n
    ys = lambda v: T + (H - T - B) * (1 - v / ymax)
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px">']
    for v in np.arange(0, ymax + 1, 50):
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" stroke="#ddd"/>'
                   f'<text x="{L-6}" y="{ys(v)+4:.1f}" text-anchor="end" font-size="10">{v:.0f}</text>')
    for k, s in enumerate(slots):
        if s:
            out.append(f'<text x="{xs(k):.1f}" y="{H-B+12}" text-anchor="middle" '
                       f'font-size="9">{MON[s[1]-1]}</text>')
    for y in years:
        ks = [x_of[(y, m)] for m in g[g.yr == y].mon]
        out.append(f'<text x="{(xs(min(ks))+xs(max(ks)))/2:.1f}" y="{H-3}" '
                   f'text-anchor="middle" font-size="10">{y}</text>')
    for col, color, w in (("obs_mm", OBS, 1.6), ("sim_ref", REF, 4.0), ("sim_now", NOW, 1.6)):
        for y in years:
            gy = g[g.yr == y].sort_values("mon")
            pts = " ".join(f"{xs(x_of[(y, m)]):.1f},{ys(v):.1f}" for m, v in zip(gy.mon, gy[col]))
            out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                       f'stroke-width="{w}" stroke-linecap="round"/>')
    out.append(f'<text x="{L}" y="{T-3}" font-size="10">mm / month</text>')
    for i, (c, lab) in enumerate(((OBS, "eeMetric"), (REF, "reference run"), (NOW, "restored run"))):
        out.append(f'<circle cx="{W-150}" cy="{T+4+i*13}" r="4" fill="{c}"/>'
                   f'<text x="{W-142}" y="{T+8+i*13}" font-size="10">{lab}</text>')
    out.append("</svg>")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", type=Path, default=ROOT / "runs" / "et_raw")
    ap.add_argument("--ref", type=Path, default=ROOT / "runs" / "et_raw_2026-09-25")
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "et_raw" / "et_restore_check.html")
    args = ap.parse_args()

    a = pd.read_csv(args.now / "monthly.csv").rename(columns={"sim_mm": "sim_now"})
    b = pd.read_csv(args.ref / "monthly.csv").rename(
        columns={"sim_mm": "sim_ref", "obs_mm": "obs_ref"})
    m = a.merge(b[["crop", "yr", "mon", "sim_ref", "obs_ref"]], on=["crop", "yr", "mon"])
    if len(m) != len(a):
        raise SystemExit(f"month rows do not line up: {len(a)} vs matched {len(m)}")
    m["d"] = (m.sim_now - m.sim_ref).abs()
    obs_d = (m.obs_mm - m.obs_ref).abs().max()

    sa = pd.read_csv(args.now / "scorecard.csv").set_index("crop")
    sb = pd.read_csv(args.ref / "scorecard.csv").set_index("crop")

    worst = m.d.max()
    verdict = ("identical to the reference run" if worst < 0.05 else
               f"largest monthly difference {worst:.2f} mm")
    parts = ["<title>ET Restore Check</title>",
             "<style>body{background:#fff;color:#000;font-family:Calibri,Carlito,sans-serif;"
             "padding:16px 24px;max-width:860px;margin:0 auto}h1{font-size:20px;margin:0 0 4px}"
             "h2{font-size:16px;margin:22px 0 2px}p{font-size:14px;margin:2px 0 8px}"
             "table{border-collapse:collapse;font-size:13px}td,th{padding:2px 8px;"
             "text-align:right;border-bottom:1px solid #ddd}"
             "th:first-child,td:first-child{text-align:left}</style>",
             "<h1>Restored model vs the reference run</h1>",
             f"<p>Both runs drawn against the same eeMetric observations, monthly, 2020–2022. "
             f"The reference run is the thick grey line and the restored run the thin blue one, "
             f"so wherever the blue sits inside the grey the two are the same. "
             f"<b>Result: {verdict}</b> across all {len(m)} crop-months. "
             f"Observations agree to {obs_d:.3f} mm, confirming both runs were scored against "
             f"the same target.</p>",
             "<table><tr><th>crop</th><th>R² ref</th><th>R² now</th>"
             "<th>|PBIAS| ref</th><th>|PBIAS| now</th><th>irrigation ref</th>"
             "<th>irrigation now</th><th>max month Δ mm</th></tr>"]
    for c in ORDER:
        d = m[m.crop == c].d.max()
        parts.append(
            f"<tr><td>{NAMES[c]}</td>"
            f"<td>{sb.loc[c,'r2_monthly']:.3f}</td><td>{sa.loc[c,'r2_monthly']:.3f}</td>"
            f"<td>{sb.loc[c,'mean_abs_pbias_pct']:.2f}</td>"
            f"<td>{sa.loc[c,'mean_abs_pbias_pct']:.2f}</td>"
            f"<td>{sb.loc[c,'irr_mm_yr']:.0f}</td><td>{sa.loc[c,'irr_mm_yr']:.0f}</td>"
            f"<td>{d:.3f}</td></tr>")
    parts.append("</table>")
    for c in ORDER:
        g = m[m.crop == c].sort_values(["yr", "mon"])
        parts.append(f"<h2>{NAMES[c]} ({c}) — max monthly difference "
                     f"{g.d.max():.3f} mm</h2>{series_svg(g)}")
    args.out.write_text("\n".join(parts))

    print(f"{'crop':<6}{'max month diff mm':>20}")
    for c in ORDER:
        print(f"{c:<6}{m[m.crop==c].d.max():>20.4f}")
    print(f"\nworst across all {len(m)} crop-months: {worst:.4f} mm")
    print(f"observations agree to {obs_d:.4f} mm")
    print(f"wrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
