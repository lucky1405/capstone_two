"""Custom application exceptions with explicit HTTP mapping."""
from typing import Optional, Any, Dict


class BillingException(Exception):
    """Base exception for billing domain."""
    status_code: int = 500
    error_code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(self, message: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}


class TenantNotFoundException(BillingException):
    status_code = 404
    error_code = "tenant_not_found"
    message = "Tenant does not exist."


class QuotaExceededException(BillingException):
    status_code = 429
    error_code = "quota_exceeded"
    message = "Monthly usage quota exceeded."

    def __init__(
        self,
        message: str,
        current_usage: int,
        limit: int,
        usage_type: str,
        retry_after: int = 60,
        reset_at: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            details={
                "current_usage": current_usage,
                "limit": limit,
                "usage_type": usage_type,
                "retry_after": retry_after,
                "reset_at": reset_at,
            },
        )
        self.retry_after = retry_after
        self.current_usage = current_usage
        self.limit = limit
        self.usage_type = usage_type
        self.reset_at = reset_at


class PaymentRequiredException(BillingException):
    status_code = 402
    error_code = "payment_required"
    message = "Active paid subscription required or payment is past due."

    def __init__(self, message: str, reason: str = "subscription_inactive", details: Optional[Dict[str, Any]] = None):
        d = details or {}
        d["reason"] = reason
        super().__init__(message=message, details=d)
        self.reason = reason


class IdempotencyConflictException(BillingException):
    status_code = 409
    error_code = "idempotency_conflict"
    message = "Idempotency key has already been used with a different request payload."


class InvalidSignatureException(BillingException):
    status_code = 400
    error_code = "invalid_signature"
    message = "Webhook cryptographic signature verification failed."


class BadRequestException(BillingException):
    status_code = 400
    error_code = "bad_request"
    message = "The request was invalid or malformed."
