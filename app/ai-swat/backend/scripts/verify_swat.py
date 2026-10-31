"""Verify SWAT+ engine runs and produces expected outputs."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if not os.environ.get("DATA_ROOT"):
    os.environ["DATA_ROOT"] = str(BACKEND.parent.parent / "data")


def main() -> int:
    from db import db_exec, get_farms
    from services import pyswat_facade
    from services.swat_service import swat
    import config

    print("=== SWAT+ Verification ===\n")
    errors: list[str] = []
    warnings: list[str] = []

    info = pyswat_facade.engine_info()
    print("[Engine]")
    for k, v in info.items():
        print(f"  {k}: {v}")

    if not info["pyswatplus_installed"]:
        errors.append("pySWATPlus not installed")
    if not info["swat_exe_exists"]:
        errors.append("SWATPLUS_EXE missing or file not found")
    if config.SWAT_ALLOW_MOCK:
        warnings.append("SWAT_ALLOW_MOCK is enabled — should always be false")

    farms = get_farms()
    if not farms:
        errors.append("No farms")
        return report(errors, warnings)

    farm = farms[0]
    txtinout = farm.get("txtinout_path") or str(config.farm_txtinout_dir(farm["id"]))
    tio = Path(txtinout)
    print(f"\n[Farm TxtInOut] {farm['name']}")
    print(f"  path: {tio}")
    val = pyswat_facade.validate_txtinout(tio)
    print(f"  valid: {val['valid']} format: {val.get('format')}")
    if not val["valid"]:
        errors.append(val.get("error", "TxtInOut invalid"))

    # Direct synchronous run (not threaded)
    period_begin = "01-Jan-2020"
    period_end = "31-Dec-2020"
    print(f"\n[Direct SWAT+ run] {period_begin} to {period_end}")
    try:
        work = pyswat_facade.prepare_sim_workspace(tio, "verify-swat-direct")
        t0 = time.time()
        pyswat_facade.run_simulation(
            work,
            begin_date=period_begin,
            end_date=period_end,
            warmup=1,
            parameters=[],
            print_prt_control=pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
        )
        elapsed = round(time.time() - t0, 1)
        success_fin = (work / "success.fin").exists()
        print(f"  elapsed: {elapsed}s")
        print(f"  success.fin: {success_fin}")
        if not success_fin:
            errors.append("success.fin not created after run")

        out_files = sorted(p.name for p in work.iterdir() if p.is_file())
        key_outputs = [f for f in out_files if any(x in f.lower() for x in ("wb", "yld", "fin", "channel"))]
        print(f"  key output files: {key_outputs[:12]}")

        summary = pyswat_facade.summarize_run_outputs(work, period_begin, period_end)
        wb = summary.get("water_balance") or {}
        yld = summary.get("yield_kgha")
        print(f"  water_balance: precip={wb.get('precip_mm')} et={wb.get('et_mm')} soil={wb.get('soil_moisture_mm')}")
        print(f"  yield_kgha: {yld}")
        if not wb:
            warnings.append("No water balance extracted from outputs")
        if yld is None or yld == 0:
            warnings.append("No crop yield in output (crop_yld may not be in print.prt for this project)")
    except Exception as exc:
        errors.append(f"Direct run failed: {exc}")

    # Service-layer run (same path as chat)
    print(f"\n[Service run via swat.start_run] scenario=irrigation")
    try:
        job = swat.start_run(
            farm_id=farm["id"],
            begin_date=period_begin,
            end_date=period_end,
            warmup_years=1,
            parameters=[],
            print_prt_control=pyswat_facade.DEFAULT_PRINT_PRT_CONTROL,
            scenario="irrigation",
        )
        print(f"  job_id: {job.job_id} initial status: {job.status}")
        for _ in range(60):
            st = swat.status(job.job_id)
            state = st.get("status", "")
            if state in ("completed", "failed", "cancelled", "not_found"):
                print(f"  final status: {state}")
                if state == "failed":
                    errors.append(f"Service run failed: {st.get('error')}")
                else:
                    out = st.get("output_summary") or {}
                    wb2 = out.get("water_balance") or {}
                    print(f"  output precip={wb2.get('precip_mm')} et={wb2.get('et_mm')} soil={wb2.get('soil_moisture_mm')}")
                    print(f"  mock_mode: {out.get('mock', False)}")
                    if out.get("mock"):
                        warnings.append("Last service run used MOCK output, not real SWAT+")
                    if not wb2:
                        warnings.append("Service run completed but no water_balance in summary")
                break
            time.sleep(2)
        else:
            errors.append("Service run timed out after 120s")
    except Exception as exc:
        errors.append(f"Service run error: {exc}")

    # DB history
    rows = db_exec(
        """SELECT id, status, simulation_type, error, completed_at
           FROM simulations WHERE farm_id = ? ORDER BY created_at DESC LIMIT 5""",
        (farm["id"],),
    )
    print(f"\n[Recent DB runs] {len(rows)}")
    for r in rows:
        row = dict(r)
        err = (row.get("error") or "")[:80]
        print(f"  {str(row.get('completed_at', ''))[:19]} {row.get('status')} type={row.get('simulation_type')} err={err or '-'}")

    return report(errors, warnings)


def report(errors: list[str], warnings: list[str]) -> int:
    print("\n=== Summary ===")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  X {e}")
        print("\nSWAT+ RESULT: NOT FULLY OK")
        return 1
    print("SWAT+ RESULT: RUNNING PROPERLY")
    if warnings:
        print("(with minor warnings above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
