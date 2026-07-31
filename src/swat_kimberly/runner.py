"""Thin pySWATPlus wrapper for the Kimberly SWAT+ model.

The model lives in ``model/TxtInOut`` (cloned from the SWAT+ ``a10_single_hru`` demo and
progressively edited into the Kimberly, ID GRACEnet field scenario). pySWATPlus'
``TxtinoutReader`` locates the vendored SWAT+ engine inside that folder and runs it in an
isolated ``sim_dir`` so the source stays pristine.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from pySWATPlus import TxtinoutReader, utils as _pysp_utils

# --- macOS Mach-O shim -------------------------------------------------------
# pySWATPlus 1.3.0 only recognizes Linux ELF / Windows PE binaries when locating
# the SWAT+ engine; the macOS engine is Mach-O, so TxtinoutReader can't find it.
# Teach its detector the Mach-O magic numbers (thin + universal/fat).
_MACHO_MAGIC = {
    b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",  # 64/32-bit little-endian
    b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",  # 64/32-bit big-endian
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # universal (fat)
}
_orig_is_exe = _pysp_utils._is_real_executable


def _is_real_executable(file_path: Path) -> bool:
    if file_path.is_file() and os.access(file_path, os.X_OK):
        try:
            if open(file_path, "rb").read(4) in _MACHO_MAGIC:
                return True
        except OSError:
            pass
    return _orig_is_exe(file_path)


_pysp_utils._is_real_executable = _is_real_executable
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TXTINOUT = PROJECT_ROOT / "model" / "TxtInOut"


class KimberlySwat:
    """Runs the Kimberly SWAT+ model and reads its outputs."""

    def __init__(self, txtinout: Path = TXTINOUT) -> None:
        self.reader = TxtinoutReader(txtinout)

    def run(self, sim_dir: Path | str | None = None, **kwargs) -> Path:
        """Run SWAT+ in an isolated directory; returns the run directory path."""
        if sim_dir is None:
            sim_dir = PROJECT_ROOT / "runs" / "latest"
        sim_dir = Path(sim_dir)
        sim_dir.mkdir(parents=True, exist_ok=True)
        return self.reader.run_swat(sim_dir=sim_dir, **kwargs)

    @staticmethod
    def read_table(run_dir: Path | str, name: str) -> pd.DataFrame:
        """Read a whitespace-delimited SWAT+ output table (2-line header: title, columns)."""
        path = Path(run_dir) / name
        return pd.read_csv(path, sep=r"\s+", skiprows=1, header=0, engine="python")


if __name__ == "__main__":
    m = KimberlySwat()
    run_dir = m.run()
    print(f"ran in {run_dir}")
    yld = m.read_table(run_dir, "basin_crop_yld_yr.txt")
    print(yld.to_string(index=False))
