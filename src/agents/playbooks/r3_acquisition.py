from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class PlaybookR3(BasePlaybook):
    """Playbook for Rule R3: Existing Customer Dominance in Acquisition Campaigns (>= 75%)."""

    rule_id: str = "R3"
    rule_name: str = "New-Customer Acquisition Cannibalization Investigation"

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY (RULE R3 - AUDIENCE TARGETING & CANNIBALIZATION):
Focus on audience targeting accuracy, geographical alignment, and regular visitor cannibalization:
Step 1: Check campaign terms (get_campaign_terms) to confirm campaign objective is 'ACQUIRE_NEW'.
Step 2: Inspect communication delivery metrics (get_delivery_metrics) to evaluate customer-outlet city mismatch percentage and channel delivery success.
Step 3: Analyze whether targeted customers live outside the merchant's operating city or whether audience criteria failed to filter out historical regulars.
Step 4: Check customer reviews (get_customer_reviews) and comparable peer campaigns (get_comparable_campaigns) for category acquisition benchmarks.
Step 5: If geographical targeting error or audience definition failure is identified, formulate the Targeting Mismatch Hypothesis and recommend 'INVESTIGATE' or 'TEST' with corrected audience criteria.
Step 6: Synthesize findings into the final JSON report with evidence citations."""
