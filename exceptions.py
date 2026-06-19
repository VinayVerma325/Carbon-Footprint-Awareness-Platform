"""
Custom exception hierarchy for the CarbonWise platform.

Provides structured, domain-specific exceptions that map cleanly to HTTP
status codes and carry machine-readable error codes alongside human-readable
messages. This replaces scattered ``ValueError`` / ``Exception`` raises with
a single taxonomy that FastAPI error handlers can intercept uniformly.

Exception hierarchy::

    CarbonWiseError (base)
    ├── ValidationError          → 400
    ├── CalculationError         → 422
    ├── ResourceNotFoundError    → 404
    ├── ExternalServiceError     → 502
    └── DatabaseError            → 500
"""

from typing import Optional


class CarbonWiseError(Exception):
    """Base exception for all CarbonWise platform errors.

    Attributes:
        message: Human-readable description of the error.
        error_code: Machine-readable slug for programmatic handling.
        http_status: Suggested HTTP status code for API responses.
    """

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        *,
        error_code: str = "INTERNAL_ERROR",
        http_status: int = 500,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.http_status = http_status
        super().__init__(self.message)


class ValidationError(CarbonWiseError):
    """Raised when user-supplied input fails validation rules.

    Examples include negative kWh values, recycling rates outside [0, 1],
    or address strings exceeding maximum length.
    """

    def __init__(
        self,
        message: str = "Input validation failed.",
        *,
        error_code: str = "VALIDATION_ERROR",
        field: Optional[str] = None,
    ) -> None:
        self.field = field
        super().__init__(message, error_code=error_code, http_status=400)


class CalculationError(CarbonWiseError):
    """Raised when the carbon calculation engine encounters an unprocessable state.

    This covers scenarios where inputs pass validation but the computation
    itself cannot proceed (e.g. unknown transport mode with no fallback).
    """

    def __init__(
        self,
        message: str = "Carbon calculation could not be completed.",
        *,
        error_code: str = "CALCULATION_ERROR",
    ) -> None:
        super().__init__(message, error_code=error_code, http_status=422)


class ResourceNotFoundError(CarbonWiseError):
    """Raised when a requested resource (user, log entry, profile) does not exist."""

    def __init__(
        self,
        message: str = "Requested resource was not found.",
        *,
        error_code: str = "NOT_FOUND",
    ) -> None:
        super().__init__(message, error_code=error_code, http_status=404)


class ExternalServiceError(CarbonWiseError):
    """Raised when an external dependency (Google Routes API, Firestore) fails.

    The platform is designed to degrade gracefully, so this exception
    is typically caught internally and triggers a fallback path.
    """

    def __init__(
        self,
        message: str = "External service communication failed.",
        *,
        error_code: str = "EXTERNAL_SERVICE_ERROR",
        service_name: Optional[str] = None,
    ) -> None:
        self.service_name = service_name
        super().__init__(message, error_code=error_code, http_status=502)


class DatabaseError(CarbonWiseError):
    """Raised when the persistence layer (Firestore or local JSON) fails unexpectedly."""

    def __init__(
        self,
        message: str = "Database operation failed.",
        *,
        error_code: str = "DATABASE_ERROR",
    ) -> None:
        super().__init__(message, error_code=error_code, http_status=500)
