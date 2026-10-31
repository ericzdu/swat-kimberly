"""Pydantic schemas for SWAT+ API — aligned with pySWATPlus parameter dicts."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SwatParameter(BaseModel):
    name: str
    change_type: Literal["pctchg", "absval", "relchg"] = "pctchg"
    value: float


class SensitivityParameter(BaseModel):
    name: str
    change_type: Literal["pctchg", "absval", "relchg"] = "absval"
    lower_bound: float
    upper_bound: float


class SwatRunRequest(BaseModel):
    farm_id: str
    begin_date: str = "01-Jan-2024"
    end_date: str = "31-Dec-2024"
    warmup_years: int = 2
    parameters: list[SwatParameter] = Field(default_factory=list)
    print_prt_control: dict[str, Any] = Field(default_factory=lambda: {"channel_sd": {}})
    scenario: str = "baseline"


class SwatRunResponse(BaseModel):
    run_id: str
    status: str


class SwatOutputs(BaseModel):
    water_balance: Optional[dict[str, float]] = None
    nutrient_balance: Optional[dict[str, float]] = None
    yield_kgha: Optional[float] = None
    summary: Optional[dict[str, Any]] = None
    files_read: list[str] = Field(default_factory=list)
    mode: Optional[str] = None


class SwatRunStatus(BaseModel):
    run_id: str
    status: Literal["starting", "running", "completed", "failed", "cancelled", "not_found"]
    progress: Optional[int] = None
    farm_id: Optional[str] = None
    job_type: Optional[str] = None
    outputs: Optional[SwatOutputs] = None
    output_summary: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    txtinout_path: Optional[str] = None


class EngineStatus(BaseModel):
    pyswatplus_installed: bool
    swat_exe_configured: bool
    swat_exe_exists: bool
    swat_exe_path: str
    active_jobs: int
    data_root: str
    data_root_writable: bool


class TxtInOutValidation(BaseModel):
    valid: bool
    path: str
    missing_files: list[str] = Field(default_factory=list)
    found_files: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class MetricsRequest(BaseModel):
    farm_id: str
    run_id: Optional[str] = None
    sim_file: str = "channel_sd_day.txt"
    sim_col: str = "flo_out"
    obs_file: str
    obs_col: str = "discharge"
    date_format: str = "%Y-%m-%d"
    indicators: list[str] = Field(default_factory=lambda: ["NSE", "KGE", "RMSE"])
    extract_sim: Optional[dict[str, Any]] = None


class MetricsResponse(BaseModel):
    indicators: dict[str, Any]
    sim_file: str
    obs_file: str


class TimeseriesRequest(BaseModel):
    sim_file: str = "channel_sd_day.txt"
    begin_date: str
    end_date: str
    has_units: bool = True
    ref_day: int = 15
    apply_filter: Optional[dict[str, Any]] = None
    usecols: Optional[list[str]] = None


class SensitivityRequest(BaseModel):
    farm_id: str
    parameters: list[SensitivityParameter]
    sample_number: int = 64
    extract_data: Optional[dict[str, Any]] = None


class SensitivityJobResponse(BaseModel):
    job_id: str
    status: str


class GisPathsRegister(BaseModel):
    dem: Optional[str] = None
    soil: Optional[str] = None
    landuse: Optional[str] = None
    watershed: Optional[str] = None


class ObservedPathsRegister(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)


class PrepareRequest(BaseModel):
    farm_id: str
    lu_threshold: float = 1.0
    soil_threshold: float = 1.0
    use_sim_workspace: bool = True
