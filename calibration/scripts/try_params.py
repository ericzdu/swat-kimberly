"""Apply a set of parameter overrides at once and report the full calibration picture.

``diagnose_sweep.py`` moves one parameter to find out whether it matters. This applies a
*combination* and scores it, which is what is needed once the individual suspects are known
and the question becomes whether they compose.

    uv run python scripts/try_params.py alfa.lai_min=0.1 corn.frac_hu2=0.5 corn.lai_max1=0.05
    uv run python scripts/try_params.py            # no args: the shipped model, as a baseline

Prints per-year yields against both measurement and the ArcSWAT reference, then the per-crop
PBIAS that gates the RL work.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import EDITABLE, TXTINOUT  # noqa: E402
from swat_gym.params import CALIBRATABLE, set_value  # noqa: E402

from calib_report import collect, pbias  # noqa: E402
from diagnose_sweep import FILE_OF  # noqa: E402


def apply_overrides(specs: list[str]) -> dict[str, str]:
    """``["alfa.lai_min=0.1", ...]`` -> ``{filename: new content}``, ready for FastRunner."""
    sources: dict[str, str] = {}
    for spec in specs:
        target, value = spec.split("=")
        row, column = target.split(".")
        file = FILE_OF[column]
        text = sources.get(file, (TXTINOUT / file).read_text())
        sources[file] = set_value(text, file, row, column, float(value))
    return sources


def report(df: pd.DataFrame, label: str) -> dict[str, float]:
    meas = df[df["yld_meas"].notna()]
    per_crop = {c: pbias(g["yld"], g["yld_meas"]) for c, g in meas.groupby("crop")}
    worst = max(abs(v) for v in per_crop.values())

    show = df[["crop", "yld", "yld_ref", "yld_meas"]].copy()
    show["err_%"] = 100 * (show["yld"] - show["yld_meas"]) / show["yld_meas"]
    print(f"\n{label}\n")
    print(show.to_string(float_format=lambda v: f"{v:8.2f}"))
    print("\nper-crop PBIAS vs measured:")
    for c, v in sorted(per_crop.items()):
        flag = "OK " if abs(v) <= 15 else "   "
        print(f"  {flag}{c:<6} {v:+7.1f} %  (n={meas[meas['crop'] == c]['yld_meas'].count()})")
    print(f"  worst crop      {worst:7.1f} %   <- must be <= 15 for RL readiness")
    if "pet_meas" in df:
        print(f"  PET vs AgriMet  {pbias(df['pet'], df['pet_meas']):+7.1f} %   "
              f"<- sanity bound, keep within +/-10")
    return {**per_crop, "worst": worst}


def main() -> None:
    specs = sys.argv[1:]
    edits = apply_overrides(specs) if specs else {}
    label = " ".join(specs) if specs else "shipped model (no overrides)"
    with FastRunner(editable=EDITABLE | CALIBRATABLE) as r:
        r.run(edits)
        report(collect(r), label)


if __name__ == "__main__":
    main()
