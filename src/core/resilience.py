from typing import Any, Dict, Optional
from google.api_core.exceptions import (
    BadGateway,
    DeadlineExceeded,
    GatewayTimeout,
    InternalServerError,
    ServiceUnavailable,
    TooManyRequests,
)

from core.config import get_config
from core.exceptions import DatabaseError
from core.logging import logger

TRANSIENT_EXCEPTIONS = (
    ServiceUnavailable,
    TooManyRequests,
    InternalServerError,
    GatewayTimeout,
    DeadlineExceeded,
    BadGateway,
    TimeoutError,
    ConnectionError,
    OSError,
)


def classify_error(exc: Exception) -> bool:
    """Check if an error is transient (network/timeout) or permanent."""
    if isinstance(exc, TRANSIENT_EXCEPTIONS):
        return True
    if isinstance(exc, DatabaseError):
        return getattr(exc, "is_transient", False) or getattr(exc, "retryable", False)
    return False


def format_tool_error(
    tool_name: str,
    exc: Exception,
    error_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Format tool failure with clean diagnostic metadata for the LLM."""
    config = get_config()
    max_attempts = getattr(config.resilience, "max_retry_count", 2)
    is_transient = classify_error(exc)

    prefix = error_prefix or f"Failed executing '{tool_name}'"
    attempts_made = getattr(exc, "attempts_made", max_attempts if is_transient else 1)
    error_type = "INFRASTRUCTURE_UNAVAILABLE" if is_transient else "PERMANENT_DATA_ERROR"

    if is_transient:
        suggested_action = (
            f"Database client already retried {attempts_made} time(s) with backoff and failed. "
            "Do NOT retry this tool. Proceed with alternative tools and report this metric as unverified."
        )
    else:
        suggested_action = (
            "Permanent query, schema, or missing record error. Do NOT retry with the same arguments. "
            "Acknowledge the missing data and continue investigating with available evidence."
        )

    logger.warning(f"Tool '{tool_name}' failed ({error_type}, attempts={attempts_made}/{max_attempts}): {exc}")

    return {
        "success": False,
        "error": f"{prefix}: {str(exc)}",
        "error_type": error_type,
        "retryable": False,
        "attempts_made": attempts_made,
        "max_attempts": max_attempts,
        "remaining_attempts": 0,
        "suggested_action": suggested_action,
    }
