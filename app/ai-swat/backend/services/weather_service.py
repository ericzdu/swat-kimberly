"""gridMET weather integration: fetch daily precip + tmax/tmin for a field location
and write SWAT+ .pcp/.tem files. Per Galen: use gridMET for consistency.

gridMET via the Northwest Knowledge THREDDS NCSS point service (CSV, no netCDF libs).
Temperature is packed (short, scale 0.1, offset 220 K) -> Celsius = raw*0.1 + 220 - 273.15.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_CHUNK_YEARS = 3   # NCSS point extraction is slow for long ranges -> fetch short chunks in parallel

_NCSS = "http://thredds.northwestknowledge.net:8080/thredds/ncss"
_VARS = {
    "pr":   ("agg_met_pr_1979_CurrentYear_CONUS.nc", "precipitation_amount"),
    "tmmx": ("agg_met_tmmx_1979_CurrentYear_CONUS.nc", "daily_maximum_temperature"),
    "tmmn": ("agg_met_tmmn_1979_CurrentYear_CONUS.nc", "daily_minimum_temperature"),
}


def _fetch_one(key: str, lat: float, lon: float, ys: int, ye: int, retries: int = 2) -> dict[str, float]:
    """Fetch one short date-range chunk for one variable (with retry)."""
    f, v = _VARS[key]
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            r = requests.get(f"{_NCSS}/{f}", params={
                "var": v, "latitude": lat, "longitude": lon,
                "time_start": f"{ys}-01-01", "time_end": f"{ye}-12-31", "accept": "csv",
            }, timeout=90)
            r.raise_for_status()
            out: dict[str, float] = {}
            for line in r.text.splitlines()[1:]:
                p = line.split(",")
                if len(p) < 4:
                    continue
                try:
                    out[p[0][:10]] = float(p[-1])
                except ValueError:
                    pass
            return out
        except Exception as exc:  # noqa: BLE001 - retry any transient network error
            last = exc
    raise last if last else RuntimeError("gridMET fetch failed")


def _fetch_all(lat: float, lon: float, y0: int, y1: int) -> dict[str, dict[str, float]]:
    """Fetch pr/tmmx/tmmn for [y0,y1] in short sequential chunks.

    NCSS point extraction is slow for long ranges and REFUSES concurrent connections
    (parallel requests hit connect-timeouts), so chunk short and fetch serially.
    """
    out: dict[str, dict[str, float]] = {k: {} for k in _VARS}
    for key in _VARS:
        for ys in range(y0, y1 + 1, _CHUNK_YEARS):
            out[key].update(_fetch_one(key, lat, lon, ys, min(ys + _CHUNK_YEARS - 1, y1)))
    return out


def _degC(raw: float, offset: float = 220.0) -> float:
    # gridMET packs temps as short with scale 0.1; add_offset DIFFERS by variable:
    # tmmx=220.0 K, tmmn=210.0 K. Using the wrong offset shifts a channel by 10 K.
    return raw * 0.1 + offset - 273.15


def _elevation(lat: float, lon: float, default: float = 1000.0) -> float:
    try:
        r = requests.get("https://epqs.nationalmap.gov/v1/json",
                         params={"x": lon, "y": lat, "units": "Meters", "wkid": 4326}, timeout=25)
        r.raise_for_status()
        v = r.json().get("value")
        return round(float(v), 3) if v not in (None, "") else default
    except Exception:
        return default


def apply_gridmet_weather(txtinout: str | Path, lat: float, lon: float, y0: int, y1: int) -> dict:
    """Fetch gridMET and overwrite the .pcp/.tem daily series for [y0, y1]."""
    tio = Path(txtinout)
    try:
        got = _fetch_all(lat, lon, y0, y1)
        pr, tx, tn = got["pr"], got["tmmx"], got["tmmn"]
    except Exception as exc:
        logger.warning("gridMET fetch failed for (%s,%s): %s", lat, lon, exc)
        return {"ok": False, "error": f"gridMET fetch failed: {exc}"}

    dates = sorted(set(pr) & set(tx) & set(tn))
    if not dates:
        return {"ok": False, "error": "gridMET returned no data (US only)."}

    elev = _elevation(lat, lon)
    nbyr = y1 - y0 + 1
    meta = f"{nbyr:>6}         0  {lat:>9.3f}  {lon:>9.3f}  {elev:>9.3f}"
    pcp_rows, tem_rows = [], []
    total_pcp = 0.0
    for d in dates:
        yr, mo, dy = int(d[:4]), int(d[5:7]), int(d[8:10])
        jd = date(yr, mo, dy).timetuple().tm_yday
        p = pr[d] * 0.1  # gridMET pr is packed (scale 0.1, offset 0) -> mm
        total_pcp += p
        pcp_rows.append(f"{yr}  {jd:>4}  {p:>10.5f}")
        tem_rows.append(f"{yr}  {jd:>4}  {_degC(tx[d], 220.0):>10.5f}  {_degC(tn[d], 210.0):>10.5f}")

    (tio / "tfccpcp.pcp").write_text(
        "tfccpcp.pcp: gridMET precipitation (AI-SWAT+)\n"
        "nbyr     tstep       lat       lon      elev\n" + meta + "\n" + "\n".join(pcp_rows) + "\n",
        encoding="utf-8")
    (tio / "tfcctmp.tem").write_text(
        "tfcctmp.tem: gridMET temperature (AI-SWAT+)\n"
        "nbyr     tstep       lat       lon      elev\n" + meta + "\n" + "\n".join(tem_rows) + "\n",
        encoding="utf-8")

    # keep the station file pointing at the observed files; update its coordinates
    _update_weather_sta(tio, lat, lon)

    return {"ok": True, "source": "gridMET", "days": len(dates), "years": nbyr,
            "elev_m": elev, "annual_precip_mm": round(total_pcp / nbyr, 1)}


def _update_weather_sta(tio: Path, lat: float, lon: float) -> None:
    """Refresh the wgn record's lat/lon in weather-wgn.cli so PET/solar use the field."""
    wgn = tio / "weather-wgn.cli"
    if not wgn.exists():
        return
    lines = wgn.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        t = ln.split()
        # station header line: name lat lon elev rain_yrs
        if len(t) >= 5 and t[0].startswith(("4", "s")) and _isnum(t[1]) and _isnum(t[2]):
            t[1], t[2] = f"{lat:.5f}", f"{lon:.5f}"
            lines[i] = "  ".join(t)
            break
    wgn.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _isnum(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
