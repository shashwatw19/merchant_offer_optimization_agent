"""Playbook R3: Acquisition Cannibalization Investigation (>= 75% Existing Customers)."""
from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class R3AcquisitionPlaybook(BasePlaybook):
    """Specialized multi-branch investigation playbook for acquisition cannibalization alerts (Rule R3)."""

    rule_id: str = "R3"
    rule_name: str = "Acquisition Cannibalization Investigation (>= 75% Existing Customers)"

    def get_playbook_guidance(self) -> str:
        return """### PLAYBOOK R3: ACQUISITION CANNIBALIZATION INVESTIGATION (>= 75% EXISTING CUSTOMERS)
Trigger: New-customer acquisition campaign is dominated (>= 75%) by pre-existing shoppers.
Primary Objective: Diagnose whether cannibalization is driven by audience filtering failure, in-store staff code misuse, or an excessively high trial barrier deterring first-time customers.

Mandatory Investigation Steps:
1. Baseline Terms & Scope (Step 1):
   - Call `get_campaign_terms` to verify objective = 'ACQUIRE_NEW' and examine active terms (`min_spend`, cashback percentage).
   - Call `get_campaign_performance` to review total redeemers vs existing customer count.

2. Branch A — Audience Targeting Leakage (Primary Hypothesis):
   - Call `get_delivery_metrics` to inspect audience filtering criteria and geographic city alignment.
   - Check whether known repeat customers were improperly included in the dispatch cohort.
   - If confirmed:
     - Audience leakage is SUPPORTED.
     - Synthesize recommendations: Include `TARGETING_OVERHAUL` with strict first-time shopper exclusion lists.

3. Branch B — High Trial Barrier & Terms Friction (Alternative Hypothesis):
   - Call `get_spend_distribution` to examine merchant ticket sizes.
   - If `min_spend` is set too high for a first-time trial customer (e.g. ₹2,000), new customers are deterred from taking a risk on an unfamiliar merchant, while existing loyalists readily claim the cashback.
   - If trial barrier friction is identified:
     - Trial barrier friction is SUPPORTED.
     - Formulate candidate entry threshold (e.g. ₹1,000 or ₹1,250).
     - Call `validate_proposal` to ensure policy compliance.
     - Call `simulate_campaign_change` to evaluate qualification recovery on non-redeemers.
     - Synthesize recommendations: Include `ADJUST_THRESHOLD` alongside `TARGETING_OVERHAUL`.

4. Branch C — In-Store Cashier Misuse & Staff Abuse (Alternative Hypothesis):
   - Call `get_customer_reviews` and `get_merchant_feedback` to check if in-store staff are applying codes universally at checkout for regular shoppers.
   - If confirmed: Include `MERCHANT_ESCALATION` to audit POS coupon validation and retrain merchant staff."""
