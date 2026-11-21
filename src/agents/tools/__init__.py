"""Pure agent tools package.

Contains only tools callable by LLM agents.
"""
from agents.tools.bigquery_tools import (
    get_campaign_terms,
    get_campaign_performance,
    get_spend_distribution,
    get_customer_reviews,
    get_merchant_feedback,
    get_delivery_metrics,
    get_comparable_campaigns,
    simulate_campaign_change,
)
from agents.tools.policy_tools import validate_proposal

ALL_TOOLS = [
    get_campaign_terms,
    get_campaign_performance,
    get_spend_distribution,
    get_customer_reviews,
    get_merchant_feedback,
    get_delivery_metrics,
    get_comparable_campaigns,
    validate_proposal,
    simulate_campaign_change,
]

__all__ = [
    "ALL_TOOLS",
    "get_campaign_terms",
    "get_campaign_performance",
    "get_spend_distribution",
    "get_customer_reviews",
    "get_merchant_feedback",
    "get_delivery_metrics",
    "get_comparable_campaigns",
    "simulate_campaign_change",
    "validate_proposal",
]
