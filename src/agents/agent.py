import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from core.time_utils import now_ist_str
from agents.tools.bigquery_tools import (
    get_campaign_terms,
    get_campaign_performance,
    get_spend_distribution,
    get_customer_reviews,
    get_merchant_feedback,
    get_delivery_metrics,
    get_comparable_campaigns,
    simulate_campaign_change,
)
from agents.tools.policy_tools import validate_proposal
from agents.tracer import ExecutionTracer
from core.config import get_config
from core.logging import logger
from domain.contracts import InvestigationReport
from prompts import format_investigation_prompt, get_system_instruction

config = get_config()

# Configure GCP project and location identical to bigquery_client
_gcp_project = getattr(getattr(config, "gcp", None), "project_id", "prj-imp-act-campaign")
_gcp_location = getattr(getattr(config, "gcp", None), "location", "asia-south1")

if "GOOGLE_CLOUD_PROJECT" not in os.environ and _gcp_project:
    os.environ["GOOGLE_CLOUD_PROJECT"] = _gcp_project
if "GCP_PROJECT" not in os.environ and _gcp_project:
    os.environ["GCP_PROJECT"] = _gcp_project
if "GOOGLE_CLOUD_LOCATION" not in os.environ and _gcp_location:
    os.environ["GOOGLE_CLOUD_LOCATION"] = _gcp_location

# If Gemini API key is present in environment, sync it; otherwise use Google Cloud Vertex AI like BigQuery client
_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if _API_KEY:
    os.environ["GEMINI_API_KEY"] = _API_KEY
    os.environ["GOOGLE_API_KEY"] = _API_KEY
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

APP_NAME = "merchant_offer_app"
USER_ID = "merchant_user"
MODEL_NAME = config.agent.model

agent = LlmAgent(
    name=config.agent.name,
    model=MODEL_NAME,
    instruction=get_system_instruction(),
    tools=[
        get_campaign_terms,
        get_campaign_performance,
        get_spend_distribution,
        get_customer_reviews,
        get_merchant_feedback,
        get_delivery_metrics,
        get_comparable_campaigns,
        validate_proposal,
        simulate_campaign_change,
    ],
)

root_agent = agent
runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
tracer = ExecutionTracer()


async def get_or_create_session(user_id: str, session_id: str):
    """Retrieve an existing session or create a new isolated session."""
    try:
        session = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if session:
            return session
    except Exception:
        pass

    return await runner.session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )


async def init_session(session_id: Optional[str] = None):
    sid = session_id or f"session_{int(time.time())}"
    return await get_or_create_session(USER_ID, sid)


async def get_session(session_id: Optional[str] = None):
    sid = session_id or f"session_{int(time.time())}"
    return await get_or_create_session(USER_ID, sid)


def extract_json_report(text: str) -> Optional[Dict[str, Any]]:
    """Extract and validate the JSON report from agent response text."""
    # Match markdown code block ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate_str = match.group(1) if match else text.strip()

    # Find outermost braces if raw text
    if not match:
        start_idx = candidate_str.find("{")
        end_idx = candidate_str.rfind("}")
        if start_idx != -1 and end_idx != -1:
            candidate_str = candidate_str[start_idx : end_idx + 1]

    try:
        data = json.loads(candidate_str)
        # Validate against Pydantic contract
        report = InvestigationReport(**data)
        return report.model_dump()
    except Exception as exc:
        logger.warning(f"Could not parse valid InvestigationReport JSON from text: {exc}")
        return None


async def process_alert_async(
    alert: Dict[str, Any],
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute end-to-end investigation workflow for an alert using Google ADK."""
    start_time = time.time()
    alert_id = alert.get("alert_id", "A_UNKNOWN")
    campaign_id = alert.get("campaign_id", "CMP_UNKNOWN")
    exec_id = execution_id or f"exec_{alert_id}_{int(start_time)}"
    session_id = f"session_alert_{alert_id}"

    # Configure GCP environment identical to bigquery_client
    gcp_proj = getattr(getattr(config, "gcp", None), "project_id", "prj-imp-act-campaign")
    gcp_loc = getattr(getattr(config, "gcp", None), "location", "asia-south1")
    if gcp_proj:
        os.environ["GOOGLE_CLOUD_PROJECT"] = gcp_proj
        os.environ["GCP_PROJECT"] = gcp_proj
    if gcp_loc:
        os.environ["GOOGLE_CLOUD_LOCATION"] = gcp_loc

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        os.environ["GOOGLE_API_KEY"] = api_key
    else:
        # Use Google Cloud Vertex AI credentials, identical to BigQuery client
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

    session = await get_or_create_session(USER_ID, session_id)
    prompt = format_investigation_prompt(alert)

    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""
    tool_calls_trace: List[Dict[str, Any]] = []
    tool_start_times: Dict[str, float] = {}
    prompt_tokens = 0
    candidates_tokens = 0
    total_tokens = 0
    cached_tokens = 0
    tool_use_tokens = 0
    thoughts_tokens = 0

    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=content,
        ):
            if hasattr(event, "usage_metadata") and event.usage_metadata:
                um = event.usage_metadata
                prompt_tokens = getattr(um, "prompt_token_count", prompt_tokens) or prompt_tokens
                candidates_tokens = getattr(um, "candidates_token_count", candidates_tokens) or candidates_tokens
                total_tokens = getattr(um, "total_token_count", total_tokens) or total_tokens
                cached_tokens = getattr(um, "cached_content_token_count", cached_tokens) or cached_tokens
                tool_use_tokens = getattr(um, "tool_use_prompt_token_count", tool_use_tokens) or tool_use_tokens
                thoughts_tokens = getattr(um, "thoughts_token_count", thoughts_tokens) or thoughts_tokens

            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if getattr(part, "function_call", None):
                        fc = part.function_call
                        tool_start_times[fc.name] = time.time()
                        logger.info(f"Tool called: {fc.name}", extra={"alert_id": alert_id, "tool_name": fc.name})
                        tool_calls_trace.append({
                            "type": "call",
                            "name": fc.name,
                            "args": fc.args,
                            "timestamp": time.time(),
                        })
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        start_t = tool_start_times.get(fr.name, time.time())
                        tool_duration_ms = round((time.time() - start_t) * 1000, 2)
                        logger.info(f"Tool responded: {fr.name} ({tool_duration_ms}ms)", extra={"alert_id": alert_id, "tool_name": fr.name})
                        tool_calls_trace.append({
                            "type": "response",
                            "name": fr.name,
                            "response": str(fr.response)[:5000],
                            "duration_ms": tool_duration_ms,
                            "timestamp": time.time(),
                        })
                    elif getattr(part, "text", None):
                        final_text += part.text

        duration_ms = round((time.time() - start_time) * 1000, 2)
        total_tool_latency_ms = round(sum(t.get("duration_ms", 0) for t in tool_calls_trace if t.get("type") == "response"), 2)

        
        # Total Input = prompt (initial prompt + instructions) + tool_use (results from tool execution)
        total_input_tokens = prompt_tokens + tool_use_tokens
        # Total Output = candidates (generated text/report) + thoughts (reasoning)
        total_output_tokens = candidates_tokens + thoughts_tokens
        # If total_tokens from API is reported, preserve it; otherwise sum input + output
        effective_total_tokens = total_tokens or (total_input_tokens + total_output_tokens)

        metrics = {
            "duration_ms": duration_ms,
            "tool_latency_ms": total_tool_latency_ms,
            "prompt_tokens": prompt_tokens,
            "tool_use_tokens": tool_use_tokens,
            "input_tokens": total_input_tokens,
            "candidates_tokens": candidates_tokens,
            "thoughts_tokens": thoughts_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": effective_total_tokens,
            "cached_tokens": cached_tokens,
            "tool_call_count": len([t for t in tool_calls_trace if t.get("type") == "call"]),
            "model": MODEL_NAME,
        }
        parsed_report = extract_json_report(final_text)

        now_str = now_ist_str()

        # Fallback if LLM output could not be strictly parsed as JSON
        if not parsed_report:
            parsed_report = {
                "alert_id": alert_id,
                "campaign_id": campaign_id,
                "execution_id": exec_id,
                "generated_at": now_str,
                "status": "COMPLETE",
                "summary": final_text[:1000],
                "findings": [
                    {
                        "observation": f"Alert {alert_id} investigated for campaign {campaign_id}.",
                        "evidence": [f"rule:{alert.get('rule_id')}"],
                    }
                ],
                "hypotheses": [],
                "proposal": {"type": "MONITOR", "rationale": "Review raw findings."},
                "simulation_type": "HISTORICAL_REPLAY",
                "future_incremental_spend": None,
                "human_approval_required": True,
                "metrics": metrics,
                "tool_calls": tool_calls_trace,
            }
        else:
            if not parsed_report.get("execution_id"):
                parsed_report["execution_id"] = exec_id
            if not parsed_report.get("generated_at"):
                parsed_report["generated_at"] = now_str
            parsed_report["metrics"] = metrics
            parsed_report["tool_calls"] = tool_calls_trace

        tracer.write_trace(
            alert_id=alert_id,
            campaign_id=campaign_id,
            model=MODEL_NAME,
            tool_calls=tool_calls_trace,
            report=parsed_report,
            duration_ms=duration_ms,
            execution_id=exec_id,
            metrics=metrics,
        )

        return {
            "success": True,
            "execution_id": exec_id,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "report": parsed_report,
            "raw_text": final_text,
            "tool_call_count": len([t for t in tool_calls_trace if t.get("type") == "call"]),
            "tool_calls": tool_calls_trace,
            "duration_ms": duration_ms,
            "metrics": metrics,
        }

    except Exception as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Investigation failed for alert {alert_id}: {exc}", extra={"alert_id": alert_id})
        total_input_tokens = prompt_tokens + tool_use_tokens
        total_output_tokens = candidates_tokens + thoughts_tokens
        effective_total_tokens = total_tokens or (total_input_tokens + total_output_tokens)
        metrics = {
            "duration_ms": duration_ms,
            "tool_latency_ms": 0.0,
            "prompt_tokens": prompt_tokens,
            "tool_use_tokens": tool_use_tokens,
            "input_tokens": total_input_tokens,
            "candidates_tokens": candidates_tokens,
            "thoughts_tokens": thoughts_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": effective_total_tokens,
            "cached_tokens": cached_tokens,
            "tool_call_count": len([t for t in tool_calls_trace if t.get("type") == "call"]),
            "model": MODEL_NAME,
        }
        tracer.write_trace(
            alert_id=alert_id,
            campaign_id=campaign_id,
            model=MODEL_NAME,
            tool_calls=tool_calls_trace,
            report=None,
            duration_ms=duration_ms,
            error=str(exc),
            execution_id=exec_id,
            metrics=metrics,
        )
        return {
            "success": False,
            "execution_id": exec_id,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "error": str(exc),
            "report": None,
            "tool_calls": tool_calls_trace,
            "duration_ms": duration_ms,
            "metrics": metrics,
        }
