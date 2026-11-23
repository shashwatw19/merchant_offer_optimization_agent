"""Playbook R1: Low Redemption Rate Investigation (< 5.0% Audience Engagement)."""
from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class R1ThresholdPlaybook(BasePlaybook):
    """Specialized multi-branch investigation playbook for low redemption rate alerts (Rule R1)."""

    rule_id: str = "R1"
    rule_name: str = "Low Redemption Rate Investigation (< 5.0% Audience Engagement)"

    def get_playbook_guidance(self) -> str:
        return """### PLAYBOOK R1: LOW REDEMPTION RATE INVESTIGATION (< 5.0% AUDIENCE ENGAGEMENT)
Trigger: Less than 5.0% of targeted customer cohort redeemed cashback.
Primary Objective: Diagnose whether low redemption stems from spend threshold friction, audience targeting/delivery breakdown, or merchant service quality failure.

Mandatory Investigation Steps:
1. Baseline Terms & Scope (Step 1):
   - Call `get_campaign_terms` to verify configured min_spend, cashback percentage, and policy allowlist compliance.
   - Call `get_campaign_performance` to confirm audience size and redemption percentage.

2. Branch A — Spend Threshold Friction (Primary Hypothesis):
   - Call `get_spend_distribution` to inspect merchant ticket sizes (median spend, p25, p50, p75).
   - If median spend is significantly below min_spend (e.g. median ₹750 vs threshold ₹2,000):
     - Spend threshold friction is SUPPORTED.
     - Call `get_comparable_campaigns` to benchmark peer merchants in the same category.
     - Call `validate_proposal` with an allowlisted lower threshold (e.g. ₹1,000, ₹1,250, or ₹1,500).
     - Call `simulate_campaign_change` to run retrospective historical replay on targeted transactions.
     - Synthesize recommendations: Include `ADJUST_THRESHOLD` with validated parameters and `MONITOR_VELOCITY`.

3. Branch B — Channel Delivery & Geographical Targeting Failure (Alternative Hypothesis):
   - If median spend is already near or above min_spend (spend friction is REFUTED):
     - Call `get_delivery_metrics` to inspect push notification delivery success and city alignment.
     - If delivery rate < 50% or customer-to-merchant city mismatch is high:
       - Targeting/delivery failure is SUPPORTED.
       - Synthesize recommendations: Include `TARGETING_OVERHAUL` to fix geofencing and re-syndicate audience.

4. Branch C — Customer Sentiment & Service Quality (Alternative Hypothesis):
   - Call `get_customer_reviews` and `get_merchant_feedback`.
   - If severe negative customer complaints exist (e.g. hygiene, billing, food quality):
     - Recommend `MERCHANT_ESCALATION` to notify relationship manager before altering terms.
     - Record operational red flags. NEVER suggest passive KEEP."""
