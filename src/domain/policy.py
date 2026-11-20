from typing import Any, Dict, Optional
from core.config import get_config
from core.logging import logger


class PolicyValidator:
    """Validates proposed campaign modifications against centralized policy rules."""

    def __init__(self, config=None):
        self.config = config or get_config()

    def validate_proposal(
        self,
        proposed_min_spend: float,
        cashback_pct: float,
        cashback_cap: float,
        budget: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Validate proposed spend and cashback terms against allowable limits."""
        try:
            min_spend = float(proposed_min_spend)
            pct = float(cashback_pct)
            cap = float(cashback_cap)
        except (TypeError, ValueError) as exc:
            logger.warning(f"Invalid input types in policy validation: {exc}")
            return {
                "allowed": False,
                "reason": "Invalid input types - expected numeric values",
                "retryable": False,
            }

        if min_spend < 0 or pct < 0 or cap < 0:
            return {
                "allowed": False,
                "reason": "Thresholds and cashback values cannot be negative",
                "retryable": False,
            }

        allowed_thresholds = self.config.policy.allowed_thresholds
        if min_spend not in allowed_thresholds:
            return {
                "allowed": False,
                "reason": f"min_spend {min_spend} not in permitted thresholds: {allowed_thresholds}",
                "retryable": False,
            }

        configured_pct = self.config.policy.cashback_percent
        if pct != configured_pct:
            return {
                "allowed": False,
                "reason": f"cashback_pct {pct}% does not match fixed campaign policy ({configured_pct}%)",
                "retryable": False,
            }

        configured_cap = self.config.policy.cashback_cap
        if cap != configured_cap:
            return {
                "allowed": False,
                "reason": f"cashback_cap {cap} does not match fixed campaign policy ({configured_cap})",
                "retryable": False,
            }

        if budget is not None:
            ceiling = self.config.policy.budget_ceiling
            if float(budget) > ceiling:
                return {
                    "allowed": False,
                    "reason": f"Campaign budget {budget} exceeds global budget ceiling {ceiling}",
                    "retryable": False,
                }

        return {
            "allowed": True,
            "reason": "Proposal satisfies all business policy constraints",
            "retryable": False,
        }
