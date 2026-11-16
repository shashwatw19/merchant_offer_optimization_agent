import asyncio
import json
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

APP_NAME = "merchant_offer_app"
USER_ID = "merchant_user"
MODEL_NAME = config.agent.model

TOOL_PURPOSES: Dict[str, str] = {
    "get_campaign_terms": "Retrieve campaign discount structure, budget limits, minimum spend, and operational status.",
    "get_campaign_performance": "Fetch historical impressions, clicks, spend, redemption rate, and customer reach.",
    "get_spend_distribution": "Analyze customer transaction spend distribution relative to minimum spend thresholds.",
    "get_customer_reviews": "Inspect customer sentiment and qualitative feedback regarding offer value and experience.",
    "get_merchant_feedback": "Evaluate merchant satisfaction, margin constraints, and business preferences.",
    "get_delivery_metrics": "Analyze order fulfillment latency, cancellation rates, and operational bottlenecks.",
    "get_comparable_campaigns": "Benchmark campaign performance against similar merchant campaigns in the same category.",
    "validate_proposal": "Verify proposed changes against business guardrails, allowed thresholds, and budget caps.",
    "simulate_campaign_change": "Run deterministic historical replay simulation on past transactions to project financial impact.",
}

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
    """Execute end-to-end investigation workflow for an alert using Google ADK with full execution observability."""
    start_time = time.time()
    alert_id = alert.get("alert_id", "A_UNKNOWN")
    campaign_id = alert.get("campaign_id", "CMP_UNKNOWN")
    exec_id = execution_id or f"exec_{alert_id}_{int(start_time)}"
    session_id = f"session_alert_{alert_id}"

    session = await get_or_create_session(USER_ID, session_id)
    prompt = format_investigation_prompt(alert)

    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""
    tool_calls_trace: List[Dict[str, Any]] = []
    execution_steps: List[Dict[str, Any]] = []
    tool_start_times: Dict[str, float] = {}
    step_counter = 0

    prompt_tokens = 0
    candidates_tokens = 0
    total_tokens = 0

    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=content,
        ):
            # Capture observable token consumption from Google ADK response metadata
            usage = getattr(event, "usage_metadata", None)
            if usage:
                p_tok = getattr(usage, "prompt_token_count", 0) or 0
                c_tok = getattr(usage, "candidates_token_count", 0) or 0
                t_tok = getattr(usage, "total_token_count", 0) or 0
                if p_tok:
                    prompt_tokens = p_tok
                if c_tok:
                    candidates_tokens = c_tok
                if t_tok:
                    total_tokens = t_tok

            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if getattr(part, "function_call", None):
                        fc = part.function_call
                        step_counter += 1
                        tool_start_times[fc.name] = time.time()
                        fc_args = {}
                        try:
                            if hasattr(fc, "args") and fc.args:
                                fc_args = dict(fc.args)
                        except Exception:
                            fc_args = {"raw": str(getattr(fc, "args", ""))}

                        logger.info(f"Tool called: {fc.name}", extra={"alert_id": alert_id, "tool_name": fc.name})
                        tool_calls_trace.append({
                            "step": step_counter,
                            "type": "call",
                            "name": fc.name,
                            "args": fc_args,
                            "timestamp": time.time(),
                        })
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        st = tool_start_times.get(fr.name, time.time())
                        step_duration_ms = round((time.time() - st) * 1000, 1)

                        resp_val = getattr(fr, "response", {})
                        resp_preview = str(resp_val)
                        if len(resp_preview) > 500:
                            resp_preview = resp_preview[:500] + "... [truncated]"

                        is_success = True
                        if isinstance(resp_val, dict):
                            is_success = resp_val.get("success", True)

                        # Match with preceding call
                        matching_call = next(
                            (c for c in reversed(tool_calls_trace) if c.get("name") == fr.name and c.get("type") == "call"),
                            None,
                        )
                        args = matching_call.get("args") if matching_call else {}
                        step_num = matching_call.get("step") if matching_call else step_counter

                        purpose = TOOL_PURPOSES.get(fr.name, "Execute investigation tool")

                        execution_steps.append({
                            "step_number": step_num,
                            "agent": config.agent.name,
                            "tool_name": fr.name,
                            "purpose": purpose,
                            "inputs": args,
                            "output_preview": resp_preview,
                            "duration_ms": step_duration_ms,
                            "status": "SUCCESS" if is_success else "ERROR",
                        })

                        logger.info(f"Tool responded: {fr.name}", extra={"alert_id": alert_id, "tool_name": fr.name})
                        tool_calls_trace.append({
                            "step": step_num,
                            "type": "response",
                            "name": fr.name,
                            "response": resp_preview,
                            "duration_ms": step_duration_ms,
                            "timestamp": time.time(),
                        })
                    elif getattr(part, "text", None):
                        final_text += part.text

        duration_ms = round((time.time() - start_time) * 1000, 2)
        parsed_report = extract_json_report(final_text)

        # Fallback token estimation if provider did not surface usage_metadata
        if total_tokens == 0:
            prompt_tokens = max(1, len(prompt) // 4)
            candidates_tokens = max(1, len(final_text) // 4)
            total_tokens = prompt_tokens + candidates_tokens

        execution_trace = {
            "execution_id": exec_id,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "agent_name": config.agent.name,
            "model": MODEL_NAME,
            "total_duration_ms": duration_ms,
            "tokens": {
                "input_tokens": prompt_tokens,
                "output_tokens": candidates_tokens,
                "total_tokens": total_tokens or (prompt_tokens + candidates_tokens),
            },
            "tool_calls_count": len(execution_steps),
            "steps": execution_steps,
            "status": "SUCCESS" if parsed_report else "FAILED",
        }

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
            }
        else:
            if not parsed_report.get("execution_id"):
                parsed_report["execution_id"] = exec_id
            if not parsed_report.get("generated_at"):
                parsed_report["generated_at"] = now_str

        # Attach execution trace directly into parsed report
        parsed_report["execution_trace"] = execution_trace

        tracer.write_trace(
            alert_id=alert_id,
            campaign_id=campaign_id,
            model=MODEL_NAME,
            tool_calls=tool_calls_trace,
            report=parsed_report,
            duration_ms=duration_ms,
            execution_id=exec_id,
        )

        return {
            "success": True,
            "execution_id": exec_id,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "report": parsed_report,
            "trace": execution_trace,
            "raw_text": final_text,
            "tool_call_count": len(execution_steps),
            "duration_ms": duration_ms,
        }

    except Exception as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(f"Investigation failed for alert {alert_id}: {exc}", extra={"alert_id": alert_id})

        if total_tokens == 0:
            prompt_tokens = max(1, len(prompt) // 4)
            candidates_tokens = max(0, len(final_text) // 4)
            total_tokens = prompt_tokens + candidates_tokens

        failed_trace = {
            "execution_id": exec_id,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "agent_name": config.agent.name,
            "model": MODEL_NAME,
            "total_duration_ms": duration_ms,
            "tokens": {
                "input_tokens": prompt_tokens,
                "output_tokens": candidates_tokens,
                "total_tokens": total_tokens or (prompt_tokens + candidates_tokens),
            },
            "tool_calls_count": len(execution_steps),
            "steps": execution_steps,
            "status": "FAILED",
            "error": str(exc),
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
        )
        return {
            "success": False,
            "execution_id": exec_id,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "error": str(exc),
            "report": None,
            "trace": failed_trace,
            "duration_ms": duration_ms,
        }
