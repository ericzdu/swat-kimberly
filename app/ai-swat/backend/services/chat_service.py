"""
Shared AI chat — LangGraph agent with LangChain tool calling.
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.agent import build_agent
from db import create_chat_session, create_message, db_one, get_messages
from services import insights_service, readiness_service
from services.llm_service import LLMConfigError, get_ai_status, resolve_provider_model, simple_chat
from utils.text import safe_text

logger = logging.getLogger(__name__)

FARMER_SYSTEM = """You are AgriAdvisor, a friendly farm assistant inside AI-SWAT+ (standalone software).
Use plain language. Never mention QSWAT+ or external editors — crop and setup are in Setup and Maps in this app.
If simulation data is provided, base your advice on those numbers."""

AGENT_RECURSION_LIMIT = 30


def _farm_context_message(farm: dict) -> str:
    from services import confidence_service

    readiness = readiness_service.get_farm_readiness(farm["id"])
    insights = insights_service.get_farm_insights(farm["id"])
    parts = [
        f"Farm: {farm['name']}",
        f"Location: {farm.get('location') or 'unknown'}",
        f"Soil: {farm.get('soil_type') or 'unknown'}",
        f"Farm ID: {farm['id']}",
        f"Ready to simulate: {readiness.get('ready_to_simulate', False)}",
    ]
    if insights.get("has_data"):
        wb = insights.get("run_output", {}).get("water_balance") or {}
        nb = insights.get("run_output", {}).get("nutrient_balance") or {}
        parts.append(
            f"Latest results - soil moisture {wb.get('soil_moisture_mm', 0):.0f} mm, "
            f"ET {wb.get('et_mm', 0):.0f} mm, N {nb.get('nitrogen_kgha', 0):.0f} kg/ha"
        )
    context = "FARM CONTEXT:\n" + "\n".join(parts)

    # Reuse the readiness we already computed so the assessment doesn't refetch it.
    assessment = confidence_service.assess_field_data_and_confidence(farm["id"], readiness=readiness)
    block = confidence_service.compact_confidence_block(assessment)
    if block:
        context += "\n\n" + block
    return context


def _extract_created_farm_id(messages: list) -> str | None:
    """If create_new_field succeeded, return the new farm id for the UI to switch."""
    for msg in messages:
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "") or ""
            if name != "create_new_field":
                continue
            content = str(msg.content or "")
            try:
                import json
                data = json.loads(content)
                if data.get("ok") and data.get("farm_id"):
                    return str(data["farm_id"])
            except json.JSONDecodeError:
                pass
    return None


def _extract_widget_requests(messages: list) -> list[dict]:
    """Pull generative-UI markers ({"__widget__": {...}}) returned by request_* tools,
    tagged with the originating tool_call_id. Mirrors _extract_tool_trace."""
    import ast
    import json as _json

    reqs: list[dict] = []
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = str(getattr(msg, "content", "") or "")
        if "__widget__" not in content:
            continue
        data = None
        try:
            data = _json.loads(content)
        except Exception:
            try:
                data = ast.literal_eval(content)
            except Exception:
                data = None
        if not isinstance(data, dict):
            continue
        marker = data.get("__widget__")
        if not isinstance(marker, dict):
            continue
        reqs.append({
            "tool_call_id": getattr(msg, "tool_call_id", None) or f"w-{len(reqs)}",
            "marker": marker,
        })
    return reqs


def _extract_tool_trace(messages: list) -> tuple[list[str], str | None]:
    """Parse LangChain message trace for tool names and simulation run_id."""
    tools_used: list[str] = []
    sim_id = None
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?")
                tools_used.append(str(name))
        if isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "") or ""
            if name and name not in tools_used:
                tools_used.append(name)
            content = str(msg.content or "")
            if name == "start_swat_simulation" and len(content) == 36 and not content.startswith("ERROR"):
                sim_id = content
            if name == "wait_for_simulation" and '"run_id"' in content:
                try:
                    import json
                    data = json.loads(content)
                    sim_id = data.get("run_id") or sim_id
                except json.JSONDecodeError:
                    pass
    return tools_used, sim_id


def run_agent_chat(
    farm_id: str,
    message: str,
    provider: str | None = None,
    model: str | None = None,
    use_agent: bool = True,
    session_id: str | None = None,
) -> dict:
    farm = db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if not farm:
        return _error_response("Please select a farm first.")

    if not session_id:
        session = create_chat_session(farm_id)
        session_id = session["id"]

    try:
        provider, model = resolve_provider_model(provider, model)
    except LLMConfigError as exc:
        return {
            **_error_response(safe_text(str(exc)) + " Open Settings to configure Ollama or a cloud API."),
            "mode": "config_error",
            "provider": provider,
            "model": model,
            "session_id": session_id,
        }

    create_message(farm_id, "user", message, session_id)
    context = _farm_context_message(farm)

    if use_agent:
        result = _run_with_agent(farm_id, session_id, context, provider, model)
        if result:
            result["session_id"] = session_id
            return result
        logger.warning("LangGraph agent failed — falling back to simple chat")

    result = _run_simple_chat(farm_id, session_id, message, context, provider, model)
    result["session_id"] = session_id
    return result


def render_resume_message(kind: str, data: dict) -> str:
    """Deterministic synthetic message from a widget submission — the two-way loop.
    Embeds the structured answer verbatim so the agent re-derives intent reliably.
    NOTE: server code, never model output; no ToolMessage injection."""
    data = data or {}
    if kind == "choice":
        picked = data.get("label") or data.get("value") or data
        return f"I choose: {picked}"
    if kind == "confirm":
        return "Yes, go ahead." if data.get("confirmed") else "No, do not do that."
    if kind == "field-picker":
        return f"Use this field: {data.get('label') or data.get('farm_id')}."
    if kind == "map-draw":
        area = data.get("area_ha")
        area_txt = f" (about {area:.0f} ha)" if isinstance(area, (int, float)) else ""
        return (
            f"I drew and saved my field boundary on the map{area_txt}. "
            "Now download real elevation, soil, and weather for this boundary and build my SWAT+ "
            "field model (fetch_online_map_data or auto_setup_field_for_swat), then tell me what you set up."
        )
    if kind == "form":
        vals = data.get("values") or {}
        action = data.get("submit_action") or ""
        if action == "save_farm_crop_settings":
            return (
                f"Set my crop to {vals.get('crop_type')} planted {vals.get('planting_date')}. "
                "Use save_farm_crop_settings, then continue."
            )
        pairs = ", ".join(f"{k}={v}" for k, v in vals.items())
        return f"Here are my inputs: {pairs}. Apply them ({action}) and continue."
    import json as _json
    return f"[{kind} submitted] {_json.dumps(data, default=str)}"


def run_interaction(
    farm_id: str,
    session_id: str,
    widget_id: str,
    kind: str,
    data: dict,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Resume the conversation from a widget submission by re-running the exact
    stateless agent path with a deterministic synthetic message."""
    synthetic = render_resume_message(kind, data)
    return run_agent_chat(
        farm_id=farm_id,
        message=synthetic,
        provider=provider,
        model=model,
        use_agent=True,
        session_id=session_id,
    )


def _run_with_agent(
    farm_id: str,
    session_id: str,
    context: str,
    provider: str,
    model: str,
) -> dict | None:
    history = get_messages(farm_id, session_id, limit=12)
    lc_messages: list = [SystemMessage(content=context)]
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))

    try:
        agent = build_agent(provider, model, farm_id)
        result = agent.invoke(
            {"messages": lc_messages},
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )
    except Exception as exc:
        logger.warning("Agent invoke failed: %s", exc, exc_info=True)
        return None

    messages = result.get("messages", [])
    if not messages:
        return None

    final_msg = messages[-1]
    if isinstance(final_msg.content, str):
        response_text = final_msg.content
    elif isinstance(final_msg.content, list):
        response_text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in final_msg.content
        )
    else:
        response_text = str(final_msg.content)

    tools_used, sim_id = _extract_tool_trace(messages)
    created_farm_id = _extract_created_farm_id(messages)

    # Never leave a run silently "running in the background". If the model started a
    # simulation but didn't wait for it (LLMs are unreliable at chaining the wait
    # tool), poll it to a terminal state here and surface the real outcome — above
    # all, a FAILURE — instead of trusting the model's narration.
    sim_failed = False
    if sim_id and "wait_for_simulation" not in tools_used:
        from services.field_setup_service import _poll_simulation
        outcome = _poll_simulation(sim_id, max_wait=45)
        state = outcome.get("status")
        if state in ("failed", "cancelled", "not_found"):
            sim_failed = True
            detail = safe_text(str(outcome.get("error") or f"run {state}"))
            response_text += (
                f"\n\n⚠️ **The model run did not complete — it {state}.** {detail}\n"
                "Nothing is still running. This usually means the field's inputs need "
                "attention (weather, soil, or management). Tell me and I'll help fix it."
            )
        elif outcome.get("error") == "Simulation timed out":
            response_text += (
                "\n\n⏳ The model is still running — results will appear here as soon as it finishes."
            )

    # Generative-UI channel: widgets[] + canvas phase. `cards` kept as a
    # backward-compatible alias so the current UI keeps rendering unchanged.
    widget_requests = _extract_widget_requests(messages)
    widgets, cards, phase = insights_service.build_widgets(tools_used, widget_requests, farm_id)

    create_message(
        farm_id, "assistant", response_text,
        session_id, tools_used=tools_used, simulation_id=sim_id, cards=cards, widgets=widgets,
    )
    result = {
        "response": response_text,
        "simulation_id": sim_id,
        "simulation_failed": sim_failed,
        "provider": provider,
        "model": model,
        "mode": "agent",
        "tools_used": tools_used,
        "cards": cards,
        "widgets": widgets,
        "phase": phase,
    }
    if created_farm_id:
        result["created_farm_id"] = created_farm_id
    return result


def _run_simple_chat(
    farm_id: str,
    session_id: str,
    message: str,
    context: str,
    provider: str,
    model: str,
) -> dict:
    history = get_messages(farm_id, session_id, limit=10)
    messages = [{"role": "system", "content": FARMER_SYSTEM + "\n\n" + context}]
    for msg in history[-6:]:
        if msg.get("role") in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    try:
        resp = simple_chat(provider, model, messages)
    except Exception as exc:
        return {
            **_error_response(safe_text(f"AI error ({provider}): {exc}")),
            "provider": provider,
            "model": model,
            "mode": "error",
        }

    create_message(farm_id, "assistant", resp.content, session_id)
    return {
        "response": resp.content,
        "simulation_id": None,
        "provider": provider,
        "model": model,
        "mode": "chat",
        "tools_used": [],
        "cards": [],
    }


def _error_response(text: str, session_id: str | None = None) -> dict:
    return {
        "response": safe_text(text),
        "simulation_id": None,
        "provider": None,
        "model": None,
        "mode": "error",
        "tools_used": [],
        "cards": [],
        "session_id": session_id,
    }


def get_chat_ai_status() -> dict:
    status = get_ai_status()
    status["agent"] = {
        "framework": "langgraph",
        "tool_calling": True,
        "recursion_limit": AGENT_RECURSION_LIMIT,
    }
    return status
