"""Playbook R2: Sudden Velocity Collapse Investigation (>= 50% Drop Between Periods)."""
from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class R2VelocityDropPlaybook(BasePlaybook):
    """Specialized multi-branch investigation playbook for abrupt velocity drop alerts (Rule R2)."""

    rule_id: str = "R2"
    rule_name: str = "Sudden Velocity Collapse Investigation (>= 50% Drop Between Periods)"

    def get_playbook_guidance(self) -> str:
        return """### PLAYBOOK R2: SUDDEN VELOCITY COLLAPSE INVESTIGATION (>= 50% DROP BETWEEN PERIODS)
Trigger: Campaign redemption velocity collapsed by >= 50% in Period 2 compared to Period 1 baseline.
Primary Objective: Diagnose whether velocity collapse stems from external operational disruption, structural terms & policy non-compliance, or channel delivery breakdown.

Mandatory Investigation Steps:
1. Baseline Terms & Timing (Step 1):
   - Call `get_campaign_terms` to verify configured min_spend, cashback percentage, and policy allowlist compliance.
   - Call `get_campaign_performance` to confirm the exact date and magnitude of the velocity drop between Period 1 and Period 2.

2. Branch A — Physical / Operational Disruption (Primary Hypothesis):
   - Call `get_merchant_feedback` and `get_customer_reviews` around the drop date.
   - Look for store renovations, temporary closures, terminal outages, POS errors, or service quality drops.
   - If confirmed:
     - Operational disruption is SUPPORTED.
     - Synthesize recommendations:
       - Include `PAUSE_CAMPAIGN` (during closure) or `EXTEND_CAMPAIGN` (post-renovation).
       - Include `MERCHANT_ESCALATION` to notify account manager.
     - Record operational disruption in findings and red_flags. NEVER suggest passive KEEP.

3. Branch B — Policy Non-Compliance & Spend Threshold Exhaustion (Alternative Hypothesis):
   - If no physical closure is found:
     - Call `get_spend_distribution` to inspect typical ticket sizes.
     - Check if current campaign terms violate enterprise policy allowlists or if Period 1 redemptions exhausted a small cohort of high spenders, leaving regular shoppers unable to meet the threshold.
     - If terms non-compliance or threshold friction is identified:
       - Terms friction is SUPPORTED.
       - Call `validate_proposal` with an allowlisted compliant threshold (e.g. ₹1,000, ₹1,250, ₹1,500).
       - Call `simulate_campaign_change` to run historical replay and quantify qualification recovery.
       - Synthesize recommendations: Include `ADJUST_THRESHOLD` with validated parameters.

4. Branch C — Channel Delivery Failure (Alternative Hypothesis):
   - Call `get_delivery_metrics` to check if push notification delivery dropped in Period 2.
   - If delivery collapsed: Recommend `TARGETING_OVERHAUL`."""
