from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class PlaybookR1(BasePlaybook):
    """Playbook for Rule R1: Low Redemption Rate (< 5% of targeted customer audience)."""

    rule_id: str = "R1"
    rule_name: str = "Low Redemption Rate Investigation"

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY (RULE R1 - LOW REDEMPTION FRICTION):
Focus on transaction barrier and spend threshold friction:
Step 1: Retrieve campaign terms (get_campaign_terms) and redemption performance (get_campaign_performance).
Step 2: Inspect merchant card payment history (get_spend_distribution) to determine typical ticket size percentiles and median bill.
Step 3: Compare median ticket size against configured minimum spend threshold. If minimum spend is substantially higher than median spend, formulate the Spend Friction Hypothesis.
Step 4: Check peer campaigns in the category (get_comparable_campaigns) to benchmark redemption rates with lower thresholds.
Step 5: Inspect customer reviews (get_customer_reviews) for price/menu sensitivity or value complaints.
Step 6: If spend friction is substantiated, test allowable lower thresholds (validate_proposal) and run retrospective historical replay (simulate_campaign_change).
Step 7: Synthesize findings into the final JSON report with 'TEST' or 'KEEP' recommendation."""
