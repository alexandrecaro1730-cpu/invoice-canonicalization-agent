"""Business objective: provide explicit failure categories for safe operational handling.

Technical description: defines typed exceptions used across ingestion, retrieval, model access, and reviews.
"""


class CanonicalizationError(Exception):
    """Base error for controlled application failures."""


class ValidationError(CanonicalizationError):
    """Raised when business input violates a documented contract."""


class DocumentExtractionError(CanonicalizationError):
    """Raised when an invoice cannot be safely converted into line items."""


class UnsupportedDocumentError(CanonicalizationError):
    """Raised when a supplied file type is not on the allow-list."""


class ProviderError(CanonicalizationError):
    """Raised when an external or fixture model provider violates its contract."""


class BudgetExceededError(CanonicalizationError):
    """Raised before a model call would exceed the configured budget."""


class ReviewNotFoundError(CanonicalizationError):
    """Raised when a requested human review does not exist for the tenant."""


class ReviewConflictError(CanonicalizationError):
    """Raised when a review has already been completed or has invalid approval data."""


class AuthenticationError(CanonicalizationError):
    """Raised when an API caller cannot be authenticated."""


class AuthorizationError(CanonicalizationError):
    """Raised when an authenticated caller requests another tenant or an unauthorized role."""
