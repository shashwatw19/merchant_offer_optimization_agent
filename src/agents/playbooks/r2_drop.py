from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class PlaybookR2(BasePlaybook):
    """Playbook for Rule R2: Sudden Drop in Redemption Rate Between Comparable Periods."""

    rule_id: str = "R2"
    rule_name: str = "Sudden Velocity Drop Investigation"

    def get_investigation_methodology(self) -> str:
        return """INVESTIGATION METHODOLOGY (RULE R2 - OPERATIONAL DISRUPTION / VELOCITY COLLAPSE):
Primary Objective: Diagnose whether a sudden drop in redemptions was caused by external operational disruptions, physical venue status, stockouts, or delivery collapse.
Step 1: Check campaign baseline performance (get_campaign_performance) and terms (get_campaign_terms) to verify the velocity drop.
Step 2: Inspect merchant relationship feedback notes (get_merchant_feedback) for operational incidents: stockouts, delayed inventory shipments, renovations, store closures, chef/management changes, or power/POS outages.
Step 3: Inspect dated customer reviews (get_customer_reviews) specifically around the drop date for complaints about out-of-stock items, closed doors, declined vouchers, or degraded service.
Step 4: Check communication delivery metrics (get_delivery_metrics) to verify whether push notifications or SMS deliveries failed.
Step 5: CRITICAL POLICY CONSTRAINT:
   - If merchant feedback or customer reviews reveal an operational outage, stockout, or store closure:
     THE DROP IS OPERATIONAL, NOT CAUSED BY SPEND THRESHOLDS!
     You MUST NOT call validate_proposal or simulate_campaign_change.
     Spend threshold adjustments CANNOT resolve a stockout or closed store.
   - Formulate the Operational Disruption Hypothesis citing the feedback_id / review_id.
   - Propose 'MONITOR' (if inventory is in transit / reopening scheduled) or 'INVESTIGATE' (to coordinate with merchant operations).
Step 6: Synthesize verified facts and dated citations into the final JSON report."""

    def get_investigation_mandate(self) -> str:
        return """INVESTIGATION MANDATE (RULE R2):
1. Retrieve campaign performance (get_campaign_performance) and terms (get_campaign_terms).
2. Inspect merchant relationship feedback notes (get_merchant_feedback) for recorded operational incidents, stockouts, or closures.
3. Inspect dated customer reviews (get_customer_reviews) to corroborate operational issues or service disruptions.
4. Check communication delivery metrics (get_delivery_metrics) to confirm messaging delivery integrity.
5. STRICT NEGATIVE CONSTRAINT: Do NOT call validate_proposal or simulate_campaign_change if operational disruption, stockout, or store closure is detected. Changing minimum spend will not fix missing stock or a closed store.
6. Recommend 'MONITOR' or 'INVESTIGATE' with operational rationale.
7. Return a valid JSON InvestigationReport matching the output contract."""
