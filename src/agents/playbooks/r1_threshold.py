from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class PlaybookR1(BasePlaybook):
    """Playbook for Rule R1: Low Redemption Rate (< 5% of targeted customer audience)."""

    rule_id: str = "R1"
    rule_name: str = "Low Redemption Rate Investigation"

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY (RULE R1 - LOW REDEMPTION / SPEND THRESHOLD FRICTION):
Primary Objective: Diagnose whether the campaign minimum spend threshold creates an unnatural spending barrier relative to typical customer ticket size.
Step 1: Retrieve campaign terms (get_campaign_terms) and baseline performance (get_campaign_performance) to establish the low redemption baseline.
Step 2: Inspect merchant card payment history (get_spend_distribution) to determine median ticket size and spend distribution.
Step 3: Compare median ticket size against configured minimum spend threshold. If minimum spend is substantially higher than median spend (e.g. ₹2000 vs ₹850), formulate the Spend Friction Hypothesis.
Step 4: Inspect dated customer reviews (get_customer_reviews) and merchant relationship notes (get_merchant_feedback) to verify whether customer sentiment mentions high prices/bills and confirm no operational disruptions occurred.
Step 5: Check peer campaign benchmarks in the category (get_comparable_campaigns) to confirm peer redemption rates under lower thresholds.
Step 6: If spend friction is substantiated, test allowable lower thresholds with validate_proposal and evaluate with simulate_campaign_change.
Step 7: Propose 'TEST' with recommended threshold (or 'KEEP' if threshold matches normal spend) and synthesize into the final JSON report."""

    def get_investigation_mandate(self) -> str:
        return """INVESTIGATION MANDATE (RULE R1):
1. Retrieve campaign terms and baseline performance (get_campaign_terms, get_campaign_performance).
2. Retrieve merchant spend distribution (get_spend_distribution) to analyze customer ticket size against minimum spend.
3. Retrieve customer reviews (get_customer_reviews) and merchant feedback (get_merchant_feedback) to verify pricing perception and rule out closures.
4. Retrieve comparable category benchmarks (get_comparable_campaigns).
5. If spend friction is present, call validate_proposal and simulate_campaign_change for allowable lower thresholds.
6. Recommend 'TEST' with recommended threshold or 'KEEP' if threshold is already well-calibrated.
7. Return a valid JSON InvestigationReport matching the output contract."""
