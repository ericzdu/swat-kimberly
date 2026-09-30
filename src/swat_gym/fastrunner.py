"""Fast repeated SWAT+ runs: copy inputs once, rewrite only edited files per run.

Each run deletes non-input files (no stale reads) and restores edited files (no leakage).
"""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from .engine import EngineError, find_engine, run_engine
from .manifest import input_files
from .printprt import GYM_OUTPUTS, trim

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TXTINOUT = PROJECT_ROOT / "model" / "TxtInOut"

#: Files an action may rewrite.
EDITABLE = frozenset({
    "management.sch",   # rotation, fertiliser, irrigation, harvest operations
    "irr.ops",          # per-event irrigation amounts
    "fertilizer.frt",   # manure compositions
    "plant.ini",        # initial plant community
    "time.sim",         # simulation window (replay mode truncates it)
    "landuse.lum",      # schedule/community wiring
})


class FastRunner:
    """Reusable SWAT+ working dir. Not thread/process safe; one per worker."""

    def __init__(
        self,
        txtinout: Path = TXTINOUT,
        workdir: Path | None = None,
        *,
        trim_outputs: bool = True,
        keep: Mapping[str, set[str]] = GYM_OUTPUTS,
        editable: frozenset[str] = EDITABLE,
    ) -> None:
        #: Only calibration widens this (passes CALIBRATABLE).
        self.editable = frozenset(editable)
        self.source = Path(txtinout)
        self.manifest = input_files(self.source)
        self._engine_name = find_engine(self.source).name
        self.manifest.add(self._engine_name)

        if workdir is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="swat_gym_")
            self.workdir = Path(self._tmp.name)
        else:
            self._tmp = None
            self.workdir = Path(workdir)
            self.workdir.mkdir(parents=True, exist_ok=True)

        for name in self.manifest:
            shutil.copy2(self.source / name, self.workdir / name)
        # copy2 preserves the executable bit, so the engine stays runnable.
        self.engine = self.workdir / self._engine_name

        #: Engine runs; the unit PPO and CMA-ES budgets are matched in.
        self.n_runs = 0

        if trim_outputs:
            pp = self.workdir / "print.prt"
            pp.write_text(trim(pp.read_text(), keep))
            # The trimmed copy is the pristine one from here on, so run() does not undo it.
            self._pristine = {n: (self.workdir / n).read_bytes() for n in self.editable
                              if n in self.manifest}
            self._pristine["print.prt"] = pp.read_bytes()
        else:
            self._pristine = {n: (self.workdir / n).read_bytes() for n in self.editable
                              if n in self.manifest}

    # -- running -------------------------------------------------------------------

    def run(self, edits: Mapping[str, str] | None = None, timeout: float = 600.0) -> Path:
        """Apply ``edits`` (filename -> full file content), run SWAT+, return the work dir."""
        edits = edits or {}
        unknown = set(edits) - self.editable
        if unknown:
            raise ValueError(
                f"Refusing to write {sorted(unknown)}; editable files are "
                f"{sorted(self.editable)}"
            )

        self._reset()
        for name, content in edits.items():
            (self.workdir / name).write_text(content)

        self.n_runs += 1
        run_engine(self.engine, self.workdir, timeout=timeout)
        return self.workdir

    def _reset(self) -> None:
        """Delete every non-input file and restore the editable inputs to pristine content."""
        for path in self.workdir.iterdir():
            if path.name not in self.manifest:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        for name, content in self._pristine.items():
            (self.workdir / name).write_bytes(content)

    # -- reading -------------------------------------------------------------------

    def read(self, name: str) -> pd.DataFrame:
        """Read a SWAT+ output table as numeric; skips the units row some tables have."""
        path = self.workdir / name
        if not path.is_file():
            raise EngineError(
                f"{name} not produced. If it is a table you need, add it to "
                f"printprt.GYM_OUTPUTS — the runner trims print.prt by default."
            )
        df = pd.read_csv(path, sep=r"\s+", skiprows=1, header=0, engine="python")
        if len(df) and pd.to_numeric(pd.Series([df.iloc[0, 0]]), errors="coerce").isna().all():
            df = df.iloc[1:].reset_index(drop=True)
        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().all():  # leave genuinely textual columns (e.g. `name`) alone
                df[col] = converted
        return df

    def yields(self) -> pd.DataFrame:
        """Annual dry yield per crop. Use yld(t); the per-ha column is per cut for alfalfa."""
        df = self.read("basin_crop_yld_yr.txt")
        return df[df["yld(t)"] > 0].reset_index(drop=True)

    # -- lifecycle -----------------------------------------------------------------

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()

    def __enter__(self) -> FastRunner:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
