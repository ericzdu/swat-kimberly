#!/usr/bin/env python3
"""Build a nutrient-unlimited scratch copy of the model under runs/ for ET calibration.

Never edits model/TxtInOut/management.sch (it is the measured baseline). Only annual crops
are fertilised; alfalfa is the unstressed control.

    uv run python scripts/et_nostress.py --sweep 0 150 300 450    # find the minimal rate
    uv run python scripts/et_nostress.py --rate 300 --build       # write the tree
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import TXTINOUT  # noqa: E402

SCH = "management.sch"
TREE = ROOT / "runs" / "et_calib_tree"
OUT = ROOT / "runs" / "et_nostress_sweep.json"

#: Crops that can be nitrogen-limited here. Alfalfa fixes, so it is deliberately absent.
ANNUALS = ("corn", "barl")

#: Split application days after planting.
SPLIT_DAYS = (0, 25, 50)

MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _add_days(mon: int, day: int, n: int) -> tuple[int, int]:
    """Advance a month/day by ``n`` days, non-leap. Calibration dates, not a calendar."""
    day += n
    while day > MONTH_DAYS[mon - 1]:
        day -= MONTH_DAYS[mon - 1]
        mon += 1
        if mon > 12:                      # a split that would spill into next year is clamped
            return 12, 31
    return mon, day


def parse(text: str) -> tuple[list[str], list[dict]]:
    """Split ``management.sch`` into (header lines, ops), keeping every field."""
    lines = text.splitlines()
    header, ops = lines[:3], []
    for raw in lines[3:]:
        t = raw.split()
        if len(t) < 7:
            continue
        ops.append({"typ": t[0], "mon": int(t[1]), "day": int(t[2]), "hu": float(t[3]),
                    "d1": t[4], "d2": t[5], "d3": float(t[6]), "raw": raw})
    return header, ops


def year_index(ops: list[dict]) -> list[int]:
    """Which simulation year each op belongs to — the engine advances on a date wrap."""
    years, y, prev = [], 0, (0, 0)
    for op in ops:
        cur = (op["mon"], op["day"])
        if cur < prev:
            y += 1
        years.append(y)
        prev = cur
    return years


def fmt(op: dict) -> str:
    return (f"{'':48s}{op['typ']:<14s}{op['mon']:>4d}{op['day']:>10d}{op['hu']:>14.5f}"
            f"{op['d1']:>18s}{op['d2']:>18s}{op['d3']:>14.5f}  ")


def with_nostress_n(text: str, rate: float) -> tuple[str, list[dict]]:
    """Add ``rate`` kg N/ha split per annual planting; ops stable-sorted by date within year."""
    header, ops = parse(text)
    years = year_index(ops)
    added = []
    for i, op in enumerate(ops):
        if op["typ"] != "plnt" or op["d1"] not in ANNUALS:
            continue
        # The harvest that closes this planting bounds where a split may land.
        end = next((ops[j] for j in range(i + 1, len(ops))
                    if ops[j]["typ"] in ("hvkl", "harv") and years[j] == years[i]), None)
        for k, dd in enumerate(SPLIT_DAYS):
            mon, day = _add_days(op["mon"], op["day"], dd)
            if end is not None and (mon, day) >= (end["mon"], end["day"]):
                continue                  # never fertilise after the crop is off the field
            added.append({"typ": "fert", "mon": mon, "day": day, "hu": 0.0,
                          "d1": "elem_n", "d2": "broadcast", "d3": rate / len(SPLIT_DAYS),
                          "year": years[i], "tie": i + (k + 1) / 100.0, "crop": op["d1"]})

    rows = [{**op, "year": years[i], "tie": float(i)} for i, op in enumerate(ops)] + added
    rows.sort(key=lambda r: (r["year"], r["mon"], r["day"], r["tie"]))
    body = [fmt(r) for r in rows]
    head = header[:2] + [f"kimb_rot                             {len(body):<4d}         0  "]
    return "\n".join(head + body) + "\n", added


def stress(runner: FastRunner) -> pd.DataFrame:
    """Per-year nitrogen stress and canopy, joined to the rotation's crop sequence."""
    pw = runner.read("hru_pw_yr.txt")
    crops = {int(r.year): r.crop for r in pd.read_csv(ROOT / "data" / "reference_hru119.csv")
             .itertuples()}
    pw = pw[pw["yr"].isin(crops)].copy()
    pw["crop"] = [crops[int(y)] for y in pw["yr"]]
    return pw[["yr", "crop", "lai", "bioms", "strsn", "strsw", "strsa"]]


def with_auto_irrigation(text: str) -> str:
    """Attach irr_str9_unlim auto-irrigation to remove water stress too."""
    lines = text.splitlines()
    head, body = lines[:3], lines[3:]
    n_ops = len(body)
    head[2] = f"kimb_rot                             {n_ops:<4d}         1  "
    return "\n".join(head + [f"{'':48s}{'irr_str9_unlim':<18s}"] + body) + "\n"


def build_tree(rate: float, dest: Path = TREE, auto_irr: bool = False) -> Path:
    """Write a complete TxtInOut with the no-stress schedule. Idempotent."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(TXTINOUT, dest)
    text, added = with_nostress_n((TXTINOUT / SCH).read_text(), rate)
    if auto_irr:
        text = with_auto_irrigation(text)
        irr = dest / "irr.ops"
        if "sprinkler_ilm" not in irr.read_text():
            from monoculture import SPRINKLER_ILM
            irr.write_text(irr.read_text().rstrip("\n") + "\n" + SPRINKLER_ILM + "\n")
    (dest / SCH).write_text(text)
    (dest / "_NOSTRESS.json").write_text(json.dumps(
        {"rate_kg_n_ha": rate, "auto_irrigation": auto_irr,
         "splits": list(SPLIT_DAYS), "n_ops_added": len(added),
         "crops": sorted({a["crop"] for a in added}),
         "warning": "CALIBRATION TREE ONLY. Its management.sch is not measured practice."},
        indent=2))
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", nargs="+", type=float, default=[0, 150, 300, 450],
                    help="kg N/ha/season rates to test for the minimal no-stress rate")
    ap.add_argument("--rate", type=float, help="build the tree at this rate and stop")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--auto-irr", action="store_true",
                    help="also attach irr_str9_unlim, removing the water limit as well")
    ap.add_argument("--dest", type=Path, default=TREE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.build:
        if args.rate is None:
            ap.error("--build needs --rate")
        d = build_tree(args.rate, args.dest, auto_irr=args.auto_irr)
        print(f"no-stress calibration tree at {d}  ({args.rate:g} kg N/ha/season"
              f"{', unlimited irrigation' if args.auto_irr else ''})")
        return

    src = (TXTINOUT / SCH).read_text()
    results = []
    print(f"{'rate':>6} " + " ".join(f"{c:>7}" for c in ("2013c", "2014b", "2018c", "2019b"))
          + f" {'max strsn':>10} {'mean LAI':>9}")
    for rate in args.sweep:
        text, added = with_nostress_n(src, rate) if rate > 0 else (src, [])
        with FastRunner(keep={"hru_pw": {"yearly"}}) as r:
            r.run({SCH: text})
            df = stress(r)
        ann = df[df["crop"].isin(("CSIL", "BARL"))]
        by = {int(x.yr): float(x.strsn) for x in ann.itertuples()}
        results.append({"rate": rate, "n_ops_added": len(added),
                        "strsn": {str(k): v for k, v in by.items()},
                        "max_strsn_annual": float(ann["strsn"].max()),
                        "mean_lai": float(df["lai"].mean()),
                        "per_year": df.round(3).to_dict(orient="records")})
        print(f"{rate:>6.0f} " + " ".join(f"{by.get(y, float('nan')):>7.2f}"
                                          for y in (2013, 2014, 2018, 2019))
              + f" {ann['strsn'].max():>10.2f} {df['lai'].mean():>9.2f}")

    ok = [r for r in results if r["max_strsn_annual"] < 0.01]
    minimal = min(ok, key=lambda r: r["rate"]) if ok else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"results": results,
                                    "minimal_no_stress_rate":
                                        minimal["rate"] if minimal else None}, indent=2))
    if minimal:
        print(f"\nminimal no-stress rate: {minimal['rate']:g} kg N/ha/season "
              f"(annual crops only; alfalfa fixes and is left alone)")
    else:
        print("\nno swept rate removed nitrogen stress — widen the sweep before fitting")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
