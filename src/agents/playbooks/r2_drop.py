"""Playbook R2: Sudden Velocity Collapse Investigation (>= 50% Drop Between Periods)."""
from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class R2VelocityDropPlaybook(BasePlaybook):
    """Specialized investigation playbook for abrupt velocity drop alerts (Rule R2)."""

    rule_id: str = "R2"
    rule_name: str = "Sudden Velocity Collapse Investigation (>= 50% Drop Between Periods)"

    def get_playbook_guidance(self) -> str:
        return """### PLAYBOOK R2: SUDDEN VELOCITY COLLAPSE INVESTIGATION (>= 50% DROP BETWEEN PERIODS)
Trigger: Campaign redemption velocity collapsed by >= 50% in the second half compared to the first half baseline.
Primary Objective: Identify external operational disruptions, merchant incidents, or store renovations.

Investigation Steps:
1. Call `get_campaign_performance` to confirm the timing and magnitude of the drop.
2. Call `get_merchant_feedback` to check relationship manager logs and operational notes.
   - Look for store renovations, temporary closures, terminal outages, or POS issues.
3. Call `get_customer_reviews` to inspect sentiment shifts or service complaints around the drop date.
4. Call `get_delivery_metrics` to check if push notification delivery dropped in Period 2.
5. If store renovation or operational pause is discovered:
   - Synthesize `recommendations` array:
     - Include `PAUSE_CAMPAIGN` or `EXTEND_CAMPAIGN` post-renovation.
     - Include `MERCHANT_ESCALATION` to notify account manager.
   - Ensure `red_flags` records the operational disruption.
   - NEVER suggest passive KEEP without addressing the physical cause."""
