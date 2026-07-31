# swat-kimberly

A **SWAT+** replication of the calibrated **RuFaS** Kimberly, ID field scenario
(USDA-ARS GRACEnet rotation, 2012–2019), driven from Python via **pySWATPlus** —
built to cross-compare a third model (SWAT+) against RuFaS and the GRACEnet
measurements on the same plot. Sibling to `../RuFaS` and `../aquaswat-gym`.

Built entirely from **input files** — no SWAT+ Editor / QSWAT+ GUI. The model is a
clone of the SWAT+ `a10_single_hru` demo `TxtInOut` (one HRU ≈ one field), edited
into the Kimberly scenario.

## Layout
- `model/TxtInOut/` — the SWAT+ model (text input + output files).
- `model/swatplus_rev60.5.7` — vendored SWAT+ engine (rev 60.5.7, macОS x86_64).
- `model/lib/libiomp5.dylib` — Intel OpenMP runtime the engine needs.
- `src/swat_kimberly/runner.py` — pySWATPlus wrapper (`KimberlySwat`).
- `runs/` — isolated run dirs (git-ignored); source `TxtInOut` stays pristine.

## Run
```
uv sync
uv run python -m swat_kimberly.runner
```

## macOS toolchain notes (already handled)
Two things make the stock SWAT+ engine + pySWATPlus work on Apple Silicon/macOS:
1. **libiomp5** — the engine links Intel OpenMP. We vendor `libiomp5.dylib` from the
   SWAT+ Editor bundle and bake its dir into the engine's `LC_RPATH`
   (`install_name_tool -add_rpath`), so it runs with no `DYLD_*` env var.
2. **Mach-O detection** — pySWATPlus 1.3.0 only recognizes ELF/PE binaries when
   locating the engine; `runner.py` monkeypatches its detector to accept Mach-O
   magic numbers.

## Status
- [x] Toolchain: engine runs, pySWATPlus drives it, outputs read into pandas.
- [ ] Port Kimberly weather (TWFI), Portneuf soil, GRACEnet rotation/manure/irrigation,
      calibrated crop params, 2012–2019 period.
- [ ] Compare yield / N / ET / percolation against RuFaS + GRACEnet.
