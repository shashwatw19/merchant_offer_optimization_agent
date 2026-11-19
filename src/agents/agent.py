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
from agents.telemetry import ExecutionMetricsCollector
from agents.tracer import ExecutionTracer
from core.config import get_config
from core.logging import logger
from domain.contracts import InvestigationReport
from prompts import format_investigation_prompt, get_system_instruction

config = get_config()

APP_NAME = "merchant_offer_app"
USER_ID = "merchant_user"
MODEL_NAME = config.agent.model

_RULE_RUNNERS: Dict[str, InMemoryRunner] = {}


def get_runner_for_rule(rule_id: Optional[str] = None) -> InMemoryRunner:
    """Return an InMemoryRunner configured with the rule-specific Playbook system instruction."""
    clean_rule = (rule_id or "DEFAULT").upper()
    if clean_rule not in _RULE_RUNNERS:
        instruction = get_system_instruction(clean_rule)
        rule_agent = LlmAgent(
            name=f"{config.agent.name}_{clean_rule.lower()}",
            model=MODEL_NAME,
            instruction=instruction,
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
        _RULE_RUNNERS[clean_rule] = InMemoryRunner(agent=rule_agent, app_name=APP_NAME)
    return _RULE_RUNNERS[clean_rule]


# Default runner and agent references for backward compatibility
runner = get_runner_for_rule("DEFAULT")
agent = runner.agent
root_agent = agent
tracer = ExecutionTracer()


async def get_or_create_session(user_id: str, session_id: str, runner_instance: Optional[InMemoryRunner] = None):
    """Retrieve an existing session or create a new isolated session."""
    active_runner = runner_instance or runner
    try:
        session = await active_runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if session:
            return session
    except Exception:
        pass

    return await active_runner.session_service.create_session(
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


def _create_fallback_report(
    alert: Dict[str, Any],
    alert_id: str,
    campaign_id: str,
    exec_id: str,
    now_str: str,
    final_text: str,
    metrics: Dict[str, Any],
    tool_calls_trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Construct a safe fallback report when the LLM output cannot be strictly parsed as JSON."""
    return {
        "alert_id": alert_id,
        "campaign_id": campaign_id,
        "execution_id": exec_id,
        "generated_at": now_str,
        "status": "COMPLETE",
        "summary": final_text[:1000] if final_text else f"Investigation completed for alert {alert_id}.",
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


def _record_run_telemetry(
    execution_id: str,
    alert: Dict[str, Any],
    status: str,
    metrics: Dict[str, Any],
    tool_calls_trace: List[Dict[str, Any]],
    run_number: Optional[int] = None,
    gcs_json_uri: Optional[str] = None,
    gcs_markdown_uri: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Persist agent run execution telemetry to BigQuery table card_gold.agent_runs."""
    try:
        from services.run_store import record_agent_run
        record_agent_run(
            execution_id=execution_id,
            alert_id=alert.get("alert_id", "A_UNKNOWN"),
            campaign_id=alert.get("campaign_id", "CMP_UNKNOWN"),
            merchant_id=alert.get("merchant_id"),
            rule_id=alert.get("rule_id"),
            run_number=run_number,
            status=status,
            metrics=metrics,
            tool_calls=tool_calls_trace,
            gcs_json_uri=gcs_json_uri,
            gcs_markdown_uri=gcs_markdown_uri,
            error=error,
            agent_name=config.agent.name,
            model_name=MODEL_NAME,
        )
    except Exception as run_exc:
        logger.debug(f"Could not record BigQuery agent run: {run_exc}")


async def process_alert_async(
    alert: Dict[str, Any],
    execution_id: Optional[str] = None,
    run_number: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute end-to-end investigation workflow for an alert using Google ADK."""
    from services.run_store import generate_execution_id, get_next_run_number

    start_time = time.time()
    alert_id = alert.get("alert_id", "A_UNKNOWN")
    campaign_id = alert.get("campaign_id", "CMP_UNKNOWN")

    resolved_run_num = run_number
    if resolved_run_num is None and not execution_id:
        resolved_run_num = get_next_run_number(alert_id)

    exec_id = execution_id or generate_execution_id(alert_id, run_number=resolved_run_num)
    session_id = f"session_alert_{alert_id}"

    rule_id = alert.get("rule_id", "DEFAULT")
    rule_runner = get_runner_for_rule(rule_id)
    session = await get_or_create_session(USER_ID, session_id, runner_instance=rule_runner)
    prompt = format_investigation_prompt(alert)

    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    collector = ExecutionMetricsCollector(model_name=MODEL_NAME, alert_id=alert_id)

    try:
        async for event in rule_runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=content,
        ):
            collector.process_event(event)

        collector.end_time = time.time()
        metrics = collector.compute_metrics()
        duration_ms = metrics["duration_ms"]
        tool_calls_trace = collector.tool_calls_trace
        final_text = collector.final_text
        parsed_report = extract_json_report(final_text)
        now_str = now_ist_str()

        if not parsed_report:
            parsed_report = _create_fallback_report(
                alert=alert,
                alert_id=alert_id,
                campaign_id=campaign_id,
                exec_id=exec_id,
                now_str=now_str,
                final_text=final_text,
                metrics=metrics,
                tool_calls_trace=tool_calls_trace,
            )
        else:
            if not parsed_report.get("execution_id"):
                parsed_report["execution_id"] = exec_id
            if not parsed_report.get("generated_at"):
                parsed_report["generated_at"] = now_str
            parsed_report["metrics"] = metrics
            parsed_report["tool_calls"] = tool_calls_trace

        if resolved_run_num is not None:
            parsed_report["run_number"] = resolved_run_num

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

        _record_run_telemetry(
            execution_id=exec_id,
            alert=alert,
            status="SUCCESS",
            metrics=metrics,
            tool_calls_trace=tool_calls_trace,
            run_number=resolved_run_num,
        )

        return {
            "success": True,
            "execution_id": exec_id,
            "run_number": resolved_run_num,
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
        collector.end_time = time.time()
        duration_ms = collector.get_duration_ms()
        logger.error(f"Investigation failed for alert {alert_id}: {exc}", extra={"alert_id": alert_id})
        metrics = collector.compute_metrics()
        tool_calls_trace = collector.tool_calls_trace

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

        _record_run_telemetry(
            execution_id=exec_id,
            alert=alert,
            status="FAILED",
            metrics=metrics,
            tool_calls_trace=tool_calls_trace,
            run_number=resolved_run_num,
            error=str(exc),
        )

        return {
            "success": False,
            "execution_id": exec_id,
            "run_number": resolved_run_num,
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "error": str(exc),
            "report": None,
            "tool_calls": tool_calls_trace,
            "duration_ms": duration_ms,
            "metrics": metrics,
        }
