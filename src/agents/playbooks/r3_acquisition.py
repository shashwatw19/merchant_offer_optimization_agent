from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class PlaybookR3(BasePlaybook):
    """Playbook for Rule R3: Existing Customer Dominance in Acquisition Campaigns (>= 75%)."""

    rule_id: str = "R3"
    rule_name: str = "New-Customer Acquisition Cannibalization Investigation"

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY (RULE R3 - AUDIENCE TARGETING & CANNIBALIZATION):
Primary Objective: Diagnose why an ACQUIRE_NEW campaign is being dominated by existing regular customers (>= 75% redemptions) instead of acquiring new-to-merchant customers.
Step 1: Check campaign terms (get_campaign_terms) to confirm campaign objective is 'ACQUIRE_NEW'.
Step 2: Check communication delivery metrics (get_delivery_metrics) to evaluate:
   - Percentage of targeted customers residing outside the merchant's operating city (city_mismatch_pct).
   - Delivery rate and failed deliveries.
Step 3: Inspect merchant relationship feedback notes (get_merchant_feedback) and customer reviews (get_customer_reviews) for feedback on customer footfall (e.g. merchant noting offer reaches established customers, or promotion visibility issues).
Step 4: Check comparable peer campaigns (get_comparable_campaigns) to benchmark typical acquisition rates in the merchant category.
Step 5: CRITICAL POLICY CONSTRAINT:
   - If delivery metrics show high geographical mismatch (e.g. city_mismatch_pct > 20%) or audience selection targeted historical patrons:
     THE ROOT CAUSE IS AUDIENCE TARGETING MISALLOCATION, NOT SPEND THRESHOLDS!
     You MUST NOT call validate_proposal or simulate_campaign_change for minimum spend adjustments.
     Modifying minimum spend does NOT fix sending offers to people in the wrong city or existing regulars!
   - Formulate the Targeting Mismatch Hypothesis citing delivery metrics and feedback.
   - Propose 'INVESTIGATE' (marketing platform audience reconfiguration) or 'TEST' (targeted pilot with strict city boundary filter and exclusion of existing customers).
Step 6: Synthesize verified facts and targeting evidence into the final JSON report."""

    def get_investigation_mandate(self) -> str:
        return """INVESTIGATION MANDATE (RULE R3):
1. Retrieve campaign terms (get_campaign_terms) to verify objective is 'ACQUIRE_NEW'.
2. Retrieve delivery metrics (get_delivery_metrics) to inspect city mismatch percentage and geographical targeting errors.
3. Retrieve merchant relationship feedback (get_merchant_feedback) and customer reviews (get_customer_reviews) regarding footfall composition.
4. Retrieve comparable category campaigns (get_comparable_campaigns) for acquisition benchmarks.
5. STRICT NEGATIVE CONSTRAINT: Do NOT call validate_proposal or simulate_campaign_change for spend adjustments when geographical or audience targeting error is identified. Changing minimum spend will not fix targeting customers in the wrong city.
6. Recommend 'INVESTIGATE' (re-segment targeting audience in marketing platform) or 'TEST' (geo-fenced audience pilot excluding existing customers).
7. Return a valid JSON InvestigationReport matching the output contract."""
