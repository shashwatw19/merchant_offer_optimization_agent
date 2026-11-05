from typing import Any, Dict
from domain.policy import PolicyValidator

_VALIDATOR = PolicyValidator()


def validate_proposal(
    proposed_min_spend: float,
    cashback_pct: float,
    cashback_cap: float,
) -> Dict[str, Any]:
    """Check a proposed campaign configuration against approved policy allowlists.

    Returns whether the spend threshold, cashback percentage, and cashback cap
    are permitted, along with a deterministic validation reason.
    
    Args:
        proposed_min_spend: The proposed minimum spend threshold in currency units (e.g., 1000, 1500, 2000).
        cashback_pct: The proposed cashback percentage (e.g., 10.0).
        cashback_cap: The proposed maximum cashback cap per transaction (e.g., 200.0).
        
    Returns:
        A dictionary with "allowed": bool and "reason": str.
    """
    return _VALIDATOR.validate_proposal(
        proposed_min_spend=proposed_min_spend,
        cashback_pct=cashback_pct,
        cashback_cap=cashback_cap,
    )
