"""Pydantic schemas for boundary input validation and structured API responses."""
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator


class UsageRecordRequest(BaseModel):
    """Payload to record a billable usage event."""
    usage_type: Literal["api_call", "ai_tokens"] = Field(
        ..., description="The modality of usage being recorded."
    )
    quantity: int = Field(
        default=1, ge=1, description="Quantity of events or tokens to meter. Must be >= 1."
    )
    input_tokens: int = Field(
        default=0, ge=0, description="Fresh input prompt tokens."
    )
    cached_input_tokens: int = Field(
        default=0, ge=0, description="Discounted cached input tokens."
    )
    output_tokens: int = Field(
        default=0, ge=0, description="Standard model output completion tokens."
    )
    reasoning_tokens: int = Field(
        default=0, ge=0, description="Reasoning/thinking tokens (billed at output rate)."
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Arbitrary tracking metadata."
    )

    @field_validator("quantity")
    def validate_quantity_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Quantity must be at least 1.")
        return v


class UsageRecordResponse(BaseModel):
    """Result of a successfully metered usage event."""
    success: bool = True
    event_id: str
    tenant_id: str
    usage_type: str
    quantity: int
    cost_micro_units: int
    formatted_cost: str
    quota_used: int
    quota_limit: int
    quota_remaining: int
    idempotent_replay: bool = False


class GenerateRequest(BaseModel):
    """Simulated billable AI generation endpoint request."""
    prompt: str = Field(..., min_length=1, description="Input prompt for generation.")
    model: str = Field(default="gemini-2.5-flash", description="Target model identifier.")
    # Optional simulated token counts for deterministic testing
    input_tokens: Optional[int] = Field(default=None, ge=0)
    cached_input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0)


class GenerateResponse(BaseModel):
    """Response returned by the simulated billable generation endpoint."""
    status: str = "completed"
    completion: str
    tenant_id: str
    event_id: str
    token_usage: Dict[str, Any]
    cost: Dict[str, Any]
    quota: Dict[str, Any]
    idempotent_replay: bool = False


class TokenBreakdown(BaseModel):
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int


class UsageQuotaItem(BaseModel):
    used: int
    limit: int
    remaining: int
    percent_used: float


class UsageSummaryResponse(BaseModel):
    """Rollup of current billing cycle consumption and cost."""
    tenant_id: str
    tenant_name: str
    plan_id: str
    plan_name: str
    subscription_status: str
    current_period_start: str
    current_period_end: str
    api_calls: UsageQuotaItem
    ai_tokens: UsageQuotaItem
    token_breakdown: TokenBreakdown
    total_cost_micro_units: int
    formatted_total_cost: str


class CheckoutSessionRequest(BaseModel):
    """Initiates a Stripe Checkout session for plan upgrades."""
    plan_id: Literal["pro"] = "pro"
    success_url: Optional[str] = "https://example.com/checkout/success"
    cancel_url: Optional[str] = "https://example.com/checkout/cancel"


class CheckoutSessionResponse(BaseModel):
    """Stripe Checkout session URL and session identifiers."""
    session_id: str
    checkout_url: str
    tenant_id: str
    plan_id: str
    mode: str = "test"


class WebhookResponse(BaseModel):
    """Webhook handling confirmation."""
    status: str
    event_id: str
    message: Optional[str] = None
