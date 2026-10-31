"""End-to-end verification for AI-SWAT+ backend."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if not os.environ.get("DATA_ROOT"):
    os.environ["DATA_ROOT"] = str(BACKEND.parent.parent / "data")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    print("=== AI-SWAT+ System Verification ===\n")

    # Paths
    from config import demo_txtinout_source

    swat_exe = os.environ.get("SWATPLUS_EXE", "")
    data_root = os.environ.get("DATA_ROOT", "")
    print("[Paths]")
    print(f"  DATA_ROOT: {data_root}")
    print(f"  SWATPLUS_EXE: {swat_exe or '(not set)'}")
    if swat_exe and not Path(swat_exe).exists():
        errors.append(f"SWAT+ executable not found: {swat_exe}")
    elif swat_exe:
        print(f"  SWAT exe exists: True")
    else:
        warnings.append("SWATPLUS_EXE not set — simulations will fail until set")

    demo = Path(demo_txtinout_source())
    print(f"  Demo TxtInOut: {demo} (exists={demo.exists()})")
    if not demo.exists():
        warnings.append("Demo TxtInOut folder missing")

    # AI
    from services.llm_service import (
        DEFAULT_MODELS,
        MINIMAX_ANTHROPIC_BASE,
        get_ai_status,
        get_saved_config,
        resolve_provider_model,
    )

    cfg = get_saved_config()
    print("\n[AI Settings]")
    print(f"  Saved provider: {cfg.get('provider')}")
    print(f"  Saved model: {cfg.get('model') or '(provider default)'}")
    print(f"  MiniMax Anthropic base: {MINIMAX_ANTHROPIC_BASE}")

    try:
        provider, model = resolve_provider_model(None, None)
        print(f"  Resolved: {provider} / {model}")
        expected_default = DEFAULT_MODELS.get(provider, "")
        if provider == "minimax" and model != expected_default and not cfg.get("model"):
            warnings.append(f"MiniMax model is {model}, default is {expected_default}")
    except Exception as exc:
        errors.append(f"AI config: {exc}")
        provider, model = "", ""

    status = get_ai_status()
    print(f"  Configured: {status.get('configured')}")
    print(f"  Message: {status.get('message', '')[:150]}")
    if not status.get("configured"):
        errors.append("AI not configured — set provider and API key in Settings")

    # Farms
    from db import get_farms
    from services import data_download_service, insights_service, readiness_service

    farms = get_farms()
    print(f"\n[Farms] {len(farms)} total")
    ready_farm = None
    for f in farms[:5]:
        rid = f["id"]
        r = readiness_service.get_farm_readiness(rid)
        b = data_download_service.get_boundary_status(rid)
        print(f"  - {f['name']} [{rid[:8]}]")
        print(f"      ready_to_simulate={r.get('ready_to_simulate')}")
        print(f"      has_boundary={b.get('has_boundary')} txtinout={bool(f.get('txtinout_path'))}")
        if r.get("ready_to_simulate") and not ready_farm:
            ready_farm = f

    if not farms:
        warnings.append("No farms in database — add one in My Farms")

    # Insights / simulation
    if farms:
        fid = farms[0]["id"]
        ins = insights_service.get_farm_insights(fid)
        print(f"\n[Insights: {farms[0]['name']}]")
        print(f"  has_data={ins.get('has_data')}")
        if ins.get("has_data"):
            wb = (ins.get("run_output") or {}).get("water_balance") or {}
            card = insights_service.interpret_irrigation(ins.get("run_output") or {})
            print(f"  soil_moisture_mm={wb.get('soil_moisture_mm')}")
            print(f"  irrigation verdict={card.get('verdict')} recommendation={card.get('recommendation')}")
        else:
            warnings.append(f"No simulation data for {farms[0]['name']}")
        lr = ins.get("last_run")
        if lr:
            print(f"  last_run: status={lr.get('status')} at {str(lr.get('completed_at', ''))[:19]}")
        else:
            warnings.append("No completed simulation runs yet")

    # Chat cards
    sample = {
        "water_balance": {
            "soil_moisture_mm": 24,
            "et_mm": 247,
            "precip_mm": 246,
            "runoff_mm": 5,
            "deep_perc_mm": 2,
        }
    }
    card = insights_service.interpret_irrigation(sample)
    print("\n[Irrigation card logic]")
    print(f"  verdict={card.get('verdict')} recommendation={card.get('recommendation')}")
    if card.get("verdict") != "yes":
        errors.append("Irrigation card logic wrong for dry soil test case")

    cards = insights_service.build_chat_cards(["run_irrigation_analysis"], farms[0]["id"] if farms else "x")
    print(f"  build_chat_cards from DB: {len(cards)} card(s)")

    # TxtInOut validation
    if ready_farm and ready_farm.get("txtinout_path"):
        from services import pyswat_facade

        v = pyswat_facade.validate_txtinout(Path(ready_farm["txtinout_path"]))
        print(f"\n[TxtInOut: {ready_farm['name']}]")
        print(f"  valid={v.get('valid')} path={ready_farm['txtinout_path']}")
        if not v.get("valid"):
            errors.append(f"TxtInOut invalid: {v.get('error', '')[:200]}")
    elif ready_farm:
        warnings.append(f"{ready_farm['name']} is ready but has no txtinout_path")

    # Agent build (no API call)
    if provider and model:
        try:
            from agent.agent import build_agent

            agent = build_agent(provider, model, farms[0]["id"] if farms else "test")
            print(f"\n[Agent]")
            print(f"  LangGraph agent built OK for {provider}/{model}")
            del agent
        except Exception as exc:
            errors.append(f"Agent build failed: {exc}")

    # Summary
    print("\n=== Summary ===")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  X {e}")
        print("\nRESULT: ISSUES FOUND")
        return 1

    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
