"""
Unified pySWATPlus integration — all SWAT+ operations go through this module.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

import config

logger = logging.getLogger(__name__)

_pyswatplus_available: Optional[bool] = None


class PySwatError(Exception):
    pass


def is_installed() -> bool:
    global _pyswatplus_available
    if _pyswatplus_available is None:
        try:
            import pySWATPlus  # noqa: F401
            _pyswatplus_available = True
        except Exception:
            _pyswatplus_available = False
    return _pyswatplus_available


def engine_info() -> dict:
    exe = config.SWATPLUS_EXE
    data_root = config.DATA_ROOT
    return {
        "pyswatplus_installed": is_installed(),
        "swat_exe_configured": bool(exe),
        "swat_exe_exists": bool(exe and os.path.isfile(exe)),
        "swat_exe_path": exe or "",
        "data_root": str(data_root),
        "data_root_writable": os.access(data_root, os.W_OK) if data_root.exists() else False,
    }


def validate_txtinout(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_dir():
        return {
            "valid": False,
            "path": str(p),
            "missing_files": list(config.TXTINOUT_MODERN),
            "found_files": [],
            "error": f"Directory not found: {p}",
            "format": None,
        }
    found = [f for f in os.listdir(p) if os.path.isfile(p / f)]
    legacy_missing = [f for f in config.TXTINOUT_LEGACY if not (p / f).exists()]
    modern_missing = [f for f in config.TXTINOUT_MODERN if not (p / f).exists()]
    if not legacy_missing:
        fmt, missing = "legacy", []
    elif not modern_missing:
        fmt, missing = "modern", []
    else:
        fmt, missing = None, modern_missing
    return {
        "valid": fmt is not None,
        "path": str(p),
        "missing_files": missing,
        "found_files": sorted(found)[:50],
        "error": None if fmt else f"Missing required files (modern): {modern_missing}",
        "format": fmt,
    }


def _ensure_exe_in_txtinout(tio_dir: Path) -> None:
    """pySWATPlus requires exactly one .exe inside the TxtInOut folder."""
    import pySWATPlus
    from pySWATPlus import utils

    exe_files = utils._find_executables(tio_dir)
    if len(exe_files) == 1:
        return
    if not config.SWATPLUS_EXE or not os.path.isfile(config.SWATPLUS_EXE):
        raise PySwatError(
            f"No SWAT+ executable in {tio_dir}. "
            f"Set SWATPLUS_EXE to your swatplus-*-win_amd64.exe path, "
            f"or copy one .exe into the TxtInOut folder."
        )
    dest = tio_dir / Path(config.SWATPLUS_EXE).name
    if dest.exists():
        dest.unlink()
    shutil.copy2(config.SWATPLUS_EXE, dest)


def make_reader(txtinout_path: str | Path):
    if not is_installed():
        raise PySwatError("pySWATPlus is not installed")
    import pySWATPlus

    tio = Path(txtinout_path).resolve()
    _ensure_exe_in_txtinout(tio)
    return pySWATPlus.TxtinoutReader(str(tio))


# SWAT+ output-file suffixes (average-annual, yearly, monthly, daily). These are
# never inputs, so they are safe to purge from a fresh workspace.
_STALE_OUTPUT_GLOBS = ("*_aa.txt", "*_yr.txt", "*_mon.txt", "*_day.txt")
# Run-completion marker written by SWAT+ only on a successful run.
_SUCCESS_MARKER = "success.fin"


def clear_stale_outputs(txtinout_path: str | Path) -> None:
    """Remove copied-in output files and the success marker before a run.

    prepare_sim_workspace() clones the whole source TxtInOut, which may include a
    stale success.fin and previous output tables. Deleting them guarantees that
    success.fin and any output this code later reads come from THIS run — so the
    completion check in run_simulation() is meaningful and summaries are never
    read from stale, copied-in files.
    """
    tio = Path(txtinout_path)
    marker = tio / _SUCCESS_MARKER
    if marker.exists():
        marker.unlink()
    for pattern in _STALE_OUTPUT_GLOBS:
        for f in tio.glob(pattern):
            try:
                if f.is_file():
                    f.unlink()
            except OSError as exc:
                logger.debug("Could not remove stale output %s: %s", f.name, exc)


def prepare_sim_workspace(txtinout_path: str | Path, run_id: str) -> Path:
    """Copy TxtInOut into an isolated run workspace; inject SWAT+ exe into the copy only."""
    src = Path(txtinout_path).resolve()
    workspace = config.run_output_dir(run_id) / "workspace"
    dest = workspace / "TxtInOut"
    if dest.exists():
        shutil.rmtree(workspace)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    clear_stale_outputs(dest)
    _ensure_exe_in_txtinout(dest)
    return dest


DEFAULT_PRINT_PRT_CONTROL = {
    "hru_wb": {"daily": True, "avann": True},
    "hru_nb": {"avann": True},
    "hru_ls": {"monthly": True, "avann": True},   # landscape nutrient losses (nitrate leaching)
    "hru_pw": {"avann": True},                    # plant/water: biomass + yield (silage isn't in crop_yld)
    "channel_sd": {"monthly": True, "avann": True},   # in-stream nitrate load + flow
}
# crop_yld is a special print.prt TOGGLE, not an object row — enabling it as an object
# makes the engine reject print.prt ("crop_yld ... is not a valid object"). Silage yield
# is read from hru_pw instead, so we never touch crop_yld here.

# Calendar days per month, for estimating monthly stream nitrate concentration.
_DAYS_IN_MONTH = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# EPA drinking-water limit for nitrate-nitrogen (mg/L). Referenced in Richards et al. (2021).
NITRATE_N_LIMIT_MGL = 10.0


def enable_farmer_outputs(txtinout_path: str | Path) -> None:
    """Enable HRU water balance, nutrients, yield, and nitrate outputs before a run."""
    if not is_installed():
        return
    reader = make_reader(txtinout_path)
    for obj, flags in (
        ("hru_wb", {"daily": True, "monthly": False, "yearly": False, "avann": True}),
        # daily nutrient + plant/water so the run-timeline can chart nitrate, biomass & stress
        ("hru_nb", {"daily": True, "monthly": False, "yearly": False, "avann": True}),
        ("hru_ls", {"daily": False, "monthly": True, "yearly": False, "avann": True}),
        ("channel_sd", {"daily": False, "monthly": True, "yearly": False, "avann": True}),
        ("hru_pw", {"daily": True, "monthly": False, "yearly": False, "avann": True}),
        ("basin_wb", {"daily": False, "monthly": False, "yearly": False, "avann": True}),
    ):
        try:
            reader.enable_object_in_print_prt(obj, allow_unavailable_object=True, **flags)
        except Exception as exc:
            logger.debug("Could not enable print for %s: %s", obj, exc)


def run_simulation(
    txtinout_path: str | Path,
    begin_date: str,
    end_date: str,
    warmup: int,
    parameters: list[dict],
    print_prt_control: Optional[dict] = None,
) -> Path:
    reader = make_reader(txtinout_path)
    tio = Path(txtinout_path)
    # pySWATPlus requires warmup >= 1 (it maps to nyskip). Keep >=1 and <= span so at
    # least one year is still reported; the build adds a spin-up year to the window so the
    # reported period still covers the full crop rotation.
    try:
        span = int(end_date[-4:]) - int(begin_date[-4:])
        warmup = max(1, min(int(warmup), span)) if span >= 1 else 1
    except (ValueError, TypeError):
        warmup = max(1, int(warmup or 1))
    enable_farmer_outputs(tio)
    try:
        reader.run_swat(
            begin_date=begin_date,
            end_date=end_date,
            warmup=warmup,
            parameters=parameters or [],
            print_prt_control=print_prt_control or DEFAULT_PRINT_PRT_CONTROL,
        )
    except Exception as exc:
        if (tio / "success.fin").exists():
            logger.warning("run_swat raised %s but success.fin present — treating as completed", exc)
        else:
            raise
    return tio


def _df_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict(orient="records")
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    return str(obj)


def extract_timeseries(
    sim_file: str | Path,
    begin_date: str,
    end_date: str,
    **kwargs,
) -> Any:
    if not is_installed():
        raise PySwatError("pySWATPlus is not installed")
    import pySWATPlus

    result = pySWATPlus.DataManager().simulated_timeseries_df(
        sim_file=str(sim_file),
        begin_date=begin_date,
        end_date=end_date,
        **kwargs,
    )
    return _df_to_dict(result)


def _parse_swat_aa_table(path: Path) -> tuple[list[str], list[list[str]]]:
    """Parse SWAT+ annual-average text files (header line 2, units line 3, data from line 4)."""
    lines = [ln for ln in path.read_text(errors="ignore").splitlines() if ln.strip()]
    if len(lines) < 4:
        return [], []
    header = lines[1].split()
    rows = [row.split() for row in lines[3:] if row.split()]
    return header, rows


def _col_index(header: list[str], *names: str) -> Optional[int]:
    lower = [h.lower() for h in header]
    for name in names:
        if name.lower() in lower:
            return lower.index(name.lower())
    return None


def _avg_col(header: list[str], rows: list[list[str]], *names: str) -> Optional[float]:
    idx = _col_index(header, *names)
    if idx is None:
        return None
    vals: list[float] = []
    for row in rows:
        if idx < len(row):
            try:
                vals.append(float(row[idx]))
            except ValueError:
                pass
    return sum(vals) / len(vals) if vals else None


def _parse_water_balance_aa(base: Path) -> tuple[Optional[dict], Optional[str]]:
    for fname in ("hru_wb_aa.txt", "basin_wb_aa.txt"):
        fpath = base / fname
        if not fpath.exists():
            continue
        try:
            header, rows = _parse_swat_aa_table(fpath)
            if not rows:
                continue
            precip = _avg_col(header, rows, "precip")
            et = _avg_col(header, rows, "et")
            runoff = _avg_col(header, rows, "surq_gen", "surq")
            latq = _avg_col(header, rows, "latq", "perc")
            soil = _avg_col(header, rows, "sw_final", "sw_ave", "sw")
            if precip is not None or et is not None:
                return {
                    "precip_mm": float(precip or 0),
                    "et_mm": float(et or 0),
                    "runoff_mm": float(runoff or 0),
                    "deep_perc_mm": float(latq or 0),
                    "soil_moisture_mm": float(soil or 0),
                }, fname
        except Exception as exc:
            logger.debug("Water parse %s: %s", fname, exc)
    return None, None


def _parse_nutrients_aa(base: Path) -> tuple[Optional[dict], Optional[str]]:
    for fname in ("hru_nb_aa.txt", "basin_nb_aa.txt"):
        fpath = base / fname
        if not fpath.exists():
            continue
        try:
            header, rows = _parse_swat_aa_table(fpath)
            if not rows:
                continue
            n_act = _avg_col(header, rows, "act_nit_n", "act_sta_n", "grzn")
            n_fert = _avg_col(header, rows, "fertn", "nuptake")
            p_act = _avg_col(header, rows, "act_sta_p", "lab_min_p", "grzp")
            p_fert = _avg_col(header, rows, "fertp", "puptake")
            n_val = (n_act or 0) + (n_fert or 0)
            p_val = (p_act or 0) + (p_fert or 0)
            if n_act is not None or p_act is not None:
                return {
                    "nitrogen_kgha": float(n_val),
                    "phosphorus_kgha": float(p_val),
                }, fname
        except Exception as exc:
            logger.debug("Nutrient parse %s: %s", fname, exc)
    return None, None


def _parse_yield_aa(base: Path) -> tuple[Optional[float], Optional[str]]:
    # hru_pw_aa carries harvested yield/biomass for silage etc. (crop_yld is often empty).
    for fname in ("hru_pw_aa.txt", "crop_yld_aa.txt", "basin_crop_yld_aa.txt", "plant_yld_aa.txt"):
        fpath = base / fname
        if not fpath.exists():
            continue
        try:
            header, rows = _parse_swat_aa_table(fpath)
            if not rows:
                continue
            for col_name in ("yield", "yld", "mass", "bioms"):
                idx = _col_index(header, col_name)
                if idx is None:
                    continue
                vals: list[float] = []
                for row in rows:
                    if idx < len(row):
                        try:
                            vals.append(float(row[idx]))
                        except ValueError:
                            pass
                if vals:
                    return sum(vals) / len(vals), fname
        except Exception as exc:
            logger.debug("Yield parse %s: %s", fname, exc)
    return None, None


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _sum_col(header: list[str], rows: list[list[str]], *names: str) -> Optional[float]:
    """Sum a column across all rows (used to roll monthly rows up to an annual total)."""
    idx = _col_index(header, *names)
    if idx is None:
        return None
    total = 0.0
    seen = False
    for row in rows:
        if idx < len(row):
            v = _safe_float(row[idx])
            if v is not None:
                total += v
                seen = True
    return total if seen else None


def _parse_nitrate_losses_aa(base: Path) -> tuple[Optional[dict], Optional[str]]:
    """Average-annual nitrate loss pathways per HRU (kg-N/ha).

    Mirrors the loss processes in Richards et al. (2021): fertilizer N that is
    not taken up leaches downward (percn) to groundwater or leaves via surface
    runoff / lateral flow / tile drains, then discharges to the stream.

    Prefers the average-annual (_aa) file; falls back to summing the monthly
    (_mon) file when a run only produced monthly output.
    """
    sources = (
        ("hru_ls_aa.txt", _avg_col),
        ("basin_ls_aa.txt", _avg_col),
        ("hru_ls_mon.txt", _sum_col),
        ("basin_ls_mon.txt", _sum_col),
    )
    for fname, agg in sources:
        fpath = base / fname
        if not fpath.exists():
            continue
        try:
            header, rows = _parse_swat_aa_table(fpath)
            if not rows:
                continue
            surq = agg(header, rows, "surqno3")
            lat = agg(header, rows, "lat3no3", "latno3")
            tile = agg(header, rows, "tileno3")
            perc = agg(header, rows, "percn")
            satex = agg(header, rows, "satexn")
            if perc is None and surq is None:
                continue
            leached = float(perc or 0)
            surf = float(surq or 0)
            latf = float(lat or 0)
            tilef = float(tile or 0)
            satf = float(satex or 0)
            return {
                "leached_to_groundwater_kgha": round(leached, 3),
                "surface_runoff_kgha": round(surf, 3),
                "lateral_flow_kgha": round(latf, 3),
                "tile_drain_kgha": round(tilef, 3),
                "sat_excess_kgha": round(satf, 3),
                "total_no3_loss_kgha": round(leached + surf + latf + tilef + satf, 3),
            }, fname
        except Exception as exc:
            logger.debug("Nitrate loss parse %s: %s", fname, exc)
    return None, None


def _parse_stream_nitrate(base: Path) -> tuple[Optional[dict], list[dict], Optional[str]]:
    """In-stream nitrate: annual summary + monthly series (concentration + load).

    channel_sd reports no3_out (kg-N) and flo_out (m^3/s). Monthly concentration
    is estimated as load / (mean flow x seconds in month). The seasonal signal
    (winter peaks at low baseflow) is the headline of Richards et al. (2021).
    """
    series: list[dict] = []
    mon_file = base / "channel_sd_mon.txt"
    if mon_file.exists():
        try:
            header, rows = _parse_swat_aa_table(mon_file)
            mon_i = _col_index(header, "mon")
            no3_i = _col_index(header, "no3_out")
            flo_i = _col_index(header, "flo_out")
            buckets: dict[int, dict[str, list[float]]] = {}
            for row in rows:
                if mon_i is None or mon_i >= len(row):
                    continue
                mon = _safe_float(row[mon_i])
                if mon is None:
                    continue
                mon = int(mon)
                if not 1 <= mon <= 12:
                    continue
                b = buckets.setdefault(mon, {"no3": [], "flo": []})
                if no3_i is not None and no3_i < len(row):
                    v = _safe_float(row[no3_i])
                    if v is not None:
                        b["no3"].append(v)
                if flo_i is not None and flo_i < len(row):
                    v = _safe_float(row[flo_i])
                    if v is not None:
                        b["flo"].append(v)
            for mon in range(1, 13):
                if mon not in buckets or not buckets[mon]["no3"]:
                    continue
                no3_avg = sum(buckets[mon]["no3"]) / len(buckets[mon]["no3"])
                flo_vals = buckets[mon]["flo"]
                flo_avg = sum(flo_vals) / len(flo_vals) if flo_vals else 0.0
                volume_m3 = flo_avg * 86400 * _DAYS_IN_MONTH[mon]
                conc = (no3_avg / volume_m3 * 1000) if volume_m3 > 0 else None
                series.append({
                    "month": mon,
                    "month_label": _MONTH_LABELS[mon - 1],
                    "no3_load_kg": round(no3_avg, 3),
                    "no3_mgL": round(conc, 3) if conc is not None else None,
                    "flow_m3s": round(flo_avg, 4),
                })
        except Exception as exc:
            logger.debug("Stream nitrate monthly parse: %s", exc)

    annual: Optional[dict] = None
    aa_file = base / "channel_sd_aa.txt"
    if aa_file.exists():
        try:
            header, rows = _parse_swat_aa_table(aa_file)
            no3 = _avg_col(header, rows, "no3_out")
            flo = _avg_col(header, rows, "flo_out")
            if no3 is not None:
                mean_conc = None
                if flo and flo > 0:
                    mean_conc = round(no3 / (flo * 86400 * 365) * 1000, 3)
                annual = {
                    "no3_load_kg_yr": round(no3, 2),
                    "mean_no3_mgL": mean_conc,
                    "limit_mgL": NITRATE_N_LIMIT_MGL,
                }
        except Exception as exc:
            logger.debug("Stream nitrate annual parse: %s", exc)

    # Fall back to rolling the monthly series up when the annual file is absent
    # or truncated (e.g. an engine that only wrote monthly output).
    if annual is None and series:
        total_load = sum(m["no3_load_kg"] for m in series)
        total_vol = sum(
            (m.get("flow_m3s") or 0) * 86400 * _DAYS_IN_MONTH[m["month"]] for m in series
        )
        annual = {
            "no3_load_kg_yr": round(total_load, 2),
            "mean_no3_mgL": round(total_load / total_vol * 1000, 3) if total_vol > 0 else None,
            "limit_mgL": NITRATE_N_LIMIT_MGL,
        }

    fname = "channel_sd_mon.txt" if series else ("channel_sd_aa.txt" if annual else None)
    return annual, series, fname


def _parse_daily_series(base: Path, begin_date: str, end_date: str) -> tuple[list[dict], Optional[str]]:
    """Extract daily time series from hru_wb_day or channel_sd_day via DataManager."""
    for fname in ("hru_wb_day.txt", "channel_sd_day.txt"):
        fpath = base / fname
        if not fpath.exists() or not is_installed():
            continue
        try:
            ts = extract_timeseries(
                fpath,
                begin_date=begin_date,
                end_date=end_date,
                has_units=True,
            )
            if isinstance(ts, list) and ts:
                series = []
                for row in ts[-90:]:
                    if not isinstance(row, dict):
                        continue
                    series.append({
                        "date": str(row.get("date", row.get("Date", ""))),
                        "precip_mm": float(row.get("precip", row.get("precip_mm", 0)) or 0),
                        "et_mm": float(row.get("et", row.get("et_mm", 0)) or 0),
                        "soil_moisture_mm": float(
                            row.get("sw", row.get("sw_final", row.get("soil_moisture_mm", 0))) or 0
                        ),
                    })
                if series:
                    return series, fname
        except Exception as exc:
            logger.debug("Daily series %s: %s", fname, exc)
    return [], None


def read_simulation_period(txtinout_path: str | Path) -> dict:
    """Read simulation begin/end from time.sim."""
    tio = Path(txtinout_path)
    time_sim = tio / "time.sim"
    result = {"begin": "01-Jan-2000", "end": "31-Dec-2000", "source": None}
    if not time_sim.exists():
        return result
    try:
        lines = [ln.strip() for ln in time_sim.read_text(errors="ignore").splitlines() if ln.strip()]
        for line in lines:
            parts = line.split()
            if len(parts) >= 5 and parts[0].isdigit():
                y_start, y_end = int(parts[1]), int(parts[3])
                result["begin"] = f"01-Jan-{y_start}"
                result["end"] = f"31-Dec-{y_end}"
                result["source"] = "time.sim"
                break
    except Exception as exc:
        logger.debug("time.sim parse: %s", exc)
    if is_installed() and result["source"] is None:
        try:
            reader = make_reader(tio)
            if hasattr(reader, "get_simulation_period"):
                period = reader.get_simulation_period()
                if period:
                    result.update(period)
                    result["source"] = "TxtinoutReader"
        except Exception:
            pass
    return result


def summarize_run_outputs(txtinout_path: str | Path, begin_date: str, end_date: str) -> dict:
    """Build API summary using SWAT+ output files and pySWATPlus DataManager."""
    base = Path(txtinout_path)
    output: dict[str, Any] = {
        "mode": "pyswatplus",
        "files_read": [],
        "summary": {},
        "errors": [],
    }

    wb, wb_file = _parse_water_balance_aa(base)
    if wb:
        output["water_balance"] = wb
        output["files_read"].append(wb_file)
    else:
        channel_day = base / "channel_sd_day.txt"
        if channel_day.exists() and is_installed():
            try:
                ts = extract_timeseries(
                    channel_day,
                    begin_date=begin_date,
                    end_date=end_date,
                    has_units=True,
                )
                if isinstance(ts, list) and ts:
                    output["files_read"].append("channel_sd_day.txt")
                    output["summary"]["channel_sd_day"] = ts[-10:]
                    last = ts[-1] if ts else {}
                    if isinstance(last, dict):
                        output["water_balance"] = {
                            "precip_mm": float(last.get("precip", last.get("precip_mm", 0)) or 0),
                            "et_mm": float(last.get("et", last.get("et_mm", 0)) or 0),
                            "runoff_mm": float(last.get("surq", last.get("runoff_mm", 0)) or 0),
                            "deep_perc_mm": float(last.get("latq", last.get("deep_perc_mm", 0)) or 0),
                            "soil_moisture_mm": float(last.get("sw", last.get("soil_moisture_mm", 0)) or 0),
                        }
            except Exception as exc:
                logger.warning("DataManager channel summary failed: %s", exc)
        if "water_balance" not in output:
            output["errors"].append(
                "Water balance output not found. Enable HRU water balance in print settings."
            )

    nb, nb_file = _parse_nutrients_aa(base)
    if nb:
        output["nutrient_balance"] = nb
        output["files_read"].append(nb_file)
    else:
        output["nutrient_balance"] = {"nitrogen_kgha": 0, "phosphorus_kgha": 0}
        output["errors"].append(
            "Nutrient output not found. Enable HRU nutrient balance in print settings."
        )

    yld, yld_file = _parse_yield_aa(base)
    if yld is not None:
        output["yield_kgha"] = yld
        output["files_read"].append(yld_file)
    else:
        output["errors"].append(
            "Yield output not found or zero. Set crop type and planting date in Setup, then run again."
        )

    no3_loss, ls_file = _parse_nitrate_losses_aa(base)
    stream_annual, stream_series, stream_file = _parse_stream_nitrate(base)
    nitrate: dict[str, Any] = {}
    if no3_loss:
        nitrate.update(no3_loss)
        output["files_read"].append(ls_file)
    if stream_annual:
        nitrate["stream"] = stream_annual
    nitrate["limit_mgL"] = NITRATE_N_LIMIT_MGL
    if stream_series:
        output["nitrate_monthly"] = stream_series
        if stream_file:
            output["files_read"].append(stream_file)
    if no3_loss or stream_annual:
        output["nitrate"] = nitrate
    else:
        output["errors"].append(
            "Nitrate output not found. Enable hru_ls and channel_sd in print settings, then run again."
        )

    daily, daily_file = _parse_daily_series(base, begin_date, end_date)
    if daily:
        output["daily_series"] = daily
        output["files_read"].append(daily_file)

    return output


def compute_metrics(
    sim_file: str | Path,
    obs_file: str | Path,
    indicators: list[str],
    sim_col: str = "flo_out",
    obs_col: str = "discharge",
    date_format: str = "%Y-%m-%d",
    extract_sim: Optional[dict] = None,
) -> dict:
    if not is_installed():
        raise PySwatError("pySWATPlus is not installed")
    import pySWATPlus

    kwargs: dict[str, Any] = {
        "sim_file": str(sim_file),
        "sim_col": sim_col,
        "obs_file": str(obs_file),
        "obs_col": obs_col,
        "date_format": date_format,
        "indicators": indicators,
    }
    if extract_sim:
        kwargs["extract_sim"] = extract_sim
    else:
        kwargs["has_units"] = True

    result = pySWATPlus.PerformanceMetrics().indicator_from_file(**kwargs)
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"result": _df_to_dict(result)}


def run_sensitivity(
    parameters: list[dict],
    sample_number: int,
    sensim_dir: str | Path,
    txtinout_folder: str | Path,
    extract_data: Optional[dict] = None,
) -> Any:
    if not is_installed():
        raise PySwatError("pySWATPlus is not installed")
    import pySWATPlus

    Path(sensim_dir).mkdir(parents=True, exist_ok=True)
    return pySWATPlus.SensitivityAnalyzer().simulation_by_sample_parameters(
        parameters=parameters,
        sample_number=sample_number,
        sensim_dir=str(sensim_dir),
        txtinout_folder=str(txtinout_folder),
        extract_data=extract_data or {},
    )


def sensitivity_indices(
    sensim_file: str | Path,
    df_name: str,
    obs_file: str | Path,
    sim_col: str,
    obs_col: str,
    indicators: list[str],
    date_format: str = "%Y-%m-%d",
) -> dict:
    if not is_installed():
        raise PySwatError("pySWATPlus is not installed")
    import pySWATPlus

    result = pySWATPlus.SensitivityAnalyzer().parameter_sensitivity_indices(
        sensim_file=str(sensim_file),
        df_name=df_name,
        sim_col=sim_col,
        obs_file=str(obs_file),
        obs_col=obs_col,
        date_format=date_format,
        indicators=indicators,
    )
    if isinstance(result, dict):
        return result
    return {"result": _df_to_dict(result)}


def archive_outputs(txtinout_path: str | Path, run_output: str | Path) -> list[str]:
    """Copy key output files to run archive folder."""
    src = Path(txtinout_path)
    dest = Path(run_output)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    patterns = ("*.txt", "*.csv", "*.json")
    for pattern in patterns:
        for f in src.glob(pattern):
            if f.is_file():
                shutil.copy2(f, dest / f.name)
                copied.append(f.name)
    return copied


def serialize_for_db(obj: Any) -> str:
    return json.dumps(obj, default=str)
