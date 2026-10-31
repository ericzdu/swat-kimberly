#!/usr/bin/env python3
"""
Test the SWAT+ API against the a10_single_hru QSWAT+ project.

Usage (from ai-swat/backend):
  python scripts/test_a10_single_hru.py
  python scripts/test_a10_single_hru.py --run          # attempt real pySWATPlus run
  python scripts/test_a10_single_hru.py --api          # hit running server on :8000

Set SWATPLUS_EXE to your SWAT+ binary (match project revision — a10 uses rev 61):
  $env:SWATPLUS_EXE="G:\AI-SWAT+ project\swatplus_bin\swatplus-61.0.2.61-gnu-win_amd64-Rel.exe"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Project paths
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[1]
TXTINOUT = ROOT / "a10_single_hru" / "a10_single_hru" / "Scenarios" / "Default" / "TxtInOut"

sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATA_ROOT", str(ROOT / "data"))
os.environ.setdefault("SWAT_ALLOW_MOCK", "false")


def validate_only():
    from services import pyswat_facade

    print(f"TxtInOut: {TXTINOUT}")
    print(f"Exists: {TXTINOUT.is_dir()}")
    result = pyswat_facade.validate_txtinout(TXTINOUT)
    print(json.dumps(result, indent=2))
    info = pyswat_facade.engine_info()
    print("Engine:", json.dumps(info, indent=2))
    return result["valid"]


def run_via_service():
    from db import create_farm, init_db
    from services.swat_service import SWATService

    init_db()
    farm = create_farm(
        name="a10_single_hru test",
        location="QSWAT+ benchmark",
        soil_type="test",
        txtinout_path=str(TXTINOUT),
    )
    print(f"Farm created: {farm['id']}")

    service = SWATService()
    validation = service.validate_farm_txtinout(farm["id"])
    print("Validation:", json.dumps(validation, indent=2))
    if not validation.get("valid"):
        print("TxtInOut invalid — aborting run")
        return 1

    # Match time.sim: 2005–2025
    job = service.start_run(
        farm_id=farm["id"],
        begin_date="01-Jan-2005",
        end_date="31-Dec-2025",
        warmup_years=2,
        parameters=[],
        print_prt_control={"channel_sd": {}},
        scenario="baseline",
    )
    print(f"Run started: {job.job_id} status={job.status}")
    if job.status == "failed":
        print(f"Failed immediately: {job.error}")
        return 1

    for i in range(120):
        time.sleep(3)
        status = service.status(job.job_id)
        st = status.get("status")
        prog = status.get("progress")
        print(f"  poll {i+1}: status={st} progress={prog}")
        if st in ("completed", "failed"):
            print(json.dumps(status, indent=2, default=str))
            return 0 if st == "completed" else 1
    print("Timed out waiting for run")
    return 1


def run_via_api(base: str):
    try:
        import urllib.request
    except ImportError:
        print("urllib required")
        return 1

    def post(path, body):
        req = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def get(path):
        with urllib.request.urlopen(f"{base}{path}", timeout=30) as resp:
            return json.loads(resp.read())

    health = get("/api/health")
    print("Health:", json.dumps(health, indent=2))

    farm = post("/api/farms", {
        "name": "a10_single_hru test",
        "location": "QSWAT+ benchmark",
        "txtinout_path": str(TXTINOUT),
    })
    farm_id = farm["id"]
    print(f"Farm: {farm_id}")

    val = get(f"/api/swat/validate/{farm_id}")
    print("Validate:", json.dumps(val, indent=2))

    run = post("/api/swat/run", {
        "farm_id": farm_id,
        "begin_date": "01-Jan-2005",
        "end_date": "31-Dec-2025",
        "warmup_years": 2,
        "parameters": [],
    })
    run_id = run["run_id"]
    print(f"Run: {run_id}")

    for i in range(120):
        time.sleep(3)
        status = get(f"/api/swat/runs/{run_id}")
        print(f"  poll {i+1}: {status.get('status')}")
        if status.get("status") in ("completed", "failed"):
            print(json.dumps(status, indent=2, default=str))
            return 0 if status.get("status") == "completed" else 1
    return 1


def main():
    parser = argparse.ArgumentParser(description="Test a10_single_hru with SWAT+ API")
    parser.add_argument("--run", action="store_true", help="Run SWAT+ via SWATService")
    parser.add_argument("--api", action="store_true", help="Test via HTTP API (server must be running)")
    parser.add_argument("--base", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    if not TXTINOUT.is_dir():
        print(f"ERROR: TxtInOut not found at {TXTINOUT}")
        return 1

    if not validate_only():
        return 1

    if args.api:
        return run_via_api(args.base)
    if args.run:
        return run_via_service()
    print("\nValidation OK. Next steps:")
    print("  python scripts/test_a10_single_hru.py --run     # direct service test")
    print("  python scripts/test_a10_single_hru.py --api     # via FastAPI on :8000")
    print(f"\nSet SWATPLUS_EXE before --run for a real model execution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
