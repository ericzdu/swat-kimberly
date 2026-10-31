"""Application configuration — paths and SWAT+ engine settings."""
import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))

# SWAT+ rev-62 engine matches Galen's SWAT+ Editor v4.0.1 project files. Prefer it
# (env override still wins) so gSSURGO/management projects run without gwflow/crop_yld
# rev-mismatch errors.
_SWATBIN = Path(r"G:\AI-SWAT+ project\swatplus_bin")
SWATPLUS_EXE_REV62 = str(_SWATBIN / "swatplus-62.0.0-gnu-win_amd64-Rel.exe")
SWATPLUS_EXE = os.environ.get("SWATPLUS_EXE") or (
    SWATPLUS_EXE_REV62 if os.path.isfile(SWATPLUS_EXE_REV62) else ""
)

# gSSURGO soils database (USDA "SWAT US SSURGO Soils", keyed by mukey) and the
# rev-62 single-HRU template used to assemble runnable projects.
# Two backends: the original MS-Access .mdb (Windows only — needs pyodbc + the Access
# driver) and a portable SQLite conversion that works everywhere, including Linux
# containers. The SQLite one is preferred when present; see tools/convert_ssurgo.sh.
SSURGO_MDB = os.environ.get("SSURGO_MDB", r"C:\Users\shari\Downloads\SWAT_US_SSURGO_Soils.mdb")
_SSURGO_SQLITE_DEFAULTS = (
    r"G:\AI-SWAT+ project\soils_db\ssurgo.sqlite",
    "/opt/ai-swat/soils_db/ssurgo.sqlite",   # baked/mounted in the Docker image
)
SSURGO_SQLITE = os.environ.get("SSURGO_SQLITE") or next(
    (p for p in _SSURGO_SQLITE_DEFAULTS if os.path.isfile(p)), ""
)
REV62_TEMPLATE = os.environ.get("REV62_TEMPLATE", r"G:\AI-SWAT+ project\rev62_template\TxtInOut")

# Galen Richards' corn-silage defaults — used to fill everything the farmer doesn't specify.
GALEN_DEFAULTS = {
    "crop": "csil", "plant": (6, 1), "harvest": (9, 25), "harv_op": "silage",
    "irr_amt_mm": 9.1, "irr_eff": 1.0, "irr_trigger_fc": 0.80,
    "sim_years": (2020, 2021),  # proven-clean window; base project SIGFPEs on some dates in 2018 & 2022
}

SWAT_ALLOW_MOCK = False  # Real SWAT+ only — mock outputs are disabled permanently.
SWAT_API_ONLY = os.environ.get("SWAT_API_ONLY", "false").lower() in ("1", "true", "yes")

# Minimum files for a runnable TxtInOut (legacy fig.dat OR modern file.cio)
TXTINOUT_LEGACY = ("fig.dat", "hru-data.hru")
TXTINOUT_MODERN = ("file.cio", "hru-data.hru", "time.sim")


def ensure_data_dirs():
    for sub in ("gis", "farms", "outputs", "observed", "sensitivity", "db"):
        (DATA_ROOT / sub).mkdir(parents=True, exist_ok=True)


def demo_txtinout_source() -> Path:
    """Path to bundled a10 single-HRU demo project (env override, Docker bake, or local)."""
    candidates = [
        Path(p) for p in (os.environ.get("DEMO_TXTINOUT"),) if p
    ] + [
        DATA_ROOT / "test_projects" / "a10_single_hru" / "a10_single_hru" / "Scenarios" / "Default" / "TxtInOut",
        Path(__file__).resolve().parents[2] / "a10_single_hru" / "a10_single_hru" / "Scenarios" / "Default" / "TxtInOut",
    ]
    for c in candidates:
        if c.is_dir() and (c / "file.cio").exists():
            return c
    return candidates[0]


def farm_gis_dir(farm_id: str) -> Path:
    return DATA_ROOT / "gis" / farm_id


def farm_inbox_dir(farm_id: str) -> Path:
    return farm_gis_dir(farm_id) / "inbox"


def farm_txtinout_dir(farm_id: str) -> Path:
    return DATA_ROOT / "farms" / farm_id / "TxtInOut"


def farm_observed_dir(farm_id: str) -> Path:
    return DATA_ROOT / "observed" / farm_id


def run_output_dir(run_id: str) -> Path:
    return DATA_ROOT / "outputs" / run_id


def sensitivity_dir(job_id: str) -> Path:
    return DATA_ROOT / "sensitivity" / job_id


def resolve_data_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return DATA_ROOT / path
