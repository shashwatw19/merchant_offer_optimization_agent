from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class PlaybookR2(BasePlaybook):
    """Playbook for Rule R2: Sudden Drop in Redemption Rate Between Comparable Periods."""

    rule_id: str = "R2"
    rule_name: str = "Sudden Velocity Drop Investigation"

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY (RULE R2 - OPERATIONAL DISRUPTION / VELOCITY COLLAPSE):
Focus on operational continuity, physical venue status, and delivery interruptions:
Step 1: Check campaign baseline performance (get_campaign_performance) and terms (get_campaign_terms).
Step 2: Inspect merchant relationship feedback notes (get_merchant_feedback) for recorded operational incidents: renovation closures, chef/management changes, or staffing shortages.
Step 3: Analyze communication delivery rates (get_delivery_metrics) to verify whether channel deliverability plummeted in the second half.
Step 4: Check dated customer reviews (get_customer_reviews) for sudden quality complaints, temporary service disruptions, or closure mentions.
Step 5: Do NOT propose spend threshold adjustments if venue was closed or delivery failed. If operational disruption is confirmed, propose 'MONITOR' or 'INVESTIGATE' with rationale.
Step 6: Synthesize findings into the final JSON report with dated evidence citations."""
