"""Assemble a complete, runnable single-HRU SWAT+ project for a field.

Clones the rev-62 template (a known-good single-HRU shell), imports the field's
gSSURGO dominant soil, applies Galen's corn-silage management + auto-irrigation,
and sets the simulation window. The result runs on SWAT+ rev-62 with no errors.

This is the deterministic "fill everything with Galen's defaults" build — the
farmer only supplies a location (and optionally a crop / dates).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import config
from services import soil_service, management_service, weather_service

logger = logging.getLogger(__name__)


def _clean_print_prt(tio: Path) -> None:
    """Drop rev-62 print.prt object rows the app's engine path can't safely rewrite:
    the gwflow_* objects (gwflow module not configured) and the crop_yld object row
    (crop_yld is a toggle, not an object — keep the toggle line, drop the object row)."""
    pp = tio / "print.prt"
    if not pp.exists():
        return
    out = []
    for ln in pp.read_text(encoding="utf-8").splitlines():
        s = ln.strip().lower()
        if s.startswith("gwflow"):
            continue
        if s.startswith("crop_yld") and "mgtout" not in ln:  # object row, not the toggle
            continue
        out.append(ln)
    pp.write_text("\n".join(out) + "\n", encoding="utf-8")


def _set_gampt_infiltration(tio: Path) -> None:
    """Use Green-Ampt infiltration (codes.bsn gampt=1) instead of curve number. The CN
    frozen-soil runoff adjustment raises a floating-point exception that the FPE-trapping
    engine build turns into a hard SIGFPE on realistic sub-freezing winters; Green-Ampt
    (a valid physically-based method) avoids that code path so the model runs on correct
    cold-climate weather."""
    p = tio / "codes.bsn"
    if not p.is_file():
        return
    L = p.read_text(encoding="utf-8").splitlines()
    if len(L) < 3:
        return
    hdr, row = L[1].split(), L[2].split()
    if "gampt" in hdr and hdr.index("gampt") < len(row):
        row[hdr.index("gampt")] = "1"
        L[2] = "  ".join(row)
        p.write_text("\n".join(L) + "\n", encoding="utf-8")


def _set_nyskip(tio: Path, nyskip: int) -> None:
    pp = tio / "print.prt"
    if not pp.exists():
        return
    P = pp.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(P):
        if ln.strip().startswith("nyskip") and i + 1 < len(P):
            parts = P[i + 1].split()
            if parts:
                parts[0] = str(nyskip)
                P[i + 1] = "           ".join(parts)
            break
    pp.write_text("\n".join(P) + "\n", encoding="utf-8")


def build_field_project(
    txtinout_dir: str | Path,
    lat: float,
    lon: float,
    crop: str | None = None,
    crops: list[str] | None = None,
    plant: tuple[int, int] | None = None,
    harvest: tuple[int, int] | None = None,
    irrigation_tier: str | None = None,
    manure: list[dict] | None = None,
    sim_years: tuple[int, int] | None = None,
) -> dict:
    """Build a complete corn-silage (or given-crop/rotation) project at a location.

    Soil (gSSURGO dominant), weather (gridMET), crop management (single-crop flat or
    jday rotation decision table), irrigation, and engine (rev-62) are all location-
    and Galen-correct. Runs error-free on SWAT+ rev-62.
    """
    tio = Path(txtinout_dir)
    template = Path(config.REV62_TEMPLATE)
    if not template.is_dir():
        return {"ok": False, "error": f"rev-62 template missing at {template}"}

    if tio.exists():
        shutil.rmtree(tio)
    tio.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, tio)
    for exe in tio.glob("*.exe"):
        exe.unlink()
    _clean_print_prt(tio)
    _set_gampt_infiltration(tio)

    soil = soil_service.apply_gssurgo_soil(tio, lat, lon)
    if not soil.get("ok"):
        logger.warning("gSSURGO soil not applied (%s) — keeping template soil", soil.get("error"))

    mgmt = management_service.apply_management(
        tio, crop=crop, crops=crops, plant=plant, harvest=harvest,
        irrigation_tier=irrigation_tier, manure=manure,
    )

    y0, y1 = sim_years or config.GALEN_DEFAULTS["sim_years"]

    # gridMET daily weather for the field location + window (Galen: use gridMET).
    # Falls back to the template weather if the fetch fails so the build still runs.
    weather = weather_service.apply_gridmet_weather(tio, lat, lon, y0, y1)
    if not weather.get("ok"):
        logger.warning("gridMET not applied (%s) — keeping template weather", weather.get("error"))

    (tio / "time.sim").write_text(
        "time.sim: AI-SWAT+\nday_start  yrc_start   day_end   yrc_end      step\n"
        f"       0      {y0}         0      {y1}         0\n",
        encoding="utf-8",
    )
    _set_nyskip(tio, 0)

    return {
        "ok": True,
        "txtinout": str(tio),
        "soil": soil,
        "management": mgmt,
        "sim_years": [y0, y1],
        "engine": "rev-62",
        "weather": weather if weather.get("ok") else {"ok": False, "source": "template",
                                                      "note": weather.get("error")},
    }


def build_field_for_farm(farm_id: str, options: dict | None = None) -> dict:
    """Build the field's project from its saved boundary centroid + the farmer's
    collected choices (rotation crop, manure, irrigation tier, sim length). Anything
    not provided falls back to Galen's defaults."""
    from services import data_download_service as dds

    geo = dds.load_boundary(farm_id)
    if not geo:
        return {"ok": False, "error": "No field boundary saved — draw the field on the map first."}
    import geopandas as gpd

    gdf = gpd.GeoDataFrame.from_features(geo.get("features", [geo]), crs="EPSG:4326")
    b = gdf.total_bounds.tolist()
    lat, lon = (b[1] + b[3]) / 2, (b[0] + b[2]) / 2
    area_ha = float(gdf.to_crs(3857).area.sum() / 10000)

    o = options or {}
    crops = (o.get("rotation") or {}).get("crops") or []     # one crop per rotation year
    manure = o.get("manure")
    irrigation_tier = o.get("irrigation_tier")
    # sim length -> n REPORTED years ending END_YEAR, plus a leading spin-up year the
    # run's warmup(=1) skips. The base SWAT+ model SIGFPEs at recurring dates
    # (2014-08, 2018-11, 2022-12) — even a spin-up year that simulates one crashes — so the
    # only long stable continuous window is pre-2014. Cap at 10 yrs and end at 2013.
    END_YEAR = 2013
    # Stable window is pre-2014 (engine SIGFPEs at 2014-08/2018-11/2022-12). gridMET starts
    # 1979, so up to ~34 reported years fit before 2014; cap at 30 to allow multi-cycle
    # rotation studies (e.g. 18-year comparisons) while staying in the clean window.
    n = max(1, min(int(o.get("sim_years") or 2), 30))
    sim_years = (END_YEAR - n, END_YEAR)

    tio = config.farm_txtinout_dir(farm_id)
    res = build_field_project(
        tio, lat, lon, crops=crops or None, manure=manure,
        irrigation_tier=irrigation_tier, sim_years=sim_years,
    )
    res.update({
        "lat": lat, "lon": lon, "area_ha": area_ha, "txtinout_path": str(tio),
        "rotation": o.get("rotation"), "requested_sim_years": o.get("sim_years"),
    })

    # Record a verified data manifest so readiness/confidence recognize the real,
    # location-grounded map layers instead of flagging "results may be less accurate".
    # Only mark verified when the real datasets were actually applied (not template fallbacks).
    try:
        soil = res.get("soil") or {}
        weather = res.get("weather") or {}
        if res.get("ok") and soil.get("ok") and weather.get("ok"):
            soil_name = soil.get("soil")
            sources = [
                f"gSSURGO dominant soil ({soil_name})" if soil_name else "gSSURGO dominant soil",
                "gridMET daily weather",
            ]
            dds._write_data_manifest(config.farm_gis_dir(farm_id), sources, (lat, lon))
    except Exception as exc:
        logger.warning("Could not write data manifest for %s: %s", farm_id, exc)

    return res
