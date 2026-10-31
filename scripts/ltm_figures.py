"""Inline-SVG primitives for the LTM report pages (scripts/ltm_results.py,
scripts/ltm_nutrient_summary.py).

Plain SVG, no libraries: white surface, Calibri, hover via <title>. Colours: the dataviz
reference categorical slots, validated on #ffffff (strategies: slots 1-3, all-pairs pass;
crops: slots 1-6, adjacent pass). Aqua/yellow/magenta are < 3:1 on white, so every mark that
uses them is also direct-labelled or has its numbers in the page's tables.
"""
from __future__ import annotations

import html
import math

STRAT_COL = {"yield": "#2a78d6", "balanced": "#eb6834", "sustainability": "#1baf7a"}
CROP_COL = {"barl": "#2a78d6", "sgbt": "#eb6834", "wwht": "#1baf7a", "pota": "#eda100",
            "alfa": "#e87ba4", "corn": "#008300"}
CROP_INK = {"barl": "#fff", "corn": "#fff"}          # white text on the two dark fills
TRIAL = "#52514e"
DEFAULT = "#9a9893"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
FONT = "font-family:Calibri,sans-serif"


def e(x) -> str:
    return html.escape(str(x))


def svg(w: int, h: int, body: str, label: str) -> str:
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{e(label)}" style="{FONT};max-width:100%;height:auto">{body}</svg>')


def text(x, y, s, size=12, anchor="start", color=INK, weight="normal", extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{color}" font-weight="{weight}" {extra}>{e(s)}</text>')


def ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    t = math.floor(lo / step + 1e-9) * step         # cover [lo, hi]: the domain is the ticks
    out = [round(t, 10)]
    while out[-1] < hi - 1e-9:
        out.append(round(out[-1] + step, 10))
    return out


def fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 10 or v == 0 else f"{v:g}"


class Axes:
    """A plot rectangle with linear x/y scales."""

    def __init__(self, x0, y0, w, h, xd, yd):
        self.x0, self.y0, self.w, self.h, self.xd, self.yd = x0, y0, w, h, xd, yd

    def x(self, v):
        return self.x0 + (v - self.xd[0]) / (self.xd[1] - self.xd[0]) * self.w

    def y(self, v):
        return self.y0 + self.h - (v - self.yd[0]) / (self.yd[1] - self.yd[0]) * self.h

    def grid(self, xt=None, yt=None, xlab="", ylab="", xfmt=fmt, yfmt=fmt) -> str:
        out = []
        for t in yt or []:
            out.append(f'<line x1="{self.x0}" x2="{self.x0 + self.w}" y1="{self.y(t):.1f}" '
                       f'y2="{self.y(t):.1f}" stroke="{GRID}" stroke-width="1"/>')
            out.append(text(self.x0 - 6, self.y(t) + 4, yfmt(t), 11, "end", INK2))
        for t in xt or []:
            out.append(f'<line y1="{self.y0}" y2="{self.y0 + self.h}" x1="{self.x(t):.1f}" '
                       f'x2="{self.x(t):.1f}" stroke="{GRID}" stroke-width="1"/>')
            out.append(text(self.x(t), self.y0 + self.h + 15, xfmt(t), 11, "middle", INK2))
        if xlab:
            out.append(text(self.x0 + self.w / 2, self.y0 + self.h + 32, xlab, 12, "middle", INK2))
        if ylab:
            cx, cy = self.x0 - 46, self.y0 + self.h / 2
            out.append(text(cx, cy, ylab, 12, "middle", INK2,
                            extra=f'transform="rotate(-90 {cx:.1f} {cy:.1f})"'))
        return "".join(out)


def legend(items: list[tuple[str, str, str]], x: float, y: float) -> str:
    """items: (label, colour, shape in {'dot','ring','square'})."""
    out, cx = [], x
    for label, col, shape in items:
        if shape == "dot":
            out.append(f'<circle cx="{cx + 5}" cy="{y - 4}" r="5" fill="{col}"/>')
        elif shape == "ring":
            out.append(f'<circle cx="{cx + 5}" cy="{y - 4}" r="5" fill="#fff" stroke="{col}" '
                       f'stroke-width="2"/>')
        else:
            out.append(f'<rect x="{cx}" y="{y - 9}" width="10" height="10" rx="2" fill="{col}"/>')
        out.append(text(cx + 15, y, label, 12, color=INK))
        cx += 22 + 6.3 * len(label)
    return "".join(out)


# ---------------------------------------------------------------------------------------------
def rotations(rows: list[tuple[str, list[str]]], names: dict) -> str:
    """Crop strips: one row per plan, one cell per season, crop name in the cell."""
    cw, ch, left, top = 92, 30, 250, 26
    W = left + 8 * cw + 10
    H = top + len(rows) * (ch + 8) + 10
    body = [text(left + i * cw + cw / 2, 16, f"year {i + 1}", 11, "middle", INK2) for i in range(8)]
    for r, (label, crops) in enumerate(rows):
        y = top + r * (ch + 8)
        body.append(text(left - 10, y + ch / 2 + 4, label, 12, "end"))
        for i, c in enumerate(crops):
            x = left + i * cw
            body.append(f'<rect x="{x + 1}" y="{y}" width="{cw - 2}" height="{ch}" rx="4" '
                        f'fill="{CROP_COL[c]}"><title>{e(label)}, year {i + 1}: '
                        f'{e(names[c])}</title></rect>')
            body.append(text(x + cw / 2, y + ch / 2 + 4, names[c], 12, "middle",
                             CROP_INK.get(c, INK), extra='pointer-events="none"'))
    return svg(W, H, "".join(body), "Rotations chosen in Exp 1")
