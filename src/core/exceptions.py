"""Custom exception hierarchy for Merchant Offer Optimization Agent."""


class OfferOptimizationError(Exception):
    """Base exception for all offer optimization errors."""
    pass


class ConfigurationError(OfferOptimizationError):
    """Raised when configuration is invalid or missing."""
    pass


class PolicyViolationError(OfferOptimizationError):
    """Raised when a campaign proposal violates policy constraints."""
    pass


class DatabaseError(OfferOptimizationError):
    """Raised when BigQuery interaction fails."""
    def __init__(
        self,
        message: str,
        retryable: bool = False,
        query: str = None,
        attempts_made: int = 1,
        is_transient: bool = False,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.query = query
        self.attempts_made = attempts_made
        self.is_transient = is_transient


class ToolExecutionError(OfferOptimizationError):
    """Raised when an agent tool fails to execute."""
    def __init__(self, tool_name: str, message: str, retryable: bool = False):
        super().__init__(f"Tool '{tool_name}' failed: {message}")
        self.tool_name = tool_name
        self.retryable = retryable


class ReportValidationError(OfferOptimizationError):
    """Raised when agent output cannot be parsed into a valid InvestigationReport."""
    pass


class StorageError(OfferOptimizationError):
    """Raised when cloud or local storage operations fail."""
    def __init__(
        self,
        message: str,
        retryable: bool = False,
        is_transient: bool = False,
        attempts_made: int = 1,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.is_transient = is_transient
        self.attempts_made = attempts_made


class ReportRenderingError(OfferOptimizationError):
    """Raised when report rendering or transformation fails."""
    pass
