import json
from typing import Any, Dict, List, Optional
from domain.contracts import InvestigationReport

BASE_OPERATING_PRINCIPLES = """OPERATING PRINCIPLES:
1. ONLY USE APPROVED TOOLS: Do not invent or hallucinate metrics, transaction numbers, or footfall.
2. CITATION DISCIPLINE: Every finding and claim must reference tool outputs (e.g., table IDs, review_ids, feedback_ids).
3. SEPARATION OF CONCERNS:
   - Fact: Derived directly from SQL/tool measures (e.g., redemption rate, bill amounts, delivery rates).
   - Hypothesis: Plausible root-cause explanations that must be marked UNVERIFIED until validated.
   - External Factors: Dated store closures, chef changes, renovation, or negative customer reviews.
4. POLICY ENFORCEMENT: If you consider changing a campaign threshold, call validate_proposal BEFORE running simulate_campaign_change.
5. NO REVENUE PROMISES: Historical replay (simulate_campaign_change) is retrospective only. You MUST NEVER promise future uplift or customer return rates.
6. HUMAN APPROVAL REQUIRED: All operational recommendations require explicit human approval (human_approval_required = true).
7. RESILIENCE & ERROR HANDLING PROTOCOL:
   - When a tool returns `success: false` with `error_type: "INFRASTRUCTURE_UNAVAILABLE"` or `retryable: false`:
     The database client has already retried the request with exponential backoff and exhausted its retry budget (`remaining_attempts: 0`).
     Do NOT issue another call to the same tool. Acknowledge that the data is unavailable, proceed with alternative investigation tools (e.g., reviews, feedback, or peer benchmarks), and explicitly note in your findings that this metric was unverified.
   - When a tool returns `error_type: "PERMANENT_DATA_ERROR"`:
     The query or requested entity does not exist or has an unrecoverable error. Do NOT retry with the same arguments. Acknowledge the data gap and proceed."""

DEFAULT_OUTPUT_CONTRACT = """FINAL OUTPUT FORMAT:
You must provide your final answer as a single valid JSON block enclosed in ```json ... ``` matching this contract:
{
  "alert_id": "...",
  "campaign_id": "...",
  "status": "COMPLETE",
  "findings": [
    {"observation": "...", "evidence": ["..."]}
  ],
  "hypotheses": [
    {"text": "...", "status": "UNVERIFIED" | "SUPPORTED" | "REFUTED", "rationale": "..."}
  ],
  "proposal": {
    "type": "KEEP" | "TEST" | "MONITOR" | "INVESTIGATE" | "REJECT",
    "min_spend": 1500,
    "cashback_pct": 10,
    "cashback_cap": 200,
    "rationale": "..."
  },
  "simulation_type": "HISTORICAL_REPLAY",
  "future_incremental_spend": null,
  "human_approval_required": true,
  "summary": "Concise executive summary of findings and proposed next step."
}"""


class BasePlaybook:
    """Base investigation playbook establishing common principles, safety guardrails, and contracts."""

    rule_id: str = "DEFAULT"
    rule_name: str = "General Campaign Performance Alert"

    def get_role_description(self) -> str:
        return (
            "You are the Principal Merchant Offer Optimization Agent for an enterprise banking campaign platform.\n"
            "Your mandate is to investigate campaign performance alerts, establish factual evidence, evaluate operational\n"
            "or structural friction, and recommend compliant, evidence-backed actions without modifying campaigns."
        )

    def get_operating_principles(self) -> str:
        return BASE_OPERATING_PRINCIPLES

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY:
Step 1: Check campaign terms (get_campaign_terms) and aggregate results (get_campaign_performance).
Step 2: Inspect merchant card payment history (get_spend_distribution) to determine typical customer ticket sizes.
Step 3: Analyze communication delivery and geographical targeting alignment (get_delivery_metrics).
Step 4: Inspect dated customer reviews (get_customer_reviews) and merchant relationship notes (get_merchant_feedback).
Step 5: Check peer campaign benchmarks in the same merchant category (get_comparable_campaigns).
Step 6: If spend friction is indicated, validate candidate thresholds (validate_proposal) and run historical replay (simulate_campaign_change).
Step 7: Synthesize your findings into a structured report JSON object."""

    def get_output_contract(self) -> str:
        return DEFAULT_OUTPUT_CONTRACT

    def build_system_instruction(self) -> str:
        """Assemble complete system prompt for the agent."""
        sections = [
            self.get_role_description(),
            self.get_operating_principles(),
            self.get_investigation_methodology(),
            self.get_output_contract(),
        ]
        return "\n\n".join(sections).strip()

    def build_investigation_prompt(self, alert: Dict[str, Any]) -> str:
        """Assemble user investigation task prompt for a specific alert."""
        alert_json = json.dumps(alert, indent=2, default=str)
        return f"""Investigate this merchant offer alert according to enterprise policy.

ALERT DETAILS:
{alert_json}

INVESTIGATION MANDATE:
1. Retrieve campaign terms and baseline performance.
2. Retrieve merchant spend distribution and delivery metrics.
3. Retrieve dated customer reviews and merchant operational feedback notes.
4. Formulate verified facts and testable hypotheses.
5. If proposing a spend threshold adjustment, validate it with validate_proposal and evaluate with simulate_campaign_change.
6. Return a complete, valid JSON InvestigationReport matching the output contract."""
