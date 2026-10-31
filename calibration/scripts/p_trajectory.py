#!/usr/bin/env python3
"""The modelled April soil-P trajectory, scored against measured GRACEnet Olsen-P.

Until 2026-09-25 phosphorus had no term in any objective (CLAUDE.md caution 6). This is that
term's measurement side and model side.

**The model side is read, not reconstructed.** Unlike soil nitrate (``n_trajectory.py``), the
engine does expose the profile's labile P: ``sim_initday.f90`` sums ``soil1%mp(ly)%lab`` over all
layers into ``sol_sumsolp`` every day, and ``mgt_out.txt`` prints it on every management row. The
catch is that it prints only on operation days, and the alfalfa years (2016, 2017) have no
operation in April. So :func:`install` adds a **probe** — a 0 kg/ha fertiliser application on
:data:`PROBE_MD` of every year — whose only effect is a ``FERT`` row carrying that day's pool.
4/5 sits before the ~4/10 manure applications, matching the samples, which were taken before
fertiliser. That the probe is inert is checked, not assumed (``--check``): every other output is
bit-identical with and without it.

**What is compared.** Olsen bicarbonate P is an availability index and SWAT+'s labile pool is a
model state; they are correlated and same-signed but not the same quantity (the extraction note
in ``extract_primary.soil_p`` says to score change-over-time before any level). So each series is
expressed relative to its **own seven-year mean** — ``x / mean(x) - 1`` — and the miss is how far
the modelled relative value lies *outside* the measurement's standard-error band that year
(plot-to-plot SD / sqrt(n plots), relative to the same mean). The own-mean normaliser rather than
the 2013 value, because 2013 is the noisiest sampling of the seven (SD 5.5 ppm on a mean of 8.1).

    uv run python scripts/p_trajectory.py            # score the current model
    uv run python scripts/p_trajectory.py --check    # verify the probe is inert
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swat_gym.printprt import _set_flags_named  # noqa: E402

MEAS_CSV = ROOT / "data" / "soil_p_gracenet.csv"
#: Probe date: after the 2012 spin-up planting (4/1), before every April manure (4/9-4/10).
PROBE_MD = (4, 5)
#: Any fertiliser row will do at 0 kg/ha; ``elem_p`` so a stray non-zero would at least be P.
PROBE_FERT = "elem_p"


def measured() -> pd.DataFrame:
    """April Olsen-P, kg/ha over the sampled profile, with its standard error; by year."""
    d = pd.read_csv(MEAS_CSV).set_index("year")
    d["se_kg_ha"] = d["olsen_p_kg_ha"] * (d["sd_ppm"] / d["olsen_p_ppm"]) / np.sqrt(d["n_plots"])
    return d


def with_probes(sched: str) -> str:
    """``management.sch`` text with a 0 kg fertiliser op on :data:`PROBE_MD` of every year.

    The schedule is one sequential list with no ``skip`` separators, so a year boundary is
    wherever the date goes backwards. Each probe goes in its year's block ahead of that year's
    first operation after the probe date.
    """
    lines = sched.splitlines()
    head, ops = lines[:3], lines[3:]
    if "numb_auto" not in head[1] or int(head[2].split()[2]) != 0:
        raise SystemExit("management.sch: expected the single auto-free kimb_rot schedule")

    def md(line: str) -> tuple[int, int]:
        t = line.split()
        return int(t[1]), int(t[2])

    probe = (f"{'':48s}{'fert':<14s}{PROBE_MD[0]:>4d}{PROBE_MD[1]:>10d}{0.0:>14.5f}"
             f"{PROBE_FERT:>18s}{'broadcast':>18s}{0.0:>14.5f}  ")
    out, prev, placed = [], None, False
    for line in ops:
        if not line.strip():
            continue
        cur = md(line)
        if prev is not None and cur < prev:
            if not placed:
                out.append(probe)       # the year that just ended had nothing after 4/5
            placed = False
        if not placed and cur > PROBE_MD:
            out.append(probe)
            placed = True
        out.append(line)
        prev = cur
    n = sum(1 for ln in out if ln.strip())
    # numb_ops is read list-directed, so only the token matters, not its column.
    head[2] = re.sub(r"^(\S+\s+)\d+", lambda m: f"{m.group(1)}{n}", head[2], count=1)
    return "\n".join(head + out) + "\n"


def install(runner) -> None:
    """Add the probes and switch ``mgt_out`` on, in this runner's work directory."""
    wd = Path(runner.workdir)
    sch = wd / "management.sch"
    sch.write_text(with_probes(sch.read_text()))
    pp = wd / "print.prt"
    lines = pp.read_text().splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i - 1].split()[:1] == ["crop_yld"]:     # the label line mgtout sits under
            lines[i] = _set_flags_named(lines[i], lines[i - 1], {"mgtout": True})
    pp.write_text("".join(lines))
    for name in ("management.sch", "print.prt"):
        if name in getattr(runner, "_pristine", {}):
            runner._pristine[name] = (wd / name).read_bytes()


def pool(runner) -> pd.Series:
    """Modelled whole-profile labile P on the probe day, kg/ha, by year."""
    rows = {}
    for line in (Path(runner.workdir) / "mgt_out.txt").read_text().splitlines()[3:]:
        t = line.split()
        if (len(t) > 13 and t[5] == "FERT" and t[4] == PROBE_FERT
                and (int(t[2]), int(t[3])) == PROBE_MD and float(t[13]) == 0.0):
            rows[int(t[1])] = float(t[12])
    if not rows:
        raise RuntimeError("no probe rows in mgt_out.txt; was p_trajectory.install() called?")
    return pd.Series(rows, name="sim_lab_p")


def trajectory(runner) -> pd.DataFrame:
    """Measured vs modelled, each relative to its own mean over the shared years."""
    obs, sim = measured(), pool(runner)
    years = [y for y in obs.index if y in sim.index]
    d = obs.loc[years, ["olsen_p_kg_ha", "se_kg_ha"]].copy()
    d["sim_lab_p"] = sim.loc[years]
    om, sm = d["olsen_p_kg_ha"].mean(), d["sim_lab_p"].mean()
    d["obs_rel"] = d["olsen_p_kg_ha"] / om - 1.0
    d["band"] = d["se_kg_ha"] / om
    d["sim_rel"] = d["sim_lab_p"] / sm - 1.0
    gap = (d["sim_rel"] - d["obs_rel"]).abs() - d["band"]
    d["miss"] = gap.clip(lower=0.0)
    return d


def score(traj: pd.DataFrame) -> float:
    """RMS miss outside the band, percentage points of the series mean."""
    return float(100.0 * (traj["miss"] ** 2).mean() ** 0.5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="run with and without the probes and compare every other output")
    args = ap.parse_args()
    from swat_gym import FastRunner

    if args.check:
        outs = {}
        for probed in (False, True):
            with FastRunner(trim_outputs=False) as r:
                if probed:
                    install(r)
                r.run()
                outs[probed] = {p.name: p.read_text().splitlines()[1:]
                                for p in Path(r.workdir).glob("*.txt")
                                if p.name not in ("mgt_out.txt",) and p.stat().st_size < 50e6}
        diff = sorted(n for n in outs[False] if outs[False][n] != outs[True].get(n))
        print(f"{len(outs[False])} outputs compared; differing: {diff or 'none'}")
        return 1 if diff else 0

    with FastRunner() as r:
        install(r)
        r.run()
        t = trajectory(r)
    print(t.round(3).to_string())
    print(f"\nP trajectory miss (RMS, % of mean, outside the SE band): {score(t):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
