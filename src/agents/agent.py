import asyncio
import json
from typing import Any, Dict
 
from google.adk.runners import InMemoryRunner
from google.genai import types
 
from agents.tools.bigquery_tools import (
    get_campaign_terms,
    get_campaign_performance,
    get_spend_distribution,
    get_customer_reviews,
    get_merchant_feedback,
    get_delivery_metrics,
    simulate_campaign_change,
)

 
from agents.tools.policy_tools import validate_proposal

APP_NAME = "merchant_offer_app"
USER_ID = "merchant_user"
 
try:
    from google.adk.agents import LlmAgent
    agent = LlmAgent(
        name="merchant_offer_investigator",
        model="gemini-3.5-flash",
        instruction="""
        You are a merchant offer investigation agent.
 
        Rules:
        - Use only the approved tools.
        - Treat the alert as the starting point.
        - Separate fact from hypothesis.
        - Use tool outputs as evidence.
        - Validate any campaign proposal before suggesting a change.
        - Historical replay is retrospective only.
        - If evidence is weak, say so clearly.
        - Human approval is required before operational action.
        """,
        tools=[
            get_campaign_terms,
            get_campaign_performance,
            get_spend_distribution,
            get_customer_reviews,
            get_merchant_feedback,
            get_delivery_metrics,
            validate_proposal,
            simulate_campaign_change,
        ],
    )
except Exception:
    from google.adk import Agent
    agent = Agent(
        name="merchant_offer_investigator",
        model="gemini-3.5-flash",
        instruction="""
        You are a merchant offer investigation agent.
 
        Rules:
        - Use only the approved tools.
        - Treat the alert as the starting point.
        - Separate fact from hypothesis.
        - Use tool outputs as evidence.
        - Validate any campaign proposal before suggesting a change.
        - Historical replay is retrospective only.
        - If evidence is weak, say so clearly.
        - Human approval is required before operational action.
        """,
        tools=[
            get_campaign_terms,
            get_campaign_performance,
            get_spend_distribution,
            get_customer_reviews,
            get_merchant_feedback,
            get_delivery_metrics,
            validate_proposal,
            simulate_campaign_change,
        ],
    )
 
runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
 
 
async def init_session():
    return await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
 
 
async def get_session():
    return await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
 
 
async def process_alert_async(alert: Dict[str, Any]) -> str:
    session = await get_session()
    prompt = f"""
    Investigate this merchant offer alert.
 
    Alert:
    {json.dumps(alert, indent=2, default=str)}
 
    Instructions:
    1. Use only approved tools.
    2. Fetch campaign details, performance, merchant spend, delivery metrics, and customer feedback as needed.
    3. Separate facts from hypotheses.
    4. If proposing a campaign change, validate it first.
    5. Return a final recommendation and clearly state human approval is required.
    """
 
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=content,
    ):

        if hasattr(event, "content") and event.content:
            for part in event.content.parts:

                if getattr(part, "function_call", None):
                    print(
                        f"TOOL CALLED: {part.function_call.name}"
                    )

                elif getattr(part, "function_response", None):
                    print(
                        f"TOOL RESPONSE: {part.function_response.response}"
                    )

                elif getattr(part, "text", None):
                    final_text += part.text
    return final_text
 
 
root_agent = agent