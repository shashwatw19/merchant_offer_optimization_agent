"""Playbook R3: Acquisition Cannibalization Investigation (>= 75% Existing Customers)."""
from typing import Any, Dict
from agents.playbooks.base import BasePlaybook


class R3AcquisitionPlaybook(BasePlaybook):
    """Specialized investigation playbook for new-customer acquisition cannibalization alerts (Rule R3)."""

    rule_id: str = "R3"
    rule_name: str = "Acquisition Cannibalization Investigation (>= 75% Existing Customers)"

    def get_playbook_guidance(self) -> str:
        return """### PLAYBOOK R3: ACQUISITION CANNIBALIZATION INVESTIGATION (>= 75% EXISTING CUSTOMERS)
Trigger: New-customer acquisition campaign is dominated (>= 75%) by pre-existing shoppers.
Primary Objective: Identify targeting mismatch, poor audience filtering, or geographic misalignment.

Investigation Steps:
1. Call `get_campaign_terms` to verify objective = 'ACQUIRE_NEW'.
2. Call `get_delivery_metrics` to check geographic city mismatch between customer home locations and merchant outlets.
   - High city mismatch indicates faulty geofencing or audience syndication error.
3. Call `get_customer_reviews` and `get_merchant_feedback` to inspect whether existing loyalists claimed codes in-store.
4. Synthesize `recommendations` array:
   - Include `TARGETING_OVERHAUL` with strict first-time shopper exclusion lists.
   - Include `MERCHANT_ESCALATION` if in-store staff are applying codes universally regardless of new-customer status."""
