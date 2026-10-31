"""Write SWAT+ daily weather files from Open-Meteo archive JSON (real measured data)."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_days(payload: dict) -> list[dict[str, Any]]:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    precip = daily.get("precipitation_sum") or []
    rows: list[dict[str, Any]] = []
    for i, ds in enumerate(dates):
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d")
        except ValueError:
            continue
        rows.append({
            "year": dt.year,
            "month": dt.month,
            "jday": int(dt.timetuple().tm_yday),
            "tmax": float(tmax[i]) if i < len(tmax) and tmax[i] is not None else math.nan,
            "tmin": float(tmin[i]) if i < len(tmin) and tmin[i] is not None else math.nan,
            "precip_mm": float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
        })
    if not rows:
        raise ValueError("Open-Meteo file has no daily weather rows.")
    return rows


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sd(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    m = _mean(values)
    return (sum((x - m) ** 2 for x in values) / (len(values) - 1)) ** 0.5


def _monthly_stats(rows: list[dict[str, Any]]) -> list[dict[str, float]]:
    by_month: dict[int, list[dict[str, Any]]] = {m: [] for m in range(1, 13)}
    for row in rows:
        by_month[row["month"]].append(row)

    stats: list[dict[str, float]] = []
    for month in range(1, 13):
        items = by_month[month]
        if not items:
            stats.append({
                "tmp_max_ave": 0.0, "tmp_min_ave": 0.0, "tmp_max_sd": 1.0, "tmp_min_sd": 1.0,
                "pcp_ave": 5.0, "pcp_sd": 1.0, "pcp_skew": 1.5,
                "wet_dry": 0.3, "wet_wet": 0.4, "pcp_days": 2.0, "pcp_hhr": 1.0,
                "slr_ave": 15.0, "dew_ave": 0.5, "wnd_ave": 2.0,
            })
            continue
        tmaxs = [x["tmax"] for x in items if not math.isnan(x["tmax"])]
        tmins = [x["tmin"] for x in items if not math.isnan(x["tmin"])]
        pcps_mm = [x["precip_mm"] for x in items]           # daily precip, mm
        # Per-year averages in METRIC units (SWAT+ wgn is mm, not inches). The guards
        # below keep the weather-generator math finite at init: pcp_days averaged per
        # year (not summed over all years), pcpmm kept > 0, and the max 0.5h rainfall
        # (pcp_hhr) strictly below the monthly total — otherwise SWAT+'s rainfall
        # -fraction log()/division traps and raises SIGFPE before the run starts.
        n_years = max(1, len({x["year"] for x in items}))
        wet = [p for p in pcps_mm if p > 0.1]
        pcp_days = max(0.5, len(wet) / n_years)
        pcp_ave = max(0.5, sum(pcps_mm) / n_years)          # avg monthly total, mm
        max_daily = max(pcps_mm) if pcps_mm else 0.0
        pcp_hhr = max(0.1, min(0.3 * max_daily, 0.9 * pcp_ave))
        stats.append({
            "tmp_max_ave": _mean(tmaxs),
            "tmp_min_ave": _mean(tmins),
            "tmp_max_sd": _sd(tmaxs) or 1.0,
            "tmp_min_sd": _sd(tmins) or 1.0,
            "pcp_ave": round(pcp_ave, 3),
            "pcp_sd": round(_sd(pcps_mm) or 1.0, 3),
            "pcp_skew": 1.5,
            "wet_dry": 0.3,
            "wet_wet": 0.4,
            "pcp_days": round(pcp_days, 3),
            "pcp_hhr": round(pcp_hhr, 3),
            "slr_ave": 15.0,
            "dew_ave": 0.5,
            "wnd_ave": 2.0,
        })
    return stats


def apply_openmeteo_to_txtinout(
    weather_json_path: Path,
    txtinout_dir: Path,
    lat: float,
    lon: float,
    elev_m: float,
) -> dict[str, Any]:
    """Create SWAT+ pcp/tem/cli files from downloaded Open-Meteo JSON."""
    payload = json.loads(weather_json_path.read_text(encoding="utf-8"))
    rows = _parse_days(payload)
    years = sorted({r["year"] for r in rows})
    y0, y1 = years[0], years[-1]
    nbyr = y1 - y0 + 1
    pcp_name = "farm_weather.pcp"
    tem_name = "farm_weather.tem"
    wgn_name = "farm_wgn"

    pcp_lines = [
        f"{pcp_name}: Precipitation from Open-Meteo archive",
        "nbyr     tstep       lat       lon      elev",
        f"  {nbyr:2d}         0    {lat:7.3f}  {lon:8.3f}  {elev_m:8.3f}",
    ]
    tem_lines = [
        f"{tem_name}: Temperature from Open-Meteo archive",
        "nbyr     tstep       lat       lon      elev",
        f"  {nbyr:2d}         0    {lat:7.3f}  {lon:8.3f}  {elev_m:8.3f}",
    ]
    for row in rows:
        # SWAT+ weather is metric: precip in mm, temperature in C (NOT inches).
        precip_mm = row["precip_mm"]
        pcp_lines.append(f"{row['year']:4d}  {row['jday']:3d}  {precip_mm:9.5f}")
        if math.isnan(row["tmax"]) or math.isnan(row["tmin"]):
            raise ValueError(f"Missing temperature on {row['year']}-{row['month']:02d}")
        tem_lines.append(f"{row['year']:4d}  {row['jday']:3d}  {row['tmax']:9.5f}  {row['tmin']:9.5f}")

    txtinout_dir.mkdir(parents=True, exist_ok=True)
    (txtinout_dir / pcp_name).write_text("\n".join(pcp_lines) + "\n", encoding="utf-8")
    (txtinout_dir / tem_name).write_text("\n".join(tem_lines) + "\n", encoding="utf-8")
    (txtinout_dir / "pcp.cli").write_text(
        "pcp.cli: Precipitation file names\nfilename\n" + pcp_name + "\n",
        encoding="utf-8",
    )
    (txtinout_dir / "tmp.cli").write_text(
        "tem.cli: Temperature file names\nfilename\n" + tem_name + "\n",
        encoding="utf-8",
    )

    monthly = _monthly_stats(rows)
    # SWAT+ wgn layout: title, station row (name lat lon elev years), monthly header,
    # then 12 monthly rows. NO separate station-label line — the reader takes the row
    # right after the title as station DATA, so an extra label line makes it read
    # "lat"/"years" as numbers (years=0) and trap.
    wgn_lines = [
        "weather-wgn.cli: generated from Open-Meteo archive",
        f"{wgn_name:<30} {lat:11.5f} {lon:12.5f} {elev_m:11.5f} {nbyr:11d}",
        " tmp_max_ave   tmp_min_ave    tmp_max_sd    tmp_min_sd       pcp_ave        pcp_sd      pcp_skew       wet_dry       wet_wet      pcp_days       pcp_hhr       slr_ave       dew_ave       wnd_ave",
    ]
    for m in monthly:
        wgn_lines.append(
            f" {m['tmp_max_ave']:11.5f} {m['tmp_min_ave']:11.5f} {m['tmp_max_sd']:11.5f} {m['tmp_min_sd']:11.5f}"
            f" {m['pcp_ave']:11.5f} {m['pcp_sd']:11.5f} {m['pcp_skew']:11.5f} {m['wet_dry']:11.5f}"
            f" {m['wet_wet']:11.5f} {m['pcp_days']:11.5f} {m['pcp_hhr']:11.5f}"
            f" {m['slr_ave']:11.5f} {m['dew_ave']:11.5f} {m['wnd_ave']:11.5f}"
        )

    (txtinout_dir / "weather-wgn.cli").write_text("\n".join(wgn_lines) + "\n", encoding="utf-8")
    (txtinout_dir / "weather-sta.cli").write_text(
        "weather-sta.cli: generated from Open-Meteo archive\n"
        "name                           wgn                        pcp                        tmp                        slr                        hmd                        wnd                        pet          atmo_dep\n"
        f"farm_station              {wgn_name:<24} {pcp_name:<26} {tem_name:<26} sim                        sim                        sim                       null              null\n",
        encoding="utf-8",
    )
    (txtinout_dir / "time.sim").write_text(
        "time.sim: generated from Open-Meteo archive\n"
        "day_start  yrc_start   day_end   yrc_end      step\n"
        f"       0      {y0}         0      {y1}         0\n",
        encoding="utf-8",
    )
    (txtinout_dir / ".weather_source").write_text("open-meteo\n", encoding="utf-8")

    return {
        "source": "open-meteo",
        "begin_year": y0,
        "end_year": y1,
        "days": len(rows),
        "pcp_file": pcp_name,
        "tem_file": tem_name,
    }
