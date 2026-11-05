from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

def validate_proposal(proposed_min_spend: float, cashback_pct: float, cashback_cap: float) -> Dict[str, Any]:
    """Check a proposed campaign configuration against the approved allowlists.

    Returns whether the spend threshold, cashback percentage, and cashback cap
    are permitted, along with a short reason.
    
    Args:
        proposed_min_spend: The proposed minimum spend threshold.
        cashback_pct: The proposed cashback percentage.
        cashback_cap: The proposed cashback cap amount.
        
    Returns:
        A dictionary with allowed status and reason, or error details.
    """
    try:
        # Input validation
        proposed_min_spend = float(proposed_min_spend)
        cashback_pct = float(cashback_pct)
        cashback_cap = float(cashback_cap)
        
        if proposed_min_spend < 0 or cashback_pct < 0 or cashback_cap < 0:
            print(f"Negative values in validate_proposal: min_spend={proposed_min_spend}, pct={cashback_pct}, cap={cashback_cap}")
            return {
                "allowed": False,
                "reason": "Values cannot be negative",
                "retryable": False
            }
        
        allowed_min_spends = [1000, 1500, 2000]
        allowed_cashback_pct = [10]
        allowed_cashback_cap = [200]

        if proposed_min_spend not in allowed_min_spends:
            print(f"min_spend {proposed_min_spend} not in allowlist: {allowed_min_spends}")
            return {
                "allowed": False,
                "reason": "min_spend not in allowlist",
                "retryable": False
            }

        if cashback_pct not in allowed_cashback_pct:
            print(f"cashback_pct {cashback_pct} not in allowlist: {allowed_cashback_pct}")
            return {
                "allowed": False,
                "reason": "cashback_pct not in allowlist",
                "retryable": False
            }

        if cashback_cap not in allowed_cashback_cap:
            print(f"cashback_cap {cashback_cap} not in allowlist: {allowed_cashback_cap}")
            return {
                "allowed": False,
                "reason": "cashback_cap not in allowlist",
                "retryable": False
            }

        return {
            "allowed": True,
            "reason": "proposal passes policy validation",
            "retryable": False
        }
        
    except (TypeError, ValueError) as e:
        print(f"Invalid input types in validate_proposal: min_spend={proposed_min_spend}, pct={cashback_pct}, cap={cashback_cap}: {e}")
        return {
            "error": "Invalid input types - expected numeric values",
            "retryable": False
        }
        
    except Exception as e:
        print(f"Error in validate_proposal(min_spend={proposed_min_spend}, pct={cashback_pct}, cap={cashback_cap}): {e}")
        return {
            "error": f"Unexpected error during proposal validation: {str(e)}",
            "retryable": True
        }