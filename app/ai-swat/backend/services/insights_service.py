"""Farmer-facing insights from simulation outputs."""
from __future__ import annotations

import json
from typing import Any, Optional

from db import db_one
from services import readiness_service
from utils.text import safe_text


def interpret_irrigation(output: dict) -> dict:
    wb = output.get("water_balance") or {}
    precip = wb.get("precip_mm", 0)
    et = wb.get("et_mm", 0)
    runoff = wb.get("runoff_mm", 0)
    soil_moist = wb.get("soil_moisture_mm", 0)
    deep_perc = wb.get("deep_perc_mm", 0)

    if soil_moist < 150:
        headline = "Your soil is very dry"
        severity = "critical"
        verdict = "yes"
        recommendation = "Yes — irrigate today"
        advice = "Run your irrigation system today to replenish soil moisture."
    elif soil_moist < 200:
        headline = "Soil moisture is getting low"
        severity = "warning"
        verdict = "soon"
        recommendation = "Irrigate within 3 days"
        advice = "Plan irrigation soon before crops become stressed."
    elif soil_moist < 250:
        headline = "Moisture is acceptable for now"
        severity = "ok"
        verdict = "no"
        recommendation = "No irrigation needed today"
        advice = "Check again in 5–7 days or after hot dry weather."
    else:
        headline = "Soil moisture is adequate"
        severity = "ok"
        verdict = "no"
        recommendation = "No irrigation needed"
        advice = "Hold off on irrigation unless weather turns unusually dry."

    if precip > 0 and et > 0:
        explanation = (
            f"You have received {precip:.0f} mm of rain while evaporation and crop use "
            f"removed about {et:.0f} mm. Soil moisture is {soil_moist:.0f} mm."
        )
    else:
        explanation = f"Soil moisture is {soil_moist:.0f} mm based on your latest simulation."

    detail = (
        f"Precipitation {precip:.0f} mm, ET {et:.0f} mm, runoff {runoff:.0f} mm, "
        f"soil moisture {soil_moist:.0f} mm, deep percolation {deep_perc:.0f} mm."
    )
    return {
        "headline": safe_text(headline),
        "severity": severity,
        "verdict": verdict,
        "recommendation": safe_text(recommendation),
        "detail": safe_text(detail),
        "advice": safe_text(advice),
        "explanation": safe_text(explanation),
    }


def interpret_fertilizer(output: dict) -> dict:
    nb = output.get("nutrient_balance") or {}
    n = nb.get("nitrogen_kgha", 0)
    p = nb.get("phosphorus_kgha", 0)

    if n < 50:
        n_headline = "Apply nitrogen within 10 days"
        n_sev = "warning"
        verdict = "yes"
        recommendation = "Yes — apply nitrogen soon"
    elif n < 100:
        n_headline = "Side-dress nitrogen if rain is expected"
        n_sev = "ok"
        verdict = "soon"
        recommendation = "Consider side-dressing nitrogen"
    else:
        n_headline = "Nitrogen levels adequate"
        n_sev = "ok"
        verdict = "no"
        recommendation = "No nitrogen application needed now"

    if p < 10:
        p_headline = "Phosphorus is low - consider application"
        p_sev = "warning"
        if verdict == "no":
            verdict = "soon"
            recommendation = "Consider phosphorus application"
    else:
        p_headline = "Phosphorus adequate"
        p_sev = "ok"

    severity = "warning" if n_sev == "warning" or p_sev == "warning" else "ok"
    headline = n_headline if n_sev == "warning" else p_headline
    detail = f"Nitrogen {n:.0f} kg/ha, phosphorus {p:.0f} kg/ha."
    advice = safe_text(f"{n_headline}. {p_headline}.")
    explanation = (
        f"Your field has about {n:.0f} kg/ha of nitrogen and {p:.0f} kg/ha of phosphorus "
        f"based on the latest model run."
    )
    return {
        "headline": safe_text(headline),
        "severity": severity,
        "verdict": verdict,
        "recommendation": safe_text(recommendation),
        "detail": safe_text(detail),
        "advice": advice,
        "explanation": safe_text(explanation),
    }


def interpret_yield(output: dict) -> dict:
    y = output.get("yield_kgha") or 0
    if y <= 0:
        return {
            "headline": "No yield data yet",
            "severity": "warning",
            "verdict": "unknown",
            "recommendation": "Add crop details in Setup",
            "detail": "Set your crop type and planting date in AI-SWAT+ Setup, then run a yield simulation.",
            "advice": "Open Setup → Crop details in this app (not QSWAT+). Choose crop and planting date, save, then ask again.",
            "explanation": "The model needs your crop and planting date before it can estimate yield.",
        }
    t_ha = y / 1000
    headline = f"Estimated yield: {t_ha:.1f} t/ha"
    return {
        "headline": headline,
        "severity": "ok",
        "verdict": "info",
        "recommendation": f"{y:.0f} kg/ha expected",
        "detail": "Based on your latest simulation results.",
        "advice": headline,
        "explanation": f"At current conditions, the model estimates about {t_ha:.1f} tonnes per hectare.",
    }


def interpret_nitrate(output: dict) -> dict:
    """Water-quality / nitrate-leaching insight.

    Grounded in Richards et al. (2021), Agric. Ecosyst. Environ. 308:107223:
    fertilizer nitrogen not taken up by the crop leaches to groundwater and
    later discharges to the stream, worst in winter at low baseflow. This card
    tells the farmer how much N is being lost and how to keep it in the field.
    """
    nit = output.get("nitrate") or {}
    monthly = output.get("nitrate_monthly") or []
    limit = nit.get("limit_mgL", 10.0)

    leached = nit.get("leached_to_groundwater_kgha", 0) or 0
    surface = nit.get("surface_runoff_kgha", 0) or 0
    total_loss = nit.get("total_no3_loss_kgha")
    if total_loss is None:
        total_loss = leached + surface + (nit.get("lateral_flow_kgha", 0) or 0) + (nit.get("tile_drain_kgha", 0) or 0)

    stream = nit.get("stream") or {}
    stream_conc = stream.get("mean_no3_mgL")

    # Peak monthly stream concentration and when it occurs.
    conc_points = [(m.get("no3_mgL"), m.get("month_label")) for m in monthly if m.get("no3_mgL") is not None]
    peak_conc, peak_month = (max(conc_points, key=lambda x: x[0]) if conc_points else (None, None))
    ref_conc = stream_conc if stream_conc is not None else peak_conc

    # Risk from field N loss (kg-N/ha/yr) and, when available, stream concentration.
    if total_loss >= 30 or (ref_conc is not None and ref_conc >= limit):
        severity, verdict = "critical", "high"
        headline = "High nitrate loss — fertilizer N is reaching groundwater"
        recommendation = "Cut and split nitrogen; add cover crops"
    elif total_loss >= 10 or (ref_conc is not None and ref_conc >= limit * 0.5):
        severity, verdict = "warning", "moderate"
        headline = "Moderate nitrate loss from your field"
        recommendation = "Tighten nitrogen timing to reduce leaching"
    else:
        severity, verdict = "ok", "low"
        headline = "Nitrate loss is low"
        recommendation = "Current nitrogen management looks efficient"

    detail = (
        f"N leached to groundwater {leached:.1f} kg/ha, surface runoff {surface:.1f} kg/ha, "
        f"total N loss {total_loss:.1f} kg/ha per year."
    )
    if ref_conc is not None:
        detail += f" Estimated stream nitrate-N ~{ref_conc:.1f} mg/L (limit {limit:.0f} mg/L)."

    season_note = ""
    if peak_month:
        season_note = (
            f" Stream nitrate peaks around {peak_month}, when low flow is mostly groundwater — "
            "the seasonal pattern documented in the Bazile Creek study."
        )

    advice = (
        "Apply only what the crop needs, split nitrogen into in-season applications, avoid fall "
        "application, and plant cover crops to keep nitrogen in the root zone instead of leaching "
        "to groundwater and the creek." + season_note
    )
    explanation = (
        f"About {total_loss:.1f} kg/ha of nitrate-N left your field this year "
        f"({leached:.1f} kg/ha of it downward to groundwater). Nitrogen the crop does not use "
        "leaches below the roots, travels with groundwater, and resurfaces in the stream — so "
        "reducing surplus nitrogen protects both your input costs and downstream water quality."
    )
    return {
        "headline": safe_text(headline),
        "severity": severity,
        "verdict": verdict,
        "recommendation": safe_text(recommendation),
        "detail": safe_text(detail),
        "advice": safe_text(advice),
        "explanation": safe_text(explanation),
    }


def interpret_drought(output: dict) -> dict:
    wb = output.get("water_balance") or {}
    soil = wb.get("soil_moisture_mm", 0)
    et = wb.get("et_mm", 0)
    precip = wb.get("precip_mm", 0)

    if soil < 150 or (precip < et * 0.5 and soil < 200):
        return {"headline": "High drought risk", "severity": "critical", "detail": f"Soil moisture {soil:.0f} mm.", "advice": "Monitor closely and plan irrigation."}
    if soil < 220:
        return {"headline": "Moderate drought risk", "severity": "warning", "detail": f"Soil moisture {soil:.0f} mm.", "advice": "Watch weather and soil moisture."}
    return {"headline": "Low drought risk", "severity": "ok", "detail": f"Soil moisture {soil:.0f} mm.", "advice": "Conditions look stable."}


def build_insights(output: Optional[dict]) -> dict[str, Any]:
    if not output:
        empty = {"headline": "Run a simulation first", "severity": "missing", "detail": "", "advice": ""}
        return {
            "irrigation": empty,
            "fertilizer": empty,
            "nitrate": empty,
            "drought_risk": empty,
            "yield": empty,
            "has_data": False,
        }
    return {
        "irrigation": interpret_irrigation(output),
        "fertilizer": interpret_fertilizer(output),
        "nitrate": interpret_nitrate(output),
        "drought_risk": interpret_drought(output),
        "yield": interpret_yield(output),
        "has_data": bool(output.get("water_balance")),
        "run_output": {
            "water_balance": output.get("water_balance"),
            "nutrient_balance": output.get("nutrient_balance"),
            "nitrate": output.get("nitrate"),
            "nitrate_monthly": output.get("nitrate_monthly"),
            "yield_kgha": output.get("yield_kgha"),
            "daily_series": output.get("daily_series"),
        },
    }


def get_farm_insights(farm_id: str) -> dict[str, Any]:
    readiness = readiness_service.get_farm_readiness(farm_id)
    if readiness.get("error"):
        return {"error": readiness["error"], "has_data": False}

    output = _latest_run_output(farm_id)
    insights = build_insights(output)
    insights["farm_id"] = farm_id
    insights["farm_name"] = readiness.get("farm_name")
    insights["readiness"] = readiness
    insights["last_run"] = readiness.get("last_run")

    # Additive: attach data/confidence self-assessment and per-insight confidence.
    from services import confidence_service

    assessment = confidence_service.assess_field_data_and_confidence(farm_id, readiness=readiness)
    insights["confidence"] = assessment
    for kind in ("irrigation", "fertilizer", "nitrate", "drought_risk", "yield"):
        conf = confidence_service.output_confidence(assessment, kind)
        if conf and isinstance(insights.get(kind), dict):
            insights[kind]["confidence"] = conf
    return insights


def _latest_run_output(farm_id: str) -> Optional[dict]:
    row = db_one(
        """SELECT results FROM simulations
           WHERE farm_id = ? AND status = 'completed' AND results IS NOT NULL
           ORDER BY completed_at DESC LIMIT 1""",
        (farm_id,),
    )
    if not row or not row.get("results"):
        return None
    try:
        return json.loads(row["results"])
    except json.JSONDecodeError:
        return None


def scenario_advice(scenario: str, output: dict) -> str:
    if scenario == "irrigation":
        i = interpret_irrigation(output)
        return i["recommendation"] + ". " + i["advice"]
    if scenario == "fertilizer":
        f = interpret_fertilizer(output)
        return f["recommendation"] + ". " + f["advice"]
    if scenario == "yield":
        return interpret_yield(output)["advice"]
    if scenario in ("nitrate", "water_quality"):
        n = interpret_nitrate(output)
        return n["recommendation"] + ". " + n["advice"]
    return build_insights(output).get("irrigation", {}).get("advice", "")


def build_chat_cards(tools_used: list[str], farm_id: str) -> list[dict[str, Any]]:
    """Structured insight cards for the chat UI after analysis tools run."""
    tool_map = {
        "run_irrigation_analysis": "irrigation",
        "run_fertilizer_analysis": "fertilizer",
        "run_nitrate_analysis": "nitrate",
        "run_yield_analysis": "yield",
    }
    requested = [tool_map[t] for t in tools_used if t in tool_map]
    if not requested:
        return []

    output = _latest_run_output(farm_id)
    if not output:
        return []

    from services import confidence_service
    assessment = confidence_service.assess_field_data_and_confidence(farm_id)

    cards: list[dict[str, Any]] = []
    for kind in requested:
        if kind == "irrigation":
            insight = interpret_irrigation(output)
            cards.append({
                "type": "irrigation",
                **insight,
                "water_balance": output.get("water_balance"),
            })
        elif kind == "fertilizer":
            insight = interpret_fertilizer(output)
            cards.append({
                "type": "fertilizer",
                **insight,
                "nutrient_balance": output.get("nutrient_balance"),
            })
        elif kind == "nitrate":
            insight = interpret_nitrate(output)
            cards.append({
                "type": "nitrate",
                **insight,
                "nitrate": output.get("nitrate"),
                "nitrate_monthly": output.get("nitrate_monthly"),
            })
        elif kind == "yield":
            insight = interpret_yield(output)
            cards.append({
                "type": "yield",
                **insight,
                "yield_kgha": output.get("yield_kgha"),
            })
        if cards:
            cards[-1]["confidence"] = confidence_service.output_confidence(assessment, kind)
    return cards


def build_widgets(
    tools_used: list[str],
    widget_requests: list[dict[str, Any]] | None,
    farm_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Generative-UI channel: build typed 'widget' envelopes + the canvas phase.

    (a) Interactive widgets from the agent's thin ``request_*`` markers, and
    (b) output ``result-card`` widgets from the existing 4-tool result map.
    Backward-compatible — also returns the legacy ``cards`` so the current UI keeps
    working while the chat-native UI reads ``widgets``.
    """
    widgets: list[dict[str, Any]] = []

    for req in (widget_requests or []):
        marker = req.get("marker") or {}
        kind = marker.get("kind")
        if not kind:
            continue
        interactive = bool(marker.get("interactive", True))
        env: dict[str, Any] = {
            "widget_id": req.get("tool_call_id") or f"w-{len(widgets)}",
            "kind": kind,
            "placement": marker.get("placement", "canvas"),
            "interactive": interactive,
            "title": marker.get("title"),
            "prompt": marker.get("prompt"),
            "payload": marker.get("payload", {}),
        }
        if kind in ("chart", "table"):  # widgets.ts requires a confidence field on these
            env["confidence"] = marker.get("confidence")
        if interactive:
            env["submit"] = {"endpoint": "/api/interact", "label": marker.get("submit_label", "Submit")}
        widgets.append(env)

    cards = build_chat_cards(tools_used, farm_id)
    for i, card in enumerate(cards):
        widgets.append({
            "widget_id": f"card-{i}",
            "kind": "result-card",
            "placement": "inline",
            "interactive": False,
            "title": None,
            "payload": card,
            "confidence": card.get("confidence"),
        })

    # Rich charts for the canvas from the latest run output, per analysis tool.
    chart_variants: list[str] = []
    for t in tools_used:
        chart_variants += _CHART_MAP.get(t, [])
    if chart_variants:
        output = _latest_run_output(farm_id)
        if output:
            from services import confidence_service
            assessment = confidence_service.assess_field_data_and_confidence(farm_id)
            for variant in dict.fromkeys(chart_variants):
                cw = _chart_widget(variant, output, assessment)
                if cw:
                    widgets.append(cw)

    has_interactive = any(w.get("interactive") for w in widgets)
    has_output = any(not w.get("interactive") for w in widgets)
    if has_interactive:
        phase = "collecting"
    elif has_output:
        phase = "results"
    else:
        phase = "idle"
    return widgets, cards, phase


_CHART_MAP = {
    "run_irrigation_analysis": ["water_balance", "soil_moisture"],
    "run_fertilizer_analysis": ["nutrient_balance"],
    "run_nitrate_analysis": ["stream_nitrate", "n_pathways"],
}

_CHART_TITLES = {
    "water_balance": "Water balance",
    "nutrient_balance": "Soil nutrients",
    "stream_nitrate": "Stream nitrate through the year",
    "n_pathways": "Where nitrogen leaves the field",
    "soil_moisture": "Soil moisture over time",
}

_CHART_CONF_KIND = {
    "water_balance": "irrigation",
    "soil_moisture": "irrigation",
    "nutrient_balance": "fertilizer",
    "stream_nitrate": "nitrate",
    "n_pathways": "nitrate",
}


def _chart_widget(variant: str, output: dict, assessment: dict) -> Optional[dict[str, Any]]:
    from services import confidence_service

    payload: dict[str, Any] = {"variant": variant}
    if variant == "water_balance":
        if not output.get("water_balance"):
            return None
        payload["water_balance"] = output["water_balance"]
    elif variant == "nutrient_balance":
        if not output.get("nutrient_balance"):
            return None
        payload["nutrient_balance"] = output["nutrient_balance"]
    elif variant == "stream_nitrate":
        if not output.get("nitrate_monthly"):
            return None
        payload["nitrate_monthly"] = output["nitrate_monthly"]
        payload["nitrate"] = output.get("nitrate")
    elif variant == "n_pathways":
        if not output.get("nitrate"):
            return None
        payload["nitrate"] = output["nitrate"]
    elif variant == "soil_moisture":
        if not output.get("daily_series"):
            return None
        payload["daily_series"] = output["daily_series"]
    else:
        return None
    conf = confidence_service.output_confidence(assessment, _CHART_CONF_KIND.get(variant, "irrigation"))
    return {
        "widget_id": f"chart-{variant}",
        "kind": "chart",
        "placement": "canvas",
        "interactive": False,
        "title": _CHART_TITLES.get(variant, "Chart"),
        "payload": payload,
        "confidence": conf,
    }
