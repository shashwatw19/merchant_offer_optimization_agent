"""Playbook R1: Low Redemption Rate Investigation (< 5.0% Audience Engagement)."""
from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class R1ThresholdPlaybook(BasePlaybook):
    """Specialized investigation playbook for low redemption rate friction alerts (Rule R1)."""

    rule_id: str = "R1"
    rule_name: str = "Low Redemption Rate Investigation (< 5.0% Audience Engagement)"

    def get_playbook_guidance(self) -> str:
        return """### PLAYBOOK R1: LOW REDEMPTION RATE INVESTIGATION (< 5.0% AUDIENCE ENGAGEMENT)
Trigger: Less than 5.0% of targeted customer cohort redeemed cashback.
Primary Objective: Identify whether minimum spend threshold creates restrictive friction.

Investigation Steps:
1. Call `get_campaign_terms` to identify configured min_spend (e.g. ₹2,000) and cashback percentage.
2. Call `get_spend_distribution` to inspect merchant ticket sizes (median spend, p25, p50, p75).
   - If median spend is significantly below min_spend (e.g. median ₹750 vs threshold ₹2,000), threshold friction is SUPPORTED.
3. Call `get_comparable_campaigns` to benchmark peer merchants in the same category.
4. If threshold friction is confirmed:
   - Call `validate_proposal` with an allowlisted lower threshold (e.g. ₹1,000, ₹1,250, or ₹1,500).
   - Call `simulate_campaign_change` to run a retrospective historical replay strictly on targeted card payments.
5. Synthesize `recommendations` array:
   - Include `ADJUST_THRESHOLD` with parameter_changes: `{'min_spend': proposed_val}`.
   - Include `MONITOR_VELOCITY` as a secondary tracking action."""
