"""The gym's hot path: run SWAT+ many thousands of times, cheaply.

``swat_kimberly.runner.KimberlySwat`` copies the whole 14 MB / 238-file ``TxtInOut`` per run
and drives the engine through pySWATPlus — 3.9 s against an engine that finishes in 0.42 s.
That is fine for one-off comparison runs, and it stays the reference implementation. It is
not viable for a search that needs thousands of evaluations.

:class:`FastRunner` inverts the cost: copy the *inputs only*, **once**, at construction; then
per run rewrite just the handful of schedule files that changed and invoke the engine directly.

Guarantees that matter for correctness:

* **No stale reads.** Every file not in the input manifest is deleted before each run, so a
  table left behind by a previous (or failed) run can never be mistaken for this run's output.
* **No cross-run leakage.** Mutated files are restored from the pristine source each run, so
  an edit applied in run *n* does not persist into run *n+1*.
* **Dynamics untouched.** Only schedule inputs and ``print.prt``'s output flags are written;
  no SWAT+ source, binary, or parameter file is patched.
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

#: Files an action may rewrite. Restricting the set is a guardrail, not a limitation: an
#: action that needs to touch anything else is a change to the experiment, not to a schedule.
EDITABLE = frozenset({
    "management.sch",   # rotation, fertiliser, irrigation, harvest operations
    "irr.ops",          # per-event irrigation amounts
    "fertilizer.frt",   # manure compositions
    "plant.ini",        # initial plant community
    "time.sim",         # simulation window (replay mode truncates it)
    "landuse.lum",      # schedule/community wiring
})


class FastRunner:
    """A reusable SWAT+ working directory.

    One instance owns one scratch directory and is **not** thread-safe or process-shared —
    give each parallel worker its own.
    """

    def __init__(
        self,
        txtinout: Path = TXTINOUT,
        workdir: Path | None = None,
        *,
        trim_outputs: bool = True,
        keep: Mapping[str, set[str]] = GYM_OUTPUTS,
        editable: frozenset[str] = EDITABLE,
    ) -> None:
        #: Calibration is the one legitimate reason to widen this: fitting the model *is*
        #: changing its dynamics, whereas an action must not. Gym code leaves it at the
        #: default; ``scripts/calibrate/`` passes :data:`CALIBRATABLE`.
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

        #: Engine invocations by this runner. The unit budgets are matched in: PPO's
        #: `total_timesteps` and CMA-ES's evaluation count are *not* comparable, and last
        #: round that let PPO have 200,000 engine runs against the fixed-schedule optimizer's
        #: 6,528 — a 30x gap that produced the entire apparent advantage. Count, don't assume.
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
        """Read a SWAT+ output table, returning numeric columns as numbers.

        The tables are inconsistent about their header: ``basin_crop_yld_yr.txt`` is
        title + column names, but ``hru_wb_yr.txt``, ``hru_pw_yr.txt`` and ``basin_nb_yr.txt``
        insert a **units row** ("mm", "kgha", "m**2/m**2") beneath the names. Read naively,
        that row becomes data and forces every column to string dtype — so ``df["et"].mean()``
        raises rather than returning a number. Detect it by the first cell being non-numeric.
        """
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
        """Annual dry-matter yield per crop, as ``basin_crop_yld_yr.txt`` reports it.

        ``yld_t`` (total) is the trustworthy column; the file's own per-hectare column is
        **per cut** for multi-cut alfalfa, because ``harv_area`` accumulates one field area
        per cut. See the README section on reading this table.
        """
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
