"""
SWAT+ job orchestration — runs pySWATPlus via pyswat_facade, persists to SQLite.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config
from services import data_service, pyswat_facade

logger = logging.getLogger(__name__)


@dataclass
class JobResult:
    job_id: str
    status: str
    output: Optional[dict] = None
    error: Optional[str] = None


class SWATService:
    def __init__(self):
        self._running: dict[str, dict] = {}
        self._results: dict[str, JobResult] = {}
        self._cancel: set[str] = set()
        config.ensure_data_dirs()

    def engine_status(self) -> dict:
        info = pyswat_facade.engine_info()
        info["active_jobs"] = len(self._running)
        return info

    def _persist_create(self, job_id: str, farm_id: str, job_type: str, params: dict):
        from db import db_exec

        now = datetime.now().isoformat()
        db_exec(
            """INSERT INTO simulations
               (id, farm_id, sim_type, status, parameters, results, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, farm_id, job_type, "running", json.dumps(params), None, now, None),
        )

    def _persist_complete(self, job_id: str, status: str, output: Optional[dict], error: Optional[str]):
        from db import db_exec

        now = datetime.now().isoformat()
        payload = output
        if status == "failed" and error:
            payload = {"error": error}
        db_exec(
            "UPDATE simulations SET status = ?, results = ?, completed_at = ? WHERE id = ?",
            (status, json.dumps(payload, default=str) if payload is not None else None, now, job_id),
        )

    def _get_farm_txtinout(self, farm_id: str) -> Path:
        from db import db_one
        from services import readiness_service

        farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
        if not farm:
            raise ValueError(f"Farm {farm_id} not found")

        readiness = readiness_service.get_farm_readiness(farm_id)
        if not readiness.get("ready_to_simulate"):
            blockers = [
                c["detail"] for c in readiness.get("checks", [])
                if c.get("status") in ("missing", "warning")
            ]
            detail = blockers[0] if blockers else "Farm data is incomplete."
            raise ValueError(f"Cannot run SWAT+: {detail}")

        path = data_service.resolve_farm_txtinout(farm_id, farm)
        validation = pyswat_facade.validate_txtinout(path)
        if not validation["valid"]:
            raise ValueError(validation.get("error") or "Invalid TxtInOut")
        if not pyswat_facade.is_installed():
            raise ValueError("pySWATPlus is not installed — cannot run simulations.")
        if not pyswat_facade.engine_info().get("swat_exe_exists"):
            raise ValueError("SWATPLUS_EXE is not configured or executable not found.")
        return path

    def _run_job(
        self,
        job_id: str,
        farm_id: str,
        job_type: str,
        txtinout: Path,
        runner,
    ):
        try:
            self._running[job_id] = {"status": "running", "progress": 10}
            if job_id in self._cancel:
                raise RuntimeError("Cancelled")
            output = runner(job_id, txtinout)
            self._results[job_id] = JobResult(job_id, "completed", output)
            self._persist_complete(job_id, "completed", output, None)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            self._results[job_id] = JobResult(job_id, "failed", error=str(exc))
            self._persist_complete(job_id, "failed", None, str(exc))
        finally:
            self._running.pop(job_id, None)
            self._cancel.discard(job_id)

    def start_run(
        self,
        farm_id: str,
        begin_date: str,
        end_date: str,
        warmup_years: int,
        parameters: list[dict],
        print_prt_control: dict,
        scenario: str = "baseline",
    ) -> JobResult:
        job_id = str(uuid.uuid4())
        params = {
            "begin_date": begin_date,
            "end_date": end_date,
            "warmup_years": warmup_years,
            "parameters": parameters,
            "print_prt_control": print_prt_control,
            "scenario": scenario,
        }
        self._results[job_id] = JobResult(job_id, "running")
        self._running[job_id] = {"status": "starting", "progress": 0}
        self._persist_create(job_id, farm_id, "run", params)

        def runner(jid: str, txtinout: Path) -> dict:
            self._running[jid]["progress"] = 20
            work_dir = pyswat_facade.prepare_sim_workspace(txtinout, jid)
            self._running[jid]["progress"] = 40
            pyswat_facade.run_simulation(
                work_dir,
                begin_date=begin_date,
                end_date=end_date,
                warmup=warmup_years,
                parameters=parameters,
                print_prt_control=print_prt_control,
            )
            self._running[jid]["progress"] = 80
            archive = config.run_output_dir(jid)
            copied = pyswat_facade.archive_outputs(work_dir, archive)
            summary = pyswat_facade.summarize_run_outputs(work_dir, begin_date, end_date)
            summary["archived_files"] = copied
            summary["txtinout_path"] = str(work_dir)
            summary["scenario"] = scenario
            return summary

        try:
            txtinout = self._get_farm_txtinout(farm_id)
        except ValueError as exc:
            self._results[job_id] = JobResult(job_id, "failed", error=str(exc))
            self._persist_complete(job_id, "failed", None, str(exc))
            self._running.pop(job_id, None)
            return JobResult(job_id, "failed", error=str(exc))

        threading.Thread(
            target=self._run_job,
            args=(job_id, farm_id, "run", txtinout, runner),
            daemon=True,
        ).start()
        return JobResult(job_id, "running")

    def start_sensitivity(
        self,
        farm_id: str,
        parameters: list[dict],
        sample_number: int,
        extract_data: Optional[dict],
    ) -> JobResult:
        job_id = str(uuid.uuid4())
        params = {"parameters": parameters, "sample_number": sample_number, "extract_data": extract_data}
        self._results[job_id] = JobResult(job_id, "running")
        self._running[job_id] = {"status": "starting", "progress": 0}
        self._persist_create(job_id, farm_id, "sensitivity", params)

        def runner(jid: str, txtinout: Path) -> dict:
            sensim_dir = config.sensitivity_dir(jid)
            result = pyswat_facade.run_sensitivity(
                parameters=parameters,
                sample_number=sample_number,
                sensim_dir=sensim_dir,
                txtinout_folder=txtinout,
                extract_data=extract_data,
            )
            return {
                "mode": "pyswatplus",
                "sensim_dir": str(sensim_dir),
                "result": result if isinstance(result, dict) else str(result),
            }

        try:
            txtinout = self._get_farm_txtinout(farm_id)
        except ValueError as exc:
            self._results[job_id] = JobResult(job_id, "failed", error=str(exc))
            self._persist_complete(job_id, "failed", None, str(exc))
            self._running.pop(job_id, None)
            return JobResult(job_id, "failed", error=str(exc))

        threading.Thread(
            target=self._run_job,
            args=(job_id, farm_id, "sensitivity", txtinout, runner),
            daemon=True,
        ).start()
        return JobResult(job_id, "running")

    def compute_metrics(
        self,
        farm_id: str,
        sim_file: str,
        obs_file: str,
        indicators: list[str],
        sim_col: str,
        obs_col: str,
        date_format: str,
        run_id: Optional[str] = None,
        extract_sim: Optional[dict] = None,
    ) -> dict:
        txtinout = self._get_farm_txtinout(farm_id)
        sim_path = Path(sim_file)
        if not sim_path.is_absolute():
            if run_id:
                candidate = config.run_output_dir(run_id) / sim_file
                sim_path = candidate if candidate.exists() else txtinout / sim_file
            else:
                sim_path = txtinout / sim_file
        obs_path = Path(obs_file) if Path(obs_file).is_absolute() else config.resolve_data_path(obs_file)
        return pyswat_facade.compute_metrics(
            sim_file=sim_path,
            obs_file=obs_path,
            indicators=indicators,
            sim_col=sim_col,
            obs_col=obs_col,
            date_format=date_format,
            extract_sim=extract_sim,
        )

    def get_timeseries(
        self,
        farm_id: str,
        run_id: Optional[str],
        sim_file: str,
        begin_date: str,
        end_date: str,
        **kwargs,
    ) -> Any:
        txtinout = self._get_farm_txtinout(farm_id)
        sim_path = Path(sim_file)
        if not sim_path.is_absolute():
            if run_id:
                candidate = config.run_output_dir(run_id) / sim_file
                sim_path = candidate if candidate.exists() else txtinout / sim_file
            else:
                sim_path = txtinout / sim_file
        return pyswat_facade.extract_timeseries(
            sim_path, begin_date=begin_date, end_date=end_date, **kwargs
        )

    def validate_farm_txtinout(self, farm_id: str) -> dict:
        from db import db_one

        farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
        if not farm:
            return {"valid": False, "error": "Farm not found"}
        path = data_service.resolve_farm_txtinout(farm_id, farm)
        return pyswat_facade.validate_txtinout(path)

    def cancel(self, job_id: str) -> dict:
        self._cancel.add(job_id)
        if job_id in self._running:
            return {"ok": True, "status": "cancelling"}
        return {"ok": False, "error": "Job not running"}

    def status(self, job_id: str) -> dict:
        if job_id in self._running:
            return self._running[job_id]
        if job_id in self._results:
            r = self._results[job_id]
            return {
                "run_id": job_id,
                "status": r.status,
                "output_summary": r.output,
                "outputs": r.output,
                "error": r.error,
            }
        from db import db_one

        row = db_one("SELECT * FROM simulations WHERE id = ?", (job_id,))
        if row:
            output = None
            if row.get("results"):
                try:
                    output = json.loads(row["results"])
                except json.JSONDecodeError:
                    output = {"raw": row["results"]}
            return {
                "run_id": job_id,
                "status": row["status"],
                "farm_id": row.get("farm_id"),
                "job_type": row.get("sim_type"),
                "output_summary": output,
                "outputs": output,
                "error": None if row["status"] != "failed" else "Job failed",
            }
        return {"run_id": job_id, "status": "not_found"}

    def list_for_farm(self, farm_id: str, limit: int = 20) -> list[dict]:
        from db import db_exec

        rows = db_exec(
            "SELECT id, farm_id, sim_type, status, parameters, results, created_at, completed_at FROM simulations "
            "WHERE farm_id = ? ORDER BY created_at DESC LIMIT ?",
            (farm_id, limit),
        )
        out = []
        for row in rows:
            r = dict(row)
            params = {}
            if r.get("parameters"):
                try:
                    params = json.loads(r["parameters"]) or {}
                except json.JSONDecodeError:
                    params = {}
            # snapshot identity: a user label, falling back to the scenario name
            r["label"] = params.get("label") or params.get("scenario") or ""
            r["scenario"] = params.get("scenario") or ""
            r["begin_date"] = params.get("begin_date") or ""
            r["end_date"] = params.get("end_date") or ""
            r.pop("parameters", None)
            if r.get("results"):
                try:
                    data = json.loads(r["results"])
                    if isinstance(data, dict) and data.get("error"):
                        r["error"] = data["error"]
                except json.JSONDecodeError:
                    pass
            r["run_id"] = r["id"]
            out.append(r)
        return out

    def set_label(self, run_id: str, label: str) -> dict:
        """Name a run so it reads as a comparable snapshot."""
        from db import db_exec, db_one
        row = db_one("SELECT parameters FROM simulations WHERE id = ?", (run_id,))
        if not row:
            return {"ok": False, "error": "Run not found"}
        try:
            params = json.loads(row["parameters"]) if row.get("parameters") else {}
        except (json.JSONDecodeError, TypeError):
            params = {}
        params["label"] = label
        db_exec("UPDATE simulations SET parameters = ? WHERE id = ?", (json.dumps(params), run_id))
        return {"ok": True, "run_id": run_id, "label": label}

    def rerun(self, run_id: str, label: Optional[str] = None) -> dict:
        """Start a NEW run using an existing snapshot's saved config (window, warmup,
        parameter overrides, scenario) — so the user can tweak the model files and re-run
        the same setup for a comparable snapshot."""
        from db import db_one
        row = db_one("SELECT farm_id, parameters FROM simulations WHERE id = ?", (run_id,))
        if not row:
            return {"ok": False, "error": "Run not found"}
        try:
            p = json.loads(row["parameters"]) if row.get("parameters") else {}
        except (json.JSONDecodeError, TypeError):
            p = {}
        result = self.start_run(
            farm_id=row["farm_id"],
            begin_date=p.get("begin_date", ""),
            end_date=p.get("end_date", ""),
            warmup_years=int(p.get("warmup_years") or 1),
            parameters=p.get("parameters") or [],
            print_prt_control=p.get("print_prt_control") or {},
            scenario=p.get("scenario") or "baseline",
        )
        if result.status == "failed":
            return {"ok": False, "error": result.error}
        lbl = (label or f"{p.get('label') or p.get('scenario') or 'run'} (re-run)").strip()
        self.set_label(result.job_id, lbl)
        return {"ok": True, "run_id": result.job_id, "status": result.status, "label": lbl}

    def list_output_files(self, job_id: str) -> list[str]:
        out_dir = config.run_output_dir(job_id)
        if not out_dir.exists():
            return []
        return sorted(f.name for f in out_dir.iterdir() if f.is_file())

    # Legacy alias for simulate router
    def create(self, farm_id: str, txtinout_path: str, sim_type: str,
               params: dict, begin_date: str, end_date: str) -> JobResult:
        return self.start_run(
            farm_id=farm_id,
            begin_date=begin_date,
            end_date=end_date,
            warmup_years=params.get("warmup_years", 2) if params else 2,
            parameters=params.get("parameters", []) if params else [],
            print_prt_control=print_prt_control or pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
            scenario=sim_type,
        )


swat = SWATService()
